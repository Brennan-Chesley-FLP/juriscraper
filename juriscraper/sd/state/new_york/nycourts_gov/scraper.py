"""New York Court of Appeals Scraper.

This module scrapes opinions from the New York Court of Appeals,
the highest court in New York State.

Entry point:
- Main decisions page: https://www.nycourts.gov/ctapps/decisions.htm
- Monthly pages: https://www.nycourts.gov/ctapps/Decisions/{YYYY}/{Mon}{YY}/{Month}{YY}.html

Flow:
1. get_entry -> Main decisions page (index of all available months)
2. parse_decisions_index -> Yields requests for each month's page
3. parse_month_page -> Parses opinion rows, yields ArchiveRequests for PDFs
4. handle_opinion_download -> Yields final NYOpinionCluster

Design decisions:
- Scrapes from monthly decision pages which are simple HTML tables
- Each decision day section has date header, Decision List PDF, then individual opinions
- Opinion rows have: Opinion number | PDF link | Case name
- Uses DateRange filter on date_filed for searching
- Date filtering happens at the month level (only fetch relevant months)
"""

from __future__ import annotations

import re
from calendar import month_name
from datetime import date
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
    NYOpinion,
    NYOpinionCluster,
    normalize_opinion_type,
)

if TYPE_CHECKING:
    from collections.abc import Generator

    from juriscraper.scraper_driver.data_types import ScraperYield


# Base URLs
BASE_URL = "https://www.nycourts.gov/ctapps/"
DECISIONS_INDEX_URL = "https://www.nycourts.gov/ctapps/decisions.htm"

# Month name to abbreviation mapping
MONTH_ABBREVS = {
    "January": "Jan",
    "February": "Feb",
    "March": "Mar",
    "April": "Apr",
    "May": "May",
    "June": "Jun",
    "July": "Jul",
    "August": "Aug",
    "September": "Sep",
    "October": "Oct",
    "November": "Nov",
    "December": "Dec",
}


