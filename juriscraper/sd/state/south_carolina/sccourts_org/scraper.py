"""South Carolina Appellate Courts Opinion Scraper.

This module contains a unified scraper for opinions from South Carolina courts:
- Supreme Court of South Carolina (sc)
- Court of Appeals of South Carolina (scctapp)

Entry points:
- Published SC: https://www.sccourts.org/opinions-orders/opinions/published-opinions/supreme-court/
- Published COA: https://www.sccourts.org/opinions-orders/opinions/published-opinions/court-of-appeals/
- Unpublished SC: https://www.sccourts.org/opinions-orders/opinions/unpublished-opinions/supreme-court/
- Unpublished COA: https://www.sccourts.org/opinions-orders/opinions/unpublished-opinions/court-of-appeals/

Opinion Listing URL patterns:
- With month filter: ?term={YYYY-MM}

PDF URL patterns:
- Supreme Court: https://www.sccourts.org/media/opinions/HTMLFiles/SC/{opinion_number}.pdf
- Court of Appeals: https://www.sccourts.org/media/opinions/HTMLFiles/COA/{opinion_number}.pdf

Flow:
  1. get_entry -> opinion listing page for selected courts (if "opinions" requested)
  2. parse_opinion_listing -> extracts opinion metadata from date-grouped listings
  3. yields ArchiveRequests for PDFs
  4. handle_opinion_download -> stores local paths, yields final clusters

Design decisions:
- Uses restrictive checked_xpaths to catch structural changes early
- Uses DateRange filter on date_filed for searching
- Uses SetFilter on court_id to select which courts to scrape
- Archives opinion PDFs via ArchiveRequest
- Supports month-based filtering via URL parameters
- Scrapes both published and unpublished opinions
"""

from __future__ import annotations

import re
from datetime import date
from typing import TYPE_CHECKING, Any, ClassVar
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
    COURT_IDS,
    COURT_URL_SEGMENT,
    SCOpinion,
    SCOpinionCluster,
)

if TYPE_CHECKING:
    from collections.abc import Generator

    from juriscraper.scraper_driver.data_types import ScraperYield


