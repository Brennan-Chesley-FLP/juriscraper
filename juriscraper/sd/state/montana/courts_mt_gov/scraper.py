"""Montana Supreme Court Scraper.

This module scrapes opinions and orders from the Montana Supreme Court
daily orders page.

Entry point:
- Daily Orders: https://courts.mt.gov/external/orders/dailyorders

Flow:
1. get_entry -> daily orders page (if "opinions" requested)
2. parse_daily_orders -> parses table rows, yields ArchiveRequests for PDFs
3. handle_document_download -> yields final MontanaOpinionCluster

Design decisions:
- Scrapes from the daily orders page which lists recent orders and opinions
- Each entry has: Document Description, File Date, Case Number, Title
- Case numbers link to case info pages
- PDFs are served from juddocumentservice.mt.gov
- Uses DateRange filter on date_filed for searching
- Montana has no intermediate appellate court - only the Supreme Court

Case number format: {PREFIX} {YY}-{NNNN}
  - DA: Direct Appeal
  - OP: Original Proceeding
  - PR: Professional Responsibility/Attorney Discipline
  - AF: Administrative Filing
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import TYPE_CHECKING, ClassVar
from urllib.parse import quote, urljoin

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
    MontanaOpinion,
    MontanaOpinionCluster,
)

if TYPE_CHECKING:
    from collections.abc import Generator

    from juriscraper.scraper_driver.data_types import ScraperYield


# Base URLs
BASE_URL = "https://courts.mt.gov"
DAILY_ORDERS_URL = "https://courts.mt.gov/external/orders/dailyorders"
CASE_INFO_URL_TEMPLATE = "https://courts.mt.gov/external/orders/caseInfo?id={}"
DOCUMENT_SERVICE_URL = (
    "https://juddocumentservice.mt.gov/getDocByCTrackId?DocId={}"
)


class MontanaScraper(BaseScraper[MontanaOpinionCluster]):
    """Scraper for Montana Supreme Court opinions and orders.

    Scrapes opinions and orders from the Montana Supreme Court
    daily orders page.

    Usage:
        # Scrape all recent orders/opinions
        scraper = MontanaScraper()

        # Filter by date range
        params = MontanaScraper.params()
        params.MontanaOpinionCluster.date_filed.gte = date(2026, 1, 1)
        params.MontanaOpinionCluster.date_filed.lte = date(2026, 1, 31)
        scraper = MontanaScraper(params=params)

        # Scrape specific case by docket number
        params = MontanaScraper.params()
        params.MontanaOpinionCluster.docket_id.value = "DA 25-0142"
        scraper = MontanaScraper(params=params)
    """

    # === Metadata ===
    court_ids: ClassVar[set[str]] = {"mont"}
    court_url: ClassVar[str] = "https://courts.mt.gov/Courts/Supreme"
    data_types: ClassVar[set[str]] = {"opinions"}
    status: ClassVar[ScraperStatus] = ScraperStatus.IN_DEVELOPMENT
    version: ClassVar[str] = "2026-01-23"
    requires_auth: ClassVar[bool] = False

    # Rate limiting - be respectful to court servers
    msec_per_request_rate_limit: ClassVar[int] = 1000

    # === Regex patterns ===
    # Case number pattern: DA 25-0142, OP 25-0001, PR 25-0001, AF 25-0001
    CASE_NUMBER_PATTERN = re.compile(r"(DA|OP|PR|AF)\s+(\d{2})-(\d{4})")

    # Date parsing pattern from table: YYYY-MM-DD HH:MM:SS.0
    DATE_PATTERN = re.compile(r"(\d{4})-(\d{2})-(\d{2})")

    # Document ID pattern from URLs
    DOC_ID_PATTERN = re.compile(r"DocId=(\d+)")

    # Mapping from model name to data type
    MODEL_TO_DATA_TYPE: ClassVar[dict[str, str]] = {
        "MontanaOpinionCluster": "opinions",
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
            model_proxy = self._params.MontanaOpinionCluster
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

    def _parse_date(self, date_str: str) -> date | None:
        """Parse date from table cell.

        Args:
            date_str: Date like '2026-01-22 08:59:34.0' or '2026-01-22'

        Returns:
            Parsed date or None
        """
        match = self.DATE_PATTERN.search(date_str)
        if match:
            year = int(match.group(1))
            month = int(match.group(2))
            day = int(match.group(3))
            return date(year, month, day)
        return None

    def _normalize_case_number(self, case_num: str) -> str:
        """Normalize case number format.

        Ensures consistent format like 'DA 25-0142'.

        Args:
            case_num: Raw case number from table

        Returns:
            Normalized case number
        """
        # Remove extra whitespace and normalize
        case_num = " ".join(case_num.split())
        return case_num

    def _build_case_info_url(self, case_num: str) -> str:
        """Build URL for case info page.

        Args:
            case_num: Case number like 'DA 25-0142'

        Returns:
            URL to case info page
        """
        # URL encode the case number (space becomes %20)
        encoded = quote(case_num, safe="")
        return CASE_INFO_URL_TEMPLATE.format(encoded)

    # =========================================================================
    # Entry Point
    # =========================================================================

    @entry(MontanaOpinionCluster)
    def get_entry(self) -> Generator[NavigatingRequest, None, None]:
        """Yield initial request to daily orders page."""
        requested = self._get_requested_data_types()

        if "opinions" in requested:
            yield NavigatingRequest(
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url=DAILY_ORDERS_URL,
                ),
                continuation=self.parse_daily_orders,
            )

    # =========================================================================
    # Daily Orders Page Parsing
    # =========================================================================

    @step(xsd="xsds/parse_daily_orders.xsd")
    def parse_daily_orders(
        self,
        lxml_tree: CheckedHtmlElement,
        response: Response,
    ) -> Generator[ScraperYield[MontanaOpinionCluster], None, None]:
        """Parse the daily orders page and yield requests for PDFs.

        The page has multiple date sections, each with a table containing:
        - Document Description
        - File Date
        - Case Number (linked to case info page)
        - Title

        We need to navigate to each case info page to find the actual
        document download links.
        """
        date_gte, date_lte, target_docket = self._get_search_params()

        # Find all tables on the page - each date section has a table
        tables = lxml_tree.checked_xpath(
            "//table",
            "order tables",
            min_count=0,
        )

        for table in tables:
            # Get all rows in the table body
            rows = table.checked_xpath(
                ".//tr[td]",
                "table rows with data",
                min_count=0,
            )

            for row in rows:
                # Get all cells in the row
                cells = row.checked_xpath(
                    "td",
                    "row cells",
                    min_count=0,
                )

                if len(cells) < 4:
                    # Skip rows that don't have all expected columns
                    continue

                # Extract document description from first cell
                doc_desc_texts = cells[0].checked_xpath(
                    ".//text()",
                    "document description",
                    min_count=0,
                    type=str,
                )
                doc_description = " ".join(
                    t.strip() for t in doc_desc_texts if t.strip()
                )

                # Extract file date from second cell
                date_texts = cells[1].checked_xpath(
                    ".//text()",
                    "file date",
                    min_count=0,
                    type=str,
                )
                date_str = "".join(date_texts).strip()
                file_date = self._parse_date(date_str)

                if file_date is None:
                    continue

                # Filter by date range if specified
                if date_gte and file_date < date_gte:
                    continue
                if date_lte and file_date > date_lte:
                    continue

                # Extract case number from third cell
                case_links = cells[2].checked_xpath(
                    ".//a",
                    "case number link",
                    min_count=0,
                )

                if not case_links:
                    # Try to get case number as text if no link
                    case_texts = cells[2].checked_xpath(
                        ".//text()",
                        "case number text",
                        min_count=0,
                        type=str,
                    )
                    case_number = "".join(case_texts).strip()
                    case_info_href = None
                else:
                    case_link = case_links[0]
                    case_texts = case_link.checked_xpath(
                        ".//text()",
                        "case number text",
                        min_count=0,
                        type=str,
                    )
                    case_number = "".join(case_texts).strip()

                    # Get href from link
                    hrefs = case_link.checked_xpath(
                        "@href",
                        "case link href",
                        min_count=0,
                        type=str,
                    )
                    case_info_href = hrefs[0] if hrefs else None

                case_number = self._normalize_case_number(case_number)

                # Validate case number format
                if not self.CASE_NUMBER_PATTERN.match(case_number):
                    continue

                # Filter by specific docket if specified
                if target_docket and case_number != target_docket:
                    continue

                # Extract title from fourth cell
                title_texts = cells[3].checked_xpath(
                    ".//text()",
                    "case title",
                    min_count=0,
                    type=str,
                )
                case_title = " ".join(
                    t.strip() for t in title_texts if t.strip()
                )

                # Build case info URL
                if case_info_href:
                    case_info_url = urljoin(response.url, case_info_href)
                else:
                    case_info_url = self._build_case_info_url(case_number)

                # Build accumulated data for case info page
                cluster_data = {
                    "docket_id": case_number,
                    "court_id": "mont",
                    "date_filed": file_date.isoformat(),
                    "case_name": case_title,
                    "source_url": response.url,
                    "case_info_url": case_info_url,
                    "document_description": doc_description,
                }

                # Navigate to case info page to get document links
                yield NavigatingRequest(
                    request=HTTPRequestParams(
                        method=HttpMethod.GET,
                        url=case_info_url,
                    ),
                    continuation=self.parse_case_info,
                    accumulated_data=cluster_data,
                )

    # =========================================================================
    # Case Info Page Parsing
    # =========================================================================

    @step(xsd="xsds/parse_case_info.xsd")
    def parse_case_info(
        self,
        lxml_tree: CheckedHtmlElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[MontanaOpinionCluster], None, None]:
        """Parse case info page and extract document download links.

        The case info page contains:
        - Case Information table (Case Number, Appeal Basis, Case Type, etc.)
        - Party Information table
        - Register of Actions table with document links

        We're looking for Opinion or Order documents in the Register of Actions.
        """
        # Try to extract case type from the case information
        case_type = None
        case_type_cells = lxml_tree.checked_xpath(
            "//td[contains(text(), 'Case Type')]/following-sibling::td[1]//text()",
            "case type",
            min_count=0,
            type=str,
        )
        if case_type_cells:
            case_type = " ".join(
                t.strip() for t in case_type_cells if t.strip()
            )
            accumulated_data["case_type"] = case_type

        # Look for document links in the Register of Actions
        # Documents are typically linked as "View Document" or similar
        doc_links = lxml_tree.checked_xpath(
            "//a[contains(@href, 'juddocumentservice') or contains(@href, 'getDocByCTrackId')]",
            "document links",
            min_count=0,
        )

        # If no direct document links, look for links with DocId parameter
        if not doc_links:
            doc_links = lxml_tree.checked_xpath(
                "//a[contains(@href, 'DocId=')]",
                "document links with DocId",
                min_count=0,
            )

        # Collect all document URLs
        doc_urls = []
        for link in doc_links:
            hrefs = link.checked_xpath(
                "@href",
                "document href",
                min_count=0,
                type=str,
            )
            if hrefs:
                href = hrefs[0]
                # Convert relative URLs to absolute
                doc_url = urljoin(response.url, href)

                # Extract doc ID if present
                doc_id_match = self.DOC_ID_PATTERN.search(doc_url)
                doc_id = doc_id_match.group(1) if doc_id_match else None

                doc_urls.append(
                    {
                        "url": doc_url,
                        "doc_id": doc_id,
                    }
                )

        if not doc_urls:
            # No documents found - yield cluster without PDFs
            # This can happen for cases where documents are not yet available
            cluster = MontanaOpinionCluster(
                docket_id=accumulated_data["docket_id"],
                court_id=accumulated_data["court_id"],
                date_filed=datetime.fromisoformat(
                    accumulated_data["date_filed"]
                ).date(),
                case_name=accumulated_data["case_name"],
                opinions=[],
                source_url=accumulated_data["source_url"],
                case_info_url=accumulated_data["case_info_url"],
                document_description=accumulated_data.get(
                    "document_description"
                ),
                case_type=accumulated_data.get("case_type"),
                precedential_status="Unknown",
            )
            yield ParsedData(cluster)
            return

        # Prepare download tracking
        accumulated_data["pending_downloads"] = len(doc_urls)
        accumulated_data["completed_downloads"] = 0
        accumulated_data["downloaded_paths"] = {}
        accumulated_data["doc_urls"] = doc_urls

        # Start downloading first document
        first_doc = doc_urls[0]
        first_url = first_doc["url"]
        assert isinstance(first_url, str)
        yield ArchiveRequest(
            request=HTTPRequestParams(
                method=HttpMethod.GET,
                url=first_url,
            ),
            continuation=self.handle_document_download,
            expected_type="pdf",
            accumulated_data={
                **accumulated_data,
                "current_download_index": 0,
            },
        )

    # =========================================================================
    # Download Handler
    # =========================================================================

    @step
    def handle_document_download(
        self,
        response: ArchiveResponse,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[MontanaOpinionCluster], None, None]:
        """Handle a downloaded document PDF."""
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
            doc_urls = accumulated_data["doc_urls"]
            next_doc = doc_urls[next_index]

            yield ArchiveRequest(
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url=next_doc["url"],
                ),
                continuation=self.handle_document_download,
                expected_type="pdf",
                accumulated_data={
                    **accumulated_data,
                    "current_download_index": next_index,
                },
            )

    def _yield_final_cluster(
        self, accumulated_data: dict
    ) -> Generator[ScraperYield[MontanaOpinionCluster], None, None]:
        """Build and yield the final OpinionCluster with all PDFs downloaded."""
        opinions = []
        doc_urls = accumulated_data.get("doc_urls", [])

        for i, doc_data in enumerate(doc_urls):
            local_path = accumulated_data["downloaded_paths"].get(i)
            opinions.append(
                MontanaOpinion(
                    download_url=doc_data["url"],
                    doc_id=doc_data.get("doc_id"),
                    local_path=local_path,
                )
            )

        date_filed = datetime.fromisoformat(
            accumulated_data["date_filed"]
        ).date()

        cluster = MontanaOpinionCluster(
            docket_id=accumulated_data["docket_id"],
            court_id=accumulated_data["court_id"],
            date_filed=date_filed,
            case_name=accumulated_data["case_name"],
            opinions=opinions,
            source_url=accumulated_data["source_url"],
            case_info_url=accumulated_data.get("case_info_url"),
            document_description=accumulated_data.get("document_description"),
            case_type=accumulated_data.get("case_type"),
            precedential_status="Unknown",
        )

        yield ParsedData(cluster)
