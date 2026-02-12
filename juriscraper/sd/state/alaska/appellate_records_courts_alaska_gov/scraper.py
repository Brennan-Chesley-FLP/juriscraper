"""Alaska Appellate Courts Scraper.

This module contains a unified scraper for opinions from Alaska appellate courts:
- Alaska Supreme Court (alaska)
- Alaska Court of Appeals (alaskactapp)

Entry points:
- Supreme Court opinions: https://appellate-records.courts.alaska.gov/CMSPublic/Home/Opinions?isCOA=False
- Court of Appeals opinions: https://appellate-records.courts.alaska.gov/CMSPublic/Home/Opinions?isCOA=True

Opinions Flow:
  1. get_entry -> fetches opinions page for each enabled court
  2. parse_opinions_page -> extracts opinions grouped by release date
     - Each date heading contains a table with opinion details
     - Yields ArchiveRequest for each opinion PDF
  3. handle_opinion_download -> stores local path, yields final AlaskaOpinionCluster

Design decisions:
- Uses HTML scraping (no JSON API available)
- Uses DateRange filter on date_filed for searching
- Uses SetFilter on court_id to select which courts to scrape
- Archives opinion PDFs via ArchiveRequest
- All opinions on a single page (no pagination needed)
- Opinions grouped by release date (Friday for slip opinions)
"""

from __future__ import annotations

import re
from datetime import date
from typing import TYPE_CHECKING, ClassVar
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
    BASE_URL,
    COURT_CONFIG,
    AlaskaOpinion,
    AlaskaOpinionCluster,
)

if TYPE_CHECKING:
    from collections.abc import Generator

    from kent.data_types import ScraperYield


