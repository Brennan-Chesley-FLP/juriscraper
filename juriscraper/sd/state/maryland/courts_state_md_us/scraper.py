"""Maryland Appellate Courts Scraper.

This module scrapes published opinions from Maryland appellate courts:
- Supreme Court of Maryland (md) - formerly Court of Appeals
- Appellate Court of Maryland (mdctspecapp) - formerly Court of Special Appeals

Entry point:
- Search results: https://www.courts.state.md.us/cgi-bin/indexlist.pl?court={court}&year={year}&order=bydate&submit=Submit

Flow:
1. get_entry -> opinion search results page
2. parse_opinions_page -> parses table, yields ArchiveRequests for PDFs
3. handle_opinion_download -> yields final MarylandOpinionCluster

Design decisions:
- Uses the CGI search interface which provides structured table output
- Supports filtering by year via URL parameter
- Court can be identified from PDF URL path (coa=Supreme, cosa=Appellate)
- Date is in YYYY-MM-DD format directly in the table
- Uses DateRange filter on date_filed for searching
- Uses SetFilter on court_id to filter by specific court

PDF URL patterns:
- Supreme Court: /data/opinions/coa/{year}/{number}a{yy}.pdf
- Appellate Court: /data/opinions/cosa/{year}/{number}s{yy}.pdf
"""

from __future__ import annotations

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
    MarylandOpinion,
    MarylandOpinionCluster,
)

if TYPE_CHECKING:
    from collections.abc import Generator

    from juriscraper.scraper_driver.data_types import ScraperYield


# Base URL for the opinions search
BASE_URL = "https://www.courts.state.md.us"
SEARCH_URL = "https://www.courts.state.md.us/cgi-bin/indexlist.pl"


