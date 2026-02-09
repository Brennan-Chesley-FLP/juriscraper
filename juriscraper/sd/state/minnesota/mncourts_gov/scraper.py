"""Minnesota Appellate Courts Scraper.

This module scrapes published opinions from:
- Minnesota Supreme Court (minn)
- Minnesota Court of Appeals (minnctapp)

Entry points:
- Supreme Court: https://mncourts.gov/supremecourt/recentopinions/minnesota-supreme-court-opinion
- Court of Appeals Precedential: https://mncourts.gov/courtofappeals/recentopinions/precedential-opinions
- Court of Appeals Nonprecedential: https://mncourts.gov/courtofappeals/recentopinions/nonprecedential-opinions

Flow:
1. get_entry -> branch based on requested data types
2. parse_supreme_court_opinions -> parses SC opinion page, yields ArchiveRequests
3. parse_coa_precedential_opinions -> parses CoA precedential page
4. parse_coa_nonprecedential_opinions -> parses CoA nonprecedential page
5. handle_opinion_download -> yields final MNOpinionCluster

Design decisions:
- Pages are simple HTML with opinions in paragraphs, not tables
- Each opinion entry has a link with docket number, followed by case text
- PDF URLs follow pattern: mncourts.gov/_media/migration/appellate/{court}/standard-opinions/{date}/...
- Uses DateRange filter on date_filed for searching
- Supports filtering by court_id to scrape only one court
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import TYPE_CHECKING, ClassVar
from urllib.parse import urljoin

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
    MNCourt,
    MNOpinion,
    MNOpinionCluster,
    PrecedentialStatus,
)

if TYPE_CHECKING:
    from collections.abc import Generator

    from juriscraper.scraper_driver.data_types import ScraperYield


# Base URLs
BASE_URL = "https://mncourts.gov"
SC_OPINIONS_URL = "https://mncourts.gov/supremecourt/recentopinions/minnesota-supreme-court-opinion"
COA_PRECEDENTIAL_URL = (
    "https://mncourts.gov/courtofappeals/recentopinions/precedential-opinions"
)
COA_NONPRECEDENTIAL_URL = "https://mncourts.gov/courtofappeals/recentopinions/nonprecedential-opinions"


class MNCourtsScraper(BaseScraper[MNOpinionCluster]):
    """Scraper for Minnesota appellate court opinions.

    Scrapes published opinions from both the Minnesota Supreme Court
    and Court of Appeals (precedential and nonprecedential).

    Usage:
        # Scrape all opinions from both courts
        scraper = MNCourtsScraper()

        # Filter opinions by date range
        params = MNCourtsScraper.params()
        params.MNOpinionCluster.date_filed.gte = date(2026, 1, 1)
        params.MNOpinionCluster.date_filed.lte = date(2026, 1, 31)
        scraper = MNCourtsScraper(params=params)

        # Scrape only Supreme Court opinions
        params = MNCourtsScraper.params()
        params.MNOpinionCluster.court_id.values = {"minn"}
        scraper = MNCourtsScraper(params=params)

        # Scrape specific opinion by docket number
        params = MNCourtsScraper.params()
        params.MNOpinionCluster.docket_id.value = "A25-0268"
        scraper = MNCourtsScraper(params=params)
    """

    # === Metadata ===
    court_ids: ClassVar[set[str]] = {"minn", "minnctapp"}
    court_url: ClassVar[str] = "https://mncourts.gov/"
    data_types: ClassVar[set[str]] = {"opinions"}
    status: ClassVar[ScraperStatus] = ScraperStatus.IN_DEVELOPMENT
    version: ClassVar[str] = "2026-01-23"
    requires_auth: ClassVar[bool] = False

    # Rate limiting - be respectful to court servers
    msec_per_request_rate_limit: ClassVar[int] = 1000

    # === Regex patterns ===
    # Docket number pattern: A{YY}-{NNNN} (e.g., A25-0268)
    DOCKET_PATTERN = re.compile(r"A\d{2}-\d{4}")

    # Date from page header pattern: e.g., "JANUARY 20, 2026" or "FILED TUESDAY, JANUARY 20, 2026"
    DATE_HEADER_PATTERN = re.compile(
        r"(?:FILED\s+)?(?:\w+,\s+)?(\w+)\s+(\d{1,2}),\s+(\d{4})",
        re.IGNORECASE,
    )

    # Disposition patterns (in strong/bold text)
    DISPOSITION_PATTERN = re.compile(
        r"(Affirmed|Reversed|Reversed and remanded|Affirmed in part.*?remanded|"
        r"Dismissed|Vacated|Vacated and remanded)",
        re.IGNORECASE,
    )

    # Judge/Justice author pattern (follows disposition)
    AUTHOR_PATTERN = re.compile(
        r"(?:Chief\s+)?(?:Justice|Judge)\s+([A-Za-z\.\s]+?)(?:\.|,|$)",
        re.IGNORECASE,
    )

    # Mapping from model name to data type
    MODEL_TO_DATA_TYPE: ClassVar[dict[str, str]] = {
        "MNOpinionCluster": "opinions",
    }

    # Month name to number mapping
    MONTH_MAP: ClassVar[dict[str, int]] = {
        "january": 1,
        "february": 2,
        "march": 3,
        "april": 4,
        "may": 5,
        "june": 6,
        "july": 7,
        "august": 8,
        "september": 9,
        "october": 10,
        "november": 11,
        "december": 12,
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
            model_proxy = self._params.MNOpinionCluster
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

    def _parse_date_from_header(self, header_text: str) -> date | None:
        """Parse date from a page header.

        Args:
            header_text: Header text like 'FILED TUESDAY, JANUARY 20, 2026'
                        or 'RELEASED JANUARY 21, 2026'

        Returns:
            Parsed date or None
        """
        match = self.DATE_HEADER_PATTERN.search(header_text)
        if match:
            month_name = match.group(1).lower()
            day = int(match.group(2))
            year = int(match.group(3))

            month = self.MONTH_MAP.get(month_name)
            if month:
                return date(year, month, day)
        return None

    def _extract_disposition_and_author(
        self, text: str
    ) -> tuple[str | None, str | None]:
        """Extract disposition and author from opinion text.

        Args:
            text: Full text content of the opinion entry

        Returns:
            Tuple of (disposition, author)
        """
        disposition = None
        author = None

        disp_match = self.DISPOSITION_PATTERN.search(text)
        if disp_match:
            disposition = disp_match.group(1).strip()

        author_match = self.AUTHOR_PATTERN.search(text)
        if author_match:
            author = author_match.group(1).strip()
            # Clean up trailing periods or whitespace
            author = re.sub(r"[\.\s]+$", "", author)

        return disposition, author

    def _should_scrape_court(
        self, court_id: str, court_filter: set[str] | None
    ) -> bool:
        """Check if we should scrape opinions from a given court."""
        if court_filter is None:
            return True
        return court_id in court_filter

    # =========================================================================
    # Entry Point
    # =========================================================================

    @entry(MNOpinionCluster)
    def get_entry(self) -> Generator[NavigatingRequest, None, None]:
        """Yield initial requests based on requested data types and filters."""
        requested = self._get_requested_data_types()

        if "opinions" not in requested:
            return

        _, _, _, court_ids = self._get_search_params()

        # Supreme Court opinions
        if self._should_scrape_court(MNCourt.SUPREME_COURT.value, court_ids):
            yield NavigatingRequest(
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url=SC_OPINIONS_URL,
                ),
                continuation=self.parse_supreme_court_opinions,
            )

        # Court of Appeals - precedential opinions
        if self._should_scrape_court(
            MNCourt.COURT_OF_APPEALS.value, court_ids
        ):
            yield NavigatingRequest(
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url=COA_PRECEDENTIAL_URL,
                ),
                continuation=self.parse_coa_precedential_opinions,
            )

            # Court of Appeals - nonprecedential opinions
            yield NavigatingRequest(
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url=COA_NONPRECEDENTIAL_URL,
                ),
                continuation=self.parse_coa_nonprecedential_opinions,
            )

    # =========================================================================
    # Supreme Court Opinions Parsing
    # =========================================================================

    @step(xsd="xsds/parse_supreme_court_opinions.xsd")
    def parse_supreme_court_opinions(
        self,
        lxml_tree: CheckedHtmlElement,
        response: Response,
    ) -> Generator[ScraperYield[MNOpinionCluster], None, None]:
        """Parse the Supreme Court opinions page."""
        date_gte, date_lte, target_docket, _ = self._get_search_params()

        # Find the main content area
        main_content = lxml_tree.checked_xpath(
            "//main",
            "main content area",
            min_count=1,
            max_count=1,
        )[0]

        # Extract release date from page text
        # Look for text like "RELEASED JANUARY 21, 2026"
        page_text_nodes = main_content.checked_xpath(
            ".//text()",
            "page text nodes",
            min_count=1,
            type=str,
        )
        page_text = " ".join(page_text_nodes)

        release_date = None
        released_match = re.search(
            r"RELEASED\s+(\w+\s+\d{1,2},\s+\d{4})",
            page_text,
            re.IGNORECASE,
        )
        if released_match:
            release_date = self._parse_date_from_header(
                released_match.group(1)
            )

        # Apply date filter
        if release_date:
            if date_gte and release_date < date_gte:
                return
            if date_lte and release_date > date_lte:
                return

        # Find all opinion links (to PDF files)
        opinion_links = main_content.checked_xpath(
            ".//a[contains(@href, '.pdf')]",
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

            # Get docket number from link text
            link_text_nodes = link.checked_xpath(
                ".//text()",
                "link text",
                min_count=0,
                type=str,
            )
            link_text = "".join(link_text_nodes).strip()

            docket_match = self.DOCKET_PATTERN.search(link_text)
            if not docket_match:
                # Might be an order or other document, skip
                continue

            docket_number = docket_match.group(0)

            # Filter by specific docket if specified
            if target_docket and docket_number != target_docket:
                continue

            pdf_url = urljoin(response.url, href)

            # Get surrounding text for case name and metadata
            # The structure is: link with docket, followed by case text
            parent = link.getparent()
            if parent is None:
                continue

            parent_text_nodes = parent.checked_xpath(
                ".//text()",
                "parent text",
                min_count=0,
                type=str,
            )
            parent_text = " ".join(parent_text_nodes)

            # Extract case name - text after docket number
            case_name = self._extract_case_name_from_text(
                parent_text, docket_number
            )

            # Extract disposition and author
            disposition, author = self._extract_disposition_and_author(
                parent_text
            )

            cluster_data = {
                "docket_id": docket_number,
                "court_id": MNCourt.SUPREME_COURT.value,
                "date_filed": release_date.isoformat()
                if release_date
                else None,
                "case_name": case_name or f"Case {docket_number}",
                "source_url": response.url,
                "pdf_url": pdf_url,
                "precedential_status": PrecedentialStatus.PRECEDENTIAL.value,
                "author": author,
                "disposition": disposition,
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
    # Court of Appeals Opinions Parsing
    # =========================================================================

    @step(xsd="xsds/parse_coa_precedential_opinions.xsd")
    def parse_coa_precedential_opinions(
        self,
        lxml_tree: CheckedHtmlElement,
        response: Response,
    ) -> Generator[ScraperYield[MNOpinionCluster], None, None]:
        """Parse the Court of Appeals precedential opinions page."""
        yield from self._parse_coa_opinions(
            lxml_tree,
            response,
            PrecedentialStatus.PRECEDENTIAL,
        )

    @step(xsd="xsds/parse_coa_nonprecedential_opinions.xsd")
    def parse_coa_nonprecedential_opinions(
        self,
        lxml_tree: CheckedHtmlElement,
        response: Response,
    ) -> Generator[ScraperYield[MNOpinionCluster], None, None]:
        """Parse the Court of Appeals nonprecedential opinions page."""
        yield from self._parse_coa_opinions(
            lxml_tree,
            response,
            PrecedentialStatus.NONPRECEDENTIAL,
        )

    def _parse_coa_opinions(
        self,
        lxml_tree: CheckedHtmlElement,
        response: Response,
        precedential_status: PrecedentialStatus,
    ) -> Generator[ScraperYield[MNOpinionCluster], None, None]:
        """Parse Court of Appeals opinions page.

        Both precedential and nonprecedential pages have similar structure.
        """
        date_gte, date_lte, target_docket, _ = self._get_search_params()

        # Find the main content area
        main_content = lxml_tree.checked_xpath(
            "//main",
            "main content area",
            min_count=1,
            max_count=1,
        )[0]

        # Extract release date from page headings or text
        # Look for text like "FILED TUESDAY, JANUARY 20, 2026"
        page_text_nodes = main_content.checked_xpath(
            ".//text()",
            "page text nodes",
            min_count=1,
            type=str,
        )
        page_text = " ".join(page_text_nodes)

        release_date = None
        filed_match = re.search(
            r"FILED\s+(?:\w+,\s+)?(\w+\s+\d{1,2},\s+\d{4})",
            page_text,
            re.IGNORECASE,
        )
        if filed_match:
            release_date = self._parse_date_from_header(filed_match.group(1))

        # Apply date filter
        if release_date:
            if date_gte and release_date < date_gte:
                return
            if date_lte and release_date > date_lte:
                return

        # Find all opinion links (to PDF files)
        opinion_links = main_content.checked_xpath(
            ".//a[contains(@href, '.pdf')]",
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

            # Get docket number from link text
            link_text_nodes = link.checked_xpath(
                ".//text()",
                "link text",
                min_count=0,
                type=str,
            )
            link_text = "".join(link_text_nodes).strip()

            # Handle multiple docket numbers in one link (e.g., "A25-0110, A25-0113")
            docket_matches = self.DOCKET_PATTERN.findall(link_text)
            if not docket_matches:
                continue

            # Use first docket number as primary
            docket_number = docket_matches[0]

            # Filter by specific docket if specified
            if target_docket and docket_number != target_docket:
                continue

            pdf_url = urljoin(response.url, href)

            # Get surrounding text for case name and metadata
            parent = link.getparent()
            if parent is None:
                continue

            parent_text_nodes = parent.checked_xpath(
                ".//text()",
                "parent text",
                min_count=0,
                type=str,
            )
            parent_text = " ".join(parent_text_nodes)

            # Extract case name
            case_name = self._extract_case_name_from_text(
                parent_text, docket_number
            )

            # Extract disposition and author
            disposition, author = self._extract_disposition_and_author(
                parent_text
            )

            # Try to extract lower court info
            lower_court, lower_court_judge = self._extract_lower_court_info(
                parent_text
            )

            cluster_data = {
                "docket_id": docket_number,
                "court_id": MNCourt.COURT_OF_APPEALS.value,
                "date_filed": release_date.isoformat()
                if release_date
                else None,
                "case_name": case_name or f"Case {docket_number}",
                "source_url": response.url,
                "pdf_url": pdf_url,
                "precedential_status": precedential_status.value,
                "author": author,
                "disposition": disposition,
                "lower_court": lower_court,
                "lower_court_judge": lower_court_judge,
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

    def _extract_case_name_from_text(
        self, text: str, docket_number: str
    ) -> str | None:
        """Extract case name from surrounding text.

        The pattern is typically: docket number followed by case name.
        Case name often ends at a period or at disposition text.
        """
        # Find text after docket number
        idx = text.find(docket_number)
        if idx == -1:
            return None

        # Get text after docket number
        after_docket = text[idx + len(docket_number) :].strip()

        # Case name typically ends before disposition or court info
        # Look for patterns like "Affirmed.", "Reversed.", county names, etc.
        end_patterns = [
            r"\.\s*(?:Affirmed|Reversed|Dismissed|Vacated)",
            r"\.\s*(?:Chief\s+)?(?:Justice|Judge)",
            r"\s+County\s+District\s+Court",
            r"\s+Bureau\s+of\s+",
            r"\s+Office\s+of\s+",
            r"\s+Board\s+of\s+",
        ]

        case_name = after_docket
        for pattern in end_patterns:
            match = re.search(pattern, case_name, re.IGNORECASE)
            if match:
                case_name = case_name[: match.start()]
                break

        # Clean up
        case_name = case_name.strip()
        # Remove leading/trailing periods, commas
        case_name = re.sub(r"^[\.,\s]+|[\.,\s]+$", "", case_name)

        return case_name if case_name else None

    def _extract_lower_court_info(
        self, text: str
    ) -> tuple[str | None, str | None]:
        """Extract lower court and judge info from text.

        Patterns like:
        - "Hennepin County District Court, Hon. Edward Thomas Wahl."
        - "Bureau of Mediation Services."
        """
        lower_court = None
        lower_court_judge = None

        # Pattern for county district court
        court_match = re.search(
            r"(\w+\s+County\s+District\s+Court)(?:,\s*Hon\.\s*([^\.]+))?",
            text,
            re.IGNORECASE,
        )
        if court_match:
            lower_court = court_match.group(1)
            if court_match.group(2):
                lower_court_judge = court_match.group(2).strip()
        else:
            # Try other agency patterns
            agency_match = re.search(
                r"(Bureau\s+of\s+[^\.]+|Office\s+of\s+[^\.]+|"
                r"Board\s+of\s+[^\.]+|Minnesota\s+[^\.]+)\.",
                text,
                re.IGNORECASE,
            )
            if agency_match:
                lower_court = agency_match.group(1).strip()

        return lower_court, lower_court_judge

    # =========================================================================
    # Download Handler
    # =========================================================================

    @step
    def handle_opinion_download(
        self,
        response: ArchiveResponse,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[MNOpinionCluster], None, None]:
        """Handle a downloaded opinion PDF."""
        date_filed = None
        if accumulated_data.get("date_filed"):
            date_filed = datetime.fromisoformat(
                accumulated_data["date_filed"]
            ).date()

        opinion = MNOpinion(
            download_url=accumulated_data["pdf_url"],
            local_path=response.file_url,
        )

        cluster = MNOpinionCluster(
            docket_id=accumulated_data["docket_id"],
            court_id=accumulated_data["court_id"],
            date_filed=date_filed or date.today(),
            case_name=accumulated_data["case_name"],
            opinions=[opinion],
            source_url=accumulated_data["source_url"],
            precedential_status=PrecedentialStatus(
                accumulated_data["precedential_status"]
            ),
            author=accumulated_data.get("author"),
            lower_court=accumulated_data.get("lower_court"),
            lower_court_judge=accumulated_data.get("lower_court_judge"),
            disposition=accumulated_data.get("disposition"),
        )

        yield ParsedData(cluster)
