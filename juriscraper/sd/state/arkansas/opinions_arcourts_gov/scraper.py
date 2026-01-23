"""Arkansas Appellate Courts Opinions Scraper.

This module contains a unified scraper for opinions from Arkansas appellate courts:
- Arkansas Supreme Court (ark)
- Arkansas Court of Appeals (arkctapp)

The scraper uses the Lexum/Norma platform at https://opinions.arcourts.gov/

Entry points:
- Opinions are accessed via speculative ID probing
- Item URLs: https://opinions.arcourts.gov/ark/{court}/en/item/{id}/index.do
- PDF URLs: https://opinions.arcourts.gov/ark/{court}/en/{id}/1/document.do

Design decisions:
- Uses SpeculativeRequest to probe item IDs (sequential integers)
- Parses HTML pages for case metadata (no API available)
- Archives opinion PDFs via ArchiveRequest
- Filters syllabi (weekly summaries) by checking title prefix
- Supports both Supreme Court and Court of Appeals via court_id filter
"""

from __future__ import annotations

import re
from datetime import date
from typing import TYPE_CHECKING, ClassVar

from juriscraper.scraper_driver.common.checked_html import CheckedHtmlElement
from juriscraper.scraper_driver.common.decorators import step
from juriscraper.scraper_driver.data_types import (
    ArchiveRequest,
    ArchiveResponse,
    BaseScraper,
    HttpMethod,
    HTTPRequestParams,
    ParsedData,
    Response,
    ScraperStatus,
    SpeculativeRequest,
)

from .models import (
    BASE_PATH,
    BASE_URL,
    COURT_CONFIG,
    ArkOpinion,
    ArkOpinionCluster,
)

if TYPE_CHECKING:
    from collections.abc import Generator

    from juriscraper.scraper_driver.data_types import ScraperYield


