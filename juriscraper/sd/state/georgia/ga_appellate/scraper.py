"""Georgia Appellate Courts Opinions Scraper.

This module contains a unified scraper for opinions from Georgia appellate courts:
- Georgia Supreme Court (ga)
- Georgia Court of Appeals (gactapp)

Entry points:
- Supreme Court: Date-based scraping from yearly opinion archives
  URL: https://www.gasupreme.us/{YYYY}-opinions/
- Court of Appeals: Date-based scraping from opinion search
  URL: https://www.gaappeals.gov/wp-content/themes/benjamin/docket/docketdate/results_all.php

Design decisions:
- Uses date-based search for both courts (preferred over speculative ID probing)
- Parses HTML pages for case metadata
- Archives opinion PDFs via ArchiveRequest
- Supreme Court: PDFs from WordPress uploads
- Court of Appeals: PDFs from efast.gaappeals.us with UUID-based URLs
"""

from __future__ import annotations

import re
from datetime import date, timedelta
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
    COURT_CONFIG,
    GA_CASE_TYPES,
    GACTAPP_CASE_TYPES,
    GaOpinion,
    GaOpinionCluster,
)

if TYPE_CHECKING:
    from collections.abc import Generator

    from juriscraper.scraper_driver.data_types import ScraperYield


