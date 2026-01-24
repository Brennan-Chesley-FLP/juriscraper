"""Nevada Appellate Courts Scraper.

This module scrapes opinions from the Nevada Supreme Court and Court of Appeals
using their decisions pages at nvcourts.gov.

Entry points::

    - Advance Opinions: https://nvcourts.gov/supreme/decisions/advance_opinions
    - Unpublished Orders: https://nvcourts.gov/supreme/decisions/unpublished_orders

Flow::

    1. get_entry -> Navigate to opinions list page
    2. parse_opinions_list -> Parse table, yield ArchiveRequests for PDFs
    3. handle_opinion_download -> Yield final NevadaOpinionCluster

Design decisions::

    - Parses HTML tables for opinion metadata (case number, title, date, PDF link)
    - Uses DateRange filter on date_filed for searching
    - Uses SetFilter on court_id to select which courts to scrape
    - Advance opinions are published; unpublished orders are not precedential
    - Nevada uses 5-digit case numbers (e.g., 88998)
    - Both courts share the same pages (deflective model - Supreme Court assigns
      approximately 1/3 of cases to Court of Appeals)

Note:
    The site doesn't distinguish between Supreme Court and Court of Appeals
    opinions on the list pages - both are intermixed. The court is determined
    by examining the opinion itself, which is beyond the scope of this scraper.
    For now, we assign all opinions to 'nev' (Supreme Court) as the default.
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
    NavigatingRequest,
    ParsedData,
    Response,
    ScraperStatus,
)

from .models import (
    ADVANCE_OPINIONS_URL,
    UNPUBLISHED_ORDERS_URL,
    NevadaOpinion,
    NevadaOpinionCluster,
)

if TYPE_CHECKING:
    from collections.abc import Generator

    from juriscraper.scraper_driver.data_types import ScraperYield


class NevadaScraper(BaseScraper[NevadaOpinionCluster]):
    """Scraper for Nevada appellate court opinions.

    Scrapes published opinions (advance opinions) and unpublished orders
    from the Nevada Supreme Court and Court of Appeals.

    Usage:
        # Scrape all opinions from both courts
        scraper = NevadaScraper()

        # Scrape only Supreme Court opinions
        params = NevadaScraper.params()
        params.NevadaOpinionCluster.court_id.values = {"nev"}
        scraper = NevadaScraper(params=params)

        # Scrape only Court of Appeals opinions
        params = NevadaScraper.params()
        params.NevadaOpinionCluster.court_id.values = {"nevapp"}
        scraper = NevadaScraper(params=params)

        # Filter opinions by date range
        params = NevadaScraper.params()
        params.NevadaOpinionCluster.date_filed.gte = date(2026, 1, 1)
        params.NevadaOpinionCluster.date_filed.lte = date(2026, 1, 31)
        scraper = NevadaScraper(params=params)
    """

    # === Metadata ===
    court_ids: ClassVar[set[str]] = {"nev", "nevapp"}
    court_url: ClassVar[str] = "https://nvcourts.gov/supreme"
    data_types: ClassVar[set[str]] = {"opinions"}
    status: ClassVar[ScraperStatus] = ScraperStatus.IN_DEVELOPMENT
    version: ClassVar[str] = "2026-01-23"
    requires_auth: ClassVar[bool] = False

    # Rate limiting - be respectful to court servers
    msec_per_request_rate_limit: ClassVar[int] = 1000

    # === Regex patterns ===
    # Date pattern: "Jan 15, 2026" or "January 15, 2026"
    DATE_PATTERN = re.compile(r"(\w+)\s+(\d{1,2}),?\s+(\d{4})")

    # Month names mapping
    MONTHS = {
        "jan": 1,
        "january": 1,
        "feb": 2,
        "february": 2,
        "mar": 3,
        "march": 3,
        "apr": 4,
        "april": 4,
        "may": 5,
        "jun": 6,
        "june": 6,
        "jul": 7,
        "july": 7,
        "aug": 8,
        "august": 8,
        "sep": 9,
        "sept": 9,
        "september": 9,
        "oct": 10,
        "october": 10,
        "nov": 11,
        "november": 11,
        "dec": 12,
        "december": 12,
    }

    # Case number pattern (5 digits)
    CASE_NUMBER_PATTERN = re.compile(r"^\d{5}$")

    # Mapping from model name to data type
    MODEL_TO_DATA_TYPE: ClassVar[dict[str, str]] = {
        "NevadaOpinionCluster": "opinions",
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
            model_proxy = self._params.NevadaOpinionCluster
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

    def _parse_date(self, date_str: str) -> date | None:
        """Parse date from format like 'Jan 15, 2026'.

        Args:
            date_str: Date string in various formats.

        Returns:
            Parsed date or None if parsing fails.
        """
        date_str = date_str.strip()

        match = self.DATE_PATTERN.search(date_str)
        if not match:
            return None

        try:
            month_str = match.group(1).lower()
            day = int(match.group(2))
            year = int(match.group(3))

            month = self.MONTHS.get(month_str)
            if month is None:
                return None

            return date(year, month, day)
        except (ValueError, IndexError):
            return None

    # =========================================================================
    # Entry Point
    # =========================================================================

    def get_entry(self) -> Generator[NavigatingRequest, None, None]:
        """Yield initial requests to opinions list pages."""
        requested = self._get_requested_data_types()

        if "opinions" in requested:
            # Scrape advance opinions (published)
            yield NavigatingRequest(
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url=ADVANCE_OPINIONS_URL,
                ),
                continuation=self.parse_advance_opinions,
                accumulated_data={
                    "opinion_type": "advance_opinion",
                    "precedential_status": "Published",
                },
            )

            # Scrape unpublished orders
            yield NavigatingRequest(
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url=UNPUBLISHED_ORDERS_URL,
                ),
                continuation=self.parse_unpublished_orders,
                accumulated_data={
                    "opinion_type": "unpublished_order",
                    "precedential_status": "Unpublished",
                },
            )

    # =========================================================================
    # Advance Opinions Parsing
    # =========================================================================

    @step(xsd="xsds/parse_advance_opinions.xsd")
    def parse_advance_opinions(
        self,
        lxml_tree: CheckedHtmlElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[NevadaOpinionCluster], None, None]:
        """Parse the advance opinions page.

        Table structure:
        - Column 1: Advance No.
        - Column 2: Case Number Access to Docket (links to docket)
        - Column 3: Case Title
        - Column 4: Date of Opinion Link to Opinion (contains PDF link)
        """
        date_gte, date_lte, target_docket, court_ids = (
            self._get_search_params()
        )
        opinion_type = accumulated_data.get("opinion_type", "advance_opinion")
        precedential_status = accumulated_data.get(
            "precedential_status", "Published"
        )

        # Find all table rows (skip header)
        # The table has headers: Advance No., Case Number..., Case Title, Date...
        rows = lxml_tree.xpath("//table//tr[td]")

        for row in rows:
            # Get all cells in this row
            cells = row.xpath("td")
            if len(cells) < 4:
                continue

            # Extract advance number (column 1)
            advance_no_text = cells[0].text_content().strip()
            try:
                advance_number = int(advance_no_text)
            except ValueError:
                advance_number = None

            # Extract case number (column 2) - may be a link
            case_number_links = cells[1].xpath(".//a")
            if case_number_links:
                docket_number = case_number_links[0].text_content().strip()
            else:
                docket_number = cells[1].text_content().strip()

            # Validate case number format
            if not self.CASE_NUMBER_PATTERN.match(docket_number):
                continue

            # Filter by specific docket if requested
            if target_docket and docket_number != target_docket:
                continue

            # Extract case title (column 3)
            case_name = cells[2].text_content().strip()

            # Extract date and PDF link (column 4)
            date_links = cells[3].xpath(".//a")
            if not date_links:
                continue

            date_link = date_links[0]
            date_text = date_link.text_content().strip()
            pdf_url = date_link.get("href", "")

            # Parse the date
            date_filed = self._parse_date(date_text)
            if date_filed is None:
                continue

            # Filter by date range
            if date_gte and date_filed < date_gte:
                continue
            if date_lte and date_filed > date_lte:
                continue

            # Build full PDF URL if relative
            if pdf_url.startswith("/"):
                pdf_url = f"https://nvcourts.gov{pdf_url}"

            # For Nevada, we default to Supreme Court since the pages
            # don't distinguish between courts
            court_id = "nev"

            # Check court filter
            if court_ids and court_id not in court_ids:
                continue

            # Build cluster data for download
            cluster_data = {
                "docket_number": docket_number,
                "court_id": court_id,
                "date_filed": date_filed.isoformat(),
                "case_name": case_name,
                "source_url": response.url,
                "advance_number": advance_number,
                "precedential_status": precedential_status,
                "opinion_type": opinion_type,
                "pdf_url": pdf_url,
            }

            # Yield ArchiveRequest for the PDF
            yield ArchiveRequest(
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url=pdf_url,
                ),
                continuation=self.handle_opinion_download,
                expected_type="pdf",
                accumulated_data=cluster_data,
            )

    # =========================================================================
    # Unpublished Orders Parsing
    # =========================================================================

    @step(xsd="xsds/parse_unpublished_orders.xsd")
    def parse_unpublished_orders(
        self,
        lxml_tree: CheckedHtmlElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[NevadaOpinionCluster], None, None]:
        """Parse the unpublished orders page.

        Table structure:
        - Column 1: Case Number (links to docket)
        - Column 2: Case Title
        - Column 3: Date (contains PDF link)
        """
        date_gte, date_lte, target_docket, court_ids = (
            self._get_search_params()
        )
        opinion_type = accumulated_data.get(
            "opinion_type", "unpublished_order"
        )
        precedential_status = accumulated_data.get(
            "precedential_status", "Unpublished"
        )

        # Find all table rows (skip header)
        rows = lxml_tree.xpath("//table//tr[td]")

        for row in rows:
            # Get all cells in this row
            cells = row.xpath("td")
            if len(cells) < 3:
                continue

            # Extract case number (column 1) - may be a link
            case_number_links = cells[0].xpath(".//a")
            if case_number_links:
                docket_number = case_number_links[0].text_content().strip()
            else:
                docket_number = cells[0].text_content().strip()

            # Validate case number format
            if not self.CASE_NUMBER_PATTERN.match(docket_number):
                continue

            # Filter by specific docket if requested
            if target_docket and docket_number != target_docket:
                continue

            # Extract case title (column 2)
            case_name = cells[1].text_content().strip()

            # Extract date and PDF link (column 3)
            date_links = cells[2].xpath(".//a")
            if not date_links:
                continue

            date_link = date_links[0]
            date_text = date_link.text_content().strip()
            pdf_url = date_link.get("href", "")

            # Parse the date
            date_filed = self._parse_date(date_text)
            if date_filed is None:
                continue

            # Filter by date range
            if date_gte and date_filed < date_gte:
                continue
            if date_lte and date_filed > date_lte:
                continue

            # Build full PDF URL if relative
            if pdf_url.startswith("/"):
                pdf_url = f"https://nvcourts.gov{pdf_url}"

            # For Nevada, we default to Supreme Court
            court_id = "nev"

            # Check court filter
            if court_ids and court_id not in court_ids:
                continue

            # Build cluster data for download
            cluster_data = {
                "docket_number": docket_number,
                "court_id": court_id,
                "date_filed": date_filed.isoformat(),
                "case_name": case_name,
                "source_url": response.url,
                "advance_number": None,
                "precedential_status": precedential_status,
                "opinion_type": opinion_type,
                "pdf_url": pdf_url,
            }

            # Yield ArchiveRequest for the PDF
            yield ArchiveRequest(
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url=pdf_url,
                ),
                continuation=self.handle_opinion_download,
                expected_type="pdf",
                accumulated_data=cluster_data,
            )

    # =========================================================================
    # Download Handler
    # =========================================================================

    @step
    def handle_opinion_download(
        self,
        response: ArchiveResponse,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[NevadaOpinionCluster], None, None]:
        """Handle a downloaded opinion PDF and yield the final cluster."""
        from datetime import datetime

        # Parse date from ISO format
        date_filed = datetime.fromisoformat(
            accumulated_data["date_filed"]
        ).date()

        # Create opinion object
        opinion = NevadaOpinion(
            download_url=accumulated_data["pdf_url"],
            type=accumulated_data.get("opinion_type", "unknown"),
            local_path=response.file_url,
            advance_number=accumulated_data.get("advance_number"),
        )

        # Create the cluster
        cluster = NevadaOpinionCluster(
            docket_number=accumulated_data["docket_number"],
            court_id=accumulated_data["court_id"],
            date_filed=date_filed,
            case_name=accumulated_data["case_name"],
            opinions=[opinion],
            source_url=accumulated_data.get("source_url"),
            advance_number=accumulated_data.get("advance_number"),
            precedential_status=accumulated_data.get(
                "precedential_status", "Unknown"
            ),
        )

        yield ParsedData(cluster)
