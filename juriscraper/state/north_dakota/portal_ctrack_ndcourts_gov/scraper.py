"""North Dakota Supreme Court Scraper.

Scrapes docket and oral argument data from the North Dakota Supreme
Court via the North Dakota Appellate Case System (a Thomson Reuters
Case Management Systems / C-Track deployment) at
portal.ctrack.ndcourts.gov.

Supported courts:
- North Dakota Supreme Court (nd)

Entry points:

- Dockets/Cases:
  - API: https://portal-api.ctrack.ndcourts.gov/courts/cms/cases
  - Portal: https://portal.ctrack.ndcourts.gov/portal/search/case

- Oral Arguments (Calendar):
  - API: https://portal-api.ctrack.ndcourts.gov/courts/cms/events

Dockets Flow (dockets_by_filing_date):
  1. dockets_by_filing_date -> date range search requests
  2. parse_dockets_search -> handles 10,000 result limit by splitting dates
     - Yields case detail requests for each case found
     - Paginates through all results
  3. parse_case_detail -> parses case header, yields party fetch request
  4. parse_case_parties -> parses parties, yields docket entries fetch request
  5. parse_docket_entries -> parses entries, chains into the documents fetch
  6. parse_documents_list -> queues per-document archive downloads, yields NdDocket
  7. parse_document_download -> emits an NdDocument per archived file

Oral Arguments Flow (oral_arguments_by_argument_date):
  1. oral_arguments_by_argument_date -> events API search
  2. parse_events_list -> filters by court/date, yields hearing requests
  3. parse_event_hearings -> parses cases, yields NdOralArgument objects
"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from jkent.common.decorators import entry, step
from jkent.common.param_models import DateRange
from jkent.data_types import BaseScraper, DriverRequirement, ScraperStatus
from pyrate_limiter import Duration, Rate

from juriscraper.state.common.tr.scraper import TRPortalMixin

from .models import (
    API_BASE_URL,
    COURT_CONFIG,
    PORTAL_URL,
    NdDocket,
    NdDocketEntry,
    NdDocument,
    NdOralArgument,
)

if TYPE_CHECKING:
    from collections.abc import Generator

    from jkent.data_types import Request, ScraperYield


class NorthDakotaScraper(
    TRPortalMixin,
    BaseScraper[NdDocket | NdDocument | NdOralArgument],
):
    """Scraper for the North Dakota Supreme Court.

    Scrapes dockets and oral argument information from the North
    Dakota Appellate Case System, a Thomson Reuters C-Track
    deployment.

    Entry points (driver seeds ``court_ids`` and the date range):
        - ``dockets_by_filing_date(court_ids, date_range)`` — cases filed in
          the window, server-side filtered by filed date.
        - ``oral_arguments_by_argument_date(court_ids, date_range)`` —
          calendar events scheduled in the window.
    """

    # === Metadata ===
    court_ids: ClassVar[set[str]] = {"nd"}
    court_url: ClassVar[str] = "https://portal.ctrack.ndcourts.gov/"
    data_types: ClassVar[set[str]] = {"dockets", "oral_arguments"}
    status: ClassVar[ScraperStatus] = ScraperStatus.IN_DEVELOPMENT
    version: ClassVar[str] = "2026-06-25"
    last_verified: ClassVar[str] = "2026-04-30"
    requires_auth: ClassVar[bool] = False
    # Pure JSON REST API — no browser needed.
    driver_requirements: ClassVar[list[DriverRequirement]] = []

    rate_limits: ClassVar[list[Rate] | None] = [Rate(4, Duration.SECOND)]

    # === TR Portal configuration ===
    TR_API_BASE_URL: ClassVar[str] = API_BASE_URL
    TR_PORTAL_URL: ClassVar[str] = PORTAL_URL
    TR_COURT_CONFIG: ClassVar[dict] = COURT_CONFIG

    # === Model classes ===
    DOCKET_CLASS: ClassVar[type] = NdDocket
    DOCKET_ENTRY_CLASS: ClassVar[type] = NdDocketEntry
    DOCUMENT_CLASS: ClassVar[type] = NdDocument
    ORAL_ARGUMENT_CLASS: ClassVar[type] = NdOralArgument

    # =========================================================================
    # Dockets Entry Points
    # =========================================================================

    @entry(NdDocket)
    def dockets_by_filing_date(
        self,
        court_ids: set[str],
        date_range: DateRange,
    ) -> Generator[Request, None, None]:
        """Enumerate dockets filed within ``date_range`` for ``court_ids``.

        The ``cms/cases`` endpoint searches server-side by filed date;
        ``parse_dockets_search`` splits the range when a window exceeds the
        10,000-result cap.
        """
        target_courts = self._tr_get_target_courts(court_ids)
        yield from self._tr_yield_dockets_search_request(
            date_range.start, date_range.end, target_courts
        )

    # =========================================================================
    # Dockets Steps
    # =========================================================================

    @step(priority=6)
    def parse_dockets_search(
        self,
        json_content: dict,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[NdDocket | NdOralArgument], None, None]:
        """Parse docket search results."""
        yield from self._tr_handle_dockets_search(
            json_content, accumulated_data
        )

    @step(priority=5)
    def parse_case_detail(
        self,
        json_content: dict,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[NdDocket | NdOralArgument], None, None]:
        """Parse case detail and fetch parties."""
        yield from self._tr_handle_case_detail(json_content, accumulated_data)

    @step(priority=4)
    def parse_case_parties(
        self,
        json_content: dict,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[NdDocket | NdOralArgument], None, None]:
        """Parse case parties and fetch docket entries."""
        yield from self._tr_handle_case_parties(json_content, accumulated_data)

    @step(priority=3)
    def parse_docket_entries(
        self,
        json_content: dict,
        accumulated_data: dict,
    ) -> Generator[
        ScraperYield[NdDocket | NdDocument | NdOralArgument], None, None
    ]:
        """Parse docket entries and chain into the documents fetch."""
        yield from self._tr_handle_docket_entries(
            json_content, accumulated_data
        )

    @step(priority=2)
    def parse_documents_list(
        self,
        json_content: dict,
        accumulated_data: dict,
    ) -> Generator[
        ScraperYield[NdDocket | NdDocument | NdOralArgument], None, None
    ]:
        """Parse the documents access listing and chain doc downloads."""
        yield from self._tr_handle_documents_list(
            json_content, accumulated_data
        )

    @step(priority=2)
    def parse_document_download(
        self,
        local_filepath: str | None,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[NdDocument], None, None]:
        """Emit an NdDocument record for an archived file."""
        yield from self._tr_handle_document_download(
            local_filepath, accumulated_data
        )

    # =========================================================================
    # Oral Arguments Entry Point
    # =========================================================================

    @entry(NdOralArgument)
    def oral_arguments_by_argument_date(
        self,
        court_ids: set[str],
        date_range: DateRange,
    ) -> Generator[Request, None, None]:
        """Enumerate oral arguments scheduled within ``date_range``.

        The events endpoint searches server-side by start (argument) date;
        ``parse_events_list`` filters the all-courts feed down to
        ``court_ids``.
        """
        target_courts = self._tr_get_target_courts(court_ids)
        yield from self._tr_yield_events_request(
            date_range.start, date_range.end, target_courts
        )

    # =========================================================================
    # Oral Arguments Steps
    # =========================================================================

    @step(priority=3)
    def parse_events_list(
        self,
        json_content: dict,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[NdDocket | NdOralArgument], None, None]:
        """Parse events list and yield hearing requests."""
        yield from self._tr_handle_events_list(json_content, accumulated_data)

    @step(priority=2)
    def parse_event_hearings(
        self,
        json_content: dict,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[NdDocket | NdOralArgument], None, None]:
        """Parse event hearings and yield oral arguments."""
        yield from self._tr_handle_event_hearings(
            json_content, accumulated_data
        )