class GeorgiaScraper(BaseScraper[GaOpinionCluster]):
    """Unified scraper for Georgia appellate court opinions.

    Scrapes opinions from the Georgia Supreme Court (ga) and
    Court of Appeals (gactapp).

    Usage:
        # Scrape all courts
        scraper = GeorgiaScraper()

        # Scrape only Supreme Court
        params = GeorgiaScraper.params()
        params.GaOpinionCluster.court_id.values = {"ga"}
        scraper = GeorgiaScraper(params=params)

        # Scrape only Court of Appeals
        params = GeorgiaScraper.params()
        params.GaOpinionCluster.court_id.values = {"gactapp"}
        scraper = GeorgiaScraper(params=params)

        # Filter by date range
        params = GeorgiaScraper.params()
        params.GaOpinionCluster.date_filed.gte = date(2026, 1, 1)
        params.GaOpinionCluster.date_filed.lte = date(2026, 1, 31)
        scraper = GeorgiaScraper(params=params)
    """

    # === Metadata ===
    court_ids: ClassVar[set[str]] = {"ga", "gactapp"}
    court_url: ClassVar[str] = "https://www.gasupreme.us/"
    data_types: ClassVar[set[str]] = {"opinions"}
    status: ClassVar[ScraperStatus] = ScraperStatus.IN_DEVELOPMENT
    version: ClassVar[str] = "2026-01-22"
    requires_auth: ClassVar[bool] = False

    # Rate limiting - be respectful to court servers
    msec_per_request_rate_limit: ClassVar[int] = 2000

    # === Regex patterns ===
    # Pattern to extract case number and case name from Supreme Court links
    # Example: "S25A0994. FRANKLIN v. THE STATE"
    GA_LINK_PATTERN = re.compile(
        r"^(?P<docket>S\d{2}[A-Z]\d+)(?:,\s*S\d{2}[A-Z]\d+)*\.\s+(?P<case_name>.+)$"
    )

    # Pattern to parse case number components
    # Example: "S25A0994" -> year=25, type=A, seq=0994
    CASE_NUM_PATTERN = re.compile(
        r"^(?P<prefix>[SA])(?P<year>\d{2})(?P<type>[A-Z])(?P<seq>\d+)$"
    )

    # Date patterns
    # For Supreme Court: "January 21, 2026—"
    GA_DATE_PATTERN = re.compile(
        r"^(?P<month>\w+)\s+(?P<day>\d{1,2}),\s+(?P<year>\d{4})"
    )

    # Month name to number mapping
    MONTH_NAMES = {
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

    def _get_search_params(
        self,
    ) -> tuple[date | None, date | None, set[str] | None]:
        """Extract search parameters from ScraperParams.

        Returns:
            Tuple of (date_gte, date_lte, court_ids)
        """
        if self._params is None:
            return None, None, None

        try:
            model_proxy = self._params.GaOpinionCluster
        except AttributeError:
            return None, None, None

        date_gte = None
        date_lte = None
        court_ids = None

        searchable = model_proxy.get_searchable_fields()

        date_field = searchable.get("date_filed")
        if date_field and date_field.is_set():
            date_gte = date_field.gte
            date_lte = date_field.lte

        court_field = searchable.get("court_id")
        if court_field and court_field.is_set():
            court_ids = court_field.values

        return date_gte, date_lte, court_ids

    def _get_target_courts(self) -> set[str]:
        """Get the set of court IDs to scrape."""
        _, _, court_ids = self._get_search_params()

        if court_ids:
            valid_courts = court_ids & set(COURT_CONFIG.keys())
            if valid_courts:
                return valid_courts

        return set(COURT_CONFIG.keys())

    def _get_date_range(self) -> tuple[date, date]:
        """Get the date range to scrape.

        Returns:
            Tuple of (start_date, end_date). Defaults to today's date if not specified.
        """
        date_gte, date_lte, _ = self._get_search_params()

        # Default to today if no date range specified
        today = date.today()
        start_date = date_gte or today
        end_date = date_lte or today

        return start_date, end_date

    def _parse_case_type(
        self, docket_number: str
    ) -> tuple[str | None, str | None]:
        """Parse case type from docket number.

        Args:
            docket_number: Case number (e.g., 'S25A0994' or 'A25A1439')

        Returns:
            Tuple of (type_code, type_description)
        """
        match = self.CASE_NUM_PATTERN.match(docket_number)
        if not match:
            return None, None

        prefix = match.group("prefix")
        type_code = match.group("type")

        if prefix == "S":
            description = GA_CASE_TYPES.get(type_code)
        else:
            description = GACTAPP_CASE_TYPES.get(type_code)

        return type_code, description

    def _parse_date_from_text(self, text: str) -> date | None:
        """Parse date from text like 'January 21, 2026'.

        Args:
            text: Date text to parse

        Returns:
            Parsed date or None if parsing fails
        """
        match = self.GA_DATE_PATTERN.search(text)
        if not match:
            return None

        try:
            month_name = match.group("month").lower()
            month = self.MONTH_NAMES.get(month_name)
            if not month:
                return None
            day = int(match.group("day"))
            year = int(match.group("year"))
            return date(year, month, day)
        except (ValueError, KeyError):
            return None

    # =========================================================================
    # Entry Point
    # =========================================================================

    @step()
    def get_entry(
        self,
    ) -> Generator[ScraperYield[GaOpinionCluster], None, None]:
        """Yield navigation requests to opinion pages for each target court.

        Branches early based on target courts - Supreme Court and Court of Appeals
        have different page structures and URLs.
        """
        target_courts = self._get_target_courts()
        start_date, end_date = self._get_date_range()

        # Branch based on which courts to scrape
        if "ga" in target_courts:
            # Supreme Court: scrape yearly opinion pages
            # Get unique years in the date range
            years = set()
            current = start_date
            while current <= end_date:
                years.add(current.year)
                current += timedelta(days=365)
            years.add(end_date.year)

            for year in sorted(years):
                yield NavigatingRequest(
                    request=HTTPRequestParams(
                        method=HttpMethod.GET,
                        url=f"https://www.gasupreme.us/{year}-opinions/",
                    ),
                    continuation=self.parse_ga_opinions_page,
                    accumulated_data={
                        "court_id": "ga",
                        "year": year,
                        "date_gte": start_date,
                        "date_lte": end_date,
                    },
                )

        if "gactapp" in target_courts:
            # Court of Appeals: scrape day by day using opinion search
            current_date = start_date
            while current_date <= end_date:
                # Format date as D-M-YYYY (no leading zeros)
                date_str = f"{current_date.day}-{current_date.month}-{current_date.year}"
                url = (
                    f"https://www.gaappeals.gov/wp-content/themes/benjamin/"
                    f"docket/docketdate/results_all.php"
                    f"?OPstartDate={date_str}&OPendDate={date_str}"
                )

                yield NavigatingRequest(
                    request=HTTPRequestParams(
                        method=HttpMethod.GET,
                        url=url,
                    ),
                    continuation=self.parse_gactapp_opinions_page,
                    accumulated_data={
                        "court_id": "gactapp",
                        "query_date": current_date,
                    },
                )

                current_date += timedelta(days=1)

    # =========================================================================
    # Supreme Court Opinion Parsing
    # =========================================================================

    @step()
    def parse_ga_opinions_page(
        self,
        lxml_tree: CheckedHtmlElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[GaOpinionCluster], None, None]:
        """Parse the Supreme Court opinions year page.

        The page structure is:
        - Multiple date sections, each with:
          - A heading with date (e.g., "January 21, 2026—SUMMARIES...")
          - A list of opinion links

        Each opinion link has format:
        - "S25A0994. FRANKLIN v. THE STATE"
        """
        date_gte = accumulated_data.get("date_gte")
        date_lte = accumulated_data.get("date_lte")

        # Find all date headings and their associated opinion lists
        # The structure is: <p><strong>January 21, 2026—...</strong></p>
        # followed by <ul> with opinion links
        date_sections = lxml_tree.xpath("//p[strong[contains(text(), '—')]]")

        current_date: date | None = None

        for section in date_sections:
            # Extract the date from the heading
            heading_text = section.text_content().strip()
            parsed_date = self._parse_date_from_text(heading_text)
            if parsed_date:
                current_date = parsed_date

            # Check if date is within range
            if current_date:
                if date_gte and current_date < date_gte:
                    continue
                if date_lte and current_date > date_lte:
                    continue

            # Find the next sibling <ul> containing opinion links
            following_ul = section.xpath("following-sibling::ul[1]")
            if not following_ul:
                continue

            ul = following_ul[0]

            # Parse each opinion link
            links = ul.xpath(".//li/a")
            for link in links:
                link_text = link.text_content().strip()
                href = link.get("href", "")

                if not href or not link_text:
                    continue

                # Parse the link text to extract docket number and case name
                match = self.GA_LINK_PATTERN.match(link_text)
                if not match:
                    # Handle multi-case consolidated opinions
                    # Example: "S25A1098, S25A1099, S25A1100. UPSHAW v. THE STATE (three cases)"
                    parts = link_text.split(". ", 1)
                    if len(parts) == 2:
                        docket_part = parts[0].strip()
                        case_name = parts[1].strip()
                        # Use the first docket number
                        docket_numbers = [
                            d.strip() for d in docket_part.split(",")
                        ]
                        docket_number = (
                            docket_numbers[0] if docket_numbers else ""
                        )
                    else:
                        continue
                else:
                    docket_number = match.group("docket")
                    case_name = match.group("case_name")

                # Get case type info
                type_code, type_desc = self._parse_case_type(docket_number)

                # Create the opinion cluster
                cluster = GaOpinionCluster(
                    court_id="ga",
                    date_filed=current_date or date.today(),
                    case_name=case_name,
                    docket_number=docket_number,
                    case_type_code=type_code,
                    case_type_description=type_desc,
                    source_url=response.url,
                    opinions=[],
                )

                # Create opinion with PDF URL
                opinion = GaOpinion(
                    download_url=href,
                    type="majority",
                )
                cluster.opinions.append(opinion)

                # Yield ArchiveRequest for PDF download
                yield ArchiveRequest(
                    request=HTTPRequestParams(
                        method=HttpMethod.GET,
                        url=href,
                    ),
                    continuation=self.handle_opinion_download,
                    expected_type="pdf",
                    accumulated_data={
                        "cluster": cluster,
                    },
                )

    # =========================================================================
    # Court of Appeals Opinion Parsing
    # =========================================================================

    @step()
    def parse_gactapp_opinions_page(
        self,
        lxml_tree: CheckedHtmlElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[GaOpinionCluster], None, None]:
        """Parse the Court of Appeals opinion search results page.

        The page structure is a table with columns:
        - Case Number
        - Style
        - Judgment Date
        - COA Judgment/Ruling
        - Web Docket (link)
        - Opinion/Order (PDF link)
        """
        query_date = accumulated_data.get("query_date")

        # Find all table rows (skip header row)
        rows = lxml_tree.xpath("//table//tr[position() > 1]")

        for row in rows:
            cells = row.xpath("td")
            if len(cells) < 6:
                continue

            # Extract cell values
            docket_number = cells[0].text_content().strip()
            case_name = cells[1].text_content().strip()
            judgment_date_text = cells[2].text_content().strip()
            disposition = cells[3].text_content().strip()

            # Get PDF link from the last cell
            pdf_links = cells[5].xpath(".//a/@href")
            if not pdf_links:
                continue
            pdf_url = pdf_links[0]

            # Parse judgment date
            # Format: "January 22, 2026"
            judgment_date = self._parse_date_from_text(judgment_date_text)
            if not judgment_date:
                judgment_date = query_date or date.today()

            # Get case type info
            type_code, type_desc = self._parse_case_type(docket_number)

            # Create the opinion cluster
            cluster = GaOpinionCluster(
                court_id="gactapp",
                date_filed=judgment_date,
                case_name=case_name,
                docket_number=docket_number,
                case_type_code=type_code,
                case_type_description=type_desc,
                disposition=disposition,
                source_url=response.url,
                opinions=[],
            )

            # Create opinion with PDF URL
            opinion = GaOpinion(
                download_url=pdf_url,
                type="majority",
            )
            cluster.opinions.append(opinion)

            # Yield ArchiveRequest for PDF download
            yield ArchiveRequest(
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url=pdf_url,
                ),
                continuation=self.handle_opinion_download,
                expected_type="pdf",
                accumulated_data={
                    "cluster": cluster,
                },
            )

    # =========================================================================
    # Common Download Handler
    # =========================================================================

    @step()
    def handle_opinion_download(
        self,
        archive_response: ArchiveResponse,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[GaOpinionCluster], None, None]:
        """Handle the downloaded opinion PDF and yield the final cluster.

        Args:
            archive_response: Response from archiving the PDF
            accumulated_data: Contains the cluster
        """
        cluster = accumulated_data.get("cluster")

        if not cluster or not isinstance(cluster, GaOpinionCluster):
            return

        # Update the opinion with the local path
        if cluster.opinions:
            cluster.opinions[0].local_path = archive_response.file_url

        # Yield the complete cluster
        yield ParsedData(data=cluster)
