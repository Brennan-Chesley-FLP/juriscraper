"""Michigan Appellate Courts Scraper.

This module scrapes opinions from the Michigan Supreme Court and
Court of Appeals using their ZIP file archive page.

Entry point:
- ZIP Files Page: https://www.courts.michigan.gov/courts/opinion-order-zip-files/

Flow:
1. get_entry -> ZIP files page URL (if "opinions" requested)
2. parse_zip_files_page -> parses page for ZIP links, yields ArchiveRequests
3. handle_zip_download -> extracts PDFs, yields ArchiveRequests for each PDF
4. handle_pdf_download -> yields final MichiganOpinionCluster

Design decisions:
- Uses ZIP file archives as primary data source for reliability
- ZIP files are available for 28 days (COA) or 90 days (MSC)
- Each ZIP contains opinion PDFs named with 6-digit docket numbers
- PDF filenames contain the docket number (e.g., '167745_74_01.pdf')
- COA ZIP files come in three flavors: all, published, unpublished
- MSC ZIP files contain all opinions for that release date
- Uses DateRange filter on date_filed for searching
- Uses SetFilter on court_id to select which courts to scrape
"""

from __future__ import annotations

import io
import re
import zipfile
from datetime import date
from typing import TYPE_CHECKING, ClassVar

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
    MichiganOpinion,
    MichiganOpinionCluster,
)

if TYPE_CHECKING:
    from collections.abc import Generator

    from juriscraper.scraper_driver.data_types import ScraperYield


# ZIP files page URL
ZIP_FILES_URL = "https://www.courts.michigan.gov/courts/opinion-order-zip-files/"


