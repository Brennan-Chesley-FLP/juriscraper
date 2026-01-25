"""California Appellate Courts Scraper.

This module contains scrapers for the California courts.ca.gov website:

1. CalScraper - Opinions from Supreme Court and Courts of Appeal
2. CalSupremeBriefsScraper - Briefs from argued Supreme Court cases
3. CalSupremeOralArgumentsScraper - Oral argument webcasts from Supreme Court
4. CalDocketScraper - Dockets from appellatecases.courtinfo.ca.gov

Entry points:
- Published Opinions: https://www.courts.ca.gov/opinions/publishedcitable-opinions
- Unpublished Opinions: https://www.courts.ca.gov/opinions/unpublishednon-citable-opinions
- Supreme Court Briefs: https://supreme.courts.ca.gov/case-information/briefs-argued-cases
- Supreme Court Oral Arguments: https://supreme.courts.ca.gov/case-information/oral-arguments/webcast-library
- Docket Search: https://appellatecases.courtinfo.ca.gov/search.cfm?dist={district_id}

Opinions Flow:
  1. get_entry -> opinions list page (published and/or unpublished)
  2. parse_opinions_page -> parses opinions, yields ArchiveRequests for PDFs
  3. handle_opinion_download -> stores local paths, yields final clusters
  4. Pagination: follows ?page=N links until no more results

Briefs Flow:
  1. get_entry -> briefs index page
  2. parse_briefs_index -> extracts session links, yields requests for each
  3. parse_briefs_session -> parses cases/briefs, yields ArchiveRequests for PDFs
  4. handle_brief_download -> stores local paths, yields final dockets

Oral Arguments Flow:
  1. get_entry -> webcast library page
  2. parse_webcast_library -> parses table rows, yields OralArgument objects

Docket Flow:
  1. get_entry -> search page for each court
  2. docket_search_{court_id} -> generates SpeculativeRequests for case numbers
  3. parse_docket_search -> parses Case Summary, yields requests for other tabs
  4. parse_docket_tab -> parses Docket (Register of Actions)
  5. parse_briefs_tab -> parses Briefs
  6. parse_disposition_tab -> parses Disposition
  7. parse_parties_tab -> parses Parties and Attorneys
  8. parse_trial_court_tab -> parses Trial Court, yields final CalAppellateDocket

Design decisions:
- Uses restrictive checked_xpaths to catch structural changes early
- Uses DateRange filter on date_filed for searching
- Uses SetFilter on court_id to select which courts to scrape
- Downloads all PDFs via ArchiveRequest
- Supports both published (120-day rolling) and unpublished (60-day rolling)
- Docket scraper uses SpeculativeRequests for case number enumeration
- Session tokens required for docket access (obtained through search form)
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import TYPE_CHECKING, Any, ClassVar
from urllib.parse import parse_qs, urljoin, urlparse

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
    SpeculativeRequest,
)

from .models import (
    CASE_PREFIX_TO_COURT,
    CalAppellateDocket,
    CalOpinion,
    CalOpinionCluster,
    CalSupremeBriefDocket,
    CalSupremeBriefEntry,
    CalSupremeOralArgument,
)

if TYPE_CHECKING:
    from collections.abc import Generator

    from juriscraper.scraper_driver.data_types import ScraperYield


# URLs for opinions pages
PUBLISHED_OPINIONS_URL = (
    "https://www.courts.ca.gov/opinions/publishedcitable-opinions"
)
UNPUBLISHED_OPINIONS_URL = (
    "https://www.courts.ca.gov/opinions/unpublishednon-citable-opinions"
)

# URLs for Supreme Court briefs and oral arguments
SUPREME_COURT_BRIEFS_URL = (
    "https://supreme.courts.ca.gov/case-information/briefs-argued-cases"
)
SUPREME_COURT_WEBCAST_LIBRARY_URL = "https://supreme.courts.ca.gov/case-information/oral-arguments/webcast-library"


class CalScraper(BaseScraper[CalOpinionCluster]):
    """Unified scraper for California appellate court opinions.

    Scrapes published and unpublished opinions from the CA Judicial Branch.
    Supports the Supreme Court and all Districts of the Courts of Appeal.

    Usage:
        # Scrape all opinions (published and unpublished, all courts)
        scraper = CalScraper()

        # Scrape only published opinions
        params = CalScraper.params()
        params.CalOpinionCluster.precedential_status.values = {"Published"}
        scraper = CalScraper(params=params)

        # Scrape only Supreme Court opinions
        params = CalScraper.params()
        params.CalOpinionCluster.court_id.values = {"cal"}
        scraper = CalScraper(params=params)

        # Filter opinions by date range
        params = CalScraper.params()
        params.CalOpinionCluster.date_filed.gte = date(2025, 12, 1)
        params.CalOpinionCluster.date_filed.lte = date(2025, 12, 31)
        scraper = CalScraper(params=params)

        # Scrape a specific case number
        params = CalScraper.params()
        params.CalOpinionCluster.case_number.eq = "S275272M"
        scraper = CalScraper(params=params)
    """

    # === Metadata ===
    court_ids: ClassVar[set[str]] = {
        "cal",
        "calctapp1d",
        "calctapp2d",
        "calctapp3d",
        "calctapp4d",
        "calctapp5d",
        "calctapp6d",
        "calappdeptsuper",
    }
    court_url: ClassVar[str] = "https://www.courts.ca.gov/"
    data_types: ClassVar[set[str]] = {"opinions"}
    status: ClassVar[ScraperStatus] = ScraperStatus.IN_DEVELOPMENT
    version: ClassVar[str] = "2026-01-22"
    requires_auth: ClassVar[bool] = False

    # Rate limiting - be respectful to court servers
    msec_per_request_rate_limit: ClassVar[int] = 1000

    # === Regex patterns ===
    # Case number pattern: S123456, A123456, B123456M, etc.
    # Suffix letters (M, N, S, A) indicate modifications/amendments
    CASE_NUMBER_PATTERN = re.compile(r"^([A-Z])(\d+)([A-Z]*)$")
    # Date pattern: January 22, 2026 or 1/22/26
    DATE_PATTERN = re.compile(
        r"(\d{1,2}/\d{1,2}/\d{2,4})|"
        r"(January|February|March|April|May|June|July|August|September|"
        r"October|November|December)\s+(\d{1,2}),?\s*(\d{4})"
    )
    # Division pattern from case title: CA1/4, CA2/6, CA4/1, etc.
    DIVISION_PATTERN = re.compile(r"CA(\d)/(\d)")

    # =========================================================================
    # Parameter extraction
    # =========================================================================

    def _get_search_params(
        self,
    ) -> tuple[
        date | None,
        date | None,
        str | None,
        set[str] | None,
        set[str] | None,
    ]:
        """Extract search parameters from ScraperParams.

        Returns:
            Tuple of (date_gte, date_lte, case_number, court_ids, statuses)
        """
        if self._params is None:
            return None, None, None, None, None

        try:
            model_proxy = self._params.CalOpinionCluster
        except AttributeError:
            return None, None, None, None, None

        date_gte = None
        date_lte = None
        case_number = None
        court_ids = None
        statuses = None

        searchable = model_proxy.get_searchable_fields()

        date_field = searchable.get("date_filed")
        if date_field and date_field.is_set():
            date_gte = date_field.gte
            date_lte = date_field.lte

        case_field = searchable.get("case_number")
        if case_field and case_field.is_set():
            case_number = case_field.value

        court_field = searchable.get("court_id")
        if court_field and court_field.is_set():
            court_ids = court_field.values

        status_field = searchable.get("precedential_status")
        if status_field and status_field.is_set():
            statuses = status_field.values

        return date_gte, date_lte, case_number, court_ids, statuses

    def _get_target_statuses(self) -> set[str]:
        """Get the set of publication statuses to scrape."""
        _, _, _, _, statuses = self._get_search_params()
        if statuses:
            return statuses
        return {"Published", "Unpublished"}

    def _get_target_courts(self) -> set[str] | None:
        """Get the set of court IDs to scrape (None means all)."""
        _, _, _, court_ids, _ = self._get_search_params()
        return court_ids

    # =========================================================================
    # Entry Point
    # =========================================================================

    def get_entry(self) -> Generator[NavigatingRequest, None, None]:
        """Yield initial requests for opinions pages.

        Yields requests for published and/or unpublished opinions
        based on params.
        """
        target_statuses = self._get_target_statuses()

        if "Published" in target_statuses:
            yield NavigatingRequest(
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url=PUBLISHED_OPINIONS_URL,
                ),
                continuation=self.parse_opinions_page,
                accumulated_data={
                    "precedential_status": "Published",
                    "page": 0,
                },
            )

        if "Unpublished" in target_statuses:
            yield NavigatingRequest(
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url=UNPUBLISHED_OPINIONS_URL,
                ),
                continuation=self.parse_opinions_page,
                accumulated_data={
                    "precedential_status": "Unpublished",
                    "page": 0,
                },
            )

    # =========================================================================
    # Opinions Scraping Steps
    # =========================================================================

    @step(xsd="xsds/parse_opinions_page.xsd")
    def parse_opinions_page(
        self,
        lxml_tree: CheckedHtmlElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[CalOpinionCluster], None, None]:
        """Parse the opinions list page and yield opinion clusters.

        Handles pagination by following ?page=N links.
        """
        precedential_status = accumulated_data.get(
            "precedential_status", "Published"
        )
        current_page = accumulated_data.get("page", 0)
        date_gte, date_lte, target_case, target_courts, _ = (
            self._get_search_params()
        )

        # Find all opinion list items
        # Structure: ul > li > div (card) containing case info and PDF link
        opinion_items = lxml_tree.checked_xpath(
            "//ul/li[.//a[contains(@href, '.PDF')]]",
            "opinion list items",
            min_count=0,  # Page might be empty on last page
        )

        found_in_date_range = False

        for item in opinion_items:
            # Extract case number and date from the first line
            # Format: "S275272M |January 22, 2026"
            case_info_text = item.checked_xpath(
                ".//div[contains(text(), '|')]",
                "case info div",
                min_count=0,
            )
            if not case_info_text:
                # Try alternate structure
                case_info_text = item.checked_xpath(
                    ".//*[contains(text(), '|')]",
                    "case info element",
                    min_count=0,
                )

            if not case_info_text:
                continue

            info_text = case_info_text[0].text_content().strip()
            parts = info_text.split("|")
            if len(parts) < 2:
                continue

            case_number = parts[0].strip()
            date_text = parts[1].strip()

            # Validate case number format
            case_match = self.CASE_NUMBER_PATTERN.match(case_number)
            if not case_match:
                continue

            # Extract court_id from case number prefix
            prefix = case_match.group(1)
            court_id = CASE_PREFIX_TO_COURT.get(prefix)
            if not court_id:
                continue

            # Filter by court_id if specified
            if target_courts and court_id not in target_courts:
                continue

            # Filter by specific case number if specified
            if target_case and case_number != target_case:
                continue

            # Parse date
            filed_date = self._parse_date(date_text)
            if not filed_date:
                continue

            # Apply date filters
            if date_gte and filed_date < date_gte:
                # If we're seeing dates before our range and this is a
                # date-ordered list, we might be past our range
                continue
            if date_lte and filed_date > date_lte:
                continue

            found_in_date_range = True

            # Extract source court from the second line
            # Format: "2nd District Court of Appeal • Published Opinion"
            source_info = item.checked_xpath(
                ".//div[contains(text(), 'Court of Appeal') or "
                "contains(text(), 'Supreme Court') or "
                "contains(text(), 'Appellate Division')]",
                "source court info",
                min_count=0,
            )
            source_court = None
            if source_info:
                source_text = source_info[0].text_content().strip()
                # Extract just the court name (before the bullet)
                if "•" in source_text:
                    source_court = source_text.split("•")[0].strip()
                else:
                    source_court = source_text

            # Extract case name from heading link
            case_name_links = item.checked_xpath(
                ".//h2//a | .//h3//a",
                "case name heading link",
                min_count=0,
            )
            case_name = "Unknown"
            case_info_url = None
            division = None

            if case_name_links:
                link = case_name_links[0]
                full_title = link.text_content().strip()
                case_info_url = link.get("href")

                # Parse case name - format: "P. v. Grandberry 1/22/26 CA2/6"
                # Remove the date and division suffix
                name_parts = full_title.rsplit(" ", 2)
                if len(name_parts) >= 1:
                    # Try to identify and remove date/division suffix
                    case_name = full_title
                    div_match = self.DIVISION_PATTERN.search(full_title)
                    if div_match:
                        division = (
                            f"CA{div_match.group(1)}/{div_match.group(2)}"
                        )
                        # Remove division from case name
                        case_name = full_title[: div_match.start()].strip()
                    # Remove trailing date patterns
                    date_suffix_match = re.search(
                        r"\s+\d{1,2}/\d{1,2}/\d{2,4}\s*$", case_name
                    )
                    if date_suffix_match:
                        case_name = case_name[
                            : date_suffix_match.start()
                        ].strip()
                    # Also try "Month Day Year" format at end
                    date_suffix_match2 = re.search(
                        r"\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)"
                        r"[a-z]*\s+\d{1,2},?\s*\d{4}\s*$",
                        case_name,
                        re.IGNORECASE,
                    )
                    if date_suffix_match2:
                        case_name = case_name[
                            : date_suffix_match2.start()
                        ].strip()

            # Extract PDF URL
            pdf_links = item.checked_xpath(
                ".//a[contains(@href, '.PDF')]",
                "PDF download link",
                min_count=1,
            )
            pdf_url = pdf_links[0].get("href")
            if not pdf_url:
                continue

            # Make URL absolute
            pdf_url = urljoin(response.url, pdf_url)

            # Extract "Other Formats" URL
            other_formats_links = item.checked_xpath(
                ".//a[contains(text(), 'Other Formats')]",
                "other formats link",
                min_count=0,
            )
            other_formats_url = None
            if other_formats_links:
                other_formats_url = other_formats_links[0].get("href")
                if other_formats_url:
                    other_formats_url = urljoin(
                        response.url, other_formats_url
                    )

            # Extract related cases if present
            related_cases: list[str] = []
            related_links = item.checked_xpath(
                ".//p[contains(text(), 'Related Cases')]//a",
                "related case links",
                min_count=0,
            )
            for rel_link in related_links:
                rel_case = rel_link.text_content().strip()
                if rel_case:
                    related_cases.append(rel_case)

            # Build cluster data and yield ArchiveRequest for PDF
            cluster_data: dict[str, Any] = {
                "case_number": case_number,
                "court_id": court_id,
                "date_filed": filed_date.isoformat(),
                "case_name": case_name,
                "precedential_status": precedential_status,
                "source_court": source_court,
                "division": division,
                "related_cases": related_cases,
                "case_info_url": case_info_url,
                "other_formats_url": other_formats_url,
                "source_url": response.url,
                "pdf_url": pdf_url,
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

        # Handle pagination - check for next page link
        # Only paginate if we found opinions in our date range
        if found_in_date_range or not (date_gte or date_lte):
            next_page_links = lxml_tree.checked_xpath(
                "//a[contains(text(), 'Next') or @aria-label='Go to next page']",
                "next page link",
                min_count=0,
            )

            if next_page_links:
                next_href = next_page_links[0].get("href")
                if next_href:
                    next_url = urljoin(response.url, next_href)

                    # Parse the page number from the URL
                    parsed = urlparse(next_url)
                    query_params = parse_qs(parsed.query)
                    next_page = int(
                        query_params.get("page", [current_page + 1])[0]
                    )

                    yield NavigatingRequest(
                        request=HTTPRequestParams(
                            method=HttpMethod.GET,
                            url=next_url,
                        ),
                        continuation=self.parse_opinions_page,
                        accumulated_data={
                            "precedential_status": precedential_status,
                            "page": next_page,
                        },
                    )

    @step
    def handle_opinion_download(
        self,
        response: ArchiveResponse,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[CalOpinionCluster], None, None]:
        """Handle a downloaded opinion PDF and yield the final cluster."""
        filed_date = datetime.fromisoformat(
            accumulated_data["date_filed"]
        ).date()

        opinion = CalOpinion(
            download_url=accumulated_data["pdf_url"],
            type="majority",
            local_path=response.file_url,
        )

        cluster = CalOpinionCluster(
            case_number=accumulated_data["case_number"],
            court_id=accumulated_data["court_id"],
            date_filed=filed_date,
            case_name=accumulated_data["case_name"],
            opinions=[opinion],
            precedential_status=accumulated_data["precedential_status"],
            source_court=accumulated_data.get("source_court"),
            division=accumulated_data.get("division"),
            related_cases=accumulated_data.get("related_cases", []),
            case_info_url=accumulated_data.get("case_info_url"),
            other_formats_url=accumulated_data.get("other_formats_url"),
            source_url=accumulated_data.get("source_url"),
        )

        yield ParsedData(cluster)

    # =========================================================================
    # Helper Methods
    # =========================================================================

    def _parse_date(self, date_text: str) -> date | None:
        """Parse a date string into a date object.

        Handles formats:
        - January 22, 2026
        - 1/22/26
        - 1/22/2026
        """
        date_text = date_text.strip()

        # Try month name format first: January 22, 2026
        month_names = {
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

        for month_name, month_num in month_names.items():
            if month_name in date_text.lower():
                match = re.search(
                    rf"{month_name}\s+(\d{{1,2}}),?\s*(\d{{4}})",
                    date_text,
                    re.IGNORECASE,
                )
                if match:
                    day = int(match.group(1))
                    year = int(match.group(2))
                    try:
                        return date(year, month_num, day)
                    except ValueError:
                        continue

        # Try numeric format: 1/22/26 or 1/22/2026
        numeric_match = re.search(r"(\d{1,2})/(\d{1,2})/(\d{2,4})", date_text)
        if numeric_match:
            month = int(numeric_match.group(1))
            day = int(numeric_match.group(2))
            year = int(numeric_match.group(3))

            # Handle 2-digit years
            if year < 100:
                # Assume 2000s for now (opinions are recent)
                year += 2000

            try:
                return date(year, month, day)
            except ValueError:
                pass

        return None


# =============================================================================
# Supreme Court Briefs Scraper
# =============================================================================


class CalSupremeBriefsScraper(BaseScraper[CalSupremeBriefDocket]):
    """Scraper for California Supreme Court briefs.

    Scrapes briefs filed in cases argued before the California Supreme Court.
    Briefs are organized by oral argument session dates, with PDFs available
    for download.

    Usage:
        # Scrape all briefs
        scraper = CalSupremeBriefsScraper()

        # Filter by oral argument date range
        params = CalSupremeBriefsScraper.params()
        params.CalSupremeBriefDocket.oral_argument_date.gte = date(2025, 1, 1)
        params.CalSupremeBriefDocket.oral_argument_date.lte = date(2025, 12, 31)
        scraper = CalSupremeBriefsScraper(params=params)

        # Scrape a specific case
        params = CalSupremeBriefsScraper.params()
        params.CalSupremeBriefDocket.case_number.eq = "S289430"
        scraper = CalSupremeBriefsScraper(params=params)
    """

    # === Metadata ===
    court_ids: ClassVar[set[str]] = {"cal"}
    court_url: ClassVar[str] = "https://supreme.courts.ca.gov/"
    data_types: ClassVar[set[str]] = {"briefs"}
    status: ClassVar[ScraperStatus] = ScraperStatus.IN_DEVELOPMENT
    version: ClassVar[str] = "2026-01-25"
    requires_auth: ClassVar[bool] = False

    # Rate limiting
    msec_per_request_rate_limit: ClassVar[int] = 1000

    # Regex patterns
    CASE_NUMBER_PATTERN = re.compile(r"S\d+")
    SESSION_DATE_PATTERN = re.compile(
        r"(January|February|March|April|May|June|July|August|September|"
        r"October|November|December)\s+(\d{1,2})(?:\s+and\s+\d{1,2})?,?\s*(\d{4})"
    )

    # =========================================================================
    # Parameter extraction
    # =========================================================================

    def _get_search_params(
        self,
    ) -> tuple[date | None, date | None, str | None]:
        """Extract search parameters from ScraperParams.

        Returns:
            Tuple of (date_gte, date_lte, case_number)
        """
        if self._params is None:
            return None, None, None

        try:
            model_proxy = self._params.CalSupremeBriefDocket
        except AttributeError:
            return None, None, None

        date_gte = None
        date_lte = None
        case_number = None

        searchable = model_proxy.get_searchable_fields()

        date_field = searchable.get("oral_argument_date")
        if date_field and date_field.is_set():
            date_gte = date_field.gte
            date_lte = date_field.lte

        case_field = searchable.get("case_number")
        if case_field and case_field.is_set():
            case_number = case_field.value

        return date_gte, date_lte, case_number

    # =========================================================================
    # Entry Point
    # =========================================================================

    def get_entry(self) -> Generator[NavigatingRequest, None, None]:
        """Yield initial request for the briefs index page."""
        yield NavigatingRequest(
            request=HTTPRequestParams(
                method=HttpMethod.GET,
                url=SUPREME_COURT_BRIEFS_URL,
            ),
            continuation=self.parse_briefs_index,
            accumulated_data={},
        )

    # =========================================================================
    # Briefs Scraping Steps
    # =========================================================================

    @step(xsd="xsds/parse_briefs_index.xsd")
    def parse_briefs_index(
        self,
        lxml_tree: CheckedHtmlElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[CalSupremeBriefDocket], None, None]:
        """Parse the briefs index page and yield requests for session pages.

        The index page has accordion sections for each year, with links to
        individual oral argument session pages.
        """
        date_gte, date_lte, target_case = self._get_search_params()

        # Find all session links in the accordion content
        # Structure: .usa-accordion__content > ul > li > a
        session_links = lxml_tree.checked_xpath(
            "//div[contains(@class, 'usa-accordion__content')]//a["
            "contains(@href, 'oral-argument-cases')]",
            "session page links",
            min_count=1,
        )

        for link in session_links:
            href = link.get("href")
            if not href:
                continue

            link_text = link.text_content().strip()

            # Parse the session date from the link text
            # Format: "February 4, 2026 Oral Argument Cases"
            session_date = self._parse_session_date(link_text)
            if not session_date:
                continue

            # Apply date filters
            if date_gte and session_date < date_gte:
                continue
            if date_lte and session_date > date_lte:
                continue

            session_url = urljoin(response.url, href)

            yield NavigatingRequest(
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url=session_url,
                ),
                continuation=self.parse_briefs_session,
                accumulated_data={
                    "session_date": session_date.isoformat(),
                    "session_url": session_url,
                    "target_case": target_case,
                },
            )

    @step(xsd="xsds/parse_briefs_session.xsd")
    def parse_briefs_session(
        self,
        lxml_tree: CheckedHtmlElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[CalSupremeBriefDocket], None, None]:
        """Parse a briefs session page and yield dockets with brief entries.

        Each session page contains multiple cases, each with their briefs listed.
        """
        session_date = datetime.fromisoformat(
            accumulated_data["session_date"]
        ).date()
        session_url = accumulated_data["session_url"]
        target_case = accumulated_data.get("target_case")

        # Find all case headings (h2 elements with case numbers)
        # Structure: h2 containing "S123456 - CASE NAME"
        case_headings = lxml_tree.checked_xpath(
            "//h2[contains(text(), 'S') and contains(text(), ' - ')]",
            "case headings",
            min_count=0,
        )

        for heading in case_headings:
            heading_text = heading.text_content().strip()

            # Extract case number and name
            # Format: "S289430 - IN RE Z.G."
            case_match = self.CASE_NUMBER_PATTERN.search(heading_text)
            if not case_match:
                continue

            case_number = case_match.group(0)

            # Filter by case number if specified
            if target_case and case_number != target_case:
                continue

            # Extract case name (everything after " - ")
            name_parts = heading_text.split(" - ", 1)
            case_name = name_parts[1].strip() if len(name_parts) > 1 else ""

            # Look for consolidated case info
            # Structure: following <p> with <em> containing "Consolidated case with"
            consolidated_with: list[str] = []
            next_p = heading.getnext()
            while next_p is not None and next_p.tag == "p":
                p_text = next_p.text_content().strip()
                if "Consolidated case with" in p_text:
                    # Extract case numbers
                    consolidated_cases = self.CASE_NUMBER_PATTERN.findall(
                        p_text
                    )
                    consolidated_with.extend(consolidated_cases)
                    next_p = next_p.getnext()
                elif "assigned justice" in p_text.lower():
                    next_p = next_p.getnext()
                else:
                    break

            # Look for assigned justice info
            assigned_justice = None
            justice_elements = heading.xpath(
                "following-sibling::p[contains(text(), 'assigned justice')]"
                "[position()=1]"
            )
            if justice_elements:
                justice_text = justice_elements[0].text_content().strip()
                # Extract justice name from "(Baltodano, J., assigned justice pro tempore)"
                justice_match = re.search(r"\(([^)]+)\)", justice_text)
                if justice_match:
                    assigned_justice = justice_match.group(1)

            # Find the briefs list following this heading
            # Structure: ul.jcc-list following the heading
            briefs_list = heading.xpath(
                "following-sibling::ul[contains(@class, 'jcc-list') or "
                ".//a[contains(@href, '.pdf')]][1]"
            )

            if not briefs_list:
                # Try alternative: any ul that comes after and has PDF links
                briefs_list = heading.xpath(
                    "following-sibling::ul[.//a[contains(@href, '.pdf')]][1]"
                )

            briefs: list[dict[str, Any]] = []
            if briefs_list:
                brief_items = briefs_list[0].xpath(
                    ".//li[.//a[contains(@href, '.pdf')]]"
                )
                for item in brief_items:
                    pdf_link = item.xpath(".//a[contains(@href, '.pdf')]")[0]
                    pdf_url = pdf_link.get("href")
                    if pdf_url:
                        pdf_url = urljoin(response.url, pdf_url)

                    brief_desc = pdf_link.text_content().strip()

                    # Extract filed date from the item text
                    # Format: "Filed on February 24, 2025"
                    item_text = item.text_content()
                    filed_date = None
                    filed_match = re.search(
                        r"Filed on\s+(\w+\s+\d{1,2},?\s*\d{4})", item_text
                    )
                    if filed_match:
                        filed_date = self._parse_date(filed_match.group(1))

                    # Categorize brief type
                    brief_type = self._categorize_brief(brief_desc)

                    briefs.append(
                        {
                            "description": brief_desc,
                            "download_url": pdf_url,
                            "date_filed": (
                                filed_date.isoformat()
                                if filed_date
                                else session_date.isoformat()
                            ),
                            "brief_type": brief_type,
                        }
                    )

            # Build docket data and yield ArchiveRequests for each brief PDF
            docket_data: dict[str, Any] = {
                "case_number": case_number,
                "case_name": case_name,
                "oral_argument_date": session_date.isoformat(),
                "assigned_justice": assigned_justice,
                "consolidated_with": consolidated_with,
                "session_url": session_url,
                "source_url": response.url,
                "briefs": briefs,
                "briefs_downloaded": [],
            }

            # Yield ArchiveRequest for first brief, chain the rest
            if briefs:
                docket_data["pending_briefs"] = briefs[1:]
                docket_data["current_brief_index"] = 0

                yield ArchiveRequest(
                    request=HTTPRequestParams(
                        method=HttpMethod.GET,
                        url=briefs[0]["download_url"],
                    ),
                    continuation=self.handle_brief_download,
                    expected_type="pdf",
                    accumulated_data=docket_data,
                )
            else:
                # No briefs to download, yield the docket as-is
                docket = CalSupremeBriefDocket(
                    case_number=case_number,
                    case_name=case_name,
                    oral_argument_date=session_date,
                    court_id="cal",
                    assigned_justice=assigned_justice,
                    consolidated_with=consolidated_with,
                    session_url=session_url,
                    source_url=response.url,
                    briefs=[],
                )
                yield ParsedData(docket)

    @step
    def handle_brief_download(
        self,
        response: ArchiveResponse,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[CalSupremeBriefDocket], None, None]:
        """Handle a downloaded brief PDF and continue with remaining briefs."""
        briefs = accumulated_data["briefs"]
        current_index = accumulated_data["current_brief_index"]
        pending_briefs = accumulated_data.get("pending_briefs", [])
        briefs_downloaded = accumulated_data["briefs_downloaded"]

        # Store the downloaded brief info
        current_brief = briefs[current_index]
        filed_date = datetime.fromisoformat(current_brief["date_filed"]).date()

        brief_entry = CalSupremeBriefEntry(
            description=current_brief["description"],
            date_filed=filed_date,
            download_url=current_brief["download_url"],
            local_path=response.file_url,
            brief_type=current_brief.get("brief_type"),
        )
        briefs_downloaded.append(brief_entry)

        # Check if there are more briefs to download
        if pending_briefs:
            next_brief = pending_briefs[0]
            accumulated_data["pending_briefs"] = pending_briefs[1:]
            accumulated_data["current_brief_index"] = current_index + 1
            accumulated_data["briefs_downloaded"] = briefs_downloaded

            yield ArchiveRequest(
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url=next_brief["download_url"],
                ),
                continuation=self.handle_brief_download,
                expected_type="pdf",
                accumulated_data=accumulated_data,
            )
        else:
            # All briefs downloaded, yield the final docket
            oral_arg_date = datetime.fromisoformat(
                accumulated_data["oral_argument_date"]
            ).date()

            docket = CalSupremeBriefDocket(
                case_number=accumulated_data["case_number"],
                case_name=accumulated_data["case_name"],
                oral_argument_date=oral_arg_date,
                court_id="cal",
                assigned_justice=accumulated_data.get("assigned_justice"),
                consolidated_with=accumulated_data.get(
                    "consolidated_with", []
                ),
                session_url=accumulated_data.get("session_url"),
                source_url=accumulated_data.get("source_url"),
                briefs=briefs_downloaded,
            )
            yield ParsedData(docket)

    # =========================================================================
    # Helper Methods
    # =========================================================================

    def _parse_session_date(self, text: str) -> date | None:
        """Parse a session date from text like 'February 4, 2026 Oral Argument Cases'."""
        match = self.SESSION_DATE_PATTERN.search(text)
        if not match:
            return None

        month_name = match.group(1).lower()
        day = int(match.group(2))
        year = int(match.group(3))

        month_map = {
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

        month = month_map.get(month_name)
        if not month:
            return None

        try:
            return date(year, month, day)
        except ValueError:
            return None

    def _parse_date(self, date_text: str) -> date | None:
        """Parse a date string like 'February 24, 2025'."""
        month_names = {
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

        for month_name, month_num in month_names.items():
            if month_name in date_text.lower():
                match = re.search(
                    rf"{month_name}\s+(\d{{1,2}}),?\s*(\d{{4}})",
                    date_text,
                    re.IGNORECASE,
                )
                if match:
                    day = int(match.group(1))
                    year = int(match.group(2))
                    try:
                        return date(year, month_num, day)
                    except ValueError:
                        continue
        return None

    def _categorize_brief(self, description: str) -> str:
        """Categorize a brief based on its description."""
        desc_lower = description.lower()

        if "petition for review" in desc_lower:
            return "petition"
        elif "opening brief" in desc_lower:
            return "opening"
        elif "answer brief" in desc_lower or "answer to" in desc_lower:
            return "answer"
        elif "reply brief" in desc_lower or "reply to" in desc_lower:
            return "reply"
        elif "amicus curiae" in desc_lower or "amicus" in desc_lower:
            return "amicus"
        elif "supplemental" in desc_lower:
            return "supplemental"
        elif "response" in desc_lower:
            return "response"
        elif "traverse" in desc_lower:
            return "traverse"
        elif "habeas corpus" in desc_lower:
            return "habeas"
        elif "focus issues" in desc_lower:
            return "focus_issues"
        else:
            return "other"


# =============================================================================
# Supreme Court Oral Arguments Scraper
# =============================================================================


class CalSupremeOralArgumentsScraper(BaseScraper[CalSupremeOralArgument]):
    """Scraper for California Supreme Court oral argument webcasts.

    Scrapes oral argument webcasts from the Supreme Court's webcast library.
    Each webcast is hosted on Granicus and includes case information,
    video embedding, and optional links to related opinions.

    Usage:
        # Scrape all oral arguments
        scraper = CalSupremeOralArgumentsScraper()

        # Filter by date range
        params = CalSupremeOralArgumentsScraper.params()
        params.CalSupremeOralArgument.date_argued.gte = date(2025, 1, 1)
        params.CalSupremeOralArgument.date_argued.lte = date(2025, 12, 31)
        scraper = CalSupremeOralArgumentsScraper(params=params)

        # Scrape a specific case
        params = CalSupremeOralArgumentsScraper.params()
        params.CalSupremeOralArgument.case_number.eq = "S286493"
        scraper = CalSupremeOralArgumentsScraper(params=params)
    """

    # === Metadata ===
    court_ids: ClassVar[set[str]] = {"cal"}
    court_url: ClassVar[str] = "https://supreme.courts.ca.gov/"
    data_types: ClassVar[set[str]] = {"oral_arguments"}
    status: ClassVar[ScraperStatus] = ScraperStatus.IN_DEVELOPMENT
    version: ClassVar[str] = "2026-01-25"
    requires_auth: ClassVar[bool] = False

    # Rate limiting
    msec_per_request_rate_limit: ClassVar[int] = 1000

    # Regex patterns
    CASE_NUMBER_PATTERN = re.compile(r"S\d+")
    GRANICUS_URL_PATTERN = re.compile(
        r"jcc\.granicus\.com/player/clip/(\d+)\?meta_id=(\d+)"
    )
    DATE_PATTERN = re.compile(r"(\d{2})/(\d{2})/(\d{4})")

    # =========================================================================
    # Parameter extraction
    # =========================================================================

    def _get_search_params(
        self,
    ) -> tuple[date | None, date | None, str | None]:
        """Extract search parameters from ScraperParams.

        Returns:
            Tuple of (date_gte, date_lte, case_number)
        """
        if self._params is None:
            return None, None, None

        try:
            model_proxy = self._params.CalSupremeOralArgument
        except AttributeError:
            return None, None, None

        date_gte = None
        date_lte = None
        case_number = None

        searchable = model_proxy.get_searchable_fields()

        date_field = searchable.get("date_argued")
        if date_field and date_field.is_set():
            date_gte = date_field.gte
            date_lte = date_field.lte

        case_field = searchable.get("case_number")
        if case_field and case_field.is_set():
            case_number = case_field.value

        return date_gte, date_lte, case_number

    # =========================================================================
    # Entry Point
    # =========================================================================

    def get_entry(self) -> Generator[NavigatingRequest, None, None]:
        """Yield initial request for the webcast library page."""
        yield NavigatingRequest(
            request=HTTPRequestParams(
                method=HttpMethod.GET,
                url=SUPREME_COURT_WEBCAST_LIBRARY_URL,
            ),
            continuation=self.parse_webcast_library,
            accumulated_data={},
        )

    # =========================================================================
    # Oral Arguments Scraping Steps
    # =========================================================================

    @step(xsd="xsds/parse_webcast_library.xsd")
    def parse_webcast_library(
        self,
        lxml_tree: CheckedHtmlElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[CalSupremeOralArgument], None, None]:
        """Parse the webcast library page and yield oral argument objects.

        The page has accordion sections for each year, with tables listing
        individual oral argument webcasts.
        """
        date_gte, date_lte, target_case = self._get_search_params()

        # Find all webcast table rows
        # Structure: table > tbody > tr containing Granicus links
        webcast_rows = lxml_tree.checked_xpath(
            "//tr[.//a[contains(@href, 'granicus.com/player')]]",
            "webcast table rows",
            min_count=0,
        )

        for row in webcast_rows:
            # Extract the Granicus link and case info
            granicus_links = row.xpath(
                ".//a[contains(@href, 'granicus.com/player')]"
            )
            if not granicus_links:
                continue

            granicus_link = granicus_links[0]
            granicus_url = granicus_link.get("href")
            if not granicus_url:
                continue

            # Make URL absolute
            if granicus_url.startswith("//"):
                granicus_url = "https:" + granicus_url
            elif not granicus_url.startswith("http"):
                granicus_url = urljoin(response.url, granicus_url)

            # Extract clip_id and meta_id from URL
            clip_id = None
            meta_id = None
            url_match = self.GRANICUS_URL_PATTERN.search(granicus_url)
            if url_match:
                clip_id = url_match.group(1)
                meta_id = url_match.group(2)

            # Extract case info from link text
            link_text = granicus_link.text_content().strip()

            # Extract case number(s)
            case_numbers = self.CASE_NUMBER_PATTERN.findall(link_text)
            if not case_numbers:
                continue

            case_number = case_numbers[0]

            # Filter by case number if specified
            if target_case and case_number != target_case:
                continue

            # Extract case name (text before case number)
            case_name = link_text
            # Try to clean up the case name
            # Format: "People v. Morgan (Henry), S286493"
            name_match = re.match(r"^(.+?),?\s*S\d+", link_text)
            if name_match:
                case_name = name_match.group(1).strip()

            # Check for automatic appeal
            is_automatic_appeal = "[Automatic Appeal]" in link_text

            # Check for assigned justice
            assigned_justice = None
            justice_match = re.search(r"\(([^)]+,\s*[JP]\..*?)\)", link_text)
            if justice_match:
                assigned_justice = justice_match.group(1)

            # Check for consolidated cases
            consolidated_cases = (
                case_numbers[1:] if len(case_numbers) > 1 else []
            )

            # Extract date argued from the next cell
            date_cells = row.xpath(".//td[2]")
            date_argued = None
            if date_cells:
                date_text = date_cells[0].text_content().strip()
                date_match = self.DATE_PATTERN.search(date_text)
                if date_match:
                    month = int(date_match.group(1))
                    day = int(date_match.group(2))
                    year = int(date_match.group(3))
                    try:
                        date_argued = date(year, month, day)
                    except ValueError:
                        pass

            if not date_argued:
                continue

            # Apply date filters
            if date_gte and date_argued < date_gte:
                continue
            if date_lte and date_argued > date_lte:
                continue

            # Check for opinion PDF link in the third cell
            opinion_pdf_url = None
            opinion_cells = row.xpath(".//td[3]//a[contains(@href, '.PDF')]")
            if opinion_cells:
                opinion_pdf_url = opinion_cells[0].get("href")
                if opinion_pdf_url and not opinion_pdf_url.startswith("http"):
                    opinion_pdf_url = urljoin(response.url, opinion_pdf_url)

            # Build embed URL
            embed_url = None
            if clip_id and meta_id:
                embed_url = (
                    f"//jcc.granicus.com/player/clip/{clip_id}"
                    f"?meta_id={meta_id}&embed=1"
                )

            oral_argument = CalSupremeOralArgument(
                case_number=case_number,
                case_name=case_name,
                court_id="cal",
                date_argued=date_argued,
                granicus_url=granicus_url,
                embed_url=embed_url,
                clip_id=clip_id,
                meta_id=meta_id,
                opinion_pdf_url=opinion_pdf_url,
                assigned_justice=assigned_justice,
                is_automatic_appeal=is_automatic_appeal,
                consolidated_cases=consolidated_cases,
                source_url=response.url,
            )

            yield ParsedData(oral_argument)


# =============================================================================
# California Appellate Docket Scraper
# =============================================================================

# Search URL for each court
DOCKET_SEARCH_BASE_URL = "https://appellatecases.courtinfo.ca.gov/search.cfm"

# Court configuration for docket scraping
# Maps court_id to (district_id, case_prefix, suggested_speculation_threshold)
# Thresholds based on observed case numbers from the search system
DOCKET_COURT_CONFIG = {
    "cal": {
        "district_id": 0,
        "case_prefix": "S",
        "court_name": "Supreme Court",
        # Suggested speculation threshold: S275000 (doc_id=2384930)
        "speculation_threshold": 275000,
    },
    "calctapp1d": {
        "district_id": 1,
        "case_prefix": "A",
        "court_name": "1st Appellate District",
        # Suggested speculation threshold: A170000 (doc_id=2982736)
        "speculation_threshold": 170000,
    },
    "calctapp2d": {
        "district_id": 2,
        "case_prefix": "B",
        "court_name": "2nd Appellate District",
        # Suggested speculation threshold: B330000 (doc_id=2657396)
        "speculation_threshold": 330000,
    },
    "calctapp3d": {
        "district_id": 3,
        "case_prefix": "C",
        "court_name": "3rd Appellate District",
        # Suggested speculation threshold: C100000
        "speculation_threshold": 100000,
    },
    "calctapp4d_div1": {
        "district_id": 41,
        "case_prefix": "D",
        "court_name": "4th Appellate District, Division 1",
        # Suggested speculation threshold: D085000
        "speculation_threshold": 85000,
    },
    "calctapp4d_div2": {
        "district_id": 42,
        "case_prefix": "E",
        "court_name": "4th Appellate District, Division 2",
        # Suggested speculation threshold: E085000
        "speculation_threshold": 85000,
    },
    "calctapp4d_div3": {
        "district_id": 43,
        "case_prefix": "G",
        "court_name": "4th Appellate District, Division 3",
        # Suggested speculation threshold: G065000
        "speculation_threshold": 65000,
    },
    "calctapp5d": {
        "district_id": 5,
        "case_prefix": "F",
        "court_name": "5th Appellate District",
        # Suggested speculation threshold: F090000
        "speculation_threshold": 90000,
    },
    "calctapp6d": {
        "district_id": 6,
        "case_prefix": "H",
        "court_name": "6th Appellate District",
        # Suggested speculation threshold: H055000
        "speculation_threshold": 55000,
    },
}


class CalDocketScraper(BaseScraper[CalAppellateDocket]):
    """Scraper for California appellate court dockets.

    Scrapes docket information from the appellatecases.courtinfo.ca.gov
    search system. Supports speculative enumeration of case numbers for
    each of the 9 appellate courts (Supreme Court and Courts of Appeal).

    The search system requires session tokens obtained through the search
    workflow, so this scraper navigates through the search form to access
    individual case pages.

    Usage:
        # Scrape all courts (speculative enumeration)
        scraper = CalDocketScraper()

        # Scrape a specific case number
        params = CalDocketScraper.params()
        params.CalAppellateDocket.case_number.eq = "S275000"
        scraper = CalDocketScraper(params=params)

        # Scrape only Supreme Court cases
        params = CalDocketScraper.params()
        params.CalAppellateDocket.court_id.values = {"cal"}
        scraper = CalDocketScraper(params=params)

        # Start speculation from a specific case number
        params = CalDocketScraper.params()
        params.CalAppellateDocket.speculative_case_num.gt = 275000
        params.CalAppellateDocket.court_id.values = {"cal"}
        scraper = CalDocketScraper(params=params)
    """

    # === Metadata ===
    court_ids: ClassVar[set[str]] = {
        "cal",
        "calctapp1d",
        "calctapp2d",
        "calctapp3d",
        "calctapp4d",
        "calctapp5d",
        "calctapp6d",
    }
    court_url: ClassVar[str] = "https://appellatecases.courtinfo.ca.gov/"
    data_types: ClassVar[set[str]] = {"dockets"}
    status: ClassVar[ScraperStatus] = ScraperStatus.IN_DEVELOPMENT
    version: ClassVar[str] = "2026-01-25"
    requires_auth: ClassVar[bool] = False

    # Rate limiting - be respectful to court servers
    msec_per_request_rate_limit: ClassVar[int] = 1000

    # Regex patterns
    CASE_NUMBER_PATTERN = re.compile(r"^([A-Z])(\d+)$")
    DATE_PATTERN = re.compile(r"(\d{2}/\d{2}/\d{4})")

    # =========================================================================
    # Parameter extraction
    # =========================================================================

    def _get_search_params(
        self,
    ) -> tuple[str | None, int | None, set[str] | None]:
        """Extract search parameters from ScraperParams.

        Returns:
            Tuple of (case_number, speculative_gt, court_ids)
        """
        if self._params is None:
            return None, None, None

        try:
            model_proxy = self._params.CalAppellateDocket
        except AttributeError:
            return None, None, None

        case_number = None
        speculative_gt = None
        court_ids = None

        searchable = model_proxy.get_searchable_fields()

        case_field = searchable.get("case_number")
        if case_field and case_field.is_set():
            case_number = case_field.value

        spec_field = searchable.get("speculative_case_num")
        if spec_field and spec_field.is_set():
            speculative_gt = spec_field.gt

        court_field = searchable.get("court_id")
        if court_field and court_field.is_set():
            court_ids = court_field.values

        return case_number, speculative_gt, court_ids

    def _get_target_courts(self) -> list[str]:
        """Get the list of court configurations to scrape."""
        _, _, court_ids = self._get_search_params()

        # Map court_ids to config keys (handle calctapp4d -> 3 divisions)
        target_configs = []

        if court_ids:
            for court_id in court_ids:
                if court_id == "calctapp4d":
                    # 4th District has 3 divisions
                    target_configs.extend(
                        [
                            "calctapp4d_div1",
                            "calctapp4d_div2",
                            "calctapp4d_div3",
                        ]
                    )
                elif court_id in DOCKET_COURT_CONFIG:
                    target_configs.append(court_id)
        else:
            # All courts
            target_configs = list(DOCKET_COURT_CONFIG.keys())

        return target_configs

    # =========================================================================
    # Entry Point
    # =========================================================================

    def get_entry(self) -> Generator[NavigatingRequest, None, None]:
        """Yield initial requests for docket scraping.

        For each target court, yields a NavigatingRequest to the search page
        which will then generate SpeculativeRequests for case numbers.
        """
        case_number, _, _ = self._get_search_params()

        # If specific case number requested, only scrape that
        if case_number:
            case_match = self.CASE_NUMBER_PATTERN.match(case_number)
            if case_match:
                prefix = case_match.group(1)
                case_num = int(case_match.group(2))

                # Find the config for this prefix
                for config_key, config in DOCKET_COURT_CONFIG.items():
                    if config["case_prefix"] == prefix:
                        yield NavigatingRequest(
                            request=HTTPRequestParams(
                                method=HttpMethod.GET,
                                url=f"{DOCKET_SEARCH_BASE_URL}?dist={config['district_id']}",
                            ),
                            continuation=self._get_court_step(config_key),
                            accumulated_data={
                                "court_config_key": config_key,
                                "target_case_num": case_num,
                                "single_case_mode": True,
                            },
                        )
                        return
            return

        # Otherwise, scrape all target courts
        target_courts = self._get_target_courts()

        for config_key in target_courts:
            config = DOCKET_COURT_CONFIG[config_key]
            yield NavigatingRequest(
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url=f"{DOCKET_SEARCH_BASE_URL}?dist={config['district_id']}",
                ),
                continuation=self._get_court_step(config_key),
                accumulated_data={
                    "court_config_key": config_key,
                },
            )

    def _get_court_step(self, config_key: str):
        """Get the step function for a specific court."""
        step_map = {
            "cal": self.docket_search_cal,
            "calctapp1d": self.docket_search_calctapp1d,
            "calctapp2d": self.docket_search_calctapp2d,
            "calctapp3d": self.docket_search_calctapp3d,
            "calctapp4d_div1": self.docket_search_calctapp4d_div1,
            "calctapp4d_div2": self.docket_search_calctapp4d_div2,
            "calctapp4d_div3": self.docket_search_calctapp4d_div3,
            "calctapp5d": self.docket_search_calctapp5d,
            "calctapp6d": self.docket_search_calctapp6d,
        }
        return step_map[config_key]

    # =========================================================================
    # Court-Specific Speculative Step Functions
    # =========================================================================

    @step(speculative=True)
    def docket_search_cal(
        self,
        lxml_tree: CheckedHtmlElement,
        response: Response,
        accumulated_data: dict,
        speculative_id: int,
    ) -> Generator[ScraperYield[CalAppellateDocket], bool | None, None]:
        """Generate SpeculativeRequests for California Supreme Court (S prefix).

        Suggested speculation threshold: S275000
        """
        yield from self._generate_speculative_requests(
            "cal", lxml_tree, response, accumulated_data, speculative_id
        )

    @step(speculative=True)
    def docket_search_calctapp1d(
        self,
        lxml_tree: CheckedHtmlElement,
        response: Response,
        accumulated_data: dict,
        speculative_id: int,
    ) -> Generator[ScraperYield[CalAppellateDocket], bool | None, None]:
        """Generate SpeculativeRequests for 1st District Court of Appeal (A prefix).

        Suggested speculation threshold: A170000
        """
        yield from self._generate_speculative_requests(
            "calctapp1d", lxml_tree, response, accumulated_data, speculative_id
        )

    @step(speculative=True)
    def docket_search_calctapp2d(
        self,
        lxml_tree: CheckedHtmlElement,
        response: Response,
        accumulated_data: dict,
        speculative_id: int,
    ) -> Generator[ScraperYield[CalAppellateDocket], bool | None, None]:
        """Generate SpeculativeRequests for 2nd District Court of Appeal (B prefix).

        Suggested speculation threshold: B330000
        """
        yield from self._generate_speculative_requests(
            "calctapp2d", lxml_tree, response, accumulated_data, speculative_id
        )

    @step(speculative=True)
    def docket_search_calctapp3d(
        self,
        lxml_tree: CheckedHtmlElement,
        response: Response,
        accumulated_data: dict,
        speculative_id: int,
    ) -> Generator[ScraperYield[CalAppellateDocket], bool | None, None]:
        """Generate SpeculativeRequests for 3rd District Court of Appeal (C prefix).

        Suggested speculation threshold: C100000
        """
        yield from self._generate_speculative_requests(
            "calctapp3d", lxml_tree, response, accumulated_data, speculative_id
        )

    @step(speculative=True)
    def docket_search_calctapp4d_div1(
        self,
        lxml_tree: CheckedHtmlElement,
        response: Response,
        accumulated_data: dict,
        speculative_id: int,
    ) -> Generator[ScraperYield[CalAppellateDocket], bool | None, None]:
        """Generate SpeculativeRequests for 4th District, Division 1 (D prefix).

        Suggested speculation threshold: D085000
        """
        yield from self._generate_speculative_requests(
            "calctapp4d_div1",
            lxml_tree,
            response,
            accumulated_data,
            speculative_id,
        )

    @step(speculative=True)
    def docket_search_calctapp4d_div2(
        self,
        lxml_tree: CheckedHtmlElement,
        response: Response,
        accumulated_data: dict,
        speculative_id: int,
    ) -> Generator[ScraperYield[CalAppellateDocket], bool | None, None]:
        """Generate SpeculativeRequests for 4th District, Division 2 (E prefix).

        Suggested speculation threshold: E085000
        """
        yield from self._generate_speculative_requests(
            "calctapp4d_div2",
            lxml_tree,
            response,
            accumulated_data,
            speculative_id,
        )

    @step(speculative=True)
    def docket_search_calctapp4d_div3(
        self,
        lxml_tree: CheckedHtmlElement,
        response: Response,
        accumulated_data: dict,
        speculative_id: int,
    ) -> Generator[ScraperYield[CalAppellateDocket], bool | None, None]:
        """Generate SpeculativeRequests for 4th District, Division 3 (G prefix).

        Suggested speculation threshold: G065000
        """
        yield from self._generate_speculative_requests(
            "calctapp4d_div3",
            lxml_tree,
            response,
            accumulated_data,
            speculative_id,
        )

    @step(speculative=True)
    def docket_search_calctapp5d(
        self,
        lxml_tree: CheckedHtmlElement,
        response: Response,
        accumulated_data: dict,
        speculative_id: int,
    ) -> Generator[ScraperYield[CalAppellateDocket], bool | None, None]:
        """Generate SpeculativeRequests for 5th District Court of Appeal (F prefix).

        Suggested speculation threshold: F090000
        """
        yield from self._generate_speculative_requests(
            "calctapp5d", lxml_tree, response, accumulated_data, speculative_id
        )

    @step(speculative=True)
    def docket_search_calctapp6d(
        self,
        lxml_tree: CheckedHtmlElement,
        response: Response,
        accumulated_data: dict,
        speculative_id: int,
    ) -> Generator[ScraperYield[CalAppellateDocket], bool | None, None]:
        """Generate SpeculativeRequests for 6th District Court of Appeal (H prefix).

        Suggested speculation threshold: H055000
        """
        yield from self._generate_speculative_requests(
            "calctapp6d", lxml_tree, response, accumulated_data, speculative_id
        )

    # =========================================================================
    # Speculative Request Generation
    # =========================================================================

    def _generate_speculative_requests(
        self,
        config_key: str,
        lxml_tree: CheckedHtmlElement,  # noqa: ARG002
        response: Response,
        accumulated_data: dict,
        speculative_id: int,
    ) -> Generator[ScraperYield[CalAppellateDocket], bool | None, None]:
        """Generate SpeculativeRequests for a court.

        This method generates case numbers and yields SpeculativeRequests
        for the search form submission. The driver will handle form submission
        via the continuation.
        """
        config = DOCKET_COURT_CONFIG[config_key]
        case_prefix = config["case_prefix"]
        district_id = config["district_id"]

        # Get starting point
        _, speculative_gt, _ = self._get_search_params()
        single_case_mode = accumulated_data.get("single_case_mode", False)
        target_case_num = accumulated_data.get("target_case_num")

        if single_case_mode and target_case_num:
            # Single case mode - just fetch one case
            case_number = f"{case_prefix}{target_case_num}"
            yield SpeculativeRequest(
                request=HTTPRequestParams(
                    method=HttpMethod.POST,
                    url=response.url,
                    data={
                        "query_caseNumber": case_number,
                        "caseSearch": "number",
                    },
                ),
                continuation=self.parse_docket_search,
                accumulated_data={
                    "court_config_key": config_key,
                    "case_number": case_number,
                    "case_num": target_case_num,
                    "district_id": district_id,
                },
                speculative_id=target_case_num,
            )
            return

        # Speculative enumeration mode
        start_num = speculative_id or speculative_gt or 1

        while True:
            case_number = f"{case_prefix}{start_num}"

            should_continue = yield SpeculativeRequest(
                request=HTTPRequestParams(
                    method=HttpMethod.POST,
                    url=response.url,
                    data={
                        "query_caseNumber": case_number,
                        "caseSearch": "number",
                    },
                ),
                continuation=self.parse_docket_search,
                accumulated_data={
                    "court_config_key": config_key,
                    "case_number": case_number,
                    "case_num": start_num,
                    "district_id": district_id,
                },
                speculative_id=start_num,
            )

            if not should_continue:
                break

            start_num += 1

    # =========================================================================
    # Common Parsing Steps
    # =========================================================================

    @step(xsd="xsds/parse_docket_search.xsd")
    def parse_docket_search(
        self,
        lxml_tree: CheckedHtmlElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[CalAppellateDocket], None, None]:
        """Parse the search results / case summary page.

        This is the common continuation for all 9 appellate courts.
        Extracts data from the Case Summary page and yields requests
        for additional tabs (Docket, Briefs, etc.).
        """
        config_key = accumulated_data["court_config_key"]
        config = DOCKET_COURT_CONFIG[config_key]
        case_number = accumulated_data["case_number"]
        case_num = accumulated_data["case_num"]

        # Check if we were redirected to an error page or session expired
        if "inputError" in response.url or "session has expired" in str(
            lxml_tree.text_content()
        ):
            # No case found at this number - expected for speculative scraping
            return

        # Check if we got search results (multiple matches) instead of a case page
        # This happens if the search returned multiple results
        search_results = lxml_tree.checked_xpath(
            "//table[contains(@class, 'searchResults')]//tr",
            "search results rows",
            min_count=0,
        )
        if search_results:
            # Multiple results - we need to handle this differently
            # For now, skip these cases
            return

        # Extract doc_id from URL
        doc_id = None
        if "doc_id=" in response.url:
            doc_id_match = re.search(r"doc_id=(\d+)", response.url)
            if doc_id_match:
                doc_id = int(doc_id_match.group(1))

        # Extract request_token from URL
        request_token = None
        if "request_token=" in response.url:
            token_match = re.search(r"request_token=([^&]+)", response.url)
            if token_match:
                request_token = token_match.group(1)

        # === Parse Case Summary ===
        case_name = (
            self._extract_text(lxml_tree, "Case Caption", response.url)
            or "Unknown"
        )

        # Map config to court_id
        court_id = config_key
        if config_key.startswith("calctapp4d_"):
            court_id = "calctapp4d"

        # Extract other case summary fields
        trial_court_case = self._extract_text(
            lxml_tree, "Trial Court Case", response.url
        )
        court_of_appeal_case = self._extract_text(
            lxml_tree, "Court of Appeal Case", response.url
        )
        division = self._extract_text(lxml_tree, "Division", response.url)
        case_type = self._extract_text(lxml_tree, "Case Type", response.url)
        case_category = self._extract_text(
            lxml_tree, "Case Category", response.url
        )
        case_status = self._extract_text(
            lxml_tree, "Case Status", response.url
        )
        issues = self._extract_text(lxml_tree, "Issues", response.url)
        case_citation = self._extract_text(
            lxml_tree, "Case Citation", response.url
        )
        oral_argument_datetime = self._extract_text(
            lxml_tree, "Oral Argument Date/Time", response.url
        )

        # Extract dates
        filing_date = self._extract_date(lxml_tree, "Filing Date")
        if not filing_date:
            filing_date = self._extract_date(lxml_tree, "Start Date")
        completion_date = self._extract_date(lxml_tree, "Completion Date")
        disposition_date = self._extract_date(lxml_tree, "Disposition Date")

        # Store case summary data for subsequent tab requests
        case_data = {
            "court_config_key": config_key,
            "court_id": court_id,
            "case_number": case_number,
            "case_num": case_num,
            "doc_id": doc_id,
            "request_token": request_token,
            "case_name": case_name,
            "trial_court_case": trial_court_case,
            "court_of_appeal_case": court_of_appeal_case,
            "division": division,
            "case_type": case_type,
            "case_category": case_category,
            "case_status": case_status,
            "issues": issues,
            "case_citation": case_citation,
            "oral_argument_datetime": oral_argument_datetime,
            "filing_date": filing_date.isoformat() if filing_date else None,
            "completion_date": (
                completion_date.isoformat() if completion_date else None
            ),
            "disposition_date": (
                disposition_date.isoformat() if disposition_date else None
            ),
            "source_url": response.url,
            # Initialize containers for data from other tabs
            "docket_entries": [],
            "briefs": [],
            "scheduled_actions": [],
            "dispositions": [],
            "parties": [],
            "trial_court_info": None,
            "cross_referenced_cases": [],
        }

        # Extract cross-referenced cases
        cross_ref_links = lxml_tree.checked_xpath(
            "//a[contains(@href, 'mainCaseScreen')]",
            "cross-referenced case links",
            min_count=0,
        )
        for link in cross_ref_links:
            link_text = link.text_content().strip()
            if link_text and link_text != case_number:
                case_data["cross_referenced_cases"].append(link_text)

        # Build the base URL for tab requests
        base_url = response.url.rsplit("/", 1)[0]

        # Request Docket tab
        yield NavigatingRequest(
            request=HTTPRequestParams(
                method=HttpMethod.GET,
                url=f"{base_url}/dockets.cfm?dist={config['district_id']}&doc_id={doc_id}&doc_no={case_number}&request_token={request_token}",
            ),
            continuation=self.parse_docket_tab,
            accumulated_data=case_data,
        )

    @step(xsd="xsds/parse_docket_tab.xsd")
    def parse_docket_tab(
        self,
        lxml_tree: CheckedHtmlElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[CalAppellateDocket], None, None]:
        """Parse the Docket (Register of Actions) tab."""
        config_key = accumulated_data["court_config_key"]
        config = DOCKET_COURT_CONFIG[config_key]
        case_number = accumulated_data["case_number"]
        doc_id = accumulated_data["doc_id"]
        request_token = accumulated_data["request_token"]

        # Parse docket entries from table
        rows = lxml_tree.checked_xpath(
            "//table//tr[td]",
            "docket entry rows",
            min_count=0,
        )

        docket_entries = []
        for row in rows:
            cells = row.xpath(".//td")
            if len(cells) >= 2:
                date_text = cells[0].text_content().strip()
                description = cells[1].text_content().strip()
                notes = (
                    cells[2].text_content().strip() if len(cells) > 2 else None
                )

                entry_date = self._parse_date(date_text)
                if entry_date and description:
                    docket_entries.append(
                        {
                            "entry_date": entry_date.isoformat(),
                            "description": description,
                            "notes": notes,
                        }
                    )

        accumulated_data["docket_entries"] = docket_entries

        # Request Briefs tab
        base_url = response.url.rsplit("/", 1)[0]
        yield NavigatingRequest(
            request=HTTPRequestParams(
                method=HttpMethod.GET,
                url=f"{base_url}/briefing.cfm?dist={config['district_id']}&doc_id={doc_id}&doc_no={case_number}&request_token={request_token}",
            ),
            continuation=self.parse_briefs_tab,
            accumulated_data=accumulated_data,
        )

    @step(xsd="xsds/parse_briefs_tab.xsd")
    def parse_briefs_tab(
        self,
        lxml_tree: CheckedHtmlElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[CalAppellateDocket], None, None]:
        """Parse the Briefs tab."""
        config_key = accumulated_data["court_config_key"]
        config = DOCKET_COURT_CONFIG[config_key]
        case_number = accumulated_data["case_number"]
        doc_id = accumulated_data["doc_id"]
        request_token = accumulated_data["request_token"]

        # Parse brief entries from table
        rows = lxml_tree.checked_xpath(
            "//table//tr[td]",
            "brief entry rows",
            min_count=0,
        )

        briefs = []
        for row in rows:
            cells = row.xpath(".//td")
            if len(cells) >= 2:
                brief_type = cells[0].text_content().strip()
                filing_party = (
                    cells[1].text_content().strip() if len(cells) > 1 else None
                )

                briefs.append(
                    {
                        "brief_type": brief_type,
                        "filing_party": filing_party,
                    }
                )

        accumulated_data["briefs"] = briefs

        # Request Disposition tab
        base_url = response.url.rsplit("/", 1)[0]
        yield NavigatingRequest(
            request=HTTPRequestParams(
                method=HttpMethod.GET,
                url=f"{base_url}/disposition.cfm?dist={config['district_id']}&doc_id={doc_id}&doc_no={case_number}&request_token={request_token}",
            ),
            continuation=self.parse_disposition_tab,
            accumulated_data=accumulated_data,
        )

    @step(xsd="xsds/parse_disposition_tab.xsd")
    def parse_disposition_tab(
        self,
        lxml_tree: CheckedHtmlElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[CalAppellateDocket], None, None]:
        """Parse the Disposition tab."""
        config_key = accumulated_data["court_config_key"]
        config = DOCKET_COURT_CONFIG[config_key]
        case_number = accumulated_data["case_number"]
        doc_id = accumulated_data["doc_id"]
        request_token = accumulated_data["request_token"]

        # Parse disposition entries from table
        rows = lxml_tree.checked_xpath(
            "//table//tr[td]",
            "disposition entry rows",
            min_count=0,
        )

        dispositions = []
        for row in rows:
            cells = row.xpath(".//td")
            if len(cells) >= 2:
                date_text = cells[0].text_content().strip()
                description = cells[1].text_content().strip()

                disp_date = self._parse_date(date_text)
                if disp_date and description:
                    dispositions.append(
                        {
                            "disposition_date": disp_date.isoformat(),
                            "description": description,
                        }
                    )

        accumulated_data["dispositions"] = dispositions

        # Extract citation if present
        citation_elem = lxml_tree.checked_xpath(
            "//*[contains(text(), 'Case Citation')]",
            "case citation element",
            min_count=0,
        )
        if citation_elem:
            parent = citation_elem[0].getparent()
            if parent is not None:
                citation_text = parent.text_content()
                if "none" not in citation_text.lower():
                    accumulated_data["case_citation"] = citation_text.split(
                        ":"
                    )[-1].strip()

        # Request Parties and Attorneys tab
        base_url = response.url.rsplit("/", 1)[0]
        yield NavigatingRequest(
            request=HTTPRequestParams(
                method=HttpMethod.GET,
                url=f"{base_url}/partiesAndAttorneys.cfm?dist={config['district_id']}&doc_id={doc_id}&doc_no={case_number}&request_token={request_token}",
            ),
            continuation=self.parse_parties_tab,
            accumulated_data=accumulated_data,
        )

    @step(xsd="xsds/parse_parties_tab.xsd")
    def parse_parties_tab(
        self,
        lxml_tree: CheckedHtmlElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[CalAppellateDocket], None, None]:
        """Parse the Parties and Attorneys tab."""
        config_key = accumulated_data["court_config_key"]
        config = DOCKET_COURT_CONFIG[config_key]
        case_number = accumulated_data["case_number"]
        doc_id = accumulated_data["doc_id"]
        request_token = accumulated_data["request_token"]

        # Parse parties from table
        rows = lxml_tree.checked_xpath(
            "//table//tr[td]",
            "party rows",
            min_count=0,
        )

        parties = []
        for row in rows:
            cells = row.xpath(".//td")
            if len(cells) >= 2:
                party_info = cells[0].text_content().strip()
                attorney_info = (
                    cells[1].text_content().strip() if len(cells) > 1 else ""
                )

                # Parse party name and type from "Name : Type" format
                if " : " in party_info:
                    name, party_type = party_info.split(" : ", 1)
                else:
                    name = party_info
                    party_type = "Unknown"

                # Parse attorneys (may be multiple)
                attorneys = [
                    a.strip()
                    for a in attorney_info.split("\n")
                    if a.strip() and a.strip() != "Pro Per"
                ]

                parties.append(
                    {
                        "name": name.strip(),
                        "party_type": party_type.strip(),
                        "attorneys": attorneys,
                    }
                )

        accumulated_data["parties"] = parties

        # Request Trial Court tab
        base_url = response.url.rsplit("/", 1)[0]
        yield NavigatingRequest(
            request=HTTPRequestParams(
                method=HttpMethod.GET,
                url=f"{base_url}/trialCourt.cfm?dist={config['district_id']}&doc_id={doc_id}&doc_no={case_number}&request_token={request_token}",
            ),
            continuation=self.parse_trial_court_tab,
            accumulated_data=accumulated_data,
        )

    @step(xsd="xsds/parse_trial_court_tab.xsd")
    def parse_trial_court_tab(
        self,
        lxml_tree: CheckedHtmlElement,
        response: Response,  # noqa: ARG002
        accumulated_data: dict,
    ) -> Generator[ScraperYield[CalAppellateDocket], None, None]:
        """Parse the Trial Court tab and yield the final docket."""
        # Parse trial court information
        trial_court_info = None

        # Check if there's trial court data
        no_data = lxml_tree.checked_xpath(
            "//*[contains(text(), 'No') and contains(text(), 'data found')]",
            "no data message",
            min_count=0,
        )

        if not no_data:
            trial_court_case = self._extract_text(
                lxml_tree, "Trial Court Case", response.url
            )
            trial_court_name = self._extract_text(
                lxml_tree, "Trial Court", response.url
            )
            trial_judge = self._extract_text(
                lxml_tree, "Trial Judge", response.url
            )
            judgment_date = self._extract_date(lxml_tree, "Judgment Date")

            if trial_court_case or trial_court_name:
                trial_court_info = {
                    "trial_court_case": trial_court_case,
                    "trial_court_name": trial_court_name,
                    "trial_judge": trial_judge,
                    "judgment_date": (
                        judgment_date.isoformat() if judgment_date else None
                    ),
                }

        accumulated_data["trial_court_info"] = trial_court_info

        # Now yield the final docket
        yield from self._yield_final_docket(accumulated_data)

    def _yield_final_docket(
        self, accumulated_data: dict
    ) -> Generator[ScraperYield[CalAppellateDocket], None, None]:
        """Build and yield the final CalAppellateDocket."""
        from .models import (
            CalAppellateDocket,
            CalBriefEntry,
            CalDisposition,
            CalDocketEntry,
            CalParty,
            CalTrialCourtInfo,
        )

        # Build docket entries
        docket_entries = [
            CalDocketEntry(
                entry_date=datetime.fromisoformat(e["entry_date"]).date(),
                description=e["description"],
                notes=e.get("notes"),
            )
            for e in accumulated_data.get("docket_entries", [])
        ]

        # Build brief entries
        briefs = [
            CalBriefEntry(
                brief_type=b["brief_type"],
                filing_party=b.get("filing_party"),
            )
            for b in accumulated_data.get("briefs", [])
        ]

        # Build dispositions
        dispositions = [
            CalDisposition(
                disposition_date=datetime.fromisoformat(
                    d["disposition_date"]
                ).date(),
                description=d["description"],
            )
            for d in accumulated_data.get("dispositions", [])
        ]

        # Build parties
        parties = [
            CalParty(
                name=p["name"],
                party_type=p["party_type"],
                attorneys=p.get("attorneys", []),
            )
            for p in accumulated_data.get("parties", [])
        ]

        # Build trial court info
        trial_court_info = None
        tc_data = accumulated_data.get("trial_court_info")
        if tc_data:
            trial_court_info = CalTrialCourtInfo(
                trial_court_case=tc_data.get("trial_court_case"),
                trial_court_name=tc_data.get("trial_court_name"),
                trial_judge=tc_data.get("trial_judge"),
                judgment_date=(
                    datetime.fromisoformat(tc_data["judgment_date"]).date()
                    if tc_data.get("judgment_date")
                    else None
                ),
            )

        # Build final docket
        docket = CalAppellateDocket(
            case_number=accumulated_data["case_number"],
            court_id=accumulated_data["court_id"],
            speculative_case_num=accumulated_data["case_num"],
            case_name=accumulated_data["case_name"],
            case_type=accumulated_data.get("case_type"),
            case_category=accumulated_data.get("case_category"),
            division=accumulated_data.get("division"),
            filing_date=(
                datetime.fromisoformat(accumulated_data["filing_date"]).date()
                if accumulated_data.get("filing_date")
                else None
            ),
            completion_date=(
                datetime.fromisoformat(
                    accumulated_data["completion_date"]
                ).date()
                if accumulated_data.get("completion_date")
                else None
            ),
            case_status=accumulated_data.get("case_status"),
            disposition_date=(
                datetime.fromisoformat(
                    accumulated_data["disposition_date"]
                ).date()
                if accumulated_data.get("disposition_date")
                else None
            ),
            case_citation=accumulated_data.get("case_citation"),
            issues=accumulated_data.get("issues"),
            oral_argument_datetime=accumulated_data.get(
                "oral_argument_datetime"
            ),
            trial_court_case=accumulated_data.get("trial_court_case"),
            court_of_appeal_case=accumulated_data.get("court_of_appeal_case"),
            cross_referenced_cases=accumulated_data.get(
                "cross_referenced_cases", []
            ),
            docket_entries=docket_entries,
            briefs=briefs,
            scheduled_actions=[],  # TODO: Parse scheduled actions tab for CoA
            dispositions=dispositions,
            parties=parties,
            trial_court_info=trial_court_info,
            doc_id=accumulated_data.get("doc_id"),
            source_url=accumulated_data.get("source_url"),
            request_token=accumulated_data.get("request_token"),
        )

        yield ParsedData(docket)

    # =========================================================================
    # Helper Methods
    # =========================================================================

    def _extract_text(
        self,
        lxml_tree: CheckedHtmlElement,
        label: str,
        url: str,  # noqa: ARG002
    ) -> str | None:
        """Extract text value following a label."""
        # Try to find elements containing the label
        label_elems = lxml_tree.checked_xpath(
            f"//*[contains(text(), '{label}')]",
            f"{label} label",
            min_count=0,
        )

        for elem in label_elems:
            # Get the next sibling or parent's next child
            next_elem = elem.getnext()
            if next_elem is not None:
                text = next_elem.text_content().strip()
                if text and text.lower() not in ("none", "no data found"):
                    return text

            # Try parent's structure
            parent = elem.getparent()
            if parent is not None:
                siblings = list(parent)
                idx = siblings.index(elem)
                if idx + 1 < len(siblings):
                    text = siblings[idx + 1].text_content().strip()
                    if text and text.lower() not in ("none", "no data found"):
                        return text

        return None

    def _extract_date(
        self, lxml_tree: CheckedHtmlElement, label: str
    ) -> date | None:
        """Extract a date value following a label."""
        text = self._extract_text(lxml_tree, label, "")
        if text:
            return self._parse_date(text)
        return None

    def _parse_date(self, date_text: str) -> date | None:
        """Parse a date string in MM/DD/YYYY format."""
        match = self.DATE_PATTERN.search(date_text)
        if match:
            try:
                return datetime.strptime(match.group(1), "%m/%d/%Y").date()
            except ValueError:
                pass
        return None
