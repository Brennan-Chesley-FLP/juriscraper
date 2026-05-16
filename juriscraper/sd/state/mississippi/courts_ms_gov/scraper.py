"""Mississippi Appellate Courts Scraper.

Pulls dockets from the unified ``courts.ms.gov/appellatecourts/docket/``
backend that serves both the Mississippi Supreme Court (``miss``) and the
Court of Appeals of Mississippi (``missctapp``).

The site exposes only an autocomplete search (capped at 7 results) and a
direct lookup by internal sequential ``case_num``. The scraper therefore
uses a single speculative entry over the unified ``case_num`` integer
space; the public docket number's ``-SCT`` / ``-COA`` suffix is parsed
from the response and used to assign ``court_id``.

Each case requires up to four detail fetches against ``build_docket.php``
(case + parties + trial-court + oral-args) which are chained via
``accumulated_data``. Every referenced PDF is yielded as an archive
Request resolved separately into ``MsAppDocument``.
"""

from __future__ import annotations

import re
from datetime import date
from typing import TYPE_CHECKING, ClassVar
from urllib.parse import urljoin

from jkent.common.decorators import entry, step
from jkent.common.param_models import SpeculativeRange
from jkent.data_types import (
    BaseScraper,
    HttpMethod,
    HTTPRequestParams,
    ParsedData,
    Request,
    Response,
    ScraperStatus,
)
from pyrate_limiter import Duration, Rate

from .models import (
    DEFAULT_COURT_ID,
    SUFFIX_TO_COURT_ID,
    MsAppAttorney,
    MsAppDocket,
    MsAppDocketEntry,
    MsAppDocument,
    MsAppOralArgument,
    MsAppParty,
    MsAppTrialCourt,
)

if TYPE_CHECKING:
    from collections.abc import Generator

    from jkent.common.page_element import PageElement
    from jkent.data_types import ScraperYield


BASE_URL = "https://courts.ms.gov"
INDEX_URL = f"{BASE_URL}/index.php"
BUILD_DOCKET_URL = f"{BASE_URL}/appellatecourts/docket/build_docket.php"

# Body sent for the docket / case header tab. ``limit=true`` caps the
# returned PDF metadata (without it we still get the full entry list, but
# the response can be ~5x larger for very long dockets).
DOCKET_BODY = "docket_type=docket&sortdir=desc&case_num={cn}&limit=true"
PARTIES_BODY = "docket_type=apinfo&case_num={cn}&listby=pty"
LCOURT_BODY = "docket_type=lcinfo&case_num={cn}"
ORALARG_BODY = "docket_type=oralarg&case_num={cn}"

XHR_HEADERS: dict[str, str] = {
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    "X-Requested-With": "XMLHttpRequest",
    "Referer": INDEX_URL,
}

# String present in the case-header response when the requested case_num
# is not assigned to any public case.
SOFT_404_NEEDLE = "No public results were found for your search"

# Public docket-number patterns. Modern: 4-digit year + suffix; legacy:
# 2-digit year, no suffix.
_DOCKET_RE_MODERN = re.compile(
    r"\b(\d{4})-([A-Z]{1,3})-(\d{4,5})-([A-Z]{2,3})\b"
)
_DOCKET_RE_LEGACY = re.compile(r"\b(\d{2})-([A-Z]{1,3})-(\d{4,5})\b")
_RULING_DATE_RE = re.compile(r"Ruling Date:\s*(\d{1,2}/\d{1,2}/\d{2,4})", re.I)
_TRIAL_CASE_RE = re.compile(r"Trial Court Case #\s*(.+?)\s*$")


