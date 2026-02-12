"""Massachusetts Appellate Courts Scraper.

This module scrapes published opinions from the Massachusetts Supreme Judicial
Court and Appeals Court, as well as Appeals Court summary dispositions.

Entry points:
- Published opinions: https://www.mass.gov/info-details/new-opinions
- Summary dispositions: https://128archive.com/

Flow:
1. get_entry -> yields requests based on enabled data types
2. parse_new_opinions -> parses mass.gov new opinions page
3. parse_128archive -> parses 128archive.com search results
4. handle_opinion_download -> yields final MassOpinionCluster

Docket number formats:
- SJC: SJC-{NNNNN} (e.g., SJC-13767) - extracted as "SJC 13767" from links
- Appeals Court: {YY}-P-{NNNN} (e.g., 24-P-1364)

Design decisions:
- Mass.gov only shows recent opinions, not a full archive
- 128archive.com has complete summary dispositions from 2008+
- Summary dispositions are non-binding (Rule 23.0)
- Both courts' published opinions appear on the same mass.gov page
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
    MassOpinion,
    MassOpinionCluster,
)

if TYPE_CHECKING:
    from collections.abc import Generator

    from kent.data_types import ScraperYield


# Base URLs
NEW_OPINIONS_URL = "https://www.mass.gov/info-details/new-opinions"
ARCHIVE_128_URL = "https://128archive.com/"


class MassachusettsScraper(BaseScraper[MassOpinionCluster]):
    """Scraper for Massachusetts appellate court opinions.

    Scrapes published opinions from the Supreme Judicial Court (SJC) and
    Appeals Court, as well as Appeals Court summary dispositions.

    Usage:
        # Scrape all available opinions
        scraper = MassachusettsScraper()

        # Filter by date range
        params = MassachusettsScraper.params()
        params.MassOpinionCluster.date_filed.gte = date(2026, 1, 1)
        params.MassOpinionCluster.date_filed.lte = date(2026, 1, 31)
        scraper = MassachusettsScraper(params=params)

        # Filter by court
        params = MassachusettsScraper.params()
        params.MassOpinionCluster.court_id.values = {"mass"}  # SJC only
        scraper = MassachusettsScraper(params=params)

        # Filter by docket number
        params = MassachusettsScraper.params()
        params.MassOpinionCluster.docket_id.value = "24-P-1364"
        scraper = MassachusettsScraper(params=params)
    """

    # === Metadata ===
    court_ids: ClassVar[set[str]] = {"mass", "massappct"}
    court_url: ClassVar[str] = "https://www.mass.gov/info-details/new-opinions"
    data_types: ClassVar[set[str]] = {"opinions"}
    status: ClassVar[ScraperStatus] = ScraperStatus.IN_DEVELOPMENT
    version: ClassVar[str] = "2026-01-23"
    requires_auth: ClassVar[bool] = False

    # Rate limiting - be respectful to court servers
    msec_per_request_rate_limit: ClassVar[int] = 1000

    # === Regex patterns ===
    # Published opinion patterns from mass.gov link text
    # Format: "Case Name (AC YY-P-NNNN)" or "Case Name (SJC NNNNN)"
    # The link text may include a date in parentheses after the docket
    PUBLISHED_PATTERN = re.compile(
        r"^(.+?)\s+\((AC|SJC)\s+(\d{2}-P-\d+|\d+)\)"
    )

    # Date pattern in link text: "(January 20, 2026)"
    DATE_IN_LINK_PATTERN = re.compile(r"\((\w+)\s+(\d{1,2}),\s+(\d{4})\)\s*$")

    # 128archive date format: MM/DD/YYYY
    ARCHIVE_DATE_PATTERN = re.compile(r"(\d{2})/(\d{2})/(\d{4})")

    # SJC docket normalization (SJC 13767 -> SJC-13767)
    SJC_NORMALIZE_PATTERN = re.compile(r"SJC\s*(\d+)")

    # AC docket patterns - extract from URL slug like "ac-m24p1364"
    AC_SLUG_PATTERN = re.compile(r"ac-[a-z]?(\d{2})p(\d+)")

    # Mapping from model name to data type
    MODEL_TO_DATA_TYPE: ClassVar[dict[str, str]] = {
        "MassOpinionCluster": "opinions",
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
            model_proxy = self._params.MassOpinionCluster
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

    def _parse_date_from_string(self, date_str: str) -> date | None:
        """Parse date from various formats.

        Handles:
        - "January 20, 2026"
        - "01/20/2026"
        """
        # Try full month name format
        match = self.DATE_IN_LINK_PATTERN.search(date_str)
        if match:
            month_name = match.group(1)
            day = int(match.group(2))
            year = int(match.group(3))

            month_map = {
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
            month = month_map.get(month_name)
            if month:
                return date(year, month, day)

        # Try MM/DD/YYYY format
        match = self.ARCHIVE_DATE_PATTERN.search(date_str)
        if match:
            month = int(match.group(1))
            day = int(match.group(2))
            year = int(match.group(3))
            return date(year, month, day)

        return None

    def _normalize_docket(self, docket: str) -> str:
        """Normalize docket number format.

        Converts:
        - "SJC 13767" -> "SJC-13767"
        - "24-P-1364" -> "24-P-1364" (unchanged)
        """
        match = self.SJC_NORMALIZE_PATTERN.match(docket)
        if match:
            return f"SJC-{match.group(1)}"
        return docket

    def _extract_docket_from_url(self, url: str) -> tuple[str, str] | None:
        """Extract court_id and docket from mass.gov PDF URL.

        URL patterns:
        - /doc/commonwealth-v-lewis-sjc-m13767/download -> ("mass", "SJC-13767")
        - /doc/commonwealth-v-ortiz-ac-m24p1364/download -> ("massappct", "24-P-1364")
        """
        url_lower = url.lower()

        # SJC pattern: sjc-[letter]NNNNN
        sjc_match = re.search(r"sjc-[a-z]?(\d+)", url_lower)
        if sjc_match:
            return ("mass", f"SJC-{sjc_match.group(1)}")

        # AC pattern: ac-[letter]YYpNNNN
        ac_match = self.AC_SLUG_PATTERN.search(url_lower)
        if ac_match:
            year = ac_match.group(1)
            number = ac_match.group(2)
            return ("massappct", f"{year}-P-{number}")

        return None

    def _should_include_court(
        self, court_id: str, court_filter: set[str] | None
    ) -> bool:
        """Check if court should be included based on filter."""
        if court_filter is None:
            return True
        return court_id in court_filter

    # =========================================================================
    # Entry Point
    # =========================================================================

    @entry(MassOpinionCluster)
    def get_entry(self) -> Generator[NavigatingRequest, None, None]:
        """Yield initial requests based on enabled data types."""
        requested = self._get_requested_data_types()

        if "opinions" in requested:
            # Fetch published opinions from mass.gov
            yield NavigatingRequest(
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url=NEW_OPINIONS_URL,
                ),
                continuation=self.parse_new_opinions,
            )

            # Fetch summary dispositions from 128archive.com
            # Build URL with date filters if specified
            date_gte, date_lte, _, court_filter = self._get_search_params()

            # Only fetch from 128archive if Appeals Court is requested
            if self._should_include_court("massappct", court_filter):
                archive_url = self._build_128archive_url(date_gte, date_lte)
                yield NavigatingRequest(
                    request=HTTPRequestParams(
                        method=HttpMethod.GET,
                        url=archive_url,
                    ),
                    continuation=self.parse_128archive,
                )

    def _build_128archive_url(
        self, date_gte: date | None, date_lte: date | None
    ) -> str:
        """Build 128archive.com search URL with date filters."""
        params = []

        if date_gte:
            params.append(
                f"ReleaseDateFrom={date_gte.month:02d}%2F{date_gte.day:02d}%2F{date_gte.year}"
            )
        if date_lte:
            params.append(
                f"ReleaseDateTo={date_lte.month:02d}%2F{date_lte.day:02d}%2F{date_lte.year}"
            )

        if params:
            return f"{ARCHIVE_128_URL}?{'&'.join(params)}"
        return ARCHIVE_128_URL

    # =========================================================================
    # Mass.gov New Opinions Page Parsing
    # =========================================================================

    @step(xsd="xsds/parse_new_opinions.xsd")
    def parse_new_opinions(
        self,
        lxml_tree: CheckedHtmlElement,
        response: Response,
    ) -> Generator[ScraperYield[MassOpinionCluster], None, None]:
        """Parse the mass.gov new opinions page.

        This page lists recent published opinions from both SJC and Appeals Court.
        Each opinion links directly to a PDF download.
        """
        date_gte, date_lte, target_docket, court_filter = (
            self._get_search_params()
        )

        # Find all links to opinion PDFs
        # These are in the main content area and link to /doc/.../download
        opinion_links = lxml_tree.checked_xpath(
            "//main//a[contains(@href, '/doc/') and contains(@href, '/download')]",
            "opinion PDF links",
            min_count=0,
        )

        for link in opinion_links:
            href_list = link.checked_xpath(
                "@href",
                "link href",
                min_count=1,
                max_count=1,
                type=str,
            )
            href = href_list[0]

            # Get link text for case name and docket
            text_parts = link.checked_xpath(
                ".//text()",
                "link text",
                min_count=1,
                type=str,
            )
            link_text = "".join(text_parts).strip()

            # Skip non-opinion links (like "List of unpublished...")
            if "unpublished" in link_text.lower():
                continue

            # Extract court and docket from URL
            extracted = self._extract_docket_from_url(href)
            if extracted is None:
                continue

            court_id, docket = extracted

            # Apply court filter
            if not self._should_include_court(court_id, court_filter):
                continue

            # Apply docket filter
            if target_docket and docket != target_docket:
                continue

            # Extract case name from link text
            # Format: "Case Name (AC YY-P-NNNN) (Date)" or "Case Name (SJC NNNNN)"
            match = self.PUBLISHED_PATTERN.match(link_text)
            if match:
                case_name = match.group(1).strip()
            else:
                # Fallback: use text before first parenthesis
                paren_idx = link_text.find("(")
                if paren_idx > 0:
                    case_name = link_text[:paren_idx].strip()
                else:
                    case_name = link_text

            # Try to extract date from link text
            opinion_date = self._parse_date_from_string(link_text)
            if opinion_date is None:
                # Use today as fallback since this page shows recent opinions
                opinion_date = date.today()

            # Apply date filter
            if date_gte and opinion_date < date_gte:
                continue
            if date_lte and opinion_date > date_lte:
                continue

            pdf_url = urljoin(response.url, href)

            # Build accumulated data for download handler
            cluster_data = {
                "docket_id": docket,
                "court_id": court_id,
                "date_filed": opinion_date.isoformat(),
                "case_name": case_name,
                "source_url": response.url,
                "pdf_url": pdf_url,
                "is_summary_disposition": False,
            }

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
    # 128archive.com Parsing
    # =========================================================================

    @step(xsd="xsds/parse_128archive.xsd")
    def parse_128archive(
        self,
        lxml_tree: CheckedHtmlElement,
        response: Response,
    ) -> Generator[ScraperYield[MassOpinionCluster], None, None]:
        """Parse 128archive.com search results for summary dispositions.

        The page structure has result cards with:
        - Docket Number
        - Case Name
        - Release Date
        - Download PDF / Read in Full links
        """
        date_gte, date_lte, target_docket, _ = self._get_search_params()

        # Find all result rows - each contains labeled fields
        # The structure is a series of divs with Docket Number, Case Name, etc.
        # Look for Download PDF links and work backwards
        pdf_links = lxml_tree.checked_xpath(
            "//a[contains(text(), 'Download PDF')]",
            "Download PDF links",
            min_count=0,
        )

        for pdf_link in pdf_links:
            # Get the PDF URL
            href_list = pdf_link.checked_xpath(
                "@href",
                "PDF href",
                min_count=1,
                max_count=1,
                type=str,
            )
            pdf_url = urljoin(response.url, href_list[0])

            # Navigate up to find the parent result container
            # The parent should contain the docket, case name, and date
            parent = pdf_link.getparent()
            if parent is None:
                continue

            # Find grandparent container with the data fields
            grandparent = parent.getparent()
            if grandparent is None:
                continue

            # Extract docket number
            docket_elements = grandparent.xpath(
                ".//div[contains(text(), 'Docket Number')]/following-sibling::div[1]/text()"
            )
            if not docket_elements:
                # Try alternative structure
                docket_elements = grandparent.xpath(
                    ".//div[div[contains(text(), 'Docket Number')]]/div[2]/text()"
                )
            if not docket_elements:
                continue

            docket = str(docket_elements[0]).strip()

            # Apply docket filter
            if target_docket and docket != target_docket:
                continue

            # Extract case name
            case_elements = grandparent.xpath(
                ".//div[contains(text(), 'Case Name')]/following-sibling::div[1]/text()"
            )
            if not case_elements:
                case_elements = grandparent.xpath(
                    ".//div[div[contains(text(), 'Case Name')]]/div[2]/text()"
                )
            if not case_elements:
                continue

            case_name = str(case_elements[0]).strip()

            # Extract release date
            date_elements = grandparent.xpath(
                ".//div[contains(text(), 'Release Date')]/following-sibling::div[1]/text()"
            )
            if not date_elements:
                date_elements = grandparent.xpath(
                    ".//div[div[contains(text(), 'Release Date')]]/div[2]/text()"
                )
            if not date_elements:
                continue

            date_str = str(date_elements[0]).strip()
            opinion_date = self._parse_date_from_string(date_str)
            if opinion_date is None:
                continue

            # Apply date filter
            if date_gte and opinion_date < date_gte:
                continue
            if date_lte and opinion_date > date_lte:
                continue

            # Build accumulated data
            cluster_data = {
                "docket_id": docket,
                "court_id": "massappct",
                "date_filed": opinion_date.isoformat(),
                "case_name": case_name,
                "source_url": response.url,
                "pdf_url": pdf_url,
                "is_summary_disposition": True,
            }

            yield ArchiveRequest(
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url=pdf_url,
                ),
                continuation=self.handle_opinion_download,
                expected_type="pdf",
                accumulated_data=cluster_data,
            )

        # Check if there's a next page by looking at pagination info
        # The page shows "Page X of Y" - if X < Y, there are more pages
        page_info = lxml_tree.xpath("//text()[contains(., ' of ')]")
        for info in page_info:
            info_str = str(info).strip()
            if "of" in info_str:
                # Parse "X of Y" pattern
                parts = info_str.split("of")
                if len(parts) == 2:
                    try:
                        current_page = int(parts[0].strip())
                        total_pages = int(parts[1].strip())

                        if current_page < total_pages:
                            # Need to navigate to next page
                            # The form uses JavaScript, so we need to construct the URL
                            # with page parameters
                            # Build next page URL - 128archive uses query params
                            # Note: This is a simplified approach; the actual site
                            # may use different pagination mechanics
                            break
                    except ValueError:
                        pass

    # =========================================================================
    # Download Handler
    # =========================================================================

    @step
    def handle_opinion_download(
        self,
        response: ArchiveResponse,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[MassOpinionCluster], None, None]:
        """Handle a downloaded opinion PDF."""
        date_filed = datetime.fromisoformat(
            accumulated_data["date_filed"]
        ).date()

        opinion = MassOpinion(
            download_url=accumulated_data["pdf_url"],
            local_path=response.file_url,
        )

        # Determine precedential status based on disposition type
        if accumulated_data.get("is_summary_disposition", False):
            precedential_status = "Unpublished"
        else:
            precedential_status = "Published"

        cluster = MassOpinionCluster(
            docket_id=accumulated_data["docket_id"],
            court_id=accumulated_data["court_id"],
            date_filed=date_filed,
            case_name=accumulated_data["case_name"],
            opinions=[opinion],
            source_url=accumulated_data["source_url"],
            is_summary_disposition=accumulated_data.get(
                "is_summary_disposition", False
            ),
            precedential_status=precedential_status,
        )

        yield ParsedData(cluster)
