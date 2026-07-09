"""Michigan appellate courts scraper (courts.michigan.gov).

Site: https://www.courts.michigan.gov/case-search/

Scrapes case listings and full case detail for the Michigan Court of
Appeals (``michctapp``) and Michigan Supreme Court (``mich``). The site is
an Episerver SSR SPA fronted by Cloudflare; the per-case detail JSON
(``/c/courts/get*casedetaildata/{id}``) is gated by an *invisible*
execute-mode hCaptcha (a JWT the SPA mints per page-load and sends in a
``captchatoken`` header).

Rather than forge that token, this scraper runs under a real browser
(``JS_EVAL`` + ``FF_ALIKE`` + ``HCAP_HANDLER`` → Camoufox) and lets the SPA
mint it: it navigates to a page and **promotes** the JSON the page fetches
in the background, using the driver's ``Request.incidental`` mechanism
(``Singular(...)`` matches the captured XHR and its response is pre-resolved
into a follow-up request without a second network round-trip). Because the
whole scraper is browser-bound, even the listing JSON is obtained this way:
navigate to the listing URL with ``Accept: application/json`` and promote the
document response.

Flow:
    dockets_by_filing_date → (listing nav) → promote_listing
        → parse_listing_page ──(per in-window case)→ (detail nav) → promote_detail
        │                    └─(next page)→ promote_listing → parse_listing_page
        └ (detail nav) → promote_detail → parse_case_detail → ParsedData

    dockets_by_number → (detail nav) → promote_detail → parse_case_detail
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING, ClassVar
from urllib.parse import urlencode

from jkent.common.decorators import entry, step
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
    Singular,
    SkipDeduplicationCheck,
    WaitForLoadState,
)
from pyrate_limiter import Duration, Rate

from juriscraper.state.common.params import CourtRange, InferrableDateRange

from .models import (
    COURT_IDS,
    LISTING_PATH,
    LISTING_URL,
    MAX_PAGE_SIZE,
    SITE_BASE,
    SITE_COURT_NAME,
    MichDocket,
)
from .parsers import CaseDetailParser
from .parsers._common import parse_filing_date

if TYPE_CHECKING:
    from collections.abc import Generator

    from jkent.data_types import ScraperYield

# CourtListener court id → the ``/c/courts/{seg}/case/{n}`` path segment for
# the detail page (which, once loaded, fires the gated ``casedetaildata`` XHR).
COURT_PATH_SEGMENT: dict[str, str] = {"michctapp": "coa", "mich": "msc"}

# Incidental-match globs. The listing URL is hit twice per navigation — once
# as the SSR ``document`` (text/html shell) and once as the SPA's client-side
# ``fetch`` (the ``application/json`` we want) — so the listing match pins
# ``resource_type="fetch"`` to select the JSON. The detail XHR path is
# unambiguous: ``...casedetaildata/{id}`` (``getcourtofappeals...`` /
# ``getmichigansupreme...``), distinct from the ``/case/{id}`` document URL.
LISTING_MATCH = "*/case-search/*resultType=cases*"
DETAIL_MATCH = "*casedetaildata*"

# Wait for the page's background fetches (the SSR document / the gated detail
# XHR) to settle before the transport snapshots and persists incidentals.
_SETTLE = WaitForLoadState("networkidle", timeout=60000)


class MichCourtRange(CourtRange):
    """A ``CourtRange`` carrying the target court for the speculative
    single-case lookup (the court rides on the range, §4)."""

    def search_key(self) -> str:
        return SITE_COURT_NAME[self.court_id]


def _build_listing_url(
    *,
    site_court: str,
    page: int,
    page_size: int = MAX_PAGE_SIZE,
    sort_order: str = "Newest",
) -> str:
    """Build the SSR listing URL that returns JSON under ``Accept: json``."""
    params = {
        "page": page,
        "resultType": "cases",
        "sortOrder": sort_order,
        "pageSize": page_size,
        "aAppellateCourt": site_court,
        "expand": "*",
        "currentPageUrl": LISTING_PATH,
    }
    return f"{LISTING_URL}?{urlencode(params)}"


def _detail_page_url(court: str, number: int | str) -> str:
    """Build the case-detail *page* URL for one court + site case number."""
    return f"{SITE_BASE}/c/courts/{COURT_PATH_SEGMENT[court]}/case/{number}"


class MichiganCourtsScraper(BaseScraper[MichDocket]):
    """Scraper for Michigan appellate court dockets, with full case detail.

    The Michigan judicial site lacks a date-range search parameter, so the
    date-bounded entry walks the Newest-sorted listing forwards until the
    oldest item on a page is older than the requested start. Each in-window
    case is then enriched with the full (captcha-gated) case detail by
    navigating to its page and promoting the resulting detail XHR.
    """

    # === Metadata ===
    court_ids: ClassVar[set[str]] = set(COURT_IDS)
    court_url: ClassVar[str] = LISTING_URL
    data_types: ClassVar[set[str]] = {"dockets"}
    status: ClassVar[ScraperStatus] = ScraperStatus.IN_DEVELOPMENT
    version: ClassVar[str] = "2026-07-09"
    last_verified: ClassVar[str] = "2026-07-09"
    requires_auth: ClassVar[bool] = False
    # Runs under Camoufox: the case-detail JSON is gated by an invisible
    # hCaptcha JWT the SPA mints per page-load. We navigate a real browser and
    # promote the resulting XHR rather than forging the token. HCAP_HANDLER is
    # belt-and-suspenders in case the passive challenge ever escalates to a
    # visible widget; the detail flow itself needs no interaction.
    driver_requirements: ClassVar[list[DriverRequirement]] = [
        DriverRequirement.JS_EVAL,
        DriverRequirement.FF_ALIKE,
        DriverRequirement.HCAP_HANDLER,
    ]
    # A high-traffic public service, and every case is now a browser
    # navigation; keep it conservative.
    rate_limits: ClassVar[list[Rate] | None] = [Rate(1, Duration.SECOND)]

    # =========================================================================
    # Entry points (§4)
    # =========================================================================

    @entry(MichDocket)
    def dockets_by_filing_date(
        self, court_ids: set[str], date_range: InferrableDateRange
    ) -> Generator[Request, None, None]:
        """Walk each requested court's listing newest-first over a window.

        The site has no server-side date filter, so each court's ``Newest``
        listing is paginated forward and stops once the oldest item on a page
        falls before ``date_range.start``. Each in-window case is enriched
        with full detail (see :meth:`parse_listing_page`).
        """
        for court_id in sorted(court_ids & self.court_ids):
            yield self._listing_nav(court_id, date_range, page=1)

    @entry(MichDocket)
    def dockets_by_number(
        self, docket_number: MichCourtRange
    ) -> Generator[Request, None, None]:
        """Speculative single-case lookup by site case number.

        Navigates straight to the case-detail page and promotes its detail
        XHR, yielding a fully-populated docket. The court rides on the
        ``MichCourtRange`` (§4 multi-court speculative); seed one per court.
        """
        yield self._detail_nav(
            docket_number.court_id,
            docket_number.min,
            entry_point="dockets_by_number",
        )

    # =========================================================================
    # Request builders
    # =========================================================================

    def _listing_nav(
        self, court_id: str, date_range: DateRange, *, page: int
    ) -> Request:
        """Navigate to one listing page (its JSON document is promoted next)."""
        site_court = SITE_COURT_NAME[court_id]
        return Request(
            request=HTTPRequestParams(
                method=HttpMethod.GET,
                url=_build_listing_url(site_court=site_court, page=page),
                # The document navigation returns the HTML SPA shell (the
                # server serves HTML to top-level navigations regardless of
                # Accept); the SPA then fires the listing JSON as a client-side
                # fetch, which promote_listing promotes.
            ),
            continuation=self.promote_listing,
            accumulated_data={
                "court_id": court_id,
                "site_court": site_court,
                "page": page,
                "start": date_range.start.isoformat(),
                "end": date_range.end.isoformat(),
                "entry_point": "dockets_by_filing_date",
            },
            # Pagination pages depend on the live Newest ordering; never dedup.
            deduplication_key=SkipDeduplicationCheck(),
        )

    def _detail_nav(
        self, court_id: str, number: int | str, *, entry_point: str
    ) -> Request:
        """Navigate to one case-detail page (its XHR is promoted next)."""
        return Request(
            request=HTTPRequestParams(
                method=HttpMethod.GET,
                url=_detail_page_url(court_id, number),
            ),
            continuation=self.promote_detail,
            accumulated_data={
                "court_id": court_id,
                "docket_number": str(number),
                "entry_point": entry_point,
            },
            deduplication_key=f"detail_nav:{court_id}:{number}",
        )

    # =========================================================================
    # Promote steps — turn a navigation's captured XHR into a data request
    # =========================================================================

    @step(priority=4, await_list=[_SETTLE])
    def promote_listing(
        self, response: Response, accumulated_data: dict
    ) -> Generator[Request, None, None]:
        """Promote the listing-page JSON document captured by the navigation."""
        yield Request(
            request=HTTPRequestParams(method=HttpMethod.GET, url=response.url),
            incidental=Singular(url=LISTING_MATCH, resource_type="fetch"),
            continuation=self.parse_listing_page,
            nonnavigating=True,
            accumulated_data=dict(accumulated_data),
            deduplication_key=SkipDeduplicationCheck(),
        )

    @step(priority=2, await_list=[_SETTLE])
    def promote_detail(
        self, response: Response, accumulated_data: dict
    ) -> Generator[Request, None, None]:
        """Promote the gated case-detail XHR captured by the navigation."""
        court_id = accumulated_data["court_id"]
        number = accumulated_data["docket_number"]
        yield Request(
            request=HTTPRequestParams(method=HttpMethod.GET, url=response.url),
            incidental=Singular(url=DETAIL_MATCH),
            continuation=self.parse_case_detail,
            nonnavigating=True,
            accumulated_data=dict(accumulated_data),
            deduplication_key=f"detail:{court_id}:{number}",
        )

    # =========================================================================
    # Parse steps
    # =========================================================================

    @step(priority=3)
    def parse_listing_page(
        self,
        json_content: dict,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[MichDocket], None, None]:
        """Fan out a detail fetch per in-window case, then the next page.

        Stops paginating once the oldest item on a page is older than the
        configured ``start`` date (Newest sort → later pages only get older).
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
        number_key = (
            "courtOfAppealsCaseNumber"
            if court_id == "michctapp"
            else "supremeCourtCaseNumber"
        )

        for item in items:
            number = item.get(number_key)
            if not number:
                continue
            filing_date = parse_filing_date(item.get("filingDate"))
            if filing_date is not None and (
                oldest_on_page is None or filing_date < oldest_on_page
            ):
                oldest_on_page = filing_date

            if filing_date is None or filing_date < start or filing_date > end:
                continue

            # Enrich every in-window case with its full (gated) detail.
            yield self._detail_nav(
                court_id, number, entry_point="dockets_by_filing_date"
            )

        # Continue while the oldest filing date on this page is on-or-after the
        # window start (Newest sort means later pages only get older).
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
                ),
                continuation=self.promote_listing,
                accumulated_data={**accumulated_data, "page": next_page},
                deduplication_key=SkipDeduplicationCheck(),
            )

    @step(priority=1)
    def parse_case_detail(
        self,
        json_content: dict,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[MichDocket], None, None]:
        """Parse the promoted case-detail JSON into a full ``MichDocket``."""
        court_id: str = accumulated_data["court_id"]
        deferred = CaseDetailParser(court_id)(json_content)
        if not deferred:
            return
        raw = deferred[0].raw_data
        raw["source_entry_point"] = accumulated_data.get("entry_point")
        if not raw.get("source_url"):
            raw["source_url"] = _detail_page_url(
                court_id, accumulated_data.get("docket_number", "")
            )
        yield ParsedData(MichDocket.raw(**raw))
