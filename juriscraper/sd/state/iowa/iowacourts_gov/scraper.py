"""Iowa Appellate Courts Scraper.

This module scrapes opinions from the Iowa Supreme Court and
Iowa Court of Appeals using their public website.

Entry points:
- Supreme Court: https://www.iowacourts.gov/iowa-courts/supreme-court/supreme-court-opinions/
- Court of Appeals: https://www.iowacourts.gov/iowa-courts/court-of-appeals/court-of-appeals-court-opinions/

Flow:
1. get_entry -> Opinions listing page for each enabled court
2. parse_opinion_list -> Extracts case links, yields requests to detail pages
3. parse_case_detail -> Extracts case metadata, yields ArchiveRequest for PDF
4. handle_opinion_download -> Yields final IowaOpinionCluster

Design decisions:
- Scrapes from opinion listing pages which show 12 opinions per page
- Follows links to case detail pages to get full metadata (county, attorneys, summary)
- PDF URLs extracted from case detail page (internal ID required)
- Supports filtering by court (iowa, iowactapp) and date range
- Pagination handled by following "Next" links
"""

from __future__ import annotations

import re
from datetime import date, datetime
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
    COURT_IDS,
    COURT_OPINION_TYPE,
    COURT_URLS,
    IowaOpinion,
    IowaOpinionCluster,
)

if TYPE_CHECKING:
    from collections.abc import Generator

    from kent.data_types import ScraperYield


# Base URL
BASE_URL = "https://www.iowacourts.gov"


