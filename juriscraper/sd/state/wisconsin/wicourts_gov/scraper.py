"""Wisconsin Appellate Courts Scraper.

This module scrapes opinions from Wisconsin appellate courts:
- Wisconsin Supreme Court (wis)
- Wisconsin Court of Appeals (wisctapp)

Entry points:
- Supreme Court: https://www.wicourts.gov/supreme/scopin.jsp?begin_date=MM/DD/YYYY&end_date=MM/DD/YYYY&SortBy=date
- Court of Appeals: https://www.wicourts.gov/other/appeals/caopin.jsp?begin_date=MM/DD/YYYY&end_date=MM/DD/YYYY&SortBy=date

Flow:
1. get_entry -> opinions pages for both courts (if "opinions" requested)
2. parse_supreme_court_opinions -> iterate through table rows, extract opinion metadata
3. parse_appeals_court_opinions -> iterate through table rows, extract opinion metadata
4. For each opinion: yield ArchiveRequest for PDF
5. handle_opinion_download -> yield final WisconsinOpinionCluster

Data characteristics:
- Supreme Court: Columns are Release date, Case number, Caption, PDF link
- Court of Appeals: Columns are Release date, Case number, Caption, District, County, PDF link
- Court of Appeals may have "[Recommended for Publication]" in caption
- All Supreme Court opinions are published
- Court of Appeals opinions are generally unpublished unless noted
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
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
    WisconsinOpinion,
    WisconsinOpinionCluster,
)

if TYPE_CHECKING:
    from collections.abc import Generator

    from juriscraper.scraper_driver.data_types import ScraperYield


# Base URLs
BASE_URL = "https://www.wicourts.gov"
SUPREME_COURT_OPINIONS_URL = "https://www.wicourts.gov/supreme/scopin.jsp"
APPEALS_COURT_OPINIONS_URL = "https://www.wicourts.gov/other/appeals/caopin.jsp"


class WisconsinScraper(BaseScraper[WisconsinOpinionCluster]):
    """Scraper for Wisconsin appellate court opinions.

    Scrapes opinions from both Wisconsin appellate courts:
    - Wisconsin Supreme Court (wis)
    - Wisconsin Court of Appeals (wisctapp)

    Usage:
        # Scrape all opinions for the last 30 days
        scraper = WisconsinScraper()

        # Filter opinions by date range
        params = WisconsinScraper.params()
        params.WisconsinOpinionCluster.date_filed.gte = date(2026, 1, 1)
        params.WisconsinOpinionCluster.date_filed.lte = date(2026, 1, 31)
        scraper = WisconsinScraper(params=params)

        # Scrape specific court only
        params = WisconsinScraper.params()
        params.WisconsinOpinionCluster.court_id.values = {"wis"}  # Supreme Court only
        scraper = WisconsinScraper(params=params)

        # Scrape specific case by docket number
        params = WisconsinScraper.params()
        params.WisconsinOpinionCluster.docket_number.value = "2023AP002319-CR"
        scraper = WisconsinScraper(params=params)
    """

    # === Metadata ===
    court_ids: ClassVar[set[str]] = {"wis", "wisctapp"}
    court_url: ClassVar[str] = "https://www.wicourts.gov/"
    data_types: ClassVar[set[str]] = {"opinions"}
    status: ClassVar[ScraperStatus] = ScraperStatus.IN_DEVELOPMENT
    version: ClassVar[str] = "2026-01-23"
    requires_auth: ClassVar[bool] = False

    # Rate limiting - be respectful to court servers
    msec_per_request_rate_limit: ClassVar[int] = 1000

    # === Regex patterns ===
    # Date parsing pattern for MM/DD/YYYY or M/D/YYYY
    DATE_PATTERN = re.compile(r"(\d{1,2})/(\d{1,2})/(\d{4})")

    # Date format with month name: "Jan 14, 2026"
    DATE_MONTH_PATTERN = re.compile(
        r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+(\d{1,2}),\s+(\d{4})"
    )

    # Month name to number mapping
    MONTH_MAP: ClassVar[dict[str, int]] = {
        "Jan": 1,
        "Feb": 2,
        "Mar": 3,
        "Apr": 4,
        "May": 5,
        "Jun": 6,
        "Jul": 7,
        "Aug": 8,
        "Sep": 9,
        "Oct": 10,
        "Nov": 11,
        "Dec": 12,
    }

    # Mapping from model name to data type
    MODEL_TO_DATA_TYPE: ClassVar[dict[str, str]] = {
        "WisconsinOpinionCluster": "opinions",
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
            Tuple of (date_gte, date_lte, docket_number, court_ids)
        """
        if self._params is None:
            return None, None, None, None

        try:
            model_proxy = self._params.WisconsinOpinionCluster
        except AttributeError:
            return None, None, None, None

        date_gte = None
        date_lte = None
        docket_number = None
        court_ids = None

        searchable = model_proxy.get_searchable_fields()

        date_field = searchable.get("date_filed")
        if date_field and date_field.is_set():
            date_gte = date_field.gte
            date_lte = date_field.lte

        docket_field = searchable.get("docket_number")
        if docket_field and docket_field.is_set():
            docket_number = docket_field.value

        court_field = searchable.get("court_id")
        if court_field and court_field.is_set():
            court_ids = court_field.values

        return date_gte, date_lte, docket_number, court_ids

    def _parse_date_str(self, date_str: str) -> date | None:
        """Parse date from various formats.

        Supports:
        - "Jan 14, 2026" format
        - "01/14/2026" or "1/14/2026" format

        Args:
            date_str: Date string

        Returns:
            Parsed date or None
        """
        # Try month name format first (Jan 14, 2026)
        match = self.DATE_MONTH_PATTERN.match(date_str.strip())
        if match:
            month_name = match.group(1)
            day = int(match.group(2))
            year = int(match.group(3))
            month = self.MONTH_MAP.get(month_name, 1)
            return date(year, month, day)

        # Try numeric format (MM/DD/YYYY or M/D/YYYY)
        match = self.DATE_PATTERN.match(date_str.strip())
        if match:
            month = int(match.group(1))
            day = int(match.group(2))
            year = int(match.group(3))
            return date(year, month, day)

        return None

    def _get_date_range(self) -> tuple[date, date]:
        """Determine date range to scrape based on date filters.

        Returns:
            Tuple of (start_date, end_date) inclusive
        """
        date_gte, date_lte, _, _ = self._get_search_params()

        today = date.today()

        if date_gte and date_lte:
            return date_gte, date_lte
        elif date_gte:
            return date_gte, today
        elif date_lte:
            # Go back to 1995 (earliest available for Supreme Court)
            return date(1995, 9, 1), date_lte
        else:
            # Default to last 30 days
            return today - timedelta(days=30), today

    def _format_date_url(self, d: date) -> str:
        """Format a date for URL parameters (MM/DD/YYYY)."""
        return d.strftime("%m/%d/%Y")

    # =========================================================================
    # Entry Point
    # =========================================================================

    def get_entry(self) -> Generator[NavigatingRequest, None, None]:
        """Yield initial request(s) to opinions pages."""
        requested = self._get_requested_data_types()

        if "opinions" not in requested:
            return

        _, _, _, court_ids = self._get_search_params()
        start_date, end_date = self._get_date_range()

        # Build date parameters
        begin_date = self._format_date_url(start_date)
        end_date_str = self._format_date_url(end_date)

        # Request Supreme Court opinions (if not filtered out)
        if court_ids is None or "wis" in court_ids:
            url = f"{SUPREME_COURT_OPINIONS_URL}?begin_date={begin_date}&end_date={end_date_str}&SortBy=date"
            yield NavigatingRequest(
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url=url,
                ),
                continuation=self.parse_supreme_court_opinions,
                accumulated_data={"court_id": "wis"},
            )

        # Request Court of Appeals opinions (if not filtered out)
        if court_ids is None or "wisctapp" in court_ids:
            url = f"{APPEALS_COURT_OPINIONS_URL}?begin_date={begin_date}&end_date={end_date_str}&SortBy=date"
            yield NavigatingRequest(
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url=url,
                ),
                continuation=self.parse_appeals_court_opinions,
                accumulated_data={"court_id": "wisctapp"},
            )

    # =========================================================================
    # Supreme Court Opinions Parsing
    # =========================================================================

    @step(xsd="xsds/parse_supreme_court_opinions.xsd")
    def parse_supreme_court_opinions(
        self,
        lxml_tree: CheckedHtmlElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[WisconsinOpinionCluster], None, None]:
        """Parse the Supreme Court opinions page.

        Table structure:
        - Release date | Case number | Caption | Select/view (PDF checkbox and link)
        """
        date_gte, date_lte, target_docket, target_courts = self._get_search_params()

        # Check for "no records found" message
        no_records = lxml_tree.xpath(
            "//*[contains(text(), 'no records found')]"
        )
        if no_records:
            return

        # Find all data rows in the table body
        # The structure has a tbody with opinion rows
        rows = lxml_tree.checked_xpath(
            "//table//tbody/tr",
            "opinion table rows",
            min_count=0,
        )

        for row in rows:
            yield from self._parse_supreme_court_row(
                row,
                response,
                date_gte,
                date_lte,
                target_docket,
            )

    def _parse_supreme_court_row(
        self,
        row: CheckedHtmlElement,
        response: Response,
        date_gte: date | None,
        date_lte: date | None,
        target_docket: str | None,
    ) -> Generator[ScraperYield[WisconsinOpinionCluster], None, None]:
        """Parse a single row from the Supreme Court opinions table."""
        cells = row.checked_xpath(
            "./td",
            "table cells",
            min_count=0,
        )

        if len(cells) < 4:
            return

        # Extract cell content
        # Cell 0: Release date
        date_text = cells[0].text_content().strip()
        opinion_date = self._parse_date_str(date_text)

        if opinion_date is None:
            return

        # Filter by date range if specified
        if date_gte and opinion_date < date_gte:
            return
        if date_lte and opinion_date > date_lte:
            return

        # Cell 1: Case number
        docket_number = cells[1].text_content().strip()

        # Filter by docket if specified
        if target_docket and docket_number != target_docket:
            return

        # Cell 2: Caption (case name)
        case_name = cells[2].text_content().strip()

        # Cell 3: PDF link
        pdf_links = cells[3].xpath(".//a[contains(@href, '.pdf')]/@href")
        if not pdf_links:
            return

        pdf_url = urljoin(response.url, pdf_links[0])

        # Build accumulated data for download handler
        cluster_data = {
            "docket_number": docket_number,
            "court_id": "wis",
            "date_filed": opinion_date.isoformat(),
            "case_name": case_name,
            "source_url": response.url,
            "district": None,
            "county": None,
            "precedential_status": "Published",
            "recommended_for_publication": False,
            "pdf_url": pdf_url,
        }

        # Yield ArchiveRequest for the opinion PDF
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
    # Court of Appeals Opinions Parsing
    # =========================================================================

    @step(xsd="xsds/parse_appeals_court_opinions.xsd")
    def parse_appeals_court_opinions(
        self,
        lxml_tree: CheckedHtmlElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[WisconsinOpinionCluster], None, None]:
        """Parse the Court of Appeals opinions page.

        Table structure:
        - Release date | Case number | Caption | District | County | Select/view (PDF)

        Caption may contain "[Recommended for Publication]" in bold.
        """
        date_gte, date_lte, target_docket, target_courts = self._get_search_params()

        # Check for "no records found" message
        no_records = lxml_tree.xpath(
            "//*[contains(text(), 'no records found')]"
        )
        if no_records:
            return

        # Find all data rows in the table body
        rows = lxml_tree.checked_xpath(
            "//table//tbody/tr",
            "opinion table rows",
            min_count=0,
        )

        for row in rows:
            yield from self._parse_appeals_court_row(
                row,
                response,
                date_gte,
                date_lte,
                target_docket,
            )

    def _parse_appeals_court_row(
        self,
        row: CheckedHtmlElement,
        response: Response,
        date_gte: date | None,
        date_lte: date | None,
        target_docket: str | None,
    ) -> Generator[ScraperYield[WisconsinOpinionCluster], None, None]:
        """Parse a single row from the Court of Appeals opinions table."""
        cells = row.checked_xpath(
            "./td",
            "table cells",
            min_count=0,
        )

        if len(cells) < 6:
            return

        # Extract cell content
        # Cell 0: Release date
        date_text = cells[0].text_content().strip()
        opinion_date = self._parse_date_str(date_text)

        if opinion_date is None:
            return

        # Filter by date range if specified
        if date_gte and opinion_date < date_gte:
            return
        if date_lte and opinion_date > date_lte:
            return

        # Cell 1: Case number
        docket_number = cells[1].text_content().strip()

        # Filter by docket if specified
        if target_docket and docket_number != target_docket:
            return

        # Cell 2: Caption (case name)
        # May contain "[Recommended for Publication]" in bold
        case_name_full = cells[2].text_content().strip()

        # Check for recommended for publication
        recommended = "[Recommended for Publication]" in case_name_full
        case_name = case_name_full.replace("[Recommended for Publication]", "").strip()

        # Determine precedential status
        # Court of Appeals opinions are generally unpublished unless marked
        precedential_status = "Published" if recommended else "Unpublished"

        # Cell 3: District
        district = cells[3].text_content().strip()

        # Cell 4: County
        county = cells[4].text_content().strip()

        # Cell 5: PDF link
        pdf_links = cells[5].xpath(".//a[contains(@href, '.pdf')]/@href")
        if not pdf_links:
            return

        pdf_url = urljoin(response.url, pdf_links[0])

        # Build accumulated data for download handler
        cluster_data = {
            "docket_number": docket_number,
            "court_id": "wisctapp",
            "date_filed": opinion_date.isoformat(),
            "case_name": case_name,
            "source_url": response.url,
            "district": district if district else None,
            "county": county if county else None,
            "precedential_status": precedential_status,
            "recommended_for_publication": recommended,
            "pdf_url": pdf_url,
        }

        # Yield ArchiveRequest for the opinion PDF
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
    ) -> Generator[ScraperYield[WisconsinOpinionCluster], None, None]:
        """Handle a downloaded opinion PDF."""
        # Create opinion object for this download
        opinion = WisconsinOpinion(
            download_url=accumulated_data["pdf_url"],
            local_path=response.file_url,
        )

        # Parse the date from ISO format
        date_filed = datetime.fromisoformat(accumulated_data["date_filed"]).date()

        # Build and yield the final cluster
        cluster = WisconsinOpinionCluster(
            docket_number=accumulated_data["docket_number"],
            court_id=accumulated_data["court_id"],
            date_filed=date_filed,
            case_name=accumulated_data["case_name"],
            opinions=[opinion],
            source_url=accumulated_data["source_url"],
            district=accumulated_data.get("district"),
            county=accumulated_data.get("county"),
            precedential_status=accumulated_data["precedential_status"],
            recommended_for_publication=accumulated_data.get(
                "recommended_for_publication", False
            ),
        )

        yield ParsedData(cluster)
