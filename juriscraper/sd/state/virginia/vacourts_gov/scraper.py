"""Virginia Appellate Courts Opinion Scraper.

This module contains a unified scraper for opinions from Virginia courts:
- Supreme Court of Virginia (va)
- Court of Appeals of Virginia (vactapp) - both published and unpublished

Entry points::

  - Supreme Court: https://www.vacourts.gov/scndex
    (redirects to https://webdev.vacourts.gov/dynamic/scndex.htm)
  - Court of Appeals Published: https://www.vacourts.gov/wpcap
    (redirects to https://webdev.vacourts.gov/dynamic/wpcap.htm)
  - Court of Appeals Unpublished: https://www.vacourts.gov/wpcau
    (redirects to https://webdev.vacourts.gov/dynamic/wpcau.htm)

PDF URL patterns::

  - Supreme Court: https://www.vacourts.gov/opinions/opnscvwp/1{case_number}.pdf
  - Court of Appeals: https://www.vacourts.gov/opinions/opncavwp/{case_number}.pdf

Page structure::

  - Opinions are listed in <p> elements
  - Each <p> contains:

    - <a> link with case number text and href to PDF
    - <b> or plain text with case name
    - Date in MM/DD/YYYY format
    - Summary/disposition text

Flow::

  1. get_entry -> opinion index page(s) based on requested courts
  2. parse_opinions -> extracts opinion metadata from paragraph elements
  3. yields ArchiveRequests for PDFs
  4. handle_download -> stores local paths, yields final clusters

Design decisions::

  - Uses restrictive checked_xpaths to catch structural changes early
  - Uses DateRange filter on date_filed for searching
  - Uses SetFilter on court_id to select which courts to scrape
  - Archives opinion PDFs via ArchiveRequest
  - Scrapes all three opinion pages (va, vactapp published, vactapp unpublished)
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
    COURT_IDS,
    VaOpinion,
    VaOpinionCluster,
)

if TYPE_CHECKING:
    from collections.abc import Generator

    from kent.data_types import ScraperYield


class VirginiaScraper(BaseScraper[VaOpinionCluster]):
    """Unified scraper for Virginia appellate court opinions.

    Scrapes opinions from Supreme Court of Virginia and Court of Appeals.

    Usage::

        # Scrape all courts (default)
        scraper = VirginiaScraper()

        # Scrape only Supreme Court
        params = VirginiaScraper.params()
        params.VaOpinionCluster.court_id.values = {"va"}
        scraper = VirginiaScraper(params=params)

        # Scrape only Court of Appeals
        params = VirginiaScraper.params()
        params.VaOpinionCluster.court_id.values = {"vactapp"}
        scraper = VirginiaScraper(params=params)

        # Filter by date range
        params = VirginiaScraper.params()
        params.VaOpinionCluster.date_filed.gte = date(2026, 1, 1)
        params.VaOpinionCluster.date_filed.lte = date(2026, 1, 31)
        scraper = VirginiaScraper(params=params)

        # Lookup specific docket number
        params = VirginiaScraper.params()
        params.VaOpinionCluster.docket_number.value = "240736"
        scraper = VirginiaScraper(params=params)
    """

    # === Metadata ===
    court_ids: ClassVar[set[str]] = COURT_IDS
    court_url: ClassVar[str] = "https://www.vacourts.gov/"
    data_types: ClassVar[set[str]] = {"opinions"}
    status: ClassVar[ScraperStatus] = ScraperStatus.IN_DEVELOPMENT
    version: ClassVar[str] = "2026-01-23"
    requires_auth: ClassVar[bool] = False

    # Rate limiting - be respectful to court servers
    msec_per_request_rate_limit: ClassVar[int] = 1000

    # Opinion page URLs
    OPINION_URLS: ClassVar[dict[str, tuple[str, str, str]]] = {
        # key: (url, court_id, precedential_status)
        "va": (
            "https://www.vacourts.gov/scndex",
            "va",
            "published",
        ),
        "vactapp_published": (
            "https://www.vacourts.gov/wpcap",
            "vactapp",
            "published",
        ),
        "vactapp_unpublished": (
            "https://www.vacourts.gov/wpcau",
            "vactapp",
            "unpublished",
        ),
    }

    # === Regex patterns ===
    # Date pattern: MM/DD/YYYY or M/D/YYYY
    DATE_PATTERN = re.compile(r"(\d{1,2}/\d{1,2}/\d{4})")
    # Case number pattern (Supreme Court): 6 digits e.g., 240736
    VA_CASE_PATTERN = re.compile(r"^(\d{6})$")
    # Case number pattern (Court of Appeals): 7 digits e.g., 0350251
    VACTAPP_CASE_PATTERN = re.compile(r"^(\d{7})$")

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
            Tuple of (date_gte, date_lte, docket_number, court_ids)
        """
        if self._params is None:
            return None, None, None, None

        try:
            model_proxy = self._params.VaOpinionCluster
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

    def _get_target_pages(self) -> list[str]:
        """Get the list of opinion page keys to scrape based on court_ids filter.

        Returns list of page keys: 'va', 'vactapp_published', 'vactapp_unpublished'
        """
        _, _, _, court_ids = self._get_opinions_search_params()

        if court_ids:
            pages = []
            if "va" in court_ids:
                pages.append("va")
            if "vactapp" in court_ids:
                pages.extend(["vactapp_published", "vactapp_unpublished"])
            return pages if pages else ["va"]  # Default to Supreme Court

        # Default: all pages
        return ["va", "vactapp_published", "vactapp_unpublished"]

    # =========================================================================
    # Entry Point
    # =========================================================================

    @entry(VaOpinionCluster)
    def get_entry(self) -> Generator[NavigatingRequest, None, None]:
        """Yield initial requests for opinion scraping.

        Yields separate NavigatingRequests for each opinion page.
        """
        target_pages = self._get_target_pages()
        date_gte, date_lte, docket_number, _ = (
            self._get_opinions_search_params()
        )

        first_page = target_pages[0]
        remaining_pages = target_pages[1:]

        url, court_id, precedential_status = self.OPINION_URLS[first_page]

        yield NavigatingRequest(
            request=HTTPRequestParams(
                method=HttpMethod.GET,
                url=url,
            ),
            continuation=self.parse_opinions,
            accumulated_data={
                "page_key": first_page,
                "court_id": court_id,
                "precedential_status": precedential_status,
                "remaining_pages": remaining_pages,
                "docket_filter": docket_number,
                "date_gte": date_gte.isoformat() if date_gte else None,
                "date_lte": date_lte.isoformat() if date_lte else None,
            },
        )

    # =========================================================================
    # Opinion Page Parsing
    # =========================================================================

    @step(xsd="xsds/parse_opinions.xsd")
    def parse_opinions(
        self,
        lxml_tree: CheckedHtmlElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[VaOpinionCluster], None, None]:
        """Parse the opinion listing page.

        Extracts opinion metadata from paragraph elements and yields
        ArchiveRequests for each opinion PDF.

        Page structure:
        - Opinions are in <p> elements
        - Each <p> contains a link (<a>) to the PDF with case number text
        - Case name may be in <b> tags or plain text
        - Date and summary follow the case name
        """
        court_id = accumulated_data.get("court_id", "va")
        precedential_status = accumulated_data.get(
            "precedential_status", "published"
        )
        remaining_pages = accumulated_data.get("remaining_pages", [])
        docket_filter = accumulated_data.get("docket_filter")
        date_gte_str = accumulated_data.get("date_gte")
        date_lte_str = accumulated_data.get("date_lte")

        date_gte = date.fromisoformat(date_gte_str) if date_gte_str else None
        date_lte = date.fromisoformat(date_lte_str) if date_lte_str else None

        # Find all paragraphs containing opinion links
        # Each opinion is in a <p> with a link containing the case number
        opinion_paragraphs = lxml_tree.xpath(
            "//p[a[contains(@href, 'opinions/opn')]]"
        )

        for para in opinion_paragraphs:
            # Extract the PDF link
            pdf_links = para.xpath(".//a[contains(@href, '.pdf')]")
            if not pdf_links:
                continue

            pdf_link = pdf_links[0]
            pdf_href = pdf_link.get("href", "")
            pdf_url = urljoin(response.url, pdf_href)

            # Extract case/docket number from link text
            docket_number = pdf_link.text_content().strip()
            # Clean up: remove whitespace and any non-digit characters at edges
            docket_number = re.sub(r"\s+", "", docket_number)

            if not docket_number or not docket_number.isdigit():
                continue

            # Apply docket filter if specified
            if docket_filter and docket_number != docket_filter:
                continue

            # Get the full text content of the paragraph
            full_text = para.text_content()

            # Extract case name - look for text after the case number
            # Try to find case name in bold tags first
            bold_elements = para.xpath(".//b")
            case_name = None
            for bold in bold_elements:
                bold_text = bold.text_content().strip()
                # Case names typically contain "v." or "v "
                if bold_text and (
                    "v." in bold_text or " v " in bold_text.lower()
                ):
                    case_name = bold_text
                    break

            if not case_name:
                # Extract from full text after docket number
                # Pattern: case number + case name + date + summary
                # Find position after case number
                docket_pos = full_text.find(docket_number)
                if docket_pos >= 0:
                    after_docket = full_text[
                        docket_pos + len(docket_number) :
                    ].strip()
                    # Find the date to separate case name from summary
                    date_match = self.DATE_PATTERN.search(after_docket)
                    if date_match:
                        case_name = after_docket[: date_match.start()].strip()
                    else:
                        # Take first part as case name
                        case_name = after_docket[:100].strip()

            if not case_name:
                case_name = f"Case {docket_number}"

            # Extract date from full text
            date_filed = None
            date_match = self.DATE_PATTERN.search(full_text)
            if date_match:
                date_filed = self._parse_date(date_match.group(1))

            # Apply date filters
            if date_filed:
                if date_gte and date_filed < date_gte:
                    continue
                if date_lte and date_filed > date_lte:
                    continue

            # Extract summary - text after the date
            summary = None
            if date_match:
                summary = full_text[date_match.end() :].strip()
                # Clean up summary
                if summary:
                    # Remove excessive whitespace
                    summary = " ".join(summary.split())
                    # Limit length
                    if len(summary) > 2000:
                        summary = summary[:2000] + "..."

            # Build cluster data for accumulated_data
            cluster_data: dict[str, Any] = {
                "docket_number": docket_number,
                "court_id": court_id,
                "case_name": case_name,
                "precedential_status": precedential_status,
                "summary": summary,
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
                continuation=self.handle_download,
                expected_type="pdf",
                accumulated_data={
                    **cluster_data,
                    "current_download_index": 0,
                },
            )

        # Move to next page after processing this one
        if remaining_pages:
            next_page = remaining_pages[0]
            url, court_id, precedential_status = self.OPINION_URLS[next_page]

            yield NavigatingRequest(
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url=url,
                ),
                continuation=self.parse_opinions,
                accumulated_data={
                    "page_key": next_page,
                    "court_id": court_id,
                    "precedential_status": precedential_status,
                    "remaining_pages": remaining_pages[1:],
                    "docket_filter": docket_filter,
                    "date_gte": date_gte_str,
                    "date_lte": date_lte_str,
                },
            )

    # =========================================================================
    # PDF Download Handling
    # =========================================================================

    @step
    def handle_download(
        self,
        response: ArchiveResponse,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[VaOpinionCluster], None, None]:
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
            # Handle multiple PDFs per cluster (if needed in future)
            next_index = current_index + 1
            opinions_data = accumulated_data["opinions_data"]
            next_opinion = opinions_data[next_index]

            yield ArchiveRequest(
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url=next_opinion["download_url"],
                ),
                continuation=self.handle_download,
                expected_type="pdf",
                accumulated_data={
                    **accumulated_data,
                    "current_download_index": next_index,
                },
            )

    def _yield_final_cluster(
        self, accumulated_data: dict
    ) -> Generator[ScraperYield[VaOpinionCluster], None, None]:
        """Build and yield the final OpinionCluster with all PDFs downloaded."""
        opinions = []
        for i, op_data in enumerate(accumulated_data["opinions_data"]):
            local_path = accumulated_data["downloaded_paths"].get(i)
            opinions.append(
                VaOpinion(
                    download_url=op_data["download_url"],
                    type=op_data.get("type", "majority"),
                    local_path=local_path,
                )
            )

        date_filed = None
        if accumulated_data.get("date_filed"):
            date_filed = date.fromisoformat(accumulated_data["date_filed"])

        cluster = VaOpinionCluster(
            docket_number=accumulated_data["docket_number"],
            court_id=accumulated_data["court_id"],
            date_filed=date_filed,
            case_name=accumulated_data["case_name"],
            precedential_status=accumulated_data.get("precedential_status"),
            summary=accumulated_data.get("summary"),
            opinions=opinions,
            source_url=accumulated_data.get("source_url"),
        )

        yield ParsedData(cluster)
