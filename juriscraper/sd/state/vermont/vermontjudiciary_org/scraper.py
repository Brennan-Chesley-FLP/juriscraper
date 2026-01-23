"""Vermont Supreme Court Scraper.

This module scrapes opinions from the Vermont Supreme Court's
Opinions, Decisions and Order Library.

Entry points:
- Search page: https://www.vermontjudiciary.org/opinions-decisions

Flow:
1. get_entry -> opinions search page with Supreme Court filter
2. parse_search_results -> parses articles, yields ArchiveRequests for PDFs
3. handle_opinion_download -> yields final VermontOpinionCluster

Design decisions:
- Uses the Supreme Court filter (court_division_opinions_library_:7)
- Each result shows case name, date, docket number, and link to PDF
- Docket format: YY-AP-NNN (e.g., 25-AP-314)
- Date format: MM/DD/YYYY
- Supports date range filtering via DateRange on date_filed
- Vermont has no intermediate appellate court - only the Supreme Court
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import TYPE_CHECKING, ClassVar
from urllib.parse import urlencode, urljoin

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
    VermontOpinion,
    VermontOpinionCluster,
)

if TYPE_CHECKING:
    from collections.abc import Generator

    from juriscraper.scraper_driver.data_types import ScraperYield


# Base URLs
BASE_URL = "https://www.vermontjudiciary.org"
# The filter court_division_opinions_library_:7 shows only Supreme Court entries
OPINIONS_URL = "https://www.vermontjudiciary.org/opinions-decisions"


class VermontScraper(BaseScraper[VermontOpinionCluster]):
    """Scraper for Vermont Supreme Court opinions.

    Scrapes published and unpublished opinions from the Vermont Supreme Court
    through the Opinions, Decisions and Order Library.

    Usage:
        # Scrape all opinions
        scraper = VermontScraper()

        # Filter opinions by date range
        params = VermontScraper.params()
        params.VermontOpinionCluster.date_filed.gte = date(2026, 1, 1)
        params.VermontOpinionCluster.date_filed.lte = date(2026, 1, 31)
        scraper = VermontScraper(params=params)

        # Scrape specific opinion by docket number
        params = VermontScraper.params()
        params.VermontOpinionCluster.docket_id.value = "25-AP-314"
        scraper = VermontScraper(params=params)
    """

    # === Metadata ===
    court_ids: ClassVar[set[str]] = {"vt"}
    court_url: ClassVar[str] = "https://www.vermontjudiciary.org/supreme-court"
    data_types: ClassVar[set[str]] = {"opinions"}
    status: ClassVar[ScraperStatus] = ScraperStatus.IN_DEVELOPMENT
    version: ClassVar[str] = "2026-01-23"
    requires_auth: ClassVar[bool] = False

    # Rate limiting - be respectful to court servers
    msec_per_request_rate_limit: ClassVar[int] = 1000

    # === Regex patterns ===
    # Date parsing pattern: MM/DD/YYYY
    DATE_PATTERN = re.compile(r"(\d{2})/(\d{2})/(\d{4})")

    # Media ID extraction from URL: /media/19786
    MEDIA_ID_PATTERN = re.compile(r"/media/(\d+)")

    # Docket number pattern: YY-AP-NNN (e.g., 25-AP-314)
    DOCKET_PATTERN = re.compile(r"\d{2}-AP-\d+")

    # Mapping from model name to data type
    MODEL_TO_DATA_TYPE: ClassVar[dict[str, str]] = {
        "VermontOpinionCluster": "opinions",
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
            model_proxy = self._params.VermontOpinionCluster
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

    def _parse_date(self, date_str: str) -> date | None:
        """Parse date from result entry.

        Args:
            date_str: Date like 'MM/DD/YYYY' (e.g., '01/09/2026')

        Returns:
            Parsed date or None
        """
        match = self.DATE_PATTERN.search(date_str)
        if match:
            month = int(match.group(1))
            day = int(match.group(2))
            year = int(match.group(3))
            return date(year, month, day)
        return None

    def _build_search_url(
        self,
        page: int = 0,
        date_from: date | None = None,
        date_to: date | None = None,
    ) -> str:
        """Build the search URL with filters.

        Args:
            page: Page number (0-indexed)
            date_from: Start date filter
            date_to: End date filter

        Returns:
            Full search URL
        """
        params = {
            "f[0]": "court_division_opinions_library_:7",  # Supreme Court filter
            "search_api_fulltext": "",
            "page": str(page),
        }

        if date_from:
            params["facet_from_date"] = date_from.strftime("%m/%d/%Y")
        else:
            params["facet_from_date"] = ""

        if date_to:
            params["facet_to_date"] = date_to.strftime("%m/%d/%Y")
        else:
            params["facet_to_date"] = ""

        return f"{OPINIONS_URL}?{urlencode(params)}"

    # =========================================================================
    # Entry Point
    # =========================================================================

    def get_entry(self) -> Generator[NavigatingRequest, None, None]:
        """Yield initial request to opinions search page."""
        requested = self._get_requested_data_types()

        if "opinions" in requested:
            date_gte, date_lte, _ = self._get_search_params()

            url = self._build_search_url(
                page=0,
                date_from=date_gte,
                date_to=date_lte,
            )

            yield NavigatingRequest(
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url=url,
                ),
                continuation=self.parse_search_results,
                accumulated_data={"page": 0},
            )

    # =========================================================================
    # Search Results Parsing
    # =========================================================================

    @step(xsd="xsds/parse_search_results.xsd")
    def parse_search_results(
        self,
        lxml_tree: CheckedHtmlElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[VermontOpinionCluster], None, None]:
        """Parse the search results page and yield requests for PDFs."""
        date_gte, date_lte, target_docket = self._get_search_params()
        current_page = accumulated_data.get("page", 0)

        # Get all article elements containing results
        articles = lxml_tree.checked_xpath(
            "//main//article",
            "opinion result articles",
            min_count=0,
        )

        for article in articles:
            # Extract case name and PDF link
            case_links = article.checked_xpath(
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

            # Extract media ID from URL
            media_match = self.MEDIA_ID_PATTERN.search(pdf_url)
            if not media_match:
                continue
            media_id = int(media_match.group(1))

            # Extract date from time element
            date_elements = article.checked_xpath(
                ".//time/text()",
                "date text",
                min_count=0,
                max_count=1,
                type=str,
            )

            opinion_date = None
            if date_elements:
                opinion_date = self._parse_date(date_elements[0])

            if opinion_date is None:
                # Skip entries without a valid date
                continue

            # Filter by date range if specified
            if date_gte and opinion_date < date_gte:
                continue
            if date_lte and opinion_date > date_lte:
                continue

            # Extract court division - we only want Supreme Court
            article.checked_xpath(
                ".//div[contains(@class, 'field--name-field-court-division')]//text() | "
                ".//span[contains(@class, 'views-field-field-court-division')]//text() | "
                ".//*[contains(text(), 'Supreme Court') or contains(text(), 'Civil') or "
                "contains(text(), 'Environmental') or contains(text(), 'Family') or "
                "contains(text(), 'Criminal') or contains(text(), 'Probate')]/text()",
                "court division",
                min_count=0,
                type=str,
            )

            # The division is shown as text in the article
            # Based on the page structure, it's in a generic div after the time
            all_texts = article.checked_xpath(
                ".//text()",
                "all text",
                min_count=0,
                type=str,
            )
            all_text = " ".join(t.strip() for t in all_texts if t.strip())

            # Only process Supreme Court entries
            if "Supreme Court" not in all_text:
                continue

            # Extract docket number (last text element in the article)
            # The structure is: link, time, division, docket
            docket_texts = article.checked_xpath(
                ".//*[not(self::a) and not(self::time)]/text()",
                "docket text candidates",
                min_count=0,
                type=str,
            )

            docket_id = None
            for text in reversed(docket_texts):
                text = text.strip()
                if self.DOCKET_PATTERN.match(text):
                    docket_id = text
                    break

            if docket_id is None:
                # Try to find docket in all text
                for text in all_texts:
                    text = text.strip()
                    if self.DOCKET_PATTERN.match(text):
                        docket_id = text
                        break

            if docket_id is None:
                continue

            # Filter by specific docket if specified
            if target_docket and docket_id != target_docket:
                continue

            # Build accumulated data for download handler
            cluster_data = {
                "docket_id": docket_id,
                "court_id": "vt",
                "date_filed": opinion_date.isoformat(),
                "case_name": case_name,
                "source_url": response.url,
                "media_id": media_id,
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

        # Check for next page
        next_page_links = lxml_tree.checked_xpath(
            "//a[contains(@class, 'page-link') and contains(., 'Next')]/@href | "
            "//nav[@aria-label='Pagination']//a[text()='>']/@href | "
            "//li/a[contains(.//text(), '>')]/@href",
            "next page link",
            min_count=0,
            type=str,
        )

        if next_page_links:
            next_page = current_page + 1
            date_gte, date_lte, _ = self._get_search_params()

            next_url = self._build_search_url(
                page=next_page,
                date_from=date_gte,
                date_to=date_lte,
            )

            yield NavigatingRequest(
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url=next_url,
                ),
                continuation=self.parse_search_results,
                accumulated_data={"page": next_page},
            )

    # =========================================================================
    # Download Handler
    # =========================================================================

    @step
    def handle_opinion_download(
        self,
        response: ArchiveResponse,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[VermontOpinionCluster], None, None]:
        """Handle a downloaded opinion PDF."""
        date_filed = datetime.fromisoformat(
            accumulated_data["date_filed"]
        ).date()

        opinion = VermontOpinion(
            download_url=accumulated_data["pdf_url"],
            local_path=response.file_url,
        )

        cluster = VermontOpinionCluster(
            docket_id=accumulated_data["docket_id"],
            court_id=accumulated_data["court_id"],
            date_filed=date_filed,
            case_name=accumulated_data["case_name"],
            opinions=[opinion],
            source_url=accumulated_data["source_url"],
            media_id=accumulated_data["media_id"],
        )

        yield ParsedData(cluster)
