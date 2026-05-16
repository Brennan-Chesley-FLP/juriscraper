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

Dockets Flow (get_dockets / get_dockets_by_date):
  1. get_dockets -> date range search requests
  2. parse_dockets_search -> handles 10,000 result limit by splitting dates
     - Yields case detail requests for each case found
     - Paginates through all results
  3. parse_case_detail -> parses case header, yields party fetch request
  4. parse_case_parties -> parses parties, yields docket entries fetch request
  5. parse_docket_entries -> parses entries, yields final OreDocket

Oral Arguments Flow (get_oral_arguments):
  1. get_oral_arguments -> events API search
  2. parse_events_list -> filters by court/date, yields hearing requests
  3. parse_event_hearings -> parses cases, yields OreOralArgument objects

Note: Oregon's TR Portal does not use the publications endpoint for
opinion release lists. Opinions are tracked via docket entries with
type "Case Dispositional Decision".
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import TYPE_CHECKING, ClassVar

from jkent.common.decorators import entry, step
from jkent.common.param_models import DateRange
from jkent.data_types import BaseScraper, ScraperStatus
from pyrate_limiter import Duration, Rate

from juriscraper.sd.state.common.tr.scraper import TRPortalMixin

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

    Usage:
        # Scrape everything (all data types, all courts)
        scraper = OregonScraper()

        # Scrape only dockets
        params = OregonScraper.params()
        params.OreOralArgument = None
        scraper = OregonScraper(params=params)

        # Scrape only Supreme Court dockets
        params = OregonScraper.params()
        params.OreOralArgument = None
        params.OreDocket.court_id.values = {"or"}
        scraper = OregonScraper(params=params)

        # Filter dockets by date range
        params = OregonScraper.params()
        params.OreDocket.date_filed.gte = date(2025, 1, 1)
        params.OreDocket.date_filed.lte = date(2025, 12, 31)
        scraper = OregonScraper(params=params)
    """

    # === Metadata ===
    court_ids: ClassVar[set[str]] = {"or", "orctapp"}
    court_url: ClassVar[str] = "https://trportal.courts.oregon.gov/"
    data_types: ClassVar[set[str]] = {"dockets", "oral_arguments"}
    status: ClassVar[ScraperStatus] = ScraperStatus.IN_DEVELOPMENT
    version: ClassVar[str] = "2026-04-14"
    requires_auth: ClassVar[bool] = False

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
    def get_dockets(self) -> Generator[Request, None, None]:
        """Yield initial requests for dockets scraping.

        Uses date range splitting to handle the 10,000 result limit.
        If no date range is specified, defaults to searching from 2012.
        """
        date_gte, date_lte, _, _ = self._tr_get_search_params("OreDocket")

        if date_gte is None:
            date_gte = date(2012, 1, 1)
        if date_lte is None:
            date_lte = date.today()

        yield from self._tr_yield_dockets_search_request(date_gte, date_lte)

    @entry(OreDocket)
    def get_dockets_by_date(
        self,
        date_range: DateRange,
    ) -> Generator[Request, None, None]:
        """Yield requests for dockets within the supplied date range."""
        yield from self._tr_yield_dockets_search_request(
            date_range.start, date_range.end
        )

    # =========================================================================
    # Dockets Steps
    # =========================================================================

    @step()
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

    @step()
    def parse_case_detail(
        self,
        json_content: dict,
        accumulated_data: dict,
    ) -> Generator[
        ScraperYield[OreDocket | OreDocument | OreOralArgument], None, None
    ]:
        """Parse case detail and fetch parties."""
        yield from self._tr_handle_case_detail(json_content, accumulated_data)

    @step()
    def parse_case_parties(
        self,
        json_content: dict,
        accumulated_data: dict,
    ) -> Generator[
        ScraperYield[OreDocket | OreDocument | OreOralArgument], None, None
    ]:
        """Parse case parties and fetch docket entries."""
        yield from self._tr_handle_case_parties(json_content, accumulated_data)

    @step()
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

    @step()
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

    @step()
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
    def get_oral_arguments(self) -> Generator[Request, None, None]:
        """Yield initial requests for oral arguments scraping.

        Searches for calendar events across all target courts.
        Defaults to 6 months past to 1 year future.
        """
        date_gte, date_lte, _, _ = self._tr_get_search_params(
            "OreOralArgument", date_field_name="date_argued"
        )

        if date_gte is None:
            date_gte = date.today() - timedelta(days=180)
        if date_lte is None:
            date_lte = date.today() + timedelta(days=365)

        yield from self._tr_yield_events_request(date_gte, date_lte)

    # =========================================================================
    # Oral Arguments Steps
    # =========================================================================

    @step()
    def parse_events_list(
        self,
        json_content: dict,
        accumulated_data: dict,
    ) -> Generator[
        ScraperYield[OreDocket | OreDocument | OreOralArgument], None, None
    ]:
        """Parse events list and yield hearing requests."""
        _, _, _, court_ids = self._tr_get_search_params(
            "OreOralArgument", date_field_name="date_argued"
        )
        target_courts = self._tr_get_target_courts(court_ids)

        yield from self._tr_handle_events_list(
            json_content, accumulated_data, target_courts
        )

    @step()
    def parse_event_hearings(
        self,
        json_content: dict,
        accumulated_data: dict,
    ) -> Generator[
        ScraperYield[OreDocket | OreDocument | OreOralArgument], None, None
    ]:
        """Parse event hearings and yield oral arguments."""
        _, _, case_number_filter, _ = self._tr_get_search_params(
            "OreOralArgument", date_field_name="date_argued"
        )

        yield from self._tr_handle_event_hearings(
            json_content, accumulated_data, case_number_filter
        )
