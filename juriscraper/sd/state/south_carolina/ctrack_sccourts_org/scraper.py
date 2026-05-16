"""South Carolina Appellate Courts Scraper (C-Track).

Scrapes appellate dockets from the C-Track Public Access portal at
https://ctrack.sccourts.org/. The same install hosts the Supreme Court
of South Carolina (`sc`) and the South Carolina Court of Appeals
(`scctapp`).

Entry points:

- ``get_dockets_by_date(date_range: DateRange)`` — bulk scrape across
  both courts by filed-date window. Walks the listing's "Next" pages.
- ``get_docket(docket_number: str)`` — direct lookup by appellate case
  number (e.g. ``2026-000911``). Single matches 302 to the case detail.

Per-case flow:

    parse_search_listing  ── for each result row ──▶
    GET caseView.do?csIID=N
        └─ parse_case_detail
             └─ ParsedData(SCAppDocket)

Document URLs are not enriched in v1; each docket entry records the
``event_id`` (C-Track ``deID``) and a ``has_documents`` flag instead.
See DESIGN.md "Known Gaps".
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from typing import TYPE_CHECKING, ClassVar
from urllib.parse import urljoin

from jkent.common.decorators import entry, step
from jkent.common.page_element import PageElement
from jkent.common.param_models import DateRange
from jkent.data_types import (
    BaseScraper,
    DriverRequirement,
    HttpMethod,
    HTTPRequestParams,
    ParsedData,
    Request,
    Response,
    ScraperStatus,
    SkipDeduplicationCheck,
)
from pyrate_limiter import Duration, Rate

from juriscraper.sd.state.common.ctrack import (
    build_dwr_doc_links_body,
    build_search_form_skeleton,
    parse_dwr_doc_link_anchors,
    parse_label_value_table,
    parse_mmddyyyy,
)

from .models import (
    SCAppDocket,
    SCAppDocketEntry,
    SCAppDocument,
    SCAppParty,
)

if TYPE_CHECKING:
    from collections.abc import Generator

    from jkent.data_types import ScraperYield


BASE_URL = "https://ctrack.sccourts.org"
SEARCH_URL = f"{BASE_URL}/public/caseSearch.do"
CASE_VIEW_URL = f"{BASE_URL}/public/caseView.do"

# DWR endpoint that resolves a docket-event ID (`deID`) to a list of
# document download URLs. The site loads this lazily as a tooltip when
# the user hovers a documentLink icon. The endpoint is stateless — any
# `scriptSessionId` value works, and `httpSessionId` may be empty.
DWR_DOCUMENT_LINKS_URL = (
    f"{BASE_URL}/public/dwr/call/plaincall/AJAX.getViewDocumentLinks.dwr"
)

# Listing page caps at this many rows per response. The server respects
# values up to at least 200; using a larger page size cuts the round
# trips on big windows.
PAGE_SIZE = 200

# Number of days back from "today" for the no-arg get_dockets() entry.
DEFAULT_LOOKBACK_DAYS = 30

# Form-text → CourtListener court ID. Mirrors ``COURT_IDS`` in models.py
# but keyed on the human-readable "Court:" string the site emits.
_COURT_NAME_TO_ID: dict[str, str] = {
    "Supreme Court": "sc",
    "Court of Appeals": "scctapp",
}

# Sentinel emitted by the search page when csNumber yields zero matches.
_NO_RECORDS_SENTINEL = '<span class="NoRecords">No records were found.</span>'

# The case-number cell on each listing row. We extract csIID from the
# href and the appellate case number from the link text.
_CSIID_RE = re.compile(r"csIID=(\d+)")

# Docket events (the third FormTable on the case detail page) have a
# document icon whose `name` attribute encodes the event ID.
_DEID_RE = re.compile(r"deID:(\d+)")


class SouthCarolinaAppellateScraper(BaseScraper[SCAppDocket | SCAppDocument]):
    """Scraper for SC Supreme Court and SC Court of Appeals dockets."""

    # === Metadata ===
    court_ids: ClassVar[set[str]] = {"sc", "scctapp"}
    court_url: ClassVar[str] = BASE_URL
    data_types: ClassVar[set[str]] = {"dockets"}
    status: ClassVar[ScraperStatus] = ScraperStatus.IN_DEVELOPMENT
    version: ClassVar[str] = "2026-05-05"
    requires_auth: ClassVar[bool] = False

    rate_limits: ClassVar[list[Rate] | None] = [Rate(2, Duration.SECOND)]

    # 302 from the case-number search lands directly on the detail page.
    driver_requirements: ClassVar[list[DriverRequirement]] = [
        DriverRequirement.FOLLOW_REDIRECTS,
    ]

    # =========================================================================
    # Helpers
    # =========================================================================

    @staticmethod
    def _normalize_whitespace(text: str) -> str:
        """Collapse contiguous whitespace to a single space."""
        return " ".join(text.split())

    @classmethod
    def _build_search_form(
        cls,
        *,
        from_date: date | None = None,
        to_date: date | None = None,
        cs_number: str | None = None,
        start_row: int = 1,
        page_size: int = PAGE_SIZE,
    ) -> dict[str, str]:
        """Build the case-search form body.

        Mirrors the hidden + visible fields in ``caseSearchForm`` so the
        server treats the request as a real button-press POST.
        """
        return build_search_form_skeleton(
            start_row=start_row,
            display_rows=page_size,
            order_by="FileDt",
            order_dir="DESC",
            extra={
                "courtID": "-1",  # both courts
                "shortTitle": "",
                "fromDt": from_date.strftime("%m/%d/%Y") if from_date else "",
                "toDt": to_date.strftime("%m/%d/%Y") if to_date else "",
                "csGroupID": "-1",
                "csNumber": cs_number or "",
                "csTypeID": "-1",
                # exclude omitted → unchecked → include closed cases too
            },
        )

    # =========================================================================
    # Entry points
    # =========================================================================

    @entry(SCAppDocket)
    def get_dockets(self) -> Generator[Request, None, None]:
        """Walk the most recent ~30 days of filings.

        Provided for default scheduled runs. Use
        ``get_dockets_by_date`` to control the window precisely.
        """
        today = date.today()
        start = today - timedelta(days=DEFAULT_LOOKBACK_DAYS)
        yield from self._yield_listing_request(start, today)

    @entry(SCAppDocket)
    def get_dockets_by_date(
        self, date_range: DateRange
    ) -> Generator[Request, None, None]:
        """Bulk scrape all appellate filings in a filed-date window."""
        yield from self._yield_listing_request(
            date_range.start, date_range.end
        )

    @entry(SCAppDocket)
    def get_docket(self, docket_number: str) -> Generator[Request, None, None]:
        """Fetch a single docket by appellate case number.

        The site 302s a single-match case-number search straight to the
        case-detail page, so we let the redirect carry us through and
        branch on the final URL in ``parse_case_or_miss``.
        """
        clean = docket_number.strip()
        yield Request(
            request=HTTPRequestParams(
                method=HttpMethod.POST,
                url=SEARCH_URL,
                data=self._build_search_form(cs_number=clean),
            ),
            continuation=self.parse_case_or_miss,
            accumulated_data={"requested_docket_number": clean},
            deduplication_key=clean,
        )

    # =========================================================================
    # Listing flow
    # =========================================================================

    def _yield_listing_request(
        self, from_date: date, to_date: date, start_row: int = 1
    ) -> Generator[Request, None, None]:
        yield Request(
            request=HTTPRequestParams(
                method=HttpMethod.POST,
                url=SEARCH_URL,
                data=self._build_search_form(
                    from_date=from_date,
                    to_date=to_date,
                    start_row=start_row,
                ),
            ),
            continuation=self.parse_search_listing,
            accumulated_data={
                "from_date": from_date.isoformat(),
                "to_date": to_date.isoformat(),
                "start_row": start_row,
            },
            deduplication_key=SkipDeduplicationCheck(),
        )

    @step()
    def parse_search_listing(
        self,
        page: PageElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[SCAppDocket], None, None]:
        """Walk one page of search results.

        For each row, enqueue a GET of the case detail. If a "Next" link
        is present, enqueue the same form POST advanced by ``PAGE_SIZE``.
        """
        # Only match leaf <tr> rows that have a case link as a *child*
        # of one of their TDs — keeps ancestor table rows (which inherit
        # descendant matches) out of the list.
        rows = page.query_xpath(
            "//tr[./td/a[contains(@href, 'csIID=')]]",
            "result rows",
            min_count=0,
        )

        for row in rows:
            cells = row.query_xpath(".//td", "result cells", min_count=0)
            if len(cells) < 8:
                continue

            court_text = self._normalize_whitespace(cells[0].text_content())
            court_id = _COURT_NAME_TO_ID.get(court_text)
            if court_id is None:
                # Unknown court label — skip rather than emit a record
                # with a guessed court_id.
                continue

            links = cells[1].query_xpath(
                ".//a[contains(@href, 'csIID=')]",
                "case link",
                min_count=0,
                max_count=1,
            )
            if not links:
                continue
            href = links[0].get_attribute("href") or ""
            csiid_match = _CSIID_RE.search(href)
            if not csiid_match:
                continue
            site_case_id = csiid_match.group(1)
            docket_number = self._normalize_whitespace(links[0].text_content())

            case_url = urljoin(response.url, href)

            yield Request(
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url=case_url,
                ),
                continuation=self.parse_case_detail,
                accumulated_data={
                    "docket_number": docket_number,
                    "court_id": court_id,
                    "site_case_id": site_case_id,
                },
                deduplication_key=site_case_id,
            )

        # Pagination — re-POST the form with an advanced startRow.
        next_links = page.find_links(
            "//a[normalize-space(text())='Next']",
            "next page",
            min_count=0,
            max_count=2,
        )
        if next_links:
            from_date = date.fromisoformat(accumulated_data["from_date"])
            to_date = date.fromisoformat(accumulated_data["to_date"])
            next_start = int(accumulated_data["start_row"]) + PAGE_SIZE
            yield from self._yield_listing_request(
                from_date, to_date, start_row=next_start
            )

    # =========================================================================
    # Direct case-number lookup
    # =========================================================================

    @step()
    def parse_case_or_miss(
        self,
        page: PageElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[SCAppDocket], None, None]:
        """Branch on whether the case# search redirected to a detail page."""
        url = response.url or ""

        if "/public/caseView.do" in url:
            csiid_match = _CSIID_RE.search(url)
            site_case_id = csiid_match.group(1) if csiid_match else ""
            yield from self._emit_case_detail(
                page=page,
                response=response,
                accumulated_data={
                    "docket_number": accumulated_data.get(
                        "requested_docket_number", ""
                    ),
                    # Court is parsed from the detail page's "Court:" cell.
                    "court_id": "",
                    "site_case_id": site_case_id,
                },
            )
            return

        if _NO_RECORDS_SENTINEL in response.text:
            return  # clean miss

        # We're still on a search page but with rows — unusual for a
        # case# query (it should redirect on a single match). Walk it
        # like a normal listing.
        yield from self.parse_search_listing(  # type: ignore[misc]
            page=page,
            response=response,
            accumulated_data={
                "from_date": date.today().isoformat(),
                "to_date": date.today().isoformat(),
                "start_row": 1,
            },
        )

    # =========================================================================
    # Case detail
    # =========================================================================

    @step()
    def parse_case_detail(
        self,
        page: PageElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[SCAppDocket], None, None]:
        yield from self._emit_case_detail(
            page=page,
            response=response,
            accumulated_data=accumulated_data,
        )

    def _emit_case_detail(
        self,
        *,
        page: PageElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[SCAppDocket | SCAppDocument], None, None]:
        """Build and emit a ``SCAppDocket`` from a case-detail page."""
        case_info = parse_label_value_table(page, label_class="Label")
        parties = self._parse_parties(page)
        entries = self._parse_events(page)
        full_title = self._parse_full_title(page)

        # Court text wins over caller-supplied court_id (which is empty
        # on the case-number lookup path). Both should agree on the
        # listing-driven path.
        court_text = case_info.get("Court", "")
        court_id = (
            _COURT_NAME_TO_ID.get(court_text)
            or accumulated_data.get("court_id")
            or ""
        )

        docket_number = (
            self._parse_docket_number(page)
            or accumulated_data.get("docket_number")
            or ""
        )
        site_case_id = accumulated_data.get("site_case_id") or ""

        docket = SCAppDocket(
            docket_id=docket_number,
            court_id=court_id,
            site_case_id=site_case_id,
            case_name=case_info.get("Short Title", "") or docket_number,
            full_title=full_title,
            classification=case_info.get("Classification") or None,
            case_status=case_info.get("Case Status") or None,
            consolidated=case_info.get("Consolidated") or None,
            date_filed=parse_mmddyyyy(case_info.get("Filed Date")),
            oral_argument_date=parse_mmddyyyy(
                case_info.get("Oral Argument Date")
            ),
            disposition_date=parse_mmddyyyy(case_info.get("Disposition Date")),
            disposition_type=case_info.get("Disposition Type") or None,
            remittitur_date=parse_mmddyyyy(case_info.get("Remittitur Date")),
            lower_court=case_info.get("Lower Court or Tribunal") or None,
            parties=parties,
            entries=entries,
            source_url=response.url,
        )
        yield ParsedData(data=docket)

        # Resolve and archive per-event documents. Each docket event with
        # a `documentLink` icon needs one DWR call to turn the deID into
        # one-or-more documentID links, which we then archive.
        case_url = response.url or ""
        for entry_obj in entries:
            if not entry_obj.event_id:
                continue
            yield Request(
                request=HTTPRequestParams(
                    method=HttpMethod.POST,
                    url=DWR_DOCUMENT_LINKS_URL,
                    data=build_dwr_doc_links_body(
                        case_url=case_url,
                        params=[entry_obj.event_id],
                    ),
                    headers={"Content-Type": "text/plain"},
                ),
                continuation=self.fetch_event_document_links,
                accumulated_data={
                    "docket_id": docket.docket_id,
                    "court_id": docket.court_id,
                    "event_id": entry_obj.event_id,
                },
                deduplication_key=f"dwr:{entry_obj.event_id}",
                nonnavigating=True,
            )

    @step()
    def fetch_event_document_links(
        self,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[SCAppDocument], None, None]:
        """Parse a DWR reply and archive each linked PDF.

        The reply body is a `dwr.engine._remoteHandleCallback` call whose
        third argument is an HTML fragment of `<a href="...">label</a>`
        anchors — one per document attached to this docket event.
        """
        for download_url, document_id, label in parse_dwr_doc_link_anchors(
            response.text or "", BASE_URL + "/"
        ):
            yield Request(
                archive=True,
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url=download_url,
                ),
                continuation=self.handle_document_download,
                expected_type="pdf",
                accumulated_data={
                    "docket_id": accumulated_data["docket_id"],
                    "court_id": accumulated_data["court_id"],
                    "event_id": accumulated_data["event_id"],
                    "document_id": document_id,
                    "download_url": download_url,
                    "label": label,
                },
                deduplication_key=f"doc:{document_id}",
            )

    @step()
    def handle_document_download(
        self,
        accumulated_data: dict,
        local_filepath: str | None = None,
    ) -> Generator[ScraperYield[SCAppDocument], None, None]:
        """Emit one ``SCAppDocument`` for an archived PDF."""
        yield ParsedData(
            data=SCAppDocument(
                docket_id=accumulated_data["docket_id"],
                court_id=accumulated_data["court_id"],
                event_id=accumulated_data["event_id"],
                document_id=accumulated_data["document_id"],
                download_url=accumulated_data["download_url"],
                label=accumulated_data["label"],
                local_path=local_filepath,
            )
        )

    def _parse_docket_number(self, page: PageElement) -> str | None:
        spans = page.query_xpath(
            "//span[@id='csNumber']", "csNumber span", min_count=0, max_count=1
        )
        if not spans:
            return None
        text = self._normalize_whitespace(spans[0].text_content())
        return text or None

    def _parse_full_title(self, page: PageElement) -> str | None:
        divs = page.query_xpath(
            "//div[@id='fullTitle']", "fullTitle div", min_count=0, max_count=1
        )
        if not divs:
            return None
        text = self._normalize_whitespace(divs[0].text_content())
        return text or None

    def _parse_parties(self, page: PageElement) -> list[SCAppParty]:
        """Parse the Party Information table."""
        rows = page.query_xpath(
            "//table[@id='partyInfo']//tbody//tr",
            "party rows",
            min_count=0,
        )
        parties: list[SCAppParty] = []
        for row in rows:
            cells = row.query_xpath(".//td", "party cells", min_count=0)
            # Subheading rows have `class="TableSubHeading"` and 4 cells
            # of column titles ("Appellate Role" / "Party Name" / ...).
            classes = (row.get_attribute("class") or "").lower()
            if "tablesubheading" in classes:
                continue
            if len(cells) < 4:
                continue
            role = self._normalize_whitespace(cells[0].text_content())
            name = self._normalize_whitespace(cells[1].text_content())
            former_text = self._normalize_whitespace(
                cells[2].text_content()
            ).upper()
            attorneys_raw = cells[3].text_content() or ""
            attorneys = [
                self._normalize_whitespace(part)
                for part in re.split(r"[\r\n]+", attorneys_raw)
                if part.strip()
            ]
            if not (role and name):
                continue
            parties.append(
                SCAppParty(
                    role=role,
                    name=name,
                    is_former=former_text == "Y",
                    attorneys=attorneys,
                )
            )
        return parties

    def _parse_events(self, page: PageElement) -> list[SCAppDocketEntry]:
        """Parse the Event Information table.

        The events table is the third ``class="FormTable"`` table on the
        page (after the case-info table and the parties table) and has
        three columns: Filed Date, Event Information, Doc.
        """
        # Locate event rows by their structure: a TR with exactly three
        # TDs whose first TD matches MM/DD/YYYY. This is robust to the
        # absence of a stable id/class on the table itself.
        rows = page.query_xpath(
            "//tr[count(./td)=3 and "
            "translate(normalize-space(./td[1]/text()),'0123456789','') = '//']",
            "event rows",
            min_count=0,
        )
        entries: list[SCAppDocketEntry] = []
        for row in rows:
            cells = row.query_xpath(".//td", "event cells", min_count=3)
            date_text = self._normalize_whitespace(cells[0].text_content())
            description = self._normalize_whitespace(cells[1].text_content())

            event_id: str | None = None
            has_documents = False
            doc_imgs = cells[2].query_xpath(
                ".//img[contains(@class, 'documentLink')]",
                "doc icons",
                min_count=0,
                max_count=1,
            )
            if doc_imgs:
                name_attr = doc_imgs[0].get_attribute("name") or ""
                deid_match = _DEID_RE.search(name_attr)
                if deid_match:
                    event_id = deid_match.group(1)
                    has_documents = True

            entries.append(
                SCAppDocketEntry(
                    date_filed=parse_mmddyyyy(date_text),
                    description=description,
                    event_id=event_id,
                    has_documents=has_documents,
                )
            )
        return entries
