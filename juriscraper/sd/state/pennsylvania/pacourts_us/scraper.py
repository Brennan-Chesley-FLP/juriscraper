"""Pennsylvania Appellate Courts Opinion Scraper.

This module contains a unified scraper for opinions from Pennsylvania courts:

- Supreme Court of Pennsylvania (pa)
- Superior Court of Pennsylvania (pasuperct)
- Commonwealth Court of Pennsylvania (pacommwct)

Entry point - RSS Feeds:

- Supreme Court: ``https://www.pacourts.us/Rss/Opinions/Supreme/``
- Superior Court: ``https://www.pacourts.us/Rss/Opinions/Superior/``
- Commonwealth Court: ``https://www.pacourts.us/Rss/Opinions/Commonwealth/``

RSS Feed structure - each ``<item>`` element contains:

- ``<title>``: Case name + docket number (e.g., "Com. v. Woodall, J. No. 876 WDA 2024")
- ``<link>``: Direct PDF URL
- ``<guid>``: PDF URL (for deduplication)
- ``<pubDate>``: Publication date in RFC 822 format
- ``<dc:creator>``: Author/judge name or "Per Curiam"
- ``<description>``: Empty CDATA (no abstract available)

PDF URL pattern: ``https://www.pacourts.us/assets/opinions/{Court}/out/{filename}.pdf``
where Court is "Supreme", "Superior", or "Commonwealth" and filename varies.

Flow:

1. get_entry -> RSS feed URLs for selected courts (if "opinions" requested)
2. parse_rss_feed -> extracts opinion metadata from RSS items
3. yields ArchiveRequests for PDFs
4. handle_opinion_download -> stores local paths, yields final clusters

Design decisions:

- Uses RSS feeds as primary data source for reliability and efficiency
- RSS feeds provide case name, docket number, date, author, and PDF URL
- Uses DateRange filter on date_filed for searching
- Uses SetFilter on court_id to select which courts to scrape
- Archives opinion PDFs via ArchiveRequest
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import TYPE_CHECKING, Any, ClassVar

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
    COURT_ID_TO_RSS_COURT,
    COURT_IDS,
    PennsylvaniaOpinion,
    PennsylvaniaOpinionCluster,
)

if TYPE_CHECKING:
    from collections.abc import Generator

    from juriscraper.scraper_driver.data_types import ScraperYield


# RSS feed URL template
RSS_FEED_URL_TEMPLATE = "https://www.pacourts.us/Rss/Opinions/{court}/"


class PennsylvaniaScraper(BaseScraper[PennsylvaniaOpinionCluster]):
    """Unified scraper for Pennsylvania appellate court opinions via RSS feeds.

    Scrapes opinions from Pennsylvania Supreme Court (pa), Superior Court
    (pasuperct), and Commonwealth Court (pacommwct).

    Usage:
        # Scrape all courts (default)
        scraper = PennsylvaniaScraper()

        # Scrape only Supreme Court
        params = PennsylvaniaScraper.params()
        params.PennsylvaniaOpinionCluster.court_id.values = {"pa"}
        scraper = PennsylvaniaScraper(params=params)

        # Scrape Superior and Commonwealth courts
        params = PennsylvaniaScraper.params()
        params.PennsylvaniaOpinionCluster.court_id.values = {"pasuperct", "pacommwct"}
        scraper = PennsylvaniaScraper(params=params)

        # Filter by date range
        params = PennsylvaniaScraper.params()
        params.PennsylvaniaOpinionCluster.date_filed.gte = date(2026, 1, 1)
        params.PennsylvaniaOpinionCluster.date_filed.lte = date(2026, 1, 31)
        scraper = PennsylvaniaScraper(params=params)

        # Lookup specific docket number
        params = PennsylvaniaScraper.params()
        params.PennsylvaniaOpinionCluster.docket_number.value = "95 MAP 2024"
        scraper = PennsylvaniaScraper(params=params)
    """

    # === Metadata ===
    court_ids: ClassVar[set[str]] = COURT_IDS
    court_url: ClassVar[str] = "https://www.pacourts.us/"
    data_types: ClassVar[set[str]] = {"opinions"}
    status: ClassVar[ScraperStatus] = ScraperStatus.IN_DEVELOPMENT
    version: ClassVar[str] = "2026-01-23"
    requires_auth: ClassVar[bool] = False

    # Rate limiting - be respectful to court servers
    msec_per_request_rate_limit: ClassVar[int] = 1000

    # === Regex patterns ===
    # Docket number patterns for each court type
    # Supreme Court: {Number} {TYPE} {YEAR} (e.g., "95 MAP 2024", "167 WAL 2025")
    # Superior Court: {Number} {TYPE} {YEAR} (e.g., "876 WDA 2024", "348 MDA 2025")
    # Commonwealth Court: {Number} {TYPE} {YEAR} (e.g., "918 C.D. 2024")
    DOCKET_PATTERN = re.compile(
        r"(?:No\.?\s*)?"
        r"(\d+\s+(?:MAP|MAL|WAL|EAL|EAP|WAP|WDA|MDA|EDA|C\.?D\.?|M\.?D\.?)\s+\d{4})"
    )

    # Pattern to extract case name from title (everything before "No." or docket number)
    CASE_NAME_PATTERN = re.compile(
        r"^(.+?)(?:\s*[-–—]\s*No\.|\s+No\.\s*\d|\s+\d+\s+(?:MAP|MAL|WAL|EAL|EAP|WAP|WDA|MDA|EDA|C\.?D\.?|M\.?D\.?))",
        re.IGNORECASE,
    )

    # Mapping from model name to data type
    MODEL_TO_DATA_TYPE: ClassVar[dict[str, str]] = {
        "PennsylvaniaOpinionCluster": "opinions",
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
            model_proxy = self._params.PennsylvaniaOpinionCluster
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

    def _get_target_courts(self) -> list[str]:
        """Get the list of court IDs to scrape based on params.

        Returns list of court IDs to scrape.
        """
        _, _, _, court_ids = self._get_search_params()

        if court_ids:
            # Filter to valid court IDs
            valid_courts = [cid for cid in court_ids if cid in COURT_IDS]
            return sorted(valid_courts) if valid_courts else ["pa"]

        # Default: All three appellate courts
        return sorted(COURT_IDS)

    def _parse_rss_date(self, date_str: str) -> date | None:
        """Parse RSS pubDate format (RFC 822).

        Args:
            date_str: Date like 'Thu, 22 Jan 2026 05:00:00 GMT'

        Returns:
            Parsed date or None
        """
        try:
            # Try RFC 822 format with timezone
            # Handle both "+0000" and "GMT" timezone formats
            date_str = date_str.strip()
            if date_str.endswith("GMT"):
                date_str = date_str.replace("GMT", "+0000")
            dt = datetime.strptime(date_str, "%a, %d %b %Y %H:%M:%S %z")
            return dt.date()
        except ValueError:
            pass

        try:
            # Try without timezone
            dt = datetime.strptime(
                date_str.strip()[:25], "%a, %d %b %Y %H:%M:%S"
            )
            return dt.date()
        except ValueError:
            return None

    def _extract_docket_number(self, title: str) -> str | None:
        """Extract docket number from RSS title.

        Args:
            title: RSS title like "Com. v. Woodall, J. No. 876 WDA 2024"

        Returns:
            Docket number like "876 WDA 2024" or None
        """
        match = self.DOCKET_PATTERN.search(title)
        if match:
            return match.group(1).strip()
        return None

    def _extract_case_name(self, title: str) -> str:
        """Extract case name from RSS title.

        Args:
            title: RSS title like "Com. v. Woodall, J. No. 876 WDA 2024"

        Returns:
            Case name like "Com. v. Woodall, J." or "Unknown"
        """
        match = self.CASE_NAME_PATTERN.match(title)
        if match:
            name = match.group(1).strip()
            # Remove trailing punctuation and whitespace
            name = name.rstrip(" -–—.,;:")
            if name:
                return name

        # Fallback: take everything before the last occurrence of a docket-like pattern
        docket_match = self.DOCKET_PATTERN.search(title)
        if docket_match:
            before_docket = title[: docket_match.start()].strip()
            # Remove "No." prefix and clean up
            before_docket = re.sub(r"\s*[-–—]\s*No\.?\s*$", "", before_docket)
            before_docket = before_docket.rstrip(" -–—.,;:")
            if before_docket:
                return before_docket

        return "Unknown"

    def _get_opinion_type(self, author: str | None) -> str:
        """Determine opinion type from author/dc:creator field.

        Args:
            author: dc:creator value like "Justice David Wecht", "Per Curiam"

        Returns:
            Opinion type string
        """
        if not author:
            return PennsylvaniaOpinionCluster.OPINION_TYPE_UNKNOWN

        author_lower = author.lower()

        if "per curiam" in author_lower:
            return PennsylvaniaOpinionCluster.OPINION_TYPE_PER_CURIAM

        # Check for dissent/concurrence indicators in author field
        # Format: "Author ~ Dissenting Opinion by OtherAuthor"
        if "dissent" in author_lower:
            return PennsylvaniaOpinionCluster.OPINION_TYPE_DISSENT
        if "concur" in author_lower:
            return PennsylvaniaOpinionCluster.OPINION_TYPE_CONCURRENCE

        # Default to majority for named judges/justices
        if (
            "justice" in author_lower
            or "judge" in author_lower
            or "j." in author_lower
        ):
            return PennsylvaniaOpinionCluster.OPINION_TYPE_MAJORITY

        return PennsylvaniaOpinionCluster.OPINION_TYPE_UNKNOWN

    # =========================================================================
    # Entry Point
    # =========================================================================

    @entry(PennsylvaniaOpinionCluster)
    def get_entry(self) -> Generator[NavigatingRequest, None, None]:
        """Yield initial requests to RSS feeds for selected courts."""
        requested = self._get_requested_data_types()

        if "opinions" not in requested:
            return

        courts = self._get_target_courts()
        date_gte, date_lte, docket_number, _ = self._get_search_params()

        first_court = courts[0]
        remaining_courts = courts[1:]

        rss_court = COURT_ID_TO_RSS_COURT.get(first_court, "Supreme")
        url = RSS_FEED_URL_TEMPLATE.format(court=rss_court)

        yield NavigatingRequest(
            request=HTTPRequestParams(
                method=HttpMethod.GET,
                url=url,
            ),
            continuation=self.parse_rss_feed,
            accumulated_data={
                "court_id": first_court,
                "remaining_courts": remaining_courts,
                "date_gte": date_gte.isoformat() if date_gte else None,
                "date_lte": date_lte.isoformat() if date_lte else None,
                "docket_number_filter": docket_number,
            },
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
    ) -> Generator[ScraperYield[PennsylvaniaOpinionCluster], None, None]:
        """Parse RSS feed and yield requests for each opinion."""
        court_id = accumulated_data.get("court_id", "pa")
        remaining_courts = accumulated_data.get("remaining_courts", [])
        date_gte_str = accumulated_data.get("date_gte")
        date_lte_str = accumulated_data.get("date_lte")
        docket_number_filter = accumulated_data.get("docket_number_filter")

        date_gte = date.fromisoformat(date_gte_str) if date_gte_str else None
        date_lte = date.fromisoformat(date_lte_str) if date_lte_str else None

        # Find all <item> elements in the RSS feed
        items = lxml_tree.checked_xpath(
            "//item",
            "RSS items",
            min_count=0,
        )

        for item in items:
            # Extract title (case name + docket number)
            title_elems = item.xpath("title/text()")
            if not title_elems:
                continue
            title = str(title_elems[0]).strip()

            # Skip judgment lists and other non-opinion items
            if (
                "judgement list" in title.lower()
                or "judgment list" in title.lower()
            ):
                continue

            # Extract docket number
            docket_number = self._extract_docket_number(title)
            if not docket_number:
                continue

            # Filter by specific docket if specified
            if docket_number_filter and docket_number != docket_number_filter:
                continue

            # Extract case name
            case_name = self._extract_case_name(title)

            # Extract link (PDF URL)
            link_elems = item.xpath("link/text()")
            if not link_elems:
                continue
            pdf_url = str(link_elems[0]).strip()

            # Extract guid for deduplication
            guid_elems = item.xpath("guid/text()")
            guid = str(guid_elems[0]).strip() if guid_elems else pdf_url

            # Extract pubDate
            pub_date_elems = item.xpath("pubDate/text()")
            if not pub_date_elems:
                continue
            pub_date_str = str(pub_date_elems[0]).strip()
            pub_date = self._parse_rss_date(pub_date_str)

            if pub_date is None:
                continue

            # Filter by date range if specified
            if date_gte and pub_date < date_gte:
                continue
            if date_lte and pub_date > date_lte:
                continue

            # Extract author from dc:creator (with namespace handling)
            author = None
            creator_elems = item.xpath(
                "dc:creator/text()",
                namespaces={"dc": "http://purl.org/dc/elements/1.1/"},
            )
            if creator_elems:
                author = str(creator_elems[0]).strip()

            # Also try without namespace (some feeds may not use it)
            if not author:
                creator_elems = item.xpath("creator/text()")
                if creator_elems:
                    author = str(creator_elems[0]).strip()

            # Determine opinion type from author
            opinion_type = self._get_opinion_type(author)

            # Build cluster data for accumulated_data
            cluster_data: dict[str, Any] = {
                "docket_number": docket_number,
                "court_id": court_id,
                "date_filed": pub_date.isoformat(),
                "case_name": case_name,
                "raw_title": title,
                "guid": guid,
                "source_url": response.url,
                "opinions_data": [
                    {
                        "download_url": pdf_url,
                        "type": opinion_type,
                        "author_str": author,
                    }
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

        # Move to next court after processing this one
        if remaining_courts:
            next_court = remaining_courts[0]
            rss_court = COURT_ID_TO_RSS_COURT.get(next_court, "Supreme")
            url = RSS_FEED_URL_TEMPLATE.format(court=rss_court)

            yield NavigatingRequest(
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url=url,
                ),
                continuation=self.parse_rss_feed,
                accumulated_data={
                    "court_id": next_court,
                    "remaining_courts": remaining_courts[1:],
                    "date_gte": date_gte_str,
                    "date_lte": date_lte_str,
                    "docket_number_filter": docket_number_filter,
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
    ) -> Generator[ScraperYield[PennsylvaniaOpinionCluster], None, None]:
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
    ) -> Generator[ScraperYield[PennsylvaniaOpinionCluster], None, None]:
        """Build and yield the final OpinionCluster with all PDFs downloaded."""
        opinions = []
        for i, op_data in enumerate(accumulated_data["opinions_data"]):
            local_path = accumulated_data["downloaded_paths"].get(i)
            opinions.append(
                PennsylvaniaOpinion(
                    download_url=op_data["download_url"],
                    type=op_data.get("type", "majority"),
                    local_path=local_path,
                    author_str=op_data.get("author_str"),
                )
            )

        date_filed = date.fromisoformat(accumulated_data["date_filed"])

        cluster = PennsylvaniaOpinionCluster(
            docket_number=accumulated_data["docket_number"],
            court_id=accumulated_data["court_id"],
            date_filed=date_filed,
            case_name=accumulated_data["case_name"],
            opinions=opinions,
            source_url=accumulated_data.get("source_url"),
            guid=accumulated_data.get("guid"),
            raw_title=accumulated_data.get("raw_title"),
        )

        yield ParsedData(cluster)
