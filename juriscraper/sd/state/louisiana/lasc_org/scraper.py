"""Louisiana Supreme Court Scraper.

This module scrapes opinions from the Louisiana Supreme Court website.

Entry points:

- Court Actions: ``https://www.lasc.org/CourtActions/{year}``

  - Actions: ``https://www.lasc.org/Actions?p={year}-{number}``
  - Opinions: ``https://www.lasc.org/Opinions?p={year}-{number}``
  - Rehearings: ``https://www.lasc.org/Rehearings?p={year}-{number}``

Flow:

1. get_entry -> Court Actions year page URL (if "opinions" requested)
2. parse_court_actions_year -> parses table of releases, yields NavigatingRequests
3. parse_release_page -> parses individual release, yields ArchiveRequests for PDFs
4. handle_opinion_download -> yields final LouisianaOpinionCluster

Design decisions:

- Scrapes from Court Actions pages which list all releases
- Each release can be Actions (writ dispositions), Opinions (full opinions),
  or Rehearings (rehearing decisions)
- Uses DateRange filter on date_filed for searching
- Year parameter controls which year's releases to scrape
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
    COURT_ID,
    LouisianaOpinion,
    LouisianaOpinionCluster,
)

if TYPE_CHECKING:
    from collections.abc import Generator

    from kent.data_types import ScraperYield


# Base URL
BASE_URL = "https://www.lasc.org"


class LouisianaSupremeCourtScraper(BaseScraper[LouisianaOpinionCluster]):
    """Scraper for Louisiana Supreme Court opinions.

    Scrapes opinions and orders from the Louisiana Supreme Court.

    Usage:
        # Scrape current year's opinions
        scraper = LouisianaSupremeCourtScraper()

        # Filter by date range
        params = LouisianaSupremeCourtScraper.params()
        params.LouisianaOpinionCluster.date_filed.gte = date(2026, 1, 1)
        params.LouisianaOpinionCluster.date_filed.lte = date(2026, 1, 31)
        scraper = LouisianaSupremeCourtScraper(params=params)

        # Filter by specific case number
        params = LouisianaSupremeCourtScraper.params()
        params.LouisianaOpinionCluster.docket_id.value = "2025-C-01635"
        scraper = LouisianaSupremeCourtScraper(params=params)
    """

    # === Metadata ===
    court_ids: ClassVar[set[str]] = {"la"}
    court_url: ClassVar[str] = BASE_URL
    data_types: ClassVar[set[str]] = {"opinions"}
    status: ClassVar[ScraperStatus] = ScraperStatus.IN_DEVELOPMENT
    version: ClassVar[str] = "2026-01-22"
    requires_auth: ClassVar[bool] = False

    # Rate limiting - be respectful to court servers
    msec_per_request_rate_limit: ClassVar[int] = 1000

    # === Regex patterns ===
    # Case number pattern: YYYY-XX-NNNNN (e.g., 2025-C-01635)
    CASE_NUMBER_PATTERN = re.compile(r"(\d{4})-([A-Z]+)-(\d{4,5})")

    # Release number pattern: YYYY-NNN (e.g., 2026-001)
    RELEASE_NUMBER_PATTERN = re.compile(r"(\d{4})-(\d{3})")

    # Date patterns in release page text
    # "On the 7th day of January, 2026"
    RELEASE_DATE_PATTERN = re.compile(
        r"On the (\d{1,2})(?:st|nd|rd|th) day of (\w+),\s*(\d{4})"
    )

    # PDF URL pattern for extracting case number
    PDF_CASE_PATTERN = re.compile(
        r"/opinions/\d{4}/(\d{2})-(\d{4,5})\.([A-Z]+)\.(.*?)\.pdf"
    )

    # Mapping from model name to data type
    MODEL_TO_DATA_TYPE: ClassVar[dict[str, str]] = {
        "LouisianaOpinionCluster": "opinions",
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
    ) -> tuple[date | None, date | None, str | None]:
        """Extract search parameters from ScraperParams.

        Returns:
            Tuple of (date_gte, date_lte, docket_id)
        """
        if self._params is None:
            return None, None, None

        try:
            model_proxy = self._params.LouisianaOpinionCluster
        except AttributeError:
            return None, None, None

        date_gte = None
        date_lte = None
        docket_id = None

        searchable = model_proxy.get_searchable_fields()

        date_field = searchable.get("date_filed")
        if date_field and date_field.is_set():
            date_gte = date_field.gte
            date_lte = date_field.lte

        docket_field = searchable.get("docket_id")
        if docket_field and docket_field.is_set():
            docket_id = docket_field.value

        return date_gte, date_lte, docket_id

    def _get_target_years(self) -> list[int]:
        """Determine which years to scrape based on date filters."""
        date_gte, date_lte, _ = self._get_search_params()

        current_year = datetime.now().year

        if date_gte and date_lte:
            # Scrape years in the date range
            start_year = date_gte.year
            end_year = date_lte.year
            return list(range(start_year, end_year + 1))
        elif date_gte:
            # From start date to current year
            return list(range(date_gte.year, current_year + 1))
        elif date_lte:
            # Just the end date year
            return [date_lte.year]
        else:
            # Default to current year only
            return [current_year]

    def _parse_case_type_code(self, docket_number: str) -> str | None:
        """Extract case type code from docket number."""
        match = self.CASE_NUMBER_PATTERN.match(docket_number)
        if match:
            return match.group(2)
        return None

    def _parse_release_date(self, text: str) -> date | None:
        """Parse date from release page text.

        Args:
            text: Text like "On the 7th day of January, 2026"

        Returns:
            Parsed date or None
        """
        match = self.RELEASE_DATE_PATTERN.search(text)
        if match:
            day = int(match.group(1))
            month_name = match.group(2).lower()
            year = int(match.group(3))

            month = self.MONTH_MAP.get(month_name)
            if month:
                try:
                    return date(year, month, day)
                except ValueError:
                    return None
        return None

    def _extract_opinion_type_from_url(self, url: str) -> str:
        """Extract opinion type from PDF URL suffix.

        Args:
            url: PDF URL like '/opinions/2026/25-1635.C.PC.pdf'

        Returns:
            Opinion type string
        """
        url_lower = url.lower()
        if ".pc." in url_lower:
            return "per_curiam"
        elif ".opn." in url_lower:
            return "opinion"
        elif ".action." in url_lower:
            return "action"
        elif ".re." in url_lower or "rehearing" in url_lower:
            return "rehearing"
        elif ".dip." in url_lower or "dissent" in url_lower:
            return "dissent"
        elif ".cip." in url_lower or "concur" in url_lower:
            return "concurrence"
        elif ".grant." in url_lower:
            return "grant"
        else:
            return "unknown"

    def _extract_author_from_text(self, text: str) -> str | None:
        """Extract author from link text for dissents/concurrences.

        Args:
            text: Link text like "Penzato, J., dissents in part"

        Returns:
            Author name or None
        """
        # Look for justice name pattern at start
        match = re.match(r"([A-Za-z]+,?\s+[CJ]\.J?\.,?)", text)
        if match:
            return match.group(1).strip().rstrip(",")
        return None

    # =========================================================================
    # Entry Point
    # =========================================================================

    @entry(LouisianaOpinionCluster)
    def get_entry(self) -> Generator[NavigatingRequest, None, None]:
        """Yield initial requests to Court Actions year pages."""
        requested = self._get_requested_data_types()

        if "opinions" in requested:
            years = self._get_target_years()
            for year in years:
                url = f"{BASE_URL}/CourtActions/{year}"
                yield NavigatingRequest(
                    request=HTTPRequestParams(
                        method=HttpMethod.GET,
                        url=url,
                    ),
                    continuation=self.parse_court_actions_year,
                    accumulated_data={"year": year},
                )

    # =========================================================================
    # Court Actions Year Page
    # =========================================================================

    @step(xsd="xsds/parse_court_actions_year.xsd")
    def parse_court_actions_year(
        self,
        lxml_tree: CheckedHtmlElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[LouisianaOpinionCluster], None, None]:
        """Parse Court Actions year page to find all releases."""
        year = accumulated_data["year"]
        date_gte, date_lte, _ = self._get_search_params()

        # Find the table with releases
        # Table structure: Release #, Date, Type
        rows = lxml_tree.checked_xpath(
            "//table//tbody//tr",
            "release rows",
            min_count=0,
        )

        for row in rows:
            # Extract cells
            cells = row.checked_xpath(
                "td",
                "row cells",
                min_count=3,
                max_count=3,
            )

            # Date link
            date_links = cells[1].checked_xpath(
                "a",
                "date link",
                min_count=1,
                max_count=1,
            )
            date_link = date_links[0]
            date_text = date_link.text_content().strip()
            href = date_link.get("href", "")

            # Release type (Actions, Opinions, Rehearings)
            release_type = cells[2].text_content().strip().lower()

            # Build full URL
            release_url = urljoin(response.url, href)

            # Extract release number from URL (e.g., "2025-058")
            release_match = self.RELEASE_NUMBER_PATTERN.search(href)
            release_number = release_match.group(0) if release_match else None

            # We process all release types (actions, opinions, rehearings)
            # as they all contain opinion PDFs
            yield NavigatingRequest(
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url=release_url,
                ),
                continuation=self.parse_release_page,
                accumulated_data={
                    "year": year,
                    "release_number": release_number,
                    "release_type": release_type,
                    "release_date_text": date_text,
                    "date_gte": date_gte.isoformat() if date_gte else None,
                    "date_lte": date_lte.isoformat() if date_lte else None,
                },
            )

    # =========================================================================
    # Release Page (Actions, Opinions, or Rehearings)
    # =========================================================================

    @step(xsd="xsds/parse_release_page.xsd")
    def parse_release_page(
        self,
        lxml_tree: CheckedHtmlElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[LouisianaOpinionCluster], None, None]:
        """Parse a release page to extract cases and PDFs."""
        date_gte_str = accumulated_data.get("date_gte")
        date_lte_str = accumulated_data.get("date_lte")
        date_gte = date.fromisoformat(date_gte_str) if date_gte_str else None
        date_lte = date.fromisoformat(date_lte_str) if date_lte_str else None

        _, _, target_docket = self._get_search_params()

        release_number = accumulated_data.get("release_number")
        release_type = accumulated_data.get("release_type")

        # Find all paragraphs with PDF links - these are the cases
        case_paragraphs = lxml_tree.checked_xpath(
            "//p[.//a[contains(@href, '.pdf')]]",
            "case paragraphs with PDF links",
            min_count=0,
        )

        # Track which header applies to which paragraph by position
        for para in case_paragraphs:
            # Find the nearest preceding h1 header
            preceding_headers = para.checked_xpath(
                "preceding::h1",
                "preceding headers",
                min_count=0,
            )
            disposition = None
            if preceding_headers:
                # Get the most recent one (last in the list)
                disposition = preceding_headers[-1].text_content().strip()
                # Clean up the disposition text
                disposition = disposition.rstrip(":")

            # Find preceding paragraph with date info
            preceding_paras = para.checked_xpath(
                "preceding::p[contains(text(), 'day of')]",
                "date paragraphs",
                min_count=0,
            )
            release_date = None
            if preceding_paras:
                date_para_text = preceding_paras[-1].text_content()
                release_date = self._parse_release_date(date_para_text)

            # Filter by date if specified
            if release_date:
                if date_gte and release_date < date_gte:
                    continue
                if date_lte and release_date > date_lte:
                    continue
            else:
                # If we can't parse a date, skip date filtering for this item
                pass

            # Get all links in this paragraph
            links = para.checked_xpath(
                ".//a[contains(@href, '.pdf')]",
                "PDF links",
                min_count=1,
            )

            # First link is typically the main case link
            main_link = links[0]
            case_text = main_link.text_content().strip()
            main_pdf_url = urljoin(response.url, main_link.get("href", ""))

            # Extract case number from text
            case_match = self.CASE_NUMBER_PATTERN.search(case_text)
            if not case_match:
                continue

            docket_id = case_match.group(0)

            # Filter by specific docket if requested
            if target_docket and docket_id != target_docket:
                continue

            # Extract case name (everything after the case number)
            case_name_start = case_match.end()
            case_name = case_text[case_name_start:].strip()
            # Clean up case name
            case_name = case_name.lstrip(" -").strip()

            # Extract parish from the paragraph text
            para_text = para.text_content()
            parish = None
            parish_match = re.search(r"\(Parish of ([^)]+)\)", para_text)
            if parish_match:
                parish = f"Parish of {parish_match.group(1)}"

            # Extract votes/dissents (text nodes in paragraph not in links)
            votes = []
            # Get all text content that's not in links
            for text in para.itertext():
                text = text.strip()
                if text and "J.," in text and not text.startswith("2"):
                    # This is likely a vote notation
                    votes.append(text)

            # Build opinions list - main opinion first
            opinions_data = [
                {
                    "download_url": main_pdf_url,
                    "opinion_type": self._extract_opinion_type_from_url(
                        main_pdf_url
                    ),
                    "author": None,
                }
            ]

            # Additional links (concurrences, dissents)
            for link in links[1:]:
                href = link.get("href", "")
                if not href:
                    continue
                pdf_url = urljoin(response.url, href)
                link_text = link.text_content().strip()
                author = self._extract_author_from_text(link_text)
                opinion_type = self._extract_opinion_type_from_url(pdf_url)
                if "dissent" in link_text.lower():
                    opinion_type = "dissent"
                elif "concur" in link_text.lower():
                    opinion_type = "concurrence"

                opinions_data.append(
                    {
                        "download_url": pdf_url,
                        "opinion_type": opinion_type,
                        "author": author,
                    }
                )

            # Build accumulated data for download
            cluster_data = {
                "docket_id": docket_id,
                "court_id": COURT_ID,
                "date_filed": release_date.isoformat()
                if release_date
                else None,
                "case_name": case_name,
                "source_url": response.url,
                "parish": parish,
                "disposition": disposition,
                "release_number": release_number,
                "release_type": release_type,
                "votes": votes,
                "case_type_code": self._parse_case_type_code(docket_id),
                "opinions_data": opinions_data,
                "pending_downloads": len(opinions_data),
                "completed_downloads": 0,
                "downloaded_paths": {},
            }

            # Yield ArchiveRequest for first PDF
            first_url = opinions_data[0]["download_url"]
            assert isinstance(first_url, str)
            yield ArchiveRequest(
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url=first_url,
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
    ) -> Generator[ScraperYield[LouisianaOpinionCluster], None, None]:
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
            # Download next file
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
    ) -> Generator[ScraperYield[LouisianaOpinionCluster], None, None]:
        """Build and yield the final OpinionCluster with all PDFs downloaded."""
        opinions = []
        for i, op_data in enumerate(accumulated_data["opinions_data"]):
            local_path = accumulated_data["downloaded_paths"].get(i)
            opinions.append(
                LouisianaOpinion(
                    download_url=op_data["download_url"],
                    opinion_type=op_data["opinion_type"],
                    author=op_data.get("author"),
                    local_path=local_path,
                )
            )

        date_filed = None
        if accumulated_data.get("date_filed"):
            date_filed = datetime.fromisoformat(
                accumulated_data["date_filed"]
            ).date()
        else:
            # Use current date as fallback
            date_filed = date.today()

        cluster = LouisianaOpinionCluster(
            docket_id=accumulated_data["docket_id"],
            court_id=accumulated_data["court_id"],
            date_filed=date_filed,
            case_name=accumulated_data["case_name"],
            opinions=opinions,
            source_url=accumulated_data["source_url"],
            parish=accumulated_data.get("parish"),
            disposition=accumulated_data.get("disposition"),
            release_number=accumulated_data.get("release_number"),
            release_type=accumulated_data.get("release_type"),
            votes=accumulated_data.get("votes", []),
            case_type_code=accumulated_data.get("case_type_code"),
            precedential_status="Unknown",
        )

        yield ParsedData(cluster)