class AlaskaScraper(BaseScraper[AlaskaOpinionCluster]):
    """Unified scraper for Alaska appellate court opinions.

    Scrapes opinions from Alaska Supreme Court and Court of Appeals.

    Usage:
        # Scrape all courts
        scraper = AlaskaScraper()

        # Scrape only Supreme Court opinions
        params = AlaskaScraper.params()
        params.AlaskaOpinionCluster.court_id.values = {"alaska"}
        scraper = AlaskaScraper(params=params)

        # Scrape only Court of Appeals opinions
        params = AlaskaScraper.params()
        params.AlaskaOpinionCluster.court_id.values = {"alaskactapp"}
        scraper = AlaskaScraper(params=params)

        # Filter opinions by date range
        params = AlaskaScraper.params()
        params.AlaskaOpinionCluster.date_filed.gte = date(2025, 1, 1)
        params.AlaskaOpinionCluster.date_filed.lte = date(2025, 12, 31)
        scraper = AlaskaScraper(params=params)
    """

    # === Metadata ===
    court_ids: ClassVar[set[str]] = {"alaska", "alaskactapp"}
    court_url: ClassVar[str] = "https://appellate-records.courts.alaska.gov/"
    data_types: ClassVar[set[str]] = {"opinions"}
    status: ClassVar[ScraperStatus] = ScraperStatus.IN_DEVELOPMENT
    version: ClassVar[str] = "2026-01-22"
    requires_auth: ClassVar[bool] = False

    # Rate limiting - be respectful to court servers
    msec_per_request_rate_limit: ClassVar[int] = 2000

    # Mapping from model name to data type
    MODEL_TO_DATA_TYPE: ClassVar[dict[str, str]] = {
        "AlaskaOpinionCluster": "opinions",
    }

    # Regex to parse date headings like "Friday, December 19, 2025"
    DATE_HEADING_PATTERN = re.compile(
        r"^(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),\s+"
        r"(\w+)\s+(\d{1,2}),\s+(\d{4})$"
    )

    def _parse_date_heading(self, heading_text: str) -> date | None:
        """Parse a date from a heading like 'Friday, December 19, 2025'.

        Args:
            heading_text: The heading text containing the date.

        Returns:
            Parsed date object, or None if parsing fails.
        """
        match = self.DATE_HEADING_PATTERN.match(heading_text.strip())
        if not match:
            return None

        month_name = match.group(1)
        day = int(match.group(2))
        year = int(match.group(3))

        # Map month name to number
        months = {
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

        month = months.get(month_name)
        if month is None:
            return None

        try:
            return date(year, month, day)
        except ValueError:
            return None

    def _get_requested_data_types(self) -> set[str]:
        """Get the set of data types to scrape based on enabled models.

        Maps enabled model names to their corresponding data types.
        If no params are set, returns all data types.
        """
        if self._params is None:
            return self.data_types

        enabled_models = self._params.get_enabled_models()
        if not enabled_models:
            # No models enabled means all disabled - return empty
            return set()

        # Map enabled model names to data types
        enabled_data_types = set()
        for model_name in enabled_models:
            if model_name in self.MODEL_TO_DATA_TYPE:
                enabled_data_types.add(self.MODEL_TO_DATA_TYPE[model_name])

        return enabled_data_types & self.data_types

    # =========================================================================
    # Parameter extraction
    # =========================================================================

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
            model_proxy = self._params.AlaskaOpinionCluster
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

        case_field = searchable.get("case_number")
        if case_field and case_field.is_set():
            case_number = case_field.value

        court_field = searchable.get("court_id")
        if court_field and court_field.is_set():
            court_ids = court_field.values

        return date_gte, date_lte, case_number, court_ids

    def _get_target_courts(self) -> set[str]:
        """Get the set of court IDs to scrape."""
        _, _, _, court_ids = self._get_opinions_search_params()

        if court_ids:
            valid_courts = court_ids & set(COURT_CONFIG.keys())
            if valid_courts:
                return valid_courts

        return set(COURT_CONFIG.keys())

    # =========================================================================
    # Entry Point
    # =========================================================================

    @entry(AlaskaOpinionCluster)
    def get_entry(
        self,
    ) -> Generator[NavigatingRequest, None, None]:
        """Yield initial requests for each enabled court.

        Yields separate NavigatingRequests for Supreme Court and Court of Appeals
        based on which courts are enabled in params.
        """
        requested = self._get_requested_data_types()

        if "opinions" not in requested:
            return

        target_courts = self._get_target_courts()

        for court_id in sorted(target_courts):
            config = COURT_CONFIG[court_id]
            opinion_url = config["opinion_url"]

            yield NavigatingRequest(
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url=opinion_url,
                ),
                continuation=self.parse_opinions_page,
                accumulated_data={
                    "court_id": court_id,
                },
            )

    # =========================================================================
    # Opinions Parsing
    # =========================================================================

    @step(xsd="xsds/parse_opinions_page.xsd")
    def parse_opinions_page(
        self,
        lxml_tree: CheckedHtmlElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[AlaskaOpinionCluster], None, None]:
        """Parse the opinions page and yield ArchiveRequests for PDFs.

        The page structure:
        - h5 headings contain release dates (e.g., "Friday, December 19, 2025")
        - After each heading is a table with opinion rows
        - Table columns: Document Download, Opinion Number, Case Number, Case Title, Pacific Reporter Reference
        - Document Download cell contains a link with q= parameter for the PDF
        - Case Number cell contains a link with q= parameter to the case detail

        Each opinion row:
        - First cell: PDF download link (/CMSPublic/UserControl/OpenOpinionDocument?q=...)
        - Second cell: Opinion number (e.g., 7799)
        - Third cell: Case number link (/CMSPublic/Case/General?q=...) with case number text
        - Fourth cell: Case title
        - Fifth cell: Pacific Reporter reference (usually empty)
        """
        court_id: str = accumulated_data.get("court_id", "")

        # Get search parameters for filtering
        date_gte, date_lte, case_number_filter, _ = (
            self._get_opinions_search_params()
        )

        # Find all date headings (h5 elements)
        date_headings = lxml_tree.xpath("//h5")

        for heading in date_headings:
            heading_text = heading.text_content().strip()
            release_date = self._parse_date_heading(heading_text)

            if release_date is None:
                continue

            # Check date range filter
            if date_lte and release_date > date_lte:
                # Date is too new, skip
                continue

            if date_gte and release_date < date_gte:
                # Date is too old, skip (but continue to next heading
                # as they may be in arbitrary order)
                continue

            # Find the table that follows this heading
            # The table should be the next sibling table element
            table = heading.getnext()
            while table is not None and table.tag != "table":
                table = table.getnext()

            if table is None:
                continue

            # Process each row in the table body (skip header row)
            rows = table.xpath(".//tbody/tr")

            for row in rows:
                cells = row.xpath("./td")
                if len(cells) < 4:
                    continue

                # Extract PDF download link from first cell
                pdf_link = cells[0].xpath(".//a/@href")
                if not pdf_link:
                    continue
                pdf_url = urljoin(BASE_URL, pdf_link[0])

                # Extract opinion number from second cell
                opinion_number_text = cells[1].text_content().strip()
                try:
                    opinion_number = int(opinion_number_text)
                except ValueError:
                    opinion_number = None

                # Extract case number and case URL from third cell
                case_link = cells[2].xpath(".//a")
                if not case_link:
                    continue

                case_number = case_link[0].text_content().strip()
                case_url_path = case_link[0].get("href", "")
                case_url = urljoin(BASE_URL, case_url_path)

                # Filter by case number if specified
                if case_number_filter and case_number != case_number_filter:
                    continue

                # Extract case title from fourth cell
                case_title = cells[3].text_content().strip()

                # Extract Pacific Reporter citation from fifth cell if present
                pacific_citation = None
                if len(cells) >= 5:
                    citation_text = cells[4].text_content().strip()
                    if (
                        citation_text
                        and citation_text != "Pacific Reporter Reference"
                    ):
                        pacific_citation = citation_text

                # Create opinion cluster
                cluster = AlaskaOpinionCluster(
                    case_number=case_number,
                    court_id=court_id,
                    date_filed=release_date,
                    case_name=case_title,
                    opinion_number=opinion_number,
                    pacific_reporter_citation=pacific_citation,
                    source_url=response.url,
                    case_url=case_url,
                    opinions=[],
                )

                # Create opinion
                opinion = AlaskaOpinion(
                    download_url=pdf_url,
                    opinion_number=opinion_number,
                )

                cluster.opinions.append(opinion)

                # Yield ArchiveRequest for PDF
                yield ArchiveRequest(
                    request=HTTPRequestParams(
                        method=HttpMethod.GET,
                        url=pdf_url,
                    ),
                    continuation=self.handle_opinion_download,
                    accumulated_data={
                        "cluster": cluster,
                        "opinion_index": 0,
                    },
                )

    @step()
    def handle_opinion_download(
        self,
        archive_response: ArchiveResponse,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[AlaskaOpinionCluster], None, None]:
        """Handle the downloaded opinion PDF and yield the final cluster.

        Args:
            archive_response: Response from archiving the PDF
            accumulated_data: Contains cluster and opinion_index
        """
        cluster = accumulated_data.get("cluster")
        opinion_index = accumulated_data.get("opinion_index", 0)

        if (
            not cluster
            or not isinstance(cluster, AlaskaOpinionCluster)
            or not cluster.opinions
        ):
            return

        # Update the opinion with the local path
        if opinion_index < len(cluster.opinions):
            cluster.opinions[
                opinion_index
            ].local_path = archive_response.file_url

        # Yield the complete cluster
        yield ParsedData(data=cluster)
