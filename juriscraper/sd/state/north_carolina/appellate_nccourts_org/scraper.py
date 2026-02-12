"""North Carolina Appellate Courts Scraper.

This module scrapes opinions and orders from the North Carolina Supreme Court and
Court of Appeals using the slip opinions pages.

Entry points:
- Supreme Court: https://appellate.nccourts.org/opinion-filings/?c=sc
- Court of Appeals: https://appellate.nccourts.org/opinion-filings/?c=coa

Flow:
1. get_entry -> yields requests for Supreme Court and/or Court of Appeals pages
2. parse_slip_opinions_page -> parses table of opinions, yields ArchiveRequests for PDFs
3. handle_opinion_download -> yields final NCOpinionCluster

Page structure:
- Opinions are listed in a table grouped by filing date
- Each filing date has a header row with "Filed: DD Month YYYY" and "Mandate: DD Month YYYY"
- Published opinions have clickable case names that link to PDFs
- Unpublished opinions have text-only case names (not clickable)
- The PDF URL pattern is: https://appellate.nccourts.org/opinions/?c={1|2}&pdf={id}

Design decisions:
- Scrapes both courts unless filtered by court_id
- Uses DateRange filter on date_filed for searching
- Uses SetFilter on court_id to select which courts to scrape
- Each opinion becomes its own cluster (one cluster per case per filing date)
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import TYPE_CHECKING, ClassVar

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
    URL_COURT_PARAMS,
    NCOpinion,
    NCOpinionCluster,
)

if TYPE_CHECKING:
    from collections.abc import Generator

    from kent.data_types import ScraperYield


# Base URLs
SLIP_OPINIONS_BASE_URL = "https://appellate.nccourts.org/opinion-filings/"
PDF_BASE_URL = "https://appellate.nccourts.org/opinions/"


class NorthCarolinaScraper(BaseScraper[NCOpinionCluster]):
    """Scraper for North Carolina appellate court opinions.

    Scrapes opinions and orders from the North Carolina Supreme Court (nc) and
    Court of Appeals (ncctapp).

    Usage:
        # Scrape all opinions from both courts
        scraper = NorthCarolinaScraper()

        # Scrape only Supreme Court opinions
        params = NorthCarolinaScraper.params()
        params.NCOpinionCluster.court_id.values = {"nc"}
        scraper = NorthCarolinaScraper(params=params)

        # Scrape only Court of Appeals opinions
        params = NorthCarolinaScraper.params()
        params.NCOpinionCluster.court_id.values = {"ncctapp"}
        scraper = NorthCarolinaScraper(params=params)

        # Filter opinions by date range
        params = NorthCarolinaScraper.params()
        params.NCOpinionCluster.date_filed.gte = date(2026, 1, 1)
        params.NCOpinionCluster.date_filed.lte = date(2026, 1, 31)
        scraper = NorthCarolinaScraper(params=params)
    """

    # === Metadata ===
    court_ids: ClassVar[set[str]] = {"nc", "ncctapp"}
    court_url: ClassVar[str] = "https://appellate.nccourts.org/"
    data_types: ClassVar[set[str]] = {"opinions"}
    status: ClassVar[ScraperStatus] = ScraperStatus.IN_DEVELOPMENT
    version: ClassVar[str] = "2026-01-23"
    requires_auth: ClassVar[bool] = False

    # Rate limiting - be respectful to court servers
    msec_per_request_rate_limit: ClassVar[int] = 1000

    # === Regex patterns ===
    # Filing date pattern: "Filed: DD Month YYYY"
    FILING_DATE_PATTERN = re.compile(
        r"Filed:\s*(\d{1,2})\s+(\w+)\s+(\d{4})",
        re.IGNORECASE,
    )

    # Mandate date pattern: "Mandate: DD Month YYYY"
    MANDATE_DATE_PATTERN = re.compile(
        r"Mandate:\s*(\d{1,2})\s+(\w+)\s+(\d{4})",
        re.IGNORECASE,
    )

    # Docket number pattern in parentheses: (YY-NNNN - Published) or (YY-NNNN - Unpublished)
    # For COA: COA25-263 or just 25-263
    # For Supreme Court: 123P24 or 123PA24
    DOCKET_PATTERN = re.compile(
        r"\((\d{2}-\d+(?:-\d+)?)\s*-\s*(Published|Unpublished)\)",
        re.IGNORECASE,
    )

    # Author pattern: "Author: Judge Name" or "Author: Per Curiam"
    AUTHOR_PATTERN = re.compile(
        r"Author:\s*(.+?)(?:\s*$|\s*[;,])",
        re.IGNORECASE,
    )

    # PDF URL pattern to extract PDF ID
    PDF_ID_PATTERN = re.compile(r"pdf=(\d+)")

    # Month name to number mapping
    MONTH_MAP = {
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

    # Mapping from model name to data type
    MODEL_TO_DATA_TYPE: ClassVar[dict[str, str]] = {
        "NCOpinionCluster": "opinions",
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
            model_proxy = self._params.NCOpinionCluster
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

    def _parse_date_text(self, day: str, month: str, year: str) -> date | None:
        """Parse date components into a date object.

        Args:
            day: Day number as string
            month: Month name as string
            year: Year as string

        Returns:
            Parsed date or None if invalid
        """
        try:
            month_num = self.MONTH_MAP.get(month.lower())
            if month_num is None:
                return None
            return date(int(year), month_num, int(day))
        except (ValueError, TypeError):
            return None

    # =========================================================================
    # Entry Point
    # =========================================================================

    @entry(NCOpinionCluster)
    def get_entry(self) -> Generator[NavigatingRequest, None, None]:
        """Yield initial requests to slip opinions pages."""
        requested = self._get_requested_data_types()

        if "opinions" not in requested:
            return

        _, _, _, court_ids = self._get_search_params()

        # If no specific courts requested, scrape both
        courts_to_scrape = court_ids if court_ids else {"nc", "ncctapp"}

        for court_id in courts_to_scrape:
            params = URL_COURT_PARAMS.get(court_id)
            if params is None:
                continue

            url = f"{SLIP_OPINIONS_BASE_URL}?c={params['c']}"

            yield NavigatingRequest(
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url=url,
                ),
                continuation=self.parse_slip_opinions_page,
                accumulated_data={"court_id": court_id},
            )

    # =========================================================================
    # Slip Opinions Page Parsing
    # =========================================================================

    @step(xsd="xsds/parse_slip_opinions_page.xsd")
    def parse_slip_opinions_page(
        self,
        lxml_tree: CheckedHtmlElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[NCOpinionCluster], None, None]:
        """Parse slip opinions page and yield requests for each opinion PDF."""
        date_gte, date_lte, target_docket, _ = self._get_search_params()
        court_id = accumulated_data["court_id"]
        court_params = URL_COURT_PARAMS[court_id]

        # Find the table containing opinions
        tables = lxml_tree.checked_xpath(
            "//table",
            "opinions table",
            min_count=0,
        )

        if not tables:
            # No opinions on this page (e.g., Supreme Court may have none for current year)
            return

        table = tables[0]

        # Get all rows from the table
        rows = table.checked_xpath(
            ".//tr",
            "table rows",
            min_count=0,
        )

        current_filing_date: date | None = None
        current_mandate_date: date | None = None

        for row in rows:
            # Get all text content from the row
            row_text = "".join(row.itertext()).strip()

            if not row_text:
                continue

            # Check if this is a filing date header row
            filing_match = self.FILING_DATE_PATTERN.search(row_text)
            if filing_match:
                current_filing_date = self._parse_date_text(
                    filing_match.group(1),
                    filing_match.group(2),
                    filing_match.group(3),
                )

                # Also extract mandate date if present
                mandate_match = self.MANDATE_DATE_PATTERN.search(row_text)
                if mandate_match:
                    current_mandate_date = self._parse_date_text(
                        mandate_match.group(1),
                        mandate_match.group(2),
                        mandate_match.group(3),
                    )
                continue

            # Check if this is an "Unpublished Opinions" header row
            if "Unpublished Opinions" in row_text and "Rule 30e" in row_text:
                continue

            # Check if this is an informational row (petitions/motions count)
            if "IN ADDITION TO THE ABOVE LISTED" in row_text:
                continue

            # Skip if we don't have a filing date yet
            if current_filing_date is None:
                continue

            # Apply date filter
            if date_gte and current_filing_date < date_gte:
                continue
            if date_lte and current_filing_date > date_lte:
                continue

            # Try to extract opinion data from this row
            opinion_data = self._parse_opinion_row(
                row, row_text, court_id, court_params
            )

            if opinion_data is None:
                continue

            # Apply docket filter
            if (
                target_docket
                and opinion_data["docket_number"] != target_docket
            ):
                continue

            # Build cluster data
            cluster_data = {
                "docket_id": opinion_data["docket_number"],
                "court_id": court_id,
                "date_filed": current_filing_date.isoformat(),
                "mandate_date": current_mandate_date.isoformat()
                if current_mandate_date
                else None,
                "case_name": opinion_data["case_name"],
                "author_str": opinion_data.get("author"),
                "headnotes": opinion_data.get("headnotes"),
                "precedential_status": opinion_data["status"],
                "source_url": response.url,
                "pdf_url": opinion_data["pdf_url"],
            }

            if opinion_data["pdf_url"]:
                # Yield ArchiveRequest for the PDF
                yield ArchiveRequest(
                    request=HTTPRequestParams(
                        method=HttpMethod.GET,
                        url=opinion_data["pdf_url"],
                    ),
                    continuation=self.handle_opinion_download,
                    expected_type="pdf",
                    accumulated_data=cluster_data,
                )
            else:
                # Unpublished opinions may not have clickable links
                # Still yield the cluster with what we have
                yield from self._yield_cluster_without_pdf(cluster_data)

    def _parse_opinion_row(
        self,
        row: CheckedHtmlElement,
        row_text: str,
        court_id: str,
        court_params: dict,
    ) -> dict | None:
        """Parse an opinion row and extract case data.

        Args:
            row: The table row element
            row_text: Full text content of the row
            court_id: Court identifier ('nc' or 'ncctapp')
            court_params: URL parameters for the court

        Returns:
            Dictionary with case data or None if not a valid opinion row
        """
        # Look for docket pattern
        docket_match = self.DOCKET_PATTERN.search(row_text)
        if not docket_match:
            return None

        raw_docket = docket_match.group(1)
        status = docket_match.group(2).capitalize()

        # Build full docket number
        if court_id == "ncctapp":
            docket_number = f"COA{raw_docket}"
        else:
            # Supreme Court dockets are different format
            docket_number = raw_docket

        # Extract case name - text before the parenthetical
        case_name = "Unknown"
        docket_pos = row_text.find(f"({raw_docket}")
        if docket_pos > 0:
            case_name = row_text[:docket_pos].strip()
            # Clean up the case name
            case_name = case_name.strip("- \n\t")

        # Extract author
        author = None
        author_match = self.AUTHOR_PATTERN.search(row_text)
        if author_match:
            author = author_match.group(1).strip()

        # Extract headnotes (everything after author line)
        headnotes = None
        if author_match:
            headnotes_start = author_match.end()
            headnotes = row_text[headnotes_start:].strip()
            if headnotes:
                # Clean up headnotes
                headnotes = headnotes.strip("; \n\t")
        else:
            # Try to get headnotes after the docket pattern
            docket_end = docket_match.end()
            remaining = row_text[docket_end:].strip()
            # Skip "Author:" part if present
            if remaining.startswith("Author:"):
                pass  # Will be handled by author pattern
            elif remaining:
                headnotes = remaining.strip("; \n\t")

        # Find PDF URL - look for onclick attribute or href with pdf parameter
        pdf_url = None

        # Try to find a link with onclick or href
        links = row.checked_xpath(
            ".//a[@href] | .//*[@onclick]",
            "opinion links",
            min_count=0,
        )

        for link in links:
            # Check onclick attribute
            onclick = link.get("onclick", "")
            if "pdf=" in onclick:
                pdf_match = self.PDF_ID_PATTERN.search(onclick)
                if pdf_match:
                    pdf_id = pdf_match.group(1)
                    pdf_url = f"{PDF_BASE_URL}?c={court_params['c_num']}&pdf={pdf_id}"
                    break

            # Check href attribute
            href = link.get("href", "")
            if "pdf=" in href:
                if href.startswith("/"):
                    pdf_url = f"https://appellate.nccourts.org{href}"
                elif href.startswith("http"):
                    pdf_url = href
                else:
                    pdf_url = f"{PDF_BASE_URL}{href}"
                break

        # For published opinions, there should be a clickable link
        # For unpublished, there may not be
        if status == "Published" and pdf_url is None:
            # If we can't find a PDF link for a published opinion, skip it
            # This might indicate a structural change
            pass

        return {
            "docket_number": docket_number,
            "case_name": case_name,
            "status": status,
            "author": author,
            "headnotes": headnotes,
            "pdf_url": pdf_url,
        }

    def _yield_cluster_without_pdf(
        self, cluster_data: dict
    ) -> Generator[ScraperYield[NCOpinionCluster], None, None]:
        """Yield a cluster for cases without downloadable PDFs (e.g., unpublished)."""
        date_filed = datetime.fromisoformat(cluster_data["date_filed"]).date()

        mandate_date = None
        if cluster_data.get("mandate_date"):
            mandate_date = datetime.fromisoformat(
                cluster_data["mandate_date"]
            ).date()

        cluster = NCOpinionCluster(
            docket_id=cluster_data["docket_id"],
            court_id=cluster_data["court_id"],
            date_filed=date_filed,
            case_name=cluster_data["case_name"],
            opinions=[],  # No PDF available
            source_url=cluster_data["source_url"],
            author_str=cluster_data.get("author_str"),
            headnotes=cluster_data.get("headnotes"),
            precedential_status=cluster_data["precedential_status"],
            mandate_date=mandate_date,
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
    ) -> Generator[ScraperYield[NCOpinionCluster], None, None]:
        """Handle a downloaded opinion PDF."""
        date_filed = datetime.fromisoformat(
            accumulated_data["date_filed"]
        ).date()

        mandate_date = None
        if accumulated_data.get("mandate_date"):
            mandate_date = datetime.fromisoformat(
                accumulated_data["mandate_date"]
            ).date()

        opinion = NCOpinion(
            download_url=accumulated_data["pdf_url"],
            type="010combined",
            local_path=response.file_url,
        )

        cluster = NCOpinionCluster(
            docket_id=accumulated_data["docket_id"],
            court_id=accumulated_data["court_id"],
            date_filed=date_filed,
            case_name=accumulated_data["case_name"],
            opinions=[opinion],
            source_url=accumulated_data["source_url"],
            author_str=accumulated_data.get("author_str"),
            headnotes=accumulated_data.get("headnotes"),
            precedential_status=accumulated_data["precedential_status"],
            mandate_date=mandate_date,
        )

        yield ParsedData(cluster)
