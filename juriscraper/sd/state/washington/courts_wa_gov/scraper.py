"""Washington Appellate Courts Opinion Scraper.

This module contains a unified scraper for opinions from Washington courts:
- Washington Supreme Court (wash)
- Court of Appeals of Washington (washctapp) - Divisions I, II, and III

Entry point:
- https://www.courts.wa.gov/opinions/index.cfm?fa=opinions.recent

Opinion URL patterns:
- Recent opinions: https://www.courts.wa.gov/opinions/index.cfm?fa=opinions.recent
- All slip opinions: https://www.courts.wa.gov/opinions/index.cfm?fa=opinions.displayAll
- Opinion info sheet: https://www.courts.wa.gov/opinions/index.cfm?fa=opinions.showOpinion&filename={docket}MAJ

PDF URL patterns vary:
- Supreme Court: https://www.courts.wa.gov/opinions/pdf/{docket}.pdf
- COA Published: Various patterns like /opinions/pdf/D2 {docket}-II Published Opinion.pdf
- COA Unpublished: https://www.courts.wa.gov/opinions/pdf/{docket}_unp.pdf

Flow:
  1. get_entry -> recent opinions page (if "opinions" requested)
  2. parse_recent_opinions -> extracts opinion metadata from tables
  3. yields ArchiveRequests for PDFs
  4. handle_opinion_download -> stores local paths, yields final clusters

Design decisions:
- Uses restrictive checked_xpaths to catch structural changes early
- Uses DateRange filter on date_filed for searching
- Uses SetFilter on court_id to select which courts to scrape
- Archives opinion PDFs via ArchiveRequest
- Scrapes both Supreme Court and Court of Appeals from the same page
"""

from __future__ import annotations

import re
from datetime import date
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
    COURT_IDS,
    DIVISION_MAP,
    WashingtonOpinion,
    WashingtonOpinionCluster,
)

if TYPE_CHECKING:
    from collections.abc import Generator

    from kent.data_types import ScraperYield


