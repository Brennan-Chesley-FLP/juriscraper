"""Pennsylvania UJS Portal appellate-court docket scraper.

Scrapes the Unified Judicial System web portal at
https://ujsportal.pacourts.us/CaseSearch for the three Pennsylvania
appellate courts (Supreme, Superior, Commonwealth).

The site is a server-rendered ASP.NET Core form. There is no per-case
HTML detail page; the only structured per-case artifact is a Crystal
Reports PDF "docket sheet" linked from each result row. The scraper
emits a ``PADocket`` per result row plus a ``PADocketSheetPDF`` for
each archived PDF — PDF parsing into structured docket entries is
handled post-hoc by a downstream parser.

Entry points
------------

- ``get_docket(docket_number)`` — single-docket lookup. Court is
  inferred from the docket-number prefix (see
  ``DOCKET_PREFIX_TO_COURT_ID``).
- ``get_supreme_dockets_by_date(date_range)`` — date-range walk for
  the Supreme Court of Pennsylvania.
- ``get_superior_dockets_by_date(date_range)`` — date-range walk for
  the Superior Court of Pennsylvania.
- ``get_commonwealth_dockets_by_date(date_range)`` — date-range walk
  for the Commonwealth Court of Pennsylvania.

Flow
----

1. GET ``/CaseSearch`` to obtain the form (and the
   ``__RequestVerificationToken`` anti-forgery hidden field).
2. POST the same URL with ``SearchBy=DocketNumber`` (single-docket) or
   ``SearchBy=AppellateCourtName`` (date-range) using
   ``find_form().submit()`` so every other hidden field — including the
   anti-forgery token — is preserved.
3. Parse the inline ``#caseSearchResultGrid`` table. Each data row
   becomes a ``PADocket`` plus an ``archive=True`` request for the
   docket-sheet PDF.
4. The archive request lands in ``handle_docket_sheet_pdf`` which
   emits ``PADocketSheetPDF`` with the driver-injected
   ``local_filepath``.

Result-cap handling
-------------------

The grid is capped at 500 data rows per search (verified empirically:
1-month, 6-month, and 1-year Superior windows all return exactly 500
rows). When ``parse_results`` sees the cap on a date-range walk, it
splits the window in half and resubmits both halves; single-docket
searches don't trigger the split.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING, ClassVar
from urllib.parse import urljoin

from jkent.common.decorators import entry, step
from jkent.common.page_element import PageElement
from jkent.common.param_models import DateRange
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

from .models import COURT_IDS, PADocket, PADocketSheetPDF

if TYPE_CHECKING:
    from collections.abc import Generator

    from jkent.data_types import ScraperYield


_Yield = PADocket | PADocketSheetPDF


# =========================================================================
# Site constants
# =========================================================================

BASE_URL = "https://ujsportal.pacourts.us"
SEARCH_URL = f"{BASE_URL}/CaseSearch"

# The single search form on /CaseSearch. ``find_form()`` will preserve
# every hidden input (including ``__RequestVerificationToken``) and let
# us override only the fields we care about via the ``data=`` kwarg.
SEARCH_FORM_XPATH = "//form[@id='case-search-form-id']"
RESULTS_TABLE_ID = "caseSearchResultGrid"

# Empirical row cap for the results grid. A search whose result count
# meets this cap is presumed truncated and the date range is split.
RESULT_ROW_CAP = 500

# Floor for date-range splitting. With a 1-day window we accept whatever
# row count comes back rather than continuing to split — same-day filings
# above the cap are extremely unlikely for these courts.
MIN_SPLIT_WINDOW = timedelta(days=1)

# The PDF endpoint (/Report/PacDocketSheet) returns 401 to clients with
# httpx's default User-Agent. Sent on every request via Request.permanent
# so it cascades through the form-submit POST and the PDF archive GET.
_BROWSER_HEADERS: dict[str, str] = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/147.0.0.0 Safari/537.36"
    ),
}

# AppellateCourtName form value → CourtListener ID. The site dropdown
# only offers these three values.
SITE_COURT_TO_COURT_ID: dict[str, str] = {
    "Supreme": "pa",
    "Superior": "pasuperct",
    "Commonwealth": "pacommwct",
}
COURT_ID_TO_SITE_COURT: dict[str, str] = {
    v: k for k, v in SITE_COURT_TO_COURT_ID.items()
}

# Docket-number prefix → CourtListener ID. Built from the full 2024
# filings of each court (the cap-bound observation enumerates every
# prefix that appears at least once). Prefixes are non-overlapping
# across the three appellate courts; an unknown prefix maps to None and
# the resulting ``PADocket.court_id`` falls back to the empty string —
# rare in practice and surfaced in QA via the ``court_id`` distribution
# of emitted records.
DOCKET_PREFIX_TO_COURT_ID: dict[str, str] = {
    # Supreme Court (district + AL=Allocatur / AP=Appeal / M=Miscellaneous)
    "EAL": "pa",
    "EAP": "pa",
    "EM": "pa",
    "MAL": "pa",
    "MAP": "pa",
    "MM": "pa",
    "WAL": "pa",
    "WAP": "pa",
    "WM": "pa",
    # Superior Court (district + DA=District Appeals / DM=District Misc.)
    "EDA": "pasuperct",
    "EDM": "pasuperct",
    "MDA": "pasuperct",
    "MDM": "pasuperct",
    "WDA": "pasuperct",
    "WDM": "pasuperct",
    # Commonwealth Court
    "CD": "pacommwct",
    "FR": "pacommwct",
    "MD": "pacommwct",
    "RQR": "pacommwct",
}


# =========================================================================
# Helpers
# =========================================================================


_DOCKET_PARTS_RE = re.compile(r"^\s*(\d+)\s+([A-Z]+)\s+(\d{4})\s*$")


def _split_docket_number(docket_number: str) -> tuple[str, str, str] | None:
    """Split a docket number like ``44 WM 2026`` into (seq, prefix, year)."""
    m = _DOCKET_PARTS_RE.match(docket_number)
    if not m:
        return None
    return m.group(1), m.group(2), m.group(3)


def _court_id_from_docket_number(docket_number: str) -> str:
    """Map a docket number to a CourtListener ID via its prefix.

    Returns the empty string for unknown prefixes — caller decides what
    to do with that. We deliberately do not raise here so a
    ``get_docket`` lookup against an unrecognized prefix still emits a
    record (with court_id="") rather than killing the scrape.
    """
    parts = _split_docket_number(docket_number)
    if parts is None:
        return ""
    return DOCKET_PREFIX_TO_COURT_ID.get(parts[1], "")


def _parse_mdy(text: str) -> date | None:
    """Parse an MM/DD/YYYY string from the results grid."""
    text = (text or "").strip()
    if not text:
        return None
    try:
        return datetime.strptime(text, "%m/%d/%Y").date()
    except ValueError:
        return None


def _cell_text(row: PageElement, column_index: int) -> str:
    """Return trimmed text of the ``column_index``-th ``<td>`` in ``row``.

    Returns ``""`` when the cell doesn't exist (defensive — appellate
    rows have all 19 columns even when most are empty).
    """
    cells = row.query_xpath("./td", "row cells", min_count=0)
    if column_index >= len(cells):
        return ""
    return cells[column_index].text_content().strip()


# =========================================================================
# Scraper
# =========================================================================


class PAUjsPortalScraper(BaseScraper[_Yield]):
    """Scraper for Pennsylvania appellate courts via the UJS web portal.

    Covers the Supreme, Superior, and Commonwealth courts of
    Pennsylvania. Pure httpx — no JS challenge, no captcha. The
    anti-forgery token from the form GET is the only stateful piece and
    is propagated by ``find_form().submit()``.
    """

    court_ids: ClassVar[set[str]] = {"pa", "pasuperct", "pacommwct"}
    court_url: ClassVar[str] = SEARCH_URL
    data_types: ClassVar[set[str]] = {"dockets"}
    status: ClassVar[ScraperStatus] = ScraperStatus.IN_DEVELOPMENT
    version: ClassVar[str] = "2026-05-04"
    requires_auth: ClassVar[bool] = False
    rate_limits: ClassVar[list[Rate] | None] = [Rate(1, Duration.SECOND * 15)]

    # The UJS portal intermittently 400s on otherwise-valid form POSTs —
    # observed at ~1% across a full backfill, all on /CaseSearch with a
    # well-formed body and a fresh anti-forgery token from the immediately
    # preceding GET. Treat 400 as transient so these get retried instead
    # of dropping the (often hundreds of) rows in that date window.
    TRANSIENT_HTTP_ERROR_CODES: ClassVar[frozenset[int]] = frozenset({400})

    # =====================================================================
    # Entry points
    # =====================================================================

    @entry(PADocket)
    def get_docket(self, docket_number: str) -> Generator[Request, None, None]:
        """Look up a single docket by its docket number (e.g. ``44 WM 2026``).

        The court is inferred from the docket-number prefix.
        """
        yield Request(
            request=HTTPRequestParams(
                method=HttpMethod.GET,
                url=SEARCH_URL,
            ),
            continuation=self.submit_docket_search,
            accumulated_data={
                "search_mode": "docket_number",
                "docket_number": docket_number,
            },
            permanent={"headers": _BROWSER_HEADERS},
        )

    @entry(PADocket)
    def get_supreme_dockets_by_date(
        self, date_range: DateRange
    ) -> Generator[Request, None, None]:
        """Walk Supreme Court of Pennsylvania dockets filed in ``date_range``."""
        yield self._appellate_search_request("pa", date_range)

    @entry(PADocket)
    def get_superior_dockets_by_date(
        self, date_range: DateRange
    ) -> Generator[Request, None, None]:
        """Walk Superior Court of Pennsylvania dockets filed in ``date_range``."""
        yield self._appellate_search_request("pasuperct", date_range)

    @entry(PADocket)
    def get_commonwealth_dockets_by_date(
        self, date_range: DateRange
    ) -> Generator[Request, None, None]:
        """Walk Commonwealth Court of Pennsylvania dockets filed in ``date_range``."""
        yield self._appellate_search_request("pacommwct", date_range)

    # =====================================================================
    # Helpers
    # =====================================================================

    def _appellate_search_request(
        self, court_id: str, date_range: DateRange
    ) -> Request:
        """Build the initial GET that fetches the form for a date-range walk."""
        return Request(
            request=HTTPRequestParams(
                method=HttpMethod.GET,
                url=SEARCH_URL,
            ),
            continuation=self.submit_appellate_search,
            accumulated_data={
                "search_mode": "appellate",
                "court_id": court_id,
                "date_gte": date_range.start.isoformat(),
                "date_lte": date_range.end.isoformat(),
            },
            # Multiple courts share the same SEARCH_URL GET; skip the
            # default URL-based dedup so the three appellate entries can
            # coexist in one scrape.
            deduplication_key=SkipDeduplicationCheck(),
            permanent={"headers": _BROWSER_HEADERS},
        )

    # =====================================================================
    # Step: submit the form
    # =====================================================================

    @step()
    def submit_docket_search(
        self,
        page: PageElement,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[_Yield], None, None]:
        """POST the case-search form for a single docket-number lookup."""
        form = page.find_form(SEARCH_FORM_XPATH, "case search form")
        yield form.submit(
            data={
                "SearchBy": "DocketNumber",
                "DocketNumber": accumulated_data["docket_number"],
            },
            continuation=self.parse_results,
            accumulated_data=accumulated_data,
        )

    @step()
    def submit_appellate_search(
        self,
        page: PageElement,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[_Yield], None, None]:
        """POST the case-search form for an appellate date-range walk."""
        site_court = COURT_ID_TO_SITE_COURT[accumulated_data["court_id"]]
        form = page.find_form(SEARCH_FORM_XPATH, "case search form")
        yield form.submit(
            data={
                "SearchBy": "AppellateCourtName",
                "AppellateCourtName": site_court,
                "FiledStartDate": accumulated_data["date_gte"],
                "FiledEndDate": accumulated_data["date_lte"],
            },
            continuation=self.parse_results,
            accumulated_data=accumulated_data,
            # Two date-range halves spawned by a cap-split will hit the
            # same SEARCH_URL with overlapping form bodies; skip dedup so
            # both run.
            deduplication_key=SkipDeduplicationCheck(),
        )

    # =====================================================================
    # Step: parse the results table
    # =====================================================================

    @step()
    def parse_results(
        self,
        page: PageElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[_Yield], None, None]:
        """Walk ``#caseSearchResultGrid`` rows, emitting docket + PDF Requests.

        On a date-range walk where the row count meets ``RESULT_ROW_CAP``,
        the date range is halved and both halves are resubmitted instead
        of yielding records — the truncated result set is presumed
        unreliable. The exception is a single-day window that still hits
        the cap: we accept the (truncated) results rather than spinning
        forever, since same-day filings above 500 don't actually occur
        for these courts.
        """
        rows = page.query_xpath(
            f"//table[@id='{RESULTS_TABLE_ID}']/tbody/tr",
            "case-search result rows",
            min_count=0,
        )

        is_appellate = accumulated_data["search_mode"] == "appellate"
        cap_hit = is_appellate and len(rows) >= RESULT_ROW_CAP
        if cap_hit and self._can_split(accumulated_data):
            yield from self._split_and_resubmit(page, accumulated_data)
            return

        for row in rows:
            docket = self._row_to_docket(
                row=row,
                accumulated_data=accumulated_data,
                response_url=response.url,
            )
            if docket is None:
                continue
            yield ParsedData(data=docket)
            if docket.docket_sheet_url:
                yield Request(
                    archive=True,
                    request=HTTPRequestParams(
                        method=HttpMethod.GET,
                        url=docket.docket_sheet_url,
                    ),
                    continuation=self.handle_docket_sheet_pdf,
                    expected_type="pdf",
                    accumulated_data={
                        "court_id": docket.court_id,
                        "docket_number": docket.docket_number,
                        "document_url": docket.docket_sheet_url,
                    },
                    # Same docket fetched by both a date-range walk and a
                    # docket-number lookup should fetch the PDF once. The
                    # full URL won't dedupe because the ``dnh`` token is
                    # per-session, so key on (court_id, docket_number).
                    deduplication_key=(
                        f"{docket.court_id}-{docket.docket_number}.pdf"
                    ),
                )

    # =====================================================================
    # Step: archive PDF
    # =====================================================================

    @step()
    def handle_docket_sheet_pdf(
        self,
        local_filepath: str | None,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[_Yield], None, None]:
        """Emit a ``PADocketSheetPDF`` for the archived docket-sheet PDF.

        Reached only via an ``archive=True`` request, so the kent driver
        injects ``local_filepath`` with the on-disk path of the PDF
        (``None`` if the archive itself failed).
        """
        yield ParsedData(
            data=PADocketSheetPDF(
                court_id=accumulated_data["court_id"],
                docket_number=accumulated_data["docket_number"],
                document_url=accumulated_data["document_url"],
                local_path=local_filepath,
            )
        )

    # =====================================================================
    # Internal: row → PADocket
    # =====================================================================

    # Column indices in #caseSearchResultGrid (0-based, includes the two
    # leading display:none sort-marker cells). Matches the headers list
    # observed in Phase 1: "Docket Number", "", "Docket Number",
    # "Court Type", "Case Caption", "Case Status", "Filing Date",
    # "Primary Participant(s)", "Date Of Birth(s)", "County",
    # "Court Office", "OTN", "Complaint #", "Incident #", "Event Type?",
    # "Event Status", "Event Date", "Event Location", "" (icons col).
    _COL_DOCKET_NUMBER = 2
    _COL_COURT_TYPE = 3
    _COL_CASE_CAPTION = 4
    _COL_CASE_STATUS = 5
    _COL_FILING_DATE = 6
    _COL_PRIMARY_PARTICIPANTS = 7
    _COL_COUNTY = 9
    _COL_COURT_OFFICE = 10
    _COL_OTN = 11
    _COL_COMPLAINT_NUMBER = 12
    _COL_INCIDENT_NUMBER = 13
    _COL_EVENT_TYPE = 14
    _COL_EVENT_STATUS = 15
    _COL_EVENT_DATE = 16
    _COL_EVENT_LOCATION = 17

    def _row_to_docket(
        self,
        row: PageElement,
        accumulated_data: dict,
        response_url: str,
    ) -> PADocket | None:
        """Build a ``PADocket`` from a single result-grid row.

        Returns ``None`` if the docket-number cell is empty (the row is
        malformed).
        """
        docket_number = _cell_text(row, self._COL_DOCKET_NUMBER)
        if not docket_number:
            return None

        # Court id: prefer the entry-point's choice on the date-range
        # walk (we know what we asked for); on the docket-number path we
        # have to derive it from the prefix.
        if accumulated_data["search_mode"] == "appellate":
            court_id = accumulated_data["court_id"]
        else:
            court_id = _court_id_from_docket_number(docket_number)

        # Pull the docket-sheet PDF link out of the icon cell. Each row
        # has two copies of the link (one for the desktop layout, one
        # nested in the hamburger panel for small-screen carousel) — we
        # want exactly one.
        sheet_hrefs = row.query_xpath_strings(
            "(.//a[contains(@href, '/Report/PacDocketSheet')])[1]/@href",
            "docket sheet href",
            min_count=0,
            max_count=1,
        )
        docket_sheet_url = (
            urljoin(response_url, sheet_hrefs[0]) if sheet_hrefs else None
        )

        return PADocket(
            court_id=court_id,
            docket_number=docket_number,
            case_caption=_cell_text(row, self._COL_CASE_CAPTION),
            case_status=_cell_text(row, self._COL_CASE_STATUS) or None,
            date_filed=_parse_mdy(_cell_text(row, self._COL_FILING_DATE)),
            court_type=_cell_text(row, self._COL_COURT_TYPE) or None,
            primary_participants=(
                _cell_text(row, self._COL_PRIMARY_PARTICIPANTS) or None
            ),
            county=_cell_text(row, self._COL_COUNTY) or None,
            court_office=_cell_text(row, self._COL_COURT_OFFICE) or None,
            otn=_cell_text(row, self._COL_OTN) or None,
            complaint_number=(
                _cell_text(row, self._COL_COMPLAINT_NUMBER) or None
            ),
            incident_number=(
                _cell_text(row, self._COL_INCIDENT_NUMBER) or None
            ),
            next_event_type=_cell_text(row, self._COL_EVENT_TYPE) or None,
            next_event_status=(
                _cell_text(row, self._COL_EVENT_STATUS) or None
            ),
            next_event_date=_parse_mdy(_cell_text(row, self._COL_EVENT_DATE)),
            next_event_location=(
                _cell_text(row, self._COL_EVENT_LOCATION) or None
            ),
            docket_sheet_url=docket_sheet_url,
            source_url=response_url,
        )

    # =====================================================================
    # Internal: cap-driven date-range split
    # =====================================================================

    @staticmethod
    def _can_split(accumulated_data: dict) -> bool:
        """True iff the current date range can be halved further."""
        start = date.fromisoformat(accumulated_data["date_gte"])
        end = date.fromisoformat(accumulated_data["date_lte"])
        return (end - start) > MIN_SPLIT_WINDOW

    def _split_and_resubmit(
        self,
        page: PageElement,
        accumulated_data: dict,
    ) -> Generator[Request, None, None]:
        """Halve the current date range and resubmit both halves.

        Reuses the form on the just-returned results page (which itself
        carries a fresh anti-forgery token) so we save a GET round-trip
        per split. Caller must have established that splitting is
        possible (``_can_split``).
        """
        start = date.fromisoformat(accumulated_data["date_gte"])
        end = date.fromisoformat(accumulated_data["date_lte"])
        midpoint = start + (end - start) // 2
        site_court = COURT_ID_TO_SITE_COURT[accumulated_data["court_id"]]
        form = page.find_form(SEARCH_FORM_XPATH, "case search form")

        for half_start, half_end in (
            (start, midpoint),
            (midpoint + timedelta(days=1), end),
        ):
            yield form.submit(
                data={
                    "SearchBy": "AppellateCourtName",
                    "AppellateCourtName": site_court,
                    "FiledStartDate": half_start.isoformat(),
                    "FiledEndDate": half_end.isoformat(),
                },
                continuation=self.parse_results,
                accumulated_data={
                    **accumulated_data,
                    "date_gte": half_start.isoformat(),
                    "date_lte": half_end.isoformat(),
                },
                deduplication_key=SkipDeduplicationCheck(),
            )


# Re-export COURT_IDS at module level for parity with other scrapers.
__all__ = ["PAUjsPortalScraper", "COURT_IDS"]