class MarylandScraper(BaseScraper[MarylandOpinionCluster]):
    """Scraper for Maryland appellate court published opinions.

    Scrapes published opinions from:
    - Supreme Court of Maryland (md)
    - Appellate Court of Maryland (mdctspecapp)

    Usage:
        # Scrape all opinions from both courts for current year
        scraper = MarylandScraper()

        # Filter opinions by date range
        params = MarylandScraper.params()
        params.MarylandOpinionCluster.date_filed.gte = date(2025, 1, 1)
        params.MarylandOpinionCluster.date_filed.lte = date(2025, 12, 31)
        scraper = MarylandScraper(params=params)

        # Scrape only Supreme Court opinions
        params = MarylandScraper.params()
        params.MarylandOpinionCluster.court_id.values = {"md"}
        scraper = MarylandScraper(params=params)

        # Scrape specific docket number
        params = MarylandScraper.params()
        params.MarylandOpinionCluster.docket_id.value = "3/25"
        scraper = MarylandScraper(params=params)
    """

    # === Metadata ===
    court_ids: ClassVar[set[str]] = {"md", "mdctspecapp"}
    court_url: ClassVar[str] = (
        "https://www.courts.state.md.us/opinions/opinions"
    )
    data_types: ClassVar[set[str]] = {"opinions"}
    status: ClassVar[ScraperStatus] = ScraperStatus.IN_DEVELOPMENT
    version: ClassVar[str] = "2026-01-23"
    requires_auth: ClassVar[bool] = False

    # Rate limiting - be respectful to court servers
    msec_per_request_rate_limit: ClassVar[int] = 1000

    # Years available in the system (1995-present)
    MIN_YEAR: ClassVar[int] = 1995

    # Mapping from model name to data type
    MODEL_TO_DATA_TYPE: ClassVar[dict[str, str]] = {
        "MarylandOpinionCluster": "opinions",
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
            model_proxy = self._params.MarylandOpinionCluster
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

    def _get_years_to_scrape(
        self, date_gte: date | None, date_lte: date | None
    ) -> list[int]:
        """Determine which years to scrape based on date filters.

        Args:
            date_gte: Start date filter
            date_lte: End date filter

        Returns:
            List of years to scrape
        """
        current_year = date.today().year

        if date_gte and date_lte:
            # Scrape years within the range
            start_year = max(date_gte.year, self.MIN_YEAR)
            end_year = min(date_lte.year, current_year)
            return list(range(start_year, end_year + 1))
        elif date_gte:
            # Scrape from start year to current
            start_year = max(date_gte.year, self.MIN_YEAR)
            return list(range(start_year, current_year + 1))
        elif date_lte:
            # Scrape from MIN_YEAR to end year
            end_year = min(date_lte.year, current_year)
            return list(range(self.MIN_YEAR, end_year + 1))
        else:
            # Default to current year only
            return [current_year]

    def _get_court_param(self, court_ids: set[str] | None) -> str:
        """Determine the court parameter for the search URL.

        Args:
            court_ids: Set of court IDs to filter by

        Returns:
            'coa' for Supreme Court only
            'cosa' for Appellate Court only
            'both' for both courts
        """
        if court_ids is None:
            return "both"

        if court_ids == {"md"}:
            return "coa"
        elif court_ids == {"mdctspecapp"}:
            return "cosa"
        else:
            return "both"

    def _parse_date(self, date_str: str) -> date | None:
        """Parse date from table cell.

        Args:
            date_str: Date like '2025-12-23' or '2025-11-24 corrected 2025-11-25'

        Returns:
            Parsed date or None
        """
        # Handle corrected dates - take the original date (first one)
        date_str = date_str.strip()
        if " corrected " in date_str:
            date_str = date_str.split(" corrected ")[0].strip()

        try:
            return datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            return None

    def _get_court_id_from_url(self, pdf_url: str) -> str | None:
        """Extract court ID from PDF URL path.

        Args:
            pdf_url: URL like '/data/opinions/coa/2025/3a25.pdf'

        Returns:
            Court ID ('md' or 'mdctspecapp') or None
        """
        if "/opinions/coa/" in pdf_url:
            return "md"
        elif "/opinions/cosa/" in pdf_url:
            return "mdctspecapp"
        return None

    # =========================================================================
    # Entry Point
    # =========================================================================

    @entry(MarylandOpinionCluster)
    def get_entry(self) -> Generator[NavigatingRequest, None, None]:
        """Yield initial requests to opinion search pages."""
        requested = self._get_requested_data_types()

        if "opinions" not in requested:
            return

        date_gte, date_lte, docket_id, court_ids = self._get_search_params()
        years = self._get_years_to_scrape(date_gte, date_lte)
        court_param = self._get_court_param(court_ids)

        for year in years:
            url = f"{SEARCH_URL}?court={court_param}&year={year}&order=bydate&submit=Submit"

            yield NavigatingRequest(
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url=url,
                ),
                continuation=self.parse_opinions_page,
                accumulated_data={
                    "year": year,
                    "court_filter": court_ids,
                },
            )

    # =========================================================================
    # Opinions Page Parsing
    # =========================================================================

    @step(xsd="xsds/parse_opinions_page.xsd")
    def parse_opinions_page(
        self,
        lxml_tree: CheckedHtmlElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[MarylandOpinionCluster], None, None]:
        """Parse the opinions search results page and yield requests."""
        date_gte, date_lte, target_docket, court_filter = (
            self._get_search_params()
        )

        # Get all tables on the page (results may be split across multiple tables)
        tables = lxml_tree.checked_xpath(
            "//table[.//columnheader or .//th[contains(text(), 'CASE')]]",
            "opinion tables",
            min_count=0,
        )

        for table in tables:
            # Get all data rows (skip header rows)
            rows = table.checked_xpath(
                ".//row[cell] | .//tr[td]",
                "opinion rows",
                min_count=0,
            )

            for row in rows:
                # Get cells - the table has 6 columns:
                # CASE PDF (docket/term), CITATION, FILED, JUDGE, PARTIES, Line
                cells = row.checked_xpath(
                    "cell | td",
                    "row cells",
                    min_count=0,
                )

                if len(cells) < 5:
                    # Skip rows that don't have enough cells
                    continue

                # Extract docket number from first cell (link text)
                docket_links = cells[0].checked_xpath(
                    ".//link | .//a",
                    "docket link",
                    min_count=0,
                )

                if not docket_links:
                    continue

                docket_link = docket_links[0]

                # Get docket number from link text
                docket_texts = docket_link.checked_xpath(
                    ".//text() | text()",
                    "docket text",
                    min_count=0,
                    type=str,
                )
                docket_number = "".join(docket_texts).strip()

                if not docket_number:
                    continue

                # Filter by specific docket if specified
                if target_docket and docket_number != target_docket:
                    continue

                # Get PDF URL from link href
                pdf_hrefs = docket_link.checked_xpath(
                    "@href | @/url",
                    "PDF URL",
                    min_count=0,
                    type=str,
                )

                # Try alternative XPath for accessibility tree format
                if not pdf_hrefs:
                    pdf_hrefs = docket_link.checked_xpath(
                        ".//*[starts-with(name(), '/url')]/text() | @href",
                        "PDF URL alt",
                        min_count=0,
                        type=str,
                    )

                if not pdf_hrefs:
                    continue

                pdf_url = pdf_hrefs[0]
                if pdf_url.startswith("/"):
                    pdf_url = urljoin(response.url, pdf_url)

                # Determine court from PDF URL
                court_id = self._get_court_id_from_url(pdf_url)
                if court_id is None:
                    continue

                # Filter by court if specified
                if court_filter and court_id not in court_filter:
                    continue

                # Extract citation from second cell
                citation_texts = cells[1].checked_xpath(
                    ".//text() | text()",
                    "citation text",
                    min_count=0,
                    type=str,
                )
                citation = "".join(citation_texts).strip() or None

                # Extract date from third cell
                date_texts = cells[2].checked_xpath(
                    ".//text() | text()",
                    "date text",
                    min_count=0,
                    type=str,
                )
                date_str = "".join(date_texts).strip()
                opinion_date = self._parse_date(date_str)

                if opinion_date is None:
                    continue

                # Filter by date range if specified
                if date_gte and opinion_date < date_gte:
                    continue
                if date_lte and opinion_date > date_lte:
                    continue

                # Extract judge from fourth cell
                judge_texts = cells[3].checked_xpath(
                    ".//text() | text()",
                    "judge text",
                    min_count=0,
                    type=str,
                )
                judge = "".join(judge_texts).strip() or None

                # Extract case name from fifth cell
                case_name_texts = cells[4].checked_xpath(
                    ".//text() | text()",
                    "case name text",
                    min_count=0,
                    type=str,
                )
                case_name = "".join(case_name_texts).strip()

                if not case_name:
                    continue

                # Build accumulated data for download handler
                cluster_data = {
                    "docket_id": docket_number,
                    "court_id": court_id,
                    "date_filed": opinion_date.isoformat(),
                    "case_name": case_name,
                    "source_url": response.url,
                    "judge": judge,
                    "citation": citation,
                    "year": opinion_date.year,
                    "pdf_url": pdf_url,
                }

                # Yield ArchiveRequest for the PDF
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
    # Download Handler
    # =========================================================================

    @step
    def handle_opinion_download(
        self,
        response: ArchiveResponse,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[MarylandOpinionCluster], None, None]:
        """Handle a downloaded opinion PDF."""
        date_filed = datetime.fromisoformat(
            accumulated_data["date_filed"]
        ).date()

        opinion = MarylandOpinion(
            download_url=accumulated_data["pdf_url"],
            local_path=response.file_url,
        )

        cluster = MarylandOpinionCluster(
            docket_id=accumulated_data["docket_id"],
            court_id=accumulated_data["court_id"],
            date_filed=date_filed,
            case_name=accumulated_data["case_name"],
            opinions=[opinion],
            source_url=accumulated_data["source_url"],
            judge=accumulated_data["judge"],
            citation=accumulated_data["citation"],
            year=accumulated_data["year"],
            precedential_status="Published",
        )

        yield ParsedData(cluster)
