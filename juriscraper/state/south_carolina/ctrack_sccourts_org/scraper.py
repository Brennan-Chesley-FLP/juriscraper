"""South Carolina Appellate Courts Scraper (C-Track).

Scrapes appellate dockets from the C-Track Public Access portal at
https://ctrack.sccourts.org/. The same install hosts the Supreme Court
of South Carolina (`sc`) and the South Carolina Court of Appeals
(`scctapp`).

Entry points:

- ``dockets_by_filing_date(court_ids, date_range)`` — bulk scrape by
  filed-date window. The seeded ``court_ids`` narrow the server-side
  ``courtID`` filter (and post-filter the listing rows). Walks the
  listing's "Next" pages.
- ``docket_by_number(court_id, docket_number)`` — direct lookup by
  appellate case number (e.g. ``2026-000911``). A single match 302s to
  the case detail.

Per-case flow:

    parse_search_listing  ── for each result row ──▶
    GET caseView.do?csIID=N
        └─ parse_case_detail
             ├─ ParsedData(SCAppDocket)
             └─ for each entry with documents:
                    POST DWR getViewDocumentLinks
                      └─ fetch_event_document_links
                           └─ archive Request → handle_document_download
                                └─ ParsedData(SCAppDocument)
"""

from __future__ import annotations

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
    build_dwr_doc_links_body,
    build_search_form_skeleton,
    parse_dwr_doc_link_anchors,
)

from .models import (
    SITE_COURT_ID_BY_COURT,
    SCAppDocket,
    SCAppDocument,
)
from .parsers._common import CSIID_RE
from .parsers.case_detail import CaseDetailParser
from .parsers.search_listing import SearchListingParser

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

# Sentinel emitted by the search page when csNumber yields zero matches.
_NO_RECORDS_SENTINEL = '<span class="NoRecords">No records were found.</span>'


