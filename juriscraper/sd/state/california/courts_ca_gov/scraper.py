"""California Appellate Courts Scraper.

This module contains a unified scraper for opinions from the California
courts.ca.gov website for both the Supreme Court and Courts of Appeal.

Entry points:
- Published Opinions: https://www.courts.ca.gov/opinions/publishedcitable-opinions
- Unpublished Opinions: https://www.courts.ca.gov/opinions/unpublishednon-citable-opinions

Opinions Flow:
  1. get_entry -> opinions list page (published and/or unpublished)
  2. parse_opinions_page -> parses opinions, yields ArchiveRequests for PDFs
  3. handle_opinion_download -> stores local paths, yields final clusters
  4. Pagination: follows ?page=N links until no more results

Design decisions:
- Uses restrictive checked_xpaths to catch structural changes early
- Uses DateRange filter on date_filed for searching
- Uses SetFilter on court_id to select which courts to scrape
- Downloads all PDFs via ArchiveRequest
- Supports both published (120-day rolling) and unpublished (60-day rolling)
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import TYPE_CHECKING, Any, ClassVar
from urllib.parse import urljoin, urlparse, parse_qs, urlencode

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
    SOURCE_TO_COURT,
    CalOpinion,
    CalOpinionCluster,
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
                        division = f"CA{div_match.group(1)}/{div_match.group(2)}"
                        # Remove division from case name
                        case_name = full_title[: div_match.start()].strip()
                    # Remove trailing date patterns
                    date_suffix_match = re.search(
                        r"\s+\d{1,2}/\d{1,2}/\d{2,4}\s*$", case_name
                    )
                    if date_suffix_match:
                        case_name = case_name[: date_suffix_match.start()].strip()
                    # Also try "Month Day Year" format at end
                    date_suffix_match2 = re.search(
                        r"\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)"
                        r"[a-z]*\s+\d{1,2},?\s*\d{4}\s*$",
                        case_name,
                        re.IGNORECASE,
                    )
                    if date_suffix_match2:
                        case_name = case_name[: date_suffix_match2.start()].strip()

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
                    other_formats_url = urljoin(response.url, other_formats_url)

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
                    next_page = int(query_params.get("page", [current_page + 1])[0])

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
            "january": 1, "february": 2, "march": 3, "april": 4,
            "may": 5, "june": 6, "july": 7, "august": 8,
            "september": 9, "october": 10, "november": 11, "december": 12,
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
