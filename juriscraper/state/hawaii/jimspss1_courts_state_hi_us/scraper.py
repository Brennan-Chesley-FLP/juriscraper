"""Hawaiʻi eCourt Kōkua appellate-docket scraper.

Scrapes appellate dockets from the Hawaiʻi Judiciary's eCourt Kōkua portal
at ``http://jimspss1.courts.state.hi.us:8080/eCourt/ECC/``.

Supported courts:

- ``haw``    — Supreme Court of Hawaiʻi (case prefixes ``SC{TT}-``)
- ``hawapp`` — Hawaii Intermediate Court of Appeals (prefixes ``CA{TT}-``)

The portal is JSF 2.0 / IceFaces 4. Every search submission is gated by
**invisible** reCAPTCHA v2; kent's ``RCAP_HANDLER`` only handles the
visible-checkbox variant today, so this scraper ships
``status=IN_DEVELOPMENT`` until kent gains an invisible-reCAPTCHA solver.
See ``CC_NOTES.md`` for details.

Per-page HTML extraction lives in the ``parsers`` package
(``CaseDetailParser``); the steps keep navigation concerns (disclaimer
acceptance, the search-form submit chain, and the per-case fan-out).

Entry points (§4):
    - dockets_by_filing_date(court_ids, date_range) — Filing Date Search,
      one search per court in ``court_ids`` per <=60-day window.
    - dockets_by_number(docket_number)              — speculative Case ID
      Search; ``HiCaseRange`` carries the court + case-type prefix + year.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import TYPE_CHECKING, ClassVar
from urllib.parse import urljoin

from jkent.common.decorators import entry, step
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

from juriscraper.state.common.params import CourtRange, InferrableDateRange

from .models import (
    ICA_CASE_TYPES,
    SC_CASE_TYPES,
    HiAppDocket,
)
from .parsers import CaseDetailParser
from .parsers._common import SITE_DATE_FORMAT

if TYPE_CHECKING:
    from collections.abc import Generator

    from jkent.common.page_element import PageElement
    from jkent.data_types import ScraperYield


SITE_BASE = "http://jimspss1.courts.state.hi.us:8080/eCourt/ECC"
DISCLAIMER_URL = f"{SITE_BASE}/ECCDisclaimer.iface"
CASE_SEARCH_URL = f"{SITE_BASE}/CaseSearch.iface"
DATE_SEARCH_URL = f"{SITE_BASE}/FilingDateSearch.iface"

# Server-side cap on Filing Date Search ranges.
MAX_DATE_RANGE_DAYS = 60

# CourtListener court id → (site court-type code, site court code).
CL_TO_SITE_COURT: dict[str, tuple[str, str]] = {
    "haw": ("SC", "SC"),
    "hawapp": ("ICA", "CA"),
}

NO_RESULTS_SENTINEL = "no records found"

DISCLAIMER_FORM_XPATH = "//form[@id='frm']"
SEARCH_FORM_XPATH = "//form[@id='frm']"
RESULT_TABLE_XPATH = "//table[contains(@class, 'iceDatTbl')]"


class HiCaseRange(CourtRange):
    """Speculative case-number range for one court + case-type prefix + year.

    A speculative entry is dispatched with **only** its speculative param
    (SCRAPER_STANDARDS §4), so the target court, the case-type prefix, and
    the year all ride here. The Hawaiʻi docket-number space is partitioned
    by all three (``SCAP-22-0000234``: court ``SC`` / type ``AP`` / year
    ``22``), so this carries the discriminators a plain ``CourtRange`` lacks.

    ``from_int`` copies via ``model_copy``, so all fields survive as the
    driver advances ``min``. Seed one range per (court, prefix, year), e.g.::

        seed_params = [
            {"dockets_by_number": {"docket_number": {
                "court_id": "haw", "type_code": "AP", "year": 2024,
                "min": 1, "soft_max": 1, "gap": 15}}},
            {"dockets_by_number": {"docket_number": {
                "court_id": "hawapp", "type_code": "AP", "year": 2024,
                "min": 1, "soft_max": 1, "gap": 15}}},
        ]
    """

    type_code: str
    """Two-letter case-type code (``AP``, ``WC``, ``PW``, ...)."""

    year: int
    """Four-digit calendar year the docket-number sequence belongs to."""

    def site_court(self) -> str:
        """Return the site court code (``SC`` / ``CA``) for this court id."""
        return CL_TO_SITE_COURT[self.court_id][1]

    def docket_number(self) -> str:
        """Build the full court-prefixed docket number for ``min``."""
        return (
            f"{self.site_court()}{self.type_code}-"
            f"{self.year % 100:02d}-{self.min:07d}"
        )


class HiAppellateScraper(BaseScraper[HiAppDocket]):
    """Scraper for Hawaiʻi appellate dockets on the eCourt Kōkua portal.

    One date-range entry (seeded per court) and one speculative case-id
    entry. All paths route through:

    1. ``ensure_disclaimer`` — accept the disclaimer once per session
       (invisible reCAPTCHA gate).
    2. ``navigate_to_search`` — GET a fresh search page (current view
       tokens).
    3. ``fill_date_search_form`` / ``fill_caseid_search_form`` — submit the
       search form (invisible reCAPTCHA gate).
    4. ``parse_search_results`` — iterate the result table and queue
       case-detail fetches.
    5. ``parse_case_detail`` — assemble the ``HiAppDocket``.
    """

    # === Metadata ===
    court_ids: ClassVar[set[str]] = {"haw", "hawapp"}
    court_url: ClassVar[str] = CASE_SEARCH_URL
    data_types: ClassVar[set[str]] = {"dockets"}
    status: ClassVar[ScraperStatus] = ScraperStatus.IN_DEVELOPMENT
    version: ClassVar[str] = "2026-06-27"
    last_verified: ClassVar[str] = "2026-05-06"
    requires_auth: ClassVar[bool] = False

    # Invisible reCAPTCHA v2 on disclaimer + every search submission.
    # ``RCAP_HANDLER`` declares intent; today it solves visible reCAPTCHA
    # only. See CC_NOTES.md "Known Gaps".
    driver_requirements: ClassVar[list[DriverRequirement]] = [
        DriverRequirement.JS_EVAL,
        DriverRequirement.FF_ALIKE,
        DriverRequirement.RCAP_HANDLER,
    ]
    rate_limits: ClassVar[list[Rate] | None] = [Rate(1, Duration.SECOND)]

    # =========================================================================
    # Entry points (§4)
    # =========================================================================

    @entry(HiAppDocket)
    def dockets_by_filing_date(
        self, court_ids: set[str], date_range: InferrableDateRange
    ) -> Generator[Request, None, None]:
        """Filing Date Search for each requested appellate court.

        The site's Filing Date Search caps a query at 60 days, so the range
        is chunked into <=60-day windows; one search is seeded per
        (court, window). Only the appellate courts (``haw``, ``hawapp``) are
        served here; other ``court_ids`` are ignored.
        """
        for court_id in sorted(court_ids):
            if court_id not in CL_TO_SITE_COURT:
                continue
            site_court_type, site_court = CL_TO_SITE_COURT[court_id]
            for window_start, window_end in _chunk_date_range(
                date_range.start, date_range.end, MAX_DATE_RANGE_DAYS
            ):
                yield Request(
                    request=HTTPRequestParams(
                        method=HttpMethod.GET, url=DISCLAIMER_URL
                    ),
                    continuation=self.ensure_disclaimer,
                    accumulated_data={
                        "search_mode": "date",
                        "site_court_type": site_court_type,
                        "site_court": site_court,
                        "site_location": site_court,
                        "begin_date": window_start.strftime(
                            SITE_DATE_FORMAT
                        ).upper(),
                        "end_date": window_end.strftime(
                            SITE_DATE_FORMAT
                        ).upper(),
                        "court": court_id,
                        "entry_point": "dockets_by_filing_date",
                    },
                    deduplication_key=SkipDeduplicationCheck(),
                )

    @entry(HiAppDocket)
    def dockets_by_number(self, docket_number: HiCaseRange) -> Request:
        """Speculatively fetch one docket by Case ID Search.

        ``docket_number`` is a :class:`HiCaseRange` carrying the court, the
        case-type prefix, and the year; the driver probes ascending sequence
        numbers and advances until ``gap`` consecutive misses. Seed one range
        per (court, prefix, year) — see :class:`HiCaseRange`.
        """
        return Request(
            request=HTTPRequestParams(
                method=HttpMethod.GET, url=DISCLAIMER_URL
            ),
            continuation=self.ensure_disclaimer,
            accumulated_data={
                "search_mode": "case_id",
                "docket_number": docket_number.docket_number(),
                "court": docket_number.court_id,
                "entry_point": "dockets_by_number",
            },
            deduplication_key=(
                f"dockets_by_number:{docket_number.docket_number()}"
            ),
        )

    # =========================================================================
    # Step: accept the disclaimer (or pass through if already accepted)
    # =========================================================================

    @step(priority=6)
    def ensure_disclaimer(
        self,
        page: PageElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[HiAppDocket], None, None]:
        """Accept the JIMS disclaimer when present, then queue a fresh GET
        for the search page. The ``RCAP_HANDLER`` driver requirement is
        responsible for solving the invisible reCAPTCHA before the accept
        POST is dispatched.

        After a successful accept the server returns ``ECC.iface`` (Home)
        with a session flag; ``ice.window`` and ``ice.view`` view tokens
        change per page render, so we re-fetch the search page rather than
        submitting from a stale form."""
        if "ECCDisclaimer.iface" in (response.url or ""):
            form = page.find_form(
                DISCLAIMER_FORM_XPATH, "disclaimer accept form"
            )
            yield form.submit(
                data={"frm:acceptButtonCaptcha": ""},
                continuation=self.navigate_to_search,
                accumulated_data=accumulated_data,
                deduplication_key=SkipDeduplicationCheck(),
            )
            return
        yield from self.navigate_to_search(
            page=page,
            response=response,
            accumulated_data=accumulated_data,
        )

    @step(priority=5)
    def navigate_to_search(
        self,
        page: PageElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[HiAppDocket], None, None]:
        """Issue a fresh GET to the appropriate search page so we can capture
        a current ViewState / ice.view triple."""
        if accumulated_data.get("search_mode") == "case_id":
            target = CASE_SEARCH_URL
            continuation = self.fill_caseid_search_form
        else:
            target = DATE_SEARCH_URL
            continuation = self.fill_date_search_form
        yield Request(
            request=HTTPRequestParams(method=HttpMethod.GET, url=target),
            continuation=continuation,
            accumulated_data=accumulated_data,
            deduplication_key=SkipDeduplicationCheck(),
        )

    # =========================================================================
    # Step: fill and submit the Filing Date Search form
    # =========================================================================

    @step(priority=4)
    def fill_date_search_form(
        self,
        page: PageElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[HiAppDocket], None, None]:
        """Submit the FilingDateSearch form for the chosen court+window.

        The form lives at ``frm`` and IceFaces partial-postback dependencies
        between the court-type / court / location selects mean we set them in
        one shot and rely on server-side validation to accept the consistent
        triple (``SC/SC/SC`` or ``ICA/CA/CA``)."""
        form = page.find_form(SEARCH_FORM_XPATH, "filing date search form")
        yield form.submit(
            data={
                "frm:j_idt22:courtTypeSelect": accumulated_data[
                    "site_court_type"
                ],
                "frm:j_idt22:courtSelect": accumulated_data["site_court"],
                "frm:j_idt22:locationSelect": accumulated_data[
                    "site_location"
                ],
                "frm:beginDate": accumulated_data["begin_date"],
                "frm:endDate": accumulated_data["end_date"],
                "frm:caseType": "",
                "frm:searchButtonCaptcha": "",
            },
            continuation=self.parse_search_results,
            accumulated_data=accumulated_data,
        )

    # =========================================================================
    # Step: fill and submit the Case ID Search form (speculative)
    # =========================================================================

    @step(priority=4)
    def fill_caseid_search_form(
        self,
        page: PageElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[HiAppDocket], None, None]:
        """Submit the CaseSearch form for a single docket number."""
        form = page.find_form(SEARCH_FORM_XPATH, "case id search form")
        yield form.submit(
            data={
                "frm:caseId": accumulated_data["docket_number"],
                "frm:searchButtonCaptcha": "",
            },
            continuation=self.parse_search_results,
            accumulated_data=accumulated_data,
        )

    # =========================================================================
    # Step: parse the IceFaces result table
    # =========================================================================

    @step(priority=3)
    def parse_search_results(
        self,
        page: PageElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[HiAppDocket], None, None]:
        """Walk the result table; queue a detail fetch per case row.

        TODO(empirical): result-table column layout is inferred from the
        site's form schema and standard IceFaces conventions. Validate on
        first operational run and adjust the XPaths below."""
        # Soft-404: IceFaces re-renders the same page with a "no records"
        # message rather than emitting an HTTP error.
        body = (response.text or "").lower()
        if NO_RESULTS_SENTINEL in body:
            return

        rows = page.query(
            XPath(f"{RESULT_TABLE_XPATH}//tbody/tr"),
            "result-table rows",
            min_count=0,
        )
        for row in rows:
            link_els = row.query(
                XPath(
                    ".//a[contains(@href, 'CaseSearchView') "
                    "or contains(@id, 'caseId')]"
                ),
                "case detail link",
                min_count=0,
                max_count=1,
            )
            if not link_els:
                continue
            href = link_els[0].get_attribute("href")
            if not href:
                continue

            row_cells = row.query_strings(
                XPath(".//td//text()"), "row cell texts", min_count=0
            )
            row_docket_number = row_cells[0].strip() if row_cells else None

            child_data = dict(accumulated_data)
            child_data["docket_number"] = (
                row_docket_number
                or accumulated_data.get("docket_number")
                or ""
            )

            yield Request(
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url=urljoin(response.url, href),
                ),
                continuation=self.parse_case_detail,
                accumulated_data=child_data,
                deduplication_key=(
                    f"parse_case_detail:{child_data['docket_number']}"
                ),
            )

    # =========================================================================
    # Step: parse the case-detail page
    # =========================================================================

    @step(priority=2)
    def parse_case_detail(
        self,
        page: PageElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[HiAppDocket], None, None]:
        """Assemble a :class:`HiAppDocket` from the case detail page.

        ``CaseDetailParser`` owns the page extraction; the step stamps the
        fields derived from the request context (``docket_number``,
        ``court``, the case-type code/label, ``source_url``,
        ``source_entry_point``) and resolves relative document URLs.
        """
        docket_number = accumulated_data.get("docket_number") or ""
        court = accumulated_data["court"]

        raw = CaseDetailParser()(page)[0].raw_data
        raw["docket_number"] = docket_number
        raw["court"] = court
        raw["source_url"] = response.url
        raw["source_entry_point"] = accumulated_data.get("entry_point")

        type_code = _extract_type_code(docket_number)
        raw["case_type_code"] = type_code
        raw["case_type"] = _case_type_label(
            docket_number, type_code
        ) or raw.get("case_type")
        if not raw.get("case_name"):
            raw["case_name"] = docket_number

        # Resolve relative document hrefs against the page URL.
        for doc in raw.get("documents") or []:
            doc.download_url = urljoin(response.url or "", doc.download_url)

        yield ParsedData(HiAppDocket.raw(**raw))

    # =========================================================================
    # Soft-404 detection (per request)
    # =========================================================================

    def actually_successful(self, response: Response) -> bool:
        """Return False for the JSF re-render that signals a search miss.

        The Case ID Search re-renders ``CaseSearch.iface`` with a "no records
        found" message rather than redirecting or 404-ing. The driver treats
        False as a speculation miss."""
        if response.status_code != 200:
            return True
        body = (response.text or "").lower()
        return NO_RESULTS_SENTINEL not in body


# =============================================================================
# Date-range chunking
# =============================================================================


def _chunk_date_range(
    start: date, end: date, max_days: int
) -> list[tuple[date, date]]:
    """Split ``[start, end]`` into inclusive sub-ranges of at most
    ``max_days`` days each."""
    if start > end:
        return []
    chunks: list[tuple[date, date]] = []
    cursor = start
    step_days = timedelta(days=max_days - 1)
    while cursor <= end:
        chunk_end = min(cursor + step_days, end)
        chunks.append((cursor, chunk_end))
        cursor = chunk_end + timedelta(days=1)
    return chunks


# =============================================================================
# Docket-number helpers
# =============================================================================


def _extract_type_code(docket_number: str) -> str | None:
    """Pull the 2-letter case type out of a docket number like ``SCAP-22-...``."""
    if not docket_number or "-" not in docket_number:
        return None
    prefix = docket_number.split("-", 1)[0]
    if len(prefix) >= 4 and prefix[:2] in ("SC", "CA"):
        return prefix[2:4]
    return None


def _case_type_label(docket_number: str, type_code: str | None) -> str | None:
    """Map a docket-number prefix + type code to a human-readable label."""
    if not type_code:
        return None
    if docket_number.startswith("SC"):
        return SC_CASE_TYPES.get(type_code)
    if docket_number.startswith("CA"):
        return ICA_CASE_TYPES.get(type_code)
    return None
