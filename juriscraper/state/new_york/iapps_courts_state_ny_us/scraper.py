"""NYSCEF appellate-case scraper (iapps.courts.state.ny.us).

Scrapes appellate case data from the New York State Courts Electronic
Filing system (NYSCEF), covering the four Appellate Division departments
and the Court of Claims.

Entry points (§4)::

    - @entry docket_by_number(court_id: str, docket_number: str)
        Single-record direct lookup by the ``YYYY-NNNNN`` case number.

    - @entry dockets_by_filing_date(court_ids: set[str], date_range: DateRange)
        For each requested court, search by filing-date window. The site
        searches one county at a time and exposes no "all case numbers"
        option, so each (court, window) is covered by nine searches — one
        per leading digit 1-9 in the "Case Number and Year Separated"
        field — since every non-zero case number contains a digit 1-9. The
        NYSCEF internal ``docketId`` is used as the per-case dedup key so a
        case surfaced by several digit searches is visited once.

Docket-number lookup flow::

    1. docket_by_number → GET CaseSearch
    2. parse_search_page      → fill case-number form, submit
    3. parse_search_results   → (SearchResultsParser) → GET CaseDetails
    4. parse_case_detail      → (CaseDetailParser) → GET DocumentList
    5. parse_document_list    → (DocumentListParser) → ParsedData + downloads

Filing-date flow::

    1. dockets_by_filing_date → 9× GET CaseSearch per court
    2. fill_date_search_form     → fill digit/county/dates, submit
    3. parse_date_search_results → (SearchResultsParser) → GET CaseDetails
    4. parse_case_detail         → (shared)
    5. parse_document_list       → (shared) → ParsedData + downloads

Design decisions:
- The site returns 403 for plain HTTP and presents an hCaptcha challenge,
  so it runs under Playwright (JS_EVAL, FF_ALIKE, HCAP_HANDLER).
- HTML extraction lives in the ``parsers`` package (§9); the steps keep the
  navigation (form fills, pagination, the per-case fan-out, downloads).
- ``court`` (the CL court id) and the filing-date window ride down the
  request chain in ``accumulated_data``; entries never re-read params.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar
from urllib.parse import urljoin

from jkent.common.decorators import entry, step
from jkent.common.page_element import ViaLink
from jkent.common.param_models import DateRange
from jkent.data_types import (
    CSS,
    BaseScraper,
    DriverRequirement,
    HttpMethod,
    HTTPRequestParams,
    ParsedData,
    Request,
    Response,
    ScraperStatus,
    SkipDeduplicationCheck,
    WaitForLoadState,
    WaitForSelector,
    XPath,
)
from pyrate_limiter import Duration, Rate

from .models import (
    COURT_NAME_TO_ID,
    COURT_TO_COUNTY,
    NYSCEFCase,
    NYSCEFDownloadedDocument,
)
from .parsers import (
    CaseDetailParser,
    DocumentListParser,
    SearchResultsParser,
)
from .parsers._common import extract_query_param

_Yield = NYSCEFCase | NYSCEFDownloadedDocument

if TYPE_CHECKING:
    from collections.abc import Generator

    from jkent.common.page_element import PageElement
    from jkent.data_types import ScraperYield


# =========================================================================
# Site constants
# =========================================================================

NYSCEF_BASE: str = "https://iapps.courts.state.ny.us/nyscef"
CASE_SEARCH_URL: str = f"{NYSCEF_BASE}/CaseSearch"

# Search form (POST) — id="form" on the CaseSearch page.
SEARCH_FORM = XPath("//form[@id='form']")


class NYSCEFScraper(BaseScraper[_Yield]):
    """Scraper for NYSCEF appellate case data.

    NYSCEF (iapps.courts.state.ny.us/nyscef) hosts electronic-filing
    records for the New York Appellate Division departments and the Court
    of Claims. Case numbers follow a ``YYYY-NNNNN`` pattern. The site
    returns 403 for non-browser requests and presents an hCaptcha
    challenge, so all interactions run under Playwright.
    """

    # === Metadata ===
    court_ids: ClassVar[set[str]] = {
        "nyappd1",
        "nyappd2",
        "nyappd3",
        "nyappd4",
        "nysctcl",
    }
    court_url: ClassVar[str] = NYSCEF_BASE
    data_types: ClassVar[set[str]] = {"dockets"}
    status: ClassVar[ScraperStatus] = ScraperStatus.IN_DEVELOPMENT
    version: ClassVar[str] = "2026-03-02"
    last_verified: ClassVar[str] = "2026-03-02"
    requires_auth: ClassVar[bool] = False
    driver_requirements: ClassVar[list[DriverRequirement]] = [
        DriverRequirement.HCAP_HANDLER,
    ]
    rate_limits: ClassVar[list[Rate] | None] = [Rate(2, Duration.SECOND)]

    # =================================================================
    # Entry points (§4)
    # =================================================================

    @entry(NYSCEFCase)
    def docket_by_number(
        self, court_id: str, docket_number: str
    ) -> Generator[Request, None, None]:
        """Fetch a single NYSCEF case by its ``YYYY-NNNNN`` number.

        Single-record direct lookup — takes ``court_id: str`` (exactly one
        court) per §4. The case number alone identifies the case on the
        search form; ``court_id`` is carried forward to stamp ``court``.
        """
        yield Request(
            request=HTTPRequestParams(
                method=HttpMethod.GET,
                url=CASE_SEARCH_URL,
            ),
            continuation=self.parse_search_page,
            accumulated_data={
                "docket_number": docket_number,
                "court": court_id,
                "entry_point": "docket_by_number",
            },
            deduplication_key=f"parse_search_page:{docket_number}",
        )

    @entry(NYSCEFCase)
    def dockets_by_filing_date(
        self, court_ids: set[str], date_range: DateRange
    ) -> Generator[Request, None, None]:
        """Search each requested court for cases filed within a date range.

        Issues nine searches per court (digits 1-9 as a partial case number
        in the "Case Number and Year Separated" section), filtered by county
        and filing-date window. This covers all case numbers because every
        non-zero case number contains at least one digit 1-9. The NYSCEF
        ``docketId`` is the per-case dedup key so overlapping digit searches
        visit each case once.
        """
        start_str = date_range.start.strftime("%m/%d/%Y")
        end_str = date_range.end.strftime("%m/%d/%Y")

        for court in sorted(court_ids):
            county_value = COURT_TO_COUNTY[court]
            for digit in range(1, 10):
                yield Request(
                    request=HTTPRequestParams(
                        method=HttpMethod.GET,
                        url=CASE_SEARCH_URL,
                    ),
                    continuation=self.fill_date_search_form,
                    accumulated_data={
                        "digit": str(digit),
                        "court": court,
                        "county_value": county_value,
                        "start_date": start_str,
                        "end_date": end_str,
                        "entry_point": "dockets_by_filing_date",
                    },
                    deduplication_key=SkipDeduplicationCheck(),
                )

    # =================================================================
    # Search steps
    # =================================================================

    @step(priority=5)
    def parse_search_page(
        self,
        page: PageElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[_Yield], None, None]:
        """Fill the case-number search form and submit (docket lookup)."""
        form = page.find_form(SEARCH_FORM, "case search form")
        yield form.submit(
            data={
                "txtCaseIdentifierNumber": accumulated_data["docket_number"]
            },
            continuation=self.parse_search_results,
            accumulated_data=accumulated_data,
            deduplication_key=(
                f"search_results:{accumulated_data['docket_number']}"
            ),
        )

    @step(priority=5)
    def fill_date_search_form(
        self,
        page: PageElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[_Yield], None, None]:
        """Fill the date-based search form and submit (filing-date flow).

        Uses the "Case Number and Year Separated" section with a single
        digit, plus the county and filing-date filters under "Narrow Your
        Results".
        """
        form = page.find_form(SEARCH_FORM, "case search form")
        yield form.submit(
            data={
                "txtIndexNumber": accumulated_data["digit"],
                "txtCounty": accumulated_data["county_value"],
                "txtFilingDateFrom": accumulated_data["start_date"],
                "txtFilingDateTo": accumulated_data["end_date"],
            },
            submit_selector=XPath("(//button[@name='btnSubmit'])[2]"),
            continuation=self.parse_date_search_results,
            accumulated_data=accumulated_data,
            deduplication_key=SkipDeduplicationCheck(),
        )

    @step(priority=4)
    def parse_search_results(
        self,
        page: PageElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[_Yield], None, None]:
        """Parse the case-number search results (docket-lookup flow).

        A case-number search returns at most one row; take the first and
        navigate to its Case Detail page. No table → not found (return).
        """
        records = SearchResultsParser()(page)
        if not records:
            return
        row = records[0].raw_data
        yield from self._visit_case_detail(row, accumulated_data, response.url)

    @step(
        await_list=[
            WaitForLoadState("networkidle", timeout=30000),
            WaitForSelector(
                "div.h-captcha, table.NewSearchResults",
                timeout=15000,
            ),
        ],
        priority=4,
    )
    def parse_date_search_results(
        self,
        page: PageElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[_Yield], None, None]:
        """Parse the date-search results and fan out one request per case.

        The ``docketId`` is the dedup key so overlapping digit searches skip
        already-seen cases. Pagination follows only the ``>>`` (next) link.
        """
        for record in SearchResultsParser()(page):
            yield from self._visit_case_detail(
                record.raw_data, accumulated_data, response.url
            )

        # Pagination: follow only the ">>" (next page) link.
        next_links = page.query(
            XPath(
                "//span[@class='pageNumbers']"
                "//a[@class='pageOff' and contains(text(), '>>')]"
            ),
            "next page link",
            min_count=0,
        )
        if next_links:
            href = next_links[0].get_attribute("href")
            if href:
                yield Request(
                    request=HTTPRequestParams(
                        method=HttpMethod.GET,
                        url=urljoin(response.url, href),
                    ),
                    continuation=self.parse_date_search_results,
                    accumulated_data=accumulated_data,
                    deduplication_key=SkipDeduplicationCheck(),
                )

    def _visit_case_detail(
        self,
        row: dict,
        accumulated_data: dict,
        base_url: str,
    ) -> Generator[Request, None, None]:
        """Build the CaseDetails request for one search-result row.

        Carries the grid fields forward (the case-detail and document-list
        pages don't repeat them). ``court`` prefers the entry's pinned court
        id, falling back to the row's resolved id.
        """
        docket_id = row.get("iapps_internal_docket_id")
        if not docket_id:
            return
        court = accumulated_data.get("court") or row.get("court")
        forwarded = {
            **accumulated_data,
            "court": court,
            "iapps_internal_docket_id": docket_id,
            "grid_fields": {
                "docket_number": row.get("docket_number"),
                "court": court,
                "court_name_raw": row.get("court_name_raw"),
                "case_name_short": row.get("case_name_short"),
                "case_type": row.get("case_type"),
                "efiling_status": row.get("efiling_status"),
                "date_received": row.get("date_received"),
            },
        }
        yield Request(
            request=HTTPRequestParams(
                method=HttpMethod.GET,
                url=urljoin(base_url, f"CaseDetails?docketId={docket_id}"),
            ),
            continuation=self.parse_case_detail,
            accumulated_data=forwarded,
            deduplication_key=f"case_detail:{docket_id}",
        )

    # =================================================================
    # Case detail
    # =================================================================

    @step(priority=3)
    def parse_case_detail(
        self,
        page: PageElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[_Yield], None, None]:
        """Parse the Case Detail page and navigate to the Document List."""
        raw = CaseDetailParser()(page)[0].raw_data
        detail_fields = {
            "case_name": raw.get("case_name"),
            "originating_court_index": raw.get("originating_court_index"),
            "originating_court_name": raw.get("originating_court_name"),
            "originating_court_judge": raw.get("originating_court_judge"),
            "date_order_appealing_from": raw.get("date_order_appealing_from"),
            "date_notice_of_appeal": raw.get("date_notice_of_appeal"),
            "date_order_entered": raw.get("date_order_entered"),
            "date_notice_of_appeal_filed": raw.get(
                "date_notice_of_appeal_filed"
            ),
            "requested_argument_time": raw.get("requested_argument_time"),
            # Flatten nested deferred party/attorney records to plain dicts
            # so they survive the JSON round-trip through accumulated_data.
            "parties": [
                self._party_to_dict(p) for p in raw.get("parties") or []
            ],
        }

        docket_id = accumulated_data["iapps_internal_docket_id"]
        yield Request(
            request=HTTPRequestParams(
                method=HttpMethod.GET,
                url=urljoin(
                    response.url,
                    f"DocumentList?docketId={docket_id}&display=all",
                ),
            ),
            continuation=self.parse_document_list,
            accumulated_data={
                **accumulated_data,
                "detail_fields": detail_fields,
            },
            deduplication_key=f"document_list:{docket_id}",
        )

    @staticmethod
    def _party_to_dict(party_dv) -> dict:
        """Flatten a deferred ``NYSCEFParty`` (with nested attorneys)."""
        raw = party_dv.raw_data
        return {
            **raw,
            "attorneys": [a.raw_data for a in raw.get("attorneys") or []],
        }

    # =================================================================
    # Document list
    # =================================================================

    @step(priority=2)
    def parse_document_list(
        self,
        page: PageElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[_Yield], None, None]:
        """Parse the Document List, emit the case, and fan out downloads."""
        documents: list[dict] = []
        for dv in DocumentListParser()(page):
            doc = dv.raw_data
            # Resolve relative document URLs against the page.
            if doc.get("download_url"):
                doc["download_url"] = urljoin(
                    response.url, doc["download_url"]
                )
            if doc.get("confirmation_notice_url"):
                doc["confirmation_notice_url"] = urljoin(
                    response.url, doc["confirmation_notice_url"]
                )
            documents.append(doc)

        # Emit the assembled case.
        yield ParsedData(
            self._build_case(accumulated_data, documents, response.url)
        )

        # Fan out archive downloads. Each needs a ViaLink so the Playwright
        # driver clicks the <a> on this DocumentList page (direct GETs are
        # blocked). archive=True auto-assigns priority 1.
        docket_id = accumulated_data["iapps_internal_docket_id"]
        for doc in documents:
            if doc.get("download_url"):
                yield self._download_request(
                    docket_id,
                    doc["entry_number"],
                    doc["document_type"],
                    doc["download_url"],
                    selector_kind="ViewDocument",
                )
            if doc.get("confirmation_notice_url"):
                yield self._download_request(
                    docket_id,
                    doc["entry_number"],
                    "CONFIRMATION NOTICE",
                    doc["confirmation_notice_url"],
                    selector_kind="ConfirmationNotice",
                )

    @step(
        await_list=[WaitForLoadState("networkidle", timeout=60000)],
    )
    def handle_document_download(
        self,
        local_filepath: str | None,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[_Yield], None, None]:
        """Emit an ``NYSCEFDownloadedDocument`` for a downloaded file."""
        yield ParsedData(
            data=NYSCEFDownloadedDocument.raw(
                iapps_internal_docket_id=accumulated_data[
                    "iapps_internal_docket_id"
                ],
                entry_number=accumulated_data["entry_number"],
                document_type=accumulated_data["document_type"],
                download_url=accumulated_data["download_url"],
                local_path=local_filepath,
            )
        )

    # =================================================================
    # Helpers
    # =================================================================

    def _download_request(
        self,
        docket_id: str,
        entry_number: int,
        document_type: str,
        url: str,
        *,
        selector_kind: str,
    ) -> Request:
        """Build an archive download Request via a ViaLink click."""
        index = extract_query_param(url, "docIndex", "docId") or ""
        return Request(
            request=HTTPRequestParams(method=HttpMethod.GET, url=url),
            via=ViaLink(
                selector=CSS(f'a[href*="{selector_kind}"][href*="{index}"]'),
                description=f"document #{entry_number} download",
            ),
            archive=True,
            expected_type="pdf",
            continuation=self.handle_document_download,
            accumulated_data={
                "iapps_internal_docket_id": docket_id,
                "entry_number": entry_number,
                "document_type": document_type,
                "download_url": url,
            },
            deduplication_key=f"document:{docket_id}:{entry_number}:{index}",
        )

    @staticmethod
    def _build_case(
        accumulated_data: dict,
        documents: list[dict],
        source_url: str,
    ):
        """Assemble the final ``NYSCEFCase`` from the accumulated pages."""
        grid = accumulated_data.get("grid_fields", {})
        detail = accumulated_data.get("detail_fields", {})
        court = (
            accumulated_data.get("court")
            or grid.get("court")
            or COURT_NAME_TO_ID.get(grid.get("court_name_raw") or "")
            or ""
        )
        return NYSCEFCase.raw(
            docket_number=grid.get("docket_number")
            or accumulated_data.get("docket_number")
            or "",
            court=court,
            court_name_raw=grid.get("court_name_raw"),
            iapps_internal_docket_id=accumulated_data.get(
                "iapps_internal_docket_id"
            ),
            case_name=detail.get("case_name"),
            case_name_short=grid.get("case_name_short"),
            case_type=grid.get("case_type"),
            efiling_status=grid.get("efiling_status"),
            date_received=grid.get("date_received"),
            originating_court_index=detail.get("originating_court_index"),
            originating_court_name=detail.get("originating_court_name"),
            originating_court_judge=detail.get("originating_court_judge"),
            date_order_appealing_from=detail.get("date_order_appealing_from"),
            date_notice_of_appeal=detail.get("date_notice_of_appeal"),
            date_order_entered=detail.get("date_order_entered"),
            date_notice_of_appeal_filed=detail.get(
                "date_notice_of_appeal_filed"
            ),
            requested_argument_time=detail.get("requested_argument_time"),
            parties=detail.get("parties", []),
            docket_entries=documents,
            source_url=source_url,
            source_entry_point=accumulated_data.get("entry_point"),
        )
