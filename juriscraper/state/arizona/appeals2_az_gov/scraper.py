"""Arizona Court of Appeals, Division Two scraper.

Site: https://www.appeals2.az.gov/ODSPlus/

The site fronts an Adobe ColdFusion app. A plaintext captcha
(``searchverifycode``) is bound to the ColdFusion session
(``CFID``/``CFTOKEN`` cookies), so each search starts with a GET to
``caseInfo.cfm`` (to seed the session cookie + a fresh captcha number);
the next step parses the number out of the HTML and POSTs it with the
search criteria. The HTTP driver carries the session cookies from the GET
to the POST automatically. There are only ever a handful of in-flight
searches (one per active-case bulk pull / per year), so we run plain HTTP;
if a concurrent GET is ever observed clobbering another search's captcha
before its POST lands, add ``DriverRequirement.STRICTLY_SERIAL``.

Per-page HTML extraction lives in the ``parsers`` package
(``CaseDetailParser``); the steps keep navigation concerns (captcha
parsing, the search POST, and the per-case fan-out).

Entry points (§4):
    - dockets_by_bulk(court_ids)                — POST ``ActiveCase=Y``;
      every currently-active case (the site's bulk feed).
    - dockets_by_filing_date(court_ids, range)  — POST ``CaseYear=<year>``
      once per year covered by the date range.
    - docket_by_internal_id(court_id, id)       — direct GET of one
      case-detail page by its numeric ``caseID``.

Flow:
    entry → submit_search_form → parse_search_results
                                  └→ (per case) parse_case_detail → ParsedData
    docket_by_internal_id ─────────────────────→ parse_case_detail → ParsedData
"""

from __future__ import annotations

import re
from datetime import date
from typing import TYPE_CHECKING, ClassVar

from jkent.common.decorators import entry, step
from jkent.common.exceptions import ScraperAssumptionException
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
)
from pyrate_limiter import Duration, Rate

from .models import (
    CASE_DETAIL_URL,
    COURT_ID,
    SEARCH_FORM_URL,
    SEARCH_POST_URL,
    AzCoa2Docket,
)
from .parsers import CaseDetailParser

if TYPE_CHECKING:
    from collections.abc import Generator

    from jkent.common.page_element import PageElement
    from jkent.data_types import ScraperYield


# Captcha appears as: Enter <strong><font color="FF0000">7820</font></strong>
_CAPTCHA_RE = re.compile(r"<strong><font[^>]*>(?P<code>\d+)</font></strong>")
_CASE_ID_RE = re.compile(r"caseInfolast\.cfm\?caseID=(\d+)", re.I)

_MIN_YEAR = 1990


