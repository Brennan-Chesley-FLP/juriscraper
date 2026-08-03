"""Supreme Court of Georgia Docket Scraper.

Scrapes the public docket-search system at https://www.gasupreme.us/docket-search/
which is an iframe-embedded SPA at https://pubdoc.gasupreme.gov/ui/. The SPA
calls a plain JSON REST API on that same origin under ``/api`` — this scraper
goes directly to that API.

This is a **JSON-only** scraper: every step injects ``json_content`` and there
is no HTML to parse, so there is no ``parsers/`` package (per
``../../SCRAPER_STANDARDS.md`` §3.5; follows the arkansas/nevada shape).

Coverage is the rolling 5-year window the API exposes; older cases are
unavailable (the docket system surfaces 404 for expired-window numbers).

Entry points (§4):

- ``dockets_by_year(court_ids, year)`` — sweeps one calendar year via the
  ``CaseNumber STARTS_WITH S{YY}`` prefix query and yields a detail fetch per
  case number. Seed one call per year in the rolling window; that prefix query
  is the site's only bulk feed.
- ``docket_by_number(court_id, docket_number)`` — direct single-case lookup
  for a known docket id. Also the only way to see **updates** to an already
  known case: the search API exposes no last-modified field, so activity on
  an existing case is invisible until its detail JSON is refetched.

Flow per case:

  1. ``parse_search_results`` — read the search-results JSON list and
     dispatch one detail fetch per case.
  2. ``parse_case_detail`` — build a ``GaScDocket`` from the case JSON.

There are no document downloads — the portal exposes only filing
descriptions, not the underlying PDFs.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING, Any, ClassVar

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
)
from pyrate_limiter import Duration, Rate

from .models import (
    CASE_TYPE_DESCRIPTIONS,
    COURT_ID,
    GaScAttorney,
    GaScDocket,
    GaScDocketEntry,
    GaScJudgment,
)

if TYPE_CHECKING:
    from collections.abc import Generator

    from jkent.data_types import ScraperYield


# As of 2026-08-03 the API is served from the SPA's own origin under ``/api``.
# It previously lived on a separate host (``sced-rest.gasupreme.us``), which no
# longer resolves; ``pubdoc.gasupreme.us`` 301s to the ``.gov`` name.
API_BASE = "https://pubdoc.gasupreme.gov/api"
SEARCH_URL = f"{API_BASE}/public-docket/query"
CASE_DETAIL_URL = f"{API_BASE}/public-docket/case"

# Rolling window the API exposes, in years — how many years back
# ``dockets_by_year`` is worth seeding from the current one. As of 2026-05 the
# oldest reachable case was docketed 2021-05-03, i.e. (today - ~5 years).
ROLLING_WINDOW_YEARS = 6


class GeorgiaSupremeCourtScraper(BaseScraper[GaScDocket]):
    """Scraper for the Supreme Court of Georgia docket system.

    The site has no date-based search and no auth/bot-protection, but the
    ``CaseNumber STARTS_WITH S{YY}`` query reliably returns every case
    docketed under that two-digit year prefix in a single uncapped JSON
    response. One ``dockets_by_year`` call sweeps one such prefix and
    fetches detail per case.
    """

    # === Metadata (§3) ===
    court_ids: ClassVar[set[str]] = {COURT_ID}
    court_url: ClassVar[str] = "https://www.gasupreme.us/docket-search/"
    data_types: ClassVar[set[str]] = {"dockets"}
    status: ClassVar[ScraperStatus] = ScraperStatus.IN_DEVELOPMENT
    version: ClassVar[str] = "2026-08-03"
    last_verified: ClassVar[str] = "2026-08-03"
    requires_auth: ClassVar[bool] = False
    driver_requirements: ClassVar[list[DriverRequirement]] = []
    rate_limits: ClassVar[list[Rate] | None] = [Rate(3, Duration.SECOND)]

    # =========================================================================
    # Entry points (§4)
    # =========================================================================

    @entry(GaScDocket)
    def dockets_by_year(
        self, court_ids: set[str], year: int
    ) -> Generator[Request, None, None]:
        """Sweep every case docketed under one calendar year's number prefix.

        ``CaseNumber STARTS_WITH S{YY}`` — the site's only bulk feed —
        returns every case docketed under that year prefix (~1,300) in one
        uncapped response, so a year is a single request plus one detail
        fetch per case. Seed one call per year of the rolling
        ``ROLLING_WINDOW_YEARS``-year window; years outside it return an
        empty list rather than an error.

        ``year`` accepts either the four-digit calendar year (``2026``) or
        the site's two-digit form (``26``). Note the court's numbering year
        rolls over in early August, so a given ``S{YY}`` prefix spans the
        second half of calendar year YY-1 and the first half of YY.

        ``court_ids`` is accepted for the §4 signature but this scraper
        covers exactly one court (``ga``).
        """
        prefix = f"S{year % 100:02d}"
        yield Request(
            request=HTTPRequestParams(
                method=HttpMethod.GET,
                url=SEARCH_URL,
                params={"queryFilter": f"CaseNumber STARTS_WITH {prefix}"},
                headers={"Accept": "application/json"},
            ),
            continuation=self.parse_search_results,
            accumulated_data={
                "prefix": prefix,
                "entry_point": "dockets_by_year",
            },
            deduplication_key=f"search:prefix:{prefix}",
        )

    @entry(GaScDocket)
    def docket_by_number(
        self, court_id: str, docket_number: str
    ) -> Generator[Request, None, None]:
        """Direct lookup for a known case number (e.g. ``S26A0125``)."""
        normalized = docket_number.strip().upper()
        yield Request(
            request=HTTPRequestParams(
                method=HttpMethod.GET,
                url=f"{CASE_DETAIL_URL}/{normalized}",
                headers={"Accept": "application/json"},
            ),
            continuation=self.parse_case_detail,
            accumulated_data={
                "docket_number": normalized,
                "entry_point": "docket_by_number",
            },
            deduplication_key=f"case_detail:{normalized}",
        )

    # =========================================================================
    # Step 1: parse search results
    # =========================================================================

    @step(priority=3)
    def parse_search_results(
        self,
        json_content: list,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[GaScDocket], None, None]:
        """Dispatch a detail fetch per case number returned by the prefix query."""
        entry_point = accumulated_data.get("entry_point")
        for hit in json_content or []:
            case_number = (hit.get("caseNumber") or "").strip().upper()
            if not case_number:
                continue
            yield Request(
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url=f"{CASE_DETAIL_URL}/{case_number}",
                    headers={"Accept": "application/json"},
                ),
                continuation=self.parse_case_detail,
                accumulated_data={
                    "docket_number": case_number,
                    "preview_case_style": hit.get("caseStyle"),
                    "entry_point": entry_point,
                },
                deduplication_key=f"case_detail:{case_number}",
            )

    # =========================================================================
    # Step 2: parse case detail
    # =========================================================================

    @step(priority=2)
    def parse_case_detail(
        self,
        json_content: dict,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[GaScDocket], None, None]:
        """Build a GaScDocket from the per-case JSON payload."""
        docket_number = (
            (
                json_content.get("caseNumber")
                or accumulated_data.get("docket_number")
                or ""
            )
            .strip()
            .upper()
        )
        case_type = (
            json_content.get("caseType") or ""
        ).strip().upper() or None

        case_name = (
            json_content.get("caseStyle")
            or accumulated_data.get("preview_case_style")
            or docket_number
        )

        docket = GaScDocket.raw(
            docket_number=docket_number,
            court=COURT_ID,
            date_filed=_parse_iso_date(json_content.get("docketDate")),
            case_name=case_name,
            case_type=case_type,
            case_type_description=(
                CASE_TYPE_DESCRIPTIONS.get(case_type) if case_type else None
            ),
            case_status=json_content.get("caseStatus"),
            description=_clean(json_content.get("description")),
            docket_calendar=json_content.get("docketCalendar"),
            calendar_case=json_content.get("calendarCase"),
            county=json_content.get("county"),
            lower_court_case_numbers=_clean(
                json_content.get("lowerCourtCaseNumbers")
            ),
            entries=_parse_entries(json_content.get("filingsAndOrders")),
            judgments=_parse_judgments(json_content.get("judgments")),
            attorneys=_parse_attorneys(json_content.get("attorneys")),
            source_url=response.url,
            source_entry_point=accumulated_data.get("entry_point"),
        )
        yield ParsedData(docket)


# =============================================================================
# Parsing helpers (module-level — no self required)
# =============================================================================


def _clean(value: Any) -> str | None:
    """Strip whitespace; return None for empty/None inputs."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _parse_iso_date(value: Any) -> date | None:
    """Parse an ISO date or ISO datetime string to a ``date``.

    The API returns ``"2025-08-04"`` for plain dates and
    ``"2025-09-24T16:12:38"`` for filing timestamps; both forms are accepted.
    """
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _parse_iso_time(value: Any) -> str | None:
    """Extract the HH:MM:SS portion of an ISO datetime, if present."""
    if not value:
        return None
    text = str(value).strip()
    if "T" not in text:
        return None
    try:
        return (
            datetime.fromisoformat(text).time().isoformat(timespec="seconds")
        )
    except ValueError:
        return None


