"""Illinois Appellate Courts Scraper.

This module scrapes opinions from the Illinois Supreme Court and
Appellate Court of Illinois using their RSS feeds.

Entry points (RSS Feeds):
- Supreme Court: https://www.illinoiscourts.gov/views/courts/rss/opinions-supreme.aspx
- Appellate Court: https://www.illinoiscourts.gov/views/courts/rss/opinions-appellate.aspx

Flow:
1. get_entry -> RSS feed URLs (based on requested courts/data types)
2. parse_rss_feed -> parses RSS items, yields ArchiveRequests for PDFs
3. handle_opinion_download -> yields final IllinoisOpinionCluster

RSS Feed Fields:
- <title>: Case name (e.g., "People v. Seymore")
- <link>: PDF URL
- <pubDate>: Publication date
- <category>: "Opinion" or "Rule 23"
- <opinion:casename>: Case name (same as title)
- <opinion:filingdate>: Filing date (M/D/YYYY format)
- <opinion:type>: Type (Opinion, Rule 23)
- <opinion:citationnum>: Citation (e.g., "2025 IL 131564")
- <opinion:docketstatus>: Status (Slip, Released, Final)
- <opinion:court>: Court name
- <opinion:notes>: HTML with link to summary PDF
- <opinion:pdf>: Direct PDF URL

Design decisions:
- Uses RSS feeds as primary data source for reliability and efficiency
- Both courts share the same RSS format with opinion: namespace
- Uses DateRange filter on date_filed for searching
- Uses SetFilter on court_id to select which courts to scrape
"""

from __future__ import annotations

import html
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
    COURT_NAME_TO_DISTRICT,
    COURT_NAME_TO_ID,
    IllinoisOpinion,
    IllinoisOpinionCluster,
)

if TYPE_CHECKING:
    from collections.abc import Generator

    from juriscraper.scraper_driver.data_types import ScraperYield


# RSS feed URLs
SUPREME_COURT_RSS = (
    "https://www.illinoiscourts.gov/views/courts/rss/opinions-supreme.aspx"
)
APPELLATE_COURT_RSS = (
    "https://www.illinoiscourts.gov/views/courts/rss/opinions-appellate.aspx"
)

# Namespace for opinion elements in RSS
OPINION_NS = "https://www.illinoiscourts.gov/top-level-opinions/"