class IowaScraper(BaseScraper[IowaOpinionCluster]):
    """Scraper for Iowa appellate court opinions.

    Scrapes opinions from the Iowa Supreme Court (iowa) and
    Court of Appeals (iowactapp).

    Usage:
        # Scrape all opinions from both courts
        scraper = IowaScraper()

        # Scrape only Supreme Court opinions
        params = IowaScraper.params()
        params.IowaOpinionCluster.court_id.values = {"iowa"}
        scraper = IowaScraper(params=params)

        # Scrape only Court of Appeals opinions
        params = IowaScraper.params()
        params.IowaOpinionCluster.court_id.values = {"iowactapp"}
        scraper = IowaScraper(params=params)

        # Filter opinions by date range
        params = IowaScraper.params()
        params.IowaOpinionCluster.date_filed.gte = date(2026, 1, 1)
        params.IowaOpinionCluster.date_filed.lte = date(2026, 1, 31)
        scraper = IowaScraper(params=params)
    """

    # === Metadata ===
    court_ids: ClassVar[set[str]] = {"iowa", "iowactapp"}
    court_url: ClassVar[str] = "https://www.iowacourts.gov/"
    data_types: ClassVar[set[str]] = {"opinions"}
    status: ClassVar[ScraperStatus] = ScraperStatus.IN_DEVELOPMENT
    version: ClassVar[str] = "2026-01-22"
    requires_auth: ClassVar[bool] = False

    # Rate limiting - be respectful to court servers
    msec_per_request_rate_limit: ClassVar[int] = 1000

    # === Regex patterns ===
    # Case number pattern: YY-NNNN (e.g., 23-1794, 24-0249)
    CASE_NUMBER_PATTERN = re.compile(r"(\d{2})-(\d{4})")

    # Date parsing pattern (e.g., "Filed Jan 09, 2026")
    DATE_PATTERN = re.compile(r"Filed\s+(\w{3})\s+(\d{1,2}),\s+(\d{4})")

    # Internal ID pattern from PDF URL (e.g., /courtcases/22626/embed/...)
    INTERNAL_ID_PATTERN = re.compile(r"/courtcases/(\d+)/")

    # Mapping from model name to data type
    MODEL_TO_DATA_TYPE: ClassVar[dict[str, str]] = {
        "IowaOpinionCluster": "opinions",
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
            model_proxy = self._params.IowaOpinionCluster
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

    def _parse_date(self, date_str: str) -> date | None:
        """Parse date from 'Filed Jan 09, 2026' format.

        Args:
            date_str: Date string like 'Filed Jan 09, 2026'

        Returns:
            Parsed date or None
        """
        match = self.DATE_PATTERN.search(date_str)
        if not match:
            return None

        month_str, day_str, year_str = match.groups()
        month_map = {
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
        month = month_map.get(month_str)
        if month is None:
            return None

        try:
            return date(int(year_str), month, int(day_str))
        except ValueError:
            return None

    def _extract_internal_id(self, url: str) -> int | None:
        """Extract internal case ID from a URL.

        Args:
            url: URL like '/courtcases/22626/embed/SupremeCourtOpinion'

        Returns:
            Internal ID (e.g., 22626) or None
        """
        match = self.INTERNAL_ID_PATTERN.search(url)
        if match:
            return int(match.group(1))
        return None

    # =========================================================================
    # Entry Point
    # =========================================================================

    @entry(IowaOpinionCluster)
    def get_entry(self) -> Generator[NavigatingRequest, None, None]:
        """Yield initial requests to opinion listing pages for each court."""
        requested = self._get_requested_data_types()

        if "opinions" not in requested:
            return

        _, _, _, court_ids = self._get_search_params()

        # Default to all courts if none specified
        if court_ids is None:
            court_ids = set(COURT_IDS.keys())

        for court_id in court_ids:
            if court_id not in COURT_URLS:
                continue

            yield NavigatingRequest(
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url=COURT_URLS[court_id],
                ),
                continuation=self.parse_opinion_list,
                accumulated_data={"court_id": court_id},
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
    ) -> Generator[ScraperYield[IowaOpinionCluster], None, None]:
        """Parse the opinion listing page and yield requests for case details."""
        court_id = accumulated_data["court_id"]
        date_gte, date_lte, target_docket, _ = self._get_search_params()

        # Find all case entries - they're in h3 elements with case number links
        # The structure is: h3 (case heading) -> p (date) -> p (view opinion link)
        case_headings = lxml_tree.checked_xpath(
            "//h3[contains(@class, '') and .//a[contains(@href, '/case/')]]",
            "case headings",
            min_count=0,
        )

        reached_date_boundary = False

        for heading in case_headings:
            # Extract case link and number
            case_links = heading.checked_xpath(
                ".//a[contains(@href, '/case/')]/@href",
                "case detail link",
                min_count=1,
                max_count=1,
                type=str,
            )
            case_url = urljoin(response.url, case_links[0])

            # Extract case number from heading text
            heading_text = heading.checked_xpath(
                ".//a/text()",
                "case heading text",
                min_count=1,
                type=str,
            )
            # Text is like "Case No. 23-1794:" - extract the number
            case_text = "".join(heading_text).strip()
            case_number_match = self.CASE_NUMBER_PATTERN.search(case_text)
            if not case_number_match:
                continue
            case_number = case_number_match.group(0)

            # Filter by specific docket if specified
            if target_docket and case_number != target_docket:
                continue

            # Extract case name (in emphasis tag)
            case_name_parts = heading.checked_xpath(
                ".//em/text() | .//i/text()",
                "case name",
                min_count=0,
                type=str,
            )
            case_name = (
                " ".join(case_name_parts).strip()
                if case_name_parts
                else "Unknown"
            )

            # Get the next sibling paragraph with the date
            # Using XPath following-sibling
            parent = heading.getparent()
            if parent is None:
                continue

            # Find the date paragraph - should be right after the heading
            date_paras = heading.checked_xpath(
                "following-sibling::p[1]/text()",
                "date paragraph",
                min_count=0,
                type=str,
            )
            date_text = "".join(date_paras).strip() if date_paras else ""
            filed_date = self._parse_date(date_text)

            if filed_date is None:
                continue

            # Filter by date range
            if date_gte and filed_date < date_gte:
                # Opinions are listed newest first, so if we're past the date range, stop
                reached_date_boundary = True
                continue
            if date_lte and filed_date > date_lte:
                # Skip opinions newer than our end date
                continue

            # Get the opinion PDF link to extract internal ID
            pdf_links = heading.checked_xpath(
                "following-sibling::p[2]//a[contains(@href, '/courtcases/')]/@href",
                "opinion PDF link",
                min_count=0,
                type=str,
            )
            internal_id = None
            pdf_url = None
            if pdf_links:
                pdf_url = urljoin(BASE_URL, pdf_links[0])
                internal_id = self._extract_internal_id(pdf_links[0])

            # Yield request to case detail page for full metadata
            yield NavigatingRequest(
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url=case_url,
                ),
                continuation=self.parse_case_detail,
                accumulated_data={
                    "court_id": court_id,
                    "case_number": case_number,
                    "case_name": case_name,
                    "date_filed": filed_date.isoformat(),
                    "internal_id": internal_id,
                    "pdf_url": pdf_url,
                    "source_url": response.url,
                },
            )

        # Handle pagination - look for "Next" link
        # Only continue if we haven't reached the date boundary
        if not reached_date_boundary:
            next_links = lxml_tree.checked_xpath(
                "//a[contains(text(), 'Next')]/@href",
                "next page link",
                min_count=0,
                type=str,
            )
            if next_links:
                next_url = urljoin(response.url, next_links[0])
                yield NavigatingRequest(
                    request=HTTPRequestParams(
                        method=HttpMethod.GET,
                        url=next_url,
                    ),
                    continuation=self.parse_opinion_list,
                    accumulated_data={"court_id": court_id},
                )

    # =========================================================================
    # Case Detail Parsing
    # =========================================================================

    @step(xsd="xsds/parse_case_detail.xsd")
    def parse_case_detail(
        self,
        lxml_tree: CheckedHtmlElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[IowaOpinionCluster], None, None]:
        """Parse the case detail page and yield ArchiveRequest for PDF."""
        court_id = accumulated_data["court_id"]
        case_number = accumulated_data["case_number"]
        case_name = accumulated_data["case_name"]
        date_filed_str = accumulated_data["date_filed"]
        internal_id = accumulated_data.get("internal_id")
        pdf_url = accumulated_data.get("pdf_url")
        source_url = accumulated_data["source_url"]

        # Try to extract additional metadata from detail page

        # County (format: "County: Polk")
        county = None
        county_elems = lxml_tree.checked_xpath(
            "//*[contains(text(), 'County:')]/text()",
            "county",
            min_count=0,
            type=str,
        )
        if county_elems:
            for text in county_elems:
                if "County:" in text:
                    county = text.replace("County:", "").strip()
                    break

        # Trial court case number (format: "Trial Court Case No.: LACL155126")
        trial_case_no = None
        trial_case_elems = lxml_tree.checked_xpath(
            "//*[contains(text(), 'Trial Court Case No.')]/text()",
            "trial court case number",
            min_count=0,
            type=str,
        )
        if trial_case_elems:
            for text in trial_case_elems:
                if "Trial Court Case No.:" in text:
                    trial_case_no = text.replace(
                        "Trial Court Case No.:", ""
                    ).strip()
                    break

        # Summary - first paragraph in the main content area
        summary = None
        summary_elems = lxml_tree.checked_xpath(
            "//h2[contains(text(), 'v.')]/following-sibling::p[1]/text()",
            "case summary",
            min_count=0,
            type=str,
        )
        if summary_elems:
            summary = " ".join(summary_elems).strip()
            if not summary or len(summary) < 20:
                summary = None

        # If we don't have a PDF URL yet, try to find it on the detail page
        if not pdf_url:
            opinion_type = COURT_OPINION_TYPE.get(
                court_id, "SupremeCourtOpinion"
            )
            pdf_links = lxml_tree.checked_xpath(
                f"//a[contains(@href, '/embed/{opinion_type}')]/@href",
                "opinion PDF link on detail page",
                min_count=0,
                type=str,
            )
            if pdf_links:
                pdf_url = urljoin(BASE_URL, pdf_links[0])
                if internal_id is None:
                    internal_id = self._extract_internal_id(pdf_links[0])

        if not pdf_url:
            # No PDF found - skip this case
            return

        # Build accumulated data for download handler
        cluster_data = {
            "docket_id": case_number,
            "court_id": court_id,
            "date_filed": date_filed_str,
            "case_name": case_name,
            "source_url": source_url,
            "county": county,
            "trial_court_case_number": trial_case_no,
            "summary": summary,
            "internal_id": internal_id,
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
    ) -> Generator[ScraperYield[IowaOpinionCluster], None, None]:
        """Handle downloaded opinion PDF and yield final cluster."""
        date_filed = datetime.fromisoformat(
            accumulated_data["date_filed"]
        ).date()

        opinion = IowaOpinion(
            download_url=accumulated_data["pdf_url"],
            type="opinion",
            local_path=response.file_url,
        )

        cluster = IowaOpinionCluster(
            docket_id=accumulated_data["docket_id"],
            court_id=accumulated_data["court_id"],
            date_filed=date_filed,
            case_name=accumulated_data["case_name"],
            opinions=[opinion],
            source_url=accumulated_data["source_url"],
            county=accumulated_data.get("county"),
            trial_court_case_number=accumulated_data.get(
                "trial_court_case_number"
            ),
            summary=accumulated_data.get("summary"),
            internal_id=accumulated_data.get("internal_id"),
            precedential_status="Published",  # Iowa publishes all appellate opinions
        )

        yield ParsedData(cluster)
