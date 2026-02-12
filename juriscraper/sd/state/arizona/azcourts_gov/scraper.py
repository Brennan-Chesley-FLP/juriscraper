"""Arizona Appellate Courts Scraper.

This module contains a scraper for opinions from the Arizona Supreme Court
and Court of Appeals using the azcourts.gov website.

Entry points:
- Supreme Court: https://www.azcourts.gov/opinions/SearchOpinionsMemoDecs.aspx?court=999
- Court of Appeals Div 1: https://www.azcourts.gov/opinions/SearchOpinionsMemoDecs.aspx?court=998
- Court of Appeals Div 2: https://www.appeals2.az.gov/ODSPlus/recentOpinionsHTML.cfm

Opinions Flow:
  1. get_entry -> year-based opinion search pages for selected courts
  2. parse_opinion_results -> parse opinions from search results, yields ArchiveRequests for PDFs
  3. handle_opinion_download -> stores local paths, yields final clusters

Design decisions:
- Uses year-based URL parameters for browsing opinions
- Supports both Supreme Court and Court of Appeals Division 1 through the main site
- Division 2 has a separate site with different structure
- Downloads all PDFs via ArchiveRequest
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

from juriscraper.lib.string_utils import titlecase

from .models import (
    ArizOpinion,
    ArizOpinionCluster,
)

if TYPE_CHECKING:
    from collections.abc import Generator

    from kent.data_types import ScraperYield


# Court configuration for opinions
OPINIONS_CONFIG = {
    "ariz": {
        "name": "Arizona Supreme Court",
        "search_url": "https://www.azcourts.gov/opinions/SearchOpinionsMemoDecs.aspx",
        "court_param": "999",  # All courts (but shows AZ Supreme Court)
        "docket_prefixes": ["CR-", "CV-"],
    },
    "arizctapp": {
        "name": "Arizona Court of Appeals",
        "search_url": "https://www.azcourts.gov/opinions/SearchOpinionsMemoDecs.aspx",
        "court_param": "998",  # Court of Appeals Division 1
        "docket_prefixes": ["1 CA-", "2 CA-"],
    },
}

# Division 2 has a separate site
DIV2_CONFIG = {
    "name": "Court of Appeals Division Two",
    "url": "https://www.appeals2.az.gov/ODSPlus/recentOpinionsHTML.cfm",
    "court_id": "arizctapp",
    "docket_prefix": "2 CA-",
}


class ArizScraper(BaseScraper[ArizOpinionCluster]):
    """Scraper for Arizona appellate court opinions.

    Scrapes opinions from the Arizona Supreme Court and Court of Appeals
    from the azcourts.gov website.

    Usage:
        # Scrape all opinions (both courts)
        scraper = ArizScraper()

        # Scrape only Supreme Court
        params = ArizScraper.params()
        params.ArizOpinionCluster.court_id.values = {"ariz"}
        scraper = ArizScraper(params=params)

        # Scrape only Court of Appeals
        params = ArizScraper.params()
        params.ArizOpinionCluster.court_id.values = {"arizctapp"}
        scraper = ArizScraper(params=params)

        # Filter by date range
        params = ArizScraper.params()
        params.ArizOpinionCluster.date_filed.gte = date(2025, 1, 1)
        params.ArizOpinionCluster.date_filed.lte = date(2025, 12, 31)
        scraper = ArizScraper(params=params)
    """

    # === Metadata ===
    court_ids: ClassVar[set[str]] = {"ariz", "arizctapp"}
    court_url: ClassVar[str] = "https://www.azcourts.gov/"
    data_types: ClassVar[set[str]] = {"opinions"}
    status: ClassVar[ScraperStatus] = ScraperStatus.IN_DEVELOPMENT
    version: ClassVar[str] = "2026-01-22"
    requires_auth: ClassVar[bool] = False

    # Rate limiting - be respectful to court servers
    msec_per_request_rate_limit: ClassVar[int] = 1000

    # === XPath patterns (from existing scraper) ===
    XPATH_PDF_URLS = '//a[contains(@id, "hypCaseNum")]/@href'
    XPATH_CASE_NAMES = '//span[contains(@id, "lblTitle")]//text()'
    XPATH_FILING_DATES = '//span[contains(@id, "FilingDate")]//text()'
    XPATH_DECISION_TYPES = '//*[contains(@id, "DecType")]/text()'
    XPATH_DOCKET_NUMBERS = '//a[contains(@id, "hypCaseNum")]//text()'
    XPATH_JUDGES = '//span[contains(@id, "Judges")]//text()'
    XPATH_CONST_SUMMARY = (
        '//span[contains(@id, "ConstitutionalitySummary")]//text()'
    )

    # XPath for Division 2 site
    XPATH_DIV2_PDF_LINKS = "//table//a[contains(@href, '.pdf')]"

    # Regex pattern for date parsing
    DATE_PATTERN = re.compile(r"(\d{1,2}/\d{1,2}/\d{4})")

    def _get_search_params(
        self,
    ) -> tuple[date | None, date | None, str | None, set[str] | None]:
        """Extract search parameters from ScraperParams."""
        if self._params is None:
            return None, None, None, None

        try:
            model_proxy = self._params.ArizOpinionCluster
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

        docket_field = searchable.get("docket_id")
        if docket_field and docket_field.is_set():
            docket_number = docket_field.value

        court_field = searchable.get("court_id")
        if court_field and court_field.is_set():
            court_ids = court_field.values

        return date_gte, date_lte, docket_number, court_ids

    def _get_target_courts(self) -> set[str]:
        """Get the set of court IDs to scrape."""
        _, _, _, court_ids = self._get_search_params()
        if court_ids:
            valid_courts = court_ids & set(OPINIONS_CONFIG.keys())
            if valid_courts:
                return valid_courts
        return set(OPINIONS_CONFIG.keys())

    def _get_year_range(self) -> tuple[int, int]:
        """Determine year range to scrape based on params."""
        date_gte, date_lte, _, _ = self._get_search_params()
        current_year = datetime.now().year

        if date_gte:
            start_year = date_gte.year
        else:
            start_year = current_year  # Default to current year only

        if date_lte:
            end_year = date_lte.year
        else:
            end_year = current_year

        return start_year, end_year

    # =========================================================================
    # Entry Point
    # =========================================================================

    @entry(ArizOpinionCluster)
    def get_entry(self) -> Generator[NavigatingRequest, None, None]:
        """Yield initial requests for opinion scraping.

        Generates requests for each court and year combination based on params.
        """
        target_courts = self._get_target_courts()
        start_year, end_year = self._get_year_range()

        for court_id in sorted(target_courts):
            config = OPINIONS_CONFIG[court_id]

            for year in range(end_year, start_year - 1, -1):
                # Build the search URL with year parameter
                url = f"{config['search_url']}?court={config['court_param']}&year={year}"

                yield NavigatingRequest(
                    request=HTTPRequestParams(
                        method=HttpMethod.GET,
                        url=url,
                    ),
                    continuation=self.parse_opinion_results,
                    accumulated_data={
                        "court_id": court_id,
                        "year": year,
                    },
                )

        # Also scrape Division 2 if Court of Appeals is requested
        if "arizctapp" in target_courts:
            yield NavigatingRequest(
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url=DIV2_CONFIG["url"],
                ),
                continuation=self.parse_division2_results,
                accumulated_data={
                    "court_id": DIV2_CONFIG["court_id"],
                },
            )

    # =========================================================================
    # Main Site Parsing (Supreme Court & COA Div 1)
    # =========================================================================

    @step(xsd="xsds/parse_opinion_results.xsd")
    def parse_opinion_results(
        self,
        lxml_tree: CheckedHtmlElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[ArizOpinionCluster], None, None]:
        """Parse opinion search results from azcourts.gov.

        Extracts all opinions from the search results page and yields
        ArchiveRequests for each PDF.
        """
        court_id = accumulated_data.get("court_id", "ariz")
        year = accumulated_data.get("year")
        date_gte, date_lte, target_docket, _ = self._get_search_params()

        # Extract all data using xpaths
        pdf_urls = lxml_tree.checked_xpath(
            self.XPATH_PDF_URLS,
            "PDF URLs",
            min_count=0,
            type=str,
        )

        case_names = lxml_tree.checked_xpath(
            self.XPATH_CASE_NAMES,
            "case names",
            min_count=0,
            type=str,
        )

        filing_dates = lxml_tree.checked_xpath(
            self.XPATH_FILING_DATES,
            "filing dates",
            min_count=0,
            type=str,
        )

        decision_types = lxml_tree.checked_xpath(
            self.XPATH_DECISION_TYPES,
            "decision types",
            min_count=0,
            type=str,
        )

        docket_numbers = lxml_tree.checked_xpath(
            self.XPATH_DOCKET_NUMBERS,
            "docket numbers",
            min_count=0,
            type=str,
        )

        # Get judges info (may not exist for all entries)
        judges_list = lxml_tree.checked_xpath(
            self.XPATH_JUDGES,
            "judges",
            min_count=0,
            type=str,
        )

        # Get constitutionality summaries (may not exist for all entries)
        const_summaries = lxml_tree.checked_xpath(
            self.XPATH_CONST_SUMMARY,
            "constitutionality summaries",
            min_count=0,
            type=str,
        )

        # Process each opinion
        for i, pdf_url in enumerate(pdf_urls):
            if i >= len(docket_numbers):
                break

            docket_number = docket_numbers[i].strip()

            # Filter by docket number if specified
            if target_docket and docket_number != target_docket:
                continue

            # Parse filing date
            date_str = filing_dates[i] if i < len(filing_dates) else ""
            try:
                filed_date = datetime.strptime(
                    date_str.strip(), "%m/%d/%Y"
                ).date()
            except ValueError:
                # Try alternative format
                match = self.DATE_PATTERN.search(date_str)
                if match:
                    try:
                        filed_date = datetime.strptime(
                            match.group(1), "%m/%d/%Y"
                        ).date()
                    except ValueError:
                        filed_date = date.today()
                else:
                    filed_date = date.today()

            # Apply date filters
            if date_gte and filed_date < date_gte:
                continue
            if date_lte and filed_date > date_lte:
                continue

            # Extract case name
            case_name = case_names[i] if i < len(case_names) else "Unknown"
            case_name = titlecase(case_name.strip().upper())

            # Extract decision type
            decision_type = (
                decision_types[i] if i < len(decision_types) else "Unknown"
            )
            decision_type = decision_type.strip()

            # Determine precedential status from decision type
            if "OPINION" in decision_type.upper():
                precedential_status = "Published"
                opinion_type = "majority"
            elif "MEMORANDUM" in decision_type.upper():
                precedential_status = "Unpublished"
                opinion_type = "memorandum"
            elif "DECISION ORDER" in decision_type.upper():
                precedential_status = "Unpublished"
                opinion_type = "decision_order"
            else:
                precedential_status = "Unknown"
                opinion_type = "unknown"

            # Get judges if available
            judges = judges_list[i].strip() if i < len(judges_list) else None

            # Get constitutionality summary if available
            const_summary = (
                const_summaries[i].strip()
                if i < len(const_summaries)
                else None
            )

            # Resolve PDF URL
            full_pdf_url = urljoin(response.url, pdf_url)

            # Yield ArchiveRequest for the PDF
            yield ArchiveRequest(
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url=full_pdf_url,
                ),
                continuation=self.handle_opinion_download,
                expected_type="pdf",
                accumulated_data={
                    "docket_id": docket_number,
                    "court_id": court_id,
                    "date_filed": filed_date.isoformat(),
                    "case_name": case_name,
                    "decision_type": decision_type,
                    "precedential_status": precedential_status,
                    "opinion_type": opinion_type,
                    "judges": judges,
                    "constitutionality_summary": const_summary,
                    "source_url": response.url,
                    "publication_year": year,
                    "download_url": full_pdf_url,
                },
            )

    # =========================================================================
    # Division 2 Parsing (separate site)
    # =========================================================================

    @step(xsd="xsds/parse_division2_results.xsd")
    def parse_division2_results(
        self,
        lxml_tree: CheckedHtmlElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[ArizOpinionCluster], None, None]:
        """Parse opinions from Division 2 separate site.

        The Division 2 site has a different structure:
        - Table with PDF links
        - Docket number in the link text
        - Case name and date in following cells
        """
        court_id = accumulated_data.get("court_id", "arizctapp")
        date_gte, date_lte, target_docket, _ = self._get_search_params()

        # Find all PDF links in the table
        pdf_links = lxml_tree.checked_xpath(
            self.XPATH_DIV2_PDF_LINKS,
            "Division 2 PDF links",
            min_count=0,
        )

        for link in pdf_links:
            # Extract docket number from link text
            docket_text = (
                link.text_content().strip() if link.text_content() else ""
            )
            if not docket_text:
                continue

            # Filter by docket number if specified
            if target_docket and docket_text != target_docket:
                continue

            # Get PDF URL
            pdf_href = link.get("href")
            if not pdf_href:
                continue
            full_pdf_url = urljoin(response.url, pdf_href)

            # Extract case name from following cell
            name_elements = link.xpath("./following::td[1]/*/text()")
            if not name_elements:
                name_elements = link.xpath("./following::td[1]//text()")
            case_name = (
                name_elements[0].strip() if name_elements else "Unknown"
            )
            case_name = titlecase(case_name)

            # Extract date from following cell (format: "Opinion Filed: MM/DD/YYYY")
            date_elements = link.xpath("./following::td[2]/text()")
            date_str = date_elements[0].strip() if date_elements else ""

            # Parse date - format is "Opinion Filed: MM/DD/YYYY"
            match = self.DATE_PATTERN.search(date_str)
            if match:
                try:
                    filed_date = datetime.strptime(
                        match.group(1), "%m/%d/%Y"
                    ).date()
                except ValueError:
                    filed_date = date.today()
            else:
                filed_date = date.today()

            # Apply date filters
            if date_gte and filed_date < date_gte:
                continue
            if date_lte and filed_date > date_lte:
                continue

            # Extract summary from following row if available
            summary_elements = link.xpath("./following::tr[1]//text()")
            summary = (
                "".join(summary_elements).strip() if summary_elements else None
            )

            # Yield ArchiveRequest for the PDF
            yield ArchiveRequest(
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url=full_pdf_url,
                ),
                continuation=self.handle_opinion_download,
                expected_type="pdf",
                accumulated_data={
                    "docket_id": docket_text,
                    "court_id": court_id,
                    "date_filed": filed_date.isoformat(),
                    "case_name": case_name,
                    "decision_type": "OPINION",
                    "precedential_status": "Published",
                    "opinion_type": "majority",
                    "judges": None,
                    "constitutionality_summary": summary,
                    "source_url": response.url,
                    "publication_year": filed_date.year,
                    "download_url": full_pdf_url,
                },
            )

    # =========================================================================
    # PDF Download Handler
    # =========================================================================

    @step
    def handle_opinion_download(
        self,
        response: ArchiveResponse,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[ArizOpinionCluster], None, None]:
        """Handle a downloaded opinion PDF and yield the final cluster."""
        # Parse the date from ISO format
        filed_date = datetime.fromisoformat(
            accumulated_data["date_filed"]
        ).date()

        # Create the opinion object
        opinion = ArizOpinion(
            download_url=accumulated_data["download_url"],
            type=accumulated_data["opinion_type"],
            local_path=response.file_url,
        )

        # Create the cluster
        cluster = ArizOpinionCluster(
            docket_id=accumulated_data["docket_id"],
            court_id=accumulated_data["court_id"],
            date_filed=filed_date,
            case_name=accumulated_data["case_name"],
            opinions=[opinion],
            decision_type=accumulated_data.get("decision_type"),
            judges=accumulated_data.get("judges"),
            constitutionality_summary=accumulated_data.get(
                "constitutionality_summary"
            ),
            source_url=accumulated_data.get("source_url"),
            publication_year=accumulated_data.get("publication_year"),
            precedential_status=accumulated_data.get(
                "precedential_status", "Unknown"
            ),
        )

        yield ParsedData(cluster)
