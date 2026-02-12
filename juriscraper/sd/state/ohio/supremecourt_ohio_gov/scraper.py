"""Ohio Appellate Courts Opinion Scraper.

This module contains a unified scraper for opinions from Ohio courts:

- Ohio Supreme Court (ohio)
- First through Twelfth District Courts of Appeals (ohctapp1-12)
- Court of Claims (ohioctcl)

Entry point: ``https://www.supremecourt.ohio.gov/Rod/docs/Default.aspx``

Opinion Search URL patterns:

- Base URL: ``https://www.supremecourt.ohio.gov/Rod/docs/Default.aspx``
- With source filter: ``?source={N}`` where N is 0 (Supreme Court),
  1-12 (District Courts of Appeals), 13 (Court of Claims),
  15 (All Sources), or 16 (All District Courts)

PDF URL pattern: ``https://www.supremecourt.ohio.gov/rod/docs/pdf/{district}/{year}/{webcite}.pdf``
where district is 0 for Supreme Court or 1-12 for Courts of Appeals,
year is 4-digit, and webcite is e.g. "2026-Ohio-148".

Flow:

1. get_entry -> opinion search page for selected courts (if "opinions" requested)
2. parse_opinion_search -> extracts opinion metadata from results table
3. yields ArchiveRequests for PDFs
4. handle_opinion_download -> stores local paths, yields final clusters

Design decisions:

- Uses restrictive checked_xpaths to catch structural changes early
- Uses DateRange filter on date_decided for searching
- Uses SetFilter on court_id to select which courts to scrape
- Archives opinion PDFs via ArchiveRequest
- Supports year-based filtering via URL parameters
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import TYPE_CHECKING, Any, ClassVar
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
    COURT_ID_TO_SOURCE,
    COURT_IDS,
    SOURCE_TO_COURT_ID,
    OhioOpinion,
    OhioOpinionCluster,
)

if TYPE_CHECKING:
    from collections.abc import Generator

    from kent.data_types import ScraperYield


class OhioScraper(BaseScraper[OhioOpinionCluster]):
    """Unified scraper for Ohio appellate court opinions.

    Scrapes opinions from Ohio Supreme Court and Courts of Appeals.

    Usage:
        # Scrape all courts (default)
        scraper = OhioScraper()

        # Scrape only Supreme Court
        params = OhioScraper.params()
        params.OhioOpinionCluster.court_id.values = {"ohio"}
        scraper = OhioScraper(params=params)

        # Scrape specific district courts
        params = OhioScraper.params()
        params.OhioOpinionCluster.court_id.values = {"ohctapp1", "ohctapp8"}
        scraper = OhioScraper(params=params)

        # Filter by date range
        params = OhioScraper.params()
        params.OhioOpinionCluster.date_decided.gte = date(2026, 1, 1)
        params.OhioOpinionCluster.date_decided.lte = date(2026, 1, 31)
        scraper = OhioScraper(params=params)

        # Lookup specific webcite
        params = OhioScraper.params()
        params.OhioOpinionCluster.webcite.value = "2026-Ohio-148"
        scraper = OhioScraper(params=params)
    """

    # === Metadata ===
    court_ids: ClassVar[set[str]] = COURT_IDS
    court_url: ClassVar[str] = "https://www.supremecourt.ohio.gov/"
    data_types: ClassVar[set[str]] = {"opinions"}
    status: ClassVar[ScraperStatus] = ScraperStatus.IN_DEVELOPMENT
    version: ClassVar[str] = "2026-01-23"
    requires_auth: ClassVar[bool] = False

    # Rate limiting - be respectful to court servers
    msec_per_request_rate_limit: ClassVar[int] = 1000

    # Base URL for opinion search
    OPINION_SEARCH_URL = (
        "https://www.supremecourt.ohio.gov/Rod/docs/Default.aspx"
    )

    # === Regex patterns ===
    # Date pattern: MM/DD/YYYY or M/D/YYYY
    DATE_PATTERN = re.compile(r"(\d{1,2}/\d{1,2}/\d{4})")
    # WebCite pattern: YYYY-Ohio-NNN
    WEBCITE_PATTERN = re.compile(r"(\d{4}-Ohio-\d+)")
    # Case number pattern: YYYY-NNNN
    CASE_NUMBER_PATTERN = re.compile(r"(\d{4}-\d{4})")

    # Expected table headers
    EXPECTED_HEADERS = [
        "Case Caption",
        "Case No.",
        "Topics and Issues",
        "Author",
        "Citation / County",
        "Decided",
        "Posted",
        "WebCite",
    ]

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
            Tuple of (date_gte, date_lte, webcite, court_ids)
        """
        if self._params is None:
            return None, None, None, None

        try:
            model_proxy = self._params.OhioOpinionCluster
        except AttributeError:
            return None, None, None, None

        date_gte = None
        date_lte = None
        webcite = None
        court_ids = None

        searchable = model_proxy.get_searchable_fields()

        date_field = searchable.get("date_decided")
        if date_field and date_field.is_set():
            date_gte = date_field.gte
            date_lte = date_field.lte

        webcite_field = searchable.get("webcite")
        if webcite_field and webcite_field.is_set():
            webcite = webcite_field.value

        court_field = searchable.get("court_id")
        if court_field and court_field.is_set():
            court_ids = court_field.values

        return date_gte, date_lte, webcite, court_ids

    def _get_target_sources(self) -> list[int]:
        """Get the list of source numbers to scrape based on court_ids filter.

        Returns list of source numbers (0=Supreme Court, 1-12=Districts, etc.)
        """
        _, _, _, court_ids = self._get_opinions_search_params()

        if court_ids:
            sources = []
            for court_id in court_ids:
                if court_id in COURT_ID_TO_SOURCE:
                    sources.append(COURT_ID_TO_SOURCE[court_id])
            return (
                sorted(sources) if sources else [0]
            )  # Default to Supreme Court

        # Default: Supreme Court only (source=0)
        # Users can specify court_id.values to include other courts
        return [0]

    def _build_search_url(
        self, source: int, year_from: int, year_to: int
    ) -> str:
        """Build the opinion search URL with parameters.

        The Ohio site uses form POST for search, but we can use query params
        for source filtering and year range.
        """
        # The site actually loads with source as a query param
        return f"{self.OPINION_SEARCH_URL}?source={source}"

    # =========================================================================
    # Entry Point
    # =========================================================================

    @entry(OhioOpinionCluster)
    def get_entry(self) -> Generator[NavigatingRequest, None, None]:
        """Yield initial requests for opinion scraping.

        Yields separate NavigatingRequests for each court source.
        """
        sources = self._get_target_sources()
        date_gte, date_lte, webcite, _ = self._get_opinions_search_params()

        # Determine year range for searching
        current_year = date.today().year
        year_from = date_gte.year if date_gte else current_year
        year_to = date_lte.year if date_lte else current_year

        first_source = sources[0]
        remaining_sources = sources[1:]

        url = self._build_search_url(first_source, year_from, year_to)

        yield NavigatingRequest(
            request=HTTPRequestParams(
                method=HttpMethod.GET,
                url=url,
            ),
            continuation=self.parse_opinion_search,
            accumulated_data={
                "source": first_source,
                "remaining_sources": remaining_sources,
                "year_from": year_from,
                "year_to": year_to,
                "webcite_filter": webcite,
                "date_gte": date_gte.isoformat() if date_gte else None,
                "date_lte": date_lte.isoformat() if date_lte else None,
            },
        )

    # =========================================================================
    # Opinion Search Parsing
    # =========================================================================

    @step(xsd="xsds/parse_opinion_search.xsd")
    def parse_opinion_search(
        self,
        lxml_tree: CheckedHtmlElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[OhioOpinionCluster], None, None]:
        """Parse the opinion search results page.

        Extracts opinion metadata from the results table and yields
        ArchiveRequests for each opinion PDF.
        """
        source = accumulated_data.get("source", 0)
        remaining_sources = accumulated_data.get("remaining_sources", [])
        year_from = accumulated_data.get("year_from", date.today().year)
        year_to = accumulated_data.get("year_to", date.today().year)
        webcite_filter = accumulated_data.get("webcite_filter")
        date_gte_str = accumulated_data.get("date_gte")
        date_lte_str = accumulated_data.get("date_lte")

        date_gte = date.fromisoformat(date_gte_str) if date_gte_str else None
        date_lte = date.fromisoformat(date_lte_str) if date_lte_str else None

        # Get the court_id for this source
        court_id = SOURCE_TO_COURT_ID.get(source, "ohio")

        # Find the results table
        # The table has headers: Case Caption, Case No., Topics and Issues,
        # Author, Citation / County, Decided, Posted, WebCite
        result_rows = lxml_tree.xpath(
            "//table//tr[td[a[contains(@href, '.pdf')]]]"
        )

        for row in result_rows:
            cells = row.xpath("./td")
            if len(cells) < 8:
                continue

            # Extract data from each cell
            # Cell 0: Case Caption (link to PDF)
            caption_cell = cells[0]
            pdf_links = caption_cell.xpath(".//a[contains(@href, '.pdf')]")
            if not pdf_links:
                continue

            pdf_url = urljoin(response.url, pdf_links[0].get("href", ""))
            case_name = pdf_links[0].text_content().strip()

            # Cell 1: Case No.
            case_number = cells[1].text_content().strip() or None

            # Cell 2: Topics and Issues
            topics_and_issues = cells[2].text_content().strip() or None

            # Cell 3: Author
            author = cells[3].text_content().strip() or None

            # Cell 4: Citation / County
            citation_county = cells[4].text_content().strip() or None
            # For Supreme Court, this is the citation (e.g., "Slip Opinion No. 2026-Ohio-148")
            # For Courts of Appeals, this is the county name (e.g., "Hamilton")
            citation = None
            county = None
            if citation_county:
                if (
                    "Slip Opinion" in citation_county
                    or "Ohio" in citation_county
                ):
                    citation = citation_county
                else:
                    county = citation_county

            # Cell 5: Decided date
            decided_text = cells[5].text_content().strip()
            date_decided = None
            if decided_text:
                date_match = self.DATE_PATTERN.search(decided_text)
                if date_match:
                    date_decided = self._parse_date(date_match.group(1))

            # Cell 6: Posted date
            posted_text = cells[6].text_content().strip()
            date_posted = None
            if posted_text:
                date_match = self.DATE_PATTERN.search(posted_text)
                if date_match:
                    date_posted = self._parse_date(date_match.group(1))

            # Cell 7: WebCite
            webcite_text = cells[7].text_content().strip()
            webcite = None
            if webcite_text:
                webcite_match = self.WEBCITE_PATTERN.search(webcite_text)
                if webcite_match:
                    webcite = webcite_match.group(1)

            if not webcite:
                # Try to extract from PDF URL
                webcite_match = self.WEBCITE_PATTERN.search(pdf_url)
                if webcite_match:
                    webcite = webcite_match.group(1)

            if not webcite:
                continue  # Skip if no webcite found

            # Apply filters
            if webcite_filter and webcite != webcite_filter:
                continue

            if date_decided:
                if date_gte and date_decided < date_gte:
                    continue
                if date_lte and date_decided > date_lte:
                    continue

            # Build cluster data for accumulated_data
            cluster_data: dict[str, Any] = {
                "webcite": webcite,
                "court_id": court_id,
                "case_name": case_name,
                "case_number": case_number,
                "author": author,
                "topics_and_issues": topics_and_issues,
                "citation": citation,
                "county": county,
                "date_decided": date_decided.isoformat()
                if date_decided
                else None,
                "date_posted": date_posted.isoformat()
                if date_posted
                else None,
                "source_url": response.url,
                "opinions_data": [
                    {"download_url": pdf_url, "type": "majority"}
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

        # Check for pagination - Ohio uses ASP.NET ViewState for pagination
        # Look for page number links
        # Note: For simplicity, we're not implementing pagination here
        # as the default view shows 50 rows which is typically sufficient
        # for daily/weekly scraping. Full historical scraping would need
        # to implement pagination or use year filtering.

        # Move to next source after processing this one
        if remaining_sources:
            next_source = remaining_sources[0]
            url = self._build_search_url(next_source, year_from, year_to)

            yield NavigatingRequest(
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url=url,
                ),
                continuation=self.parse_opinion_search,
                accumulated_data={
                    "source": next_source,
                    "remaining_sources": remaining_sources[1:],
                    "year_from": year_from,
                    "year_to": year_to,
                    "webcite_filter": webcite_filter,
                    "date_gte": date_gte_str,
                    "date_lte": date_lte_str,
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
    ) -> Generator[ScraperYield[OhioOpinionCluster], None, None]:
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
    ) -> Generator[ScraperYield[OhioOpinionCluster], None, None]:
        """Build and yield the final OpinionCluster with all PDFs downloaded."""
        opinions = []
        for i, op_data in enumerate(accumulated_data["opinions_data"]):
            local_path = accumulated_data["downloaded_paths"].get(i)
            opinions.append(
                OhioOpinion(
                    download_url=op_data["download_url"],
                    type=op_data.get("type", "majority"),
                    local_path=local_path,
                    author=accumulated_data.get("author"),
                )
            )

        date_decided = None
        if accumulated_data.get("date_decided"):
            date_decided = date.fromisoformat(accumulated_data["date_decided"])

        date_posted = None
        if accumulated_data.get("date_posted"):
            date_posted = date.fromisoformat(accumulated_data["date_posted"])

        cluster = OhioOpinionCluster(
            webcite=accumulated_data["webcite"],
            court_id=accumulated_data["court_id"],
            date_decided=date_decided,
            case_name=accumulated_data["case_name"],
            case_number=accumulated_data.get("case_number"),
            author=accumulated_data.get("author"),
            topics_and_issues=accumulated_data.get("topics_and_issues"),
            citation=accumulated_data.get("citation"),
            county=accumulated_data.get("county"),
            date_posted=date_posted,
            opinions=opinions,
            source_url=accumulated_data.get("source_url"),
        )

        yield ParsedData(cluster)
