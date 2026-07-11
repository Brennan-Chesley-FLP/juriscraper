"""Oklahoma Appellate Courts Scraper.

Scrapes docket data from the Oklahoma State Courts Network (OSCN) at
www.oscn.net. The OSCN appellate database (``db=appellate``) serves the
Oklahoma Supreme Court, Court of Civil Appeals, Court of Criminal
Appeals, Court on the Judiciary, and the Judicial Ethics Advisory Panel
in a single backend; the actual court for each case is determined by
parsing the case caption heading.

Per-page HTML extraction lives in the ``parsers`` package
(``SearchResultsParser`` / ``CaseDetailParser``); the steps keep
navigation concerns (the date-window chunking, the 500-row cap resume,
the per-case fan-out, and the lower-court follow-up).

Entry points (§4):
    - dockets_by_filing_date(court_ids, date_range) — date-range scan that
      pulls every appellate case filed in the window via ``Results.aspx``.
    - docket_by_number(court_id, docket_number)     — direct lookup of one
      known appellate case number via ``GetCaseInformation.aspx``.

Flow:
    dockets_by_filing_date → parse_search_results
                              └→ (per case) parse_case_detail → ParsedData
                                  └→ parse_lower_court_case → ParsedData
                                  └→ (archive) handle_document_download
    docket_by_number ──────────────────────────→ parse_case_detail → ...
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import TYPE_CHECKING, ClassVar

from jkent.common.decorators import entry, step
from jkent.common.exceptions import (
    ScraperAssumptionException,
)
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
    SkipDeduplicationCheck,
)
from pyrate_limiter import Duration, Rate

from juriscraper.state.common.headers import FF_HEADERS
from juriscraper.state.common.params import InferrableDateRange

from .models import (
    CASE_INFO_URL,
    COURT_IDS,
    SEARCH_RESULTS_URL,
    OkDocket,
    OkLowerCourtCase,
)
from .parsers import (
    CaseDetailParser,
    SearchResultsParser,
    county_hint_from_heading,
)

if TYPE_CHECKING:
    from collections.abc import Generator, Mapping

    from jkent.data_types import ScraperYield


# Each search URL hits a single date window — keep it short to stay well
# under the server-side cap.
SEARCH_CHUNK_DAYS = 7


class SearchVolumeAssumptionError(ScraperAssumptionException):
    """Raised when an OSCN date-range search returns the 500-row cap on
    a single-day window — meaning more than 500 cases were filed on the
    same day and the date-bisection trick can't subdivide further."""