class MichiganScraper(BaseScraper[MichiganOpinionCluster]):
    """Scraper for Michigan appellate court opinions via ZIP file archives.

    Scrapes opinions from the Michigan Supreme Court (mich) and
    Court of Appeals (michctapp) from their daily ZIP file archives.

    Usage:
        # Scrape all opinions from both courts
        scraper = MichiganScraper()

        # Scrape only Supreme Court opinions
        params = MichiganScraper.params()
        params.MichiganOpinionCluster.court_id.values = {"mich"}
        scraper = MichiganScraper(params=params)

        # Scrape only Court of Appeals opinions
        params = MichiganScraper.params()
        params.MichiganOpinionCluster.court_id.values = {"michctapp"}
        scraper = MichiganScraper(params=params)

        # Filter opinions by date range
        params = MichiganScraper.params()
        params.MichiganOpinionCluster.date_filed.gte = date(2026, 1, 1)
        params.MichiganOpinionCluster.date_filed.lte = date(2026, 1, 15)
        scraper = MichiganScraper(params=params)
    """

    # === Metadata ===
    court_ids: ClassVar[set[str]] = {"mich", "michctapp"}
    court_url: ClassVar[str] = "https://www.courts.michigan.gov/"
    data_types: ClassVar[set[str]] = {"opinions"}
    status: ClassVar[ScraperStatus] = ScraperStatus.IN_DEVELOPMENT
    version: ClassVar[str] = "2026-01-23"
    requires_auth: ClassVar[bool] = False

    # Rate limiting - be respectful to court servers
    msec_per_request_rate_limit: ClassVar[int] = 2000

    # === Regex patterns ===
    # Date pattern from link text: "1/21/2026" or "12/30/2025"
    DATE_PATTERN = re.compile(r"(\d{1,2})/(\d{1,2})/(\d{4})")

    # PDF filename pattern: 6-digit docket number followed by underscore
    # Examples: 167745_74_01.pdf, 366123_01.pdf
    DOCKET_PATTERN = re.compile(r"^(\d{6})(?:-\d+)?_")

    # ZIP URL patterns to identify court type
    COA_ZIP_PATTERN = re.compile(r"/coa/zip-files/")
    MSC_OPINION_ZIP_PATTERN = re.compile(r"/sct/zip-files/.*_msc_opinions\.zip")
    MSC_ORDER_ZIP_PATTERN = re.compile(r"/orders/zip-files/.*_msc_orders\.zip")

    # Link text patterns to identify content type
    PUBLISHED_PATTERN = re.compile(r"Published", re.IGNORECASE)
    UNPUBLISHED_PATTERN = re.compile(r"Unpublished", re.IGNORECASE)
    ALL_PATTERN = re.compile(r"All Court", re.IGNORECASE)

    # Mapping from model name to data type
    MODEL_TO_DATA_TYPE: ClassVar[dict[str, str]] = {
        "MichiganOpinionCluster": "opinions",
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
            Tuple of (date_gte, date_lte, docket_number, court_ids)
        """
        if self._params is None:
            return None, None, None, None

        try:
            model_proxy = self._params.MichiganOpinionCluster
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

        docket_field = searchable.get("docket_number")
        if docket_field and docket_field.is_set():
            docket_number = docket_field.value

        court_field = searchable.get("court_id")
        if court_field and court_field.is_set():
            court_ids = court_field.values

        return date_gte, date_lte, docket_number, court_ids

    def _parse_date_from_link_text(self, text: str) -> date | None:
        """Parse date from link text like '1/21/2026 - All Court Of Appeals'.

        Args:
            text: Link text containing date

        Returns:
            Parsed date or None
        """
        match = self.DATE_PATTERN.search(text)
        if match:
            month, day, year = match.groups()
            try:
                return date(int(year), int(month), int(day))
            except ValueError:
                return None
        return None

    def _get_court_id_from_url(self, url: str) -> str | None:
        """Determine court ID from ZIP URL pattern.

        Args:
            url: ZIP file URL

        Returns:
            Court ID ('mich' or 'michctapp') or None
        """
        if self.COA_ZIP_PATTERN.search(url):
            return "michctapp"
        if self.MSC_OPINION_ZIP_PATTERN.search(url):
            return "mich"
        return None

    def _get_precedential_status(self, link_text: str, court_id: str) -> str:
        """Determine precedential status from link text.

        Args:
            link_text: The link text (e.g., "Published Court Of Appeals Opinions")
            court_id: The court ID

        Returns:
            'Published', 'Unpublished', or 'Unknown'
        """
        if court_id == "mich":
            # MSC opinions are always published
            return "Published"

        if self.PUBLISHED_PATTERN.search(link_text):
            return "Published"
        if self.UNPUBLISHED_PATTERN.search(link_text):
            return "Unpublished"
        # "All" contains both - we'll mark as Unknown
        return "Unknown"

    def _extract_docket_from_filename(self, filename: str) -> str | None:
        """Extract docket number from PDF filename.

        Args:
            filename: PDF filename like '167745_74_01.pdf'

        Returns:
            Docket number string or None
        """
        match = self.DOCKET_PATTERN.match(filename)
        if match:
            return match.group(1)
        return None

    # =========================================================================
    # Entry Point
    # =========================================================================

    def get_entry(self) -> Generator[NavigatingRequest, None, None]:
        """Yield initial request to ZIP files page."""
        requested = self._get_requested_data_types()

        if "opinions" in requested:
            yield NavigatingRequest(
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url=ZIP_FILES_URL,
                ),
                continuation=self.parse_zip_files_page,
            )

    # =========================================================================
    # ZIP Files Page Parsing
    # =========================================================================

    @step(xsd="xsds/parse_zip_files_page.xsd")
    def parse_zip_files_page(
        self,
        lxml_tree: CheckedHtmlElement,
        response: Response,
    ) -> Generator[ScraperYield[MichiganOpinionCluster], None, None]:
        """Parse ZIP files page and yield requests for each ZIP archive."""
        date_gte, date_lte, target_docket, court_ids = self._get_search_params()

        # Find all links that point to ZIP files
        # The links are in generic containers with "Title" labels
        zip_links = lxml_tree.checked_xpath(
            "//a[contains(@href, '.zip')]",
            "ZIP file links",
            min_count=0,
        )

        # Track which ZIPs we've already requested to avoid duplicates
        # We prefer "Published" or "Unpublished" specific ZIPs over "All"
        # to get accurate precedential status
        requested_zips: set[tuple[str, date]] = set()

        for link in zip_links:
            href = link.get("href", "")
            if not href:
                continue

            # Get the link text
            link_text = link.text_content().strip() if link.text_content() else ""

            # Skip MSC orders - we only want opinions
            if self.MSC_ORDER_ZIP_PATTERN.search(href):
                continue

            # Determine court from URL
            court_id = self._get_court_id_from_url(href)
            if court_id is None:
                continue

            # Filter by court if specified
            if court_ids and court_id not in court_ids:
                continue

            # Parse date from link text
            release_date = self._parse_date_from_link_text(link_text)
            if release_date is None:
                continue

            # Filter by date range if specified
            if date_gte and release_date < date_gte:
                continue
            if date_lte and release_date > date_lte:
                continue

            # Determine precedential status
            precedential_status = self._get_precedential_status(link_text, court_id)

            # For COA, prefer specific Published/Unpublished ZIPs over "All"
            # to get accurate precedential status
            zip_key = (court_id, release_date)
            if court_id == "michctapp":
                # Skip "All" ZIPs if we already have specific ones for this date
                if self.ALL_PATTERN.search(link_text):
                    if zip_key in requested_zips:
                        continue
                else:
                    # Mark that we have specific ZIPs for this date
                    requested_zips.add(zip_key)
            else:
                # For MSC, just avoid duplicates
                if zip_key in requested_zips:
                    continue
                requested_zips.add(zip_key)

            # Build full URL if relative
            if href.startswith("/"):
                full_url = f"https://www.courts.michigan.gov{href}"
            else:
                full_url = href

            # Yield ArchiveRequest for the ZIP file
            yield ArchiveRequest(
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url=full_url,
                ),
                continuation=self.handle_zip_download,
                expected_type="zip",
                accumulated_data={
                    "court_id": court_id,
                    "release_date": release_date.isoformat(),
                    "precedential_status": precedential_status,
                    "source_url": full_url,
                    "target_docket": target_docket,
                },
            )

    # =========================================================================
    # ZIP Download Handler
    # =========================================================================

    @step
    def handle_zip_download(
        self,
        response: ArchiveResponse,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[MichiganOpinionCluster], None, None]:
        """Handle downloaded ZIP file, extract PDF metadata and yield clusters.

        Note: The ZIP file itself contains the PDFs, so we extract metadata
        from the filenames and use the ZIP file's local path as reference.
        The driver already has the ZIP file downloaded, so we can read from it
        directly to get the PDF data.
        """
        court_id = accumulated_data["court_id"]
        release_date = date.fromisoformat(accumulated_data["release_date"])
        precedential_status = accumulated_data["precedential_status"]
        source_url = accumulated_data["source_url"]
        target_docket = accumulated_data.get("target_docket")
        zip_local_path = response.file_url

        # Read the ZIP file from the local path
        try:
            with open(zip_local_path, "rb") as f:
                zip_data = f.read()
        except (OSError, IOError):
            # File read failed - skip this ZIP
            return

        try:
            with zipfile.ZipFile(io.BytesIO(zip_data)) as zf:
                for filename in zf.namelist():
                    # Skip non-PDF files
                    if not filename.lower().endswith(".pdf"):
                        continue

                    # Extract docket number from filename
                    docket_number = self._extract_docket_from_filename(filename)
                    if docket_number is None:
                        continue

                    # Filter by docket number if specified
                    if target_docket and docket_number != target_docket:
                        continue

                    # Create a case name from docket number
                    # We don't have case names in the ZIP files
                    case_name = f"Case No. {docket_number}"

                    # Create the opinion - the local_path references the ZIP file
                    # The consumer will need to extract from the ZIP using pdf_filename
                    opinion = MichiganOpinion(
                        download_url=source_url,
                        local_path=zip_local_path,
                    )

                    # Create and yield the cluster
                    cluster = MichiganOpinionCluster(
                        docket_number=docket_number,
                        court_id=court_id,
                        date_filed=release_date,
                        case_name=case_name,
                        opinions=[opinion],
                        source_url=source_url,
                        precedential_status=precedential_status,
                        pdf_filename=filename,
                    )

                    yield ParsedData(cluster)

        except zipfile.BadZipFile:
            # Invalid ZIP file - skip
            return