class WashingtonScraper(BaseScraper[WashingtonOpinionCluster]):
    """Unified scraper for Washington appellate court opinions.

    Scrapes opinions from Washington Supreme Court and Court of Appeals.

    Usage:
        # Scrape all courts (default)
        scraper = WashingtonScraper()

        # Scrape only Supreme Court
        params = WashingtonScraper.params()
        params.WashingtonOpinionCluster.court_id.values = {"wash"}
        scraper = WashingtonScraper(params=params)

        # Scrape only Court of Appeals
        params = WashingtonScraper.params()
        params.WashingtonOpinionCluster.court_id.values = {"washctapp"}
        scraper = WashingtonScraper(params=params)

        # Filter by date range
        params = WashingtonScraper.params()
        params.WashingtonOpinionCluster.date_filed.gte = date(2026, 1, 1)
        params.WashingtonOpinionCluster.date_filed.lte = date(2026, 1, 31)
        scraper = WashingtonScraper(params=params)

        # Lookup specific docket number
        params = WashingtonScraper.params()
        params.WashingtonOpinionCluster.docket_number.value = "103,469-5"
        scraper = WashingtonScraper(params=params)
    """

    # === Metadata ===
    court_ids: ClassVar[set[str]] = COURT_IDS
    court_url: ClassVar[str] = "https://www.courts.wa.gov/"
    data_types: ClassVar[set[str]] = {"opinions"}
    status: ClassVar[ScraperStatus] = ScraperStatus.IN_DEVELOPMENT
    version: ClassVar[str] = "2026-01-23"
    requires_auth: ClassVar[bool] = False

    # Rate limiting - be respectful to court servers
    msec_per_request_rate_limit: ClassVar[int] = 1000

    # Base URLs
    RECENT_OPINIONS_URL = (
        "https://www.courts.wa.gov/opinions/index.cfm?fa=opinions.recent"
    )
    BASE_URL = "https://www.courts.wa.gov"

    # === Regex patterns ===
    # Date pattern: Mon. DD, YYYY (e.g., "Jan. 15, 2026")
    DATE_PATTERN = re.compile(
        r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\.\s+(\d{1,2}),\s+(\d{4})"
    )
    # Supreme Court docket pattern: NNN,NNN-N
    SC_DOCKET_PATTERN = re.compile(r"(\d{2,3},\d{3}-\d)")
    # Court of Appeals docket pattern: NNNNN-N
    COA_DOCKET_PATTERN = re.compile(r"(\d{5}-\d)")

    # Month abbreviation to number mapping
    MONTH_MAP = {
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

    def _parse_date(self, date_str: str) -> date | None:
        """Parse a date string in 'Mon. DD, YYYY' format.

        Args:
            date_str: Date string like "Jan. 15, 2026"

        Returns:
            Parsed date object, or None if parsing fails.
        """
        match = self.DATE_PATTERN.search(date_str)
        if not match:
            return None

        month_str, day_str, year_str = match.groups()
        try:
            month = self.MONTH_MAP.get(month_str)
            if month is None:
                return None
            return date(int(year_str), month, int(day_str))
        except (ValueError, TypeError):
            return None

    def _get_opinions_search_params(
        self,
    ) -> tuple[date | None, date | None, str | None, set[str] | None]:
        """Extract search parameters for opinions from ScraperParams.

        Returns:
            Tuple of (date_gte, date_lte, docket_number, court_ids)
        """
        if self._params is None:
            return None, None, None, None

        try:
            model_proxy = self._params.WashingtonOpinionCluster
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

    def _should_include_court(self, court_id: str) -> bool:
        """Check if the given court_id should be included based on filters."""
        _, _, _, court_ids = self._get_opinions_search_params()
        if court_ids is None:
            return True  # No filter, include all
        return court_id in court_ids

    # =========================================================================
    # Entry Point
    # =========================================================================

    @entry(WashingtonOpinionCluster)
    def get_entry(self) -> Generator[NavigatingRequest, None, None]:
        """Yield initial requests for opinion scraping.

        Starts with the recent opinions page which contains both
        Supreme Court and Court of Appeals opinions.
        """
        date_gte, date_lte, docket_filter, _ = (
            self._get_opinions_search_params()
        )

        yield NavigatingRequest(
            request=HTTPRequestParams(
                method=HttpMethod.GET,
                url=self.RECENT_OPINIONS_URL,
            ),
            continuation=self.parse_recent_opinions,
            accumulated_data={
                "docket_filter": docket_filter,
                "date_gte": date_gte.isoformat() if date_gte else None,
                "date_lte": date_lte.isoformat() if date_lte else None,
            },
        )

    # =========================================================================
    # Opinion Parsing
    # =========================================================================

    @step(xsd="xsds/parse_recent_opinions.xsd")
    def parse_recent_opinions(
        self,
        lxml_tree: CheckedHtmlElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[WashingtonOpinionCluster], None, None]:
        """Parse the recent opinions page.

        The page has three main sections:
        1. Supreme Court Opinions (table with 4 columns)
        2. Court of Appeals Published Opinions (table with 5 columns)
        3. Court of Appeals Unpublished Opinions (table with 5 columns)
        """
        docket_filter = accumulated_data.get("docket_filter")
        date_gte_str = accumulated_data.get("date_gte")
        date_lte_str = accumulated_data.get("date_lte")

        date_gte = date.fromisoformat(date_gte_str) if date_gte_str else None
        date_lte = date.fromisoformat(date_lte_str) if date_lte_str else None

        # Parse Supreme Court opinions (if included)
        if self._should_include_court("wash"):
            yield from self._parse_supreme_court_table(
                lxml_tree, response, docket_filter, date_gte, date_lte
            )

        # Parse Court of Appeals opinions (if included)
        if self._should_include_court("washctapp"):
            yield from self._parse_court_of_appeals_tables(
                lxml_tree, response, docket_filter, date_gte, date_lte
            )

    def _parse_supreme_court_table(
        self,
        tree: CheckedHtmlElement,
        response: Response,
        docket_filter: str | None,
        date_gte: date | None,
        date_lte: date | None,
    ) -> Generator[ScraperYield[WashingtonOpinionCluster], None, None]:
        """Parse the Supreme Court opinions table.

        Table structure (4 columns):
        - File Date
        - Case Info/File (docket number + PDF link)
        - Case Title
        - File Contains
        """
        # Find the Supreme Court table - it's after the "Supreme Court Opinions" heading
        # and has 4 header columns
        sc_tables = tree.xpath(
            "//h3[contains(text(), 'Supreme Court Opinions')]/following-sibling::table[1]"
        )

        if not sc_tables:
            return

        sc_table = sc_tables[0]

        # Get data rows (skip header row)
        rows = sc_table.xpath(".//tr[td]")

        for row in rows:
            cells = row.xpath("./td")
            if len(cells) < 4:
                continue

            # Cell 0: File Date
            date_text = cells[0].text_content().strip()
            date_filed = self._parse_date(date_text)

            # Cell 1: Case Info/File - contains docket number link and PDF link
            case_info_cell = cells[1]
            docket_links = case_info_cell.xpath(
                ".//a[contains(@href, 'showOpinion')]"
            )
            pdf_links = case_info_cell.xpath(".//a[contains(@href, '.pdf')]")

            if not docket_links or not pdf_links:
                continue

            docket_number = docket_links[0].text_content().strip()
            detail_url = urljoin(response.url, docket_links[0].get("href", ""))
            pdf_url = urljoin(response.url, pdf_links[0].get("href", ""))

            # Cell 2: Case Title
            case_name = cells[2].text_content().strip()

            # Cell 3: File Contains
            file_contents = cells[3].text_content().strip()

            # Apply filters
            if docket_filter and docket_number != docket_filter:
                continue

            if date_filed:
                if date_gte and date_filed < date_gte:
                    continue
                if date_lte and date_filed > date_lte:
                    continue

            cluster_data: dict[str, Any] = {
                "docket_number": docket_number,
                "court_id": "wash",
                "case_name": case_name,
                "date_filed": date_filed.isoformat() if date_filed else None,
                "file_contents": file_contents,
                "publication_status": "published",
                "division": None,
                "detail_url": detail_url,
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

    def _parse_court_of_appeals_tables(
        self,
        tree: CheckedHtmlElement,
        response: Response,
        docket_filter: str | None,
        date_gte: date | None,
        date_lte: date | None,
    ) -> Generator[ScraperYield[WashingtonOpinionCluster], None, None]:
        """Parse Court of Appeals opinion tables (published and unpublished).

        Table structure (5 columns):
        - File Date
        - Case Info/File (docket number + PDF link)
        - Div. (I, II, or III)
        - Case Title
        - File Contains
        """
        # Find both published and unpublished tables
        # Published table is after "Published Opinions" strong tag
        # Unpublished table is after "Unpublished Opinions" strong tag

        for pub_status in ["published", "unpublished"]:
            if pub_status == "published":
                # Find the table after "Published Opinions"
                tables = tree.xpath(
                    "//h3[contains(text(), 'Court of Appeals Opinions')]/following-sibling::*//strong[contains(text(), 'Published Opinions')]/following::table[1]"
                )
            else:
                # Find the table after "Unpublished Opinions"
                tables = tree.xpath(
                    "//strong[contains(text(), 'Unpublished Opinions')]/following::table[1]"
                )

            if not tables:
                continue

            table = tables[0]

            # Get data rows (skip header row)
            rows = table.xpath(".//tr[td]")

            for row in rows:
                cells = row.xpath("./td")
                if len(cells) < 5:
                    continue

                # Cell 0: File Date
                date_text = cells[0].text_content().strip()
                date_filed = self._parse_date(date_text)

                # Cell 1: Case Info/File
                case_info_cell = cells[1]
                docket_links = case_info_cell.xpath(
                    ".//a[contains(@href, 'showOpinion')]"
                )
                pdf_links = case_info_cell.xpath(
                    ".//a[contains(@href, '.pdf')]"
                )

                if not docket_links or not pdf_links:
                    continue

                docket_number = docket_links[0].text_content().strip()
                detail_url = urljoin(
                    response.url, docket_links[0].get("href", "")
                )
                pdf_url = urljoin(response.url, pdf_links[0].get("href", ""))

                # Cell 2: Division (I, II, or III)
                division_text = cells[2].text_content().strip()
                division = DIVISION_MAP.get(division_text)

                # Cell 3: Case Title
                case_name = cells[3].text_content().strip()

                # Cell 4: File Contains
                file_contents = cells[4].text_content().strip()

                # Apply filters
                if docket_filter and docket_number != docket_filter:
                    continue

                if date_filed:
                    if date_gte and date_filed < date_gte:
                        continue
                    if date_lte and date_filed > date_lte:
                        continue

                cluster_data: dict[str, Any] = {
                    "docket_number": docket_number,
                    "court_id": "washctapp",
                    "case_name": case_name,
                    "date_filed": date_filed.isoformat()
                    if date_filed
                    else None,
                    "file_contents": file_contents,
                    "publication_status": pub_status,
                    "division": division,
                    "detail_url": detail_url,
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

    # =========================================================================
    # PDF Download Handling
    # =========================================================================

    @step
    def handle_opinion_download(
        self,
        response: ArchiveResponse,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[WashingtonOpinionCluster], None, None]:
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
    ) -> Generator[ScraperYield[WashingtonOpinionCluster], None, None]:
        """Build and yield the final OpinionCluster with all PDFs downloaded."""
        opinions = []
        for i, op_data in enumerate(accumulated_data["opinions_data"]):
            local_path = accumulated_data["downloaded_paths"].get(i)
            opinions.append(
                WashingtonOpinion(
                    download_url=op_data["download_url"],
                    type=op_data.get("type", "majority"),
                    local_path=local_path,
                )
            )

        date_filed = None
        if accumulated_data.get("date_filed"):
            date_filed = date.fromisoformat(accumulated_data["date_filed"])

        cluster = WashingtonOpinionCluster(
            docket_number=accumulated_data["docket_number"],
            court_id=accumulated_data["court_id"],
            date_filed=date_filed,
            case_name=accumulated_data["case_name"],
            division=accumulated_data.get("division"),
            publication_status=accumulated_data.get("publication_status"),
            file_contents=accumulated_data.get("file_contents"),
            opinions=opinions,
            source_url=accumulated_data.get("source_url"),
            detail_url=accumulated_data.get("detail_url"),
        )

        yield ParsedData(cluster)
