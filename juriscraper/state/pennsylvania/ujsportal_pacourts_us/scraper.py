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

Per-row HTML extraction lives in the ``parsers`` package
(``ResultsGridParser``); the steps keep navigation concerns (the form
GET/POST anti-forgery handshake, the per-row PDF archive fan-out, and
the result-cap date-range split).

Entry points (§4):
    - dockets_by_filing_date(court_ids, date_range) — date-range walk for
      each requested appellate court (one search POST per court).
    - docket_by_number(court_id, docket_number)     — single-docket
      lookup; matches across all courts.

Flow:
    entry → submit_*_search → parse_results
                                ├→ (per row) handle_docket_sheet_pdf → ParsedData
                                └→ (cap hit) split window & resubmit → parse_results

Result-cap handling:
    The grid is capped at 500 data rows per search (verified empirically:
    1-month, 6-month, and 1-year Superior windows all return exactly 500
    rows). When ``parse_results`` sees the cap on a date-range walk, it
    splits the window in half and resubmits both halves; single-docket
    searches don't trigger the split.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import TYPE_CHECKING, ClassVar
from urllib.parse import urljoin

from jkent.common.decorators import entry, step
from jkent.common.exceptions import ScraperAssumptionException
from jkent.common.param_models import DateRange
from jkent.data_types import (
    BaseScraper,
    DriverRequirement,
    HTTPCodeType,
    HttpMethod,
    HTTPRequestParams,
    ParsedData,
    Request,
    Response,
    ScraperStatus,
    XPath,
)
from pyrate_limiter import Duration, Rate

from .models import COURT_IDS, SEARCH_URL, PADocket, PADocketSheetPDF
from .parsers import RESULTS_TABLE_ID, ResultsGridParser

if TYPE_CHECKING:
    from collections.abc import Generator

    from jkent.common.page_element import PageElement
    from jkent.data_types import ScraperYield


_Yield = PADocket | PADocketSheetPDF


# =========================================================================
# Site constants
# =========================================================================

# The single search form on /CaseSearch. ``find_form()`` preserves every
# hidden input (including ``__RequestVerificationToken``) and lets us
# override only the fields we care about via the ``data=`` kwarg.
SEARCH_FORM_XPATH = XPath("//form[@id='case-search-form-id']")

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

# AppellateCourtName form value ↔ CourtListener ID. The site dropdown only
# offers these three values.
SITE_COURT_TO_COURT_ID: dict[str, str] = {
    "Supreme": "pa",
    "Superior": "pasuperct",
    "Commonwealth": "pacommwct",
}
COURT_ID_TO_SITE_COURT: dict[str, str] = {
    v: k for k, v in SITE_COURT_TO_COURT_ID.items()
}


# =========================================================================
# Scraper
# =========================================================================