class AzCoa2Scraper(BaseScraper[AzCoa2Docket]):
    """Scraper for Arizona Court of Appeals, Division Two.

    Captures the full register of actions for each case — parties &
    attorneys, filings/continuances, oral-argument calendar entries,
    decisions, mandate info, MR/PR outcomes, and the chronological
    proceedings log — straight off the case-detail HTML page.
    """

    # === Metadata ===
    court_ids: ClassVar[set[str]] = {COURT_ID}
    court_url: ClassVar[str] = SEARCH_FORM_URL
    data_types: ClassVar[set[str]] = {"dockets"}
    status: ClassVar[ScraperStatus] = ScraperStatus.IN_DEVELOPMENT
    version: ClassVar[str] = "2026-06-26"
    last_verified: ClassVar[str] = "2026-05-02"
    requires_auth: ClassVar[bool] = False
    driver_requirements: ClassVar[list[DriverRequirement]] = []
    rate_limits: ClassVar[list[Rate] | None] = [Rate(2, Duration.SECOND)]

    # =========================================================================
    # Entry points (§4)
    # =========================================================================

    @entry(AzCoa2Docket)
    def dockets_by_bulk(
        self, court_ids: set[str]
    ) -> Generator[Request, None, None]:
        """Pull the site's bulk feed of every currently-active case.

        Posts the search form with ``ActiveCase=Y`` and no other filters.
        A single response carries all results (~700-800 active cases at
        any given time; no pagination). The court address mode is bulk —
        the site has no way to enumerate the full historical set in one
        go; use :meth:`dockets_by_filing_date` for closed/older cases.
        """
        yield from self._seed_search(
            {"search_kind": "active", "entry_point": "dockets_by_bulk"},
            deduplication_key="search_seed:active",
        )

    @entry(AzCoa2Docket)
    def dockets_by_filing_date(
        self, court_ids: set[str], date_range: DateRange
    ) -> Generator[Request, None, None]:
        """Search every case filed in each year covered by ``date_range``.

        The site searches by ``CaseYear`` (the year component of the
        docket number = filing year), so the date range is widened to
        whole years and one search is seeded per year. Years between 1990
        and the current year are accepted by the site's form.
        """
        start_year = max(date_range.start.year, _MIN_YEAR)
        end_year = min(date_range.end.year, date.today().year)
        if start_year > end_year:
            raise ScraperAssumptionException(
                f"date range {date_range.start}–{date_range.end} covers no "
                f"year the site supports (1990–{date.today().year})"
            )
        for year in range(start_year, end_year + 1):
            yield from self._seed_search(
                {
                    "search_kind": "year",
                    "year": year,
                    "entry_point": "dockets_by_filing_date",
                },
                deduplication_key=f"search_seed:year:{year}",
            )

    @entry(AzCoa2Docket)
    def docket_by_internal_id(
        self, court_id: str, internal_id: int
    ) -> Generator[Request, None, None]:
        """Direct fetch of one case detail by its numeric ``caseID``.

        The case-detail page is publicly accessible without cookies or
        captcha, so this skips the search flow entirely.
        """
        yield self._case_detail_request(
            internal_id, entry_point="docket_by_internal_id"
        )

    def _seed_search(
        self, accumulated: dict, *, deduplication_key: str
    ) -> Generator[Request, None, None]:
        """Yield the GET that seeds the session cookie + captcha.

        The ``accumulated_data`` dict carries the search criteria forward
        to :meth:`submit_search_form`, which converts them to a POST body.
        """
        yield Request(
            request=HTTPRequestParams(
                method=HttpMethod.GET,
                url=SEARCH_FORM_URL,
                headers={"Accept": "text/html"},
            ),
            continuation=self.submit_search_form,
            accumulated_data=accumulated,
            deduplication_key=deduplication_key,
        )

    def _case_detail_request(
        self, case_id: int, *, entry_point: str
    ) -> Request:
        """Build a GET request for one case-detail page."""
        return Request(
            request=HTTPRequestParams(
                method=HttpMethod.GET,
                url=CASE_DETAIL_URL,
                params={"caseID": str(case_id)},
                headers={"Accept": "text/html"},
            ),
            continuation=self.parse_case_detail,
            accumulated_data={"case_id": case_id, "entry_point": entry_point},
            deduplication_key=f"case_detail:{case_id}",
        )

    # =========================================================================
    # Step: parse captcha + POST search form
    # =========================================================================

    @step(priority=4)
    def submit_search_form(
        self, response: Response, accumulated_data: dict
    ) -> Generator[Request, None, None]:
        """Parse the four-digit captcha out of the GET response, then
        POST ``caseInfo2.cfm`` with the search criteria.

        Cookies set on the GET (CFID, CFTOKEN) flow automatically to the
        POST under the same HTTP-driver session.
        """
        match = _CAPTCHA_RE.search(response.text)
        if not match:
            raise ScraperAssumptionException(
                "captcha number not found on caseInfo.cfm — "
                "site layout may have changed"
            )
        code = match.group("code")

        data: dict[str, str] = {"searchverifycode": code}
        kind = accumulated_data["search_kind"]
        if kind == "active":
            data["ActiveCase"] = "Y"
            dedup = "search_results:active"
        elif kind == "year":
            data["CaseYear"] = str(accumulated_data["year"])
            dedup = f"search_results:year:{accumulated_data['year']}"
        else:
            raise ScraperAssumptionException(f"unknown search_kind: {kind!r}")

        yield Request(
            request=HTTPRequestParams(
                method=HttpMethod.POST,
                url=SEARCH_POST_URL,
                data=data,
                headers={
                    "Accept": "text/html",
                    "Content-Type": "application/x-www-form-urlencoded",
                },
            ),
            continuation=self.parse_search_results,
            accumulated_data=accumulated_data,
            deduplication_key=dedup,
        )

    # =========================================================================
    # Step: extract case IDs from the search results page
    # =========================================================================

    @step(priority=3)
    def parse_search_results(
        self, response: Response, accumulated_data: dict
    ) -> Generator[Request, None, None]:
        """Pull every ``caseID`` from the result page and dispatch a
        case-detail fetch for each.

        The result page has no real pagination — all hits are emitted
        inline (verified up to ~1000 results per search). If the site
        ever paginates we'll see the cap show up as a fixed result count
        and need to add a follow-link step here.
        """
        text = response.text
        if "Please go back" in text and "verification code" in text:
            raise ScraperAssumptionException(
                "captcha rejection — verification code did not match. "
                "Likely a parser regression in submit_search_form."
            )

        entry_point = accumulated_data.get("entry_point")
        seen: set[int] = set()
        for case_id_str in _CASE_ID_RE.findall(text):
            case_id = int(case_id_str)
            if case_id in seen:
                continue
            seen.add(case_id)
            yield self._case_detail_request(case_id, entry_point=entry_point)

    # =========================================================================
    # Step: parse one case detail page
    # =========================================================================

    @step(priority=2)
    def parse_case_detail(
        self,
        page: PageElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[AzCoa2Docket], None, None]:
        """Parse a case-detail page and emit one ``AzCoa2Docket``.

        ``CaseDetailParser`` owns the page extraction; the step stamps the
        fields not present on the page (``case_id`` from the URL key,
        ``court``, ``source_url``, ``source_entry_point``). ``raw_data``
        returns a copy, so we re-wrap with the merged fields rather than
        mutating the parser's deferred value in place.
        """
        raw = CaseDetailParser()(page)[0].raw_data
        raw["case_id"] = int(accumulated_data["case_id"])
        raw["court"] = COURT_ID
        raw["source_url"] = response.url
        raw["source_entry_point"] = accumulated_data.get("entry_point")
        yield ParsedData(AzCoa2Docket.raw(**raw))
