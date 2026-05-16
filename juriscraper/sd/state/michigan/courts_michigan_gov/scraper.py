"""Michigan appellate courts scraper (courts.michigan.gov).

Scrapes case listings from
https://www.courts.michigan.gov/case-search/ for the Michigan Court of
Appeals (``michctapp``) and Michigan Supreme Court (``mich``).

The site is an Episerver SPA whose listing endpoints return JSON
directly when called with the SSR query parameters
``?expand=*&currentPageUrl=%2Fcase-search%2F``. Pagination uses
``page=N`` with ``pageSize`` capped at 100. There is no date-range
filter parameter — the scraper walks ``sortOrder=Newest`` and stops when
the oldest item on a page falls before the requested window.

The per-case detail JSON endpoints (``/c/courts/get*casedetaildata/...``)
are gated by an invisible hCaptcha JWT in a custom ``captchatoken``
header. That step is intentionally not implemented here; v1 yields
listing-derived ``MichDocket`` records only.

See ``DESIGN.md`` for the full investigation.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING, ClassVar
from urllib.parse import urlencode

from jkent.common.decorators import entry, step
from jkent.common.param_models import DateRange, SpeculativeRange
from jkent.data_types import (
    BaseScraper,
    HttpMethod,
    HTTPRequestParams,
    ParsedData,
    Request,
    Response,
    ScraperStatus,
    SkipDeduplicationCheck,
)
from pyrate_limiter import Duration, Rate

from .models import COURT_IDS, SITE_COURT_NAME, MichDocket, MichTrialCourtRef

if TYPE_CHECKING:
    from collections.abc import Generator

    from jkent.data_types import ScraperYield


SITE_BASE = "https://www.courts.michigan.gov"
LISTING_PATH = "/case-search/"
SINGLE_CASE_API = f"{SITE_BASE}/api/CaseSearch/AdvancedSearchCaseDetails"

# Maximum pageSize honoured by the listing API. Anything larger is
# silently clamped to 10 (the default).
MAX_PAGE_SIZE = 100


def _build_listing_url(
    *,
    site_court: str,
    page: int,
    page_size: int = MAX_PAGE_SIZE,
    sort_order: str = "Newest",
) -> str:
    params = {
        "page": page,
        "resultType": "cases",
        "sortOrder": sort_order,
        "pageSize": page_size,
        "aAppellateCourt": site_court,
        "expand": "*",
        "currentPageUrl": LISTING_PATH,
    }
    return f"{SITE_BASE}{LISTING_PATH}?{urlencode(params)}"


def _parse_filing_date(value: str | None) -> date | None:
    """Parse the listing API's filing date.

    The listing returns ISO-8601 strings of the form
    ``2026-04-30T04:00:00+00:00`` or ``...Z``. Only the date portion
    matters for windowing; offsets are stripped.
    """
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except (TypeError, ValueError):
        return None


class MichiganCourtsScraper(BaseScraper[MichDocket]):
    """Scraper for Michigan appellate court dockets.

    The Michigan judicial site lacks a date-range search parameter, so
    each date-bounded entry walks the Newest-sorted listing forwards
    until the oldest item on a page is older than the requested start.

    Per-case detail (parties, attorneys, dockets, judges, judgments) is
    behind an hCaptcha gate and not collected by this scraper.
    """

    # === Metadata ===
    court_ids: ClassVar[set[str]] = set(COURT_IDS.keys())
    court_url: ClassVar[str] = f"{SITE_BASE}{LISTING_PATH}"
    data_types: ClassVar[set[str]] = {"dockets"}
    status: ClassVar[ScraperStatus] = ScraperStatus.IN_DEVELOPMENT
    version: ClassVar[str] = "2026-05-03"
    requires_auth: ClassVar[bool] = False

    # The listing API is light to call but the site is a high-traffic
    # public service; keep request rate conservative.
    rate_limits: ClassVar[list[Rate] | None] = [Rate(1, Duration.SECOND)]

    # =========================================================================
    # Date-bounded entry points
    # =========================================================================

    @entry(MichDocket)
    def get_coa_dockets_by_date(
        self, date_range: DateRange
    ) -> Generator[Request, None, None]:
        """Walk Court of Appeals listings filtered to a date range."""
        yield self._yield_first_listing_page("michctapp", date_range)

    @entry(MichDocket)
    def get_msc_dockets_by_date(
        self, date_range: DateRange
    ) -> Generator[Request, None, None]:
        """Walk Supreme Court listings filtered to a date range."""
        yield self._yield_first_listing_page("mich", date_range)

    def _yield_first_listing_page(
        self, court_id: str, date_range: DateRange
    ) -> Request:
        site_court = SITE_COURT_NAME[court_id]
        url = _build_listing_url(site_court=site_court, page=1)
        return Request(
            request=HTTPRequestParams(
                method=HttpMethod.GET,
                url=url,
                headers={"Accept": "application/json"},
            ),
            continuation=self.parse_listing_page,
            nonnavigating=True,
            accumulated_data={
                "court_id": court_id,
                "site_court": site_court,
                "page": 1,
                "start": date_range.start.isoformat(),
                "end": date_range.end.isoformat(),
            },
            deduplication_key=SkipDeduplicationCheck(),
        )

    # =========================================================================
    # Speculative single-case entry points
    # =========================================================================

    @entry(MichDocket)
    def fetch_coa_docket(self, rid: SpeculativeRange) -> Request:
        """Speculative fetch by COA case number (bare integer)."""
        return self._build_speculative_request("michctapp", rid.min)

    @entry(MichDocket)
    def fetch_msc_docket(self, rid: SpeculativeRange) -> Request:
        """Speculative fetch by Supreme Court case number (bare integer)."""
        return self._build_speculative_request("mich", rid.min)

    def _build_speculative_request(self, court_id: str, n: int) -> Request:
        params = {
            "aCaseId": str(n),
            "aAppellateCourt": SITE_COURT_NAME[court_id],
        }
        url = f"{SINGLE_CASE_API}?{urlencode(params)}"
        return Request(
            request=HTTPRequestParams(
                method=HttpMethod.GET,
                url=url,
                headers={
                    "Accept": "application/json",
                    "captchatoken": "",
                },
            ),
            continuation=self.parse_single_case,
            nonnavigating=True,
            accumulated_data={
                "court_id": court_id,
                "docket_id": str(n),
            },
            deduplication_key=f"mi-{court_id}-{n}",
        )

    # =========================================================================
    # Step 1: parse a listing page (paginates forward through Newest)
    # =========================================================================

    @step()
    def parse_listing_page(
        self,
        json_content: dict,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[MichDocket], None, None]:
        """Yield one ``MichDocket`` per searchItem and a next-page request.

        Stops paginating once the oldest item on a page is older than
        the configured ``start`` date (since the API sorts by Newest).
        """
        court_id: str = accumulated_data["court_id"]
        site_court: str = accumulated_data["site_court"]
        page_num: int = accumulated_data["page"]
        start = date.fromisoformat(accumulated_data["start"])
        end = date.fromisoformat(accumulated_data["end"])

        results = (json_content.get("caseSearchResults") or {}).get(
            "caseDetailResults"
        ) or {}
        items: list[dict] = results.get("searchItems") or []
        total_pages = results.get("totalPages") or 1

        oldest_on_page: date | None = None

        for item in items:
            filing_date = _parse_filing_date(item.get("filingDate"))
            if filing_date is None:
                continue
            if oldest_on_page is None or filing_date < oldest_on_page:
                oldest_on_page = filing_date

            if filing_date < start or filing_date > end:
                continue

            docket = self._build_docket_from_listing_item(
                item, court_id=court_id
            )
            if docket is not None:
                yield ParsedData(data=docket)

        # Decide whether to fetch the next page. We continue while the
        # oldest filing date on the current page is on-or-after the
        # window's start (Newest sort means later pages only get older).
        if (
            page_num < total_pages
            and oldest_on_page is not None
            and oldest_on_page >= start
        ):
            next_page = page_num + 1
            yield Request(
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url=_build_listing_url(
                        site_court=site_court, page=next_page
                    ),
                    headers={"Accept": "application/json"},
                ),
                continuation=self.parse_listing_page,
                nonnavigating=True,
                accumulated_data={
                    **accumulated_data,
                    "page": next_page,
                },
                deduplication_key=SkipDeduplicationCheck(),
            )

    # =========================================================================
    # Step 2: parse a single-case lookup response
    # =========================================================================

    @step()
    def parse_single_case(
        self,
        json_content: dict,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[MichDocket], None, None]:
        """Yield a docket from the single-case ``aCaseId`` API response."""
        court_id: str = accumulated_data["court_id"]
        results = (json_content.get("caseDetailResults") or {}).get(
            "searchItems"
        ) or []
        if not results:
            return

        # ``aCaseId`` may match multiple court systems (the same matter
        # can sit on COA + MSC + COC); pick the row that actually carries
        # the requested court's case number.
        chosen = self._pick_court_row(results, court_id)
        if chosen is None:
            return

        docket = self._build_docket_from_listing_item(
            chosen, court_id=court_id
        )
        if docket is not None:
            yield ParsedData(data=docket)

    # =========================================================================
    # Helpers
    # =========================================================================

    @staticmethod
    def _pick_court_row(rows: list[dict], court_id: str) -> dict | None:
        key = (
            "courtOfAppealsCaseNumber"
            if court_id == "michctapp"
            else "supremeCourtCaseNumber"
        )
        for row in rows:
            if row.get(key):
                return row
        return rows[0] if rows else None

    @staticmethod
    def _build_docket_from_listing_item(
        item: dict, *, court_id: str
    ) -> MichDocket | None:
        if court_id == "michctapp":
            num = item.get("courtOfAppealsCaseNumber")
            status = item.get("courtOfAppealsCaseStatus")
        else:
            num = item.get("supremeCourtCaseNumber")
            status = item.get("supremeCourtCaseStatus")

        if not num:
            return None

        filing_date = _parse_filing_date(item.get("filingDate"))

        case_url = item.get("caseUrl") or ""
        source_url = (
            f"{SITE_BASE}{case_url}" if case_url.startswith("/") else case_url
        )

        trial_courts = [
            MichTrialCourtRef(name=c)
            for c in (item.get("courts") or [])
            if isinstance(c, str) and c.strip()
        ]

        coc_raw = item.get("courtOfClaimsCaseNumber")
        coc_case_number = (
            coc_raw if isinstance(coc_raw, str) and coc_raw.strip() else None
        )

        return MichDocket(
            docket_id=str(num),
            court_id=court_id,
            date_filed=filing_date,
            case_name=(item.get("title") or "").strip()
            or f"{court_id.upper()} {num}",
            case_status=(status or None),
            has_opinions=item.get("hasOpinions"),
            has_orders=item.get("hasOrders"),
            coa_case_number=item.get("courtOfAppealsCaseNumber"),
            msc_case_number=item.get("supremeCourtCaseNumber"),
            coc_case_number=coc_case_number,
            trial_courts=trial_courts,
            source_url=source_url or None,
        )
