"""Wyoming Supreme Court Scraper.

Scrapes docket and oral argument data from the Wyoming Supreme Court
via the Appellate C-Track Electronic Filing Portal (CTEF) at
ctefiling.wyocourts.gov.

Supported courts:
- Wyoming Supreme Court (wyo)

Entry points:

- Dockets/Cases:
  - API: https://ctefiling-api.wyocourts.gov/courts/cms/cases
  - Portal: https://ctefiling.wyocourts.gov/portal/search/case

- Oral Arguments (Calendar):
  - API: https://ctefiling-api.wyocourts.gov/courts/cms/events
  - Note: the portal does not expose a public calendar UI, but the
    underlying TR Portal events API responds normally.

Dockets Flow (dockets_by_filing_date):
  1. dockets_by_filing_date -> date range search requests
  2. parse_dockets_search -> handles 10,000 result limit by splitting dates
     - Yields case detail requests for each case found
     - Paginates through all results
  3. parse_case_detail -> parses case header, yields party fetch request
  4. parse_case_parties -> parses parties, yields docket entries fetch request
  5. parse_docket_entries -> parses entries, chains into the ticklers fetch
  6. parse_ticklers_list -> parses deadlines, chains into the documents fetch
  7. parse_documents_list -> queues per-document archive downloads, yields WyoDocket
  8. parse_document_download -> emits a WyoDocument per archived file

Oral Arguments Flow (oral_arguments_by_argument_date):
  1. oral_arguments_by_argument_date -> events API search
  2. parse_events_list -> filters by court/date, yields hearing requests
  3. parse_event_hearings -> parses cases, yields WyoOralArgument objects
"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from jkent.common.decorators import entry, step
from jkent.data_types import BaseScraper, DriverRequirement, ScraperStatus
from pyrate_limiter import Duration, Rate

from juriscraper.state.common.params import InferrableDateRange
from juriscraper.state.common.tr.scraper import TRPortalMixin

from .models import (
    API_BASE_URL,
    COURT_CONFIG,
    PORTAL_URL,
    WyoDocket,
    WyoDocketEntry,
    WyoDocument,
    WyoOralArgument,
)

if TYPE_CHECKING:
    from collections.abc import Generator

    from jkent.data_types import Request, ScraperYield


class WyomingScraper(
    TRPortalMixin,
    BaseScraper[WyoDocket | WyoDocument | WyoOralArgument],
):
    """Scraper for the Wyoming Supreme Court.

    Scrapes dockets and oral argument information from the Wyoming
    Appellate C-Track Electronic Filing Portal (CTEF), which is a
    Thomson Reuters C-Track deployment.

    Entry points (driver seeds ``court_ids`` and the date range):
        - ``dockets_by_filing_date(court_ids, date_range)`` — cases filed in
          the window, server-side filtered by filed date.
        - ``oral_arguments_by_argument_date(court_ids, date_range)`` —
          calendar events scheduled in the window.
    """

    # === Metadata ===
    court_ids: ClassVar[set[str]] = {"wyo"}
    court_url: ClassVar[str] = "https://ctefiling.wyocourts.gov/"
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
    # Wyoming populates the per-case ticklers (deadlines) endpoint.
    TR_FETCH_TICKLERS: ClassVar[bool] = True

    # === Model classes ===
    DOCKET_CLASS: ClassVar[type] = WyoDocket
    DOCKET_ENTRY_CLASS: ClassVar[type] = WyoDocketEntry
    DOCUMENT_CLASS: ClassVar[type] = WyoDocument
    ORAL_ARGUMENT_CLASS: ClassVar[type] = WyoOralArgument

    # =========================================================================
    # Dockets Entry Points
    # =========================================================================

    @entry(WyoDocket)
    def dockets_by_filing_date(
        self,
        court_ids: set[str],
        date_range: InferrableDateRange,
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
    ) -> Generator[
        ScraperYield[WyoDocket | WyoDocument | WyoOralArgument], None, None
    ]:
        """Parse docket search results."""
        yield from self._tr_handle_dockets_search(
            json_content, accumulated_data
        )

    @step(priority=5)
    def parse_case_detail(
        self,
        json_content: dict,
        accumulated_data: dict,
    ) -> Generator[
        ScraperYield[WyoDocket | WyoDocument | WyoOralArgument], None, None
    ]:
        """Parse case detail and fetch parties."""
        yield from self._tr_handle_case_detail(json_content, accumulated_data)

    @step(priority=4)
    def parse_case_parties(
        self,
        json_content: dict,
        accumulated_data: dict,
    ) -> Generator[
        ScraperYield[WyoDocket | WyoDocument | WyoOralArgument], None, None
    ]:
        """Parse case parties and fetch docket entries."""
        yield from self._tr_handle_case_parties(json_content, accumulated_data)

    @step(priority=3)
    def parse_docket_entries(
        self,
        json_content: dict,
        accumulated_data: dict,
    ) -> Generator[
        ScraperYield[WyoDocket | WyoDocument | WyoOralArgument], None, None
    ]:
        """Parse docket entries and chain into the ticklers fetch."""
        yield from self._tr_handle_docket_entries(
            json_content, accumulated_data
        )

    @step(priority=2)
    def parse_ticklers_list(
        self,
        json_content: dict,
        accumulated_data: dict,
    ) -> Generator[
        ScraperYield[WyoDocket | WyoDocument | WyoOralArgument], None, None
    ]:
        """Parse ticklers (deadlines) and chain into the documents fetch."""
        yield from self._tr_handle_ticklers_list(
            json_content, accumulated_data
        )

    @step(priority=2)
    def parse_documents_list(
        self,
        json_content: dict,
        accumulated_data: dict,
    ) -> Generator[
        ScraperYield[WyoDocket | WyoDocument | WyoOralArgument], None, None
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
    ) -> Generator[ScraperYield[WyoDocument], None, None]:
        """Emit a WyoDocument record for an archived file."""
        yield from self._tr_handle_document_download(
            local_filepath, accumulated_data
        )

    # =========================================================================
    # Oral Arguments Entry Point
    # =========================================================================

    @entry(WyoOralArgument)
    def oral_arguments_by_argument_date(
        self,
        court_ids: set[str],
        date_range: InferrableDateRange,
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
    ) -> Generator[
        ScraperYield[WyoDocket | WyoDocument | WyoOralArgument], None, None
    ]:
        """Parse events list and yield hearing requests."""
        yield from self._tr_handle_events_list(json_content, accumulated_data)

    @step(priority=2)
    def parse_event_hearings(
        self,
        json_content: dict,
        accumulated_data: dict,
    ) -> Generator[
        ScraperYield[WyoDocket | WyoDocument | WyoOralArgument], None, None
    ]:
        """Parse event hearings and yield oral arguments."""
        yield from self._tr_handle_event_hearings(
            json_content, accumulated_data
        )
