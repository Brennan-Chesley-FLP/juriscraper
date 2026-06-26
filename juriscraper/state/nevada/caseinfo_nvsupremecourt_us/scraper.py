"""Nevada Appellate Courts Scraper.

Scrapes docket data from the Nevada Supreme Court (nev) and Nevada Court of
Appeals (nevapp) via the C-Track public CMS at caseinfo.nvsupremecourt.us.

Entry point: fetch_by_internal_id (SimpleSpeculation on csIID).
  The site uses a single shared csIID sequence across both courts; the
  court is determined from the docket number suffix (`-COA` -> nevapp).

Flow per case:
  1. parse_case_view       — original view: header + parties + docket
  2. parse_combined_view   — combined=true view: merges related-case
                              docket entries and tags them combined_only.
"""

from __future__ import annotations

import re
from datetime import date
from typing import TYPE_CHECKING, ClassVar
from urllib.parse import parse_qs, urlparse

from jkent.common.decorators import entry, step
from jkent.common.page_element import PageElement
from jkent.common.param_models import SpeculativeRange
from jkent.data_types import (
    BaseScraper,
    HttpMethod,
    HTTPRequestParams,
    ParsedData,
    Request,
    Response,
    ScraperStatus,
    XPath,
)
from pyrate_limiter import Duration, Rate

from juriscraper.state.common.ctrack import SOFT_404_MARKER, parse_mmddyyyy

from .models import (
    NvAttorney,
    NvDocket,
    NvDocketEntry,
    NvDocument,
    NvParty,
    NvRelatedCase,
    NvUnavailableCase,
)

if TYPE_CHECKING:
    from collections.abc import Generator

    from jkent.data_types import ScraperYield


BASE_URL = "https://caseinfo.nvsupremecourt.us"
CASE_VIEW_PATH = "/public/caseView.do"
DATE_RE = re.compile(r"^\d{1,2}/\d{1,2}/\d{4}$")