class MississippiAppellateScraper(BaseScraper[MsAppDocket | MsAppDocument]):
    """Scraper for the Mississippi Supreme Court and Court of Appeals."""

    court_ids: ClassVar[set[str]] = {"miss", "missctapp"}
    court_url: ClassVar[str] = INDEX_URL
    data_types: ClassVar[set[str]] = {"dockets"}
    status: ClassVar[ScraperStatus] = ScraperStatus.IN_DEVELOPMENT
    version: ClassVar[str] = "2026-05-03"
    requires_auth: ClassVar[bool] = False
    rate_limits: ClassVar[list[Rate] | None] = [Rate(2, Duration.SECOND)]

    # =========================================================================
    # Soft-404
    # =========================================================================

    def fails_successfully(self, response: Response) -> bool:
        """Return ``False`` when the response is the public 'no case'
        page returned for unassigned ``case_num`` values."""
        return SOFT_404_NEEDLE not in response.text

    # =========================================================================
    # Entry point
    # =========================================================================

    @entry(MsAppDocket)
    def fetch_docket(self, case_num: SpeculativeRange) -> Request:
        """Speculative docket fetcher across the unified case-num space.

        ``case_num`` is the integer assigned at filing time, shared
        between the Supreme Court and the Court of Appeals; the
        scraper decides ``court_id`` after seeing the docket-number
        suffix on the response.
        """
        cn = case_num.min
        return Request(
            request=HTTPRequestParams(
                method=HttpMethod.POST,
                url=BUILD_DOCKET_URL,
                data=DOCKET_BODY.format(cn=cn),
                headers=XHR_HEADERS,
            ),
            continuation=self.parse_docket_page,
            accumulated_data={"case_num": cn},
            deduplication_key=f"ms-app-cn-{cn}",
        )

    # =========================================================================
    # Step 1: docket page (header + entries + PDF refs)
    # =========================================================================

    @step()
    def parse_docket_page(
        self,
        page: PageElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[MsAppDocument], None, None]:
        """Parse case header + docket entries and chain into parties tab.

        Yields a fresh archive Request for every referenced PDF, and a
        follow-on Request for the parties tab whose continuation will
        eventually emit the assembled ``MsAppDocket``.
        """
        cn = int(accumulated_data["case_num"])

        casenum_cells = page.query_xpath(
            "//td[@class='casenum']",
            "case header cell",
            min_count=1,
            max_count=1,
        )
        docket_number = _strip(casenum_cells[0].text_content())

        # Caption is the next text-bearing <td> after the casenum row;
        # rely on its distinctive font-size:18px style — the page only
        # has one such cell.
        caption_cells = page.query_xpath(
            "//td[contains(@style, 'font-size:18px') and contains(@style, 'font-weight:bold')]",
            "case caption cell",
            min_count=1,
            max_count=1,
        )
        case_name = _strip(caption_cells[0].text_content())

        # Docket entries: each <tr class="entry"> followed optionally
        # by a <tr class="dockpdf-N"> sibling for its PDF.
        entries: list[MsAppDocketEntry] = []
        documents: list[MsAppDocument] = []
        earliest_date: date | None = None

        entry_rows = page.query_xpath(
            "//tr[@class='entry']", "docket entry rows", min_count=0
        )
        for row in entry_rows:
            date_strs = row.query_xpath_strings(
                ".//td[@class='DATE']/text()",
                "entry date",
                min_count=0,
                max_count=1,
            )
            desc_cells = row.query_xpath(
                ".//td[contains(@class,'DESCRIPTION')]",
                "entry description cell",
                min_count=0,
                max_count=1,
            )
            if not desc_cells:
                continue
            description = _strip(desc_cells[0].text_content())
            entry_date = _parse_date(date_strs[0]) if date_strs else None
            if entry_date and (
                earliest_date is None or entry_date < earliest_date
            ):
                earliest_date = entry_date

            desc_id_attrs = desc_cells[0].query_xpath_strings(
                "./@id", "desc id", min_count=0, max_count=1
            )
            doc_idx = _parse_desc_index(
                desc_id_attrs[0] if desc_id_attrs else ""
            )

            entries.append(
                MsAppDocketEntry(
                    date_filed=entry_date,
                    description=description,
                    document_index=doc_idx,
                )
            )

        # PDF rows live as siblings: <tr class="dockpdf-N"> with one anchor.
        pdf_rows = page.query_xpath(
            "//tr[contains(@class,'dockpdf-')]",
            "pdf entry rows",
            min_count=0,
        )
        for pdf_row in pdf_rows:
            class_attr = (
                pdf_row.query_xpath_strings(
                    "./@class", "pdf class", min_count=0, max_count=1
                )
                or [""]
            )[0]
            doc_idx = _parse_desc_index(class_attr)

            anchors = pdf_row.query_xpath(
                ".//a[contains(@href, 'sendPDF.php')]",
                "pdf link",
                min_count=0,
                max_count=1,
            )
            if not anchors:
                continue
            href = (
                anchors[0].query_xpath_strings(
                    "./@href", "pdf href", min_count=1, max_count=1
                )
            )[0]
            file_param = _extract_file_param(href)
            description = _strip(anchors[0].text_content())
            download_url = urljoin(response.url, href)

            # Match back to the parent entry to inherit its date.
            parent_date: date | None = None
            if doc_idx is not None:
                for ent in entries:
                    if ent.document_index == doc_idx:
                        parent_date = ent.date_filed
                        break

            documents.append(
                MsAppDocument(
                    docket_number=docket_number,
                    case_num=cn,
                    file_name=file_param,
                    download_url=download_url,
                    description=description or None,
                    date_filed=parent_date,
                    document_index=doc_idx,
                )
            )

        # Schedule each PDF as an archive Request — resolved into
        # ParsedData(MsAppDocument) by ``download_document``.
        for doc in documents:
            yield Request(
                archive=True,
                request=HTTPRequestParams(
                    method=HttpMethod.GET, url=doc.download_url
                ),
                continuation=self.download_document,
                expected_type="pdf",
                accumulated_data={
                    "doc": doc.model_dump(mode="json"),
                },
                deduplication_key=f"ms-app-doc-{cn}-{doc.file_name}",
            )

        accumulated_data.update(
            {
                "docket_number": docket_number,
                "case_name": case_name,
                "court_id": _court_id_from_docket_number(docket_number),
                "date_filed": earliest_date.isoformat()
                if earliest_date
                else None,
                "entries": [e.model_dump(mode="json") for e in entries],
                "document_count": len(documents),
            }
        )

        yield Request(
            request=HTTPRequestParams(
                method=HttpMethod.POST,
                url=BUILD_DOCKET_URL,
                data=PARTIES_BODY.format(cn=cn),
                headers=XHR_HEADERS,
            ),
            continuation=self.parse_parties,
            accumulated_data=accumulated_data,
        )

    # =========================================================================
    # Step 2: parties (listby=pty)
    # =========================================================================

    @step()
    def parse_parties(
        self,
        page: PageElement,
        accumulated_data: dict,
    ) -> Generator[ScraperYield, None, None]:
        """Parse the parties + attorneys block, then chain to lcinfo.

        The site's HTML for the attorney rows is malformed — each
        attorney's ``<table>`` is opened but never explicitly closed,
        so lxml normalises by nesting them. That means we cannot rely
        on `following-sibling::table[N]` to grab attorneys for a given
        party. Instead we walk every `<td class="liaptcell">` in
        document order and assign each to the nearest preceding
        party-header table (`<table bgcolor="#003366">`), matching
        blocks by element identity.
        """
        party_blocks = page.query_xpath(
            "//table[translate(@bgcolor, 'abcdef', 'ABCDEF')='#003366']",
            "party header tables",
            min_count=0,
        )

        parties_state: list[dict] = []
        for block in party_blocks:
            role_cells = block.query_xpath(
                ".//td[@class='laptcell']",
                "role cell",
                min_count=0,
                max_count=1,
            )
            role = _strip(role_cells[0].text_content()) if role_cells else ""
            name_cells = block.query_xpath(
                ".//tr[1]/td[not(@class='laptcell')]",
                "party name cell",
                min_count=0,
                max_count=1,
            )
            if not name_cells:
                continue
            name = _strip(name_cells[0].text_content())
            if not name:
                continue
            parties_state.append(
                {"role": role, "name": name, "block": block, "attorneys": []}
            )

        # Bucket each attorney row to its nearest preceding party block.
        # We can't compare PageElement instances by identity, so use
        # ``count(preceding::table[bgcolor='#003366'])`` as a stable
        # 1-based index into ``parties_state``.
        liaptcells = page.query_xpath(
            "//td[@class='liaptcell']", "attorney anchor cells", min_count=0
        )
        for cell in liaptcells:
            sibs = cell.query_xpath(
                "../td[not(@class='liaptcell')][1]",
                "attorney name cell",
                min_count=0,
                max_count=1,
            )
            if not sibs:
                continue
            atty_name = _strip(sibs[0].text_content())
            if not atty_name or atty_name == "No Attorney Representation":
                continue
            count_strs = cell.query_xpath_strings(
                "string(count(preceding::table["
                "translate(@bgcolor, 'abcdef', 'ABCDEF')='#003366']))",
                "preceding party header count",
                min_count=0,
                max_count=1,
            )
            if not count_strs:
                continue
            try:
                idx = int(float(count_strs[0])) - 1
            except (TypeError, ValueError):
                continue
            if not 0 <= idx < len(parties_state):
                continue
            atty_list: list[str] = parties_state[idx]["attorneys"]
            if atty_name not in atty_list:
                atty_list.append(atty_name)

        parties: list[MsAppParty] = [
            MsAppParty(
                name=str(state["name"]),
                role=str(state["role"]) or None,
                attorneys=[MsAppAttorney(name=n) for n in state["attorneys"]],
            )
            for state in parties_state
        ]

        accumulated_data["parties"] = [
            p.model_dump(mode="json") for p in parties
        ]

        cn = int(accumulated_data["case_num"])
        yield Request(
            request=HTTPRequestParams(
                method=HttpMethod.POST,
                url=BUILD_DOCKET_URL,
                data=LCOURT_BODY.format(cn=cn),
                headers=XHR_HEADERS,
            ),
            continuation=self.parse_trial_court,
            accumulated_data=accumulated_data,
        )

    # =========================================================================
    # Step 3: trial court info (lcinfo)
    # =========================================================================

    @step()
    def parse_trial_court(
        self,
        page: PageElement,
        accumulated_data: dict,
    ) -> Generator[ScraperYield, None, None]:
        """Parse the trial-court block(s) and chain to oralarg."""
        # Each trial court ruling occupies a contiguous run of
        # <td class="tccell"> rows within the lcinfo response. The
        # first two cells are the appellate docket number and the
        # caption (re-stated); we skip those and group the rest into
        # blocks of (court, case#, judge, ruling-date).
        cells = page.query_xpath_strings(
            "//td[@class='tccell']//text()",
            "tccell texts",
            min_count=0,
        )
        cleaned = [_strip(c) for c in cells if _strip(c)]

        appellate_no = (accumulated_data.get("docket_number") or "").upper()
        case_name = accumulated_data.get("case_name") or ""
        body = [
            c for c in cleaned if c.upper() != appellate_no and c != case_name
        ]

        trial_courts: list[MsAppTrialCourt] = []
        current: dict[str, str | date | None] = {}

        def flush() -> None:
            if not current.get("court_name"):
                return
            trial_courts.append(
                MsAppTrialCourt(
                    court_name=str(current["court_name"]),
                    trial_court_case_number=current.get(
                        "trial_court_case_number"
                    )
                    or None,  # type: ignore[arg-type]
                    judge=current.get("judge") or None,  # type: ignore[arg-type]
                    ruling_date=current.get("ruling_date") or None,  # type: ignore[assignment]
                )
            )
            current.clear()

        for line in body:
            if line.startswith("Trial Court Case #"):
                m = _TRIAL_CASE_RE.match(line)
                if m:
                    current["trial_court_case_number"] = m.group(1).strip()
            elif line.startswith("The Honorable"):
                current["judge"] = line[len("The Honorable") :].strip()
            else:
                m = _RULING_DATE_RE.search(line)
                if m:
                    current["ruling_date"] = _parse_date(m.group(1))
                    flush()
                else:
                    # New court block — flush any pending one first.
                    if current:
                        flush()
                    current["court_name"] = line
        flush()

        accumulated_data["trial_courts"] = [
            tc.model_dump(mode="json") for tc in trial_courts
        ]

        cn = int(accumulated_data["case_num"])
        yield Request(
            request=HTTPRequestParams(
                method=HttpMethod.POST,
                url=BUILD_DOCKET_URL,
                data=ORALARG_BODY.format(cn=cn),
                headers=XHR_HEADERS,
            ),
            continuation=self.parse_oral_arguments,
            accumulated_data=accumulated_data,
        )

    # =========================================================================
    # Step 4: oral arguments + final assembly
    # =========================================================================

    @step()
    def parse_oral_arguments(
        self,
        page: PageElement,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[MsAppDocket], None, None]:
        """Parse the oral-arg pane and yield the assembled docket."""
        oral_links = page.query_xpath(
            "//table[@id='archList']//a", "oral arg links", min_count=0
        )
        oral_arguments: list[MsAppOralArgument] = []
        for link in oral_links:
            urls = link.query_xpath_strings(
                "./@href", "oral arg href", min_count=0, max_count=1
            )
            if not urls:
                continue
            label = _strip(link.text_content())
            oral_arguments.append(
                MsAppOralArgument(url=urls[0], label=label or None)
            )

        cn = int(accumulated_data["case_num"])
        date_filed_raw = accumulated_data.get("date_filed")
        date_filed = (
            date.fromisoformat(date_filed_raw) if date_filed_raw else None
        )

        docket = MsAppDocket(
            docket_number=accumulated_data["docket_number"],
            court_id=accumulated_data["court_id"],
            case_num=cn,
            case_name=accumulated_data["case_name"],
            date_filed=date_filed,
            entries=[
                MsAppDocketEntry(**e)
                for e in accumulated_data.get("entries", [])
            ],
            parties=[
                MsAppParty(**p) for p in accumulated_data.get("parties", [])
            ],
            trial_courts=[
                MsAppTrialCourt(**tc)
                for tc in accumulated_data.get("trial_courts", [])
            ],
            oral_arguments=oral_arguments,
            document_count=int(accumulated_data.get("document_count", 0)),
            source_url=f"{INDEX_URL}?cn={cn}#dispArea",
        )
        yield ParsedData(data=docket)

    # =========================================================================
    # Step: document download completion
    # =========================================================================

    @step()
    def download_document(
        self,
        local_filepath: str | None,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[MsAppDocument], None, None]:
        """Finalize an archived PDF into an ``MsAppDocument`` record."""
        doc_dict = dict(accumulated_data["doc"])
        date_raw = doc_dict.get("date_filed")
        doc = MsAppDocument(
            docket_number=doc_dict["docket_number"],
            case_num=int(doc_dict["case_num"]),
            file_name=doc_dict["file_name"],
            download_url=response.url,
            description=doc_dict.get("description"),
            date_filed=date.fromisoformat(date_raw) if date_raw else None,
            document_index=doc_dict.get("document_index"),
            local_path=local_filepath,
        )
        yield ParsedData(data=doc)


