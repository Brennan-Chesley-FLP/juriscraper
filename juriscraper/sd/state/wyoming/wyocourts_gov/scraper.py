"""Wyoming Supreme Court Opinion Scraper.

This module contains a scraper for opinions from the Wyoming Supreme Court.

Entry point:
- https://www.wyocourts.gov/wy-supreme-court-opinions/

Opinion Search:
- The page uses client-side JavaScript to load and display results
- Results are loaded after clicking the "Search" button
- Pagination is handled client-side with "Next" button

PDF URL pattern:
- https://documents.courts.state.wy.us/Opinions/{filename}.pdf
- Filenames vary (e.g., "Velasquez S-25-0114.pdf", "S-25-0257 Serrano - Order...pdf")

Flow:
  1. get_entry -> opinions search page (click Search to load results)
  2. parse_opinion_search -> extracts opinion metadata from results table
  3. yields ArchiveRequests for PDFs
  4. handle_opinion_download -> stores local paths, yields final clusters

Note: This scraper requires JavaScript interaction to trigger the initial search.
The page loads with an empty table and populates it after clicking "Search".

Design decisions:
- Uses DateRange filter on date_filed for searching
- Archives opinion PDFs via ArchiveRequest
- Handles pagination via "Next" button clicks
- Supports date-based filtering via form fields (optional)
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import TYPE_CHECKING, Any, ClassVar
from urllib.parse import urljoin

from juriscraper.scraper_driver.common.checked_html import CheckedHtmlElement
from juriscraper.scraper_driver.common.decorators import step
from juriscraper.scraper_driver.data_types import (
    ArchiveRequest,
    ArchiveResponse,
    BaseScraper,
    HttpMethod,
    HTTPRequestParams,
    NavigatingRequest,
    ParsedData,
    Response,
    ScraperStatus,
)

from .models import (
    COURT_IDS,
    WyomingOpinion,
    WyomingOpinionCluster,
)

if TYPE_CHECKING:
    from collections.abc import Generator

    from juriscraper.scraper_driver.data_types import ScraperYield


class WyomingScraper(BaseScraper[WyomingOpinionCluster]):
    """Scraper for Wyoming Supreme Court opinions.

    Scrapes opinions from the Wyoming Supreme Court website.

    Usage:
        # Scrape all opinions (default - current year)
        scraper = WyomingScraper()

        # Filter by date range
        params = WyomingScraper.params()
        params.WyomingOpinionCluster.date_filed.gte = date(2026, 1, 1)
        params.WyomingOpinionCluster.date_filed.lte = date(2026, 1, 31)
        scraper = WyomingScraper(params=params)

        # Lookup specific opinion ID
        params = WyomingScraper.params()
        params.WyomingOpinionCluster.opinion_id.value = "2026 WY 11"
        scraper = WyomingScraper(params=params)
    """

    # === Metadata ===
    court_ids: ClassVar[set[str]] = COURT_IDS
    court_url: ClassVar[str] = "https://www.wyocourts.gov/"
    data_types: ClassVar[set[str]] = {"opinions"}
    status: ClassVar[ScraperStatus] = ScraperStatus.IN_DEVELOPMENT
    version: ClassVar[str] = "2026-01-23"
    requires_auth: ClassVar[bool] = False

    # Rate limiting - be respectful to court servers
    msec_per_request_rate_limit: ClassVar[int] = 2000

    # Base URL for opinion search
    OPINION_SEARCH_URL = "https://www.wyocourts.gov/wy-supreme-court-opinions/"

    # === Regex patterns ===
    # Date pattern: M/D/YYYY or MM/DD/YYYY
    DATE_PATTERN = re.compile(r"(\d{1,2}/\d{1,2}/\d{4})")
    # Opinion ID pattern: YYYY WY # (e.g., "2026 WY 11")
    OPINION_ID_PATTERN = re.compile(r"(\d{4}\s+WY\s+\d+)")
    # Docket number pattern: S-YY-NNNN, D-YY-NNNN, etc.
    DOCKET_PATTERN = re.compile(r"([A-Z]-\d{2}-\d{4})")

    # Expected table headers
    EXPECTED_HEADERS = [
        "Opinion ID",
        "Publish Date",
        "Appellant",
        "Appellee",
        "Docket Number",
    ]

    def _parse_date(self, date_str: str) -> date | None:
        """Parse a date string in M/D/YYYY format.

        Args:
            date_str: Date string in M/D/YYYY format.

        Returns:
            Parsed date object, or None if parsing fails.
        """
        try:
            return datetime.strptime(date_str.strip(), "%m/%d/%Y").date()
        except ValueError:
            return None

    def _get_opinions_search_params(
        self,
    ) -> tuple[date | None, date | None, str | None]:
        """Extract search parameters for opinions from ScraperParams.

        Returns:
            Tuple of (date_gte, date_lte, opinion_id)
        """
        if self._params is None:
            return None, None, None

        try:
            model_proxy = self._params.WyomingOpinionCluster
        except AttributeError:
            return None, None, None

        date_gte = None
        date_lte = None
        opinion_id = None

        searchable = model_proxy.get_searchable_fields()

        date_field = searchable.get("date_filed")
        if date_field and date_field.is_set():
            date_gte = date_field.gte
            date_lte = date_field.lte

        opinion_id_field = searchable.get("opinion_id")
        if opinion_id_field and opinion_id_field.is_set():
            opinion_id = opinion_id_field.value

        return date_gte, date_lte, opinion_id

    # =========================================================================
    # Entry Point
    # =========================================================================

    def get_entry(self) -> Generator[NavigatingRequest, None, None]:
        """Yield initial request for opinion scraping.

        Note: The Wyoming opinions page requires JavaScript interaction.
        The page loads empty and populates after clicking "Search".
        The driver should handle this by clicking the Search button
        after the page loads.
        """
        date_gte, date_lte, opinion_id = self._get_opinions_search_params()

        yield NavigatingRequest(
            request=HTTPRequestParams(
                method=HttpMethod.GET,
                url=self.OPINION_SEARCH_URL,
            ),
            continuation=self.parse_opinion_search,
            accumulated_data={
                "opinion_id_filter": opinion_id,
                "date_gte": date_gte.isoformat() if date_gte else None,
                "date_lte": date_lte.isoformat() if date_lte else None,
                "page_number": 1,
            },
            # Note to driver: This page requires clicking the "Search" button
            # to populate the results table. The button selector is:
            # button[contains(text(), 'Search')]
            aux_data={
                "requires_js_interaction": True,
                "js_actions": [
                    {
                        "type": "click",
                        "selector": "button:has-text('Search')",
                        "wait_for": "table",
                    }
                ],
            },
        )

    # =========================================================================
    # Opinion Search Parsing
    # =========================================================================

    @step(xsd="xsds/parse_opinion_search.xsd")
    def parse_opinion_search(
        self,
        lxml_tree: CheckedHtmlElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[WyomingOpinionCluster], None, None]:
        """Parse the opinion search results page.

        Extracts opinion metadata from the results table and yields
        ArchiveRequests for each opinion PDF.
        """
        opinion_id_filter = accumulated_data.get("opinion_id_filter")
        date_gte_str = accumulated_data.get("date_gte")
        date_lte_str = accumulated_data.get("date_lte")

        date_gte = date.fromisoformat(date_gte_str) if date_gte_str else None
        date_lte = date.fromisoformat(date_lte_str) if date_lte_str else None

        # Find the results table - it should have headers for Opinion ID, etc.
        # The table is populated via JavaScript, so we expect it to be present
        # after the driver handles the JS interaction.
        result_rows = lxml_tree.xpath(
            "//table//tr[td[a[contains(@href, '.pdf')]]]"
        )

        if not result_rows:
            # Table might not be populated yet (JS not executed)
            # or no results for the search criteria
            return

        for row in result_rows:
            cells = row.xpath("./td")
            if len(cells) < 5:
                continue

            # Extract data from each cell
            # Cell 0: Opinion ID (link to PDF)
            opinion_id_cell = cells[0]
            pdf_links = opinion_id_cell.xpath(".//a[contains(@href, '.pdf')]")
            if not pdf_links:
                continue

            pdf_url = pdf_links[0].get("href", "")
            if not pdf_url.startswith("http"):
                pdf_url = urljoin(response.url, pdf_url)

            opinion_id_text = pdf_links[0].text_content().strip()

            # Normalize opinion ID (e.g., "2026 WY 11")
            opinion_id_match = self.OPINION_ID_PATTERN.search(opinion_id_text)
            if not opinion_id_match:
                continue
            opinion_id = opinion_id_match.group(1)

            # Cell 1: Publish Date
            publish_date_text = cells[1].text_content().strip()
            date_filed = None
            if publish_date_text:
                date_match = self.DATE_PATTERN.search(publish_date_text)
                if date_match:
                    date_filed = self._parse_date(date_match.group(1))

            # Cell 2: Appellant
            appellant = cells[2].text_content().strip() or None

            # Cell 3: Appellee
            appellee = cells[3].text_content().strip() or None

            # Cell 4: Docket Number
            docket_text = cells[4].text_content().strip()
            docket_number = docket_text

            # Build case name from appellant and appellee
            if appellant and appellee:
                # Extract first meaningful name for case name
                appellant_short = appellant.split(";")[0].strip()
                appellee_short = appellee.split(";")[0].strip()
                case_name = f"{appellant_short} v. {appellee_short}"
            else:
                case_name = appellant or appellee or f"Opinion {opinion_id}"

            # Apply filters
            if opinion_id_filter and opinion_id != opinion_id_filter:
                continue

            if date_filed:
                if date_gte and date_filed < date_gte:
                    continue
                if date_lte and date_filed > date_lte:
                    continue

            # Skip if we don't have a date_filed (required field)
            if not date_filed:
                continue

            # Build cluster data for accumulated_data
            cluster_data: dict[str, Any] = {
                "opinion_id": opinion_id,
                "court_id": "wyo",
                "case_name": case_name,
                "docket_number": docket_number,
                "appellant": appellant,
                "appellee": appellee,
                "date_filed": date_filed.isoformat(),
                "source_url": response.url,
                "opinions_data": [
                    {"download_url": pdf_url, "type": "majority"}
                ],
                "pending_downloads": 1,
                "completed_downloads": 0,
                "downloaded_paths": {},
            }

            yield ArchiveRequest(
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url=pdf_url,
                ),
                continuation=self.handle_opinion_download,
                expected_type="pdf",
                accumulated_data={
                    **cluster_data,
                    "current_download_index": 0,
                },
            )

        # Check for pagination - look for "Next" button and page indicator
        # Page indicator format: "Page 1 of 138"
        # Note: Pagination is handled client-side via JavaScript
        # The driver would need to click "Next" and re-parse
        # For now, we document this but don't implement multi-page scraping
        # as it requires JS interaction for each page

    # =========================================================================
    # PDF Download Handling
    # =========================================================================

    @step
    def handle_opinion_download(
        self,
        response: ArchiveResponse,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[WyomingOpinionCluster], None, None]:
        """Handle a downloaded opinion PDF."""
        current_index = accumulated_data["current_download_index"]

        accumulated_data["downloaded_paths"][current_index] = response.file_url
        accumulated_data["completed_downloads"] += 1

        if (
            accumulated_data["completed_downloads"]
            >= accumulated_data["pending_downloads"]
        ):
            yield from self._yield_final_opinion_cluster(accumulated_data)
        else:
            # Handle multiple PDFs per cluster (if needed in future)
            next_index = current_index + 1
            opinions_data = accumulated_data["opinions_data"]
            next_opinion = opinions_data[next_index]

            yield ArchiveRequest(
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url=next_opinion["download_url"],
                ),
                continuation=self.handle_opinion_download,
                expected_type="pdf",
                accumulated_data={
                    **accumulated_data,
                    "current_download_index": next_index,
                },
            )

    def _yield_final_opinion_cluster(
        self, accumulated_data: dict
    ) -> Generator[ScraperYield[WyomingOpinionCluster], None, None]:
        """Build and yield the final OpinionCluster with all PDFs downloaded."""
        opinions = []
        for i, op_data in enumerate(accumulated_data["opinions_data"]):
            local_path = accumulated_data["downloaded_paths"].get(i)
            opinions.append(
                WyomingOpinion(
                    download_url=op_data["download_url"],
                    type=op_data.get("type", "majority"),
                    local_path=local_path,
                )
            )

        date_filed = date.fromisoformat(accumulated_data["date_filed"])

        cluster = WyomingOpinionCluster(
            opinion_id=accumulated_data["opinion_id"],
            court_id=accumulated_data["court_id"],
            date_filed=date_filed,
            case_name=accumulated_data["case_name"],
            docket_number=accumulated_data["docket_number"],
            appellant=accumulated_data.get("appellant"),
            appellee=accumulated_data.get("appellee"),
            opinions=opinions,
            source_url=accumulated_data.get("source_url"),
        )

        yield ParsedData(cluster)
