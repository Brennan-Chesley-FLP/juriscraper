"""West Virginia Appellate Courts Opinion Scraper.

This module contains a unified scraper for opinions from West Virginia courts:
- Supreme Court of Appeals (wva)
- Intermediate Court of Appeals (wvactapp)

Entry points:
- SCA Current Term: https://www.courtswv.gov/appellate-courts/supreme-court-of-appeals/opinions
- SCA Prior Terms: https://www.courtswv.gov/appellate-courts/supreme-court-of-appeals/opinions/prior-terms
- ICA Current Term: https://www.courtswv.gov/appellate-courts/intermediate-court-of-appeals/opinions
- ICA Prior Terms: https://www.courtswv.gov/appellate-courts/intermediate-court-of-appeals/opinions/prior-terms

PDF URL patterns:
- SCA: /sites/default/pubfilesmnt/{YYYY-MM}/{case_no}%20{decision_type}.pdf
- ICA: /sites/default/pubfilesmnt/{YYYY-MM}/{case_no}_{decision_type}.pdf

The prior terms pages support pagination via ?page=N (0-indexed).

Flow:
  1. get_entry -> branch to SCA and/or ICA opinions pages based on court_id filter
  2. parse_opinions_page -> extracts opinion metadata from results table
  3. yields ArchiveRequests for PDFs
  4. handle_opinion_download -> stores local paths, yields final clusters
  5. handle_pagination -> follows pagination links for prior terms pages

Design decisions:
- Uses prior terms pages for comprehensive scraping (supports date/year filtering)
- Uses restrictive checked_xpaths to catch structural changes early
- Uses DateRange filter on date_filed for searching
- Uses SetFilter on court_id to select which courts to scrape
- Archives opinion PDFs via ArchiveRequest
- Supports pagination for bulk historical scraping
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
    CASE_TYPES,
    COURT_IDS,
    DECISION_TYPES,
    WVOpinion,
    WVOpinionCluster,
)

if TYPE_CHECKING:
    from collections.abc import Generator

    from kent.data_types import ScraperYield


class WestVirginiaScraper(BaseScraper[WVOpinionCluster]):
    """Unified scraper for West Virginia appellate court opinions.

    Scrapes opinions from West Virginia Supreme Court of Appeals (SCA)
    and Intermediate Court of Appeals (ICA).

    Usage:
        # Scrape both courts (default)
        scraper = WestVirginiaScraper()

        # Scrape only Supreme Court of Appeals
        params = WestVirginiaScraper.params()
        params.WVOpinionCluster.court_id.values = {"wva"}
        scraper = WestVirginiaScraper(params=params)

        # Scrape only Intermediate Court of Appeals
        params = WestVirginiaScraper.params()
        params.WVOpinionCluster.court_id.values = {"wvactapp"}
        scraper = WestVirginiaScraper(params=params)

        # Filter by date range
        params = WestVirginiaScraper.params()
        params.WVOpinionCluster.date_filed.gte = date(2026, 1, 1)
        params.WVOpinionCluster.date_filed.lte = date(2026, 1, 31)
        scraper = WestVirginiaScraper(params=params)

        # Lookup specific case number
        params = WestVirginiaScraper.params()
        params.WVOpinionCluster.case_number.value = "25-765"
        scraper = WestVirginiaScraper(params=params)
    """

    # === Metadata ===
    court_ids: ClassVar[set[str]] = COURT_IDS
    court_url: ClassVar[str] = "https://www.courtswv.gov/"
    data_types: ClassVar[set[str]] = {"opinions"}
    status: ClassVar[ScraperStatus] = ScraperStatus.IN_DEVELOPMENT
    version: ClassVar[str] = "2026-01-23"
    requires_auth: ClassVar[bool] = False

    # Rate limiting - be respectful to court servers
    msec_per_request_rate_limit: ClassVar[int] = 1000

    # Base URLs for opinion pages
    SCA_PRIOR_TERMS_URL = (
        "https://www.courtswv.gov/appellate-courts/"
        "supreme-court-of-appeals/opinions/prior-terms"
    )
    ICA_PRIOR_TERMS_URL = (
        "https://www.courtswv.gov/appellate-courts/"
        "intermediate-court-of-appeals/opinions/prior-terms"
    )

    # === Regex patterns ===
    # Date pattern: MM/DD/YYYY or M/D/YYYY
    DATE_PATTERN = re.compile(r"(\d{1,2}/\d{1,2}/\d{4})")

    # Expected table headers (same for both courts)
    EXPECTED_HEADERS = [
        "Date Filed",
        "Case No",
        "Case Name",
        "Case Type",
        "Decision Type",
    ]

    def _parse_date(self, date_str: str) -> date | None:
        """Parse a date string in MM/DD/YYYY format.

        Args:
            date_str: Date string in M/D/YYYY format.

        Returns:
            Parsed date object, or None if parsing fails.
        """
        try:
            return datetime.strptime(date_str.strip(), "%m/%d/%Y").date()
        except ValueError:
            return None

    def _get_opinions_search_params(
        self,
    ) -> tuple[date | None, date | None, str | None, set[str] | None]:
        """Extract search parameters for opinions from ScraperParams.

        Returns:
            Tuple of (date_gte, date_lte, case_number, court_ids)
        """
        if self._params is None:
            return None, None, None, None

        try:
            model_proxy = self._params.WVOpinionCluster
        except AttributeError:
            return None, None, None, None

        date_gte = None
        date_lte = None
        case_number = None
        court_ids = None

        searchable = model_proxy.get_searchable_fields()

        date_field = searchable.get("date_filed")
        if date_field and date_field.is_set():
            date_gte = date_field.gte
            date_lte = date_field.lte

        case_number_field = searchable.get("case_number")
        if case_number_field and case_number_field.is_set():
            case_number = case_number_field.value

        court_field = searchable.get("court_id")
        if court_field and court_field.is_set():
            court_ids = court_field.values

        return date_gte, date_lte, case_number, court_ids

    def _get_target_courts(self) -> list[str]:
        """Get the list of court IDs to scrape based on court_ids filter.

        Returns list of court IDs ('wva' for SCA, 'wvactapp' for ICA).
        """
        _, _, _, court_ids = self._get_opinions_search_params()

        if court_ids:
            # Filter to valid court IDs only
            valid_courts = [c for c in court_ids if c in COURT_IDS]
            return valid_courts if valid_courts else ["wva"]

        # Default: Both courts
        return ["wva", "wvactapp"]

    def _get_base_url_for_court(self, court_id: str) -> str:
        """Get the prior terms URL for a given court.

        Args:
            court_id: Court identifier ('wva' or 'wvactapp').

        Returns:
            Base URL for the prior terms page.
        """
        if court_id == "wvactapp":
            return self.ICA_PRIOR_TERMS_URL
        return self.SCA_PRIOR_TERMS_URL

    # =========================================================================
    # Entry Point
    # =========================================================================

    @entry(WVOpinionCluster)
    def get_entry(self) -> Generator[NavigatingRequest, None, None]:
        """Yield initial requests for opinion scraping.

        Branches to SCA and/or ICA based on court_id filter.
        Uses prior terms pages for comprehensive date-based scraping.
        """
        courts = self._get_target_courts()
        date_gte, date_lte, case_number, _ = self._get_opinions_search_params()

        for court_id in courts:
            base_url = self._get_base_url_for_court(court_id)

            yield NavigatingRequest(
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url=base_url,
                ),
                continuation=self.parse_opinions_page,
                accumulated_data={
                    "court_id": court_id,
                    "base_url": base_url,
                    "page": 0,
                    "case_number_filter": case_number,
                    "date_gte": date_gte.isoformat() if date_gte else None,
                    "date_lte": date_lte.isoformat() if date_lte else None,
                },
            )

    # =========================================================================
    # Opinion Page Parsing
    # =========================================================================

    @step(xsd="xsds/parse_opinions_page.xsd")
    def parse_opinions_page(
        self,
        lxml_tree: CheckedHtmlElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[WVOpinionCluster], None, None]:
        """Parse the opinions page (current term or prior terms).

        Extracts opinion metadata from the results table and yields
        ArchiveRequests for each opinion PDF.
        """
        court_id = accumulated_data.get("court_id", "wva")
        base_url = accumulated_data.get("base_url", self.SCA_PRIOR_TERMS_URL)
        current_page = accumulated_data.get("page", 0)
        case_number_filter = accumulated_data.get("case_number_filter")
        date_gte_str = accumulated_data.get("date_gte")
        date_lte_str = accumulated_data.get("date_lte")

        date_gte = date.fromisoformat(date_gte_str) if date_gte_str else None
        date_lte = date.fromisoformat(date_lte_str) if date_lte_str else None

        # Find all rows with PDF links in the table
        result_rows = lxml_tree.xpath(
            "//table//tr[td[.//a[contains(@href, '.pdf')]]]"
        )

        found_results = False

        for row in result_rows:
            cells = row.xpath("./td")
            if len(cells) < 5:
                continue

            # Extract data from each cell
            # Cell 0: Date Filed
            date_filed_text = cells[0].text_content().strip()
            date_filed = None
            if date_filed_text:
                date_match = self.DATE_PATTERN.search(date_filed_text)
                if date_match:
                    date_filed = self._parse_date(date_match.group(1))

            # Cell 1: Case No
            case_number = cells[1].text_content().strip() or None

            # Cell 2: Case Name (contains PDF link)
            case_name_cell = cells[2]
            pdf_links = case_name_cell.xpath(".//a[contains(@href, '.pdf')]")
            if not pdf_links:
                continue

            pdf_url = urljoin(response.url, pdf_links[0].get("href", ""))
            case_name = pdf_links[0].text_content().strip()

            # Cell 3: Case Type
            case_type = cells[3].text_content().strip() or None
            case_type_name = CASE_TYPES.get(case_type) if case_type else None

            # Cell 4: Decision Type
            decision_type = cells[4].text_content().strip() or None
            decision_type_name = (
                DECISION_TYPES.get(decision_type) if decision_type else None
            )

            if not case_number or not date_filed:
                continue  # Skip rows without essential data

            # Apply filters
            if case_number_filter and case_number != case_number_filter:
                continue

            if date_filed:
                if date_gte and date_filed < date_gte:
                    continue
                if date_lte and date_filed > date_lte:
                    continue

            found_results = True

            # Build cluster data for accumulated_data
            cluster_data: dict[str, Any] = {
                "case_number": case_number,
                "court_id": court_id,
                "case_name": case_name,
                "case_type": case_type,
                "case_type_name": case_type_name,
                "decision_type": decision_type,
                "decision_type_name": decision_type_name,
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

        # Handle pagination - check for "Next" link
        # The prior terms page uses pagination like ?page=1, ?page=2, etc.
        next_page_links = lxml_tree.xpath(
            "//nav[contains(@class, 'pagination')]//a[contains(text(), 'Next')]/@href"
        )

        if next_page_links and found_results:
            next_page_href = next_page_links[0]
            next_page_url = urljoin(response.url, next_page_href)

            yield NavigatingRequest(
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url=next_page_url,
                ),
                continuation=self.parse_opinions_page,
                accumulated_data={
                    "court_id": court_id,
                    "base_url": base_url,
                    "page": current_page + 1,
                    "case_number_filter": case_number_filter,
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
    ) -> Generator[ScraperYield[WVOpinionCluster], None, None]:
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
    ) -> Generator[ScraperYield[WVOpinionCluster], None, None]:
        """Build and yield the final OpinionCluster with all PDFs downloaded."""
        opinions = []
        for i, op_data in enumerate(accumulated_data["opinions_data"]):
            local_path = accumulated_data["downloaded_paths"].get(i)
            opinions.append(
                WVOpinion(
                    download_url=op_data["download_url"],
                    type=op_data.get("type", "majority"),
                    local_path=local_path,
                )
            )

        date_filed = None
        if accumulated_data.get("date_filed"):
            date_filed = date.fromisoformat(accumulated_data["date_filed"])

        cluster = WVOpinionCluster(
            case_number=accumulated_data["case_number"],
            court_id=accumulated_data["court_id"],
            date_filed=date_filed,
            case_name=accumulated_data["case_name"],
            case_type=accumulated_data.get("case_type"),
            case_type_name=accumulated_data.get("case_type_name"),
            decision_type=accumulated_data.get("decision_type"),
            decision_type_name=accumulated_data.get("decision_type_name"),
            opinions=opinions,
            source_url=accumulated_data.get("source_url"),
        )

        yield ParsedData(cluster)
