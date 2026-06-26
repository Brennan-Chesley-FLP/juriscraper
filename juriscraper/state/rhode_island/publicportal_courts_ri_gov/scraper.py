"""Rhode Island Judiciary Public Portal scraper.

Scrapes appellate dockets from the Supreme Court of Rhode Island
via the Tyler Odyssey Public Portal at
``https://publicportal.courts.ri.gov/PublicPortal/Home/Dashboard/29``.

The portal is reCAPTCHA-gated and shielded by DataDome at the edge —
both require Playwright. The driver requirements
(``JS_EVAL`` + ``CHROME_ALIKE`` + ``RCAP_HANDLER``) cause kent to drive
a real browser through DataDome and to solve the reCAPTCHA before each
form submit.

Per-page HTML extraction lives in the ``parsers`` package
(``SearchResultsParser``); the steps keep navigation concerns (the GET
that renders the form, the reCAPTCHA-solving ``form.submit()``, and
absolutising each result row's case-detail URL).

Entry points (§4):
    - dockets_by_number(docket_number)  — speculative single-case lookup
      at the Rhode Island Supreme Court (single court, ``ri``).

Flow:
    entry → submit_search_form → parse_search_results → ParsedData
"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar
from urllib.parse import urljoin

from jkent.common.decorators import entry, step
from jkent.common.param_models import SpeculativeRange
from jkent.data_types import (
    BaseScraper,
    DriverRequirement,
    HttpMethod,
    HTTPRequestParams,
    ParsedData,
    Request,
    Response,
    ScraperStatus,
    WaitForSelector,
)
from pyrate_limiter import Duration, Rate

from .models import (
    COURT_ID,
    DASHBOARD_URL,
    PORTAL_URL,
    RI_COURTS,
    RIDocket,
)
from .parsers import SearchResultsParser

if TYPE_CHECKING:
    from collections.abc import Generator

    from jkent.common.page_element import PageElement
    from jkent.data_types import ScraperYield


# XPath for the Smart Search form. The form has no id on this Tyler
# build, so we identify it by its action URL — unique on the page.
SEARCH_FORM_XPATH = (
    "//form[contains(@action, 'SmartSearch/SmartSearch/SmartSearch')]"
)


class RhodeIslandPublicPortalScraper(BaseScraper[RIDocket]):
    """Scraper for the Supreme Court of Rhode Island via the Tyler
    Odyssey Public Portal.

    v1 supports speculative single-case lookups by docket number.
    See ``CC_NOTES.md`` for the v2 roadmap (date-range entry, full
    case-detail parse, document downloads).
    """

    # === Metadata ===
    court_ids: ClassVar[set[str]] = set(RI_COURTS.keys())
    court_url: ClassVar[str] = DASHBOARD_URL
    data_types: ClassVar[set[str]] = {"dockets"}
    status: ClassVar[ScraperStatus] = ScraperStatus.IN_DEVELOPMENT
    version: ClassVar[str] = "2026-06-27"
    last_verified: ClassVar[str] = "2026-05-04"
    requires_auth: ClassVar[bool] = False
    driver_requirements: ClassVar[list[DriverRequirement]] = [
        DriverRequirement.JS_EVAL,
        DriverRequirement.CHROME_ALIKE,
        DriverRequirement.RCAP_HANDLER,
    ]
    rate_limits: ClassVar[list[Rate] | None] = [Rate(1, Duration.SECOND)]

    # =========================================================================
    # Entry point — speculative by case number, Supreme Court only.
    #
    # Rhode Island has a single appellate court (``ri``), so this is the
    # single-court speculative shape: a plain ``SpeculativeRange`` and a
    # fixed court id. (No ``court_ids`` argument — a speculative entry is
    # dispatched with only its speculative param; see SCRAPER_STANDARDS §4
    # "Multi-court speculative entries".)
    # =========================================================================

    @entry(RIDocket)
    def dockets_by_number(
        self, docket_number: SpeculativeRange
    ) -> Generator[Request, None, None]:
        """Speculative single-case lookup at the Rhode Island Supreme Court.

        The site's "Smart Search" box accepts a free-text docket number.
        Operators seed ``SpeculativeRange`` with the appropriate sequence;
        this scraper passes the integer through unchanged so the seed
        format can match whichever docket-number convention is in use
        (legacy ``YYYY-NNN-Appeal.`` or Tyler-internal forms — see
        ``CC_NOTES.md``).

        The GET renders the search form; ``submit_search_form`` then fills
        and POSTs it (with the reCAPTCHA token inserted by
        ``RCAP_HANDLER``).
        """
        query = str(docket_number.number)
        yield Request(
            request=HTTPRequestParams(
                method=HttpMethod.GET,
                url=DASHBOARD_URL,
            ),
            continuation=self.submit_search_form,
            accumulated_data={
                "court_id": COURT_ID,
                "case_number_query": query,
                "entry_point": "dockets_by_number",
            },
            deduplication_key=f"submit_search_form:{query}",
        )

    # =========================================================================
    # Step 1: fill and submit the search form.
    # =========================================================================

    @step(priority=3)
    def submit_search_form(
        self,
        page: PageElement,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[RIDocket], None, None]:
        """Fill SearchCriteria + CourtLocation and submit the form.

        ``RCAP_HANDLER`` injects a fresh ``g-recaptcha-response`` token
        before the POST is dispatched; all other hidden fields
        (``Settings.CaptchaEnabled``, ``caseCriteria.SearchBy``, …) are
        preserved automatically by ``find_form().submit()``.
        """
        court_id = accumulated_data["court_id"]
        court_location = RI_COURTS[court_id]
        case_number_query = accumulated_data["case_number_query"]

        form = page.find_form(SEARCH_FORM_XPATH, "smart search form")
        yield form.submit(
            data={
                "caseCriteria.SearchCriteria": case_number_query,
                "caseCriteria.CourtLocation": court_location,
                "caseCriteria.CourtLocation_input": court_location,
            },
            continuation=self.parse_search_results,
            accumulated_data=accumulated_data,
            deduplication_key=f"parse_search_results:{case_number_query}",
        )

    # =========================================================================
    # Step 2: parse the rendered search-results page.
    # =========================================================================

    @step(
        priority=2,
        await_list=[
            WaitForSelector(
                "table, .k-grid, .ssSearchResultList, .smartSearchResults",
                timeout=15000,
            ),
        ],
    )
    def parse_search_results(
        self,
        page: PageElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[RIDocket], None, None]:
        """Extract one ``RIDocket`` per match from the result table.

        ``SearchResultsParser`` owns the row extraction; the step stamps
        the fields not present on the row (``court``,
        ``source_entry_point``) and absolutises the relative case-detail
        href against the response URL. ``raw_data`` returns a copy, so we
        re-wrap with the merged fields rather than mutating the parser's
        deferred value in place.

        An empty result set is a speculative miss (no case found for this
        number) — the parser returns no rows and nothing is emitted.
        """
        court_id = accumulated_data["court_id"]
        entry_point = accumulated_data.get("entry_point")

        for deferred in SearchResultsParser()(page):
            raw = dict(deferred.raw_data)
            raw["court"] = court_id
            raw["source_entry_point"] = entry_point
            href = raw.get("source_url")
            if href:
                raw["source_url"] = urljoin(response.url or PORTAL_URL, href)
            yield ParsedData(RIDocket.raw(**raw))