class OklahomaScraper(BaseScraper[OkDocket]):
    """Scraper for Oklahoma appellate court dockets via oscn.net.

    Captures the full register of actions for each case — caption, court,
    opinion citation, parties, attorneys, events, lower-court counts, and
    every docket entry (with row colour and any attached TIFF/PDF) — off
    the case-detail HTML page, optionally following the lower-court
    reference to attach the originating trial-court docket.
    """

    # === Metadata ===
    court_ids: ClassVar[set[str]] = set(COURT_IDS.keys())
    court_url: ClassVar[str] = "https://www.oscn.net/"
    data_types: ClassVar[set[str]] = {"dockets"}
    status: ClassVar[ScraperStatus] = ScraperStatus.IN_DEVELOPMENT
    version: ClassVar[str] = "2026-06-27"
    last_verified: ClassVar[str] = "2026-04-30"
    requires_auth: ClassVar[bool] = False
    driver_requirements: ClassVar[list[DriverRequirement]] = []
    rate_limits: ClassVar[list[Rate] | None] = [Rate(1, Duration.SECOND)]
    # OSCN's WAF intermittently 403s the honest ``Juriscraper``/httpx UA;
    # present a full desktop-Firefox fingerprint instead.
    default_headers: ClassVar[Mapping[str, str]] = FF_HEADERS

    # =========================================================================
    # Search-request helpers
    # =========================================================================

    def _yield_search_chunks(
        self,
        date_gte: date,
        date_lte: date,
    ) -> Generator[Request, None, None]:
        """Split the date range into ``SEARCH_CHUNK_DAYS`` windows and
        yield one search request per chunk."""
        cur = date_gte
        while cur <= date_lte:
            chunk_end = min(
                cur + timedelta(days=SEARCH_CHUNK_DAYS - 1), date_lte
            )
            yield self._search_request(cur, chunk_end)
            cur = chunk_end + timedelta(days=1)

    def _search_request(self, start: date, end: date) -> Request:
        """Build one ``Results.aspx`` date-window search request."""
        return Request(
            request=HTTPRequestParams(
                method=HttpMethod.GET,
                url=SEARCH_RESULTS_URL,
                params={
                    "db": "appellate",
                    "FiledDateL": start.strftime("%m/%d/%Y"),
                    "FiledDateH": end.strftime("%m/%d/%Y"),
                },
            ),
            continuation=self.parse_search_results,
            accumulated_data={
                "search_start": start.isoformat(),
                "search_end": end.isoformat(),
            },
            # Pagination/cap-resume postbacks overlap windows by design;
            # per-case dedup filters the duplicates downstream.
            deduplication_key=SkipDeduplicationCheck(),
        )

    def _case_detail_request(
        self, detail_url: str, docket_number: str, *, entry_point: str
    ) -> Request:
        """Build a GET request for one appellate case-detail page."""
        return Request(
            request=HTTPRequestParams(
                method=HttpMethod.GET,
                url=detail_url,
            ),
            continuation=self.parse_case_detail,
            accumulated_data={
                "appellate_case_number": docket_number,
                "entry_point": entry_point,
            },
            deduplication_key=f"case_detail:{docket_number or detail_url}",
        )

    # =========================================================================
    # Entry points (§4)
    # =========================================================================

    @entry(OkDocket)
    def dockets_by_filing_date(
        self,
        court_ids: set[str],
        date_range: InferrableDateRange,
    ) -> Generator[Request, None, None]:
        """Date-range scan over every appellate case filed in the window.

        OSCN's ``Results.aspx`` enumerates by ``FiledDate``; the range is
        split into short windows so each request stays under the 500-row
        server cap, which is otherwise resumed in
        :meth:`parse_search_results`.
        """
        yield from self._yield_search_chunks(date_range.start, date_range.end)

    @entry(OkDocket)
    def docket_by_number(
        self,
        court_id: str,
        docket_number: str,
    ) -> Generator[Request, None, None]:
        """Direct lookup of one already-known appellate case number."""
        detail_url = f"{CASE_INFO_URL}?db=appellate&number={docket_number}"
        yield self._case_detail_request(
            detail_url, docket_number, entry_point="docket_by_number"
        )

    # =========================================================================
    # Step: parse search results
    # =========================================================================

    @step(priority=3)
    def parse_search_results(
        self,
        page: PageElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[OkDocket], None, None]:
        """Parse a ``Results.aspx`` table and fan out per-case requests.

        Cloudflare detection runs first so a challenge body raises
        ``TransientException`` (driver retries) rather than being read as
        an empty result page.

        500-row cap: ``Results.aspx`` caps every response at 500 rows. We
        always emit case-detail Requests for every row; if the cap warning
        is present we additionally yield a follow-up search whose start
        date is the latest date observed on the page (end date preserved).
        Per-case dedup filters the boundary day's overlap. If the cap is
        hit on a single-day window we raise ``SearchVolumeAssumptionError``
        since date bisection can't subdivide further.
        """
        parser = SearchResultsParser()
        rows = parser(page, response.url)

        entry_point = accumulated_data.get(
            "entry_point", "dockets_by_filing_date"
        )
        for row in rows:
            yield self._case_detail_request(
                row.detail_url, row.docket_number, entry_point=entry_point
            )

        # === 500-row cap handling ===
        if not parser.cap_hit(response.text):
            return

        row_dates = [r.date_filed for r in rows if r.date_filed is not None]
        if not row_dates:
            raise SearchVolumeAssumptionError(
                "Results page reports the 500-row cap but no result "
                "dates were parseable; cannot resume the search.",
                response.url,
            )

        oldest = min(row_dates)
        newest = max(row_dates)
        if oldest == newest:
            raise SearchVolumeAssumptionError(
                f"OSCN returned the 500-row cap on a single-day window "
                f"({oldest.isoformat()}); date bisection cannot "
                f"subdivide further.",
                response.url,
            )

        original_end = date.fromisoformat(accumulated_data["search_end"])
        resume_start = newest
        if resume_start >= original_end:
            return

        yield self._search_request(resume_start, original_end)

    # =========================================================================
    # Step: parse appellate case page
    # =========================================================================

    @step(priority=2)
    def parse_case_detail(
        self,
        page: PageElement,
        response: Response,
        text: str,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[OkDocket], None, None]:
        """Parse a ``GetCaseInformation.aspx`` appellate page.

        ``CaseDetailParser`` owns the page extraction; this step stamps
        provenance, decides whether to follow the lower-court reference,
        and queues the document archive downloads.
        """
        parser = CaseDetailParser(response.url)
        raw = parser(page)[0].raw_data
        if not raw.get("docket_number"):
            raw["docket_number"] = (
                accumulated_data.get("appellate_case_number") or ""
            )
        raw["source_url"] = response.url
        raw["source_entry_point"] = accumulated_data.get("entry_point")
        docket = OkDocket(**raw)

        # === Decide whether to fetch a lower-court case ===
        county_hint = county_hint_from_heading(docket.court_name or "")
        lower_case_number = parser.first_lower_court_number(
            docket.lower_court_counts
        )

        if county_hint and lower_case_number:
            lookup_url = (
                f"{CASE_INFO_URL}?db={county_hint}&number={lower_case_number}"
            )
            yield Request(
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url=lookup_url,
                ),
                continuation=self.parse_lower_court_case,
                accumulated_data={
                    "docket": docket.model_dump(mode="json"),
                    "county": county_hint,
                    "lower_case_number": lower_case_number,
                },
                deduplication_key=f"docket_lower_court:{county_hint}:{lower_case_number}",
            )
        else:
            yield ParsedData(data=docket)
            yield from self._yield_archive_requests(docket)

    # =========================================================================
    # Step: parse trial-court page
    # =========================================================================

    @step(priority=2)
    def parse_lower_court_case(
        self,
        page: PageElement,
        response: Response,
        text: str,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[OkDocket], None, None]:
        """Parse a trial-court ``GetCaseInformation.aspx`` page and attach
        it to the parent appellate docket before yielding."""
        docket = OkDocket.model_validate(accumulated_data["docket"])
        county = accumulated_data["county"]
        lower_case_number = accumulated_data["lower_case_number"]

        parser = CaseDetailParser(response.url)
        # A populated ``json_style`` block is the most reliable signal
        # that this is a real OSCN case page rather than a soft-404 stub.
        lc_json = parser.read_json_style(page)
        if lc_json.get("casenumber"):
            caption = parser.parse_trial_caption(page)
            case_name = caption.get("case_name") or lc_json.get("style")
            docket.lower_court_case = OkLowerCourtCase(
                court_db=county,
                docket_number=lc_json.get("casenumber") or lower_case_number,
                case_name=case_name,
                date_filed=caption.get("date_filed"),
                parties=parser.parse_parties(page),
                attorneys=parser.parse_attorneys(page),
                entries=parser.parse_docket_entries(page),
                source_url=response.url,
            )

        yield ParsedData(data=docket)
        yield from self._yield_archive_requests(docket)

    # =========================================================================
    # Step: handle archived document downloads
    # =========================================================================

    @step(priority=1)
    def handle_document_download(
        self,
        local_filepath: str | None,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[OkDocket], None, None]:
        """No-op continuation for archived TIFF/PDF downloads.

        kent's archive store records the file location keyed by the
        ``deduplication_key`` we supply; we don't need to mutate the
        already-emitted ``OkDocket`` here.
        """
        if False:
            yield  # pragma: no cover

    # =========================================================================
    # Archive request helpers
    # =========================================================================

    def _yield_archive_requests(
        self, docket: OkDocket
    ) -> Generator[Request, None, None]:
        """Yield archive Requests for every TIFF/PDF discovered on the
        docket (appellate + lower court). Each download dedups on the
        docket case number + document id + format so re-runs reuse the
        archive store."""
        archive_targets: list[tuple[str, str, str]] = []

        def collect(entries) -> None:
            for docket_entry in entries:
                if docket_entry.document_id and docket_entry.tiff_url:
                    archive_targets.append(
                        (
                            docket_entry.document_id,
                            docket_entry.tiff_url,
                            "tif",
                        )
                    )
                if docket_entry.document_id and docket_entry.pdf_url:
                    archive_targets.append(
                        (docket_entry.document_id, docket_entry.pdf_url, "pdf")
                    )

        collect(docket.entries)
        if docket.lower_court_case is not None:
            collect(docket.lower_court_case.entries)

        for doc_id, url, fmt in archive_targets:
            expected_type = "pdf" if fmt == "pdf" else "image"
            # File-download key — avoid colons (used in filenames).
            dedup = f"doc-{docket.docket_number}-{doc_id}-{fmt}"
            yield Request(
                archive=True,
                request=HTTPRequestParams(method=HttpMethod.GET, url=url),
                continuation=self.handle_document_download,
                expected_type=expected_type,
                accumulated_data={
                    "docket_number": docket.docket_number,
                    "document_id": doc_id,
                    "format": fmt,
                },
                deduplication_key=dedup,
            )
