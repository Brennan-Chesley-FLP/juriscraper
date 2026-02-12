"""Idaho Appellate Courts Scraper.

This module scrapes opinions from the Idaho Supreme Court and
Idaho Court of Appeals using their opinion listing pages.

Entry point:
- Main opinions page: https://isc.idaho.gov/appeals-court/opinions

Opinion categories:
1. Supreme Court Civil Opinions (isc_civil) - published, table format
2. Supreme Court Criminal Opinions (isc_criminal) - published, table format
3. Court of Appeals Civil Opinions (coa_civil) - published, table format
4. Court of Appeals Criminal & PC Opinions (coa_criminal) - published, table format
5. Court of Appeals Unpublished Opinions (coaunpublished) - unpublished, list format
6. Court of Appeals Unpublished Per Curiam (Unpublished-Per-Curiam) - unpublished, list

Flow:
1. get_entry -> Yields requests for each enabled opinion page
2. parse_opinion_table -> Parses table format pages (published)
3. parse_opinion_list -> Parses list format pages (unpublished)
4. handle_opinion_download -> Yields final IdahoOpinionCluster

Design decisions:
- Uses DateRange filter on date_filed for searching
- Uses SetFilter on court_id to select which courts to scrape
- Table format pages have: Release Date, Docket#, Case Name, Opinion link, Summary link, Notes
- List format pages have: Date text + link with "DocketNumber CaseName"
- All opinions are at https://isc.idaho.gov/opinions/{docket}.pdf
- Summaries (published only) at https://isc.idaho.gov/opinions/{docket}summ.pdf
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import TYPE_CHECKING, ClassVar

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
    OPINION_PAGES,
    IdahoOpinion,
    IdahoOpinionCluster,
)

if TYPE_CHECKING:
    from collections.abc import Generator

    from kent.data_types import ScraperYield


# Base URL for opinions site
BASE_URL = "https://isc.idaho.gov"
OPINIONS_BASE_URL = f"{BASE_URL}/appeals-court"


class IdahoScraper(BaseScraper[IdahoOpinionCluster]):
    """Scraper for Idaho appellate court opinions.

    Scrapes opinions from the Idaho Supreme Court (idaho) and
    Idaho Court of Appeals (idahoctapp).

    Usage:
        # Scrape all opinions from both courts
        scraper = IdahoScraper()

        # Scrape only Supreme Court opinions
        params = IdahoScraper.params()
        params.IdahoOpinionCluster.court_id.values = {"idaho"}
        scraper = IdahoScraper(params=params)

        # Scrape only Court of Appeals opinions
        params = IdahoScraper.params()
        params.IdahoOpinionCluster.court_id.values = {"idahoctapp"}
        scraper = IdahoScraper(params=params)

        # Filter opinions by date range
        params = IdahoScraper.params()
        params.IdahoOpinionCluster.date_filed.gte = date(2026, 1, 1)
        params.IdahoOpinionCluster.date_filed.lte = date(2026, 1, 31)
        scraper = IdahoScraper(params=params)
    """

    # === Metadata ===
    court_ids: ClassVar[set[str]] = {"idaho", "idahoctapp"}
    court_url: ClassVar[str] = "https://isc.idaho.gov/"
    data_types: ClassVar[set[str]] = {"opinions"}
    status: ClassVar[ScraperStatus] = ScraperStatus.IN_DEVELOPMENT
    version: ClassVar[str] = "2026-01-22"
    requires_auth: ClassVar[bool] = False

    # Rate limiting - be respectful to court servers
    msec_per_request_rate_limit: ClassVar[int] = 1000

    # === Regex patterns ===
    # Date parsing pattern: "January 22, 2026" or "December 10, 2025"
    DATE_PATTERN = re.compile(
        r"(January|February|March|April|May|June|July|August|September|"
        r"October|November|December)\s+(\d{1,2}),?\s+(\d{4})"
    )

    # Docket number pattern - 5-digit number, possibly with letter suffix
    DOCKET_PATTERN = re.compile(r"^(\d{5})([a-z])?$", re.IGNORECASE)

    # Unpublished list link pattern: "DocketNumber CaseName" or "D1/D2/D3 CaseName"
    UNPUB_LINK_PATTERN = re.compile(r"^([\d/]+)\s+(.+)$")

    # Mapping from model name to data type
    MODEL_TO_DATA_TYPE: ClassVar[dict[str, str]] = {
        "IdahoOpinionCluster": "opinions",
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
            model_proxy = self._params.IdahoOpinionCluster
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
        """Parse date from format like 'January 22, 2026'.

        Args:
            date_str: Date string like "January 22, 2026"

        Returns:
            Parsed date or None
        """
        match = self.DATE_PATTERN.search(date_str)
        if not match:
            return None

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
        if month is None:
            return None

        try:
            return date(year, month, day)
        except ValueError:
            return None

    def _should_scrape_page(
        self, page_court_id: str, court_ids: set[str] | None
    ) -> bool:
        """Check if we should scrape a page based on court filter.

        Args:
            page_court_id: Court ID for this page
            court_ids: Set of allowed court IDs (None = all)

        Returns:
            True if page should be scraped
        """
        if court_ids is None:
            return True
        return page_court_id in court_ids

    # =========================================================================
    # Entry Point
    # =========================================================================

    @entry(IdahoOpinionCluster)
    def get_entry(self) -> Generator[NavigatingRequest, None, None]:
        """Yield initial requests for each opinion listing page."""
        requested = self._get_requested_data_types()

        if "opinions" not in requested:
            return

        _, _, _, court_ids = self._get_search_params()

        # Yield requests for each opinion page
        for url_path, court_id, case_type, is_published in OPINION_PAGES:
            # Filter by court if specified
            if not self._should_scrape_page(court_id, court_ids):
                continue

            url = f"{OPINIONS_BASE_URL}/{url_path}"
            precedential = "Published" if is_published else "Unpublished"

            # Published pages use table format, unpublished use list format
            if is_published:
                continuation = self.parse_opinion_table
            else:
                continuation = self.parse_opinion_list

            yield NavigatingRequest(
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url=url,
                ),
                continuation=continuation,
                accumulated_data={
                    "court_id": court_id,
                    "case_type": case_type,
                    "precedential_status": precedential,
                    "url_path": url_path,
                },
            )

    # =========================================================================
    # Table Format Parser (Published Opinions)
    # =========================================================================

    @step(xsd="xsds/parse_opinion_table.xsd")
    def parse_opinion_table(
        self,
        lxml_tree: CheckedHtmlElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[IdahoOpinionCluster], None, None]:
        """Parse table format opinion listing page (published opinions).

        Table columns: Release Date | Docket# | Case Name | Opinion/Summary | Notes
        """
        date_gte, date_lte, target_docket, _ = self._get_search_params()
        court_id = accumulated_data["court_id"]
        case_type = accumulated_data["case_type"]
        precedential_status = accumulated_data["precedential_status"]

        # Find the data table - look for table with "Release Date" header
        tables = lxml_tree.checked_xpath(
            "//table",
            "opinion tables",
            min_count=0,
        )

        for table in tables:
            # Check if this is the opinion table by looking for headers
            headers = table.xpath(".//th/text()")
            header_text = " ".join(str(h).strip().lower() for h in headers)

            if (
                "release date" not in header_text
                or "docket" not in header_text
            ):
                continue

            # Found the opinion table - parse rows
            rows = table.checked_xpath(
                ".//tr[td]",
                "data rows",
                min_count=0,
            )

            for row in rows:
                cells = row.xpath("td")
                if len(cells) < 4:
                    continue

                # Extract cell content
                # Column 0: Release Date
                date_text = "".join(cells[0].itertext()).strip()
                release_date = self._parse_date(date_text)
                if release_date is None:
                    continue

                # Filter by date range
                if date_gte and release_date < date_gte:
                    continue
                if date_lte and release_date > date_lte:
                    continue

                # Column 1: Docket#
                docket_text = "".join(cells[1].itertext()).strip()
                if not docket_text:
                    continue

                # Filter by specific docket if requested
                if target_docket and docket_text != target_docket:
                    continue

                # Column 2: Case Name
                case_name = "".join(cells[2].itertext()).strip()
                if not case_name:
                    case_name = "Unknown"

                # Column 3: Opinion/Summary links
                opinion_link = None
                summary_link = None

                for link in cells[3].xpath(".//a"):
                    href = link.get("href", "")
                    link_text = "".join(link.itertext()).strip().lower()

                    if "opinion" in link_text and href.endswith(".pdf"):
                        opinion_link = href
                    elif "summary" in link_text and href.endswith(".pdf"):
                        summary_link = href

                if not opinion_link:
                    continue

                # Normalize URL
                if opinion_link.startswith("/"):
                    opinion_link = f"{BASE_URL}{opinion_link}"

                # Column 4: Notes (optional)
                notes = None
                if len(cells) > 4:
                    notes = "".join(cells[4].itertext()).strip() or None

                # Build accumulated data for download
                cluster_data = {
                    "docket_id": docket_text,
                    "court_id": court_id,
                    "date_filed": release_date.isoformat(),
                    "case_name": case_name,
                    "source_url": response.url,
                    "case_type": case_type,
                    "notes": notes,
                    "precedential_status": precedential_status,
                    "opinion_url": opinion_link,
                    "summary_url": summary_link,
                }

                yield ArchiveRequest(
                    request=HTTPRequestParams(
                        method=HttpMethod.GET,
                        url=opinion_link,
                    ),
                    continuation=self.handle_opinion_download,
                    expected_type="pdf",
                    accumulated_data=cluster_data,
                )

    # =========================================================================
    # List Format Parser (Unpublished Opinions)
    # =========================================================================

    @step(xsd="xsds/parse_opinion_list.xsd")
    def parse_opinion_list(
        self,
        lxml_tree: CheckedHtmlElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[IdahoOpinionCluster], None, None]:
        """Parse list format opinion listing page (unpublished opinions).

        Format: Date text followed by link with "DocketNumber CaseName"
        """
        date_gte, date_lte, target_docket, _ = self._get_search_params()
        court_id = accumulated_data["court_id"]
        case_type = accumulated_data["case_type"]
        precedential_status = accumulated_data["precedential_status"]

        # Find the main content area
        content = lxml_tree.checked_xpath(
            "//div[contains(@class, 'field-items')] | //div[@id='content']",
            "content area",
            min_count=0,
        )

        if not content:
            return

        # Look for links to opinion PDFs
        for link in content[0].xpath(
            ".//a[contains(@href, '/opinions/') and contains(@href, '.pdf')]"
        ):
            href = link.get("href", "")
            link_text = "".join(link.itertext()).strip()

            if not href or not link_text:
                continue

            # Parse link text: "DocketNumber CaseName"
            match = self.UNPUB_LINK_PATTERN.match(link_text)
            if not match:
                continue

            docket_numbers = match.group(1)  # May be "52712/52713/52714"
            case_name = match.group(2).strip()

            # Use first docket number as primary
            primary_docket = docket_numbers.split("/")[0].strip()

            # Filter by specific docket if requested
            if target_docket and primary_docket != target_docket:
                continue

            # Get preceding text node for date
            # The date appears as text before the link
            parent = link.getparent()
            if parent is None:
                continue

            # Get all text content before this link
            preceding_text = ""
            for sibling in parent.iter():
                if sibling == link:
                    break
                if sibling.text:
                    preceding_text = sibling.text
                if sibling.tail:
                    preceding_text = sibling.tail

            # Try to find date in parent's text
            parent_text = "".join(parent.itertext())
            link_pos = parent_text.find(link_text)
            if link_pos > 0:
                before_link = parent_text[:link_pos]
                release_date = self._parse_date(before_link)
            else:
                # Fallback: look for date in preceding siblings
                release_date = None
                prev = link.getprevious()
                while prev is not None and release_date is None:
                    prev_text = "".join(prev.itertext())
                    release_date = self._parse_date(prev_text)
                    prev = prev.getprevious()

                # Also check text content directly before link
                if release_date is None and preceding_text:
                    release_date = self._parse_date(preceding_text)

            if release_date is None:
                # Skip entries without dates
                continue

            # Filter by date range
            if date_gte and release_date < date_gte:
                continue
            if date_lte and release_date > date_lte:
                continue

            # Normalize URL
            opinion_url = href
            if opinion_url.startswith("/"):
                opinion_url = f"{BASE_URL}{opinion_url}"

            # Build accumulated data
            cluster_data = {
                "docket_id": primary_docket,
                "court_id": court_id,
                "date_filed": release_date.isoformat(),
                "case_name": case_name,
                "source_url": response.url,
                "case_type": case_type,
                "notes": None,
                "precedential_status": precedential_status,
                "opinion_url": opinion_url,
                "summary_url": None,  # Unpublished don't have summaries
            }

            yield ArchiveRequest(
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url=opinion_url,
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
    ) -> Generator[ScraperYield[IdahoOpinionCluster], None, None]:
        """Handle a downloaded opinion PDF and yield final cluster."""
        opinion = IdahoOpinion(
            download_url=accumulated_data["opinion_url"],
            local_path=response.file_url,
            has_summary=accumulated_data.get("summary_url") is not None,
            summary_url=accumulated_data.get("summary_url"),
        )

        date_filed = datetime.fromisoformat(
            accumulated_data["date_filed"]
        ).date()

        cluster = IdahoOpinionCluster(
            docket_id=accumulated_data["docket_id"],
            court_id=accumulated_data["court_id"],
            date_filed=date_filed,
            case_name=accumulated_data["case_name"],
            opinions=[opinion],
            source_url=accumulated_data["source_url"],
            case_type=accumulated_data.get("case_type"),
            notes=accumulated_data.get("notes"),
            precedential_status=accumulated_data.get(
                "precedential_status", "Published"
            ),
        )

        yield ParsedData(cluster)
