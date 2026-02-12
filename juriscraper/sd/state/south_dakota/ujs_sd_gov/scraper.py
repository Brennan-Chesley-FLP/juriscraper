"""South Dakota Supreme Court Opinion Scraper.

This module contains a scraper for opinions from the South Dakota Supreme Court.

Entry point:
- https://ujs.sd.gov/supreme-court/opinions/

URL patterns:
- Opinion list: https://ujs.sd.gov/supreme-court/opinions/
- With year filter: https://ujs.sd.gov/supreme-court/opinions/?year=2025
- With pagination: https://ujs.sd.gov/supreme-court/opinions/?year=2025&page=2
- PDF: https://ujs.sd.gov/media/{hash}/{case_number}.pdf

Flow:
  1. get_entry -> opinion list page (optionally filtered by year)
  2. parse_opinions_list -> extracts opinion metadata from results table
  3. yields ArchiveRequests for PDFs
  4. handle_opinion_download -> stores local paths, yields final clusters

Design decisions:
- Uses year-based filtering via URL parameters for date range searches
- Supports DateRange filter on date_filed to select year
- Archives opinion PDFs via ArchiveRequest
- Handles pagination automatically via "Next" links
- South Dakota only has one appellate court (Supreme Court)
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import TYPE_CHECKING, Any, ClassVar
from urllib.parse import urljoin

from kent.common.checked_html import CheckedHtmlElement
from kent.common.decorators import entry, step
from kent.data_types import (
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
    COURT_ID,
    SouthDakotaOpinion,
    SouthDakotaOpinionCluster,
    extract_case_number_from_url,
    parse_citation,
)

if TYPE_CHECKING:
    from collections.abc import Generator

    from kent.data_types import ScraperYield


class SouthDakotaScraper(BaseScraper[SouthDakotaOpinionCluster]):
    """Scraper for South Dakota Supreme Court opinions.

    Scrapes published opinions from the South Dakota Unified Judicial System.

    Usage:
        # Scrape current year (default)
        scraper = SouthDakotaScraper()

        # Filter by date range (uses year filtering)
        params = SouthDakotaScraper.params()
        params.SouthDakotaOpinionCluster.date_filed.gte = date(2025, 1, 1)
        params.SouthDakotaOpinionCluster.date_filed.lte = date(2025, 12, 31)
        scraper = SouthDakotaScraper(params=params)

        # Lookup specific citation
        params = SouthDakotaScraper.params()
        params.SouthDakotaOpinionCluster.citation.value = "2026 S.D. 2"
        scraper = SouthDakotaScraper(params=params)
    """

    # === Metadata ===
    court_ids: ClassVar[set[str]] = {COURT_ID}
    court_url: ClassVar[str] = "https://ujs.sd.gov/supreme-court/"
    data_types: ClassVar[set[str]] = {"opinions"}
    status: ClassVar[ScraperStatus] = ScraperStatus.IN_DEVELOPMENT
    version: ClassVar[str] = "2026-01-23"
    requires_auth: ClassVar[bool] = False

    # Rate limiting - be respectful to court servers
    msec_per_request_rate_limit: ClassVar[int] = 1000

    # Base URL for opinion search
    OPINIONS_URL = "https://ujs.sd.gov/supreme-court/opinions/"

    # Date pattern: M/D/YYYY or MM/DD/YYYY
    DATE_PATTERN = re.compile(r"(\d{1,2}/\d{1,2}/\d{4})")

    # Expected table headers
    EXPECTED_HEADERS = ["Date", "Title", "Number"]

    def _parse_date(self, date_str: str) -> date | None:
        """Parse a date string in M/D/YYYY format.

        Args:
            date_str: Date string in M/D/YYYY format.

        Returns:
            Parsed date object, or None if parsing fails.
        """
        try:
            return datetime.strptime(date_str.strip(), "%m/%d/%Y").date()
        except ValueError:
            return None

    def _get_search_params(
        self,
    ) -> tuple[date | None, date | None, str | None]:
        """Extract search parameters from ScraperParams.

        Returns:
            Tuple of (date_gte, date_lte, citation_filter)
        """
        if self._params is None:
            return None, None, None

        try:
            model_proxy = self._params.SouthDakotaOpinionCluster
        except AttributeError:
            return None, None, None

        date_gte = None
        date_lte = None
        citation_filter = None

        searchable = model_proxy.get_searchable_fields()

        date_field = searchable.get("date_filed")
        if date_field and date_field.is_set():
            date_gte = date_field.gte
            date_lte = date_field.lte

        citation_field = searchable.get("citation")
        if citation_field and citation_field.is_set():
            citation_filter = citation_field.value

        return date_gte, date_lte, citation_filter

    def _get_target_years(self) -> list[int]:
        """Get the list of years to scrape based on date filters.

        Returns list of years to query. Uses year parameter in URL.
        """
        date_gte, date_lte, citation_filter = self._get_search_params()

        # If searching for a specific citation, extract year from it
        if citation_filter:
            match = re.match(r"(\d{4})\s+S\.?D\.?", citation_filter)
            if match:
                return [int(match.group(1))]

        current_year = date.today().year

        if date_gte and date_lte:
            # Get all years in the range
            start_year = date_gte.year
            end_year = date_lte.year
            return list(range(start_year, end_year + 1))
        elif date_gte:
            # From start year to current year
            return list(range(date_gte.year, current_year + 1))
        elif date_lte:
            # Just the end year (can't go back indefinitely)
            return [date_lte.year]

        # Default: current year only
        return [current_year]

    def _build_url(
        self, year: int | None = None, page: int | None = None
    ) -> str:
        """Build the opinions URL with optional year and page parameters."""
        params = []
        if year:
            params.append(f"year={year}")
        if page and page > 1:
            params.append(f"page={page}")

        if params:
            return f"{self.OPINIONS_URL}?{'&'.join(params)}"
        return self.OPINIONS_URL

    # =========================================================================
    # Entry Point
    # =========================================================================

    @entry(SouthDakotaOpinionCluster)
    def get_entry(self) -> Generator[NavigatingRequest, None, None]:
        """Yield initial requests for opinion scraping.

        Yields separate NavigatingRequests for each year to scrape.
        """
        years = self._get_target_years()
        date_gte, date_lte, citation_filter = self._get_search_params()

        first_year = years[0]
        remaining_years = years[1:]

        url = self._build_url(year=first_year)

        yield NavigatingRequest(
            request=HTTPRequestParams(
                method=HttpMethod.GET,
                url=url,
            ),
            continuation=self.parse_opinions_list,
            accumulated_data={
                "year": first_year,
                "remaining_years": remaining_years,
                "citation_filter": citation_filter,
                "date_gte": date_gte.isoformat() if date_gte else None,
                "date_lte": date_lte.isoformat() if date_lte else None,
            },
        )

    # =========================================================================
    # Opinion List Parsing
    # =========================================================================

    @step(xsd="xsds/parse_opinions_list.xsd")
    def parse_opinions_list(
        self,
        lxml_tree: CheckedHtmlElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[SouthDakotaOpinionCluster], None, None]:
        """Parse the opinion list page.

        Extracts opinion metadata from the results table and yields
        ArchiveRequests for each opinion PDF.
        """
        year = accumulated_data.get("year")
        remaining_years = accumulated_data.get("remaining_years", [])
        citation_filter = accumulated_data.get("citation_filter")
        date_gte_str = accumulated_data.get("date_gte")
        date_lte_str = accumulated_data.get("date_lte")

        date_gte = date.fromisoformat(date_gte_str) if date_gte_str else None
        date_lte = date.fromisoformat(date_lte_str) if date_lte_str else None

        # Find the results table rows
        # Table structure: Date | Title (with link) | Number
        result_rows = lxml_tree.xpath(
            "//table//tr[td[.//a[contains(@href, '.pdf')]]]"
        )

        for row in result_rows:
            cells = row.xpath("./td")
            if len(cells) < 3:
                continue

            # Cell 0: Date
            date_text = cells[0].text_content().strip()
            date_filed = self._parse_date(date_text)

            # Cell 1: Title (contains link to PDF)
            title_cell = cells[1]
            pdf_links = title_cell.xpath(".//a[contains(@href, '.pdf')]")
            if not pdf_links:
                continue

            pdf_href = pdf_links[0].get("href", "")
            pdf_url = urljoin(response.url, pdf_href)
            full_title = pdf_links[0].text_content().strip()

            # Parse case name and citation from title
            case_name, citation, opinion_number = parse_citation(full_title)

            if not citation:
                # Skip if we can't parse citation
                continue

            # Cell 2: Number (just the sequential number, same as opinion_number)
            # This is redundant with the citation but validates our parsing

            # Extract case number from PDF URL
            case_number = extract_case_number_from_url(pdf_url)

            # Apply filters
            if citation_filter and citation != citation_filter:
                continue

            if date_filed:
                if date_gte and date_filed < date_gte:
                    continue
                if date_lte and date_filed > date_lte:
                    continue

            # Build cluster data for accumulated_data
            cluster_data: dict[str, Any] = {
                "citation": citation,
                "court_id": COURT_ID,
                "case_name": case_name,
                "case_number": case_number,
                "opinion_number": opinion_number,
                "date_filed": date_filed.isoformat() if date_filed else None,
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

        # Check for "Next" pagination link
        next_links = lxml_tree.xpath(
            "//nav[@aria-label='Pagination']//a[contains(text(), 'Next')]/@href"
        )
        if next_links:
            next_url = urljoin(response.url, next_links[0])
            yield NavigatingRequest(
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url=next_url,
                ),
                continuation=self.parse_opinions_list,
                accumulated_data={
                    "year": year,
                    "remaining_years": remaining_years,
                    "citation_filter": citation_filter,
                    "date_gte": date_gte_str,
                    "date_lte": date_lte_str,
                },
            )
        elif remaining_years:
            # Move to next year after exhausting current year's pages
            next_year = remaining_years[0]
            url = self._build_url(year=next_year)

            yield NavigatingRequest(
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url=url,
                ),
                continuation=self.parse_opinions_list,
                accumulated_data={
                    "year": next_year,
                    "remaining_years": remaining_years[1:],
                    "citation_filter": citation_filter,
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
    ) -> Generator[ScraperYield[SouthDakotaOpinionCluster], None, None]:
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
    ) -> Generator[ScraperYield[SouthDakotaOpinionCluster], None, None]:
        """Build and yield the final OpinionCluster with all PDFs downloaded."""
        opinions = []
        for i, op_data in enumerate(accumulated_data["opinions_data"]):
            local_path = accumulated_data["downloaded_paths"].get(i)
            opinions.append(
                SouthDakotaOpinion(
                    download_url=op_data["download_url"],
                    type=op_data.get("type", "majority"),
                    local_path=local_path,
                )
            )

        date_filed = None
        if accumulated_data.get("date_filed"):
            date_filed = date.fromisoformat(accumulated_data["date_filed"])

        cluster = SouthDakotaOpinionCluster(
            citation=accumulated_data["citation"],
            court_id=accumulated_data["court_id"],
            date_filed=date_filed,
            case_name=accumulated_data["case_name"],
            case_number=accumulated_data.get("case_number"),
            opinion_number=accumulated_data.get("opinion_number"),
            opinions=opinions,
            source_url=accumulated_data.get("source_url"),
        )

        yield ParsedData(cluster)
