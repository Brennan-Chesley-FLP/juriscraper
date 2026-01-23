"""New Hampshire Supreme Court Scraper.

This module scrapes opinions from the New Hampshire Supreme Court.
The court website uses JavaScript to render opinion listings, so
this scraper requires the PlaywrightDriver for browser-based execution.

Entry points:
- Year opinions page: https://www.courts.nh.gov/our-courts/supreme-court/orders-and-opinions/opinions/{YEAR}

Flow:
1. get_entry -> opinion year page URL (iterates through years)
2. parse_opinion_year_page -> parses opinion listings, yields ArchiveRequests for PDFs
3. handle_opinion_download -> yields final NHOpinionCluster

Design decisions:
- The opinion page is JavaScript-rendered, requiring browser automation
- Opinions from 2024+ use neutral citation format (YYYY N.H. NN)
- Opinions before 2024 use case number citations
- Uses DateRange filter on date_filed for searching
- Scrapes all available years (2002-present) by default
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import TYPE_CHECKING, Any, ClassVar

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
    NHOpinion,
    NHOpinionCluster,
)

if TYPE_CHECKING:
    from collections.abc import Generator

    from juriscraper.scraper_driver.data_types import ScraperYield


# Base URL for opinion year pages
OPINIONS_BASE_URL = "https://www.courts.nh.gov/our-courts/supreme-court/orders-and-opinions/opinions"

# Earliest year with opinions available
EARLIEST_YEAR = 2002


class NewHampshireScraper(BaseScraper[NHOpinionCluster]):
    """Scraper for New Hampshire Supreme Court opinions.

    Scrapes opinions from the state's only appellate court (NH has no
    intermediate Court of Appeals).

    NOTE: This scraper requires the PlaywrightDriver because the opinion
    pages use JavaScript rendering.

    Usage:
        # Scrape all opinions (all years)
        scraper = NewHampshireScraper()

        # Filter opinions by date range
        params = NewHampshireScraper.params()
        params.NHOpinionCluster.date_filed.gte = date(2025, 1, 1)
        params.NHOpinionCluster.date_filed.lte = date(2025, 12, 31)
        scraper = NewHampshireScraper(params=params)

        # Look up a specific case by docket number
        params = NewHampshireScraper.params()
        params.NHOpinionCluster.docket_number.value = "2025-0056"
        scraper = NewHampshireScraper(params=params)
    """

    # === Metadata ===
    court_ids: ClassVar[set[str]] = {"nh"}
    court_url: ClassVar[str] = "https://www.courts.nh.gov/"
    data_types: ClassVar[set[str]] = {"opinions"}
    status: ClassVar[ScraperStatus] = ScraperStatus.IN_DEVELOPMENT
    version: ClassVar[str] = "2026-01-23"
    requires_auth: ClassVar[bool] = False

    # Rate limiting - be respectful to court servers
    msec_per_request_rate_limit: ClassVar[int] = 2000

    # === Regex patterns ===
    # Neutral citation pattern: YYYY N.H. NN (e.g., "2025 N.H. 54")
    NEUTRAL_CITATION_PATTERN = re.compile(r"(\d{4})\s+N\.H\.\s+(\d+)")

    # Case number pattern: YYYY-NNNN (e.g., "2025-0056")
    CASE_NUMBER_PATTERN = re.compile(r"(\d{4})-(\d{4})")

    # Date pattern: MM/DD/YYYY
    DATE_PATTERN = re.compile(r"(\d{1,2})/(\d{1,2})/(\d{4})")

    # Mapping from model name to data type
    MODEL_TO_DATA_TYPE: ClassVar[dict[str, str]] = {
        "NHOpinionCluster": "opinions",
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
            model_proxy = self._params.NHOpinionCluster
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

    def _get_years_to_scrape(self) -> list[int]:
        """Determine which years to scrape based on date filters.

        Returns:
            List of years to scrape in descending order (most recent first)
        """
        current_year = datetime.now().year
        date_gte, date_lte, _ = self._get_search_params()

        start_year = EARLIEST_YEAR
        end_year = current_year

        if date_gte:
            start_year = max(start_year, date_gte.year)
        if date_lte:
            end_year = min(end_year, date_lte.year)

        # Return years in descending order (most recent first)
        return list(range(end_year, start_year - 1, -1))

    def _parse_date(self, date_str: str) -> date | None:
        """Parse a date string in MM/DD/YYYY format.

        Args:
            date_str: Date string like "12/23/2025"

        Returns:
            Parsed date or None
        """
        match = self.DATE_PATTERN.match(date_str.strip())
        if match:
            month = int(match.group(1))
            day = int(match.group(2))
            year = int(match.group(3))
            try:
                return date(year, month, day)
            except ValueError:
                return None
        return None

    def _extract_case_number(self, text: str) -> str | None:
        """Extract case number from text.

        Args:
            text: Text that may contain a case number like "Issued in case no. 2025-0056"

        Returns:
            Case number string or None
        """
        match = self.CASE_NUMBER_PATTERN.search(text)
        if match:
            return match.group(0)
        return None

    def _extract_neutral_citation(
        self, text: str
    ) -> tuple[str | None, int | None]:
        """Extract neutral citation from text.

        Args:
            text: Text that may contain a citation like "2025 N.H. 54"

        Returns:
            Tuple of (citation_string, opinion_number)
        """
        match = self.NEUTRAL_CITATION_PATTERN.search(text)
        if match:
            citation_string = match.group(0)
            opinion_number = int(match.group(2))
            return citation_string, opinion_number
        return None, None

    # =========================================================================
    # Entry Point
    # =========================================================================

    def get_entry(self) -> Generator[NavigatingRequest, None, None]:
        """Yield initial request(s) to opinion year pages."""
        requested = self._get_requested_data_types()

        if "opinions" not in requested:
            return

        years_to_scrape = self._get_years_to_scrape()

        for year in years_to_scrape:
            yield NavigatingRequest(
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url=f"{OPINIONS_BASE_URL}/{year}",
                ),
                continuation=self.parse_opinion_year_page,
                accumulated_data={"year": year},
            )

    # =========================================================================
    # Opinion Year Page Parsing
    # =========================================================================

    @step(xsd="xsds/parse_opinion_year_page.xsd")
    def parse_opinion_year_page(
        self,
        lxml_tree: CheckedHtmlElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[NHOpinionCluster], None, None]:
        """Parse an opinion year page and yield requests for each opinion.

        The page uses a JavaScript-rendered grid with rows for each opinion.
        Each row contains:
        - Citation/title (e.g., "2025 N.H. 54, Peregrine Interests LLC v. Todd")
        - Case number (e.g., "Issued in case no. 2025-0056")
        - Document format (PDF)
        - Date (e.g., "12/23/2025")
        - Optional related documents
        """
        date_gte, date_lte, target_docket = self._get_search_params()
        year = accumulated_data.get("year", datetime.now().year)

        # Find all opinion rows in the grid
        # The structure is: grid > rowgroup > row > gridcell > generic with content
        rows = lxml_tree.checked_xpath(
            "//div[contains(@class, 'grid') or @role='grid']//div[@role='row']",
            "opinion rows",
            min_count=0,
        )

        if not rows:
            # Try alternative structure - the rows might be direct children
            rows = lxml_tree.checked_xpath(
                "//*[@role='row']",
                "opinion rows (alternative)",
                min_count=0,
            )

        for row in rows:
            # Skip header rows if any
            if row.checked_xpath(
                ".//th | .//*[@role='columnheader']",
                "header check",
                min_count=0,
            ):
                continue

            # Extract the main link (PDF URL and title)
            links = row.checked_xpath(
                ".//a[contains(@href, '.pdf')]",
                "PDF links",
                min_count=0,
            )

            if not links:
                continue

            link = links[0]

            # Get PDF URL
            href_list = link.checked_xpath(
                "@href",
                "PDF href",
                min_count=1,
                max_count=1,
                type=str,
            )
            pdf_path = href_list[0]

            # Make absolute URL
            if pdf_path.startswith("/"):
                pdf_url = f"https://www.courts.nh.gov{pdf_path}"
            else:
                pdf_url = pdf_path

            # Get the link text (contains citation and case name)
            link_text_parts = link.checked_xpath(
                ".//text()",
                "link text",
                min_count=0,
                type=str,
            )
            link_text = " ".join(
                part.strip() for part in link_text_parts
            ).strip()

            # Parse title to extract citation and case name
            # Format: "2025 N.H. 54, Peregrine Interests LLC v. Todd"
            citation_string, opinion_number = self._extract_neutral_citation(
                link_text
            )

            # Extract case name (everything after citation)
            case_name = link_text
            if citation_string and ", " in link_text:
                parts = link_text.split(", ", 1)
                if len(parts) > 1:
                    case_name = parts[1].strip()

            # Extract case number from surrounding text
            row_text_parts = row.checked_xpath(
                ".//text()",
                "row text",
                min_count=0,
                type=str,
            )
            row_text = " ".join(part.strip() for part in row_text_parts)
            docket_number = self._extract_case_number(row_text)

            # Filter by specific docket if requested
            if target_docket and docket_number != target_docket:
                continue

            # Extract date
            date_filed = None
            date_match = self.DATE_PATTERN.search(row_text)
            if date_match:
                date_str = date_match.group(0)
                date_filed = self._parse_date(date_str)

            if date_filed is None:
                # Use a default date based on year if parsing fails
                date_filed = date(year, 1, 1)

            # Filter by date range if specified
            if date_gte and date_filed < date_gte:
                continue
            if date_lte and date_filed > date_lte:
                continue

            # Extract related document URLs
            related_doc_urls = []
            related_links = row.checked_xpath(
                ".//a[contains(@href, '.pdf') and not(contains(@href, normalize-space(@href)))]",
                "related PDF links",
                min_count=0,
            )
            for rel_link in related_links[1:] if len(links) > 1 else []:
                rel_href_list = rel_link.checked_xpath(
                    "@href",
                    "related href",
                    min_count=0,
                    type=str,
                )
                if rel_href_list:
                    rel_path = rel_href_list[0]
                    if rel_path.startswith("/"):
                        related_doc_urls.append(
                            f"https://www.courts.nh.gov{rel_path}"
                        )
                    else:
                        related_doc_urls.append(rel_path)

            # Build accumulated data for download handler
            cluster_data: dict[str, Any] = {
                "docket_number": docket_number or f"unknown-{year}",
                "court_id": "nh",
                "date_filed": date_filed.isoformat(),
                "case_name": case_name,
                "citation_string": citation_string,
                "opinion_number": opinion_number,
                "source_url": response.url,
                "related_document_urls": related_doc_urls,
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
    ) -> Generator[ScraperYield[NHOpinionCluster], None, None]:
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
    ) -> Generator[ScraperYield[NHOpinionCluster], None, None]:
        """Build and yield the final OpinionCluster with all PDFs downloaded."""
        opinions = []
        for i, op_data in enumerate(accumulated_data["opinions_data"]):
            local_path = accumulated_data["downloaded_paths"].get(i)
            opinions.append(
                NHOpinion(
                    download_url=op_data["download_url"],
                    local_path=local_path,
                )
            )

        date_filed = datetime.fromisoformat(
            accumulated_data["date_filed"]
        ).date()

        cluster = NHOpinionCluster(
            docket_number=accumulated_data["docket_number"],
            court_id=accumulated_data["court_id"],
            date_filed=date_filed,
            case_name=accumulated_data["case_name"],
            citation_string=accumulated_data.get("citation_string"),
            opinion_number=accumulated_data.get("opinion_number"),
            opinions=opinions,
            related_document_urls=accumulated_data.get(
                "related_document_urls", []
            ),
            source_url=accumulated_data["source_url"],
            precedential_status="Unknown",
        )

        yield ParsedData(cluster)
