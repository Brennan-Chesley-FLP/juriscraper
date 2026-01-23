"""Delaware Courts Opinions Scraper.

This module contains a scraper for opinions from the Delaware Courts website.
The site uses JavaScript to render the opinions table dynamically.

Entry points:
- Opinions: https://courts.delaware.gov/opinions/

Opinions Flow:
  1. get_entry -> opinions page with optional court filter
  2. parse_opinions_page -> parses table, extracts opinion data and download URLs
  3. handle_opinion_download -> stores local paths, yields final clusters

Design notes:
- The page requires JavaScript rendering (use Playwright driver)
- Each table row has a button that, when clicked, navigates to Download.aspx?id={id}
- We extract the opinion ID from the button's onclick or data attribute
- Uses date-based filtering via URL parameters
- Uses court filtering via the 'ag' URL parameter

Supported courts:
- Delaware Supreme Court (del)
- Delaware Court of Chancery (delch)
- Superior Court of Delaware (delsuperct)
- Delaware Court of Common Pleas (delctcompl)
- Delaware Family Court (delfamct)
- Delaware Justice of the Peace Courts (deljustpct)
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import TYPE_CHECKING, ClassVar

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
    COURT_URL_FILTER_MAP,
    DelOpinion,
    DelOpinionCluster,
    get_court_id,
)

if TYPE_CHECKING:
    from collections.abc import Generator

    from juriscraper.scraper_driver.data_types import ScraperYield

# Base URLs
BASE_URL = "https://courts.delaware.gov"
OPINIONS_URL = "https://courts.delaware.gov/opinions/"
DOWNLOAD_URL_PATTERN = (
    "https://courts.delaware.gov/Opinions/Download.aspx?id={id}"
)


class DelawareScraper(BaseScraper[DelOpinionCluster]):
    """Scraper for Delaware court opinions.

    Scrapes opinions from all Delaware courts including Supreme Court,
    Court of Chancery, Superior Court, and others.

    Note: This scraper requires a Playwright/browser driver because the
    Delaware Courts website uses JavaScript to render the opinions table.

    Usage:
        # Scrape all courts, all opinions for this year
        scraper = DelawareScraper()

        # Scrape only Supreme Court opinions
        params = DelawareScraper.params()
        params.DelOpinionCluster.court_id.values = {"del"}
        scraper = DelawareScraper(params=params)

        # Scrape with date range
        params = DelawareScraper.params()
        params.DelOpinionCluster.date_filed.gte = date(2025, 1, 1)
        params.DelOpinionCluster.date_filed.lte = date(2025, 1, 31)
        scraper = DelawareScraper(params=params)

        # Scrape Court of Chancery only
        params = DelawareScraper.params()
        params.DelOpinionCluster.court_id.values = {"delch"}
        scraper = DelawareScraper(params=params)
    """

    # === Metadata ===
    court_ids: ClassVar[set[str]] = {
        "del",
        "delch",
        "delsuperct",
        "delctcompl",
        "delfamct",
        "deljustpct",
    }
    court_url: ClassVar[str] = "https://courts.delaware.gov/"
    data_types: ClassVar[set[str]] = {"opinions"}
    status: ClassVar[ScraperStatus] = ScraperStatus.IN_DEVELOPMENT
    version: ClassVar[str] = "2026-01-22"
    requires_auth: ClassVar[bool] = False

    # Rate limiting - be respectful to court servers
    msec_per_request_rate_limit: ClassVar[int] = 2000

    # === XPath definitions ===
    # Table structure from Delaware opinions page
    XPATH_OPINION_ROWS = "//table//tbody//tr"
    XPATH_CELL_BUTTON = ".//td[1]//button"
    XPATH_CELL_DATE = ".//td[2]"
    XPATH_CELL_FILE_NUMBER = ".//td[3]"
    XPATH_CELL_COURT = ".//td[4]"
    XPATH_CELL_TYPE = ".//td[5]"
    XPATH_CELL_JUDICIAL_OFFICER = ".//td[6]"
    XPATH_CELL_DESCRIPTION = ".//td[7]"
    XPATH_PAGINATION_BUTTONS = (
        "//nav[@aria-label='Index of pages']//button[not(@disabled)]"
    )

    # === Regex patterns ===
    # Date format: MM/DD/YYYY
    DATE_PATTERN = re.compile(r"(\d{1,2}/\d{1,2}/\d{4})")
    # Opinion ID from Download URL
    OPINION_ID_PATTERN = re.compile(r"id=(\d+)")
    # Originating court from Supreme Court entries (e.g., "Supreme Court (Court of Chancery)")
    ORIGINATING_COURT_PATTERN = re.compile(r"Supreme Court\s*\(([^)]+)\)")

    # === Mapping ===
    MODEL_TO_DATA_TYPE: ClassVar[dict[str, str]] = {
        "DelOpinionCluster": "opinions",
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
    ) -> tuple[date | None, date | None, set[str] | None]:
        """Extract search parameters from ScraperParams.

        Returns:
            Tuple of (date_gte, date_lte, court_ids)
        """
        if self._params is None:
            return None, None, None

        try:
            model_proxy = self._params.DelOpinionCluster
        except AttributeError:
            return None, None, None

        date_gte = None
        date_lte = None
        court_ids = None

        searchable = model_proxy.get_searchable_fields()

        date_field = searchable.get("date_filed")
        if date_field and date_field.is_set():
            date_gte = date_field.gte
            date_lte = date_field.lte

        court_field = searchable.get("court_id")
        if court_field and court_field.is_set():
            court_ids = court_field.values

        return date_gte, date_lte, court_ids

    def _get_target_courts(self) -> set[str]:
        """Get the set of court IDs to scrape."""
        _, _, court_ids = self._get_search_params()
        if court_ids:
            valid_courts = court_ids & self.court_ids
            if valid_courts:
                return valid_courts
        return self.court_ids

    def _build_opinions_url(self, court_id: str | None = None) -> str:
        """Build the opinions URL with optional court filter.

        Args:
            court_id: CourtListener court ID to filter by (e.g., 'del', 'delch')

        Returns:
            URL string with query parameters
        """
        base = OPINIONS_URL
        if court_id and court_id in COURT_URL_FILTER_MAP:
            court_filter = COURT_URL_FILTER_MAP[court_id]
            # URL encode the court name (spaces become +)
            encoded = court_filter.replace(" ", "+").lower()
            return f"{base}index.aspx?ag={encoded}"
        return base

    # =========================================================================
    # Entry Point
    # =========================================================================

    def get_entry(self) -> Generator[NavigatingRequest, None, None]:
        """Yield initial request for opinions scraping.

        Yields requests for each court to be scraped based on params.
        """
        requested = self._get_requested_data_types()

        if "opinions" not in requested:
            return

        target_courts = self._get_target_courts()

        # If scraping all courts, use a single request without filter
        if target_courts == self.court_ids:
            yield NavigatingRequest(
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url=OPINIONS_URL,
                ),
                continuation=self.parse_opinions_page,
                accumulated_data={
                    "court_filter": None,
                    "page_number": 1,
                },
            )
        else:
            # Yield separate requests for each filtered court
            for court_id in sorted(target_courts):
                url = self._build_opinions_url(court_id)
                yield NavigatingRequest(
                    request=HTTPRequestParams(
                        method=HttpMethod.GET,
                        url=url,
                    ),
                    continuation=self.parse_opinions_page,
                    accumulated_data={
                        "court_filter": court_id,
                        "page_number": 1,
                    },
                )

    # =========================================================================
    # Opinions Scraping Steps
    # =========================================================================

    @step(xsd="xsds/parse_opinions_page.xsd")
    def parse_opinions_page(
        self,
        lxml_tree: CheckedHtmlElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[DelOpinionCluster], None, None]:
        """Parse the opinions table and yield opinion clusters.

        Extracts:
        - Case name (from button text)
        - Date
        - File number (docket number)
        - Court
        - Type (Civil/Criminal)
        - Judicial Officer
        - Description (opinion type)
        - Download URL (from button onclick/navigation)
        """
        date_gte, date_lte, filter_court_ids = self._get_search_params()

        # Find all opinion rows in the table
        rows = lxml_tree.checked_xpath(
            self.XPATH_OPINION_ROWS,
            "opinion table rows",
            min_count=0,  # May be empty if no opinions
        )

        for row in rows:
            # Extract button with case name and download link
            buttons = row.checked_xpath(
                self.XPATH_CELL_BUTTON,
                "case name button",
                min_count=0,
            )
            if not buttons:
                continue

            button = buttons[0]
            case_name = button.text_content().strip()
            if not case_name:
                continue

            # Try to get download URL from button attributes
            # The button triggers navigation to Download.aspx?id=X
            # We need to extract this from onclick, data-*, or href
            opinion_id = None
            download_url = None

            # Check for onclick attribute
            onclick = button.get("onclick")
            if onclick:
                id_match = self.OPINION_ID_PATTERN.search(onclick)
                if id_match:
                    opinion_id = int(id_match.group(1))

            # Check for data-id attribute
            if not opinion_id:
                data_id = button.get("data-id")
                if data_id and data_id.isdigit():
                    opinion_id = int(data_id)

            # Check for href in nested link
            if not opinion_id:
                links = button.checked_xpath(
                    ".//a[@href]",
                    "download link",
                    min_count=0,
                )
                if links:
                    href = links[0].get("href", "")
                    id_match = self.OPINION_ID_PATTERN.search(href)
                    if id_match:
                        opinion_id = int(id_match.group(1))

            # Skip if we couldn't find the opinion ID
            if not opinion_id:
                # The site uses JavaScript to populate the button behavior
                # We may need to use a different approach
                continue

            download_url = DOWNLOAD_URL_PATTERN.format(id=opinion_id)

            # Extract date
            date_cells = row.checked_xpath(
                self.XPATH_CELL_DATE,
                "date cell",
                min_count=0,
            )
            opinion_date = None
            if date_cells:
                date_text = date_cells[0].text_content().strip()
                date_match = self.DATE_PATTERN.search(date_text)
                if date_match:
                    try:
                        opinion_date = datetime.strptime(
                            date_match.group(1), "%m/%d/%Y"
                        ).date()
                    except ValueError:
                        pass

            # Apply date filter
            if date_gte and opinion_date and opinion_date < date_gte:
                continue
            if date_lte and opinion_date and opinion_date > date_lte:
                continue

            # Extract file number (docket number)
            file_number_cells = row.checked_xpath(
                self.XPATH_CELL_FILE_NUMBER,
                "file number cell",
                min_count=0,
            )
            docket_number = ""
            if file_number_cells:
                docket_number = file_number_cells[0].text_content().strip()

            # Extract court
            court_cells = row.checked_xpath(
                self.XPATH_CELL_COURT,
                "court cell",
                min_count=0,
            )
            court_name = ""
            originating_court = None
            court_id = None
            if court_cells:
                court_name = court_cells[0].text_content().strip()
                # Normalize whitespace
                court_name = " ".join(court_name.split())

                # Check for originating court in Supreme Court appeals
                orig_match = self.ORIGINATING_COURT_PATTERN.match(court_name)
                if orig_match:
                    originating_court = orig_match.group(1).strip()

                court_id = get_court_id(court_name)

            # Apply court filter if filtering by specific courts
            if (
                filter_court_ids
                and court_id
                and court_id not in filter_court_ids
            ):
                continue

            # Extract case type (Civil/Criminal)
            type_cells = row.checked_xpath(
                self.XPATH_CELL_TYPE,
                "type cell",
                min_count=0,
            )
            case_type = None
            if type_cells:
                case_type = type_cells[0].text_content().strip()

            # Extract judicial officer
            officer_cells = row.checked_xpath(
                self.XPATH_CELL_JUDICIAL_OFFICER,
                "judicial officer cell",
                min_count=0,
            )
            judicial_officer = None
            if officer_cells:
                judicial_officer = " ".join(
                    officer_cells[0].text_content().split()
                )

            # Extract description (opinion type)
            desc_cells = row.checked_xpath(
                self.XPATH_CELL_DESCRIPTION,
                "description cell",
                min_count=0,
            )
            description = None
            if desc_cells:
                description = desc_cells[0].text_content().strip()

            # Build cluster data
            cluster_data = {
                "docket_number": docket_number,
                "court_id": court_id or "del",  # Default to Supreme Court
                "date_filed": opinion_date.isoformat()
                if opinion_date
                else None,
                "case_name": case_name,
                "case_type": case_type,
                "judicial_officer": judicial_officer,
                "description": description,
                "originating_court": originating_court,
                "source_url": response.url,
                "opinion_id": opinion_id,
                "download_url": download_url,
            }

            # Yield archive request to download the PDF
            yield ArchiveRequest(
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url=download_url,
                ),
                continuation=self.handle_opinion_download,
                expected_type="pdf",
                accumulated_data=cluster_data,
            )

        # Handle pagination - check for next page button
        next_buttons = lxml_tree.checked_xpath(
            "//button[contains(text(), 'Next page') and not(@disabled)]",
            "next page button",
            min_count=0,
        )

        if next_buttons:
            # The pagination uses JavaScript, so we'd need to handle this
            # via Playwright. For now, we'll document that pagination
            # requires browser-based execution.
            # TODO: Implement pagination support with Playwright
            pass

    @step
    def handle_opinion_download(
        self,
        response: ArchiveResponse,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[DelOpinionCluster], None, None]:
        """Handle a downloaded opinion PDF and yield the final cluster."""
        # Build the opinion object
        opinion = DelOpinion(
            download_url=accumulated_data["download_url"],
            opinion_id=accumulated_data["opinion_id"],
            local_path=response.file_url,
        )

        # Parse date from ISO format
        date_filed = None
        if accumulated_data.get("date_filed"):
            date_filed = datetime.fromisoformat(
                accumulated_data["date_filed"]
            ).date()

        # Build and yield the cluster
        cluster = DelOpinionCluster(
            docket_number=accumulated_data["docket_number"],
            court_id=accumulated_data["court_id"],
            date_filed=date_filed
            or date.today(),  # Fallback to today if no date
            case_name=accumulated_data["case_name"],
            opinions=[opinion],
            case_type=accumulated_data.get("case_type"),
            judicial_officer=accumulated_data.get("judicial_officer"),
            description=accumulated_data.get("description"),
            originating_court=accumulated_data.get("originating_court"),
            source_url=accumulated_data.get("source_url"),
        )

        yield ParsedData(cluster)