class ArkansasScraper(BaseScraper[ArkOpinionCluster]):
    """Unified scraper for Arkansas appellate court opinions.

    Scrapes opinions from the Arkansas Supreme Court (ark) and
    Court of Appeals (arkctapp) from the Lexum/Norma platform.

    Uses speculative ID probing to discover opinions since the platform
    uses sequential integer IDs for items.

    Usage:
        # Scrape all courts
        scraper = ArkansasScraper()

        # Scrape only Supreme Court
        params = ArkansasScraper.params()
        params.ArkOpinionCluster.court_id.values = {"ark"}
        scraper = ArkansasScraper(params=params)

        # Scrape only Court of Appeals
        params = ArkansasScraper.params()
        params.ArkOpinionCluster.court_id.values = {"arkctapp"}
        scraper = ArkansasScraper(params=params)

        # Filter by date range
        params = ArkansasScraper.params()
        params.ArkOpinionCluster.date_filed.gte = date(2025, 1, 1)
        params.ArkOpinionCluster.date_filed.lte = date(2025, 12, 31)
        scraper = ArkansasScraper(params=params)

        # Start from a specific item ID
        params = ArkansasScraper.params()
        params.ArkOpinionCluster.item_id.gt = 520000
        scraper = ArkansasScraper(params=params)
    """

    # === Metadata ===
    court_ids: ClassVar[set[str]] = {"ark", "arkctapp"}
    court_url: ClassVar[str] = "https://opinions.arcourts.gov/"
    data_types: ClassVar[set[str]] = {"opinions"}
    status: ClassVar[ScraperStatus] = ScraperStatus.IN_DEVELOPMENT
    version: ClassVar[str] = "2026-01-22"
    requires_auth: ClassVar[bool] = False

    # Rate limiting - be respectful to court servers
    msec_per_request_rate_limit: ClassVar[int] = 2000

    # === Starting ID ===
    # Starting ID for speculative probing - this is a recent ID
    # Historical data goes back to much lower IDs
    DEFAULT_START_ID: ClassVar[int] = 524000

    # === Regex patterns ===
    # Pattern to extract item ID from URL
    ITEM_ID_PATTERN = re.compile(r"/item/(\d+)/")

    # Pattern to parse heading: "CASE NAME - CITATION - DATE"
    # Examples:
    # "JONATHAN ROLFE v. STATE OF ARKANSAS - 2026 Ark. 4 - 01/22/2026"
    # "2026-01-22.SYLLABUS - 01/22/2026" (syllabus - no citation)
    HEADING_PATTERN = re.compile(
        r"^(?P<case_name>.+?)"
        r"(?:\s*-\s*(?P<citation>\d{4}\s+Ark\.(?:\s+App\.)?\s+\d+))?"
        r"\s*-\s*(?P<date>\d{2}/\d{2}/\d{4})$"
    )

    # Date pattern for parsing
    DATE_PATTERN = re.compile(r"(\d{2})/(\d{2})/(\d{4})")

    def _get_search_params(
        self,
    ) -> tuple[date | None, date | None, int | None, set[str] | None]:
        """Extract search parameters from ScraperParams.

        Returns:
            Tuple of (date_gte, date_lte, start_id, court_ids)
        """
        if self._params is None:
            return None, None, None, None

        try:
            model_proxy = self._params.ArkOpinionCluster
        except AttributeError:
            return None, None, None, None

        date_gte = None
        date_lte = None
        start_id = None
        court_ids = None

        searchable = model_proxy.get_searchable_fields()

        date_field = searchable.get("date_filed")
        if date_field and date_field.is_set():
            date_gte = date_field.gte
            date_lte = date_field.lte

        id_field = searchable.get("item_id")
        if id_field and id_field.is_set():
            start_id = id_field.gt

        court_field = searchable.get("court_id")
        if court_field and court_field.is_set():
            court_ids = court_field.values

        return date_gte, date_lte, start_id, court_ids

    def _get_target_courts(self) -> set[str]:
        """Get the set of court IDs to scrape."""
        _, _, _, court_ids = self._get_search_params()

        if court_ids:
            valid_courts = court_ids & set(COURT_CONFIG.keys())
            if valid_courts:
                return valid_courts

        return set(COURT_CONFIG.keys())

    def _parse_date(self, date_str: str) -> date | None:
        """Parse date from MM/DD/YYYY format.

        Args:
            date_str: Date string in MM/DD/YYYY format.

        Returns:
            Parsed date object, or None if parsing fails.
        """
        match = self.DATE_PATTERN.match(date_str)
        if not match:
            return None

        try:
            month = int(match.group(1))
            day = int(match.group(2))
            year = int(match.group(3))
            return date(year, month, day)
        except (ValueError, IndexError):
            return None

    def _is_syllabus(self, case_name: str) -> bool:
        """Check if this is a syllabus entry (not an opinion).

        Syllabi are weekly summaries, not actual opinions.
        They have titles like "2026-01-22.SYLLABUS".

        Args:
            case_name: The case name/title.

        Returns:
            True if this is a syllabus entry.
        """
        return "SYLLABUS" in case_name.upper()

    def _determine_court_id(self, url_path: str) -> str | None:
        """Determine court_id from URL path.

        Args:
            url_path: The URL path containing court identifier.

        Returns:
            Court ID ('ark' or 'arkctapp') or None if not found.
        """
        for court_id, config in COURT_CONFIG.items():
            if config["url_path"] in url_path:
                return court_id
        return None

    # =========================================================================
    # Entry Point
    # =========================================================================

    @step()
    def get_entry(
        self,
    ) -> Generator[ScraperYield[ArkOpinionCluster], bool | None, None]:
        """Yield speculative requests to probe for opinions.

        Uses SpeculativeRequest to probe item IDs. The Lexum platform
        uses sequential integer IDs, so we probe incrementally.
        """
        target_courts = self._get_target_courts()
        _, _, start_id, _ = self._get_search_params()

        # Use provided start_id or default
        current_id = start_id if start_id else self.DEFAULT_START_ID

        # Probe each court
        for court_id in sorted(target_courts):
            config = COURT_CONFIG[court_id]
            url_path = config["url_path"]

            # Use speculative requests to probe IDs
            probe_id = current_id
            while True:
                item_url = f"{BASE_URL}{BASE_PATH}/{url_path}/en/item/{probe_id}/index.do"

                should_continue = yield SpeculativeRequest(
                    request=HTTPRequestParams(
                        method=HttpMethod.GET,
                        url=item_url,
                    ),
                    continuation=self.parse_item_page,
                    accumulated_data={
                        "court_id": court_id,
                        "item_id": probe_id,
                        "speculative_id": {
                            "ArkOpinionCluster": {"item_id": probe_id}
                        },
                    },
                )

                if not should_continue:
                    # No more items found, stop probing this court
                    break

                probe_id += 1

    # =========================================================================
    # Opinion Scraping Steps
    # =========================================================================

    @step()
    def parse_item_page(
        self,
        lxml_tree: CheckedHtmlElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[ArkOpinionCluster], None, None]:
        """Parse an opinion item page and yield ArchiveRequest for PDF.

        The item page contains:
        - Case name (h1 or h2 heading)
        - Citation (in heading or metadata)
        - Date filed
        - Opinion type (e.g., "Supreme Court - Majority")
        - Court term
        - PDF download link

        Args:
            lxml_tree: Parsed HTML tree
            response: HTTP response
            accumulated_data: Contains court_id and item_id
        """
        court_id = accumulated_data.get("court_id", "")
        item_id = accumulated_data.get("item_id", 0)

        # Get date filter parameters
        date_gte, date_lte, _, court_ids = self._get_search_params()

        # Check if we should filter by court
        if court_ids and court_id not in court_ids:
            return

        # Extract the heading - it contains case name, citation, and date
        # The heading is typically in an h1 or h3 inside the main content
        headings = lxml_tree.xpath(
            "//h1[contains(@class, 'documentTitle')] | "
            "//h2[contains(@class, 'documentTitle')] | "
            "//h3[contains(@class, 'title')]//text() | "
            "//div[@class='docTitle']//text()"
        )

        if not headings:
            # Try alternate approach - look for document title in page
            headings = lxml_tree.xpath(
                "//div[contains(@class, 'item')]//h1//text() | "
                "//div[contains(@class, 'item')]//h2//text()"
            )

        if not headings:
            return

        # Join all heading text
        heading_text = " ".join(
            h.strip() if isinstance(h, str) else h.text_content().strip()
            for h in headings
            if h
        ).strip()

        # Parse the heading
        match = self.HEADING_PATTERN.match(heading_text)
        if not match:
            # Try simpler parsing - just get case name and date
            parts = heading_text.rsplit(" - ", 1)
            if len(parts) >= 2:
                case_name = parts[0].strip()
                date_str = parts[-1].strip()
                citation = None
            else:
                return
        else:
            case_name = match.group("case_name").strip()
            citation = match.group("citation")
            if citation:
                citation = citation.strip()
            date_str = match.group("date")

        # Skip syllabi
        if self._is_syllabus(case_name):
            return

        # Parse date
        date_filed = self._parse_date(date_str)
        if not date_filed:
            return

        # Check date range filter
        if date_gte and date_filed < date_gte:
            return
        if date_lte and date_filed > date_lte:
            return

        # Extract opinion type (e.g., "Supreme Court - Majority")
        opinion_type_elements = lxml_tree.xpath(
            "//div[contains(@class, 'docType')]//text() | "
            "//span[contains(@class, 'category')]//text()"
        )
        opinion_type = None
        if opinion_type_elements:
            opinion_type = " ".join(
                t.strip() for t in opinion_type_elements if t.strip()
            )

        # Extract term (e.g., "2026 Spring Term")
        term_elements = lxml_tree.xpath(
            "//div[contains(@class, 'term')]//text() | "
            "//span[contains(@class, 'term')]//text()"
        )
        term = None
        if term_elements:
            term = " ".join(t.strip() for t in term_elements if t.strip())

        # Build PDF URL
        config = COURT_CONFIG[court_id]
        url_path = config["url_path"]
        pdf_url = (
            f"{BASE_URL}{BASE_PATH}/{url_path}/en/{item_id}/1/document.do"
        )

        # Create opinion cluster
        cluster = ArkOpinionCluster(
            item_id=item_id,
            court_id=court_id,
            date_filed=date_filed,
            case_name=case_name,
            neutral_citation=citation,
            opinion_type=opinion_type,
            term=term,
            source_url=response.url,
            opinions=[],
        )

        # Create opinion with PDF URL
        opinion = ArkOpinion(
            download_url=pdf_url,
            type="majority",
        )
        cluster.opinions.append(opinion)

        # Yield ArchiveRequest for PDF download
        yield ArchiveRequest(
            request=HTTPRequestParams(
                method=HttpMethod.GET,
                url=pdf_url,
            ),
            continuation=self.handle_opinion_download,
            expected_type="pdf",
            accumulated_data={
                "cluster": cluster,
            },
        )

    @step()
    def handle_opinion_download(
        self,
        archive_response: ArchiveResponse,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[ArkOpinionCluster], None, None]:
        """Handle the downloaded opinion PDF and yield the final cluster.

        Args:
            archive_response: Response from archiving the PDF
            accumulated_data: Contains the cluster
        """
        cluster = accumulated_data.get("cluster")

        if not cluster or not isinstance(cluster, ArkOpinionCluster):
            return

        # Update the opinion with the local path
        if cluster.opinions:
            cluster.opinions[0].local_path = archive_response.file_url

        # Yield the complete cluster
        yield ParsedData(data=cluster)