class NYCourtOfAppealsScraper(BaseScraper[NYOpinionCluster]):
    """Scraper for New York Court of Appeals opinions.

    Scrapes opinions from the highest court in New York State.

    Usage:
        # Scrape all available opinions
        scraper = NYCourtOfAppealsScraper()

        # Filter by date range
        params = NYCourtOfAppealsScraper.params()
        params.NYOpinionCluster.date_filed.gte = date(2025, 12, 1)
        params.NYOpinionCluster.date_filed.lte = date(2025, 12, 31)
        scraper = NYCourtOfAppealsScraper(params=params)

        # Look up specific opinion by number
        params = NYCourtOfAppealsScraper.params()
        params.NYOpinionCluster.docket_id.value = "No. 112"
        scraper = NYCourtOfAppealsScraper(params=params)
    """

    # === Metadata ===
    court_ids: ClassVar[set[str]] = {"ny"}
    court_url: ClassVar[str] = "https://www.nycourts.gov/ctapps/"
    data_types: ClassVar[set[str]] = {"opinions"}
    status: ClassVar[ScraperStatus] = ScraperStatus.IN_DEVELOPMENT
    version: ClassVar[str] = "2026-01-23"
    requires_auth: ClassVar[bool] = False

    # Rate limiting - be respectful to court servers
    msec_per_request_rate_limit: ClassVar[int] = 1000

    # === Regex patterns ===
    # Date pattern in month pages (e.g., "December 18, 2025")
    DATE_PATTERN = re.compile(r"(\w+)\s+(\d{1,2}),\s+(\d{4})")

    # Opinion number pattern (e.g., "No. 112", "No .115", "No. 105-110", "No. 128 SSM 3")
    OPINION_NUMBER_PATTERN = re.compile(
        r"No\.?\s*(\d+(?:-\d+)?(?:\s+SSM\s+\d+)?)",
        re.IGNORECASE,
    )

    # Month URL pattern (e.g., "Decisions/2025/Dec25/December25.html")
    MONTH_URL_PATTERN = re.compile(
        r"Decisions/(\d{4})/(\w+)(\d{2})/(\w+)\d{2}\.html"
    )

    # Mapping from model name to data type
    MODEL_TO_DATA_TYPE: ClassVar[dict[str, str]] = {
        "NYOpinionCluster": "opinions",
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
            model_proxy = self._params.NYOpinionCluster
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

    def _month_in_range(
        self,
        year: int,
        month: int,
        date_gte: date | None,
        date_lte: date | None,
    ) -> bool:
        """Check if a month falls within the date range.

        Args:
            year: Year (e.g., 2025)
            month: Month number (1-12)
            date_gte: Minimum date (inclusive)
            date_lte: Maximum date (inclusive)

        Returns:
            True if the month overlaps with the date range
        """
        import calendar

        # Get first and last day of the month
        _, last_day = calendar.monthrange(year, month)
        month_start = date(year, month, 1)
        month_end = date(year, month, last_day)

        # Check overlap
        if date_gte and month_end < date_gte:
            return False
        if date_lte and month_start > date_lte:
            return False

        return True

    def _parse_date(self, date_text: str) -> date | None:
        """Parse a date string like 'December 18, 2025'.

        Args:
            date_text: Date string from the page

        Returns:
            Parsed date or None
        """
        match = self.DATE_PATTERN.match(date_text.strip())
        if not match:
            return None

        month_name_str = match.group(1)
        day = int(match.group(2))
        year = int(match.group(3))

        # Convert month name to number
        month_names_lower = {
            name.lower(): i for i, name in enumerate(month_name) if name
        }
        month = month_names_lower.get(month_name_str.lower())
        if month is None:
            return None

        try:
            return date(year, month, day)
        except ValueError:
            return None

    def _extract_opinion_number(self, text: str) -> str | None:
        """Extract opinion number from cell text.

        Args:
            text: Cell text like 'No. 112' or 'No. 128 SSM 3'

        Returns:
            Normalized opinion number or None
        """
        match = self.OPINION_NUMBER_PATTERN.match(text.strip())
        if match:
            return f"No. {match.group(1)}"
        return None

    # =========================================================================
    # Entry Point
    # =========================================================================

    def get_entry(self) -> Generator[NavigatingRequest, None, None]:
        """Yield initial request to decisions index page."""
        requested = self._get_requested_data_types()

        if "opinions" in requested:
            yield NavigatingRequest(
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url=DECISIONS_INDEX_URL,
                ),
                continuation=self.parse_decisions_index,
            )

    # =========================================================================
    # Index Page Parsing
    # =========================================================================

    @step(xsd="xsds/parse_decisions_index.xsd")
    def parse_decisions_index(
        self,
        lxml_tree: CheckedHtmlElement,
        response: Response,
    ) -> Generator[ScraperYield[NYOpinionCluster], None, None]:
        """Parse the main decisions index page and yield requests for month pages.

        The index page has a table with years and months linking to decision pages.
        """
        date_gte, date_lte, _ = self._get_search_params()

        # Find all month links in the table
        # Links are in format: Decisions/2025/Dec25/December25.html
        month_links = lxml_tree.checked_xpath(
            "//a[contains(@href, 'Decisions/')]/@href",
            "month links",
            min_count=0,
            type=str,
        )

        for href in month_links:
            # Parse the URL to get year and month
            match = self.MONTH_URL_PATTERN.search(href)
            if not match:
                continue

            year = int(match.group(1))
            month_abbrev = match.group(2)
            month_name_str = match.group(4)

            # Get month number from name
            month_names = {
                name.lower(): i for i, name in enumerate(month_name) if name
            }
            month = month_names.get(month_name_str.lower())
            if month is None:
                continue

            # Check if month is in range
            if not self._month_in_range(year, month, date_gte, date_lte):
                continue

            # Build full URL
            full_url = urljoin(response.url, href)

            yield NavigatingRequest(
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url=full_url,
                ),
                continuation=self.parse_month_page,
                accumulated_data={
                    "year": year,
                    "month": month,
                    "source_url": full_url,
                },
            )

    # =========================================================================
    # Month Page Parsing
    # =========================================================================

    @step(xsd="xsds/parse_month_page.xsd")
    def parse_month_page(
        self,
        lxml_tree: CheckedHtmlElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[NYOpinionCluster], None, None]:
        """Parse a monthly decisions page and yield requests for opinion PDFs.

        Structure of the page:
        - Table with rows
        - Date rows: first cell has <strong> with date like "December 18, 2025"
        - Decision List rows: "Decision List" | PDF link | "Entries for Cases and Motions"
        - Opinion rows: "No. NNN" | PDF link | "Case Name"
        - Empty separator rows between dates
        """
        date_gte, date_lte, target_docket = self._get_search_params()
        source_url = accumulated_data.get("source_url", response.url)

        # Get all table rows
        rows = lxml_tree.checked_xpath(
            "//table//tr",
            "table rows",
            min_count=0,
        )

        current_date: date | None = None

        for row in rows:
            # Get all cells in the row
            cells = row.checked_xpath(
                "td",
                "row cells",
                min_count=0,
            )

            if len(cells) < 3:
                continue

            # Check if this is a date row (has <strong> in first cell)
            date_strong = cells[0].checked_xpath(
                "strong/text()",
                "date text",
                min_count=0,
                type=str,
            )

            if date_strong:
                # This is a date header row
                parsed_date = self._parse_date(date_strong[0])
                if parsed_date:
                    current_date = parsed_date
                continue

            # Check if this is the Decision List header row
            first_cell_strong = cells[0].checked_xpath(
                "strong/text()",
                "first cell strong",
                min_count=0,
                type=str,
            )
            if first_cell_strong and "Decision List" in first_cell_strong[0]:
                # Skip the Decision List header row
                continue

            # Get first cell text (opinion number)
            first_cell_texts = cells[0].checked_xpath(
                ".//text()",
                "first cell text",
                min_count=0,
                type=str,
            )
            first_cell_text = "".join(first_cell_texts).strip()

            # Check if this looks like an opinion number
            opinion_number = self._extract_opinion_number(first_cell_text)
            if not opinion_number:
                continue

            # Filter by specific docket if specified
            if target_docket and opinion_number != target_docket:
                # Also try without "No. " prefix
                if target_docket not in first_cell_text:
                    continue

            # Skip if no current date (shouldn't happen in well-formed page)
            if current_date is None:
                continue

            # Filter by date range
            if date_gte and current_date < date_gte:
                continue
            if date_lte and current_date > date_lte:
                continue

            # Get PDF link from second cell
            pdf_links = cells[1].checked_xpath(
                "a/@href",
                "PDF link",
                min_count=0,
                type=str,
            )
            if not pdf_links:
                continue

            pdf_url = urljoin(response.url, pdf_links[0])

            # Get case name from third cell
            case_name_texts = cells[2].checked_xpath(
                ".//text()",
                "case name",
                min_count=0,
                type=str,
            )
            case_name = "".join(case_name_texts).strip()
            if not case_name:
                case_name = "Unknown"

            # Determine opinion type from filename
            opinion_type = normalize_opinion_type(pdf_links[0])

            # Build accumulated data for download handler
            cluster_data = {
                "docket_id": opinion_number,
                "court_id": "ny",
                "date_filed": current_date.isoformat(),
                "case_name": case_name,
                "source_url": source_url,
                "opinions_data": [
                    {"download_url": pdf_url, "type": opinion_type}
                ],
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
    ) -> Generator[ScraperYield[NYOpinionCluster], None, None]:
        """Handle a downloaded opinion PDF and yield final cluster."""
        # Build the opinion with downloaded path
        op_data = accumulated_data["opinions_data"][0]
        opinion = NYOpinion(
            download_url=op_data["download_url"],
            type=op_data["type"],
            local_path=response.file_url,
        )

        # Parse date from ISO format
        from datetime import datetime

        date_filed = datetime.fromisoformat(
            accumulated_data["date_filed"]
        ).date()

        # Build and yield the cluster
        cluster = NYOpinionCluster(
            docket_id=accumulated_data["docket_id"],
            court_id=accumulated_data["court_id"],
            date_filed=date_filed,
            case_name=accumulated_data["case_name"],
            opinions=[opinion],
            source_url=accumulated_data.get("source_url"),
            precedential_status="Published",  # Court of Appeals opinions are published
        )

        yield ParsedData(cluster)