def _parse_entries(rows: Any) -> list[GaScDocketEntry]:
    if not isinstance(rows, list):
        return []
    out: list[GaScDocketEntry] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        filing_type = _clean(row.get("filingType"))
        if not filing_type:
            continue
        out.append(
            GaScDocketEntry(
                filing_type=filing_type,
                date_filed=_parse_iso_date(row.get("filingDateTime")),
                time_filed=_parse_iso_time(row.get("filingDateTime")),
                order_type=_clean(row.get("orderType")),
                order_date=_parse_iso_date(row.get("orderDate")),
                docketed_in_error=bool(row.get("docketedInError")),
            )
        )
    return out


def _parse_judgments(rows: Any) -> list[GaScJudgment]:
    if not isinstance(rows, list):
        return []
    out: list[GaScJudgment] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        text = _clean(row.get("judgment"))
        if not text:
            continue
        out.append(
            GaScJudgment(
                judgment=text,
                judgment_line=_clean(row.get("judgmentLine")),
                judgment_date=_parse_iso_date(row.get("judgmentDate")),
            )
        )
    return out


def _parse_attorneys(rows: Any) -> list[GaScAttorney]:
    if not isinstance(rows, list):
        return []
    out: list[GaScAttorney] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        out.append(
            GaScAttorney(
                first_name=_clean(row.get("firstName")),
                middle_name=_clean(row.get("middleName")),
                last_name=_clean(row.get("lastName")),
                suffix=_clean(row.get("suffix")),
                title=_clean(row.get("title")),
                firm=_clean(row.get("firm")),
                street_address_1=_clean(row.get("streetAddress1")),
                street_address_2=_clean(row.get("streetAddress2")),
                city=_clean(row.get("city")),
                state=_clean(row.get("state")),
                zip=_clean(row.get("zip")),
                phone=_clean(row.get("phone")),
                party_type=_clean(row.get("partyType")),
            )
        )
    return out
