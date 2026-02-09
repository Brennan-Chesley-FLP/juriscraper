"""Mississippi Appellate Courts Scraper.

This module scrapes published opinions from Mississippi appellate courts:
- Mississippi Supreme Court (miss)
- Mississippi Court of Appeals (missctapp)

Entry points:
- SCT Hand Down List: https://courts.ms.gov/Images/HDList/SCT{MM-DD-YYYY}.html
- COA Hand Down List: https://courts.ms.gov/Images/HDList/COA{MM-DD-YYYY}.html

Flow:
1. get_entry -> probe hand down list pages by date
2. parse_hand_down_list -> parses table, yields ArchiveRequests for PDFs
3. handle_opinion_download -> yields final MississippiOpinionCluster

Design decisions:
- Uses date-based probing since hand down lists are published weekly
- Supports both Supreme Court and Court of Appeals
- Published opinions have PDFs; EN BANC orders may not have PDFs
- Uses DateRange filter on date_filed for searching
- Court ID is derived from case number suffix (SCT or COA)
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
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
    COURT_SUFFIX_MAP,
    MississippiOpinion,
    MississippiOpinionCluster,
)

if TYPE_CHECKING:
    from collections.abc import Generator

    from juriscraper.scraper_driver.data_types import ScraperYield


# Base URLs
BASE_URL = "https://courts.ms.gov"
SCT_HANDDOWN_URL_TEMPLATE = (
    "https://courts.ms.gov/Images/HDList/SCT{date}.html"
)
COA_HANDDOWN_URL_TEMPLATE = (
    "https://courts.ms.gov/Images/HDList/COA{date}.html"
)
OPINION_PDF_BASE = "https://courts.ms.gov/appellatecourts/Opinions/"


class MississippiScraper(BaseScraper[MississippiOpinionCluster]):
    """Scraper for Mississippi appellate court opinions.

    Scrapes published opinions from:
    - Mississippi Supreme Court (miss)
    - Mississippi Court of Appeals (missctapp)

    Usage:
        # Scrape all opinions (probes recent dates)
        scraper = MississippiScraper()

        # Filter by date range
        params = MississippiScraper.params()
        params.MississippiOpinionCluster.date_filed.gte = date(2026, 1, 1)
        params.MississippiOpinionCluster.date_filed.lte = date(2026, 1, 31)
        scraper = MississippiScraper(params=params)

        # Filter by court
        params = MississippiScraper.params()
        params.MississippiOpinionCluster.court_id.values = {"miss"}
        scraper = MississippiScraper(params=params)

        # Search for specific case
        params = MississippiScraper.params()
        params.MississippiOpinionCluster.docket_number.value = "2024-KA-01001-SCT"
        scraper = MississippiScraper(params=params)
    """

    # === Metadata ===
    court_ids: ClassVar[set[str]] = {"miss", "missctapp"}
    court_url: ClassVar[str] = "https://courts.ms.gov/"
    data_types: ClassVar[set[str]] = {"opinions"}
    status: ClassVar[ScraperStatus] = ScraperStatus.IN_DEVELOPMENT
    version: ClassVar[str] = "2026-01-23"
    requires_auth: ClassVar[bool] = False

    # Rate limiting - be respectful to court servers
    msec_per_request_rate_limit: ClassVar[int] = 1000

    # === Regex patterns ===
    # Case number pattern: YYYY-TYPE-NNNNN-COURT
    # Examples: 2024-KA-01001-SCT, 2025-SA-00614-SCT, 2023-CT-01245-SCT
    CASE_NUMBER_PATTERN = re.compile(r"(\d{4})-([A-Z]{2})-(\d{5})-([A-Z]{3})")

    # Lower court case number pattern: e.g., "53CI1:23-cr-00051-K-1"
    LC_CASE_PATTERN = re.compile(r"LC Case #:\s*([^;]+)")

    # Ruling date pattern: e.g., "Ruling Date: 08/09/2024"
    RULING_DATE_PATTERN = re.compile(r"Ruling Date:\s*(\d{2}/\d{2}/\d{4})")

    # Ruling judge pattern: e.g., "Ruling Judge: James Kitchens, Jr."
    RULING_JUDGE_PATTERN = re.compile(r"Ruling Judge:\s*([^;]+)")

    # Disposition pattern: e.g., "Disposition: Affirmed."
    DISPOSITION_PATTERN = re.compile(r"Disposition:\s*([^.]+\.)")

    # Votes pattern: e.g., "Votes: Randolph, C.J., ..."
    VOTES_PATTERN = re.compile(r"Votes:\s*(.+)$")

    # Opinion ID from PDF URL: e.g., "CO189869" from "..\Opinions\CO189869.pdf"
    OPINION_ID_PATTERN = re.compile(r"CO(\d+)")

    # Date in hand down list header: "January 22, 2026"
    HEADER_DATE_PATTERN = re.compile(
        r"(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{1,2}),\s+(\d{4})"
    )

    # Mapping from model name to data type
    MODEL_TO_DATA_TYPE: ClassVar[dict[str, str]] = {
        "MississippiOpinionCluster": "opinions",
    }

    # Default number of days to probe backward
    DEFAULT_DAYS_TO_PROBE = 90

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
            model_proxy = self._params.MississippiOpinionCluster
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

    def _parse_case_number(
        self, case_num: str
    ) -> tuple[int, str, int, str] | None:
        """Parse case number to extract components.

        Args:
            case_num: Case number like '2024-KA-01001-SCT'

        Returns:
            Tuple of (year, type_code, number, court_suffix) or None
        """
        match = self.CASE_NUMBER_PATTERN.search(case_num)
        if match:
            return (
                int(match.group(1)),
                match.group(2),
                int(match.group(3)),
                match.group(4),
            )
        return None

    def _parse_date_mmddyyyy(self, date_str: str) -> date | None:
        """Parse date from MM/DD/YYYY format.

        Args:
            date_str: Date like '08/09/2024'

        Returns:
            Parsed date or None
        """
        try:
            return datetime.strptime(date_str.strip(), "%m/%d/%Y").date()
        except ValueError:
            return None

    def _extract_metadata_from_text(self, text: str) -> dict:
        """Extract metadata fields from opinion text block.

        Args:
            text: Full text content of opinion entry

        Returns:
            Dict with extracted fields
        """
        metadata = {}

        # Extract lower court case number
        lc_match = self.LC_CASE_PATTERN.search(text)
        if lc_match:
            metadata["lower_court_case_number"] = lc_match.group(1).strip()

        # Extract ruling date
        ruling_date_match = self.RULING_DATE_PATTERN.search(text)
        if ruling_date_match:
            metadata["lower_court_ruling_date"] = self._parse_date_mmddyyyy(
                ruling_date_match.group(1)
            )

        # Extract ruling judge
        ruling_judge_match = self.RULING_JUDGE_PATTERN.search(text)
        if ruling_judge_match:
            metadata["lower_court_judge"] = ruling_judge_match.group(1).strip()

        # Extract disposition
        disposition_match = self.DISPOSITION_PATTERN.search(text)
        if disposition_match:
            metadata["disposition"] = disposition_match.group(1).strip()

        # Extract votes
        votes_match = self.VOTES_PATTERN.search(text)
        if votes_match:
            metadata["votes"] = votes_match.group(1).strip()

        return metadata

    def _get_court_id_from_suffix(self, suffix: str) -> str:
        """Map court suffix to court_id.

        Args:
            suffix: Court suffix like 'SCT' or 'COA'

        Returns:
            Court ID ('miss' or 'missctapp')
        """
        return COURT_SUFFIX_MAP.get(suffix, "miss")

    # =========================================================================
    # Entry Point
    # =========================================================================

    @entry(MississippiOpinionCluster)
    def get_entry(  # type: ignore[override]
        self,
    ) -> Generator[ScraperYield[MississippiOpinionCluster], None, None]:
        """Yield initial requests to probe hand down list pages."""
        requested = self._get_requested_data_types()

        if "opinions" not in requested:
            return

        date_gte, date_lte, docket_number, court_ids = (
            self._get_search_params()
        )

        # Determine date range to probe
        end_date = date_lte or date.today()
        start_date = date_gte or (
            end_date - timedelta(days=self.DEFAULT_DAYS_TO_PROBE)
        )

        # Determine which courts to scrape
        scrape_sct = court_ids is None or "miss" in court_ids
        scrape_coa = court_ids is None or "missctapp" in court_ids

        # Yield requests for each court
        if scrape_sct:
            yield from self._probe_dates_for_court(
                "SCT", start_date, end_date, docket_number
            )

        if scrape_coa:
            yield from self._probe_dates_for_court(
                "COA", start_date, end_date, docket_number
            )

    def _probe_dates_for_court(
        self,
        court_prefix: str,
        start_date: date,
        end_date: date,
        docket_number: str | None,
    ) -> Generator[ScraperYield[MississippiOpinionCluster], bool | None, None]:
        """Probe dates for a specific court speculatively

        Args:
            court_prefix: 'SCT' or 'COA'
            start_date: Start date to probe
            end_date: End date to probe
            docket_number: Optional specific docket to search for
        """
        url_template = (
            SCT_HANDDOWN_URL_TEMPLATE
            if court_prefix == "SCT"
            else COA_HANDDOWN_URL_TEMPLATE
        )

        current_date = end_date
        while current_date >= start_date:
            date_str = current_date.strftime("%m-%d-%Y")
            url = url_template.format(date=date_str)

            should_continue = yield NavigatingRequest(
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url=url,
                ),
                continuation=self.parse_hand_down_list,
                accumulated_data={
                    "speculative_id": {
                        "MississippiOpinionCluster": {
                            "hand_down_date": current_date.isoformat()
                        }
                    },
                    "court_prefix": court_prefix,
                    "hand_down_date": current_date.isoformat(),
                    "target_docket": docket_number,
                },
                is_speculative=True,
            )

            if not should_continue:
                # 404 or other error - try next date
                pass

            # Move to previous day
            current_date -= timedelta(days=1)

    # =========================================================================
    # Hand Down List Parsing
    # =========================================================================

    @step(xsd="xsds/parse_hand_down_list.xsd")
    def parse_hand_down_list(
        self,
        lxml_tree: CheckedHtmlElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[MississippiOpinionCluster], None, None]:
        """Parse a hand down list page and yield requests for opinion PDFs."""
        hand_down_date = datetime.fromisoformat(
            accumulated_data["hand_down_date"]
        ).date()
        target_docket = accumulated_data.get("target_docket")

        # Get all table rows - each row is an opinion entry
        # The structure is: table > tbody > tr with two cells
        rows = lxml_tree.checked_xpath(
            "//table//tr[td]",
            "opinion rows",
            min_count=0,
        )

        for row in rows:
            # Get cells in this row
            cells = row.checked_xpath(
                "td",
                "row cells",
                min_count=1,
            )

            if len(cells) < 2:
                continue

            # The content is in the second cell
            content_cell = cells[1]

            # Check if this is a published opinion (has PDF link)
            pdf_links = content_cell.checked_xpath(
                ".//a[contains(@href, '.pdf')]",
                "PDF links",
                min_count=0,
            )

            if pdf_links:
                # Published opinion with PDF
                yield from self._parse_published_opinion(
                    content_cell,
                    pdf_links[0],
                    response,
                    hand_down_date,
                    target_docket,
                )
            else:
                # EN BANC order or other entry without PDF
                yield from self._parse_en_banc_order(
                    content_cell,
                    response,
                    hand_down_date,
                    target_docket,
                )

    def _parse_published_opinion(
        self,
        content_cell: CheckedHtmlElement,
        pdf_link: CheckedHtmlElement,
        response: Response,
        hand_down_date: date,
        target_docket: str | None,
    ) -> Generator[ScraperYield[MississippiOpinionCluster], None, None]:
        """Parse a published opinion entry with PDF."""
        # Get the full text content
        all_text = content_cell.text_content().strip()

        # Extract case number from PDF link text
        case_number_texts = pdf_link.checked_xpath(
            ".//text()",
            "case number text",
            min_count=1,
            type=str,
        )
        case_number = "".join(case_number_texts).strip()

        # Filter by specific docket if requested
        if target_docket and case_number != target_docket:
            return

        # Parse case number
        parsed = self._parse_case_number(case_number)
        if not parsed:
            return

        year, type_code, number, court_suffix = parsed
        court_id = self._get_court_id_from_suffix(court_suffix)

        # Get PDF URL
        pdf_hrefs = pdf_link.checked_xpath(
            "@href",
            "PDF href",
            min_count=1,
            max_count=1,
            type=str,
        )
        pdf_url = urljoin(response.url, pdf_hrefs[0])

        # Extract opinion ID from PDF URL
        opinion_id = None
        opinion_id_match = self.OPINION_ID_PATTERN.search(pdf_url)
        if opinion_id_match:
            opinion_id = f"CO{opinion_id_match.group(1)}"

        # Extract author (first text node before the case number)
        # The structure is: "Author Name\n X case-number"
        author = None
        first_text = content_cell.checked_xpath(
            "text()[1]",
            "first text",
            min_count=0,
            type=str,
        )
        if first_text:
            author = first_text[0].strip()

        # Check if published (has X marker)
        is_published = (
            "X" in all_text.split(case_number)[0]
            if case_number in all_text
            else True
        )

        # Extract case name from the <ul> or <b> element
        case_name = None
        bold_texts = content_cell.checked_xpath(
            ".//b//text()",
            "case name bold",
            min_count=0,
            type=str,
        )
        if bold_texts:
            case_name = "".join(bold_texts).strip()
        else:
            # Try getting from <ul> content
            ul_texts = content_cell.checked_xpath(
                ".//ul//text()",
                "case details",
                min_count=0,
                type=str,
            )
            if ul_texts:
                # First part before semicolon is usually the case name
                full_text = "".join(ul_texts).strip()
                if ";" in full_text:
                    case_name = full_text.split(";")[0].strip()
                else:
                    case_name = full_text

        if not case_name:
            case_name = f"Unknown ({case_number})"

        # Extract lower court info
        ul_text = ""
        ul_elements = content_cell.checked_xpath(
            ".//ul",
            "ul element",
            min_count=0,
        )
        if ul_elements:
            ul_text = ul_elements[0].text_content()

        # Extract lower court name (after case name, before LC Case #)
        lower_court = None
        if ";" in ul_text:
            parts = ul_text.split(";")
            if len(parts) > 1:
                lower_court = parts[1].strip()

        # Extract other metadata
        metadata = self._extract_metadata_from_text(ul_text)

        # Build accumulated data for download
        cluster_data = {
            "docket_number": case_number,
            "court_id": court_id,
            "date_filed": hand_down_date.isoformat(),
            "case_name": case_name,
            "source_url": response.url,
            "author": author,
            "lower_court": lower_court,
            "lower_court_case_number": metadata.get("lower_court_case_number"),
            "lower_court_ruling_date": (
                metadata["lower_court_ruling_date"].isoformat()
                if metadata.get("lower_court_ruling_date")
                else None
            ),
            "lower_court_judge": metadata.get("lower_court_judge"),
            "disposition": metadata.get("disposition"),
            "votes": metadata.get("votes"),
            "is_en_banc": False,
            "is_published": is_published,
            "pdf_url": pdf_url,
            "opinion_id": opinion_id,
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

    def _parse_en_banc_order(
        self,
        content_cell: CheckedHtmlElement,
        response: Response,
        hand_down_date: date,
        target_docket: str | None,
    ) -> Generator[ScraperYield[MississippiOpinionCluster], None, None]:
        """Parse an EN BANC order entry (no PDF)."""
        # Get full text content
        all_text = content_cell.text_content().strip()

        # Check if this is an EN BANC entry
        is_en_banc = all_text.startswith("EN BANC")

        # Find case number in text
        case_number_match = self.CASE_NUMBER_PATTERN.search(all_text)
        if not case_number_match:
            return

        case_number = case_number_match.group(0)

        # Filter by specific docket if requested
        if target_docket and case_number != target_docket:
            return

        # Parse case number
        parsed = self._parse_case_number(case_number)
        if not parsed:
            return

        year, type_code, number, court_suffix = parsed
        court_id = self._get_court_id_from_suffix(court_suffix)

        # Extract case name from bold text
        case_name = None
        bold_texts = content_cell.checked_xpath(
            ".//b//text()",
            "case name bold",
            min_count=0,
            type=str,
        )
        if bold_texts:
            case_name = "".join(bold_texts).strip()
        else:
            # Try to extract from <ul>
            ul_texts = content_cell.checked_xpath(
                ".//ul//text()",
                "case details",
                min_count=0,
                type=str,
            )
            if ul_texts:
                full_text = "".join(ul_texts).strip()
                if ";" in full_text:
                    case_name = full_text.split(";")[0].strip()
                else:
                    case_name = full_text

        if not case_name:
            case_name = f"Unknown ({case_number})"

        # Extract metadata from text
        ul_text = ""
        ul_elements = content_cell.checked_xpath(
            ".//ul",
            "ul element",
            min_count=0,
        )
        if ul_elements:
            ul_text = ul_elements[0].text_content()

        # Extract lower court
        lower_court = None
        if ";" in ul_text:
            parts = ul_text.split(";")
            if len(parts) > 1:
                lower_court = parts[1].strip()

        metadata = self._extract_metadata_from_text(ul_text)

        # EN BANC orders without PDFs - yield directly as ParsedData
        cluster = MississippiOpinionCluster(
            docket_number=case_number,
            court_id=court_id,
            date_filed=hand_down_date,
            case_name=case_name,
            source_url=response.url,
            author=None,
            lower_court=lower_court,
            lower_court_case_number=metadata.get("lower_court_case_number"),
            lower_court_ruling_date=metadata.get("lower_court_ruling_date"),
            lower_court_judge=metadata.get("lower_court_judge"),
            disposition=metadata.get("disposition"),
            votes=metadata.get("votes"),
            is_en_banc=is_en_banc,
            is_published=False,
            opinions=[],
            precedential_status="Unpublished",
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
    ) -> Generator[ScraperYield[MississippiOpinionCluster], None, None]:
        """Handle a downloaded opinion PDF."""
        date_filed = datetime.fromisoformat(
            accumulated_data["date_filed"]
        ).date()

        lower_court_ruling_date = None
        if accumulated_data.get("lower_court_ruling_date"):
            lower_court_ruling_date = datetime.fromisoformat(
                accumulated_data["lower_court_ruling_date"]
            ).date()

        opinion = MississippiOpinion(
            download_url=accumulated_data["pdf_url"],
            local_path=response.file_url,
            opinion_id=accumulated_data.get("opinion_id"),
        )

        cluster = MississippiOpinionCluster(
            docket_number=accumulated_data["docket_number"],
            court_id=accumulated_data["court_id"],
            date_filed=date_filed,
            case_name=accumulated_data["case_name"],
            source_url=accumulated_data["source_url"],
            author=accumulated_data.get("author"),
            lower_court=accumulated_data.get("lower_court"),
            lower_court_case_number=accumulated_data.get(
                "lower_court_case_number"
            ),
            lower_court_ruling_date=lower_court_ruling_date,
            lower_court_judge=accumulated_data.get("lower_court_judge"),
            disposition=accumulated_data.get("disposition"),
            votes=accumulated_data.get("votes"),
            is_en_banc=accumulated_data.get("is_en_banc", False),
            is_published=accumulated_data.get("is_published", True),
            opinions=[opinion],
            precedential_status="Published"
            if accumulated_data.get("is_published")
            else "Unpublished",
        )

        yield ParsedData(cluster)
