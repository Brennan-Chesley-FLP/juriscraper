"""Michigan appellate courts scraper (courts.michigan.gov).

Site: https://www.courts.michigan.gov/case-search/

Scrapes case listings for the Michigan Court of Appeals (``michctapp``)
and Michigan Supreme Court (``mich``). The site is an Episerver SPA whose
listing endpoints return JSON directly when called with the SSR query
parameters ``?expand=*&currentPageUrl=%2Fcase-search%2F``. Pagination
uses ``page=N`` with ``pageSize`` capped at 100. There is no date-range
filter parameter — the scraper walks ``sortOrder=Newest`` and stops once
the oldest item on a page falls before the requested window.

The per-case detail JSON endpoints (``/c/courts/get*casedetaildata/...``)
are gated by an invisible hCaptcha JWT in a custom ``captchatoken``
header. That step is intentionally not implemented here; this version
yields listing-derived ``MichDocket`` records only.

This is a pure-JSON scraper, so per-item extraction lives in the
``parsers`` package as a JSON parser (``ListingItemParser``, see §9 note
there) rather than an HTML ``JKentParser``; the steps keep navigation
concerns (pagination, the per-court fan-out, the single-case lookup).

Entry points (§4):
    - dockets_by_filing_date(court_ids, date_range) — walk the Newest
      listing per requested court, stopping at the window start.
    - dockets_by_number(court_ids, docket_number)   — speculative single
      lookup by site case number, court carried in a ``CourtRange``.

Flow:
    dockets_by_filing_date → parse_listing_page ──→ ParsedData (per item)
                                    └─(next page)→ parse_listing_page
    dockets_by_number ─────────→ parse_single_case → ParsedData
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
    SkipDeduplicationCheck,
)
from pyrate_limiter import Duration, Rate

from juriscraper.state.common.params import CourtRange

from .models import (
    COURT_IDS,
    LISTING_PATH,
    LISTING_URL,
    MAX_PAGE_SIZE,
    SINGLE_CASE_API,
    SITE_COURT_NAME,
    MichDocket,
)
from .parsers import ListingItemParser

if TYPE_CHECKING:
    from collections.abc import Generator

    from jkent.data_types import ScraperYield


class MichCourtRange(CourtRange):
    """A ``CourtRange`` that translates a CL court id to the site's
    ``aAppellateCourt`` search key for the single-case lookup."""

    def search_key(self) -> str:
        return SITE_COURT_NAME[self.court_id]


def _build_listing_url(
    *,
    site_court: str,
    page: int,
    page_size: int = MAX_PAGE_SIZE,
    sort_order: str = "Newest",
) -> str:
    """Build the SSR listing URL that returns JSON directly."""
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


class MichiganCourtsScraper(BaseScraper[MichDocket]):
    """Scraper for Michigan appellate court dockets.

    The Michigan judicial site lacks a date-range search parameter, so the
    date-bounded entry walks the Newest-sorted listing forwards until the
    oldest item on a page is older than the requested start.

    Per-case detail (parties, attorneys, register-of-actions, judges,
    judgments) is behind an invisible hCaptcha gate and not collected by
    this scraper; see ``CC_NOTES.md``.
    """

    # === Metadata ===
    court_ids: ClassVar[set[str]] = set(COURT_IDS)
    court_url: ClassVar[str] = LISTING_URL
    data_types: ClassVar[set[str]] = {"dockets"}
    status: ClassVar[ScraperStatus] = ScraperStatus.IN_DEVELOPMENT
    version: ClassVar[str] = "2026-06-27"
    last_verified: ClassVar[str] = "2026-05-03"
    requires_auth: ClassVar[bool] = False
    # Listing + single-case endpoints are plain HTTP JSON (no captcha, no
    # JS). The captcha-gated case-detail endpoints are out of scope.
    driver_requirements: ClassVar[list[DriverRequirement]] = []
    # Light to call, but a high-traffic public service; keep it conservative.
    rate_limits: ClassVar[list[Rate] | None] = [Rate(1, Duration.SECOND)]

    # =========================================================================
    # Entry points (§4)
    # =========================================================================

    @entry(MichDocket)
    def dockets_by_filing_date(
        self, court_ids: set[str], date_range: DateRange
    ) -> Generator[Request, None, None]:
        """Walk each requested court's listing newest-first over a window.

        The site has no server-side date filter, so each requested court's
        ``Newest``-sorted listing is paginated forward and stops once the
        oldest item on a page falls before ``date_range.start``.
        """
        for court_id in sorted(court_ids & self.court_ids):
            yield self._first_listing_page(court_id, date_range)

    @entry(MichDocket)
    def dockets_by_number(
        self, docket_number: MichCourtRange
    ) -> Generator[Request, None, None]:
        """Speculative single-case lookup by site case number.

        Multi-court speculative entry (§4): the court rides on the
        ``MichCourtRange`` (seed one per court) since the driver dispatches
        a speculative entry with only its speculative param.
        """
        yield self._single_case_request(
            docket_number.court_id, docket_number.min
        )

    def _first_listing_page(
        self, court_id: str, date_range: DateRange
    ) -> Request:
        """Build the page-1 listing request for one court."""
        site_court = SITE_COURT_NAME[court_id]
        return Request(
            request=HTTPRequestParams(
                method=HttpMethod.GET,
                url=_build_listing_url(site_court=site_court, page=1),
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
                "entry_point": "dockets_by_filing_date",
            },
            # Pagination postbacks are non-idempotent; skip the dedup check.
            deduplication_key=SkipDeduplicationCheck(),
        )

    def _single_case_request(self, court_id: str, n: int) -> Request:
        """Build the single-case lookup request for one site case id."""
        params = {
            "aCaseId": str(n),
            "aAppellateCourt": SITE_COURT_NAME[court_id],
        }
        return Request(
            request=HTTPRequestParams(
                method=HttpMethod.GET,
                url=f"{SINGLE_CASE_API}?{urlencode(params)}",
                headers={
                    "Accept": "application/json",
                    "captchatoken": "",
                },
            ),
            continuation=self.parse_single_case,
            nonnavigating=True,
            accumulated_data={
                "court_id": court_id,
                "docket_number": str(n),
                "entry_point": "dockets_by_number",
            },
            deduplication_key=f"single_case:{court_id}:{n}",
        )

    # =========================================================================
    # Step: parse a listing page (paginates forward through Newest)
    # =========================================================================

    @step(priority=3)
    def parse_listing_page(
        self,
        json_content: dict,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[MichDocket], None, None]:
        """Yield one ``MichDocket`` per in-window item and a next-page
        request.

        Stops paginating once the oldest item on a page is older than the
        configured ``start`` date (the API sorts Newest-first, so later
        pages only get older).
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

        parser = ListingItemParser(court_id)
        oldest_on_page: date | None = None

        for item in items:
            deferred = parser(item)
            if not deferred:
                continue
            filing_date = deferred[0].raw_data.get("date_filed")
            if filing_date is not None and (
                oldest_on_page is None or filing_date < oldest_on_page
            ):
                oldest_on_page = filing_date

            if filing_date is None or filing_date < start or filing_date > end:
                continue

            raw = deferred[0].raw_data
            raw["source_entry_point"] = accumulated_data.get("entry_point")
            yield ParsedData(MichDocket.raw(**raw))

        # Continue while the oldest filing date on this page is on-or-after
        # the window start (Newest sort means later pages only get older).
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
                accumulated_data={**accumulated_data, "page": next_page},
                deduplication_key=SkipDeduplicationCheck(),
            )

    # =========================================================================
    # Step: parse a single-case lookup response
    # =========================================================================

    @step(priority=2)
    def parse_single_case(
        self,
        json_content: dict,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[MichDocket], None, None]:
        """Yield a docket from the single-case ``aCaseId`` API response."""
        court_id: str = accumulated_data["court_id"]
        rows = (json_content.get("caseDetailResults") or {}).get(
            "searchItems"
        ) or []
        if not rows:
            return

        # ``aCaseId`` can match multiple court systems (the same matter may
        # sit on COA + MSC + COC); pick the row carrying the requested
        # court's case number.
        chosen = self._pick_court_row(rows, court_id)
        if chosen is None:
            return

        deferred = ListingItemParser(court_id)(chosen)
        if not deferred:
            return
        raw = deferred[0].raw_data
        raw["source_entry_point"] = accumulated_data.get("entry_point")
        if not raw.get("source_url"):
            raw["source_url"] = response.url
        yield ParsedData(MichDocket.raw(**raw))

    # =========================================================================
    # Helpers
    # =========================================================================

    @staticmethod
    def _pick_court_row(rows: list[dict], court_id: str) -> dict | None:
        """Pick the listing row that carries this court's case number."""
        key = (
            "courtOfAppealsCaseNumber"
            if court_id == "michctapp"
            else "supremeCourtCaseNumber"
        )
        for row in rows:
            if row.get(key):
                return row
        return rows[0] if rows else None
