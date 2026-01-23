"""Oklahoma Appellate Courts Opinion Scraper.

This module contains a unified scraper for opinions from Oklahoma courts:
- Oklahoma Supreme Court (okla)
- Oklahoma Court of Criminal Appeals (oklacrimapp)
- Oklahoma Court of Civil Appeals (oklacivapp)

Entry point:
- https://www.oscn.net/applications/oscn/Index.asp?ftdb={database}&year={year}&level=1

Database codes (ftdb):
- STOKCSSC: Oklahoma Supreme Court Cases (1890-present)
- STOKCSCR: Oklahoma Court of Criminal Appeals Cases (1908-present)
- STOKCSCV: Oklahoma Court of Civil Appeals Cases (1968-present)

Opinion URL pattern:
- https://www.oscn.net/applications/oscn/DeliverDocument.asp?CiteID={id}

Citation formats:
- Supreme Court: YYYY OK N (e.g., 2026 OK 1)
- Criminal Appeals: YYYY OK CR N (e.g., 2026 OK CR 1)
- Civil Appeals: YYYY OK CIV APP N (e.g., 2026 OK CIV APP 1)

Index page format:
- Each opinion is listed as a paragraph with a link
- Link text format: "CITATION, [P.3d cite,] MM/DD/YYYY, CASE NAME"

Flow:
  1. get_entry -> opinion index pages for selected courts/years
  2. parse_opinion_index -> extracts opinion metadata from paragraph links
  3. yields ParsedData with opinion clusters (HTML opinions, not PDFs)

Design decisions:
- Uses restrictive checked_xpaths to catch structural changes early
- Uses DateRange filter on date_filed for searching
- Uses SetFilter on court_id to select which courts to scrape
- Opinions are HTML pages, not PDFs (no ArchiveRequest needed)
- Supports year-based filtering via URL parameters
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import TYPE_CHECKING, ClassVar
from urllib.parse import urljoin

from juriscraper.scraper_driver.common.checked_html import CheckedHtmlElement
from juriscraper.scraper_driver.common.decorators import step
from juriscraper.scraper_driver.data_types import (
    BaseScraper,
    HttpMethod,
    HTTPRequestParams,
    NavigatingRequest,
    ParsedData,
    Response,
    ScraperStatus,
)

from .models import (
    COURT_ID_TO_FTDB,
    COURT_IDS,
    FTDB_TO_COURT_ID,
    OklahomaOpinion,
    OklahomaOpinionCluster,
)

if TYPE_CHECKING:
    from collections.abc import Generator

    from juriscraper.scraper_driver.data_types import ScraperYield


class OklahomaScraper(BaseScraper[OklahomaOpinionCluster]):
    """Unified scraper for Oklahoma appellate court opinions.

    Scrapes opinions from Oklahoma Supreme Court, Court of Criminal Appeals,
    and Court of Civil Appeals via the OSCN (Oklahoma State Courts Network).

    Usage:
        # Scrape all courts (default - Supreme Court only for efficiency)
        scraper = OklahomaScraper()

        # Scrape only Supreme Court
        params = OklahomaScraper.params()
        params.OklahomaOpinionCluster.court_id.values = {"okla"}
        scraper = OklahomaScraper(params=params)

        # Scrape all three appellate courts
        params = OklahomaScraper.params()
        params.OklahomaOpinionCluster.court_id.values = {
            "okla", "oklacrimapp", "oklacivapp"
        }
        scraper = OklahomaScraper(params=params)

        # Filter by date range
        params = OklahomaScraper.params()
        params.OklahomaOpinionCluster.date_filed.gte = date(2026, 1, 1)
        params.OklahomaOpinionCluster.date_filed.lte = date(2026, 1, 31)
        scraper = OklahomaScraper(params=params)

        # Lookup specific CiteID
        params = OklahomaScraper.params()
        params.OklahomaOpinionCluster.cite_id.value = "551118"
        scraper = OklahomaScraper(params=params)
    """

    # === Metadata ===
    court_ids: ClassVar[set[str]] = COURT_IDS
    court_url: ClassVar[str] = "https://www.oscn.net/"
    data_types: ClassVar[set[str]] = {"opinions"}
    status: ClassVar[ScraperStatus] = ScraperStatus.IN_DEVELOPMENT
    version: ClassVar[str] = "2026-01-23"
    requires_auth: ClassVar[bool] = False

    # Rate limiting - be respectful to court servers
    msec_per_request_rate_limit: ClassVar[int] = 1000

    # Base URL for opinion index
    INDEX_BASE_URL = "https://www.oscn.net/applications/oscn/Index.asp"

    # === Regex patterns ===
    # Citation patterns
    # Supreme Court: 2026 OK 1
    SC_CITATION_PATTERN = re.compile(r"(\d{4})\s+OK\s+(\d+)")
    # Criminal Appeals: 2026 OK CR 1
    CR_CITATION_PATTERN = re.compile(r"(\d{4})\s+OK\s+CR\s+(\d+)")
    # Civil Appeals: 2026 OK CIV APP 1
    CIV_CITATION_PATTERN = re.compile(r"(\d{4})\s+OK\s+CIV\s+APP\s+(\d+)")

    # Pacific Reporter citation: 562 P.3d 612
    PACIFIC_REPORTER_PATTERN = re.compile(r"(\d+)\s+P\.3d\s+(\d+)")

    # Date pattern: MM/DD/YYYY
    DATE_PATTERN = re.compile(r"(\d{1,2}/\d{1,2}/\d{4})")

    # CiteID from URL
    CITEID_PATTERN = re.compile(r"CiteID=(\d+)")

    def _parse_date(self, date_str: str) -> date | None:
        """Parse a date string in MM/DD/YYYY format.

        Args:
            date_str: Date string in M/D/YYYY format.

        Returns:
            Parsed date object, or None if parsing fails.
        """
        try:
            return datetime.strptime(date_str.strip(), "%m/%d/%Y").date()
        except ValueError:
            return None

    def _get_opinions_search_params(
        self,
    ) -> tuple[date | None, date | None, str | None, set[str] | None]:
        """Extract search parameters for opinions from ScraperParams.

        Returns:
            Tuple of (date_gte, date_lte, cite_id, court_ids)
        """
        if self._params is None:
            return None, None, None, None

        try:
            model_proxy = self._params.OklahomaOpinionCluster
        except AttributeError:
            return None, None, None, None

        date_gte = None
        date_lte = None
        cite_id = None
        court_ids = None

        searchable = model_proxy.get_searchable_fields()

        date_field = searchable.get("date_filed")
        if date_field and date_field.is_set():
            date_gte = date_field.gte
            date_lte = date_field.lte

        cite_id_field = searchable.get("cite_id")
        if cite_id_field and cite_id_field.is_set():
            cite_id = cite_id_field.value

        court_field = searchable.get("court_id")
        if court_field and court_field.is_set():
            court_ids = court_field.values

        return date_gte, date_lte, cite_id, court_ids

    def _get_target_databases(self) -> list[str]:
        """Get the list of database codes to scrape based on court_ids filter.

        Returns list of ftdb codes (STOKCSSC, STOKCSCR, STOKCSCV)
        """
        _, _, _, court_ids = self._get_opinions_search_params()

        if court_ids:
            databases = []
            for court_id in court_ids:
                if court_id in COURT_ID_TO_FTDB:
                    databases.append(COURT_ID_TO_FTDB[court_id])
            return databases if databases else ["STOKCSSC"]

        # Default: Supreme Court only
        return ["STOKCSSC"]

    def _build_index_url(self, ftdb: str, year: int) -> str:
        """Build the opinion index URL with parameters.

        Args:
            ftdb: Database code (STOKCSSC, STOKCSCR, STOKCSCV)
            year: Year to fetch opinions for

        Returns:
            URL string for the index page
        """
        return f"{self.INDEX_BASE_URL}?ftdb={ftdb}&year={year}&level=1"

    def _parse_link_text(
        self, link_text: str, link_url: str
    ) -> dict | None:
        """Parse the opinion link text to extract metadata.

        Link text format: "CITATION, [P.3d cite,] MM/DD/YYYY, CASE NAME"
        Examples:
        - "2026 OK 1, 01/13/2026, TOBACCO SETTLEMENT ENDOWMENT TRUST FUND v. STITT"
        - "2025 OK 1, 562 P.3d 612, 01/13/2025, STATE ex rel. OBA v. JONES"

        Args:
            link_text: The text content of the opinion link
            link_url: The URL of the opinion link

        Returns:
            Dictionary with parsed metadata, or None if parsing fails
        """
        # Extract CiteID from URL
        cite_id_match = self.CITEID_PATTERN.search(link_url)
        if not cite_id_match:
            return None
        cite_id = cite_id_match.group(1)

        # Determine court and citation
        citation = None
        court_id = None

        # Try Civil Appeals first (most specific pattern)
        civ_match = self.CIV_CITATION_PATTERN.search(link_text)
        if civ_match:
            year = civ_match.group(1)
            num = civ_match.group(2)
            citation = f"{year} OK CIV APP {num}"
            court_id = "oklacivapp"
        else:
            # Try Criminal Appeals
            cr_match = self.CR_CITATION_PATTERN.search(link_text)
            if cr_match:
                year = cr_match.group(1)
                num = cr_match.group(2)
                citation = f"{year} OK CR {num}"
                court_id = "oklacrimapp"
            else:
                # Try Supreme Court
                sc_match = self.SC_CITATION_PATTERN.search(link_text)
                if sc_match:
                    year = sc_match.group(1)
                    num = sc_match.group(2)
                    citation = f"{year} OK {num}"
                    court_id = "okla"

        if not citation or not court_id:
            return None

        # Extract Pacific Reporter citation (optional)
        pacific_cite = None
        pacific_match = self.PACIFIC_REPORTER_PATTERN.search(link_text)
        if pacific_match:
            pacific_cite = f"{pacific_match.group(1)} P.3d {pacific_match.group(2)}"

        # Extract date
        date_filed = None
        date_match = self.DATE_PATTERN.search(link_text)
        if date_match:
            date_filed = self._parse_date(date_match.group(1))

        # Extract case name - everything after the last date
        case_name = None
        if date_match:
            # Get text after the date
            after_date = link_text[date_match.end():].strip()
            # Remove leading comma and whitespace
            if after_date.startswith(","):
                after_date = after_date[1:].strip()
            if after_date:
                case_name = after_date

        if not case_name:
            return None

        return {
            "cite_id": cite_id,
            "court_id": court_id,
            "citation": citation,
            "pacific_reporter_cite": pacific_cite,
            "date_filed": date_filed,
            "case_name": case_name,
            "download_url": link_url,
        }

    # =========================================================================
    # Entry Point
    # =========================================================================

    def get_entry(self) -> Generator[NavigatingRequest, None, None]:
        """Yield initial requests for opinion scraping.

        Yields separate NavigatingRequests for each court database and year.
        """
        databases = self._get_target_databases()
        date_gte, date_lte, cite_id_filter, _ = self._get_opinions_search_params()

        # Determine year range for searching
        current_year = date.today().year
        year_from = date_gte.year if date_gte else current_year
        year_to = date_lte.year if date_lte else current_year

        # Build list of (database, year) pairs to process
        requests_to_make = []
        for ftdb in databases:
            for year in range(year_from, year_to + 1):
                requests_to_make.append((ftdb, year))

        if not requests_to_make:
            return

        first_ftdb, first_year = requests_to_make[0]
        remaining = requests_to_make[1:]

        url = self._build_index_url(first_ftdb, first_year)

        yield NavigatingRequest(
            request=HTTPRequestParams(
                method=HttpMethod.GET,
                url=url,
            ),
            continuation=self.parse_opinion_index,
            accumulated_data={
                "ftdb": first_ftdb,
                "year": first_year,
                "remaining_requests": remaining,
                "cite_id_filter": cite_id_filter,
                "date_gte": date_gte.isoformat() if date_gte else None,
                "date_lte": date_lte.isoformat() if date_lte else None,
            },
        )

    # =========================================================================
    # Opinion Index Parsing
    # =========================================================================

    @step(xsd="xsds/parse_opinion_index.xsd")
    def parse_opinion_index(
        self,
        lxml_tree: CheckedHtmlElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[OklahomaOpinionCluster], None, None]:
        """Parse the opinion index page.

        The index page lists opinions as paragraphs with links in the format:
        <p><a href="DeliverDocument.asp?CiteID=551118">2026 OK 1, 01/13/2026, CASE NAME</a></p>

        Extracts opinion metadata and yields ParsedData for each opinion.
        """
        ftdb = accumulated_data.get("ftdb", "STOKCSSC")
        remaining_requests = accumulated_data.get("remaining_requests", [])
        cite_id_filter = accumulated_data.get("cite_id_filter")
        date_gte_str = accumulated_data.get("date_gte")
        date_lte_str = accumulated_data.get("date_lte")

        date_gte = date.fromisoformat(date_gte_str) if date_gte_str else None
        date_lte = date.fromisoformat(date_lte_str) if date_lte_str else None

        # Get the expected court_id for this database
        expected_court_id = FTDB_TO_COURT_ID.get(ftdb, "okla")

        # Find all opinion links
        # The structure is: div > p > a[href*="DeliverDocument.asp?CiteID="]
        opinion_links = lxml_tree.xpath(
            "//a[contains(@href, 'DeliverDocument.asp?CiteID=')]"
        )

        for link in opinion_links:
            link_text = link.text_content().strip()
            link_href = link.get("href", "")

            if not link_text or not link_href:
                continue

            # Build full URL
            full_url = urljoin(response.url, link_href)

            # Parse the link text
            parsed = self._parse_link_text(link_text, full_url)
            if not parsed:
                continue

            # Verify court matches expected database
            if parsed["court_id"] != expected_court_id:
                continue

            # Apply filters
            if cite_id_filter and parsed["cite_id"] != cite_id_filter:
                continue

            if parsed["date_filed"]:
                if date_gte and parsed["date_filed"] < date_gte:
                    continue
                if date_lte and parsed["date_filed"] > date_lte:
                    continue

            # Build opinion
            opinion = OklahomaOpinion(
                download_url=parsed["download_url"],
                type="majority",
                local_path=None,
            )

            # Build and yield cluster
            cluster = OklahomaOpinionCluster(
                cite_id=parsed["cite_id"],
                court_id=parsed["court_id"],
                date_filed=parsed["date_filed"],
                case_name=parsed["case_name"],
                citation=parsed["citation"],
                docket_number=None,
                opinions=[opinion],
                source_url=response.url,
            )

            yield ParsedData(cluster)

        # Process remaining requests
        if remaining_requests:
            next_ftdb, next_year = remaining_requests[0]
            url = self._build_index_url(next_ftdb, next_year)

            yield NavigatingRequest(
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url=url,
                ),
                continuation=self.parse_opinion_index,
                accumulated_data={
                    "ftdb": next_ftdb,
                    "year": next_year,
                    "remaining_requests": remaining_requests[1:],
                    "cite_id_filter": cite_id_filter,
                    "date_gte": date_gte_str,
                    "date_lte": date_lte_str,
                },
            )
