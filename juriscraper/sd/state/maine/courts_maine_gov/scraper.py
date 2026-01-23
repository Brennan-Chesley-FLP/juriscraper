"""Maine Supreme Judicial Court Scraper.

This module scrapes published opinions from the Maine Supreme Judicial Court
(also known as the Law Court when sitting in its appellate capacity).

Entry points:
- Current year: https://www.courts.maine.gov/courts/sjc/opinions.html
- Archive years: https://www.courts.maine.gov/courts/sjc/lawcourt/{year}/index.html

Flow:
1. get_entry -> main opinions page (if "opinions" requested)
2. parse_opinions_page -> parses table, yields ArchiveRequests for PDFs
3. handle_opinion_download -> yields final MaineOpinionCluster

Design decisions:
- Starts from the main opinions page which contains current year + archive links
- Each year page has a table with Opinion #, Case, and Date columns
- PDF URLs follow predictable pattern: lawcourt/{year}/{yy}me{nnn}.pdf
- Uses DateRange filter on date_filed for searching
- Maine has no intermediate appellate court - only the Supreme Judicial Court
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import TYPE_CHECKING, ClassVar
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
    MaineOpinion,
    MaineOpinionCluster,
)

if TYPE_CHECKING:
    from collections.abc import Generator

    from juriscraper.scraper_driver.data_types import ScraperYield


# Base URLs
BASE_URL = "https://www.courts.maine.gov"
OPINIONS_URL = "https://www.courts.maine.gov/courts/sjc/opinions.html"


class MaineScraper(BaseScraper[MaineOpinionCluster]):
    """Scraper for Maine Supreme Judicial Court published opinions.

    Scrapes published opinions from the Maine Supreme Judicial Court
    (also known as the Law Court).

    Usage:
        # Scrape all opinions
        scraper = MaineScraper()

        # Filter opinions by date range
        params = MaineScraper.params()
        params.MaineOpinionCluster.date_filed.gte = date(2026, 1, 1)
        params.MaineOpinionCluster.date_filed.lte = date(2026, 1, 31)
        scraper = MaineScraper(params=params)

        # Scrape specific opinion by citation
        params = MaineScraper.params()
        params.MaineOpinionCluster.docket_id.value = "2026 ME 4"
        scraper = MaineScraper(params=params)
    """

    # === Metadata ===
    court_ids: ClassVar[set[str]] = {"me"}
    court_url: ClassVar[str] = "https://www.courts.maine.gov/courts/sjc/"
    data_types: ClassVar[set[str]] = {"opinions"}
    status: ClassVar[ScraperStatus] = ScraperStatus.IN_DEVELOPMENT
    version: ClassVar[str] = "2026-01-23"
    requires_auth: ClassVar[bool] = False

    # Rate limiting - be respectful to court servers
    msec_per_request_rate_limit: ClassVar[int] = 1000

    # === Regex patterns ===
    # Opinion citation pattern: YYYY ME N (e.g., "2026 ME 4")
    CITATION_PATTERN = re.compile(r"(\d{4})\s+ME\s+(\d+)")

    # Date parsing patterns
    # Full month name: "January 22, 2026"
    DATE_PATTERN = re.compile(r"(\w+)\s+(\d{1,2}),\s+(\d{4})")

    # Archive year link pattern
    ARCHIVE_YEAR_PATTERN = re.compile(r"lawcourt/(\d{4})/index\.html")

    # Mapping from model name to data type
    MODEL_TO_DATA_TYPE: ClassVar[dict[str, str]] = {
        "MaineOpinionCluster": "opinions",
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
    ) -> tuple[date | None, date | None, str | None]:
        """Extract search parameters from ScraperParams.

        Returns:
            Tuple of (date_gte, date_lte, docket_id)
        """
        if self._params is None:
            return None, None, None

        try:
            model_proxy = self._params.MaineOpinionCluster
        except AttributeError:
            return None, None, None

        date_gte = None
        date_lte = None
        docket_id = None

        searchable = model_proxy.get_searchable_fields()

        date_field = searchable.get("date_filed")
        if date_field and date_field.is_set():
            date_gte = date_field.gte
            date_lte = date_field.lte

        docket_field = searchable.get("docket_id")
        if docket_field and docket_field.is_set():
            docket_id = docket_field.value

        return date_gte, date_lte, docket_id

    def _parse_citation(self, citation_str: str) -> tuple[int, int] | None:
        """Parse opinion citation to extract year and number.

        Args:
            citation_str: Citation like '2026 ME 4'

        Returns:
            Tuple of (year, number) or None if not parseable
        """
        match = self.CITATION_PATTERN.search(citation_str)
        if match:
            return int(match.group(1)), int(match.group(2))
        return None

    def _parse_date(self, date_str: str) -> date | None:
        """Parse date from table cell.

        Args:
            date_str: Date like 'January 22, 2026'

        Returns:
            Parsed date or None
        """
        match = self.DATE_PATTERN.search(date_str)
        if match:
            month_name = match.group(1)
            day = int(match.group(2))
            year = int(match.group(3))

            # Convert month name to number
            month_map = {
                "January": 1,
                "February": 2,
                "March": 3,
                "April": 4,
                "May": 5,
                "June": 6,
                "July": 7,
                "August": 8,
                "September": 9,
                "October": 10,
                "November": 11,
                "December": 12,
            }
            month = month_map.get(month_name)
            if month:
                return date(year, month, day)
        return None

    # =========================================================================
    # Entry Point
    # =========================================================================

    def get_entry(self) -> Generator[NavigatingRequest, None, None]:
        """Yield initial request to opinions page."""
        requested = self._get_requested_data_types()

        if "opinions" in requested:
            yield NavigatingRequest(
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url=OPINIONS_URL,
                ),
                continuation=self.parse_opinions_page,
            )

    # =========================================================================
    # Opinions Page Parsing
    # =========================================================================

    @step(xsd="xsds/parse_opinions_page.xsd")
    def parse_opinions_page(
        self,
        lxml_tree: CheckedHtmlElement,
        response: Response,
    ) -> Generator[ScraperYield[MaineOpinionCluster], None, None]:
        """Parse the opinions page (current year) and yield requests."""
        date_gte, date_lte, target_docket = self._get_search_params()

        # Parse table rows from the current year opinions
        yield from self._parse_opinion_table(
            lxml_tree, response, date_gte, date_lte, target_docket
        )

        # Also follow archive year links if date filter allows
        archive_links = lxml_tree.checked_xpath(
            "//a[contains(@href, 'lawcourt/') and contains(@href, '/index.html')]/@href",
            "archive year links",
            min_count=0,
            type=str,
        )

        for link in archive_links:
            # Extract year from link
            year_match = self.ARCHIVE_YEAR_PATTERN.search(link)
            if year_match:
                archive_year = int(year_match.group(1))

                # Skip years outside our date range if specified
                if date_gte and archive_year < date_gte.year:
                    continue
                if date_lte and archive_year > date_lte.year:
                    continue

                archive_url = urljoin(response.url, link)
                yield NavigatingRequest(
                    request=HTTPRequestParams(
                        method=HttpMethod.GET,
                        url=archive_url,
                    ),
                    continuation=self.parse_archive_page,
                )

    @step(xsd="xsds/parse_archive_page.xsd")
    def parse_archive_page(
        self,
        lxml_tree: CheckedHtmlElement,
        response: Response,
    ) -> Generator[ScraperYield[MaineOpinionCluster], None, None]:
        """Parse an archive year page and yield requests."""
        date_gte, date_lte, target_docket = self._get_search_params()

        yield from self._parse_opinion_table(
            lxml_tree, response, date_gte, date_lte, target_docket
        )

    def _parse_opinion_table(
        self,
        lxml_tree: CheckedHtmlElement,
        response: Response,
        date_gte: date | None,
        date_lte: date | None,
        target_docket: str | None,
    ) -> Generator[ScraperYield[MaineOpinionCluster], None, None]:
        """Parse the opinion table and yield archive requests for PDFs.

        The table has columns: Opinion #, Case, Date
        The Case column contains a link to the PDF with the case name as text.
        """
        # Validate table headers
        headers = lxml_tree.checked_xpath(
            "//table//th/text()",
            "opinion table headers",
            min_count=3,
            max_count=3,
            type=str,
        )

        expected_headers = ["Opinion #", "Case", "Date"]
        for i, expected in enumerate(expected_headers):
            actual = headers[i].strip()
            if expected.lower() != actual.lower():
                raise ValueError(
                    f"Unexpected column header: expected '{expected}', got '{actual}'"
                )

        # Get all table body rows
        rows = lxml_tree.checked_xpath(
            "//table/tbody/tr",
            "opinion table rows",
            min_count=0,
        )

        for row in rows:
            # Get cells
            cells = row.checked_xpath(
                "td",
                "row cells",
                min_count=3,
                max_count=3,
            )

            # Extract opinion citation from first cell
            citation_texts = cells[0].checked_xpath(
                ".//text()",
                "citation text",
                min_count=1,
                type=str,
            )
            citation = "".join(citation_texts).strip()

            parsed_citation = self._parse_citation(citation)
            if parsed_citation is None:
                continue
            opinion_year, opinion_number = parsed_citation

            # Filter by specific docket/citation if specified
            if target_docket and citation != target_docket:
                continue

            # Extract case name and PDF URL from second cell
            case_links = cells[1].checked_xpath(
                ".//a",
                "case link",
                min_count=1,
                max_count=1,
            )
            case_link = case_links[0]

            case_name_texts = case_link.checked_xpath(
                ".//text()",
                "case name text",
                min_count=1,
                type=str,
            )
            case_name = "".join(case_name_texts).strip()

            pdf_hrefs = case_link.checked_xpath(
                "@href",
                "PDF URL",
                min_count=1,
                max_count=1,
                type=str,
            )
            pdf_url = urljoin(response.url, pdf_hrefs[0])

            # Extract date from third cell
            date_texts = cells[2].checked_xpath(
                ".//text()",
                "date text",
                min_count=1,
                type=str,
            )
            date_str = "".join(date_texts).strip()
            opinion_date = self._parse_date(date_str)

            if opinion_date is None:
                continue

            # Filter by date range if specified
            if date_gte and opinion_date < date_gte:
                continue
            if date_lte and opinion_date > date_lte:
                continue

            # Build accumulated data for download handler
            cluster_data = {
                "docket_id": citation,
                "court_id": "me",
                "date_filed": opinion_date.isoformat(),
                "case_name": case_name,
                "source_url": response.url,
                "opinion_number": opinion_number,
                "year": opinion_year,
                "pdf_url": pdf_url,
            }

            # Yield ArchiveRequest for the PDF
            yield ArchiveRequest(
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url=pdf_url,
                ),
                continuation=self.handle_opinion_download,
                expected_type="pdf",
                accumulated_data=cluster_data,
            )

    # =========================================================================
    # Download Handler
    # =========================================================================

    @step
    def handle_opinion_download(
        self,
        response: ArchiveResponse,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[MaineOpinionCluster], None, None]:
        """Handle a downloaded opinion PDF."""
        date_filed = datetime.fromisoformat(
            accumulated_data["date_filed"]
        ).date()

        opinion = MaineOpinion(
            download_url=accumulated_data["pdf_url"],
            local_path=response.file_url,
        )

        cluster = MaineOpinionCluster(
            docket_id=accumulated_data["docket_id"],
            court_id=accumulated_data["court_id"],
            date_filed=date_filed,
            case_name=accumulated_data["case_name"],
            opinions=[opinion],
            source_url=accumulated_data["source_url"],
            opinion_number=accumulated_data["opinion_number"],
            year=accumulated_data["year"],
            precedential_status="Published",
        )

        yield ParsedData(cluster)