class NevadaScraper(BaseScraper[NvDocket | NvDocument | NvUnavailableCase]):
    """Scraper for Nevada Supreme Court and Nevada Court of Appeals.

    Speculative enumeration over the site-internal csIID. Each case is
    fetched in two views: the original (single-court) view and the
    combined view, which merges entries from the related case (the other
    court's proceedings). Entries that only appear in the combined view
    are tagged ``combined_only=True``.

    Yields three record types:

    - ``NvDocket`` — one per viewable case, with nested entries/parties.
    - ``NvDocument`` — one per archived docket-entry document, joinable
      back to the parent docket via ``internal_id`` (csIID).
    - ``NvUnavailableCase`` — one per csIID whose page returns the
      "rights to view" error (sealed cases and truly-invalid ids are
      indistinguishable from the site's response).
    """

    court_ids: ClassVar[set[str]] = {"nev", "nevapp"}
    court_url: ClassVar[str] = f"{BASE_URL}/"
    data_types: ClassVar[set[str]] = {"dockets"}
    status: ClassVar[ScraperStatus] = ScraperStatus.IN_DEVELOPMENT
    version: ClassVar[str] = "2026-05-05"
    requires_auth: ClassVar[bool] = False
    rate_limits: ClassVar[list[Rate] | None] = [Rate(2, Duration.SECOND)]

    # =========================================================================
    # Soft-404
    # =========================================================================

    def fails_successfully(self, response: Response) -> bool:
        """Return False for invalid/out-of-range csIIDs.

        The site returns HTTP 200 with a "Security Error" page body for any
        csIID the user cannot view (including non-existent ones).
        """
        return SOFT_404_MARKER not in (response.text or "")

    # =========================================================================
    # Entry point
    # =========================================================================

    # highest_observed=74595, largest_observed_gap=20 (2026-04-16)
    @entry(NvDocket)
    def fetch_by_internal_id(self, rid: SpeculativeRange) -> Request:
        """Fetch a docket by internal csIID.

        csIIDs are continuous sequential integers shared between the Nevada
        Supreme Court and the Nevada Court of Appeals. The sequence starts
        at 1; the court is determined from the docket number on the page.
        """
        csiid = rid.min
        url = f"{BASE_URL}{CASE_VIEW_PATH}?csIID={csiid}"
        return Request(
            request=HTTPRequestParams(method=HttpMethod.GET, url=url),
            continuation=self.parse_case_view,
            accumulated_data={"internal_id": csiid},
            deduplication_key=f"nv-{csiid}",
        )

    # =========================================================================
    # Step 1: original case view
    # =========================================================================

    @step()
    def parse_case_view(
        self,
        page: PageElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[NvDocket], None, None]:
        """Parse the single-court case view, then fetch the combined view.

        When the site renders the "rights to view" page (sealed case or
        truly-invalid csIID), a single ``NvUnavailableCase`` record is yielded
        and no follow-ups are scheduled. ``fails_successfully`` still
        returns False for this page so the driver's speculation tracker
        counts it as a miss.
        """
        internal_id = int(accumulated_data["internal_id"])

        if SOFT_404_MARKER in (response.text or ""):
            yield ParsedData(
                data=NvUnavailableCase(
                    internal_id=internal_id,
                    source_url=response.url,
                )
            )
            return

        docket_number = self._extract_docket_number(page)
        if docket_number is None:
            return

        court_id = "nevapp" if docket_number.endswith("-COA") else "nev"

        header = self._parse_info_header(page)
        parties = self._parse_parties(page)
        related_cases = self._parse_related_cases(page)
        entries = self._parse_docket_entries(page, combined_only=False)

        lower_court = header.get("Lower Court Case(s):")

        docket = NvDocket(
            docket_number=docket_number,
            court_id=court_id,
            internal_id=internal_id,
            case_name=header.get("Short Caption:") or "",
            date_filed=self._earliest_entry_date(entries),
            classification=header.get("Classification:") or None,
            case_status=header.get("Case Status:") or None,
            disqualifications=header.get("Disqualifications:") or None,
            replacement=header.get("Replacement:") or None,
            panel_assigned=header.get("Panel Assigned:") or None,
            to_sp_judge=header.get("To SP/Judge:") or None,
            sp_status=header.get("SP Status:") or None,
            oral_argument=header.get("Oral Argument:") or None,
            oral_argument_location=header.get("Oral Argument Location:")
            or None,
            submission_date=header.get("Submission Date:") or None,
            how_submitted=header.get("How Submitted:") or None,
            lower_court_cases=[lower_court] if lower_court else [],
            related_cases=related_cases,
            parties=parties,
            entries=entries,
            source_url=response.url,
        )

        yield from self._archive_entry_documents(entries, internal_id)

        entry_keys = [list(self._entry_key(e)) for e in entries]
        combined_url = (
            f"{BASE_URL}{CASE_VIEW_PATH}?csIID={internal_id}&combined=true"
        )
        yield Request(
            request=HTTPRequestParams(method=HttpMethod.GET, url=combined_url),
            continuation=self.parse_combined_view,
            accumulated_data={
                "docket_data": docket.model_dump(mode="json"),
                "original_entry_keys": entry_keys,
            },
            deduplication_key=f"nv-{internal_id}-combined",
        )

    # =========================================================================
    # Step 2: combined case view
    # =========================================================================

    @step(priority=8)
    def parse_combined_view(
        self,
        page: PageElement,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[NvDocket], None, None]:
        """Append combined-only entries and yield the final docket."""
        docket = NvDocket.model_validate(accumulated_data["docket_data"])
        seen = {tuple(k) for k in accumulated_data["original_entry_keys"]}

        combined_entries = self._parse_docket_entries(page, combined_only=True)
        new_entries: list[NvDocketEntry] = []
        for docket_entry in combined_entries:
            if self._entry_key(docket_entry) in seen:
                continue
            docket.entries.append(docket_entry)
            new_entries.append(docket_entry)

        if docket.date_filed is None:
            docket.date_filed = self._earliest_entry_date(docket.entries)

        yield from self._archive_entry_documents(
            new_entries, docket.internal_id
        )

        yield ParsedData(data=docket)

    # =========================================================================
    # Step 3: archived document records
    # =========================================================================

    @step()
    def download_document(
        self,
        local_filepath: str | None,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[NvDocument], None, None]:
        """Yield an NvDocument record after the driver archives a file.

        ``accumulated_data`` carries the csIID and the document metadata
        captured at the parse step so the record can be joined back to the
        parent NvDocket later.
        """
        date_raw = accumulated_data.get("date_filed")
        yield ParsedData(
            data=NvDocument(
                internal_id=int(accumulated_data["internal_id"]),
                document_number=accumulated_data["document_number"],
                document_url=accumulated_data["document_url"],
                date_filed=date.fromisoformat(date_raw) if date_raw else None,
                entry_type=accumulated_data.get("entry_type"),
                description=accumulated_data.get("description"),
                local_path=local_filepath,
            )
        )

    # =========================================================================
    # Archive request helper
    # =========================================================================

    def _archive_entry_documents(
        self, entries: list[NvDocketEntry], internal_id: int
    ) -> Generator[Request, None, None]:
        """Yield one archive Request per entry that has a document URL.

        Uses the document URL as the deduplication key so overlapping
        runs (e.g. same doc linked from original and combined views of a
        sibling case) do not re-download.
        """
        for docket_entry in entries:
            if (
                not docket_entry.document_url
                or not docket_entry.document_number
            ):
                continue
            yield Request(
                archive=True,
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url=docket_entry.document_url,
                    timeout=360.0,  # Longest successful download observed took 5.5 minutes.
                ),
                continuation=self.download_document,
                expected_type="pdf",
                accumulated_data={
                    "internal_id": internal_id,
                    "document_number": docket_entry.document_number,
                    "document_url": docket_entry.document_url,
                    "date_filed": (
                        docket_entry.date_filed.isoformat()
                        if docket_entry.date_filed
                        else None
                    ),
                    "entry_type": docket_entry.entry_type,
                    "description": docket_entry.description or None,
                },
                deduplication_key=f"nv-doc-{docket_entry.document_number}",
            )

    # =========================================================================
    # Parsing helpers
    # =========================================================================

    def _extract_docket_number(self, page: PageElement) -> str | None:
        """Read the docket number from the 'Case Information: X' title cell."""
        title_cells = page.query(
            XPath(
                "//td[starts-with(normalize-space(.), 'Case Information:')"
                " or starts-with(normalize-space(.), 'Combined Case Information:')]"
            ),
            "case information title",
            min_count=0,
            max_count=1,
        )
        if title_cells:
            text = self._text(title_cells[0])
            match = re.search(r"Information:\s*([^&]+?)(?:\s*&|$)", text)
            if match:
                return match.group(1).strip()
        # Fallback via <title>: "92415-COA: Case View" or "92415-COA & 92415: ..."
        titles = page.query_strings(
            XPath("//title/text()"), "page title", min_count=0, max_count=1
        )
        if titles:
            match = re.match(r"^\s*([A-Za-z0-9\-]+)\s*[:&]", titles[0])
            if match:
                return match.group(1).strip()
        return None

    def _parse_info_header(self, page: PageElement) -> dict[str, str]:
        """Parse the Case Information header rows into a label->value map.

        Rows in the header table alternate (label, value, label, value). A
        label cell's text ends with ':'.
        """
        result: dict[str, str] = {}
        caption_cells = page.query(
            XPath("//td[normalize-space(.)='Short Caption:']"),
            "Short Caption label",
            min_count=0,
            max_count=1,
        )
        if not caption_cells:
            return result
        table_rows = caption_cells[0].query(
            XPath("./ancestor::table[1]//tr"), "info table rows", min_count=0
        )
        for row in table_rows:
            cells = row.query(XPath("./td"), "info row cells", min_count=0)
            for i in range(0, len(cells) - 1, 2):
                label = self._text(cells[i])
                if not label.endswith(":"):
                    continue
                value = self._text(cells[i + 1])
                if value and label not in result:
                    result[label] = value
        return result

    def _parse_parties(self, page: PageElement) -> list[NvParty]:
        """Parse the Party Information table when rows are present in HTML."""
        parties: list[NvParty] = []
        role_headers = page.query(
            XPath("//td[normalize-space(.)='Role']"),
            "Party Role header",
            min_count=0,
            max_count=1,
        )
        if not role_headers:
            return parties
        header_rows = role_headers[0].query(
            XPath("./ancestor::tr[1]"),
            "party header row",
            min_count=1,
            max_count=1,
        )
        if not header_rows:
            return parties
        data_rows = header_rows[0].query(
            XPath("./following-sibling::tr"),
            "party data rows",
            min_count=0,
        )
        for row in data_rows:
            cells = row.query(XPath("./td"), "party cells", min_count=0)
            if len(cells) < 3:
                continue
            role = self._text(cells[0])
            name = self._text(cells[1])
            if not name:
                continue
            attorneys = self._parse_attorneys(cells[2])
            parties.append(NvParty(name=name, role=role, attorneys=attorneys))
        return parties

    @staticmethod
    def _parse_attorneys(cell: PageElement) -> list[NvAttorney]:
        """Parse an attorney cell.

        Each attorney line looks like ``Name (Firm)``; multiple attorneys are
        separated by line breaks inside the cell.
        """
        raw = cell.text_content().strip() if cell else ""
        if not raw:
            return []
        result: list[NvAttorney] = []
        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue
            match = re.match(r"^(.*?)\s*\(([^)]*)\)\s*$", line)
            if match:
                result.append(
                    NvAttorney(
                        name=match.group(1).strip(),
                        firm=match.group(2).strip() or None,
                    )
                )
            else:
                result.append(NvAttorney(name=line))
        return result

    def _parse_related_cases(self, page: PageElement) -> list[NvRelatedCase]:
        """Parse related-case links from the header's 'Related Case(s):' row."""
        related: list[NvRelatedCase] = []
        label_cells = page.query(
            XPath("//td[normalize-space(.)='Related Case(s):']"),
            "Related Case(s) label",
            min_count=0,
            max_count=1,
        )
        if not label_cells:
            return related
        value_cells = label_cells[0].query(
            XPath("./following-sibling::td[1]"),
            "related cases value cell",
            min_count=0,
            max_count=1,
        )
        if not value_cells:
            return related
        links = value_cells[0].find_links(
            XPath(".//a"), "related case links", min_count=0
        )
        for link in links:
            docket_num = link.text.strip() if link.text else ""
            if not docket_num:
                continue
            related.append(
                NvRelatedCase(
                    docket_number=docket_num,
                    internal_id=self._extract_csiid(link.url),
                )
            )
        return related

    def _parse_docket_entries(
        self, page: PageElement, *, combined_only: bool
    ) -> list[NvDocketEntry]:
        """Parse the Docket Entries table rows.

        Title row: single cell 'Docket Entries'.
        Header row: Date | Type | Description | Pending? | Document.
        Data rows: 5 cells with a MM/DD/YYYY first cell.
        """
        entries: list[NvDocketEntry] = []
        title_cells = page.query(
            XPath("//td[normalize-space(.)='Docket Entries']"),
            "Docket Entries title",
            min_count=0,
            max_count=1,
        )
        if not title_cells:
            return entries
        title_rows = title_cells[0].query(
            XPath("./ancestor::tr[1]"),
            "Docket Entries title row",
            min_count=1,
            max_count=1,
        )
        data_rows = title_rows[0].query(
            XPath("./following-sibling::tr"), "docket rows", min_count=0
        )
        for row in data_rows:
            cells = row.query(XPath("./td"), "docket cells", min_count=0)
            if len(cells) < 5:
                continue
            date_text = self._text(cells[0])
            if not DATE_RE.match(date_text):
                continue
            doc_links = cells[4].find_links(
                XPath(".//a"), "docket doc link", min_count=0
            )
            doc_number = None
            doc_url = None
            if doc_links:
                doc_number = (doc_links[0].text or "").strip() or None
                doc_url = doc_links[0].url or None
            entries.append(
                NvDocketEntry(
                    date_filed=parse_mmddyyyy(date_text),
                    entry_type=self._text(cells[1]) or None,
                    description=self._text(cells[2]),
                    pending=self._text(cells[3]).upper() == "Y",
                    document_number=doc_number,
                    document_url=doc_url,
                    combined_only=combined_only,
                )
            )
        return entries

    # =========================================================================
    # Small utilities
    # =========================================================================

    @staticmethod
    def _entry_key(entry: NvDocketEntry) -> tuple[str, str, str]:
        return (
            entry.date_filed.isoformat() if entry.date_filed else "",
            entry.entry_type or "",
            entry.description or "",
        )

    @staticmethod
    def _earliest_entry_date(entries: list[NvDocketEntry]) -> date | None:
        dates = [e.date_filed for e in entries if e.date_filed]
        return min(dates) if dates else None

    @staticmethod
    def _text(element: PageElement | None) -> str:
        if element is None:
            return ""
        try:
            return element.text_content().strip()
        except Exception:
            return ""

    @staticmethod
    def _extract_csiid(href: str | None) -> int | None:
        if not href:
            return None
        try:
            values = parse_qs(urlparse(href).query).get("csIID")
        except ValueError:
            return None
        if not values:
            return None
        try:
            return int(values[0])
        except ValueError:
            return None
