"""Hawaii Appellate Courts Scraper.

This module scrapes opinions and orders from the Hawaii Supreme Court and
Intermediate Court of Appeals using their RSS feed.

Entry point:
- RSS Feed: https://www.courts.state.hi.us/opinions-orders/feed

Flow:
1. get_entry -> RSS feed URL (if "opinions" requested)
2. parse_rss_feed -> parses RSS items, yields ArchiveRequests for PDFs
3. handle_opinion_download -> yields final HawaiiOpinionCluster

Design decisions:
- Uses RSS feed as primary data source for reliability and efficiency
- RSS feed includes case name, court info, date, and related document links
- Each RSS item may reference related documents (e.g., prior ICA opinion for cert case)
- Uses DateRange filter on date_filed for searching
- Uses SetFilter on court_id to select which courts to scrape
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import TYPE_CHECKING, Any, ClassVar

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
    HawaiiOpinion,
    HawaiiOpinionCluster,
)

if TYPE_CHECKING:
    from collections.abc import Generator

    from juriscraper.scraper_driver.data_types import ScraperYield


# RSS feed URL
RSS_FEED_URL = "https://www.courts.state.hi.us/opinions-orders/feed"


class HawaiiScraper(BaseScraper[HawaiiOpinionCluster]):
    """Scraper for Hawaii appellate court opinions via RSS feed.

    Scrapes opinions and orders from the Hawaii Supreme Court (haw) and
    Intermediate Court of Appeals (hawapp).

    Usage:
        # Scrape all opinions from both courts
        scraper = HawaiiScraper()

        # Scrape only Supreme Court opinions
        params = HawaiiScraper.params()
        params.HawaiiOpinionCluster.court_id.values = {"haw"}
        scraper = HawaiiScraper(params=params)

        # Scrape only ICA opinions
        params = HawaiiScraper.params()
        params.HawaiiOpinionCluster.court_id.values = {"hawapp"}
        scraper = HawaiiScraper(params=params)

        # Filter opinions by date range
        params = HawaiiScraper.params()
        params.HawaiiOpinionCluster.date_filed.gte = date(2026, 1, 1)
        params.HawaiiOpinionCluster.date_filed.lte = date(2026, 1, 31)
        scraper = HawaiiScraper(params=params)
    """

    # === Metadata ===
    court_ids: ClassVar[set[str]] = {"haw", "hawapp"}
    court_url: ClassVar[str] = "https://www.courts.state.hi.us/"
    data_types: ClassVar[set[str]] = {"opinions"}
    status: ClassVar[ScraperStatus] = ScraperStatus.IN_DEVELOPMENT
    version: ClassVar[str] = "2026-01-22"
    requires_auth: ClassVar[bool] = False

    # Rate limiting - be respectful to court servers
    msec_per_request_rate_limit: ClassVar[int] = 1000

    # === Regex patterns ===
    # Case number pattern: CAAP-YY-XXXXXXX, SCWC-YY-XXXXXXX, SCPW-YY-XXXXXXX
    CASE_NUMBER_PATTERN = re.compile(r"(CAAP|SCWC|SCPW)-(\d{2})-(\d{7})")

    # Opinion type suffix pattern (from PDF filename)
    OPINION_TYPE_PATTERN = re.compile(
        r"(sdo|dso|mop|ord|certrej|certerej|recond|recong|dsm)\.pdf$",
        re.IGNORECASE,
    )

    # Date parsing pattern from RSS pubDate
    RSS_DATE_PATTERN = re.compile(
        r"(\w{3}),\s+(\d{1,2})\s+(\w{3})\s+(\d{4})\s+(\d{2}):(\d{2}):(\d{2})"
    )

    # HTML link pattern in description CDATA
    HTML_LINK_PATTERN = re.compile(
        r'<a\s+href="([^"]+)"[^>]*>([^<]+)</a>',
        re.IGNORECASE,
    )

    # Issued by pattern (number of judges)
    ISSUED_BY_PATTERN = re.compile(r"Issued by:\s*(\d+)")

    # Appealed from pattern
    APPEALED_FROM_PATTERN = re.compile(r"Appealed from:\s*([^<]+)")

    # Mapping from model name to data type
    MODEL_TO_DATA_TYPE: ClassVar[dict[str, str]] = {
        "HawaiiOpinionCluster": "opinions",
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
            model_proxy = self._params.HawaiiOpinionCluster
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
            case_number: Case number like 'CAAP-23-0000347' or 'SCWC-24-0000450'

        Returns:
            Court ID ('haw' or 'hawapp') or None if unrecognized
        """
        match = self.CASE_NUMBER_PATTERN.match(case_number)
        if match:
            prefix = match.group(1)
            return CASE_PREFIX_TO_COURT.get(prefix)
        return None

    def _get_opinion_type_from_url(self, url: str) -> str:
        """Extract opinion type from PDF URL suffix.

        Args:
            url: PDF URL like '.../CAAP-23-0000347sdo.pdf'

        Returns:
            Opinion type string (e.g., 'sdo', 'ord', 'certrej')
        """
        match = self.OPINION_TYPE_PATTERN.search(url)
        if match:
            return match.group(1).lower()
        return "unknown"

    def _parse_rss_date(self, date_str: str) -> date | None:
        """Parse RSS pubDate format.

        Args:
            date_str: Date like 'Thu, 22 Jan 2026 20:21:36 +0000'

        Returns:
            Parsed date or None
        """
        try:
            # Parse RFC 2822 date format
            dt = datetime.strptime(
                date_str.strip(), "%a, %d %b %Y %H:%M:%S %z"
            )
            return dt.date()
        except ValueError:
            return None

    def _parse_description(
        self, description: str
    ) -> tuple[str, str | None, str | None, list[str]]:
        """Parse RSS item description CDATA content.

        Args:
            description: HTML content from RSS description field

        Returns:
            Tuple of (case_name, appealed_from, issued_by, related_urls)
        """
        # Extract case name - first <p> content before any HTML tags
        # Format: "Fung v. Hoi (s.d.o., affirmed)."
        case_name = "Unknown"

        # Remove CDATA markers if present
        description = description.replace("<![CDATA[", "").replace("]]>", "")

        # Extract text before first HTML tag or parenthetical
        # The case name is typically at the start, like "Fung v. Hoi"
        first_p = re.search(r"<p[^>]*>(.*?)</p>", description, re.DOTALL)
        if first_p:
            content = first_p.group(1)
            # Get text before parenthetical and strip HTML tags
            name_match = re.match(r"([^(]+)", content)
            if name_match:
                # Strip HTML tags from the name
                raw_name = re.sub(r"<[^>]+>", "", name_match.group(1)).strip()
                # Remove trailing punctuation
                case_name = raw_name.rstrip(". ")
                if case_name:
                    pass  # Keep extracted name
                else:
                    case_name = "Unknown"

        # Extract appealed from
        appealed_from = None
        appealed_match = self.APPEALED_FROM_PATTERN.search(description)
        if appealed_match:
            appealed_from = appealed_match.group(1).strip().rstrip("</p> ")

        # Extract issued by
        issued_by = None
        issued_match = self.ISSUED_BY_PATTERN.search(description)
        if issued_match:
            issued_by = issued_match.group(1)

        # Extract related document URLs
        related_urls = []
        for link_match in self.HTML_LINK_PATTERN.finditer(description):
            url = link_match.group(1)
            if url and url.endswith(".pdf"):
                related_urls.append(url)

        return case_name, appealed_from, issued_by, related_urls

    # =========================================================================
    # Entry Point
    # =========================================================================

    def get_entry(self) -> Generator[NavigatingRequest, None, None]:
        """Yield initial request to RSS feed."""
        requested = self._get_requested_data_types()

        if "opinions" in requested:
            yield NavigatingRequest(
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url=RSS_FEED_URL,
                ),
                continuation=self.parse_rss_feed,
            )

    # =========================================================================
    # RSS Feed Parsing
    # =========================================================================

    @step(xsd="xsds/parse_rss_feed.xsd")
    def parse_rss_feed(
        self,
        lxml_tree: CheckedHtmlElement,
        response: Response,
    ) -> Generator[ScraperYield[HawaiiOpinionCluster], None, None]:
        """Parse RSS feed and yield requests for each opinion."""
        date_gte, date_lte, target_docket, court_ids = (
            self._get_search_params()
        )

        # Find all <item> elements in the RSS feed
        items = lxml_tree.checked_xpath(
            "//item",
            "RSS items",
            min_count=0,
        )

        for item in items:
            # Extract title (case number)
            title_elems = item.checked_xpath(
                "title/text()",
                "item title",
                min_count=1,
                max_count=1,
                type=str,
            )
            case_number = title_elems[0].strip()

            # Validate case number format
            if not self.CASE_NUMBER_PATTERN.match(case_number):
                continue

            # Determine court from case number
            court_id = self._get_court_id_from_case_number(case_number)
            if court_id is None:
                continue

            # Filter by court if specified
            if court_ids and court_id not in court_ids:
                continue

            # Filter by specific docket if specified
            if target_docket and case_number != target_docket:
                continue

            # Extract link (PDF URL)
            link_elems = item.checked_xpath(
                "link/text()",
                "item link",
                min_count=1,
                max_count=1,
                type=str,
            )
            pdf_url = link_elems[0].strip()

            # Extract pubDate
            pub_date_elems = item.checked_xpath(
                "pubDate/text()",
                "item pubDate",
                min_count=1,
                max_count=1,
                type=str,
            )
            pub_date_str = pub_date_elems[0].strip()
            pub_date = self._parse_rss_date(pub_date_str)

            if pub_date is None:
                continue

            # Filter by date range if specified
            if date_gte and pub_date < date_gte:
                continue
            if date_lte and pub_date > date_lte:
                continue

            # Extract description (contains case name, court info, related links)
            description_elems = item.checked_xpath(
                "description/text()",
                "item description",
                min_count=0,
                type=str,
            )
            description = description_elems[0] if description_elems else ""

            # Parse description for metadata
            case_name, appealed_from, issued_by, related_urls = (
                self._parse_description(description)
            )

            # Get opinion type from PDF URL
            opinion_type = self._get_opinion_type_from_url(pdf_url)

            # Build accumulated data for download handler
            cluster_data: dict[str, Any] = {
                "docket_id": case_number,
                "court_id": court_id,
                "date_filed": pub_date.isoformat(),
                "case_name": case_name,
                "source_url": response.url,
                "appealed_from": appealed_from,
                "issued_by": issued_by,
                "related_case_urls": related_urls,
                "opinions_data": [
                    {"download_url": pdf_url, "type": opinion_type}
                ],
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
    ) -> Generator[ScraperYield[HawaiiOpinionCluster], None, None]:
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
    ) -> Generator[ScraperYield[HawaiiOpinionCluster], None, None]:
        """Build and yield the final OpinionCluster with all PDFs downloaded."""
        opinions = []
        for i, op_data in enumerate(accumulated_data["opinions_data"]):
            local_path = accumulated_data["downloaded_paths"].get(i)
            opinions.append(
                HawaiiOpinion(
                    download_url=op_data["download_url"],
                    type=op_data["type"],
                    local_path=local_path,
                )
            )

        date_filed = datetime.fromisoformat(
            accumulated_data["date_filed"]
        ).date()

        cluster = HawaiiOpinionCluster(
            docket_id=accumulated_data["docket_id"],
            court_id=accumulated_data["court_id"],
            date_filed=date_filed,
            case_name=accumulated_data["case_name"],
            opinions=opinions,
            source_url=accumulated_data["source_url"],
            appealed_from=accumulated_data.get("appealed_from"),
            issued_by=accumulated_data.get("issued_by"),
            related_case_urls=accumulated_data.get("related_case_urls", []),
            precedential_status="Unknown",  # RSS feed doesn't indicate publication status
        )

        yield ParsedData(cluster)