class SouthCarolinaScraper(BaseScraper[SCOpinionCluster]):
    """Unified scraper for South Carolina appellate court opinions.

    Scrapes opinions from Supreme Court and Court of Appeals.

    Usage:
        # Scrape all courts (default)
        scraper = SouthCarolinaScraper()

        # Scrape only Supreme Court
        params = SouthCarolinaScraper.params()
        params.SCOpinionCluster.court_id.values = {"sc"}
        scraper = SouthCarolinaScraper(params=params)

        # Scrape only Court of Appeals
        params = SouthCarolinaScraper.params()
        params.SCOpinionCluster.court_id.values = {"scctapp"}
        scraper = SouthCarolinaScraper(params=params)

        # Filter by date range
        params = SouthCarolinaScraper.params()
        params.SCOpinionCluster.date_filed.gte = date(2026, 1, 1)
        params.SCOpinionCluster.date_filed.lte = date(2026, 1, 31)
        scraper = SouthCarolinaScraper(params=params)

        # Lookup specific opinion number
        params = SouthCarolinaScraper.params()
        params.SCOpinionCluster.opinion_number.value = "28309"
        scraper = SouthCarolinaScraper(params=params)
    """

    # === Metadata ===
    court_ids: ClassVar[set[str]] = COURT_IDS
    court_url: ClassVar[str] = "https://www.sccourts.org/"
    data_types: ClassVar[set[str]] = {"opinions"}
    status: ClassVar[ScraperStatus] = ScraperStatus.IN_DEVELOPMENT
    version: ClassVar[str] = "2026-01-23"
    requires_auth: ClassVar[bool] = False

    # Rate limiting - be respectful to court servers
    msec_per_request_rate_limit: ClassVar[int] = 1000

    # Base URLs for opinion listings
    BASE_URL = "https://www.sccourts.org"
    PUBLISHED_URL_TEMPLATE = (
        "/opinions-orders/opinions/published-opinions/{court_segment}/"
    )
    UNPUBLISHED_URL_TEMPLATE = (
        "/opinions-orders/opinions/unpublished-opinions/{court_segment}/"
    )

    # === Regex patterns ===
    # Opinion number pattern from PDF URL: .../SC/28309.pdf or .../COA/6128.pdf
    OPINION_NUMBER_PATTERN = re.compile(r"/(?:SC|COA)/(\d+)\.pdf")

    # Date pattern for parsing date headings: "January 7, 2026"
    DATE_HEADING_PATTERN = re.compile(
        r"(January|February|March|April|May|June|July|August|September|"
        r"October|November|December)\s+(\d{1,2}),\s+(\d{4})"
    )

    MONTH_NAMES = {
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

    def _parse_date_heading(self, heading: str) -> date | None:
        """Parse a date heading like 'January 7, 2026'.

        Args:
            heading: Date string in "Month D, YYYY" format.

        Returns:
            Parsed date object, or None if parsing fails.
        """
        match = self.DATE_HEADING_PATTERN.search(heading)
        if not match:
            return None

        month_name, day_str, year_str = match.groups()
        try:
            month = self.MONTH_NAMES[month_name]
            return date(int(year_str), month, int(day_str))
        except (KeyError, ValueError):
            return None

    def _get_opinions_search_params(
        self,
    ) -> tuple[date | None, date | None, str | None, set[str] | None]:
        """Extract search parameters for opinions from ScraperParams.

        Returns:
            Tuple of (date_gte, date_lte, opinion_number, court_ids)
        """
        if self._params is None:
            return None, None, None, None

        try:
            model_proxy = self._params.SCOpinionCluster
        except AttributeError:
            return None, None, None, None

        date_gte = None
        date_lte = None
        opinion_number = None
        court_ids = None

        searchable = model_proxy.get_searchable_fields()

        date_field = searchable.get("date_filed")
        if date_field and date_field.is_set():
            date_gte = date_field.gte
            date_lte = date_field.lte

        opinion_field = searchable.get("opinion_number")
        if opinion_field and opinion_field.is_set():
            opinion_number = opinion_field.value

        court_field = searchable.get("court_id")
        if court_field and court_field.is_set():
            court_ids = court_field.values

        return date_gte, date_lte, opinion_number, court_ids

    def _get_target_courts(self) -> list[str]:
        """Get the list of court IDs to scrape based on court_ids filter.

        Returns list of court IDs: 'sc', 'scctapp'
        """
        _, _, _, court_ids = self._get_opinions_search_params()

        if court_ids:
            return sorted(court_ids & COURT_IDS)

        # Default: both courts
        return sorted(COURT_IDS)

    def _build_listing_url(
        self, court_id: str, published: bool, year: int, month: int
    ) -> str:
        """Build the opinion listing URL with parameters.

        Args:
            court_id: 'sc' or 'scctapp'
            published: True for published opinions, False for unpublished
            year: Year to filter by
            month: Month to filter by

        Returns:
            Full URL for the opinion listing page
        """
        court_segment = COURT_URL_SEGMENT[court_id]
        if published:
            path = self.PUBLISHED_URL_TEMPLATE.format(
                court_segment=court_segment
            )
        else:
            path = self.UNPUBLISHED_URL_TEMPLATE.format(
                court_segment=court_segment
            )

        term = f"{year:04d}-{month:02d}"
        return f"{self.BASE_URL}{path}?term={term}"

    # =========================================================================
    # Entry Point
    # =========================================================================

    @entry(SCOpinionCluster)
    def get_entry(self) -> Generator[NavigatingRequest, None, None]:
        """Yield initial requests for opinion scraping.

        Yields NavigatingRequests for each court and publication status.
        """
        courts = self._get_target_courts()
        date_gte, date_lte, opinion_number, _ = (
            self._get_opinions_search_params()
        )

        # Determine month/year range for searching
        today = date.today()
        if date_gte:
            start_year, start_month = date_gte.year, date_gte.month
        else:
            start_year, start_month = today.year, today.month

        if date_lte:
            end_year, end_month = date_lte.year, date_lte.month
        else:
            end_year, end_month = today.year, today.month

        # Build list of (year, month) tuples to scrape
        months_to_scrape = []
        current_year, current_month = start_year, start_month
        while (current_year, current_month) <= (end_year, end_month):
            months_to_scrape.append((current_year, current_month))
            current_month += 1
            if current_month > 12:
                current_month = 1
                current_year += 1

        # Build queue of requests: (court_id, published, year, month)
        request_queue = []
        for court_id in courts:
            for year, month in months_to_scrape:
                # Published opinions
                request_queue.append((court_id, True, year, month))
                # Unpublished opinions
                request_queue.append((court_id, False, year, month))

        if not request_queue:
            return

        first = request_queue[0]
        remaining = request_queue[1:]

        court_id, published, year, month = first
        url = self._build_listing_url(court_id, published, year, month)

        yield NavigatingRequest(
            request=HTTPRequestParams(
                method=HttpMethod.GET,
                url=url,
            ),
            continuation=self.parse_opinion_listing,
            accumulated_data={
                "court_id": court_id,
                "published": published,
                "year": year,
                "month": month,
                "remaining_requests": remaining,
                "opinion_number_filter": opinion_number,
                "date_gte": date_gte.isoformat() if date_gte else None,
                "date_lte": date_lte.isoformat() if date_lte else None,
            },
        )

    # =========================================================================
    # Opinion Listing Parsing
    # =========================================================================

    @step(xsd="xsds/parse_opinion_listing.xsd")
    def parse_opinion_listing(
        self,
        lxml_tree: CheckedHtmlElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[SCOpinionCluster], None, None]:
        """Parse the opinion listing page.

        The page structure has::

        - Date headings (h3) like "January 7, 2026"
        - Opinion entries under each date with:

          - Opinion number (first paragraph)
          - Case name (second paragraph)
          - Download link to PDF

        Extracts opinion metadata and yields ArchiveRequests for each PDF.
        """
        court_id = accumulated_data.get("court_id", "sc")
        published = accumulated_data.get("published", True)
        remaining_requests = accumulated_data.get("remaining_requests", [])
        opinion_number_filter = accumulated_data.get("opinion_number_filter")
        date_gte_str = accumulated_data.get("date_gte")
        date_lte_str = accumulated_data.get("date_lte")

        date_gte = date.fromisoformat(date_gte_str) if date_gte_str else None
        date_lte = date.fromisoformat(date_lte_str) if date_lte_str else None

        # Find the content section with opinions
        # The opinions are in a container with date headings (h3) and opinion entries
        # Structure: container > h3 (date) > generic (opinion entry with p+p+link)

        # Find all date headings
        date_headings = lxml_tree.xpath("//h3")

        current_date: date | None = None

        for heading in date_headings:
            heading_text = heading.text_content().strip()
            parsed_date = self._parse_date_heading(heading_text)

            if parsed_date:
                current_date = parsed_date

            # Find the sibling opinion entries after this date heading
            # These are generic elements containing opinion data
            following = heading.xpath(
                "following-sibling::*[self::div or self::section or "
                "name()='generic' or self::article or not(self::h3)]"
            )

            for element in following:
                # Stop if we hit another h3 (next date section)
                if element.tag == "h3":
                    break

                # Look for download links to PDFs
                pdf_links = element.xpath(
                    ".//a[contains(@href, '.pdf')]/@href"
                )
                if not pdf_links:
                    continue

                pdf_url = urljoin(response.url, pdf_links[0])

                # Extract opinion number from PDF URL
                opinion_match = self.OPINION_NUMBER_PATTERN.search(pdf_url)
                if not opinion_match:
                    continue
                opinion_number = opinion_match.group(1)

                # Extract case name from paragraphs
                # The structure is: first p = opinion number, second p = case name
                paragraphs = element.xpath(".//p/text()")
                case_name = ""
                for p_text in paragraphs:
                    text = p_text.strip().strip('"')
                    # Skip the opinion number paragraph
                    if text == opinion_number:
                        continue
                    if text:
                        case_name = text
                        break

                if not case_name:
                    # Try getting text from first non-number paragraph
                    all_p = element.xpath(".//p")
                    for p in all_p:
                        text = p.text_content().strip().strip('"')
                        if text and text != opinion_number:
                            case_name = text
                            break

                if not case_name:
                    case_name = f"Opinion {opinion_number}"

                # Apply filters
                if (
                    opinion_number_filter
                    and opinion_number != opinion_number_filter
                ):
                    continue

                if current_date:
                    if date_gte and current_date < date_gte:
                        continue
                    if date_lte and current_date > date_lte:
                        continue

                # Build cluster data for accumulated_data
                cluster_data: dict[str, Any] = {
                    "opinion_number": opinion_number,
                    "court_id": court_id,
                    "case_name": case_name,
                    "date_filed": current_date.isoformat()
                    if current_date
                    else None,
                    "published": published,
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

        # Move to next request in queue
        if remaining_requests:
            next_req = remaining_requests[0]
            court_id, published, year, month = next_req
            url = self._build_listing_url(court_id, published, year, month)

            yield NavigatingRequest(
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url=url,
                ),
                continuation=self.parse_opinion_listing,
                accumulated_data={
                    "court_id": court_id,
                    "published": published,
                    "year": year,
                    "month": month,
                    "remaining_requests": remaining_requests[1:],
                    "opinion_number_filter": opinion_number_filter,
                    "date_gte": date_gte_str,
                    "date_lte": date_lte_str,
                },
            )

    # =========================================================================
    # PDF Download Handling
    # =========================================================================

    @step
    def handle_opinion_download(
        self,
        response: ArchiveResponse,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[SCOpinionCluster], None, None]:
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
    ) -> Generator[ScraperYield[SCOpinionCluster], None, None]:
        """Build and yield the final OpinionCluster with all PDFs downloaded."""
        opinions = []
        for i, op_data in enumerate(accumulated_data["opinions_data"]):
            local_path = accumulated_data["downloaded_paths"].get(i)
            opinions.append(
                SCOpinion(
                    download_url=op_data["download_url"],
                    type=op_data.get("type", "majority"),
                    local_path=local_path,
                )
            )

        date_filed = None
        if accumulated_data.get("date_filed"):
            date_filed = date.fromisoformat(accumulated_data["date_filed"])

        cluster = SCOpinionCluster(
            opinion_number=accumulated_data["opinion_number"],
            court_id=accumulated_data["court_id"],
            date_filed=date_filed,
            case_name=accumulated_data["case_name"],
            published=accumulated_data.get("published", True),
            opinions=opinions,
            source_url=accumulated_data.get("source_url"),
        )

        yield ParsedData(cluster)
