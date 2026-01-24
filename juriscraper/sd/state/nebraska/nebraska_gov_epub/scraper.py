"""Nebraska Appellate Courts Scraper.

This module scrapes opinions from the Nebraska Supreme Court and
Court of Appeals using the Nebraska Appellate Courts Online Library.

Entry points::

    - Supreme Court: https://www.nebraska.gov/apps-courts-epub/public/supreme
    - Court of Appeals: https://www.nebraska.gov/apps-courts-epub/public/appeals

Flow::

    1. get_entry -> Volume list page URL (based on requested courts)
    2. parse_volume_list -> Parse volumes table, find expanded volumes with opinions
    3. _parse_opinion_rows -> Parse opinion data from expanded volume tables
    4. handle_opinion_download -> yields final NebraskaOpinionCluster

Design decisions::

    - Each court (Supreme/Appeals) has its own volume listing page
    - Volumes are expandable - clicking expands to show individual opinions
    - **Requires Playwright/browser driver**: The page uses JavaScript to expand
      volumes. The driver must click on each volume link to expand it before
      this scraper can parse the opinion data.
    - When expanded, opinions appear in a nested table with columns:
      Date, Docket No., Caption, Citation, Status
    - Opinions link to direct PDF downloads via viewAdvanced endpoint
    - Uses SetFilter on court_id to select which courts to scrape
    - Uses DateRange filter on date_filed for searching

Note: This scraper requires a Playwright/browser-based driver that will::

    1. Navigate to the volume list page
    2. Click on each volume link to expand it (or all volumes if supported)
    3. Pass the fully rendered HTML to this scraper for parsing
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import TYPE_CHECKING, ClassVar

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
    CASE_PREFIX_TO_COURT,
    VOLUME_PREFIX_TO_COURT,
    NebraskaOpinion,
    NebraskaOpinionCluster,
)

if TYPE_CHECKING:
    from collections.abc import Generator

    from juriscraper.scraper_driver.data_types import ScraperYield


# Base URLs
BASE_URL = "https://www.nebraska.gov/apps-courts-epub"
SUPREME_COURT_URL = f"{BASE_URL}/public/supreme"
COURT_OF_APPEALS_URL = f"{BASE_URL}/public/appeals"

# URL patterns
VIEW_OPINION_URL = f"{BASE_URL}/public/viewOpinion"
VIEW_ADVANCED_URL = f"{BASE_URL}/public/viewAdvanced"


class NebraskaScraper(BaseScraper[NebraskaOpinionCluster]):
    """Scraper for Nebraska appellate court opinions.

    Scrapes opinions from the Nebraska Supreme Court (neb) and
    Court of Appeals (nebctapp) via the Online Library.

    Usage:
        # Scrape all opinions from both courts
        scraper = NebraskaScraper()

        # Scrape only Supreme Court opinions
        params = NebraskaScraper.params()
        params.NebraskaOpinionCluster.court_id.values = {"neb"}
        scraper = NebraskaScraper(params=params)

        # Scrape only Court of Appeals opinions
        params = NebraskaScraper.params()
        params.NebraskaOpinionCluster.court_id.values = {"nebctapp"}
        scraper = NebraskaScraper(params=params)

        # Filter opinions by date range
        params = NebraskaScraper.params()
        params.NebraskaOpinionCluster.date_filed.gte = date(2026, 1, 1)
        params.NebraskaOpinionCluster.date_filed.lte = date(2026, 1, 31)
        scraper = NebraskaScraper(params=params)
    """

    # === Metadata ===
    court_ids: ClassVar[set[str]] = {"neb", "nebctapp"}
    court_url: ClassVar[str] = "https://www.nebraska.gov/apps-courts-epub/"
    data_types: ClassVar[set[str]] = {"opinions"}
    status: ClassVar[ScraperStatus] = ScraperStatus.IN_DEVELOPMENT
    version: ClassVar[str] = "2026-01-23"
    requires_auth: ClassVar[bool] = False

    # Rate limiting - be respectful to court servers
    msec_per_request_rate_limit: ClassVar[int] = 1000

    # === Regex patterns ===
    # Case number pattern: S-YY-NNN or A-YY-NNN
    CASE_NUMBER_PATTERN = re.compile(r"([SA])-(\d{2})-(\d{3,4})")

    # Citation pattern: Volume Reporter Page (e.g., "320 Neb. 619" or "34 Neb. App. 1")
    CITATION_PATTERN = re.compile(r"(\d+)\s+(Neb\.(?: App\.)?)\s+(\d+)")

    # Volume pattern: "320 Neb." or "34 Neb. App."
    VOLUME_PATTERN = re.compile(r"(\d+)\s+(Neb\.(?: App\.)?)")

    # Doc ID pattern from URL: docId=N00012924PUB
    DOC_ID_PATTERN = re.compile(r"docId=([A-Z0-9]+)")

    # Date patterns
    # Opening-closing dates: "10/03/2025 - 01/16/2026" or "01/20/2026 -"
    DATE_RANGE_PATTERN = re.compile(
        r"(\d{2}/\d{2}/\d{4})\s*-\s*(\d{2}/\d{2}/\d{4})?"
    )

    # Opinion date: "01/16/2026"
    OPINION_DATE_PATTERN = re.compile(r"(\d{2}/\d{2}/\d{4})")

    # Mapping from model name to data type
    MODEL_TO_DATA_TYPE: ClassVar[dict[str, str]] = {
        "NebraskaOpinionCluster": "opinions",
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
            Tuple of (date_gte, date_lte, docket_id, court_ids)
        """
        if self._params is None:
            return None, None, None, None

        try:
            model_proxy = self._params.NebraskaOpinionCluster
        except AttributeError:
            return None, None, None, None

        date_gte = None
        date_lte = None
        docket_id = None
        court_ids = None

        searchable = model_proxy.get_searchable_fields()

        date_field = searchable.get("date_filed")
        if date_field and date_field.is_set():
            date_gte = date_field.gte
            date_lte = date_field.lte

        docket_field = searchable.get("docket_id")
        if docket_field and docket_field.is_set():
            docket_id = docket_field.value

        court_field = searchable.get("court_id")
        if court_field and court_field.is_set():
            court_ids = court_field.values

        return date_gte, date_lte, docket_id, court_ids

    def _get_court_id_from_case_number(self, case_number: str) -> str | None:
        """Determine court ID from case number prefix.

        Args:
            case_number: Case number like 'S-24-295' or 'A-24-927'

        Returns:
            Court ID ('neb' or 'nebctapp') or None if unrecognized
        """
        match = self.CASE_NUMBER_PATTERN.match(case_number)
        if match:
            prefix = match.group(1)
            return CASE_PREFIX_TO_COURT.get(prefix)
        return None

    def _get_court_id_from_volume(self, volume_str: str) -> str | None:
        """Determine court ID from volume string.

        Args:
            volume_str: Volume like '320 Neb.' or '34 Neb. App.'

        Returns:
            Court ID ('neb' or 'nebctapp') or None if unrecognized
        """
        match = self.VOLUME_PATTERN.search(volume_str)
        if match:
            reporter = match.group(2)
            return VOLUME_PREFIX_TO_COURT.get(reporter)
        return None

    def _parse_date(self, date_str: str) -> date | None:
        """Parse date in MM/DD/YYYY format.

        Args:
            date_str: Date like '01/16/2026'

        Returns:
            Parsed date or None
        """
        try:
            return datetime.strptime(date_str.strip(), "%m/%d/%Y").date()
        except ValueError:
            return None

    def _parse_citation(
        self, citation_str: str
    ) -> tuple[int | None, str | None, int | None]:
        """Parse citation string into components.

        Args:
            citation_str: Citation like '320 Neb. 619'

        Returns:
            Tuple of (volume, reporter, page) or (None, None, None)
        """
        match = self.CITATION_PATTERN.search(citation_str)
        if match:
            return int(match.group(1)), match.group(2), int(match.group(3))
        return None, None, None

    def _extract_doc_id(self, url: str) -> str | None:
        """Extract document ID from URL.

        Args:
            url: URL containing docId parameter

        Returns:
            Document ID or None
        """
        match = self.DOC_ID_PATTERN.search(url)
        if match:
            return match.group(1)
        return None

    # =========================================================================
    # Entry Point
    # =========================================================================

    def get_entry(self) -> Generator[NavigatingRequest, None, None]:
        """Yield initial requests to volume list pages."""
        requested = self._get_requested_data_types()
        _, _, _, court_ids = self._get_search_params()

        if "opinions" not in requested:
            return

        # Determine which courts to scrape
        courts_to_scrape = court_ids if court_ids else {"neb", "nebctapp"}

        if "neb" in courts_to_scrape:
            yield NavigatingRequest(
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url=SUPREME_COURT_URL,
                ),
                continuation=self.parse_volume_list,
                accumulated_data={"court_type": "supreme"},
            )

        if "nebctapp" in courts_to_scrape:
            yield NavigatingRequest(
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url=COURT_OF_APPEALS_URL,
                ),
                continuation=self.parse_volume_list,
                accumulated_data={"court_type": "appeals"},
            )

    # =========================================================================
    # Volume List Parsing
    # =========================================================================

    @step(xsd="xsds/parse_volume_list.xsd")
    def parse_volume_list(
        self,
        lxml_tree: CheckedHtmlElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[NebraskaOpinionCluster], None, None]:
        """Parse the volume list page and extract opinions from expanded volumes.

        The page has a table with expandable volume rows. Each volume row
        can be clicked to expand and show individual opinions. This scraper
        expects the driver to have already expanded the volumes via JavaScript.

        When expanded, the structure is:
        - Volume row: "− 320 Neb." (minus sign indicates expanded)
        - Next row: Contains nested table with opinions

        Nested table columns: Date, Docket No., Caption, Citation, Status
        """
        date_gte, date_lte, target_docket, _ = self._get_search_params()
        court_type = accumulated_data.get("court_type", "supreme")

        # Determine court ID
        court_id = "neb" if court_type == "supreme" else "nebctapp"

        # Find all rows in the main table body
        all_rows = lxml_tree.checked_xpath(
            "//table//tbody/tr",
            "all table rows",
            min_count=0,
        )

        i = 0
        while i < len(all_rows):
            row = all_rows[i]

            # Check if this is a volume header row (contains volume link)
            volume_links = row.checked_xpath(
                ".//a[contains(@href, '#volumeOpinionsHeading')]",
                "volume links",
                min_count=0,
            )

            if not volume_links:
                i += 1
                continue

            # Get volume text
            volume_text_parts = volume_links[0].checked_xpath(
                ".//text()",
                "volume link text parts",
                min_count=0,
                type=str,
            )
            full_volume_text = "".join(volume_text_parts).strip()

            # Check if expanded (starts with − or -)
            is_expanded = full_volume_text.startswith(
                "−"
            ) or full_volume_text.startswith("-")

            # Remove the +/- prefix to get volume text
            volume_text = full_volume_text.lstrip("+-−").strip()

            # Parse volume number
            volume_match = self.VOLUME_PATTERN.search(volume_text)
            if not volume_match:
                i += 1
                continue

            volume_number = int(volume_match.group(1))

            # Get date range for this volume from the row cells
            row_text = row.text_content()
            volume_start_date = None
            volume_end_date = None

            date_match = self.DATE_RANGE_PATTERN.search(row_text)
            if date_match:
                volume_start_date = self._parse_date(date_match.group(1))
                if date_match.group(2):
                    volume_end_date = self._parse_date(date_match.group(2))

            # Skip volumes that are entirely outside the date range
            if date_gte and volume_end_date and volume_end_date < date_gte:
                i += 1
                continue
            if date_lte and volume_start_date and volume_start_date > date_lte:
                i += 1
                continue

            # If expanded, the next row should contain the opinions table
            if is_expanded and i + 1 < len(all_rows):
                next_row = all_rows[i + 1]

                # Check if next row contains a nested opinions table
                nested_tables = next_row.checked_xpath(
                    ".//table",
                    "nested opinions table",
                    min_count=0,
                )

                if nested_tables:
                    yield from self._parse_opinion_rows(
                        nested_tables[0],
                        response,
                        court_id,
                        volume_number,
                        volume_text,
                        date_gte,
                        date_lte,
                        target_docket,
                    )
                    i += 2  # Skip both the header row and the content row
                    continue

            i += 1

        # Check for pagination
        pagination_links = lxml_tree.checked_xpath(
            "//a[contains(@href, 'offset=')]/@href",
            "pagination links",
            min_count=0,
            type=str,
        )

        # Find the "next page" link - look for the >> link
        for href in pagination_links:
            if "offset=" in href:
                next_url = (
                    f"https://www.nebraska.gov{href}"
                    if href.startswith("/")
                    else href
                )
                yield NavigatingRequest(
                    request=HTTPRequestParams(
                        method=HttpMethod.GET,
                        url=next_url,
                    ),
                    continuation=self.parse_volume_list,
                    accumulated_data=accumulated_data,
                )
                break  # Only follow one pagination link per page

    def _parse_opinion_rows(
        self,
        table: CheckedHtmlElement,
        response: Response,
        court_id: str,
        volume_number: int,
        volume_text: str,
        date_gte: date | None,
        date_lte: date | None,
        target_docket: str | None,
    ) -> Generator[ScraperYield[NebraskaOpinionCluster], None, None]:
        """Parse opinion rows from a volume's expanded opinions table.

        The nested table has columns:
        - Date (e.g., "01/16/2026")
        - Docket No. (e.g., "S-25-141 S-25-140" - can be multiple)
        - Caption (case name)
        - Citation (e.g., "320 Neb. 675")
        - Status (PDF link with "Advance" or no text for published)
        """
        # Find opinion rows in the table body (skip header row)
        opinion_rows = table.checked_xpath(
            ".//tbody/tr",
            "opinion rows in volume",
            min_count=0,
        )

        for op_row in opinion_rows:
            cells = op_row.checked_xpath(
                ".//td",
                "opinion cells",
                min_count=0,
            )

            if len(cells) < 5:
                continue

            # Extract date (first cell)
            date_text = cells[0].text_content().strip()
            opinion_date = self._parse_date(date_text)

            if opinion_date is None:
                # Not a data row (might be header or empty)
                continue

            # Filter by date
            if date_gte and opinion_date < date_gte:
                continue
            if date_lte and opinion_date > date_lte:
                continue

            # Extract docket number(s) (second cell) - may have multiple
            # Text appears as "S-25-141 S-25-140 S-25-139" etc.
            docket_cell = cells[1]
            docket_text = docket_cell.text_content()
            # Split by whitespace and filter for valid case numbers
            docket_parts = docket_text.split()
            docket_numbers = [
                d.strip()
                for d in docket_parts
                if self.CASE_NUMBER_PATTERN.match(d.strip())
            ]

            if not docket_numbers:
                continue

            # Use primary docket number (first one)
            primary_docket = docket_numbers[0]

            # Filter by specific docket if specified
            if target_docket and primary_docket != target_docket:
                continue

            # Extract case name (third cell)
            case_name = cells[2].text_content().strip()

            # Extract citation (fourth cell)
            citation_text = cells[3].text_content().strip()
            cite_volume, cite_reporter, cite_page = self._parse_citation(
                citation_text
            )

            if cite_volume is None or cite_page is None:
                continue

            # Build full citation using the actual reporter from citation
            citation = f"{cite_volume} {cite_reporter} {cite_page}"

            # Extract PDF link (fifth cell)
            pdf_links = cells[4].checked_xpath(
                ".//a[contains(@href, 'view')]/@href",
                "PDF link",
                min_count=0,
                type=str,
            )

            if not pdf_links:
                continue

            pdf_href = pdf_links[0]
            # Build full URL
            if pdf_href.startswith("/"):
                pdf_url = f"https://www.nebraska.gov{pdf_href}"
            else:
                pdf_url = pdf_href

            # Extract doc ID
            doc_id = self._extract_doc_id(pdf_url)
            if not doc_id:
                continue

            # Extract status from link text
            status_text = cells[4].text_content().strip()
            status = "Advance" if "Advance" in status_text else "Published"

            # Build accumulated data for download
            cluster_data = {
                "docket_id": primary_docket,
                "docket_numbers": docket_numbers,
                "court_id": court_id,
                "date_filed": opinion_date.isoformat(),
                "case_name": case_name,
                "citation": citation,
                "volume_number": cite_volume,
                "page_number": cite_page,
                "status": status,
                "source_url": response.url,
                "opinions_data": [{"download_url": pdf_url, "doc_id": doc_id}],
                "pending_downloads": 1,
                "completed_downloads": 0,
                "downloaded_paths": {},
            }

            # Yield ArchiveRequest for the PDF
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
    # Download Handler
    # =========================================================================

    @step
    def handle_opinion_download(
        self,
        response: ArchiveResponse,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[NebraskaOpinionCluster], None, None]:
        """Handle a downloaded opinion PDF."""
        current_index = accumulated_data["current_download_index"]

        accumulated_data["downloaded_paths"][current_index] = response.file_url
        accumulated_data["completed_downloads"] += 1

        if (
            accumulated_data["completed_downloads"]
            >= accumulated_data["pending_downloads"]
        ):
            yield from self._yield_final_cluster(accumulated_data)
        else:
            # Download next file if any
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

    def _yield_final_cluster(
        self, accumulated_data: dict
    ) -> Generator[ScraperYield[NebraskaOpinionCluster], None, None]:
        """Build and yield the final OpinionCluster with all PDFs downloaded."""
        opinions = []
        for i, op_data in enumerate(accumulated_data["opinions_data"]):
            local_path = accumulated_data["downloaded_paths"].get(i)
            opinions.append(
                NebraskaOpinion(
                    download_url=op_data["download_url"],
                    doc_id=op_data["doc_id"],
                    local_path=local_path,
                )
            )

        date_filed = datetime.fromisoformat(
            accumulated_data["date_filed"]
        ).date()

        cluster = NebraskaOpinionCluster(
            docket_id=accumulated_data["docket_id"],
            court_id=accumulated_data["court_id"],
            date_filed=date_filed,
            case_name=accumulated_data["case_name"],
            citation=accumulated_data["citation"],
            volume_number=accumulated_data["volume_number"],
            page_number=accumulated_data["page_number"],
            opinions=opinions,
            source_url=accumulated_data.get("source_url"),
            status=accumulated_data.get("status", "Advance"),
        )

        yield ParsedData(cluster)