class SouthCarolinaAppellateScraper(BaseScraper[SCAppDocket | SCAppDocument]):
    """Scraper for SC Supreme Court and SC Court of Appeals dockets."""

    # === Metadata ===
    court_ids: ClassVar[set[str]] = {"sc", "scctapp"}
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
    # Helpers
    # =========================================================================

    @classmethod
    def _site_court_id(cls, court_ids: set[str]) -> str:
        """Map the seeded court set to the form's ``courtID`` value.

        A single seeded court narrows the search server-side; anything
        else (the default both-courts run) uses ``-1``.
        """
        if len(court_ids) == 1:
            (court,) = court_ids
            site_id = SITE_COURT_ID_BY_COURT.get(court)
            if site_id is not None:
                return str(site_id)
        return "-1"

    @classmethod
    def _build_search_form(
        cls,
        *,
        court_id: str = "-1",
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
                "courtID": court_id,
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
    def dockets_by_filing_date(
        self, court_ids: set[str], date_range: DateRange
    ) -> Generator[Request, None, None]:
        """Bulk scrape all appellate filings in a filed-date window."""
        yield from self._yield_listing_request(
            sorted(court_ids), date_range.start, date_range.end
        )

    @entry(SCAppDocket)
    def docket_by_number(
        self, court_id: str, docket_number: str
    ) -> Generator[Request, None, None]:
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
            accumulated_data={
                "docket_number": clean,
                "court": court_id,
            },
            deduplication_key=f"docket_by_number:{clean}",
        )

    # =========================================================================
    # Listing flow
    # =========================================================================

    def _yield_listing_request(
        self,
        target_courts: list[str],
        from_date: date,
        to_date: date,
        start_row: int = 1,
    ) -> Generator[Request, None, None]:
        yield Request(
            request=HTTPRequestParams(
                method=HttpMethod.POST,
                url=SEARCH_URL,
                data=self._build_search_form(
                    court_id=self._site_court_id(set(target_courts)),
                    from_date=from_date,
                    to_date=to_date,
                    start_row=start_row,
                ),
            ),
            continuation=self.parse_search_listing,
            accumulated_data={
                "target_courts": target_courts,
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
    ) -> Generator[ScraperYield[SCAppDocket], None, None]:
        """Walk one page of search results.

        For each row, enqueue a GET of the case detail. If a "Next" link
        is present, enqueue the same form POST advanced by ``PAGE_SIZE``.
        """
        target_courts = set(accumulated_data["target_courts"])
        for dv in SearchListingParser()(page):
            row = dv.raw_data
            court = row["court"]
            if court not in target_courts:
                # The both-courts ``courtID=-1`` search returns rows for
                # both courts; drop any outside the seeded set.
                continue
            site_case_id = row["site_case_id"]
            yield Request(
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url=f"{CASE_VIEW_URL}?csIID={site_case_id}",
                ),
                continuation=self.parse_case_detail,
                accumulated_data={
                    "docket_number": row["docket_number"],
                    "court": court,
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
                accumulated_data["target_courts"],
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
    ) -> Generator[ScraperYield[SCAppDocket], None, None]:
        """Branch on whether the case# search redirected to a detail page."""
        url = response.url or ""

        if "/public/caseView.do" in url:
            csiid_match = CSIID_RE.search(url)
            yield from self._emit_case_detail(
                page=page,
                response=response,
                accumulated_data={
                    "docket_number": accumulated_data.get("docket_number", ""),
                    # Court is parsed from the detail page's "Court:" cell.
                    "court": accumulated_data.get("court", ""),
                    "site_case_id": (
                        csiid_match.group(1) if csiid_match else ""
                    ),
                },
            )
            return

        if _NO_RECORDS_SENTINEL in (response.text or ""):
            return  # clean miss

        # Still on a search page but with rows — unusual for a case#
        # query (it should redirect on a single match). Walk it like a
        # normal listing across the seeded court.
        yield from self.parse_search_listing(  # type: ignore[misc]
            page=page,
            accumulated_data={
                "target_courts": sorted(self.court_ids),
                "from_date": date.today().isoformat(),
                "to_date": date.today().isoformat(),
                "start_row": 1,
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
        parsed = CaseDetailParser()(page)[0].raw_data

        # Court text (parsed from the page) wins over the caller-supplied
        # court, which is empty on the case-number lookup path. Both
        # should agree on the listing-driven path.
        court = parsed.get("court") or accumulated_data.get("court") or ""
        docket_number = (
            parsed.get("docket_number")
            or accumulated_data.get("docket_number")
            or ""
        )
        site_case_id = accumulated_data.get("site_case_id") or ""
        entries = parsed.get("docket_entries") or []

        yield ParsedData(
            data=SCAppDocket.raw(
                **{
                    **parsed,
                    "docket_number": docket_number,
                    "court": court,
                    "site_case_id": site_case_id,
                    "case_name": parsed.get("case_name") or docket_number,
                    "source_url": response.url,
                }
            )
        )

        # Resolve and archive per-event documents. Each docket event with
        # a `documentLink` icon needs one DWR call to turn the deID into
        # one-or-more documentID links, which we then archive.
        case_url = response.url or f"{CASE_VIEW_URL}?csIID={site_case_id}"
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
                    "docket_number": docket_number,
                    "court": court,
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
    ) -> Generator[ScraperYield[SCAppDocument], None, None]:
        """Parse a DWR reply and archive each linked PDF.

        The reply body is a `dwr.engine._remoteHandleCallback` call whose
        third argument is an HTML fragment of `<a href="...">label</a>`
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
                    "court": accumulated_data["court"],
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
    ) -> Generator[ScraperYield[SCAppDocument], None, None]:
        """Emit one ``SCAppDocument`` for an archived PDF."""
        yield ParsedData(
            data=SCAppDocument(
                docket_number=accumulated_data["docket_number"],
                court=accumulated_data["court"],
                event_id=accumulated_data["event_id"],
                document_number=accumulated_data["document_number"],
                url=accumulated_data["url"],
                description=accumulated_data["description"],
                filepath_local=local_filepath,
            )
        )
