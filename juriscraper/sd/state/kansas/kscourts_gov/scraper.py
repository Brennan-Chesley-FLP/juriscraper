"""Kansas Appellate Courts Scraper.

This module scrapes opinions and orders from the Kansas Supreme Court and
Court of Appeals using the searchdro.kscourts.gov decisions search portal.

Entry point:
- Search Page: https://searchdro.kscourts.gov/Documents/LoadPage

Flow:
1. get_entry -> Search page URL (if "opinions" requested)
2. parse_search_results -> Parses results table, yields ArchiveRequests for PDFs
3. handle_opinion_download -> Yields final KansasOpinionCluster

Design decisions:
- Uses the decisions search portal which defaults to showing last 3 months
- Parses HTML table directly (DataTables JS renders table structure server-side)
- Uses DateRange filter on date_filed for searching
- Uses SetFilter on court_id to select which courts to scrape
- Supports filtering by publication status (Published/Unpublished)
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import TYPE_CHECKING, ClassVar
from urllib.parse import urljoin

from juriscraper.scraper_driver.common.checked_html import CheckedHtmlElement
from juriscraper.scraper_driver.common.decorators import entry, step
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
    COURT_NAME_TO_ID,
    KansasOpinion,
    KansasOpinionCluster,
)

if TYPE_CHECKING:
    from collections.abc import Generator

    from juriscraper.scraper_driver.data_types import ScraperYield


# Search page URL
SEARCH_PAGE_URL = "https://searchdro.kscourts.gov/Documents/LoadPage"
BASE_URL = "https://searchdro.kscourts.gov"

# Expected table columns
EXPECTED_COLUMNS = [
    "Release Date",
    "Case Number",
    "Case Title",
    "Court",
    "Status",
    "PDF",
]


class KansasScraper(BaseScraper[KansasOpinionCluster]):
    """Scraper for Kansas appellate court opinions via decisions search portal.

    Scrapes opinions and orders from the Kansas Supreme Court (kan) and
    Court of Appeals (kanctapp).

    Usage:
        # Scrape all opinions from both courts
        scraper = KansasScraper()

        # Scrape only Supreme Court opinions
        params = KansasScraper.params()
        params.KansasOpinionCluster.court_id.values = {"kan"}
        scraper = KansasScraper(params=params)

        # Scrape only Court of Appeals opinions
        params = KansasScraper.params()
        params.KansasOpinionCluster.court_id.values = {"kanctapp"}
        scraper = KansasScraper(params=params)

        # Filter opinions by date range
        params = KansasScraper.params()
        params.KansasOpinionCluster.date_filed.gte = date(2026, 1, 1)
        params.KansasOpinionCluster.date_filed.lte = date(2026, 1, 31)
        scraper = KansasScraper(params=params)
    """

    # === Metadata ===
    court_ids: ClassVar[set[str]] = {"kan", "kanctapp"}
    court_url: ClassVar[str] = "https://kscourts.gov/"
    data_types: ClassVar[set[str]] = {"opinions"}
    status: ClassVar[ScraperStatus] = ScraperStatus.IN_DEVELOPMENT
    version: ClassVar[str] = "2026-01-22"
    requires_auth: ClassVar[bool] = False

    # Rate limiting - be respectful to court servers
    msec_per_request_rate_limit: ClassVar[int] = 1000

    # === Regex patterns ===
    # Case number pattern: 6-digit number
    CASE_NUMBER_PATTERN = re.compile(r"^(\d{6})$")

    # Date pattern from table: MM/DD/YYYY
    DATE_PATTERN = re.compile(r"(\d{1,2})/(\d{1,2})/(\d{4})")

    # Mapping from model name to data type
    MODEL_TO_DATA_TYPE: ClassVar[dict[str, str]] = {
        "KansasOpinionCluster": "opinions",
    }

    def _get_requested_data_types(self) -> set[str]:
        """Get the set of data types to scrape based on enabled models."""
        if self._params is None:
            return self.data_types

        enabled_models = self._params.get_enabled_models()
        if not enabled_models:
            return set()

        enabled_data_types = set()
        for model_name in enabled_models:
            if model_name in self.MODEL_TO_DATA_TYPE:
                enabled_data_types.add(self.MODEL_TO_DATA_TYPE[model_name])

        return enabled_data_types & self.data_types

    def _get_search_params(
        self,
    ) -> tuple[date | None, date | None, str | None, set[str] | None]:
        """Extract search parameters from ScraperParams.

        Returns:
            Tuple of (date_gte, date_lte, docket_id, court_ids)
        """
        if self._params is None:
            return None, None, None, None

        try:
            model_proxy = self._params.KansasOpinionCluster
        except AttributeError:
            return None, None, None, None

        date_gte = None
        date_lte = None
        docket_id = None
        court_ids = None

        searchable = model_proxy.get_searchable_fields()

        date_field = searchable.get("date_filed")
        if date_field and date_field.is_set():
            date_gte = date_field.gte
            date_lte = date_field.lte

        docket_field = searchable.get("docket_id")
        if docket_field and docket_field.is_set():
            docket_id = docket_field.value

        court_field = searchable.get("court_id")
        if court_field and court_field.is_set():
            court_ids = court_field.values

        return date_gte, date_lte, docket_id, court_ids

    def _parse_date(self, date_str: str) -> date | None:
        """Parse date from table format (MM/DD/YYYY).

        Args:
            date_str: Date like '1/16/2026' or '01/16/2026'

        Returns:
            Parsed date or None
        """
        match = self.DATE_PATTERN.match(date_str.strip())
        if match:
            month, day, year = match.groups()
            return date(int(year), int(month), int(day))
        return None

    def _get_court_id_from_name(self, court_name: str) -> str | None:
        """Determine court ID from court name in table.

        Args:
            court_name: Court name like 'Supreme Court' or 'Court of Appeals'

        Returns:
            Court ID ('kan' or 'kanctapp') or None if unrecognized
        """
        return COURT_NAME_TO_ID.get(court_name.strip())

    def _get_precedential_status(self, status: str) -> str:
        """Convert table status to standard precedential status.

        Args:
            status: Status like 'Published' or 'Unpublished'

        Returns:
            Standardized status string
        """
        status = status.strip().lower()
        if status == "published":
            return "Published"
        elif status == "unpublished":
            return "Unpublished"
        return "Unknown"

    # =========================================================================
    # Entry Point
    # =========================================================================

    @entry(KansasOpinionCluster)
    def get_entry(self) -> Generator[NavigatingRequest, None, None]:
        """Yield initial request to search page."""
        requested = self._get_requested_data_types()

        if "opinions" in requested:
            yield NavigatingRequest(
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url=SEARCH_PAGE_URL,
                ),
                continuation=self.parse_search_results,
            )

    # =========================================================================
    # Search Results Parsing
    # =========================================================================

    @step(xsd="xsds/parse_search_results.xsd")
    def parse_search_results(
        self,
        lxml_tree: CheckedHtmlElement,
        response: Response,
    ) -> Generator[ScraperYield[KansasOpinionCluster], None, None]:
        """Parse search results table and yield requests for each opinion PDF."""
        date_gte, date_lte, target_docket, court_ids = (
            self._get_search_params()
        )

        # Validate table headers to ensure structure hasn't changed
        headers = lxml_tree.checked_xpath(
            "//table[@id='example']//th/text()",
            "table headers",
            min_count=6,
            max_count=6,
            type=str,
        )

        # Validate header names match expected columns
        for i, expected in enumerate(EXPECTED_COLUMNS):
            actual = headers[i].strip().split(":")[0]  # Remove sorting hint
            if expected.lower() != actual.lower():
                raise ValueError(
                    f"Unexpected column header at position {i}: "
                    f"expected '{expected}', got '{actual}'"
                )

        # Find all data rows in the table body
        rows = lxml_tree.checked_xpath(
            "//table[@id='example']/tbody/tr",
            "result rows",
            min_count=0,
        )

        for row in rows:
            # Extract cells from the row
            cells = row.checked_xpath(
                "td",
                "row cells",
                min_count=6,
                max_count=6,
            )

            # Extract data from each cell
            release_date_str = cells[0].text_content().strip()
            case_number = cells[1].text_content().strip()
            case_title = cells[2].text_content().strip()
            court_name = cells[3].text_content().strip()
            status = cells[4].text_content().strip()

            # Extract PDF URL from the link in the last cell
            pdf_links = cells[5].checked_xpath(
                ".//a/@href",
                "PDF link",
                min_count=1,
                max_count=1,
                type=str,
            )
            pdf_path = pdf_links[0]
            pdf_url = urljoin(BASE_URL, pdf_path)

            # Parse date
            release_date = self._parse_date(release_date_str)
            if release_date is None:
                continue

            # Get court ID
            court_id = self._get_court_id_from_name(court_name)
            if court_id is None:
                continue

            # Filter by court if specified
            if court_ids and court_id not in court_ids:
                continue

            # Filter by specific docket if specified
            if target_docket and case_number != target_docket:
                continue

            # Filter by date range if specified
            if date_gte and release_date < date_gte:
                continue
            if date_lte and release_date > date_lte:
                continue

            # Get precedential status
            precedential_status = self._get_precedential_status(status)

            # Build accumulated data for download handler
            cluster_data = {
                "docket_id": case_number,
                "court_id": court_id,
                "date_filed": release_date.isoformat(),
                "case_name": case_title,
                "source_url": response.url,
                "precedential_status": precedential_status,
                "opinions_data": [{"download_url": pdf_url}],
                "pending_downloads": 1,
                "completed_downloads": 0,
                "downloaded_paths": {},
            }

            # Yield ArchiveRequest for the PDF
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

    # =========================================================================
    # Download Handler
    # =========================================================================

    @step
    def handle_opinion_download(
        self,
        response: ArchiveResponse,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[KansasOpinionCluster], None, None]:
        """Handle a downloaded opinion PDF."""
        current_index = accumulated_data["current_download_index"]

        accumulated_data["downloaded_paths"][current_index] = response.file_url
        accumulated_data["completed_downloads"] += 1

        if (
            accumulated_data["completed_downloads"]
            >= accumulated_data["pending_downloads"]
        ):
            yield from self._yield_final_cluster(accumulated_data)
        else:
            # Download next file if any
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

    def _yield_final_cluster(
        self, accumulated_data: dict
    ) -> Generator[ScraperYield[KansasOpinionCluster], None, None]:
        """Build and yield the final OpinionCluster with all PDFs downloaded."""
        opinions = []
        for i, op_data in enumerate(accumulated_data["opinions_data"]):
            local_path = accumulated_data["downloaded_paths"].get(i)
            opinions.append(
                KansasOpinion(
                    download_url=op_data["download_url"],
                    local_path=local_path,
                )
            )

        date_filed = datetime.fromisoformat(
            accumulated_data["date_filed"]
        ).date()

        cluster = KansasOpinionCluster(
            docket_id=accumulated_data["docket_id"],
            court_id=accumulated_data["court_id"],
            date_filed=date_filed,
            case_name=accumulated_data["case_name"],
            opinions=opinions,
            source_url=accumulated_data["source_url"],
            precedential_status=accumulated_data["precedential_status"],
        )

        yield ParsedData(cluster)