# =========================================================================
# Helpers
# =========================================================================


def _strip(value: str) -> str:
    """Collapse whitespace + non-breaking spaces in extracted text."""
    if not value:
        return ""
    return re.sub(r"\s+", " ", value.replace("\xa0", " ")).strip()


def _parse_date(value: str | None) -> date | None:
    """Parse a ``M/D/YYYY`` (or ``M/D/YY``) string."""
    if not value:
        return None
    try:
        m, d, y = value.strip().split("/")
        year = int(y)
        if year < 100:
            # Two-digit years on legacy records: 70-99 → 19xx, else 20xx.
            year += 1900 if year >= 70 else 2000
        return date(year, int(m), int(d))
    except (ValueError, AttributeError):
        return None


def _parse_desc_index(value: str) -> int | None:
    """Pull the integer N out of ``desc-N`` or ``dockpdf-N``."""
    m = re.search(r"-(\d+)\b", value or "")
    return int(m.group(1)) if m else None


def _extract_file_param(href: str) -> str:
    """Extract the ``f=…`` parameter from a sendPDF.php URL."""
    m = re.search(r"[?&]f=([^&#]+)", href or "")
    return m.group(1) if m else ""


def _court_id_from_docket_number(docket_number: str) -> str:
    """Return the CourtListener court id implied by the docket suffix.

    Falls back to ``DEFAULT_COURT_ID`` for legacy (pre-1997) docket
    numbers that have no court suffix.
    """
    m = _DOCKET_RE_MODERN.search(docket_number or "")
    if m:
        return SUFFIX_TO_COURT_ID.get(m.group(4), DEFAULT_COURT_ID)
    return DEFAULT_COURT_ID
