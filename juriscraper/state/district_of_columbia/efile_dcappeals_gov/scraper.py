"""District of Columbia Court of Appeals scraper (C-Track).

Scrapes appellate dockets from the public C-Track install at
https://efile.dcappeals.gov/. Same older HTML-form C-Track variant as
South Carolina and Nevada — shared mechanics live in
``juriscraper.state.common.ctrack``.

Entry points:

- ``dockets_by_filing_date(court_ids, date_range)`` — bulk scrape across
  a filed-date window.
- ``docket_by_number(court_id, docket_number)`` — direct lookup by
  appellate case number (e.g. ``26-CV-0339``); the site 302s on a single
  match.

Per-case flow:

    POST caseSearch.do  ──▶  parse_search_listing
    ── for each row ──▶  GET caseView.do?csIID=N
                          └─ parse_case_detail (yields DCAppDocket)
                               └─ for each event with documents:
                                    POST DWR getViewDocumentLinks
                                      └─ fetch_event_document_links
                                           └─ archive Request
                                                └─ handle_document_download
                                                     yields DCAppDocument
"""

from __future__ import annotations

import re
from datetime import date
from typing import TYPE_CHECKING, ClassVar

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
    XPath,
)
from pyrate_limiter import Duration, Rate

from juriscraper.state.common.ctrack import (
    SOFT_404_MARKER,
    build_dwr_doc_links_body,
    build_search_form_skeleton,
    parse_dwr_doc_link_anchors,
)

from .models import DCAppDocket, DCAppDocument
from .parsers.case_detail import CaseDetailParser, read_hidden_csiid
from .parsers.search_listing import SearchListingParser

if TYPE_CHECKING:
    from collections.abc import Generator

    from jkent.data_types import ScraperYield


BASE_URL = "https://efile.dcappeals.gov"
SEARCH_URL = f"{BASE_URL}/public/caseSearch.do"
CASE_VIEW_URL = f"{BASE_URL}/public/caseView.do"

# DWR endpoint for resolving a docket-event icon's `(flag, deID, csIID)`
# triple to one or more document download URLs. Note: the DWR base on
# this install is `/dwr/...` (no `/public/` prefix — SC's install puts
# DWR under `/public/dwr/...`).
DWR_DOCUMENT_LINKS_URL = (
    f"{BASE_URL}/dwr/call/plaincall/AJAX.getViewDocumentLinks.dwr"
)

# Listing page cap. The server respects values up to at least 200; a
# typical month yields ~120 cases, so 200 keeps most windows on a
# single page.
PAGE_SIZE = 200

# Sentinel emitted by the search page when csNumber yields zero matches
# (mirrors SC's behavior).
_NO_RECORDS_SENTINEL = '<span class="NoRecords">No records were found.</span>'

# Case-detail page title: "<docket>: Case View".
_CASE_VIEW_TITLE_RE = re.compile(r"<title>[^<]+:\s*Case View", re.IGNORECASE)


