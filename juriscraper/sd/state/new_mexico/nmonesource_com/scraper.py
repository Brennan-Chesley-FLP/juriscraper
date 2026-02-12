"""New Mexico Appellate Courts Scraper (NMOneSource).

This module scrapes opinions from the New Mexico Supreme Court and
Court of Appeals using NMOneSource (https://nmonesource.com/).

Entry points:
- Supreme Court: https://nmonesource.com/nmos/nmsc/en/nav_date.do
- Court of Appeals: https://nmonesource.com/nmos/nmca/en/nav_date.do

Flow:
1. get_entry -> Year listing page(s) for each court (if "opinions" requested)
2. parse_year_listing -> parses opinion list, yields requests for detail pages
3. parse_opinion_detail -> parses metadata, yields ArchiveRequest for PDF
4. handle_opinion_download -> yields final NMOpinionCluster

Design decisions:
- Uses year-based navigation as primary data source
- Supports both Slip Opinions and Unreported Opinions
- Uses DateRange filter on date_filed for searching
- Uses SetFilter on court_id to select which courts to scrape
- Rate limited to be respectful to court servers

Note: NMOneSource uses iframes for content, but the actual URLs
contain the data we need and can be scraped directly.
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
    ID_TO_NMONESOURCE_COURT,
    NMOpinion,
    NMOpinionCluster,
)

if TYPE_CHECKING:
    from collections.abc import Generator

    from kent.data_types import ScraperYield


# Base URL for NMOneSource
BASE_URL = "https://nmonesource.com"

# URL templates
YEAR_LISTING_URL = "{base}/nmos/{court}/en/{year}/nav_date.do"
CURRENT_YEAR_URL = "{base}/nmos/{court}/en/nav_date.do"


class NMOneSourceScraper(BaseScraper[NMOpinionCluster]):
    """Scraper for New Mexico appellate court opinions via NMOneSource.

    Scrapes opinions from the New Mexico Supreme Court (nm) and
    Court of Appeals (nmctapp).

    Usage:
        # Scrape opinions from both courts for current year
        scraper = NMOneSourceScraper()

        # Scrape only Supreme Court opinions
        params = NMOneSourceScraper.params()
        params.NMOpinionCluster.court_id.values = {"nm"}
        scraper = NMOneSourceScraper(params=params)

        # Scrape only Court of Appeals opinions
        params = NMOneSourceScraper.params()
        params.NMOpinionCluster.court_id.values = {"nmctapp"}
        scraper = NMOneSourceScraper(params=params)

        # Filter opinions by date range
        params = NMOneSourceScraper.params()
        params.NMOpinionCluster.date_filed.gte = date(2026, 1, 1)
        params.NMOpinionCluster.date_filed.lte = date(2026, 1, 31)
        scraper = NMOneSourceScraper(params=params)
    """

    # === Metadata ===
    court_ids: ClassVar[set[str]] = {"nm", "nmctapp"}
    court_url: ClassVar[str] = "https://nmonesource.com/"
    data_types: ClassVar[set[str]] = {"opinions"}
    status: ClassVar[ScraperStatus] = ScraperStatus.IN_DEVELOPMENT
    version: ClassVar[str] = "2026-01-23"
    requires_auth: ClassVar[bool] = False

    # Rate limiting - be respectful to court servers
    msec_per_request_rate_limit: ClassVar[int] = 1500

    # === Regex patterns ===
    # Date pattern from listing: MM/DD/YYYY
    DATE_PATTERN = re.compile(r"(\d{2}/\d{2}/\d{4})")

    # Item ID from URL pattern: /item/537787/index.do
    ITEM_ID_PATTERN = re.compile(r"/item/(\d+)/")

    # PDF URL pattern
    PDF_URL_PATTERN = re.compile(r"/(\d+)/\d+/document\.do$")

    # Mapping from model name to data type
    MODEL_TO_DATA_TYPE: ClassVar[dict[str, str]] = {
        "NMOpinionCluster": "opinions",
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
            model_proxy = self._params.NMOpinionCluster
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

        Returns:
            List of years to scrape (most recent first)
        """
        current_year = datetime.now().year

        if date_gte and date_lte:
            # Scrape all years in the range
            return list(range(date_lte.year, date_gte.year - 1, -1))
        elif date_gte:
            # From date_gte to current year
            return list(range(current_year, date_gte.year - 1, -1))
        elif date_lte:
            # Just scrape years up to date_lte (limit to reasonable range)
            return list(range(date_lte.year, date_lte.year - 5, -1))
        else:
            # Default: just current year
            return [current_year]

    def _parse_date(self, date_str: str) -> date | None:
        """Parse MM/DD/YYYY date format.

        Args:
            date_str: Date like '01/22/2026'

        Returns:
            Parsed date or None
        """
        try:
            return datetime.strptime(date_str.strip(), "%m/%d/%Y").date()
        except ValueError:
            return None

    # =========================================================================
    # Entry Point
    # =========================================================================

    @entry(NMOpinionCluster)
    def get_entry(self) -> Generator[NavigatingRequest, None, None]:
        """Yield initial requests to year listing pages for each court."""
        requested = self._get_requested_data_types()

        if "opinions" not in requested:
            return

        date_gte, date_lte, _, court_ids = self._get_search_params()
        years = self._get_years_to_scrape(date_gte, date_lte)

        # Determine which courts to scrape
        courts_to_scrape = court_ids if court_ids else self.court_ids

        for court_id in courts_to_scrape:
            nmonesource_court = ID_TO_NMONESOURCE_COURT.get(court_id)
            if not nmonesource_court:
                continue

            for year in years:
                url = YEAR_LISTING_URL.format(
                    base=BASE_URL,
                    court=nmonesource_court,
                    year=year,
                )

                yield NavigatingRequest(
                    request=HTTPRequestParams(
                        method=HttpMethod.GET,
                        url=url,
                    ),
                    continuation=self.parse_year_listing,
                    accumulated_data={
                        "court_id": court_id,
                        "nmonesource_court": nmonesource_court,
                        "year": year,
                    },
                )

    # =========================================================================
    # Year Listing Page Parsing
    # =========================================================================

    @step(xsd="xsds/parse_year_listing.xsd")
    def parse_year_listing(
        self,
        lxml_tree: CheckedHtmlElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[NMOpinionCluster], None, None]:
        """Parse year listing page and yield requests for each opinion."""
        date_gte, date_lte, target_docket, _ = self._get_search_params()
        court_id = accumulated_data["court_id"]
        nmonesource_court = accumulated_data["nmonesource_court"]

        # Find all opinion list items
        # The structure is: <ul><li>...<h3><a href="...">Case Name</a> - MM/DD/YYYY</h3>
        list_items = lxml_tree.checked_xpath(
            "//li[.//h3[contains(@class, '') or not(@class)]/a[contains(@href, '/item/')]]",
            "opinion list items",
            min_count=0,
        )

        for item in list_items:
            # Extract the case link
            case_links = item.checked_xpath(
                ".//h3/a[contains(@href, '/item/')]",
                "case link",
                min_count=1,
                max_count=1,
            )
            case_link = case_links[0]

            # Get case name from link text
            case_name_parts = case_link.checked_xpath(
                "text()",
                "case name text",
                min_count=1,
                max_count=1,
                type=str,
            )
            case_name = case_name_parts[0].strip()

            # Get detail page URL
            href_parts = case_link.checked_xpath(
                "@href",
                "case href",
                min_count=1,
                max_count=1,
                type=str,
            )
            detail_url = urljoin(response.url, href_parts[0])

            # Extract item ID from URL
            item_id_match = self.ITEM_ID_PATTERN.search(detail_url)
            item_id = item_id_match.group(1) if item_id_match else None

            # Extract date from the heading text (after the link)
            # Format: "Case Name - 01/22/2026"
            heading_texts = item.checked_xpath(
                ".//h3//text()",
                "heading texts",
                min_count=1,
                type=str,
            )
            # Combine all text and find the date
            full_heading = "".join(heading_texts)
            date_match = self.DATE_PATTERN.search(full_heading)
            if not date_match:
                continue

            opinion_date = self._parse_date(date_match.group(1))
            if not opinion_date:
                continue

            # Filter by date range if specified
            if date_gte and opinion_date < date_gte:
                continue
            if date_lte and opinion_date > date_lte:
                continue

            # Extract opinion type from the subtitle
            # Format: "Court of Appeals of New Mexico - Slip Opinions"
            # or "Supreme Court of New Mexico - Unreported Opinions"
            subtitle_texts = item.checked_xpath(
                ".//div[contains(@class, '') or not(@class)]/text()",
                "subtitle text",
                min_count=0,
                type=str,
            )
            opinion_type = "unknown"
            collection = None
            for text in subtitle_texts:
                text_lower = text.lower().strip()
                if "slip opinion" in text_lower:
                    opinion_type = "slip"
                elif "unreported" in text_lower:
                    opinion_type = "unreported"
                if (
                    "supreme court" in text_lower
                    or "court of appeals" in text_lower
                ):
                    collection = text.strip()

            # Extract PDF download URL if available on listing page
            pdf_links = item.checked_xpath(
                ".//a[contains(@href, 'document.do')]/@href",
                "PDF link",
                min_count=0,
                type=str,
            )
            pdf_url = (
                urljoin(response.url, pdf_links[0]) if pdf_links else None
            )

            # Build accumulated data for next steps
            cluster_data = {
                "court_id": court_id,
                "nmonesource_court": nmonesource_court,
                "case_name": case_name,
                "date_filed": opinion_date.isoformat(),
                "item_id": item_id,
                "detail_url": detail_url,
                "pdf_url": pdf_url,
                "opinion_type": opinion_type,
                "collection": collection,
                "source_url": response.url,
            }

            # If we have a PDF URL, skip detail page and go directly to download
            if pdf_url:
                yield from self._yield_archive_request(cluster_data)
            else:
                # Need to visit detail page to get PDF URL and more metadata
                yield NavigatingRequest(
                    request=HTTPRequestParams(
                        method=HttpMethod.GET,
                        url=detail_url,
                    ),
                    continuation=self.parse_opinion_detail,
                    accumulated_data=cluster_data,
                )

    # =========================================================================
    # Opinion Detail Page Parsing
    # =========================================================================

    @step(xsd="xsds/parse_opinion_detail.xsd")
    def parse_opinion_detail(
        self,
        lxml_tree: CheckedHtmlElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[NMOpinionCluster], None, None]:
        """Parse opinion detail page to extract metadata and PDF URL."""
        # Try to find PDF link
        pdf_links = lxml_tree.checked_xpath(
            "//a[contains(@href, 'document.do')]/@href",
            "PDF download link",
            min_count=0,
            type=str,
        )

        if pdf_links:
            accumulated_data["pdf_url"] = urljoin(response.url, pdf_links[0])

        # Extract docket number from the detail table
        # Format: "Docket Numbers: S-1-SC-40434"
        docket_cells = lxml_tree.checked_xpath(
            "//td[contains(text(), 'Docket Number')]/following-sibling::td/text()",
            "docket number cell",
            min_count=0,
            type=str,
        )
        if docket_cells:
            accumulated_data["docket_id"] = docket_cells[0].strip()

        # Extract judges/decision-makers
        # Format: "Decision-maker(s): JUSTICE NAME; JUSTICE NAME"
        judges_cells = lxml_tree.checked_xpath(
            "//td[contains(text(), 'Decision-maker')]/following-sibling::td/text()",
            "judges cell",
            min_count=0,
            type=str,
        )
        if judges_cells:
            accumulated_data["judges"] = judges_cells[0].strip()

        # Extract opinion type if not already set
        if accumulated_data.get("opinion_type") == "unknown":
            type_cells = lxml_tree.checked_xpath(
                "//td[contains(text(), 'Opinion Type')]/following-sibling::td/text()",
                "opinion type cell",
                min_count=0,
                type=str,
            )
            if type_cells:
                type_text = type_cells[0].lower().strip()
                if "slip" in type_text:
                    accumulated_data["opinion_type"] = "slip"
                elif "unreported" in type_text:
                    accumulated_data["opinion_type"] = "unreported"

        # Extract collection if not already set
        if not accumulated_data.get("collection"):
            collection_cells = lxml_tree.checked_xpath(
                "//td[contains(text(), 'Collection')]/following-sibling::td/text()",
                "collection cell",
                min_count=0,
                type=str,
            )
            if collection_cells:
                accumulated_data["collection"] = collection_cells[0].strip()

        # Update detail URL to actual response URL
        accumulated_data["detail_url"] = response.url

        # Now download the PDF
        if accumulated_data.get("pdf_url"):
            yield from self._yield_archive_request(accumulated_data)
        else:
            # No PDF available - still yield the cluster without opinions
            yield from self._yield_cluster_without_pdf(accumulated_data)

    # =========================================================================
    # Helper Methods
    # =========================================================================

    def _yield_archive_request(
        self, accumulated_data: dict
    ) -> Generator[ScraperYield[NMOpinionCluster], None, None]:
        """Yield an ArchiveRequest for the PDF."""
        yield ArchiveRequest(
            request=HTTPRequestParams(
                method=HttpMethod.GET,
                url=accumulated_data["pdf_url"],
            ),
            continuation=self.handle_opinion_download,
            expected_type="pdf",
            accumulated_data=accumulated_data,
        )

    def _yield_cluster_without_pdf(
        self, accumulated_data: dict
    ) -> Generator[ScraperYield[NMOpinionCluster], None, None]:
        """Yield a cluster when no PDF is available."""
        date_filed = datetime.fromisoformat(
            accumulated_data["date_filed"]
        ).date()

        # Determine precedential status from opinion type
        opinion_type = accumulated_data.get("opinion_type", "unknown")
        if opinion_type == "slip":
            precedential_status = "Published"
        elif opinion_type == "unreported":
            precedential_status = "Unpublished"
        else:
            precedential_status = "Unknown"

        cluster = NMOpinionCluster(
            docket_id=accumulated_data.get("docket_id", "Unknown"),
            court_id=accumulated_data["court_id"],
            date_filed=date_filed,
            case_name=accumulated_data["case_name"],
            opinions=[],
            source_url=accumulated_data.get("source_url"),
            item_id=accumulated_data.get("item_id"),
            judges=accumulated_data.get("judges"),
            opinion_type=accumulated_data.get("opinion_type"),
            collection=accumulated_data.get("collection"),
            precedential_status=precedential_status,
        )

        yield ParsedData(cluster)

    # =========================================================================
    # Download Handler
    # =========================================================================

    @step
    def handle_opinion_download(
        self,
        response: ArchiveResponse,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[NMOpinionCluster], None, None]:
        """Handle a downloaded opinion PDF."""
        date_filed = datetime.fromisoformat(
            accumulated_data["date_filed"]
        ).date()

        # Determine precedential status from opinion type
        opinion_type = accumulated_data.get("opinion_type", "unknown")
        if opinion_type == "slip":
            precedential_status = "Published"
        elif opinion_type == "unreported":
            precedential_status = "Unpublished"
        else:
            precedential_status = "Unknown"

        # Build the opinion object
        opinion = NMOpinion(
            download_url=accumulated_data["pdf_url"],
            type=opinion_type,
            local_path=response.file_url,
        )

        # Build and yield the cluster
        cluster = NMOpinionCluster(
            docket_id=accumulated_data.get("docket_id", "Unknown"),
            court_id=accumulated_data["court_id"],
            date_filed=date_filed,
            case_name=accumulated_data["case_name"],
            opinions=[opinion],
            source_url=accumulated_data.get("source_url"),
            item_id=accumulated_data.get("item_id"),
            judges=accumulated_data.get("judges"),
            opinion_type=accumulated_data.get("opinion_type"),
            collection=accumulated_data.get("collection"),
            precedential_status=precedential_status,
        )

        yield ParsedData(cluster)