class PAUjsPortalScraper(BaseScraper[_Yield]):
    """Scraper for Pennsylvania appellate courts via the UJS web portal.

    Covers the Supreme, Superior, and Commonwealth courts of
    Pennsylvania. Pure HTTP — no JS challenge, no captcha. The
    anti-forgery token from the form GET is the only stateful piece and
    is propagated by ``find_form().submit()``.
    """

    # === Metadata ===
    court_ids: ClassVar[set[str]] = {"pa", "pasuperct", "pacommwct"}
    court_url: ClassVar[str] = SEARCH_URL
    data_types: ClassVar[set[str]] = {"dockets"}
    status: ClassVar[ScraperStatus] = ScraperStatus.IN_DEVELOPMENT
    version: ClassVar[str] = "2026-06-27"
    last_verified: ClassVar[str] = "2026-05-04"
    requires_auth: ClassVar[bool] = False
    driver_requirements: ClassVar[list[DriverRequirement]] = []
    rate_limits: ClassVar[list[Rate] | None] = [Rate(1, Duration.SECOND * 15)]

    # The UJS portal intermittently 400s on otherwise-valid form POSTs —
    # observed at ~1% across a full backfill, all on /CaseSearch with a
    # well-formed body and a fresh anti-forgery token from the immediately
    # preceding GET. Reclassify 400 as transient (default is persistent)
    # so these get retried instead of dropping the (often hundreds of)
    # rows in that date window.
    HTTP_CODE_TYPES: ClassVar[dict[int, HTTPCodeType]] = {
        400: HTTPCodeType.TRANSIENT,
    }

    # =====================================================================
    # Entry points (§4)
    # =====================================================================

    @entry(PADocket)
    def dockets_by_filing_date(
        self, court_ids: set[str], date_range: DateRange
    ) -> Generator[Request, None, None]:
        """Walk dockets filed within ``date_range`` for ``court_ids``.

        The site searches one appellate court per POST (via the
        ``AppellateCourtName`` form field), so one search is seeded per
        requested court (intersected with the three this scraper
        supports). ``parse_results`` splits the window when a search hits
        the 500-row result cap.
        """
        target_courts = sorted(court_ids & set(COURT_ID_TO_SITE_COURT))
        if not target_courts:
            raise ScraperAssumptionException(
                f"no supported PA appellate court in {sorted(court_ids)} "
                f"(supported: {sorted(COURT_ID_TO_SITE_COURT)})"
            )
        for court_id in target_courts:
            yield self._appellate_search_request(court_id, date_range)

    @entry(PADocket)
    def docket_by_number(
        self, court_id: str, docket_number: str
    ) -> Generator[Request, None, None]:
        """Look up a single docket by its number (e.g. ``44 WM 2026``).

        The site matches a docket number across all courts; ``court_id``
        is the court the caller expects the docket to belong to and is
        stamped onto the emitted record.
        """
        yield Request(
            request=HTTPRequestParams(
                method=HttpMethod.GET,
                url=SEARCH_URL,
            ),
            continuation=self.submit_docket_search,
            accumulated_data={
                "search_mode": "docket_number",
                "court": court_id,
                "docket_number": docket_number,
                "entry_point": "docket_by_number",
            },
            deduplication_key=f"docket_search_seed:{docket_number}",
            permanent={"headers": _BROWSER_HEADERS},
        )

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
                "court": court_id,
                "date_gte": date_range.start.isoformat(),
                "date_lte": date_range.end.isoformat(),
                "entry_point": "dockets_by_filing_date",
            },
            # Multiple courts share the same SEARCH_URL GET; key on the
            # court so the per-court seeds coexist in one scrape.
            deduplication_key=f"appellate_search_seed:{court_id}:"
            f"{date_range.start.isoformat()}:{date_range.end.isoformat()}",
            permanent={"headers": _BROWSER_HEADERS},
        )

    # =====================================================================
    # Steps: submit the form
    # =====================================================================

    @step(priority=4)
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
            deduplication_key=(
                f"docket_search:{accumulated_data['docket_number']}"
            ),
        )

    @step(priority=4)
    def submit_appellate_search(
        self,
        page: PageElement,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[_Yield], None, None]:
        """POST the case-search form for an appellate date-range walk."""
        site_court = COURT_ID_TO_SITE_COURT[accumulated_data["court"]]
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
            deduplication_key=(
                f"appellate_search:{accumulated_data['court']}:"
                f"{accumulated_data['date_gte']}:{accumulated_data['date_lte']}"
            ),
        )

    # =====================================================================
    # Step: parse the results table
    # =====================================================================

    @step(priority=3)
    def parse_results(
        self,
        page: PageElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[_Yield], None, None]:
        """Walk ``#caseSearchResultGrid`` rows, emitting docket + PDF Requests.

        ``ResultsGridParser`` owns the per-row extraction; this step
        stamps the off-page fields (``court``, ``source_url``,
        ``source_entry_point``), resolves the relative docket-sheet href,
        and dispatches the PDF archive fan-out.

        On a date-range walk where the row count meets ``RESULT_ROW_CAP``,
        the date range is halved and both halves are resubmitted instead
        of yielding records — the truncated result set is presumed
        unreliable. The exception is a single-day window that still hits
        the cap: we accept the (truncated) results rather than spinning
        forever, since same-day filings above 500 don't actually occur
        for these courts.
        """
        is_appellate = accumulated_data["search_mode"] == "appellate"

        # A bare row count for cap-detection (before parsing/filtering).
        row_count = len(
            page.query(
                XPath(f"//table[@id='{RESULTS_TABLE_ID}']/tbody/tr"),
                "case-search result rows",
                min_count=0,
            )
        )
        cap_hit = is_appellate and row_count >= RESULT_ROW_CAP
        if cap_hit and self._can_split(accumulated_data):
            yield from self._split_and_resubmit(page, accumulated_data)
            return

        court = accumulated_data["court"]
        entry_point = accumulated_data.get("entry_point")
        for deferred in ResultsGridParser()(page):
            raw = deferred.raw_data
            raw["court"] = court
            raw["source_url"] = response.url
            raw["source_entry_point"] = entry_point
            relative = raw.get("docket_sheet_url")
            sheet_url = urljoin(response.url, relative) if relative else None
            raw["docket_sheet_url"] = sheet_url

            yield ParsedData(PADocket.raw(**raw))

            if sheet_url:
                yield Request(
                    archive=True,
                    request=HTTPRequestParams(
                        method=HttpMethod.GET,
                        url=sheet_url,
                    ),
                    continuation=self.handle_docket_sheet_pdf,
                    expected_type="pdf",
                    accumulated_data={
                        "court": court,
                        "docket_number": raw["docket_number"],
                        "document_url": sheet_url,
                    },
                    # Same docket fetched by both a date-range walk and a
                    # docket-number lookup should fetch the PDF once. The
                    # full URL won't dedupe because the ``dnh`` token is
                    # per-session, so key on (court, docket_number).
                    # Avoid colons — this becomes a filename.
                    deduplication_key=(f"{court}-{raw['docket_number']}.pdf"),
                )

    # =====================================================================
    # Step: archive PDF (download — priority 1 via archive=True)
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
                court=accumulated_data["court"],
                docket_number=accumulated_data["docket_number"],
                document_url=accumulated_data["document_url"],
                local_path=local_filepath,
            )
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
        site_court = COURT_ID_TO_SITE_COURT[accumulated_data["court"]]
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
                deduplication_key=(
                    f"appellate_search:{accumulated_data['court']}:"
                    f"{half_start.isoformat()}:{half_end.isoformat()}"
                ),
            )


# Re-export COURT_IDS at module level for parity with other scrapers.
__all__ = ["PAUjsPortalScraper", "COURT_IDS"]
