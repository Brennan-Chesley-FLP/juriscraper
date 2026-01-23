"""Utah Appellate Courts Opinion Scraper.

This module contains a unified scraper for opinions from Utah courts:
- Utah Supreme Court (utah)
- Utah Court of Appeals (utahctapp)

Entry points:
- Supreme Court: https://legacy.utcourts.gov/opinions/supopin/
- Court of Appeals: https://legacy.utcourts.gov/opinions/appopin/

Opinion listing format:
Each opinion appears as a paragraph with structure:
  <a href="{filename}.pdf">{Case Name}</a>, Case No. {case_number}, Filed {date}, {citation}

Example:
  <a href="State v. Macbeth20260115_20230512_3.pdf">State v. Macbeth</a>,
  Case No. 20230512-CA, Filed January 15, 2026, 2026 UT App 3

PDF URL pattern:
- {base_url}/{court_path}/{filename}.pdf
  - court_path: "supopin" for Supreme Court, "appopin" for Court of Appeals
  - filename: e.g., "State v. Macbeth20260115_20230512_3"

Flow:
  1. get_entry -> opinion listing page for selected courts
  2. parse_opinion_list -> extracts opinion metadata from paragraphs
  3. yields ArchiveRequests for PDFs
  4. handle_opinion_download -> stores local paths, yields final clusters

Design decisions:
- Uses restrictive checked_xpaths to catch structural changes early
- Uses DateRange filter on date_filed for searching
- Uses SetFilter on court_id to select which courts to scrape
- Archives opinion PDFs via ArchiveRequest
- Defaults to scraping both courts when no filter specified
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import TYPE_CHECKING, Any, ClassVar
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
    BASE_URL,
    COURT_IDS,
    COURT_TYPE_TO_PATH,
    UtahOpinion,
    UtahOpinionCluster,
)

if TYPE_CHECKING:
    from collections.abc import Generator

    from juriscraper.scraper_driver.data_types import ScraperYield


class UtahScraper(BaseScraper[UtahOpinionCluster]):
    """Unified scraper for Utah appellate court opinions.

    Scrapes opinions from Utah Supreme Court and Court of Appeals.

    Usage:
        # Scrape both courts (default)
        scraper = UtahScraper()

        # Scrape only Supreme Court
        params = UtahScraper.params()
        params.UtahOpinionCluster.court_id.values = {"utah"}
        scraper = UtahScraper(params=params)

        # Scrape only Court of Appeals
        params = UtahScraper.params()
        params.UtahOpinionCluster.court_id.values = {"utahctapp"}
        scraper = UtahScraper(params=params)

        # Filter by date range
        params = UtahScraper.params()
        params.UtahOpinionCluster.date_filed.gte = date(2026, 1, 1)
        params.UtahOpinionCluster.date_filed.lte = date(2026, 1, 31)
        scraper = UtahScraper(params=params)

        # Lookup specific citation
        params = UtahScraper.params()
        params.UtahOpinionCluster.citation.value = "2026 UT App 5"
        scraper = UtahScraper(params=params)
    """

    # === Metadata ===
    court_ids: ClassVar[set[str]] = COURT_IDS
    court_url: ClassVar[str] = "https://www.utcourts.gov/"
    data_types: ClassVar[set[str]] = {"opinions"}
    status: ClassVar[ScraperStatus] = ScraperStatus.IN_DEVELOPMENT
    version: ClassVar[str] = "2026-01-23"
    requires_auth: ClassVar[bool] = False

    # Rate limiting - be respectful to court servers
    msec_per_request_rate_limit: ClassVar[int] = 1000

    # === Regex patterns ===
    # Citation pattern: YYYY UT [App] NN
    CITATION_PATTERN = re.compile(r"(\d{4}\s+UT(?:\s+App)?\s+\d+)")

    # Case number pattern: YYYYMMDD-CA or just number
    CASE_NUMBER_PATTERN = re.compile(r"(\d{8}-CA|\d+-CA|\d+)")

    # Date pattern in text: "Filed Month DD, YYYY" or "Filed Month D, YYYY"
    DATE_PATTERN = re.compile(
        r"Filed\s+(\w+)\s+(\d{1,2}),?\s+(\d{4})", re.IGNORECASE
    )

    # Month name to number mapping
    MONTH_MAP: ClassVar[dict[str, int]] = {
        "january": 1,
        "february": 2,
        "march": 3,
        "april": 4,
        "may": 5,
        "june": 6,
        "july": 7,
        "august": 8,
        "september": 9,
        "october": 10,
        "november": 11,
        "december": 12,
    }

    def _parse_date(self, text: str) -> date | None:
        """Parse a date from text like 'Filed January 15, 2026'.

        Args:
            text: Text containing date information.

        Returns:
            Parsed date object, or None if parsing fails.
        """
        match = self.DATE_PATTERN.search(text)
        if not match:
            return None

        month_name = match.group(1).lower()
        day = int(match.group(2))
        year = int(match.group(3))

        month = self.MONTH_MAP.get(month_name)
        if not month:
            return None

        try:
            return date(year, month, day)
        except ValueError:
            return None

    def _get_opinions_search_params(
        self,
    ) -> tuple[date | None, date | None, str | None, set[str] | None]:
        """Extract search parameters for opinions from ScraperParams.

        Returns:
            Tuple of (date_gte, date_lte, citation, court_ids)
        """
        if self._params is None:
            return None, None, None, None

        try:
            model_proxy = self._params.UtahOpinionCluster
        except AttributeError:
            return None, None, None, None

        date_gte = None
        date_lte = None
        citation = None
        court_ids = None

        searchable = model_proxy.get_searchable_fields()

        date_field = searchable.get("date_filed")
        if date_field and date_field.is_set():
            date_gte = date_field.gte
            date_lte = date_field.lte

        citation_field = searchable.get("citation")
        if citation_field and citation_field.is_set():
            citation = citation_field.value

        court_field = searchable.get("court_id")
        if court_field and court_field.is_set():
            court_ids = court_field.values

        return date_gte, date_lte, citation, court_ids

    def _get_target_courts(self) -> list[str]:
        """Get the list of court IDs to scrape based on filters.

        Returns list of court IDs (utah, utahctapp).
        """
        _, _, _, court_ids = self._get_opinions_search_params()

        if court_ids:
            return sorted(court_ids & COURT_IDS)

        # Default: both courts
        return sorted(COURT_IDS)

    def _build_listing_url(self, court_id: str) -> str:
        """Build the opinion listing URL for a court.

        Args:
            court_id: The court identifier (utah or utahctapp)

        Returns:
            URL for the court's opinion listing page
        """
        path = COURT_TYPE_TO_PATH.get(court_id, "supopin")
        return f"{BASE_URL}/{path}/"

    # =========================================================================
    # Entry Point
    # =========================================================================

    def get_entry(self) -> Generator[NavigatingRequest, None, None]:
        """Yield initial requests for opinion scraping.

        Yields NavigatingRequests for each court to scrape.
        """
        courts = self._get_target_courts()
        date_gte, date_lte, citation, _ = self._get_opinions_search_params()

        if not courts:
            return

        first_court = courts[0]
        remaining_courts = courts[1:]

        url = self._build_listing_url(first_court)

        yield NavigatingRequest(
            request=HTTPRequestParams(
                method=HttpMethod.GET,
                url=url,
            ),
            continuation=self.parse_opinion_list,
            accumulated_data={
                "court_id": first_court,
                "remaining_courts": remaining_courts,
                "citation_filter": citation,
                "date_gte": date_gte.isoformat() if date_gte else None,
                "date_lte": date_lte.isoformat() if date_lte else None,
            },
        )

    # =========================================================================
    # Opinion List Parsing
    # =========================================================================

    @step(xsd="xsds/parse_opinion_list.xsd")
    def parse_opinion_list(
        self,
        lxml_tree: CheckedHtmlElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[UtahOpinionCluster], None, None]:
        """Parse the opinion listing page.

        Extracts opinion metadata from paragraphs and yields
        ArchiveRequests for each opinion PDF.

        Page structure:
        - Opinions listed as <p> elements containing:
          - <a href="{filename}.pdf">{Case Name}</a>
          - Text: ", Case No. {case_number}, Filed {date}, {citation}"
        """
        court_id = accumulated_data.get("court_id", "utah")
        remaining_courts = accumulated_data.get("remaining_courts", [])
        citation_filter = accumulated_data.get("citation_filter")
        date_gte_str = accumulated_data.get("date_gte")
        date_lte_str = accumulated_data.get("date_lte")

        date_gte = date.fromisoformat(date_gte_str) if date_gte_str else None
        date_lte = date.fromisoformat(date_lte_str) if date_lte_str else None

        # Find all paragraphs with PDF links
        # The opinion paragraphs are in a specific div after the separator
        opinion_paragraphs = lxml_tree.xpath(
            "//main//p[a[contains(@href, '.pdf')]]"
        )

        for para in opinion_paragraphs:
            # Get the PDF link
            pdf_links = para.xpath(".//a[contains(@href, '.pdf')]")
            if not pdf_links:
                continue

            pdf_link = pdf_links[0]
            pdf_href = pdf_link.get("href", "")
            pdf_url = urljoin(response.url, pdf_href)
            case_name = pdf_link.text_content().strip()

            if not case_name:
                continue

            # Get the full text of the paragraph for metadata extraction
            full_text = para.text_content()

            # Extract case number
            case_number = None
            case_match = self.CASE_NUMBER_PATTERN.search(full_text)
            if case_match:
                case_number = case_match.group(1)

            # Extract citation
            citation = None
            citation_match = self.CITATION_PATTERN.search(full_text)
            if citation_match:
                citation = citation_match.group(1)

            # Extract date filed
            date_filed = self._parse_date(full_text)

            if not citation:
                # Skip if no citation found
                continue

            if not case_number:
                # Try to extract from "Case No." text
                case_no_match = re.search(
                    r"Case\s+No\.?\s*(\S+)", full_text, re.IGNORECASE
                )
                if case_no_match:
                    case_number = case_no_match.group(1).rstrip(",")

            if not case_number:
                case_number = "Unknown"

            # Apply filters
            if citation_filter and citation != citation_filter:
                continue

            if date_filed:
                if date_gte and date_filed < date_gte:
                    continue
                if date_lte and date_filed > date_lte:
                    continue

            # Extract year from citation
            year = None
            year_match = re.match(r"(\d{4})", citation)
            if year_match:
                year = int(year_match.group(1))

            # Build cluster data for accumulated_data
            cluster_data: dict[str, Any] = {
                "citation": citation,
                "court_id": court_id,
                "case_name": case_name,
                "case_number": case_number,
                "date_filed": date_filed.isoformat() if date_filed else None,
                "year": year,
                "source_url": response.url,
                "opinions_data": [{"download_url": pdf_url, "type": "majority"}],
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

        # Move to next court after processing this one
        if remaining_courts:
            next_court = remaining_courts[0]
            url = self._build_listing_url(next_court)

            yield NavigatingRequest(
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url=url,
                ),
                continuation=self.parse_opinion_list,
                accumulated_data={
                    "court_id": next_court,
                    "remaining_courts": remaining_courts[1:],
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
    ) -> Generator[ScraperYield[UtahOpinionCluster], None, None]:
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
    ) -> Generator[ScraperYield[UtahOpinionCluster], None, None]:
        """Build and yield the final OpinionCluster with all PDFs downloaded."""
        opinions = []
        for i, op_data in enumerate(accumulated_data["opinions_data"]):
            local_path = accumulated_data["downloaded_paths"].get(i)
            opinions.append(
                UtahOpinion(
                    download_url=op_data["download_url"],
                    type=op_data.get("type", "majority"),
                    local_path=local_path,
                )
            )

        date_filed = None
        if accumulated_data.get("date_filed"):
            date_filed = date.fromisoformat(accumulated_data["date_filed"])

        cluster = UtahOpinionCluster(
            citation=accumulated_data["citation"],
            court_id=accumulated_data["court_id"],
            date_filed=date_filed,
            case_name=accumulated_data["case_name"],
            case_number=accumulated_data["case_number"],
            year=accumulated_data.get("year"),
            opinions=opinions,
            source_url=accumulated_data.get("source_url"),
        )

        yield ParsedData(cluster)
