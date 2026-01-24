"""Colorado Appellate Courts Scraper.

This module contains a scraper for opinions from the Colorado Supreme Court
and Court of Appeals using the Colorado Judicial Branch website.

Entry points::

    - Supreme Court Slip Opinions: https://www.coloradojudicial.gov/supreme-court/opinions
    - Case Law Search (both courts): https://research.coloradojudicial.gov/

Opinions Flow::

    1. get_entry -> slip opinions page for Supreme Court
    2. parse_slip_opinions_page -> parses opinions list, yields requests to detail pages
    3. parse_opinion_detail_page -> extracts PDF URL, yields ArchiveRequest
    4. handle_opinion_download -> yields final ColoradoOpinionCluster

Design decisions::

    - Uses restrictive checked_xpaths to catch structural changes early
    - Uses DateRange filter on date_filed for searching
    - Uses SetFilter on court_id to select which courts to scrape
    - Downloads all PDFs via ArchiveRequest
    - Currently only scrapes Supreme Court slip opinions (current fiscal year)
    - Court of Appeals opinions are available via Case Law Search but require
      additional implementation for the vLex-powered interface
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
    ColoradoOpinion,
    ColoradoOpinionCluster,
)

if TYPE_CHECKING:
    from collections.abc import Generator

    from juriscraper.scraper_driver.data_types import ScraperYield


# Court configuration
OPINIONS_CONFIG = {
    "colo": {
        "name": "Colorado Supreme Court",
        "slip_opinions_url": "https://www.coloradojudicial.gov/supreme-court/opinions",
        "docket_prefixes": {"SC", "SA"},
    },
    "coloctapp": {
        "name": "Colorado Court of Appeals",
        # Court of Appeals slip opinions are on Case Law Search
        "case_law_search_url": "https://research.coloradojudicial.gov/search/jurisdiction:US+content_type:2+court:14024_02/*",
        "docket_prefixes": {"CA"},
    },
}


class ColoradoScraper(BaseScraper[ColoradoOpinionCluster]):
    """Scraper for Colorado appellate court opinions.

    Scrapes opinions from the Colorado Supreme Court and Court of Appeals.
    Currently supports Supreme Court slip opinions from coloradojudicial.gov.

    Usage:
        # Scrape Supreme Court opinions (default)
        scraper = ColoradoScraper()

        # Filter by court
        params = ColoradoScraper.params()
        params.ColoradoOpinionCluster.court_id.values = {"colo"}
        scraper = ColoradoScraper(params=params)

        # Filter by date range
        params = ColoradoScraper.params()
        params.ColoradoOpinionCluster.date_filed.gte = date(2025, 12, 1)
        params.ColoradoOpinionCluster.date_filed.lte = date(2025, 12, 31)
        scraper = ColoradoScraper(params=params)
    """

    # === Metadata ===
    court_ids: ClassVar[set[str]] = {"colo", "coloctapp"}
    court_url: ClassVar[str] = "https://www.coloradojudicial.gov/"
    data_types: ClassVar[set[str]] = {"opinions"}
    status: ClassVar[ScraperStatus] = ScraperStatus.IN_DEVELOPMENT
    version: ClassVar[str] = "2026-01-22"
    requires_auth: ClassVar[bool] = False

    # Rate limiting - be respectful to court servers
    msec_per_request_rate_limit: ClassVar[int] = 1000

    # === Regex patterns ===
    # Citation pattern: "2025 CO 63" or "2025 CO 63M" (modified) or "26 CO 1"
    CITATION_PATTERN = re.compile(
        r"(\d{2,4})\s+CO\s+(\d+)(M)?",
        re.IGNORECASE,
    )
    # Docket pattern: "25SC347", "23SC847", "25SA204", "24CA1951"
    DOCKET_PATTERN = re.compile(
        r"(\d{2})(SC|SA|CA)(\d+)",
        re.IGNORECASE,
    )
    # Date pattern for parsing: "January 12, 2026" or "December 15, 2025"
    DATE_PATTERN = re.compile(
        r"(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{1,2}),?\s+(\d{4})",
        re.IGNORECASE,
    )

    # Mapping from model name to data type
    MODEL_TO_DATA_TYPE: ClassVar[dict[str, str]] = {
        "ColoradoOpinionCluster": "opinions",
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
            model_proxy = self._params.ColoradoOpinionCluster
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

    def _get_target_courts(self) -> set[str]:
        """Get the set of court IDs to scrape."""
        _, _, _, court_ids = self._get_search_params()
        if court_ids:
            valid_courts = court_ids & set(OPINIONS_CONFIG.keys())
            if valid_courts:
                return valid_courts
        return set(OPINIONS_CONFIG.keys())

    # =========================================================================
    # Entry Point
    # =========================================================================

    def get_entry(self) -> Generator[NavigatingRequest, None, None]:
        """Yield initial requests for opinions scraping.

        Currently only yields request for Supreme Court slip opinions.
        Court of Appeals opinions would require additional implementation
        for the vLex-powered Case Law Search interface.
        """
        requested = self._get_requested_data_types()

        if "opinions" not in requested:
            return

        target_courts = self._get_target_courts()

        # Supreme Court slip opinions
        if "colo" in target_courts:
            slip_url = OPINIONS_CONFIG["colo"]["slip_opinions_url"]
            assert isinstance(slip_url, str)
            yield NavigatingRequest(
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url=slip_url,
                ),
                continuation=self.parse_slip_opinions_page,
                accumulated_data={
                    "court_id": "colo",
                },
            )

        # Note: Court of Appeals would need Case Law Search implementation
        # which uses a vLex-powered JavaScript interface

    # =========================================================================
    # Slip Opinions Scraping Steps
    # =========================================================================

    @step(xsd="xsds/parse_slip_opinions_page.xsd")
    def parse_slip_opinions_page(
        self,
        lxml_tree: CheckedHtmlElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[ColoradoOpinionCluster], None, None]:
        """Parse the Supreme Court slip opinions page.

        The page structure is::

            - Date headers as plain text in paragraphs (e.g., "January 12, 2026")
            - Opinion entries in paragraphs with:

              - Citation link (e.g., "26 CO 1" linking to /node/15606)
              - Docket number text (e.g., ", 25SA204,")
              - Case name in <em> tags (e.g., "In re: Interest of B.J.S.")

            - Horizontal rules (<hr>) separate date groups
        """
        court_id = accumulated_data.get("court_id", "colo")
        date_gte, date_lte, target_docket, _ = self._get_search_params()

        # Get the main content area
        content_area = lxml_tree.checked_xpath(
            "//article//div[contains(@class, 'field')]",
            "main content area",
            min_count=1,
        )

        # Find all paragraph elements that could contain opinions or dates
        paragraphs = content_area[0].checked_xpath(
            ".//p",
            "content paragraphs",
            min_count=1,
        )

        current_date: date | None = None
        opinions_by_date: dict[date, list[dict[str, Any]]] = {}

        for para in paragraphs:
            para_text = para.text_content().strip()

            # Check if this is a date header
            date_match = self.DATE_PATTERN.match(para_text)
            if date_match:
                month_name = date_match.group(1)
                day = int(date_match.group(2))
                year = int(date_match.group(3))
                try:
                    current_date = datetime.strptime(
                        f"{month_name} {day} {year}", "%B %d %Y"
                    ).date()
                except ValueError:
                    current_date = None
                continue

            if current_date is None:
                continue

            # Apply date filters
            if date_gte and current_date < date_gte:
                continue
            if date_lte and current_date > date_lte:
                continue

            # Look for citation links in this paragraph
            citation_links = para.checked_xpath(
                ".//a[contains(@href, '/node/') or contains(@href, '/media/')]",
                "citation links",
                min_count=0,
            )

            if not citation_links:
                continue

            # Process each citation link in the paragraph
            for link in citation_links:
                link_text = link.text_content().strip()
                href = link.get("href", "")

                # Match citation format
                citation_match = self.CITATION_PATTERN.match(link_text)
                if not citation_match:
                    continue

                citation_year = citation_match.group(1)
                citation_num = citation_match.group(2)
                is_modified = citation_match.group(3) is not None

                # Build full citation
                if len(citation_year) == 2:
                    full_year = f"20{citation_year}"
                else:
                    full_year = citation_year
                citation = f"{full_year} CO {citation_num}"
                if is_modified:
                    citation += "M"

                # Extract node ID from href
                node_id = None
                if "/node/" in href:
                    node_id = href.split("/node/")[-1]
                elif "/media/" in href:
                    node_id = href.split("/media/")[-1]

                # Get the full paragraph text to extract docket and case name
                full_text = para.text_content()

                # Find docket number after this citation
                # Pattern: citation text followed by ", docket_number,"
                docket_number = None
                docket_match = self.DOCKET_PATTERN.search(full_text)
                if docket_match:
                    docket_year = docket_match.group(1)
                    docket_prefix = docket_match.group(2).upper()
                    docket_seq = docket_match.group(3)
                    docket_number = f"{docket_year}{docket_prefix}{docket_seq}"

                    # Skip if doesn't match target docket
                    if target_docket and docket_number != target_docket:
                        continue

                # Extract case name from <em> tags
                case_name = "Unknown"
                em_elements = para.checked_xpath(
                    ".//em | .//i",
                    "case name emphasis",
                    min_count=0,
                )
                if em_elements:
                    case_name = em_elements[0].text_content().strip()

                # Build detail page URL
                detail_url = urljoin(response.url, href)

                opinion_data = {
                    "citation": citation,
                    "docket_number": docket_number,
                    "case_name": case_name,
                    "date_filed": current_date,
                    "detail_url": detail_url,
                    "node_id": node_id,
                    "is_modified": is_modified,
                    "court_id": court_id,
                }

                if current_date not in opinions_by_date:
                    opinions_by_date[current_date] = []
                opinions_by_date[current_date].append(opinion_data)

        # Yield requests for each opinion detail page
        for _pub_date, opinions in opinions_by_date.items():
            for opinion_data in opinions:
                yield NavigatingRequest(
                    request=HTTPRequestParams(
                        method=HttpMethod.GET,
                        url=opinion_data["detail_url"],
                    ),
                    continuation=self.parse_opinion_detail_page,
                    accumulated_data={
                        **opinion_data,
                        "source_url": response.url,
                    },
                )

    @step(xsd="xsds/parse_opinion_detail_page.xsd")
    def parse_opinion_detail_page(
        self,
        lxml_tree: CheckedHtmlElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[ColoradoOpinionCluster], None, None]:
        """Parse an opinion detail page to extract the PDF URL.

        The detail page structure:
        - Title: docket number (e.g., "23SC847")
        - PDF link: /system/files/opinions-{year}-{month}/{docket}.pdf
        """
        # Find the PDF link
        pdf_links = lxml_tree.checked_xpath(
            "//a[contains(@href, '.pdf')]",
            "PDF download link",
            min_count=1,
        )

        pdf_href = pdf_links[0].get("href", "")
        pdf_url = urljoin(response.url, pdf_href)

        # Yield archive request for the PDF
        yield ArchiveRequest(
            request=HTTPRequestParams(
                method=HttpMethod.GET,
                url=pdf_url,
            ),
            continuation=self.handle_opinion_download,
            expected_type="pdf",
            accumulated_data={
                **accumulated_data,
                "pdf_url": pdf_url,
            },
        )

    @step
    def handle_opinion_download(
        self,
        response: ArchiveResponse,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[ColoradoOpinionCluster], None, None]:
        """Handle a downloaded opinion PDF and yield the final cluster."""
        # Build the opinion object
        opinion = ColoradoOpinion(
            download_url=accumulated_data["pdf_url"],
            type="majority",
            local_path=response.file_url,
        )

        # Build the cluster
        cluster = ColoradoOpinionCluster(
            docket_number=accumulated_data.get("docket_number", "Unknown"),
            court_id=accumulated_data.get("court_id", "colo"),
            date_filed=accumulated_data["date_filed"],
            case_name=accumulated_data.get("case_name", "Unknown"),
            citation=accumulated_data.get("citation"),
            opinions=[opinion],
            source_url=accumulated_data.get("source_url"),
            node_id=accumulated_data.get("node_id"),
            is_modified=accumulated_data.get("is_modified", False),
            precedential_status="Published",
        )

        yield ParsedData(cluster)
