"""North Dakota Supreme Court Scraper.

This module scrapes published opinions from the North Dakota Supreme Court.

Entry point:
- Opinions Search: https://www.ndcourts.gov/supreme-court/opinions

IMPORTANT: This scraper REQUIRES the PlaywrightDriver due to the
React SPA architecture of the opinion detail pages. The search results
list page is server-rendered, but individual opinion pages load data
via JavaScript, so static HTTP requests will not work for those.

Flow:
1. get_entry -> opinions search page (if "opinions" requested)
2. parse_opinions_list -> parses search results, yields NavigatingRequest for detail pages
3. parse_opinion_detail -> extracts PDF URL, yields ArchiveRequest for PDF
4. handle_opinion_download -> yields final NorthDakotaOpinionCluster

Design decisions:
- Uses PlaywrightDriver for JavaScript rendering (React SPA)
- Starts from the opinions search page which lists recent opinions
- Each opinion card shows metadata: case name, citation, docket, date, type, author
- The "View Opinion" button links to a detail page with the PDF
- Pagination via page parameter (?page=N, 0-indexed)
- Uses DateRange filter on date_filed for searching
- North Dakota has no intermediate appellate court - only the Supreme Court
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
    NorthDakotaOpinion,
    NorthDakotaOpinionCluster,
)

if TYPE_CHECKING:
    from collections.abc import Generator

    from juriscraper.scraper_driver.data_types import ScraperYield


# Base URLs
BASE_URL = "https://www.ndcourts.gov"
OPINIONS_URL = f"{BASE_URL}/supreme-court/opinions"


class NorthDakotaScraper(BaseScraper[NorthDakotaOpinionCluster]):
    """Scraper for North Dakota Supreme Court published opinions.

    IMPORTANT: This scraper requires PlaywrightDriver for JavaScript rendering.
    The opinion detail pages are rendered via React/JavaScript.

    Scrapes opinions from the North Dakota Supreme Court (nd).
    North Dakota does not have an intermediate appellate court.

    Usage:
        # Scrape all opinions
        scraper = NorthDakotaScraper()

        # Filter opinions by date range
        params = NorthDakotaScraper.params()
        params.NorthDakotaOpinionCluster.date_filed.gte = date(2026, 1, 1)
        params.NorthDakotaOpinionCluster.date_filed.lte = date(2026, 1, 31)
        scraper = NorthDakotaScraper(params=params)

        # Scrape specific opinion by citation
        params = NorthDakotaScraper.params()
        params.NorthDakotaOpinionCluster.docket_id.value = "2026 ND 7"
        scraper = NorthDakotaScraper(params=params)
    """

    # === Metadata ===
    court_ids: ClassVar[set[str]] = {"nd"}
    court_url: ClassVar[str] = "https://www.ndcourts.gov/supreme-court/"
    data_types: ClassVar[set[str]] = {"opinions"}
    status: ClassVar[ScraperStatus] = ScraperStatus.IN_DEVELOPMENT
    version: ClassVar[str] = "2026-01-23"
    requires_auth: ClassVar[bool] = False
    requires_playwright: ClassVar[bool] = True

    # Rate limiting - be respectful to court servers
    msec_per_request_rate_limit: ClassVar[int] = 2000

    # === Regex patterns ===
    # Citation pattern: YYYY ND NNN (e.g., "2026 ND 7")
    CITATION_PATTERN = re.compile(r"(\d{4})\s+ND\s+(\d+)")

    # Date pattern: M/D/YYYY (e.g., "1/15/2026")
    DATE_PATTERN = re.compile(r"(\d{1,2})/(\d{1,2})/(\d{4})")

    # Docket pattern: 8-digit number (e.g., "20240233")
    DOCKET_PATTERN = re.compile(r"Docket No\.:\s*(\d{8})")

    # Internal ID pattern from URL (e.g., "/supreme-court/opinions/202131")
    INTERNAL_ID_PATTERN = re.compile(r"/supreme-court/opinions/(\d+)")

    # Mapping from model name to data type
    MODEL_TO_DATA_TYPE: ClassVar[dict[str, str]] = {
        "NorthDakotaOpinionCluster": "opinions",
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
            model_proxy = self._params.NorthDakotaOpinionCluster
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

    def _parse_citation(self, text: str) -> tuple[int, int] | None:
        """Parse citation to extract year and number.

        Args:
            text: Text containing citation like '2026 ND 7'

        Returns:
            Tuple of (year, number) or None if not parseable
        """
        match = self.CITATION_PATTERN.search(text)
        if match:
            return int(match.group(1)), int(match.group(2))
        return None

    def _parse_date(self, date_str: str) -> date | None:
        """Parse date from filing date string.

        Args:
            date_str: Date like '1/15/2026'

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
                continuation=self.parse_opinions_list,
            )

    # =========================================================================
    # Opinions List Parsing
    # =========================================================================

    @step(xsd="xsds/parse_opinions_list.xsd")
    def parse_opinions_list(
        self,
        lxml_tree: CheckedHtmlElement,
        response: Response,
    ) -> Generator[ScraperYield[NorthDakotaOpinionCluster], None, None]:
        """Parse the opinions list page and yield requests for detail pages.

        The list page contains opinion cards with metadata:
        - Case name and citation (e.g., "State v. Krall 2026 ND 7")
        - Docket No.
        - Filing Date
        - Case Type
        - Author
        - View Opinion button linking to detail page
        """
        date_gte, date_lte, target_docket = self._get_search_params()

        # Get all opinion rows from the table
        rows = lxml_tree.checked_xpath(
            "//table//tr[.//button[contains(., 'View Opinion')]]",
            "opinion rows",
            min_count=0,
        )

        for row in rows:
            # Extract all text from the paragraph containing metadata
            # The structure is: case name + citation, then labeled fields
            para_texts = row.checked_xpath(
                ".//p[1]//text()",
                "opinion metadata",
                min_count=1,
                type=str,
            )
            full_text = " ".join(t.strip() for t in para_texts if t.strip())

            # Extract citation from the first line
            citation_match = self.CITATION_PATTERN.search(full_text)
            if not citation_match:
                continue

            year = int(citation_match.group(1))
            opinion_number = int(citation_match.group(2))
            citation = f"{year} ND {opinion_number}"

            # Filter by specific docket/citation if specified
            if target_docket and citation != target_docket:
                continue

            # Extract case name (everything before the citation)
            citation_start = full_text.find(f"{year} ND")
            case_name = full_text[:citation_start].strip() if citation_start > 0 else ""

            # Extract docket number
            docket_match = self.DOCKET_PATTERN.search(full_text)
            docket_number = docket_match.group(1) if docket_match else None

            # Extract filing date
            date_match = re.search(r"Filing Date:\s*(\d{1,2}/\d{1,2}/\d{4})", full_text)
            filing_date = None
            if date_match:
                filing_date = self._parse_date(date_match.group(1))

            if filing_date is None:
                continue

            # Filter by date range if specified
            if date_gte and filing_date < date_gte:
                continue
            if date_lte and filing_date > date_lte:
                continue

            # Extract case type
            case_type_match = re.search(r"Case Type:\s*([^A-Z][^\n]+?)(?=Author:|$)", full_text)
            case_type = case_type_match.group(1).strip() if case_type_match else None

            # Extract author
            author_match = re.search(r"Author:\s*(.+?)(?=$|\s{2,})", full_text)
            author_str = author_match.group(1).strip() if author_match else None

            # Get the View Opinion button URL
            # The button triggers a navigation to /supreme-court/opinions/{id}
            button_onclick = row.checked_xpath(
                ".//button[contains(., 'View Opinion')]/@onclick",
                "view opinion button",
                min_count=0,
                max_count=1,
                type=str,
            )

            # If no onclick, we need to find the internal ID differently
            # Check if there's a link or data attribute with the ID
            internal_id = None

            # Try to get internal ID from any link in the row
            links = row.checked_xpath(
                ".//a/@href",
                "opinion links",
                min_count=0,
                type=str,
            )
            for link in links:
                id_match = self.INTERNAL_ID_PATTERN.search(link)
                if id_match:
                    internal_id = id_match.group(1)
                    break

            if not internal_id:
                # The button might use JavaScript to navigate
                # We'll need to construct the detail page URL differently
                # For now, skip if we can't find the ID
                continue

            detail_url = f"{BASE_URL}/supreme-court/opinions/{internal_id}"

            # Build accumulated data for the detail page
            opinion_data = {
                "citation": citation,
                "docket_id": citation,
                "court_id": "nd",
                "date_filed": filing_date.isoformat(),
                "case_name": case_name,
                "docket_number": docket_number,
                "case_type": case_type,
                "author_str": author_str,
                "internal_id": internal_id,
                "year": year,
                "opinion_number": opinion_number,
                "source_url": response.url,
            }

            # Navigate to detail page to get PDF URL
            yield NavigatingRequest(
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url=detail_url,
                ),
                continuation=self.parse_opinion_detail,
                accumulated_data=opinion_data,
            )

        # Handle pagination - check for next page link
        next_page_links = lxml_tree.checked_xpath(
            "//a[contains(@href, 'page=')]/@href",
            "pagination links",
            min_count=0,
            type=str,
        )

        # Find the "next" page link (usually the one with the higher page number)
        current_url = response.url
        current_page = 1
        page_match = re.search(r"page=(\d+)", current_url)
        if page_match:
            current_page = int(page_match.group(1))

        for link in next_page_links:
            link_page_match = re.search(r"page=(\d+)", link)
            if link_page_match:
                link_page = int(link_page_match.group(1))
                # Follow pages sequentially
                if link_page == current_page + 1:
                    next_url = urljoin(BASE_URL, link)
                    yield NavigatingRequest(
                        request=HTTPRequestParams(
                            method=HttpMethod.GET,
                            url=next_url,
                        ),
                        continuation=self.parse_opinions_list,
                    )
                    break

    # =========================================================================
    # Opinion Detail Page Parsing
    # =========================================================================

    @step(xsd="xsds/parse_opinion_detail.xsd")
    def parse_opinion_detail(
        self,
        lxml_tree: CheckedHtmlElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[NorthDakotaOpinionCluster], None, None]:
        """Parse the opinion detail page and extract the PDF URL.

        The detail page (rendered via JavaScript) contains:
        - Opinion metadata (already have from list page)
        - Link to download the opinion PDF
        """
        # Look for PDF download link
        pdf_links = lxml_tree.checked_xpath(
            "//a[contains(@href, '.pdf') or contains(text(), 'Download') or contains(text(), 'PDF')]/@href",
            "PDF links",
            min_count=0,
            type=str,
        )

        pdf_url = None
        for link in pdf_links:
            if ".pdf" in link.lower():
                pdf_url = urljoin(response.url, link)
                break

        if not pdf_url:
            # Try alternative patterns for PDF links
            pdf_links = lxml_tree.checked_xpath(
                "//a[contains(@class, 'download') or contains(@class, 'pdf')]/@href",
                "alternative PDF links",
                min_count=0,
                type=str,
            )
            for link in pdf_links:
                pdf_url = urljoin(response.url, link)
                break

        if not pdf_url:
            # If still no PDF found, this might be a JS-rendered page
            # that hasn't loaded yet. Log and skip.
            return

        # Store PDF URL in accumulated data
        accumulated_data["pdf_url"] = pdf_url

        # Yield ArchiveRequest for the PDF
        yield ArchiveRequest(
            request=HTTPRequestParams(
                method=HttpMethod.GET,
                url=pdf_url,
            ),
            continuation=self.handle_opinion_download,
            expected_type="pdf",
            accumulated_data=accumulated_data,
        )

    # =========================================================================
    # Download Handler
    # =========================================================================

    @step
    def handle_opinion_download(
        self,
        response: ArchiveResponse,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[NorthDakotaOpinionCluster], None, None]:
        """Handle a downloaded opinion PDF."""
        date_filed = datetime.fromisoformat(
            accumulated_data["date_filed"]
        ).date()

        opinion = NorthDakotaOpinion(
            download_url=accumulated_data["pdf_url"],
            local_path=response.file_url,
        )

        cluster = NorthDakotaOpinionCluster(
            docket_id=accumulated_data["docket_id"],
            court_id=accumulated_data["court_id"],
            date_filed=date_filed,
            case_name=accumulated_data["case_name"],
            opinions=[opinion],
            source_url=accumulated_data["source_url"],
            docket_number=accumulated_data.get("docket_number"),
            case_type=accumulated_data.get("case_type"),
            author_str=accumulated_data.get("author_str"),
            internal_id=accumulated_data.get("internal_id"),
            opinion_number=accumulated_data.get("opinion_number"),
            year=accumulated_data.get("year"),
            precedential_status="Published",
        )

        yield ParsedData(cluster)
