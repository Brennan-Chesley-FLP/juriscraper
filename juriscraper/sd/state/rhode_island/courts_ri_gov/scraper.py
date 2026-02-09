"""Rhode Island Supreme Court Scraper.

This module scrapes published opinions from the Rhode Island Supreme Court.

Entry point:
- Published opinions: https://www.courts.ri.gov/Courts/SupremeCourt/Pages/published-opinions.aspx

Flow:
1. get_entry -> published opinions page (if "opinions" requested)
2. parse_opinions_page -> parses search results, yields ArchiveRequests for PDFs
3. handle_opinion_download -> yields final RhodeIslandOpinionCluster

Design decisions:
- Uses the published opinions SharePoint search page
- Each result contains: case name (with PDF link), case number, date, and summary
- PDF URLs follow predictable pattern: /Opinions/Supreme-{YY}-{N}.pdf
- Uses DateRange filter on date_filed for searching
- Uses year filter in URL hash to filter results by year
- Rhode Island has no intermediate appellate court - only the Supreme Court

Technical notes:
- The site uses SharePoint search with URL hash fragments for filtering
- Results are loaded dynamically via JavaScript
- The scraper requires JavaScript execution to get filtered results
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
    RhodeIslandOpinion,
    RhodeIslandOpinionCluster,
)

if TYPE_CHECKING:
    from collections.abc import Generator

    from juriscraper.scraper_driver.data_types import ScraperYield


# Base URLs
BASE_URL = "https://www.courts.ri.gov"
PUBLISHED_OPINIONS_URL = "https://www.courts.ri.gov/Courts/SupremeCourt/Pages/published-opinions.aspx"


class RhodeIslandScraper(BaseScraper[RhodeIslandOpinionCluster]):
    """Scraper for Rhode Island Supreme Court published opinions.

    Scrapes published opinions from the Rhode Island Supreme Court.

    Usage:
        # Scrape all opinions
        scraper = RhodeIslandScraper()

        # Filter opinions by date range
        params = RhodeIslandScraper.params()
        params.RhodeIslandOpinionCluster.date_filed.gte = date(2026, 1, 1)
        params.RhodeIslandOpinionCluster.date_filed.lte = date(2026, 1, 31)
        scraper = RhodeIslandScraper(params=params)

        # Scrape specific opinion by docket number
        params = RhodeIslandScraper.params()
        params.RhodeIslandOpinionCluster.docket_number.value = "2025-0021-Appeal."
        scraper = RhodeIslandScraper(params=params)
    """

    # === Metadata ===
    court_ids: ClassVar[set[str]] = {"ri"}
    court_url: ClassVar[str] = "https://www.courts.ri.gov/Courts/SupremeCourt/"
    data_types: ClassVar[set[str]] = {"opinions"}
    status: ClassVar[ScraperStatus] = ScraperStatus.IN_DEVELOPMENT
    version: ClassVar[str] = "2026-01-23"
    requires_auth: ClassVar[bool] = False

    # Rate limiting - be respectful to court servers
    msec_per_request_rate_limit: ClassVar[int] = 1000

    # === Regex patterns ===
    # Date parsing pattern: "Thursday, January 22, 2026"
    DATE_PATTERN = re.compile(
        r"(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),\s+"
        r"(\w+)\s+(\d{1,2}),\s+(\d{4})"
    )

    # Case number pattern: "Number: 2025-0021-Appeal."
    CASE_NUMBER_PATTERN = re.compile(r"Number:\s*(.+)")

    # PDF URL pattern to extract year
    PDF_YEAR_PATTERN = re.compile(r"/Opinions/Supreme-(\d{2,4})-\d+\.pdf")

    # Mapping from model name to data type
    MODEL_TO_DATA_TYPE: ClassVar[dict[str, str]] = {
        "RhodeIslandOpinionCluster": "opinions",
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
            Tuple of (date_gte, date_lte, docket_number)
        """
        if self._params is None:
            return None, None, None

        try:
            model_proxy = self._params.RhodeIslandOpinionCluster
        except AttributeError:
            return None, None, None

        date_gte = None
        date_lte = None
        docket_number = None

        searchable = model_proxy.get_searchable_fields()

        date_field = searchable.get("date_filed")
        if date_field and date_field.is_set():
            date_gte = date_field.gte
            date_lte = date_field.lte

        docket_field = searchable.get("docket_number")
        if docket_field and docket_field.is_set():
            docket_number = docket_field.value

        return date_gte, date_lte, docket_number

    def _parse_date(self, date_str: str) -> date | None:
        """Parse date from search result.

        Args:
            date_str: Date like 'Date: Thursday, January 22, 2026'

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

    def _extract_case_number(self, text: str) -> str | None:
        """Extract case number from text.

        Args:
            text: Text like 'Number: 2025-0021-Appeal.'

        Returns:
            Case number or None
        """
        match = self.CASE_NUMBER_PATTERN.search(text)
        if match:
            return match.group(1).strip()
        return None

    def _extract_year_from_pdf_url(self, url: str) -> int | None:
        """Extract year from PDF URL.

        Args:
            url: PDF URL like '/Opinions/Supreme-25-21.pdf'

        Returns:
            Year as integer or None
        """
        match = self.PDF_YEAR_PATTERN.search(url)
        if match:
            year_str = match.group(1)
            if len(year_str) == 2:
                # Two-digit year - assume 20XX for now
                year = 2000 + int(year_str)
            else:
                year = int(year_str)
            return year
        return None

    # =========================================================================
    # Entry Point
    # =========================================================================

    @entry(RhodeIslandOpinionCluster)
    def get_entry(self) -> Generator[NavigatingRequest, None, None]:
        """Yield initial request to published opinions page."""
        requested = self._get_requested_data_types()

        if "opinions" in requested:
            yield NavigatingRequest(
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url=PUBLISHED_OPINIONS_URL,
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
    ) -> Generator[ScraperYield[RhodeIslandOpinionCluster], None, None]:
        """Parse the published opinions search page and yield requests.

        The page uses SharePoint search. Results are in divs with:
        - Link to PDF with case name
        - Case number line
        - Date line
        - Summary text
        """
        date_gte, date_lte, target_docket = self._get_search_params()

        # Find all result items - they are divs containing links to PDFs
        # The structure is: div > a[href*=".pdf"] + div (with metadata)
        result_containers = lxml_tree.checked_xpath(
            "//a[contains(@href, '/Opinions/') and contains(@href, '.pdf')]/..",
            "opinion result containers",
            min_count=0,
        )

        for container in result_containers:
            # Get the PDF link and case name
            pdf_links = container.checked_xpath(
                ".//a[contains(@href, '/Opinions/') and contains(@href, '.pdf')]",
                "PDF link",
                min_count=1,
                max_count=1,
            )
            pdf_link = pdf_links[0]

            # Get case name from link text
            case_name_texts = pdf_link.checked_xpath(
                ".//text()",
                "case name text",
                min_count=1,
                type=str,
            )
            case_name = "".join(case_name_texts).strip()

            # Get PDF URL
            pdf_hrefs = pdf_link.checked_xpath(
                "@href",
                "PDF URL",
                min_count=1,
                max_count=1,
                type=str,
            )
            pdf_url = urljoin(response.url, pdf_hrefs[0])

            # Get metadata div (contains number, date, summary)
            metadata_divs = container.checked_xpath(
                ".//div[contains(., 'Number:')]",
                "metadata div",
                min_count=0,
            )

            case_number = None
            opinion_date = None
            summary_text = None

            if metadata_divs:
                metadata_div = metadata_divs[0]

                # Get all text from metadata div
                all_texts = metadata_div.checked_xpath(
                    ".//text()",
                    "metadata texts",
                    min_count=0,
                    type=str,
                )

                for text in all_texts:
                    text = text.strip()
                    if not text:
                        continue

                    # Check for case number
                    if text.startswith("Number:"):
                        case_number = self._extract_case_number(text)

                    # Check for date
                    elif text.startswith("Date:"):
                        opinion_date = self._parse_date(text)

                    # Otherwise it's likely summary text
                    elif len(text) > 50:  # Summary is usually longer
                        if summary_text is None:
                            summary_text = text
                        else:
                            summary_text += " " + text

            # Skip if we couldn't find essential fields
            if not case_number:
                continue

            # Filter by specific docket number if specified
            if target_docket and case_number != target_docket:
                continue

            # If no date found, try to extract year from PDF URL
            year = None
            if opinion_date:
                year = opinion_date.year
            else:
                year = self._extract_year_from_pdf_url(pdf_url)
                # Can't proceed without a date
                if year is None:
                    continue
                # Use January 1 as placeholder date when only year is known
                opinion_date = date(year, 1, 1)

            # Filter by date range if specified
            if date_gte and opinion_date < date_gte:
                continue
            if date_lte and opinion_date > date_lte:
                continue

            # Build accumulated data for download handler
            cluster_data = {
                "docket_number": case_number,
                "court_id": "ri",
                "date_filed": opinion_date.isoformat(),
                "case_name": case_name,
                "source_url": response.url,
                "summary": summary_text,
                "year": year,
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

        # Note: SharePoint search uses JavaScript pagination via URL hash
        # For complete scraping, we would need to iterate through years
        # or use the SharePoint REST API. For now, we get the first page.

    # =========================================================================
    # Download Handler
    # =========================================================================

    @step
    def handle_opinion_download(
        self,
        response: ArchiveResponse,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[RhodeIslandOpinionCluster], None, None]:
        """Handle a downloaded opinion PDF."""
        date_filed = datetime.fromisoformat(
            accumulated_data["date_filed"]
        ).date()

        opinion = RhodeIslandOpinion(
            download_url=accumulated_data["pdf_url"],
            local_path=response.file_url,
        )

        cluster = RhodeIslandOpinionCluster(
            docket_number=accumulated_data["docket_number"],
            court_id=accumulated_data["court_id"],
            date_filed=date_filed,
            case_name=accumulated_data["case_name"],
            opinions=[opinion],
            source_url=accumulated_data["source_url"],
            summary=accumulated_data.get("summary"),
            year=accumulated_data["year"],
            precedential_status="Published",
        )

        yield ParsedData(cluster)