class DCCourtOfAppealsScraper(BaseScraper[DCAppDocket | DCAppDocument]):
    """Scraper for the District of Columbia Court of Appeals."""

    # === Metadata ===
    court_ids: ClassVar[set[str]] = {"dc"}
    court_url: ClassVar[str] = BASE_URL
    data_types: ClassVar[set[str]] = {"dockets"}
    status: ClassVar[ScraperStatus] = ScraperStatus.IN_DEVELOPMENT
    version: ClassVar[str] = "2026-06-26"
    last_verified: ClassVar[str] = "2026-05-05"
    requires_auth: ClassVar[bool] = False

    rate_limits: ClassVar[list[Rate] | None] = [Rate(2, Duration.SECOND)]

    # 302 from the case-number search lands directly on the detail page.
    driver_requirements: ClassVar[list[DriverRequirement]] = [
        DriverRequirement.FOLLOW_REDIRECTS,
    ]

    # =========================================================================
    # Soft-404
    # =========================================================================

    def actually_successful(self, response: Response) -> bool:
        """Return False for invalid / out-of-range csIID responses.

        Invalid csIIDs return HTTP 500 with a "Security Error" body
        carrying the SOFT_404_MARKER. The driver only consults
        ``actually_successful`` for 2xx responses; the 5xx is already
        treated as a failure by the driver. We keep this override so that
        *valid* 2xx detail pages that nevertheless carry the marker (a
        sealed case fronted by a 200 in some flows) are still classified
        as misses.
        """
        return SOFT_404_MARKER not in (response.text or "")

    # =========================================================================
    # Form helper
    # =========================================================================

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
        """Build the case-search form body."""
        return build_search_form_skeleton(
            start_row=start_row,
            display_rows=page_size,
            order_by="CsNumber",
            order_dir="DESC",
            extra={
                "csNumber": cs_number or "",
                "shortTitle": "",
                "lcCsNumber": "",
                "fromDt": from_date.strftime("%m/%d/%Y") if from_date else "",
                "toDt": to_date.strftime("%m/%d/%Y") if to_date else "",
                # exclude omitted → unchecked → include closed cases too
            },
        )

    # =========================================================================
    # Entry points
    # =========================================================================

    @entry(DCAppDocket)
    def dockets_by_filing_date(
        self, court_ids: set[str], date_range: DateRange
    ) -> Generator[Request, None, None]:
        """Bulk scrape all appellate filings in a filed-date window."""
        yield from self._yield_listing_request(
            date_range.start, date_range.end
        )

    @entry(DCAppDocket)
    def docket_by_number(
        self, court_id: str, docket_number: str
    ) -> Generator[Request, None, None]:
        """Fetch a single docket by appellate case number.

        The site 302s a single-match case-number search straight to the
        case-detail page; we let the redirect carry through and branch on
        the final page in ``parse_case_or_miss``.
        """
        clean = docket_number.strip()
        yield Request(
            request=HTTPRequestParams(
                method=HttpMethod.POST,
                url=SEARCH_URL,
                data=self._build_search_form(cs_number=clean),
            ),
            continuation=self.parse_case_or_miss,
            accumulated_data={"docket_number": clean, "court": court_id},
            deduplication_key=f"docket_by_number:{clean}",
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
            # Paginating POSTs re-issue the same form with an advanced
            # startRow; dedup would collapse pages 2+ into page 1.
            deduplication_key=SkipDeduplicationCheck(),
        )

    @step(priority=4)
    def parse_search_listing(
        self,
        page: PageElement,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[DCAppDocket], None, None]:
        """Walk one page of search results.

        For each result row, enqueue a GET of the case detail. If a
        "Next" link is present, enqueue the next page by re-POSTing the
        form with an advanced ``startRow``.
        """
        for dv in SearchListingParser()(page):
            row = dv.raw_data
            site_case_id = row["site_case_id"]
            yield Request(
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url=f"{CASE_VIEW_URL}?csIID={site_case_id}",
                ),
                continuation=self.parse_case_detail,
                accumulated_data={
                    "docket_number": row["docket_number"],
                    "site_case_id": site_case_id,
                },
                deduplication_key=f"docket_detail:{site_case_id}",
            )

        # Pagination — re-POST the form with an advanced startRow.
        next_links = page.find_links(
            XPath("//a[normalize-space(text())='Next']"),
            "next page",
            min_count=0,
            max_count=2,
        )
        if next_links:
            yield from self._yield_listing_request(
                date.fromisoformat(accumulated_data["from_date"]),
                date.fromisoformat(accumulated_data["to_date"]),
                start_row=int(accumulated_data["start_row"]) + PAGE_SIZE,
            )

    # =========================================================================
    # Direct case-number lookup
    # =========================================================================

    @step(priority=3)
    def parse_case_or_miss(
        self,
        page: PageElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[DCAppDocket], None, None]:
        """Branch on whether the case# search redirected to a detail page.

        ``response.url`` reflects the request URL even after the kent HTTP
        driver follows the 302, so we detect the case-detail page by its
        title (``"<docket>: Case View"``) and read ``csIID`` from a hidden
        input in the body.
        """
        text = response.text or ""

        if _NO_RECORDS_SENTINEL in text:
            return  # clean miss

        if not _CASE_VIEW_TITLE_RE.search(text):
            # Unexpected: not a case-detail page and not the no-records
            # sentinel. csNumber search should always 302 on a single
            # match. Don't speculate further — emit nothing.
            return

        yield from self._emit_case_detail(
            page=page,
            response=response,
            accumulated_data={
                "docket_number": accumulated_data.get("docket_number", ""),
                "site_case_id": read_hidden_csiid(page),
            },
        )

    # =========================================================================
    # Case detail
    # =========================================================================

    @step(priority=3)
    def parse_case_detail(
        self,
        page: PageElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[DCAppDocket], None, None]:
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
    ) -> Generator[ScraperYield[DCAppDocket | DCAppDocument], None, None]:
        """Build and emit a ``DCAppDocket`` from a case-detail page."""
        parsed = CaseDetailParser()(page)[0].raw_data

        docket_number = (
            accumulated_data.get("docket_number")
            or parsed.get("docket_number")
            or ""
        )
        site_case_id = accumulated_data.get("site_case_id") or ""
        entries = parsed.get("docket_entries") or []

        yield ParsedData(
            data=DCAppDocket.raw(
                **{
                    **parsed,
                    "docket_number": docket_number,
                    "court": "dc",
                    "site_case_id": site_case_id,
                    "case_name": parsed.get("case_name") or docket_number,
                    "source_url": response.url,
                }
            )
        )

        # Resolve and archive per-event documents. Each event with a
        # documentLink icon needs one DWR call to turn (flag, deID, csIID)
        # into one-or-more documentID links, which we then archive. The
        # DWR ``page=`` field expects the case-view URL path; re-derive it
        # from csIID rather than ``response.url`` because kent reports the
        # original request URL even after a 302, and the case#-search path
        # arrives here with ``response.url`` pointing at caseSearch.do.
        dwr_page = (
            f"/public/caseView.do?csIID={site_case_id}"
            if site_case_id
            else (response.url or "")
        )
        for entry_obj in entries:
            if not (entry_obj.has_documents and entry_obj.event_id):
                continue
            params = [
                entry_obj.document_link_flag or "50",
                entry_obj.event_id,
                site_case_id,
            ]
            yield Request(
                request=HTTPRequestParams(
                    method=HttpMethod.POST,
                    url=DWR_DOCUMENT_LINKS_URL,
                    data=build_dwr_doc_links_body(
                        case_url=dwr_page, params=params
                    ),
                    headers={"Content-Type": "text/plain"},
                ),
                continuation=self.fetch_event_document_links,
                accumulated_data={
                    "docket_number": docket_number,
                    "court": "dc",
                    "event_id": entry_obj.event_id,
                },
                deduplication_key=(
                    f"document_links:{site_case_id}:{entry_obj.event_id}"
                ),
                nonnavigating=True,
            )

    @step(priority=2)
    def fetch_event_document_links(
        self,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[DCAppDocument], None, None]:
        """Parse a DWR reply and archive each linked PDF.

        The reply embeds an HTML fragment of one or more
        ``<a href="/document/view.do?documentID=N&csIID=N">label</a>``
        anchors — one per document attached to this docket event.
        """
        docket_number = accumulated_data["docket_number"]
        event_id = accumulated_data["event_id"]
        for url, document_number, description in parse_dwr_doc_link_anchors(
            response.text or "", BASE_URL + "/"
        ):
            yield Request(
                archive=True,
                request=HTTPRequestParams(method=HttpMethod.GET, url=url),
                continuation=self.handle_document_download,
                expected_type="pdf",
                accumulated_data={
                    "docket_number": docket_number,
                    "court": "dc",
                    "event_id": event_id,
                    "document_number": document_number,
                    "url": url,
                    "description": description,
                },
                deduplication_key=(
                    f"{docket_number}-{event_id}-{document_number}"
                ),
            )

    @step()
    def handle_document_download(
        self,
        accumulated_data: dict,
        local_filepath: str | None = None,
    ) -> Generator[ScraperYield[DCAppDocument], None, None]:
        """Emit one ``DCAppDocument`` for an archived PDF."""
        yield ParsedData(
            data=DCAppDocument(
                docket_number=accumulated_data["docket_number"],
                court=accumulated_data["court"],
                event_id=accumulated_data["event_id"],
                document_number=accumulated_data["document_number"],
                url=accumulated_data["url"],
                description=accumulated_data["description"],
                filepath_local=local_filepath,
            )
        )
