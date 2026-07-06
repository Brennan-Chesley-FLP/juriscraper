"""Oregon Appellate Courts Scraper.

Scrapes docket and oral argument data from Oregon appellate courts
via the TR Portal at trportal.courts.oregon.gov.

Supported courts:
- Oregon Supreme Court (or)
- Oregon Court of Appeals (orctapp)

Entry points:

- Dockets/Cases:
  - API: https://trportal-api.courts.oregon.gov/courts/cms/cases
  - Portal: https://trportal.courts.oregon.gov/portal/search/case

- Oral Arguments (Calendar):
  - API: https://trportal-api.courts.oregon.gov/courts/cms/events
  - Portal: https://trportal.courts.oregon.gov/portal/search/calendar

Dockets Flow (dockets_by_filing_date):
  1. dockets_by_filing_date -> date range search requests
  2. parse_dockets_search -> handles 10,000 result limit by splitting dates
     - Yields case detail requests for each case found
     - Paginates through all results
  3. parse_case_detail -> parses case header, yields party fetch request
  4. parse_case_parties -> parses parties, yields docket entries fetch request
  5. parse_docket_entries -> parses entries, chains into the documents fetch
  6. parse_documents_list -> queues per-document archive downloads, yields OreDocket
  7. parse_document_download -> emits an OreDocument per archived file

Oral Arguments Flow (oral_arguments_by_argument_date):
  1. oral_arguments_by_argument_date -> events API search
  2. parse_events_list -> filters by court/date, yields hearing requests
  3. parse_event_hearings -> parses cases, yields OreOralArgument objects

Note: Oregon's TR Portal does not use the publications endpoint for
opinion release lists. Opinions are tracked via docket entries with
type "Case Dispositional Decision".
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
    OreDocket,
    OreDocketEntry,
    OreDocument,
    OreOralArgument,
)

if TYPE_CHECKING:
    from collections.abc import Generator

    from jkent.data_types import Request, ScraperYield


class OregonScraper(
    TRPortalMixin,
    BaseScraper[OreDocket | OreDocument | OreOralArgument],
):
    """Scraper for Oregon appellate court data.

    Scrapes dockets and oral argument information from Oregon's
    TR Portal (Thomson Reuters C-Track).

    Supports Oregon Supreme Court (or) and Court of Appeals (orctapp).

    Entry points (driver seeds ``court_ids`` and the date range):
        - ``dockets_by_filing_date(court_ids, date_range)`` — cases filed in
          the window, server-side filtered by filed date.
        - ``oral_arguments_by_argument_date(court_ids, date_range)`` —
          calendar events scheduled in the window.
    """

    # === Metadata ===
    court_ids: ClassVar[set[str]] = {"or", "orctapp"}
    court_url: ClassVar[str] = "https://trportal.courts.oregon.gov/"
    data_types: ClassVar[set[str]] = {"dockets", "oral_arguments"}
    status: ClassVar[ScraperStatus] = ScraperStatus.IN_DEVELOPMENT
    version: ClassVar[str] = "2026-06-25"
    last_verified: ClassVar[str] = "2026-04-14"
    requires_auth: ClassVar[bool] = False
    # Pure JSON REST API — no browser needed.
    driver_requirements: ClassVar[list[DriverRequirement]] = []

    rate_limits: ClassVar[list[Rate] | None] = [Rate(4, Duration.SECOND)]

    # === TR Portal configuration ===
    TR_API_BASE_URL: ClassVar[str] = API_BASE_URL
    TR_PORTAL_URL: ClassVar[str] = PORTAL_URL
    TR_COURT_CONFIG: ClassVar[dict] = COURT_CONFIG

    # === Model classes ===
    DOCKET_CLASS: ClassVar[type] = OreDocket
    DOCKET_ENTRY_CLASS: ClassVar[type] = OreDocketEntry
    DOCUMENT_CLASS: ClassVar[type] = OreDocument
    ORAL_ARGUMENT_CLASS: ClassVar[type] = OreOralArgument

    # =========================================================================
    # Dockets Entry Points
    # =========================================================================

    @entry(OreDocket)
    def dockets_by_filing_date(
        self,
        court_ids: set[str],
        date_range: InferrableDateRange,
    ) -> Generator[Request, None, None]:
        """Enumerate dockets filed within ``date_range`` for ``court_ids``.

        The ``cms/cases`` endpoint searches server-side by filed date;
        ``parse_dockets_search`` splits the range when a window exceeds the
        10,000-result cap and drops detail requests for courts outside the
        requested set.
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
        ScraperYield[OreDocket | OreDocument | OreOralArgument], None, None
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
        ScraperYield[OreDocket | OreDocument | OreOralArgument], None, None
    ]:
        """Parse case detail and fetch parties."""
        yield from self._tr_handle_case_detail(json_content, accumulated_data)

    @step(priority=4)
    def parse_case_parties(
        self,
        json_content: dict,
        accumulated_data: dict,
    ) -> Generator[
        ScraperYield[OreDocket | OreDocument | OreOralArgument], None, None
    ]:
        """Parse case parties and fetch docket entries."""
        yield from self._tr_handle_case_parties(json_content, accumulated_data)

    @step(priority=3)
    def parse_docket_entries(
        self,
        json_content: dict,
        accumulated_data: dict,
    ) -> Generator[
        ScraperYield[OreDocket | OreDocument | OreOralArgument], None, None
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
        ScraperYield[OreDocket | OreDocument | OreOralArgument], None, None
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
    ) -> Generator[ScraperYield[OreDocument], None, None]:
        """Emit an OreDocument record for an archived file."""
        yield from self._tr_handle_document_download(
            local_filepath, accumulated_data
        )

    # =========================================================================
    # Oral Arguments Entry Point
    # =========================================================================

    @entry(OreOralArgument)
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
        ScraperYield[OreDocket | OreDocument | OreOralArgument], None, None
    ]:
        """Parse events list and yield hearing requests."""
        yield from self._tr_handle_events_list(json_content, accumulated_data)

    @step(priority=2)
    def parse_event_hearings(
        self,
        json_content: dict,
        accumulated_data: dict,
    ) -> Generator[
        ScraperYield[OreDocket | OreDocument | OreOralArgument], None, None
    ]:
        """Parse event hearings and yield oral arguments."""
        yield from self._tr_handle_event_hearings(
            json_content, accumulated_data
        )
