"""New Mexico Case Lookup scraper.

Scrapes appellate dockets from the Tapestry-based case lookup portal at
https://caselookup.nmcourts.gov/caselookup/ for the two appellate courts:

- ``nm`` — New Mexico Supreme Court (case prefix ``S-1-SC-``)
- ``nmctapp`` — New Mexico Court of Appeals (case prefix ``A-1-CA-``)

The site has no usable date filter or party-name search for appellate cases,
so the scraper relies on **speculative entry** against ``S-1-SC-{N}`` /
``A-1-CA-{N}`` where ``{N}`` is a continuous integer sequence (no zero
padding — the form accepts the raw number). The two courts share one
speculative entry, ``dockets_by_number``; the target court rides inside the
speculative param (``NmCourtRange``, a shared ``CourtRange``) and is seeded
once per court so the driver advances each sequence independently
(SCRAPER_STANDARDS §4, "Multi-court speculative entries").

Per-page HTML extraction lives in the ``parsers`` package
(``CaseDetailParser``); the steps keep navigation concerns (disclaimer
acceptance, the search-form fetch, the search POST).

Per-case flow (one ``@entry`` invocation, one case):

  GET /caselookup/                              ← disclaimer or welcome
       │
       ▼
  bootstrap_session
       │
       ├── (disclaimer page) → form.submit() → fetch_search_form
       │                                         └─ GET search-form-url
       │                                              └─ parse_search_form
       │                                                   └─ form.submit()
       │                                                        └─ parse_case_detail
       │                                                             └─ ParsedData
       └── (welcome page — already accepted) → GET search-form-url → ...

After the first call's bootstrap, the same ``JSESSIONID`` cookie carries the
disclaimer-accepted state through the rest of the run, so subsequent calls
skip the disclaimer-form submit and run with three round-trips instead of
four.

Soft-404: missing case IDs return a 200 response containing the literal text
``No results found.``. The session can also expire, producing ``Stale
Session`` or ``Your session has timed out`` pages. ``fails_successfully``
treats all three as misses; the next entry call re-bootstraps from scratch.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from jkent.common.decorators import entry, step
from jkent.common.page_element import PageElement
from jkent.data_types import (
    BaseScraper,
    DriverRequirement,
    HttpMethod,
    HTTPRequestParams,
    ParsedData,
    Request,
    Response,
    ScraperStatus,
    XPath,
)
from pyrate_limiter import Duration, Rate

from juriscraper.state.common.params import CourtRange

from .models import (
    COURT_CONFIG,
    LANDING_URL,
    SEARCH_FORM_URL,
    NmDocket,
)
from .parsers import CaseDetailParser

if TYPE_CHECKING:
    from collections.abc import Generator

    from jkent.data_types import ScraperYield


class NmCourtRange(CourtRange):
    """``CourtRange`` carrying the New Mexico case-number components.

    New Mexico addresses each appellate court by a ``(court_type,
    court_location, case_category)`` triple (``S/1/SC`` for the Supreme
    Court, ``A/1/CA`` for the Court of Appeals). ``court_id`` carries the
    CourtListener id (the seed key); the components are derived from it via
    :data:`COURT_CONFIG`. ``from_int`` (driver advancement) preserves
    ``court_id`` because it copies via ``model_copy``.
    """

    @property
    def court_type(self) -> str:
        return COURT_CONFIG[self.court_id][0]

    @property
    def court_location(self) -> str:
        return COURT_CONFIG[self.court_id][1]

    @property
    def case_category(self) -> str:
        return COURT_CONFIG[self.court_id][2]


class NewMexicoCaseLookupScraper(BaseScraper[NmDocket]):
    """Scraper for the New Mexico Supreme Court and Court of Appeals.

    One speculative ``@entry`` (``dockets_by_number``) covers both courts;
    seed once per court so the driver advances each court's docket-number
    sequence independently. Each invocation walks the disclaimer /
    search-form / case-detail chain for a single docket id.
    """

    # === Metadata ===
    court_ids: ClassVar[set[str]] = {"nm", "nmctapp"}
    court_url: ClassVar[str] = LANDING_URL
    data_types: ClassVar[set[str]] = {"dockets"}
    status: ClassVar[ScraperStatus] = ScraperStatus.IN_DEVELOPMENT
    version: ClassVar[str] = "2026-05-04"
    last_verified: ClassVar[str] = "2026-05-04"
    requires_auth: ClassVar[bool] = False
    driver_requirements: ClassVar[list[DriverRequirement]] = []

    # The site rate-limits aggressively (a 60-second hard block triggers at
    # roughly one request per second during probing). Stay well clear at one
    # request every three seconds.
    rate_limits: ClassVar[list[Rate] | None] = [
        Rate(1, Duration.SECOND * 3),
    ]

    # =========================================================================
    # Entry point (§4): one speculative docket-number probe, court in the param.
    #
    # A speculative entry is dispatched by the driver with ONLY its speculative
    # param — a separate ``court_ids: set[str]`` argument can't be supplied
    # (SCRAPER_STANDARDS §4, "Multi-court speculative entries"). So the target
    # court rides inside ``NmCourtRange``; seed once per court.
    # =========================================================================

    @entry(NmDocket)
    def dockets_by_number(self, docket_number: NmCourtRange) -> Request:
        """Speculatively fetch one docket by case number for one court.

        ``docket_number.court_id`` selects the court (``nm`` →
        ``S-1-SC-{N}``, ``nmctapp`` → ``A-1-CA-{N}``); the driver probes
        ascending ``N`` and advances until ``gap`` consecutive misses. Seed
        once per court, e.g.::

            seed_params = [
                {"dockets_by_number": {"docket_number":
                    {"court_id": "nm", "min": 1, "gap": 10}}},
                {"dockets_by_number": {"docket_number":
                    {"court_id": "nmctapp", "min": 1, "gap": 10}}},
            ]
        """
        return self._build_speculative_request(docket_number)

    def _build_speculative_request(self, rng: NmCourtRange) -> Request:
        """Build the bootstrap GET that opens a per-case chain.

        The returned request hits the disclaimer landing page; the chain of
        step functions handles disclaimer acceptance (when needed), the
        search-form fetch, and the search submission.
        """
        case_number = str(rng.min)
        docket_number = (
            f"{rng.court_type}-{rng.court_location}-"
            f"{rng.case_category}-{case_number}"
        )
        return Request(
            request=HTTPRequestParams(
                method=HttpMethod.GET,
                url=LANDING_URL,
            ),
            continuation=self.bootstrap_session,
            accumulated_data={
                "docket_number": docket_number,
                "court": rng.court_id,
                "court_type": rng.court_type,
                "court_location": rng.court_location,
                "case_category": rng.case_category,
                "case_number": case_number,
                "entry_point": "dockets_by_number",
            },
            deduplication_key=f"docket_by_number:{docket_number}",
        )

    # =========================================================================
    # Soft-404 / session detection
    # =========================================================================

    def fails_successfully(self, response: Response) -> bool:
        """Return False for misses and session failures.

        Three failure modes share HTTP 200:

        - ``No results found.`` — the docket id does not exist (true miss).
        - ``Your session has timed out`` — server-side session expired.
        - ``Stale Session`` — request reached a guarded page without an
          accepted-disclaimer session.

        All three are treated as misses; the speculation driver advances the
        gap counter and the next ``@entry`` call rebuilds the session from
        scratch.

        Intermediate pages in the bootstrap chain (the disclaimer page, the
        welcome page, the search form) never carry these markers, so they are
        correctly reported as successes.
        """
        text = response.text
        if "No results found" in text:
            return False
        if "Your session has timed out" in text:
            return False
        return "Stale Session" not in text

    # =========================================================================
    # Step 1: bootstrap session (disclaimer or welcome)
    # =========================================================================

    @step(priority=4)
    def bootstrap_session(
        self,
        page: PageElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[NmDocket], None, None]:
        """Either accept the disclaimer or skip straight to the form.

        On a fresh ``JSESSIONID`` the landing URL renders the disclaimer
        page; once accepted, subsequent visits in the same session render the
        welcome page directly. Detect by looking for the ``disclaimerForm``
        component marker.
        """
        if "disclaimerForm" in response.text:
            form = page.find_form(
                XPath(
                    "//form[.//input[@name='component'"
                    " and @value='disclaimerForm']]"
                ),
                "disclaimer form",
            )
            yield form.submit(
                data={
                    "If": "T",
                    "If_0": "F",
                    "If_1": "T",
                    "Submit": "I Accept",
                },
                continuation=self.fetch_search_form,
                accumulated_data=accumulated_data,
            )
            return

        # Welcome page — disclaimer already accepted earlier in this run.
        yield from self._yield_search_form_request(accumulated_data)

    # =========================================================================
    # Step 2a: after disclaimer accept, fetch the search form
    # =========================================================================

    @step(priority=3)
    def fetch_search_form(
        self,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[NmDocket], None, None]:
        """Issue the GET that renders the case-number search form."""
        yield from self._yield_search_form_request(accumulated_data)

    def _yield_search_form_request(
        self, accumulated_data: dict
    ) -> Generator[Request, None, None]:
        yield Request(
            request=HTTPRequestParams(
                method=HttpMethod.GET,
                url=SEARCH_FORM_URL,
            ),
            continuation=self.parse_search_form,
            accumulated_data=accumulated_data,
        )

    # =========================================================================
    # Step 2b: submit the case-number search
    # =========================================================================

    @step(priority=3)
    def parse_search_form(
        self,
        page: PageElement,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[NmDocket], None, None]:
        """Submit the search form with the speculative case-id components."""
        form = page.find_form(
            XPath(
                "//form[.//input[@name='component'"
                " and @value='caseNumberSearchForm']]"
            ),
            "case-number search form",
        )
        yield form.submit(
            data={
                "courtType": accumulated_data["court_type"],
                "courtLocation": accumulated_data["court_location"],
                "caseCategory": accumulated_data["case_category"],
                "caseNumber": accumulated_data["case_number"],
                "Submit": "Case Number Search",
            },
            continuation=self.parse_case_detail,
            accumulated_data=accumulated_data,
        )

    # =========================================================================
    # Step 3: parse the case detail page
    # =========================================================================

    @step(priority=2)
    def parse_case_detail(
        self,
        page: PageElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[NmDocket], None, None]:
        """Parse the single-page case detail and emit one ``NmDocket``.

        ``fails_successfully`` already filters out the soft-404 / stale
        session / timeout pages, so by the time this step runs the response
        is the real case-detail page. We still re-check defensively so a
        structural mismatch doesn't crash the run.

        ``CaseDetailParser`` owns the page extraction; the step stamps the
        fields not reliably present on the page (``court``, ``source_url``,
        ``source_entry_point``) and falls back to the constructed docket
        number when the summary cell is blank. ``raw_data`` returns a copy,
        so we re-wrap with the merged fields rather than mutating the
        parser's deferred value in place.
        """
        text = response.text
        if (
            "No results found" in text
            or "Your session has timed out" in text
            or "Stale Session" in text
        ):
            return

        raw = CaseDetailParser()(page)[0].raw_data
        docket_number = (
            raw.get("docket_number") or accumulated_data["docket_number"]
        )
        raw["docket_number"] = docket_number
        if not raw.get("case_name"):
            raw["case_name"] = docket_number
        raw["court"] = accumulated_data["court"]
        raw["source_url"] = response.url
        raw["source_entry_point"] = accumulated_data.get("entry_point")
        yield ParsedData(NmDocket.raw(**raw))
