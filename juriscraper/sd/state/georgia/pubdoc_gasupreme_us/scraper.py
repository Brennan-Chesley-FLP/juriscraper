"""Supreme Court of Georgia Docket Scraper.

Scrapes the public docket-search system at https://www.gasupreme.us/docket-search/
which is an iframe-embedded SPA at https://pubdoc.gasupreme.us/. The SPA calls
a plain JSON REST API at https://sced-rest.gasupreme.us/ — this scraper goes
directly to that API.

Coverage is the rolling 5-year window the API exposes; older cases are
unavailable (the docket system surfaces 404 for expired-window numbers).

Entry points:

- ``get_all_dockets()`` — sweeps the current calendar year and the five
  preceding years via the prefix query and yields a detail fetch per unique
  case number. This is the default bulk-scrape entry.
- ``get_dockets_after(watermark: str)`` — incremental entry. Issues
  ``CaseNumber GREATER_THAN <watermark>`` and yields a detail fetch per case
  whose number sorts after the cursor. Catches newly **docketed** cases
  only; updates to existing cases are not detectable through the search API
  and require a refetch of the case detail.
- ``fetch_docket_by_number(case_number: str)`` — direct single-case lookup
  for a known docket id.

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
    GaScAttorney,
    GaScDocket,
    GaScDocketEntry,
    GaScJudgment,
)

if TYPE_CHECKING:
    from collections.abc import Generator

    from jkent.data_types import ScraperYield


API_BASE = "https://sced-rest.gasupreme.us"
SEARCH_URL = f"{API_BASE}/public-docket/query"
CASE_DETAIL_URL = f"{API_BASE}/public-docket/case"

# Rolling window the API exposes. As of 2026-05 the oldest reachable case
# was docketed 2021-05-03, i.e. (today - ~5 years).
ROLLING_WINDOW_YEARS = 6


class GeorgiaSupremeCourtScraper(BaseScraper[GaScDocket]):
    """Scraper for the Supreme Court of Georgia docket system.

    The site has no date-based search and no auth/bot-protection, but the
    ``CaseNumber STARTS_WITH S{YY}`` query reliably returns every case
    docketed under that two-digit year prefix in a single uncapped JSON
    response. The scraper sweeps that prefix for the rolling 5-year window
    and fetches detail per case.
    """

    court_ids: ClassVar[set[str]] = {"ga"}
    court_url: ClassVar[str] = "https://www.gasupreme.us/docket-search/"
    data_types: ClassVar[set[str]] = {"dockets"}
    status: ClassVar[ScraperStatus] = ScraperStatus.IN_DEVELOPMENT
    version: ClassVar[str] = "2026-05-02"
    requires_auth: ClassVar[bool] = False
    rate_limits: ClassVar[list[Rate] | None] = [Rate(3, Duration.SECOND)]

    # =========================================================================
    # Entry points
    # =========================================================================

    @entry(GaScDocket)
    def get_all_dockets(self) -> Generator[Request, None, None]:
        """Sweep the rolling 5-year window via per-year prefix queries."""
        current_year = date.today().year
        for year in range(
            current_year - ROLLING_WINDOW_YEARS + 1, current_year + 1
        ):
            yy = year % 100
            prefix = f"S{yy:02d}"
            yield Request(
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url=SEARCH_URL,
                    params={"queryFilter": f"CaseNumber STARTS_WITH {prefix}"},
                ),
                continuation=self.parse_search_results,
                accumulated_data={"prefix": prefix},
                deduplication_key=f"ga-search-{prefix}",
            )

    @entry(GaScDocket)
    def get_dockets_after(
        self, watermark: str
    ) -> Generator[Request, None, None]:
        """Incremental sweep — fetch every case whose number sorts after ``watermark``.

        ``watermark`` is a case-number cursor (e.g. ``S26C1300`` from the
        previous run's max). The API's ``GREATER_THAN`` operator does a
        lexicographic comparison, which is the right semantic here because
        case numbers are assigned strictly sequentially within each
        ``S{YY}{LETTER}`` bucket and the ``S{YY}`` prefix sorts in calendar
        order.

        Only catches newly docketed cases — updates to existing ones aren't
        detectable through the search API and need a full refetch.
        """
        normalized = watermark.strip().upper()
        yield Request(
            request=HTTPRequestParams(
                method=HttpMethod.GET,
                url=SEARCH_URL,
                params={
                    "queryFilter": f"CaseNumber GREATER_THAN {normalized}"
                },
            ),
            continuation=self.parse_search_results,
            accumulated_data={"watermark": normalized},
            deduplication_key=f"ga-search-after-{normalized}",
        )

    @entry(GaScDocket)
    def fetch_docket_by_number(
        self, case_number: str
    ) -> Generator[Request, None, None]:
        """Direct lookup for a known case number (e.g. ``S26A0125``)."""
        normalized = case_number.strip().upper()
        yield Request(
            request=HTTPRequestParams(
                method=HttpMethod.GET,
                url=f"{CASE_DETAIL_URL}/{normalized}",
            ),
            continuation=self.parse_case_detail,
            accumulated_data={"docket_number": normalized},
            deduplication_key=f"ga-case-{normalized}",
        )

    # =========================================================================
    # Step 1: parse search results
    # =========================================================================

    @step()
    def parse_search_results(
        self,
        json_content: list,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[GaScDocket], None, None]:
        """Dispatch a detail fetch per case number returned by the prefix query."""
        for hit in json_content or []:
            case_number = (hit.get("caseNumber") or "").strip().upper()
            if not case_number:
                continue
            yield Request(
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url=f"{CASE_DETAIL_URL}/{case_number}",
                ),
                continuation=self.parse_case_detail,
                accumulated_data={
                    "docket_number": case_number,
                    "preview_case_style": hit.get("caseStyle"),
                },
                deduplication_key=f"ga-case-{case_number}",
            )

    # =========================================================================
    # Step 2: parse case detail
    # =========================================================================

    @step()
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

        docket = GaScDocket(
            docket_number=docket_number,
            court_id="ga",
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
        )
        yield ParsedData(data=docket)


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
