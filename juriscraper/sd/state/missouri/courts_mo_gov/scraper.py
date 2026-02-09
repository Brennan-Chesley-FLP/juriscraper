"""Missouri Appellate Courts Scraper.

This module scrapes published opinions from Missouri appellate courts:
- Supreme Court of Missouri (mo)
- Court of Appeals, Eastern District (moctapped)
- Court of Appeals, Southern District (moctappsd)
- Court of Appeals, Western District (moctappwd)

Entry points:
- All courts: https://www.courts.mo.gov/page.jsp?id=12086&dist=Opinions&date=all&year={YYYY}
- Specific date: https://www.courts.mo.gov/page.jsp?id=12086&dist=Opinions&date={MM/DD/YYYY}&year={YYYY}

Flow:
1. get_entry -> opinions page for current year (if "opinions" requested)
2. parse_opinions_page -> iterate through date buttons, extract opinion metadata
3. For each opinion: yield ArchiveRequest for PDF
4. handle_opinion_download -> yield final MissouriOpinionCluster

Design decisions:
- Uses date-based browsing via URL parameters
- Can filter by specific date range using DateRange on date_filed
- Can filter by specific court using SetFilter on court_id
- Each opinion entry may have both main opinion PDF and Overview/Summary PDF
- Court is determined from docket number prefix (SC, ED, SD, WD)
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import TYPE_CHECKING, Any, ClassVar
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
    MissouriOpinion,
    MissouriOpinionCluster,
    get_court_id_from_docket,
)

if TYPE_CHECKING:
    from collections.abc import Generator

    from juriscraper.scraper_driver.data_types import ScraperYield


# Base URLs
BASE_URL = "https://www.courts.mo.gov"
OPINIONS_URL = "https://www.courts.mo.gov/page.jsp?id=12086&dist=Opinions"


class MissouriScraper(BaseScraper[MissouriOpinionCluster]):
    """Scraper for Missouri appellate court published opinions.

    Scrapes published opinions from all Missouri appellate courts:
    - Supreme Court of Missouri
    - Court of Appeals (Eastern, Southern, Western Districts)

    Usage:
        # Scrape all opinions for current year
        scraper = MissouriScraper()

        # Filter opinions by date range
        params = MissouriScraper.params()
        params.MissouriOpinionCluster.date_filed.gte = date(2026, 1, 1)
        params.MissouriOpinionCluster.date_filed.lte = date(2026, 1, 31)
        scraper = MissouriScraper(params=params)

        # Scrape specific court only
        params = MissouriScraper.params()
        params.MissouriOpinionCluster.court_id.values = {"mo"}  # Supreme Court only
        scraper = MissouriScraper(params=params)

        # Scrape specific case by docket number
        params = MissouriScraper.params()
        params.MissouriOpinionCluster.docket_id.value = "SC101157"
        scraper = MissouriScraper(params=params)
    """

    # === Metadata ===
    court_ids: ClassVar[set[str]] = {
        "mo",
        "moctapped",
        "moctappsd",
        "moctappwd",
    }
    court_url: ClassVar[str] = "https://www.courts.mo.gov/"
    data_types: ClassVar[set[str]] = {"opinions"}
    status: ClassVar[ScraperStatus] = ScraperStatus.IN_DEVELOPMENT
    version: ClassVar[str] = "2026-01-23"
    requires_auth: ClassVar[bool] = False

    # Rate limiting - be respectful to court servers
    msec_per_request_rate_limit: ClassVar[int] = 1000

    # === Regex patterns ===
    # Docket number pattern: PREFIX followed by digits
    # PREFIX is SC (Supreme), ED (Eastern), SD (Southern), WD (Western)
    DOCKET_PATTERN = re.compile(r"^(SC|ED|SD|WD)(\d+)$")

    # Date parsing pattern for MM/DD/YYYY
    DATE_PATTERN = re.compile(r"(\d{2})/(\d{2})/(\d{4})")

    # Order document pattern (to filter out non-opinion orders)
    ORDER_PATTERN = re.compile(r"^(SC|ED|SD|WD)?Order", re.IGNORECASE)

    # Mapping from model name to data type
    MODEL_TO_DATA_TYPE: ClassVar[dict[str, str]] = {
        "MissouriOpinionCluster": "opinions",
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
            model_proxy = self._params.MissouriOpinionCluster
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

    def _parse_date_str(self, date_str: str) -> date | None:
        """Parse date from MM/DD/YYYY format.

        Args:
            date_str: Date string like '01/13/2026'

        Returns:
            Parsed date or None
        """
        match = self.DATE_PATTERN.match(date_str.strip())
        if match:
            month = int(match.group(1))
            day = int(match.group(2))
            year = int(match.group(3))
            return date(year, month, day)
        return None

    def _get_year_range(self) -> tuple[int, int]:
        """Determine year range to scrape based on date filters.

        Returns:
            Tuple of (start_year, end_year) inclusive
        """
        date_gte, date_lte, _, _ = self._get_search_params()

        current_year = date.today().year

        if date_gte and date_lte:
            return date_gte.year, date_lte.year
        elif date_gte:
            return date_gte.year, current_year
        elif date_lte:
            # Go back to 1997 (earliest available)
            return 1997, date_lte.year
        else:
            # Default to current year only
            return current_year, current_year

    # =========================================================================
    # Entry Point
    # =========================================================================

    @entry(MissouriOpinionCluster)
    def get_entry(self) -> Generator[NavigatingRequest, None, None]:
        """Yield initial request(s) to opinions pages."""
        requested = self._get_requested_data_types()

        if "opinions" in requested:
            start_year, end_year = self._get_year_range()

            # Request each year in the range
            for year in range(end_year, start_year - 1, -1):
                url = f"{OPINIONS_URL}&date=all&year={year}"
                yield NavigatingRequest(
                    request=HTTPRequestParams(
                        method=HttpMethod.GET,
                        url=url,
                    ),
                    continuation=self.parse_opinions_page,
                    accumulated_data={"year": year},
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
    ) -> Generator[ScraperYield[MissouriOpinionCluster], None, None]:
        """Parse the opinions page and yield requests for each opinion.

        The page structure::

            - Date buttons (//button) contain dates in MM/DD/YYYY format
            - When a date is selected, opinions appear in a div after the button
            - Each opinion entry is in a div with:
              - Docket number prefix (e.g., "SC101157:")
              - Optional "Overview/Summary" link
              - Case name link to PDF
              - Author text
              - Vote text
        """
        date_gte, date_lte, target_docket, target_courts = (
            self._get_search_params()
        )

        # Find all date containers - these are divs containing a disabled button
        # (indicating that date is expanded) followed by opinion entries
        # But on the "all" page, all dates have opinions listed
        date_containers = lxml_tree.checked_xpath(
            "//div[@class='margin-bottom-15']",
            "date containers",
            min_count=0,
        )

        for date_container in date_containers:
            # Get the date from the input element
            date_inputs = date_container.checked_xpath(
                ".//input[@type='hidden']/@value | .//input/@value",
                "date input value",
                min_count=0,
                type=str,
            )

            if not date_inputs:
                continue

            date_str = date_inputs[0]
            opinion_date = self._parse_date_str(date_str)

            if opinion_date is None:
                continue

            # Filter by date range if specified
            if date_gte and opinion_date < date_gte:
                continue
            if date_lte and opinion_date > date_lte:
                continue

            # Find opinion entries within this date container
            # Each opinion is in a div with class 'list-group-item-text'
            opinion_divs = date_container.checked_xpath(
                ".//div[@class='list-group-item-text']",
                "opinion entries",
                min_count=0,
            )

            for opinion_div in opinion_divs:
                yield from self._parse_opinion_entry(
                    opinion_div,
                    response,
                    opinion_date,
                    target_docket,
                    target_courts,
                )

    def _parse_opinion_entry(
        self,
        opinion_div: CheckedHtmlElement,
        response: Response,
        opinion_date: date,
        target_docket: str | None,
        target_courts: set[str] | None,
    ) -> Generator[ScraperYield[MissouriOpinionCluster], None, None]:
        """Parse a single opinion entry and yield archive requests.

        Args:
            opinion_div: The div element containing the opinion entry
            response: The HTTP response
            opinion_date: The date of this opinion
            target_docket: Specific docket to filter for (or None)
            target_courts: Set of court_ids to filter for (or None)
        """
        # Get all text content to extract docket, author, vote
        all_texts = opinion_div.checked_xpath(
            ".//text()",
            "opinion text content",
            min_count=1,
            type=str,
        )

        # Clean and join text
        text_parts = [t.strip() for t in all_texts if t.strip()]

        if not text_parts:
            return

        # First text part should contain docket number with colon
        first_text = text_parts[0]

        # Check if this is an Order (not a full opinion)
        if self.ORDER_PATTERN.match(first_text):
            return

        # Extract docket number (before the colon)
        if ":" not in first_text:
            return

        docket_part = first_text.split(":")[0].strip()

        # Handle consolidated cases (e.g., "WD87719 consolidated with WD87745")
        # Use the first docket number
        if " consolidated with " in docket_part.lower():
            docket_part = docket_part.split(" consolidated ")[0].strip()

        docket_match = self.DOCKET_PATTERN.match(docket_part)
        if not docket_match:
            return

        docket_number = docket_part
        court_id = get_court_id_from_docket(docket_number)

        if court_id is None:
            return

        # Filter by docket if specified
        if target_docket and docket_number != target_docket:
            return

        # Filter by court if specified
        if target_courts and court_id not in target_courts:
            return

        # Get all links in this opinion entry
        links = opinion_div.checked_xpath(
            ".//a",
            "opinion links",
            min_count=1,
        )

        # Determine which link is the main opinion and which is summary
        main_opinion_url = None
        main_opinion_name = None
        summary_url = None

        for link in links:
            href_list = link.checked_xpath(
                "@href",
                "link href",
                min_count=1,
                max_count=1,
                type=str,
            )
            href = href_list[0]

            link_texts = link.checked_xpath(
                ".//text()",
                "link text",
                min_count=0,
                type=str,
            )
            link_text = "".join(link_texts).strip()

            if link_text.lower() == "overview/summary":
                summary_url = urljoin(response.url, href)
            else:
                # This is the main opinion link
                main_opinion_url = urljoin(response.url, href)
                main_opinion_name = link_text

        if not main_opinion_url or not main_opinion_name:
            return

        # Extract author and vote from remaining text
        author = None
        vote = None

        for text in text_parts:
            if text.startswith("Author:"):
                author = text[7:].strip()
            elif text.startswith("Vote:"):
                vote = text[5:].strip()

        # Extract disposition from vote
        disposition = None
        if vote:
            # Disposition is usually the first part before period
            disp_match = re.match(r"^([A-Z\s]+)\.", vote)
            if disp_match:
                disposition = disp_match.group(1).strip()

        # Build accumulated data for download handler
        cluster_data: dict[str, Any] = {
            "docket_id": docket_number,
            "court_id": court_id,
            "date_filed": opinion_date.isoformat(),
            "case_name": main_opinion_name,
            "source_url": response.url,
            "author": author,
            "vote": vote,
            "disposition": disposition,
            "main_opinion_url": main_opinion_url,
            "summary_url": summary_url,
            "pending_downloads": 1 + (1 if summary_url else 0),
            "completed_downloads": 0,
            "downloaded_opinions": [],
        }

        # Yield ArchiveRequest for the main opinion PDF
        yield ArchiveRequest(
            request=HTTPRequestParams(
                method=HttpMethod.GET,
                url=main_opinion_url,
            ),
            continuation=self.handle_opinion_download,
            expected_type="pdf",
            accumulated_data={**cluster_data, "is_summary": False},
        )

    # =========================================================================
    # Download Handler
    # =========================================================================

    @step
    def handle_opinion_download(
        self,
        response: ArchiveResponse,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[MissouriOpinionCluster], None, None]:
        """Handle a downloaded opinion PDF."""
        is_summary = accumulated_data.get("is_summary", False)

        # Create opinion object for this download
        opinion = MissouriOpinion(
            download_url=(
                accumulated_data["summary_url"]
                if is_summary
                else accumulated_data["main_opinion_url"]
            ),
            local_path=response.file_url,
            is_summary=is_summary,
        )

        # Add to downloaded opinions list
        downloaded = accumulated_data["downloaded_opinions"]
        downloaded.append(opinion)
        accumulated_data["completed_downloads"] += 1

        # Check if we need to download the summary
        if (
            not is_summary
            and accumulated_data.get("summary_url")
            and accumulated_data["completed_downloads"]
            < accumulated_data["pending_downloads"]
        ):
            # Need to download summary
            yield ArchiveRequest(
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url=accumulated_data["summary_url"],
                ),
                continuation=self.handle_opinion_download,
                expected_type="pdf",
                accumulated_data={**accumulated_data, "is_summary": True},
            )
            return

        # All downloads complete - yield final cluster
        date_filed = datetime.fromisoformat(
            accumulated_data["date_filed"]
        ).date()

        cluster = MissouriOpinionCluster(
            docket_id=accumulated_data["docket_id"],
            court_id=accumulated_data["court_id"],
            date_filed=date_filed,
            case_name=accumulated_data["case_name"],
            opinions=downloaded,
            source_url=accumulated_data["source_url"],
            author=accumulated_data.get("author"),
            vote=accumulated_data.get("vote"),
            disposition=accumulated_data.get("disposition"),
            precedential_status="Published",
        )

        yield ParsedData(cluster)