class IllinoisScraper(BaseScraper[IllinoisOpinionCluster]):
    """Scraper for Illinois appellate court opinions via RSS feeds.

    Scrapes opinions from the Illinois Supreme Court (ill) and
    Appellate Court of Illinois (illappct) across all 5 districts.

    Usage:
        # Scrape all opinions from both courts
        scraper = IllinoisScraper()

        # Scrape only Supreme Court opinions
        params = IllinoisScraper.params()
        params.IllinoisOpinionCluster.court_id.values = {"ill"}
        scraper = IllinoisScraper(params=params)

        # Scrape only Appellate Court opinions
        params = IllinoisScraper.params()
        params.IllinoisOpinionCluster.court_id.values = {"illappct"}
        scraper = IllinoisScraper(params=params)

        # Filter opinions by date range
        params = IllinoisScraper.params()
        params.IllinoisOpinionCluster.date_filed.gte = date(2026, 1, 1)
        params.IllinoisOpinionCluster.date_filed.lte = date(2026, 1, 31)
        scraper = IllinoisScraper(params=params)
    """

    # === Metadata ===
    court_ids: ClassVar[set[str]] = {"ill", "illappct"}
    court_url: ClassVar[str] = "https://www.illinoiscourts.gov/"
    data_types: ClassVar[set[str]] = {"opinions"}
    status: ClassVar[ScraperStatus] = ScraperStatus.IN_DEVELOPMENT
    version: ClassVar[str] = "2026-01-22"
    requires_auth: ClassVar[bool] = False

    # Rate limiting - be respectful to court servers
    msec_per_request_rate_limit: ClassVar[int] = 1000

    # === Regex patterns ===
    # Summary URL pattern from opinion:notes HTML
    SUMMARY_URL_PATTERN = re.compile(
        r'href="([^"]+\.pdf)"',
        re.IGNORECASE,
    )

    # Mapping from model name to data type
    MODEL_TO_DATA_TYPE: ClassVar[dict[str, str]] = {
        "IllinoisOpinionCluster": "opinions",
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
            model_proxy = self._params.IllinoisOpinionCluster
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

    def _get_court_id_from_name(self, court_name: str) -> str | None:
        """Get CourtListener court ID from RSS court name.

        Args:
            court_name: Court name from RSS (e.g., 'Supreme Court',
                       'First District Appellate Court')

        Returns:
            Court ID ('ill' or 'illappct') or None if unrecognized
        """
        return COURT_NAME_TO_ID.get(court_name)

    def _get_district_from_name(self, court_name: str) -> str | None:
        """Get district from RSS court name.

        Args:
            court_name: Court name from RSS

        Returns:
            District string ('1st', '2d', '3d', '4th', '5th', 'WC')
            or None for Supreme Court
        """
        return COURT_NAME_TO_DISTRICT.get(court_name)

    def _parse_rss_date(self, date_str: str) -> date | None:
        """Parse RSS pubDate format.

        Args:
            date_str: Date like 'Thu, 22 Jan 2026 00:00:00 GMT'

        Returns:
            Parsed date or None
        """
        try:
            # Parse RFC 2822 date format
            dt = datetime.strptime(
                date_str.strip(),
                "%a, %d %b %Y %H:%M:%S %Z"
            )
            return dt.date()
        except ValueError:
            return None

    def _parse_filing_date(self, date_str: str) -> date | None:
        """Parse opinion:filingdate format.

        Args:
            date_str: Date like '1/22/2026' or '12/4/2025'

        Returns:
            Parsed date or None
        """
        try:
            dt = datetime.strptime(date_str.strip(), "%m/%d/%Y")
            return dt.date()
        except ValueError:
            return None

    def _extract_summary_url(self, notes_html: str) -> str | None:
        """Extract summary PDF URL from opinion:notes HTML.

        Args:
            notes_html: HTML content from opinion:notes field

        Returns:
            URL to summary PDF or None if not found
        """
        if not notes_html:
            return None

        # Decode HTML entities
        decoded = html.unescape(notes_html)
        match = self.SUMMARY_URL_PATTERN.search(decoded)
        if match:
            return match.group(1)
        return None

    def _should_fetch_feed(self, feed_court_id: str) -> bool:
        """Determine if we should fetch a specific RSS feed.

        Args:
            feed_court_id: The court_id for this feed ('ill' or 'illappct')

        Returns:
            True if we should fetch this feed
        """
        _, _, _, court_ids = self._get_search_params()
        if court_ids is None:
            # No filter, fetch all
            return True
        return feed_court_id in court_ids

    # =========================================================================
    # Entry Point
    # =========================================================================

    def get_entry(self) -> Generator[NavigatingRequest, None, None]:
        """Yield initial requests to RSS feeds."""
        requested = self._get_requested_data_types()

        if "opinions" not in requested:
            return

        # Check which feeds to fetch based on court_id filter
        if self._should_fetch_feed("ill"):
            yield NavigatingRequest(
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url=SUPREME_COURT_RSS,
                ),
                continuation=self.parse_rss_feed,
                accumulated_data={"feed_type": "supreme"},
            )

        if self._should_fetch_feed("illappct"):
            yield NavigatingRequest(
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url=APPELLATE_COURT_RSS,
                ),
                continuation=self.parse_rss_feed,
                accumulated_data={"feed_type": "appellate"},
            )

    # =========================================================================
    # RSS Feed Parsing
    # =========================================================================

    @step(xsd="xsds/parse_rss_feed.xsd")
    def parse_rss_feed(
        self,
        lxml_tree: CheckedHtmlElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[IllinoisOpinionCluster], None, None]:
        """Parse RSS feed and yield requests for each opinion."""
        date_gte, date_lte, target_docket, court_ids = self._get_search_params()

        # Find all <item> elements in the RSS feed
        # RSS feeds may have 0 items if no recent opinions
        items = lxml_tree.checked_xpath(
            "//item",
            "RSS items",
            min_count=0,
        )

        for item in items:
            # Extract GUID (unique identifier)
            guid_elems = item.checked_xpath(
                "guid/text()",
                "item guid",
                min_count=1,
                max_count=1,
                type=str,
            )
            guid = guid_elems[0].strip()

            # Extract category (Opinion or Rule 23)
            category_elems = item.checked_xpath(
                "category/text()",
                "item category",
                min_count=1,
                max_count=1,
                type=str,
            )
            category = category_elems[0].strip()

            # Extract title (case name)
            title_elems = item.checked_xpath(
                "title/text()",
                "item title",
                min_count=1,
                max_count=1,
                type=str,
            )
            case_name = title_elems[0].strip()

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

            # Extract opinion:* namespaced fields
            # Use local-name() to handle namespace
            casename_elems = item.checked_xpath(
                "*[local-name()='casename']/text()",
                "opinion:casename",
                min_count=0,
                type=str,
            )
            # Use casename from opinion namespace if available
            if casename_elems:
                case_name = casename_elems[0].strip()

            filingdate_elems = item.checked_xpath(
                "*[local-name()='filingdate']/text()",
                "opinion:filingdate",
                min_count=0,
                type=str,
            )
            filing_date = None
            if filingdate_elems:
                filing_date = self._parse_filing_date(filingdate_elems[0])
            # Use pub_date as fallback
            if filing_date is None:
                filing_date = pub_date
            if filing_date is None:
                # Skip items without a valid date
                continue

            type_elems = item.checked_xpath(
                "*[local-name()='type']/text()",
                "opinion:type",
                min_count=0,
                type=str,
            )
            opinion_type = type_elems[0].strip() if type_elems else category

            citation_elems = item.checked_xpath(
                "*[local-name()='citationnum']/text()",
                "opinion:citationnum",
                min_count=0,
                type=str,
            )
            citation = citation_elems[0].strip() if citation_elems else None
            if not citation:
                # Skip items without citation
                continue

            status_elems = item.checked_xpath(
                "*[local-name()='docketstatus']/text()",
                "opinion:docketstatus",
                min_count=0,
                type=str,
            )
            docket_status = status_elems[0].strip() if status_elems else None

            court_elems = item.checked_xpath(
                "*[local-name()='court']/text()",
                "opinion:court",
                min_count=0,
                type=str,
            )
            court_name = court_elems[0].strip() if court_elems else None
            if not court_name:
                continue

            # Determine court_id from court name
            court_id = self._get_court_id_from_name(court_name)
            if court_id is None:
                continue

            # Filter by court if specified
            if court_ids and court_id not in court_ids:
                continue

            # Filter by specific docket if specified
            if target_docket and citation != target_docket:
                continue

            # Filter by date range if specified
            if date_gte and filing_date < date_gte:
                continue
            if date_lte and filing_date > date_lte:
                continue

            # Extract notes (may contain summary link)
            notes_elems = item.checked_xpath(
                "*[local-name()='notes']/text()",
                "opinion:notes",
                min_count=0,
                type=str,
            )
            notes_html = notes_elems[0] if notes_elems else ""
            summary_url = self._extract_summary_url(notes_html)

            # Extract pdf URL from opinion namespace (more reliable)
            pdf_elems = item.checked_xpath(
                "*[local-name()='pdf']/text()",
                "opinion:pdf",
                min_count=0,
                type=str,
            )
            if pdf_elems:
                pdf_url = pdf_elems[0].strip()

            # Get district for appellate court
            district = self._get_district_from_name(court_name)

            # Build accumulated data for download handler
            cluster_data = {
                "docket_id": citation,
                "court_id": court_id,
                "date_filed": filing_date.isoformat(),
                "case_name": case_name,
                "source_url": response.url,
                "opinion_type": opinion_type,
                "docket_status": docket_status,
                "district": district,
                "summary_url": summary_url,
                "guid": guid,
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
    ) -> Generator[ScraperYield[IllinoisOpinionCluster], None, None]:
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
    ) -> Generator[ScraperYield[IllinoisOpinionCluster], None, None]:
        """Build and yield the final OpinionCluster with all PDFs downloaded."""
        opinions = []
        for i, op_data in enumerate(accumulated_data["opinions_data"]):
            local_path = accumulated_data["downloaded_paths"].get(i)
            opinions.append(
                IllinoisOpinion(
                    download_url=op_data["download_url"],
                    type=op_data["type"],
                    local_path=local_path,
                )
            )

        date_filed = datetime.fromisoformat(
            accumulated_data["date_filed"]
        ).date()

        cluster = IllinoisOpinionCluster(
            docket_id=accumulated_data["docket_id"],
            court_id=accumulated_data["court_id"],
            date_filed=date_filed,
            case_name=accumulated_data["case_name"],
            opinions=opinions,
            source_url=accumulated_data["source_url"],
            opinion_type=accumulated_data.get("opinion_type"),
            docket_status=accumulated_data.get("docket_status"),
            district=accumulated_data.get("district"),
            summary_url=accumulated_data.get("summary_url"),
            guid=accumulated_data.get("guid"),
            precedential_status=(
                "Published"
                if accumulated_data.get("opinion_type") == "Opinion"
                else "Unpublished"
            ),
        )

        yield ParsedData(cluster)
