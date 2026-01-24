"""Texas Appellate Courts Opinion Scraper.

This module contains a unified scraper for opinions and orders from Texas courts:

- Texas Supreme Court (tex)
- Court of Criminal Appeals of Texas (texcrimapp)
- Texas Courts of Appeals 1-15 (texapp)

Entry points:

- Court of Criminal Appeals: ``https://search.txcourts.gov/DocketSrch.aspx?coa=coscca``
- Courts of Appeals: ``https://search.txcourts.gov/DocketSrch.aspx?coa=coa{NN}``
- Supreme Court: ``https://www.txcourts.gov/supreme/orders-opinions/``

URL patterns:

- CCA/COA Handdown by Date:
  CCA: ``https://search.txcourts.gov/handdown.aspx?coa=coscca&fulldate=MM/DD/YYYY``,
  COA: ``https://search.txcourts.gov/Docket.aspx?coa=coa{NN}&FullDate=MM/DD/YYYY``
- PDF URLs: ``https://search.txcourts.gov/SearchMedia.aspx?MediaVersionID={UUID}&...``

Flow:

1. get_entry -> branch by requested courts
2. For CCA: parse_cca_calendar -> list of dates -> parse_cca_handdown -> opinions
3. For COA: parse_coa_calendar -> list of dates -> parse_coa_handdown -> opinions
4. yield ArchiveRequests for PDFs
5. handle_opinion_download -> stores local paths, yields final clusters

Design decisions:

- Uses restrictive checked_xpaths to catch structural changes early
- Uses DateRange filter on date_decided for searching
- Uses SetFilter on court_id to select which courts to scrape
- Archives opinion PDFs via ArchiveRequest
- Texas has TWO high courts (unique among US states):
  Supreme Court handles civil matters only,
  Court of Criminal Appeals handles criminal matters only.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import TYPE_CHECKING, Any, ClassVar
from urllib.parse import urljoin

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
    COURT_CODE_NAMES,
    COURT_CODE_TO_ID,
    COURT_ID_TO_CODES,
    COURT_IDS,
    TexasOpinion,
    TexasOpinionCluster,
)

if TYPE_CHECKING:
    from collections.abc import Generator

    from juriscraper.scraper_driver.data_types import ScraperYield


class TexasScraper(BaseScraper[TexasOpinionCluster]):
    """Unified scraper for Texas appellate court opinions.

    Scrapes opinions and orders from:
    - Texas Supreme Court (tex)
    - Court of Criminal Appeals (texcrimapp)
    - Courts of Appeals 1-15 (texapp)

    Usage:
        # Scrape all courts (default is Supreme Court and CCA)
        scraper = TexasScraper()

        # Scrape only Court of Criminal Appeals
        params = TexasScraper.params()
        params.TexasOpinionCluster.court_id.values = {"texcrimapp"}
        scraper = TexasScraper(params=params)

        # Scrape all Courts of Appeals
        params = TexasScraper.params()
        params.TexasOpinionCluster.court_id.values = {"texapp"}
        scraper = TexasScraper(params=params)

        # Filter by date range
        params = TexasScraper.params()
        params.TexasOpinionCluster.date_decided.gte = date(2026, 1, 1)
        params.TexasScraper.TexasOpinionCluster.date_decided.lte = date(2026, 1, 31)
        scraper = TexasScraper(params=params)
    """

    # === Metadata ===
    court_ids: ClassVar[set[str]] = COURT_IDS
    court_url: ClassVar[str] = "https://www.txcourts.gov/"
    data_types: ClassVar[set[str]] = {"opinions", "orders"}
    status: ClassVar[ScraperStatus] = ScraperStatus.IN_DEVELOPMENT
    version: ClassVar[str] = "2026-01-23"
    requires_auth: ClassVar[bool] = False

    # Rate limiting - be respectful to court servers
    msec_per_request_rate_limit: ClassVar[int] = 1000

    # Base URLs
    CCA_CALENDAR_URL = "https://search.txcourts.gov/DocketSrch.aspx?coa=coscca"
    COA_CALENDAR_URL = (
        "https://search.txcourts.gov/DocketSrch.aspx?coa=coa{court_num:02d}"
    )
    CCA_HANDDOWN_URL = (
        "https://search.txcourts.gov/handdown.aspx?coa=coscca&fulldate={date}"
    )
    COA_HANDDOWN_URL = "https://search.txcourts.gov/Docket.aspx?coa=coa{court_num:02d}&FullDate={date}"

    # === Regex patterns ===
    # Date pattern: MM/DD/YYYY
    DATE_PATTERN = re.compile(r"(\d{1,2}/\d{1,2}/\d{4})")
    # Case number patterns
    SC_CASE_PATTERN = re.compile(r"(\d{2}-\d{4})")  # Supreme Court: YY-NNNN
    CCA_PDR_PATTERN = re.compile(r"(PD-\d{4}-\d{2})")  # PDR: PD-NNNN-YY
    CCA_WR_PATTERN = re.compile(r"(WR-[\d,]+-\d{2})")  # Writ: WR-NN,NNN-NN
    COA_CASE_PATTERN = re.compile(
        r"(\d{2}-\d{2}-\d{5}-C[RV])"
    )  # COA: NN-YY-NNNNN-CR/CV

    def _parse_date(self, date_str: str) -> date | None:
        """Parse a date string in MM/DD/YYYY format."""
        try:
            return datetime.strptime(date_str.strip(), "%m/%d/%Y").date()
        except ValueError:
            return None

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
            model_proxy = self._params.TexasOpinionCluster
        except AttributeError:
            return None, None, None

        date_gte = None
        date_lte = None
        court_ids = None

        searchable = model_proxy.get_searchable_fields()

        date_field = searchable.get("date_decided")
        if date_field and date_field.is_set():
            date_gte = date_field.gte
            date_lte = date_field.lte

        court_field = searchable.get("court_id")
        if court_field and court_field.is_set():
            court_ids = court_field.values

        return date_gte, date_lte, court_ids

    def _get_target_courts(self) -> list[str]:
        """Get the list of court codes to scrape based on court_ids filter.

        Returns list of court codes (e.g., ['cossup', 'coscca', 'coa01', ...])
        """
        _, _, court_ids = self._get_search_params()

        if court_ids:
            codes = []
            for court_id in court_ids:
                if court_id in COURT_ID_TO_CODES:
                    codes.extend(COURT_ID_TO_CODES[court_id])
            return codes if codes else ["coscca"]  # Default to CCA

        # Default: Court of Criminal Appeals only
        # Users can specify court_id.values to include other courts
        return ["coscca"]

    # =========================================================================
    # Entry Point
    # =========================================================================

    def get_entry(self) -> Generator[NavigatingRequest, None, None]:
        """Yield initial requests for opinion scraping.

        Branches based on requested courts:
        - coscca -> CCA calendar page
        - coa01-coa15 -> COA calendar pages
        - cossup -> Supreme Court (different site structure)
        """
        court_codes = self._get_target_courts()
        date_gte, date_lte, _ = self._get_search_params()

        # Separate CCA, COA, and Supreme Court requests
        cca_requested = "coscca" in court_codes
        coa_codes = [c for c in court_codes if c.startswith("coa")]
        sc_requested = "cossup" in court_codes

        # Start with CCA if requested
        if cca_requested:
            yield NavigatingRequest(
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url=self.CCA_CALENDAR_URL,
                ),
                continuation=self.parse_cca_calendar,
                accumulated_data={
                    "court_code": "coscca",
                    "remaining_coa_codes": coa_codes,
                    "sc_requested": sc_requested,
                    "date_gte": date_gte.isoformat() if date_gte else None,
                    "date_lte": date_lte.isoformat() if date_lte else None,
                },
            )
        elif coa_codes:
            # Start with first COA court
            first_code = coa_codes[0]
            court_num = int(first_code[3:])
            yield NavigatingRequest(
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url=self.COA_CALENDAR_URL.format(court_num=court_num),
                ),
                continuation=self.parse_coa_calendar,
                accumulated_data={
                    "court_code": first_code,
                    "remaining_coa_codes": coa_codes[1:],
                    "sc_requested": sc_requested,
                    "date_gte": date_gte.isoformat() if date_gte else None,
                    "date_lte": date_lte.isoformat() if date_lte else None,
                },
            )
        elif sc_requested:
            # Supreme Court not yet implemented - TODO
            pass

    # =========================================================================
    # CCA Calendar Parsing
    # =========================================================================

    @step(xsd="xsds/parse_cca_calendar.xsd")
    def parse_cca_calendar(
        self,
        lxml_tree: CheckedHtmlElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[TexasOpinionCluster], None, None]:
        """Parse the CCA Released Orders/Opinions calendar page.

        Extracts handdown dates and yields requests for each date's page.
        The calendar shows dates organized by month in a table.
        """
        date_gte_str = accumulated_data.get("date_gte")
        date_lte_str = accumulated_data.get("date_lte")
        remaining_coa_codes = accumulated_data.get("remaining_coa_codes", [])
        sc_requested = accumulated_data.get("sc_requested", False)

        date_gte = date.fromisoformat(date_gte_str) if date_gte_str else None
        date_lte = date.fromisoformat(date_lte_str) if date_lte_str else None

        # Find all handdown date links
        # These are in a table with links like handdown.aspx?coa=coscca&fulldate=MM/DD/YYYY
        date_links = lxml_tree.xpath(
            "//table//a[contains(@href, 'handdown.aspx') and contains(@href, 'coscca')]"
        )

        handdown_dates = []
        for link in date_links:
            href = link.get("href", "")
            link_text = link.text_content().strip()

            # Extract date from link text (MM/DD/YYYY format)
            date_match = self.DATE_PATTERN.search(link_text)
            if date_match:
                parsed_date = self._parse_date(date_match.group(1))
                if parsed_date:
                    # Apply date filters
                    if date_gte and parsed_date < date_gte:
                        continue
                    if date_lte and parsed_date > date_lte:
                        continue
                    handdown_dates.append(
                        (parsed_date, urljoin(response.url, href))
                    )

        # Yield requests for each handdown date
        for i, (handdown_date, handdown_url) in enumerate(handdown_dates):
            is_last = i == len(handdown_dates) - 1
            yield NavigatingRequest(
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url=handdown_url,
                ),
                continuation=self.parse_cca_handdown,
                accumulated_data={
                    "court_code": "coscca",
                    "handdown_date": handdown_date.isoformat(),
                    "is_last_date": is_last,
                    "remaining_coa_codes": remaining_coa_codes
                    if is_last
                    else [],
                    "sc_requested": sc_requested if is_last else False,
                    "date_gte": date_gte_str,
                    "date_lte": date_lte_str,
                },
            )

        # If no dates found and there are other courts to process
        if not handdown_dates and remaining_coa_codes:
            yield from self._yield_next_court_request(
                remaining_coa_codes, sc_requested, date_gte_str, date_lte_str
            )

    # =========================================================================
    # CCA Handdown Page Parsing
    # =========================================================================

    @step(xsd="xsds/parse_cca_handdown.xsd")
    def parse_cca_handdown(
        self,
        lxml_tree: CheckedHtmlElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[TexasOpinionCluster], None, None]:
        """Parse a CCA handdown page.

        The CCA handdown page has a specific structure with categories like:
        - "HABEAS CORPUS RELIEF GRANTED-OPINIONS BY THE COURT:"
        - "APPELLANT'S PETITION FOR DISCRETIONARY REVIEW GRANTED:"
        - etc.

        Each case entry has:
        - Case number link (e.g., WR-82,126-02)
        - Party name and county
        - Document type and PDF links
        """
        court_code = accumulated_data.get("court_code", "coscca")
        handdown_date_str = accumulated_data.get("handdown_date")
        is_last_date = accumulated_data.get("is_last_date", False)
        remaining_coa_codes = accumulated_data.get("remaining_coa_codes", [])
        sc_requested = accumulated_data.get("sc_requested", False)
        date_gte_str = accumulated_data.get("date_gte")
        date_lte_str = accumulated_data.get("date_lte")

        handdown_date = (
            date.fromisoformat(handdown_date_str)
            if handdown_date_str
            else None
        )

        court_id = COURT_CODE_TO_ID.get(court_code, "texcrimapp")
        court_name = COURT_CODE_NAMES.get(
            court_code, "Court of Criminal Appeals"
        )

        # The page content is in a specific div structure
        # Categories are in divs with text like "CATEGORY NAME:"
        # Case entries follow each category

        # Find all case links (links to Case.aspx)
        case_links = lxml_tree.xpath("//a[contains(@href, 'Case.aspx?cn=')]")

        # Process each case
        seen_cases: set[str] = set()
        for case_link in case_links:
            case_number = case_link.text_content().strip()
            if not case_number or case_number in seen_cases:
                continue
            seen_cases.add(case_number)

            # Get the parent container to find associated data
            parent = case_link.getparent()
            if parent is None:
                continue

            # Find the grandparent to get full context
            grandparent = parent.getparent()
            if grandparent is None:
                grandparent = parent

            # Extract party name and county from sibling text
            full_text = grandparent.text_content()
            case_name = self._extract_case_name_from_text(
                full_text, case_number
            )
            county = self._extract_county_from_text(full_text)

            # Find category by looking for preceding category header
            category = self._find_category_for_case(case_link)

            # Find PDF links associated with this case
            # Look for sibling elements with PDF links
            pdf_links = grandparent.xpath(
                ".//a[contains(@href, 'SearchMedia.aspx')]"
            )

            opinions = []
            for pdf_link in pdf_links:
                pdf_url = urljoin(response.url, pdf_link.get("href", ""))

                # Determine opinion type from surrounding text
                parent_text = ""
                pdf_parent = pdf_link.getparent()
                if pdf_parent is not None:
                    parent_text = pdf_parent.text_content()

                opinion_type = self._determine_opinion_type(parent_text)
                author = self._extract_author(parent_text)
                published = "NON-PUBLISHED" not in parent_text.upper()

                opinions.append(
                    {
                        "download_url": pdf_url,
                        "type": opinion_type,
                        "author": author,
                        "published": published,
                    }
                )

            if not opinions:
                # Some entries don't have PDFs (e.g., denials without written order)
                # Create a cluster anyway for tracking
                cluster = TexasOpinionCluster(
                    court_id=court_id,
                    court_code=court_code,
                    court_name=court_name,
                    case_name=case_name or case_number,
                    docket_number=case_number,
                    date_decided=handdown_date,
                    disposition=category,
                    county=county,
                    case_type="criminal",
                    category=category,
                    source_url=response.url,
                    opinions=[],
                )
                yield ParsedData(cluster)
            else:
                # Yield ArchiveRequest for first PDF
                cluster_data: dict[str, Any] = {
                    "court_id": court_id,
                    "court_code": court_code,
                    "court_name": court_name,
                    "case_name": case_name or case_number,
                    "docket_number": case_number,
                    "date_decided": handdown_date.isoformat()
                    if handdown_date
                    else None,
                    "county": county,
                    "case_type": "criminal",
                    "category": category,
                    "source_url": response.url,
                    "opinions_data": opinions,
                    "pending_downloads": len(opinions),
                    "completed_downloads": 0,
                    "downloaded_paths": {},
                }

                first_url = opinions[0]["download_url"]
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

        # Move to next court if this was the last date
        if is_last_date and remaining_coa_codes:
            yield from self._yield_next_court_request(
                remaining_coa_codes, sc_requested, date_gte_str, date_lte_str
            )

    def _extract_case_name_from_text(
        self, text: str, case_number: str
    ) -> str | None:
        """Extract case/party name from text following case number."""
        # The format is typically: "CASE_NUMBER PARTY_NAME COUNTY"
        # e.g., "WR-82,126-02 MEJIA, CARMEN TRAVIS COUNTY"
        if case_number not in text:
            return None

        # Find text after case number
        idx = text.find(case_number)
        if idx == -1:
            return None

        after_case = text[idx + len(case_number) :].strip()

        # Look for county pattern to find end of name
        county_match = re.search(r"\s+[A-Z]+\s+COUNTY", after_case)
        if county_match:
            name = after_case[: county_match.start()].strip()
        else:
            # Take first part before any obvious separators
            name = after_case.split("\n")[0].strip()

        return name if name else None

    def _extract_county_from_text(self, text: str) -> str | None:
        """Extract county name from text."""
        # Look for pattern like "TRAVIS COUNTY" or "FROM HARRIS COUNTY"
        match = re.search(
            r"(?:FROM\s+)?([A-Z][A-Z\s]+)\s+COUNTY", text, re.IGNORECASE
        )
        if match:
            return match.group(1).strip().title()
        return None

    def _find_category_for_case(self, case_link) -> str | None:
        """Find the category header preceding this case link."""
        # Walk up and back through siblings to find category text
        current = case_link.getparent()
        while current is not None:
            prev = current.getprevious()
            while prev is not None:
                text = prev.text_content().strip()
                # Categories end with ":"
                if text.endswith(":") and len(text) > 10:
                    return text.rstrip(":")
                prev = prev.getprevious()
            current = current.getparent()
        return None

    def _determine_opinion_type(self, text: str) -> str:
        """Determine opinion type from surrounding text."""
        text_upper = text.upper()
        if "CONCURRING" in text_upper and "DISSENTING" in text_upper:
            return "concurrence_dissent"
        if "DISSENT" in text_upper:
            return "dissent"
        if "CONCUR" in text_upper:
            return "concurrence"
        if "PER CURIAM" in text_upper:
            return "per_curiam"
        if "ORDER" in text_upper:
            return "order"
        return "opinion"

    def _extract_author(self, text: str) -> str | None:
        """Extract author name from text like 'JUDGE FINLEY' or 'Justice Devine'."""
        match = re.search(
            r"(?:JUDGE|JUSTICE|CHIEF JUSTICE)\s+([A-Z][A-Za-z\-\']+)",
            text,
            re.IGNORECASE,
        )
        if match:
            return match.group(0).strip()
        return None

    # =========================================================================
    # COA Calendar Parsing
    # =========================================================================

    @step(xsd="xsds/parse_coa_calendar.xsd")
    def parse_coa_calendar(
        self,
        lxml_tree: CheckedHtmlElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[TexasOpinionCluster], None, None]:
        """Parse a COA Released Orders/Opinions calendar page."""
        court_code = accumulated_data.get("court_code", "coa01")
        date_gte_str = accumulated_data.get("date_gte")
        date_lte_str = accumulated_data.get("date_lte")
        remaining_coa_codes = accumulated_data.get("remaining_coa_codes", [])
        sc_requested = accumulated_data.get("sc_requested", False)

        date_gte = date.fromisoformat(date_gte_str) if date_gte_str else None
        date_lte = date.fromisoformat(date_lte_str) if date_lte_str else None

        court_num = int(court_code[3:])

        # Find all handdown date links
        # COA uses Docket.aspx instead of handdown.aspx
        date_links = lxml_tree.xpath(
            f"//table//a[contains(@href, 'Docket.aspx') and contains(@href, 'coa{court_num:02d}')]"
        )

        handdown_dates = []
        for link in date_links:
            href = link.get("href", "")
            link_text = link.text_content().strip()

            date_match = self.DATE_PATTERN.search(link_text)
            if date_match:
                parsed_date = self._parse_date(date_match.group(1))
                if parsed_date:
                    if date_gte and parsed_date < date_gte:
                        continue
                    if date_lte and parsed_date > date_lte:
                        continue
                    handdown_dates.append(
                        (parsed_date, urljoin(response.url, href))
                    )

        # Yield requests for each handdown date
        for i, (handdown_date, handdown_url) in enumerate(handdown_dates):
            is_last = i == len(handdown_dates) - 1
            yield NavigatingRequest(
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url=handdown_url,
                ),
                continuation=self.parse_coa_handdown,
                accumulated_data={
                    "court_code": court_code,
                    "handdown_date": handdown_date.isoformat(),
                    "is_last_date": is_last,
                    "remaining_coa_codes": remaining_coa_codes
                    if is_last
                    else [],
                    "sc_requested": sc_requested if is_last else False,
                    "date_gte": date_gte_str,
                    "date_lte": date_lte_str,
                },
            )

        # If no dates found, move to next court
        if not handdown_dates and remaining_coa_codes:
            yield from self._yield_next_court_request(
                remaining_coa_codes, sc_requested, date_gte_str, date_lte_str
            )

    # =========================================================================
    # COA Handdown Page Parsing
    # =========================================================================

    @step(xsd="xsds/parse_coa_handdown.xsd")
    def parse_coa_handdown(
        self,
        lxml_tree: CheckedHtmlElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[TexasOpinionCluster], None, None]:
        """Parse a COA Released Opinions page.

        The COA handdown page has a table structure with columns:
        - Case Number
        - Style (case name + lower court info)
        - Disposition
        - Judges
        """
        court_code = accumulated_data.get("court_code", "coa01")
        handdown_date_str = accumulated_data.get("handdown_date")
        is_last_date = accumulated_data.get("is_last_date", False)
        remaining_coa_codes = accumulated_data.get("remaining_coa_codes", [])
        sc_requested = accumulated_data.get("sc_requested", False)
        date_gte_str = accumulated_data.get("date_gte")
        date_lte_str = accumulated_data.get("date_lte")

        handdown_date = (
            date.fromisoformat(handdown_date_str)
            if handdown_date_str
            else None
        )

        court_id = COURT_CODE_TO_ID.get(court_code, "texapp")
        court_name = COURT_CODE_NAMES.get(court_code, "Texas Court of Appeals")

        # Find all result tables (Civil Causes Decided, Civil Orders, etc.)
        tables = lxml_tree.xpath(
            "//table[.//th[contains(text(), 'Case Number')]]"
        )

        for table in tables:
            # Determine case type from section heading
            # Look for preceding h3 heading
            heading = table.xpath(
                "preceding-sibling::*[self::h3 or self::div[contains(@class, 'heading')]][1]"
            )
            section_name = heading[0].text_content().strip() if heading else ""
            case_type = "civil" if "Civil" in section_name else "criminal"

            # Find all data rows (rows with case links)
            rows = table.xpath(".//tr[td//a[contains(@href, 'Case.aspx')]]")

            for row in rows:
                cells = row.xpath("./td")
                if len(cells) < 3:
                    continue

                # Cell 0: Case Number and PDF links
                case_cell = cells[0]
                case_links = case_cell.xpath(
                    ".//a[contains(@href, 'Case.aspx')]"
                )
                if not case_links:
                    continue

                case_number = case_links[0].text_content().strip()

                # Find PDF links in the case cell
                pdf_links = case_cell.xpath(
                    ".//a[contains(@href, 'SearchMedia.aspx')]"
                )

                # Cell 1: Style (case name + lower court)
                style_cell = cells[1]
                style_text = style_cell.text_content()
                case_name, lower_court, county = self._parse_coa_style(
                    style_text
                )

                # Cell 2: Disposition
                disposition = (
                    cells[2].text_content().strip() if len(cells) > 2 else None
                )

                # Cell 3: Judges
                judges_text = cells[3].text_content() if len(cells) > 3 else ""
                judges = self._parse_judges(judges_text)

                # Extract opinion info from case cell
                opinions = []
                # Get all text nodes and links to understand opinion types
                opinion_rows = case_cell.xpath(".//table//tr")
                for op_row in opinion_rows:
                    op_text = op_row.text_content().strip()
                    op_pdfs = op_row.xpath(
                        ".//a[contains(@href, 'SearchMedia.aspx')]"
                    )
                    for pdf in op_pdfs:
                        pdf_url = urljoin(response.url, pdf.get("href", ""))
                        opinion_type = self._determine_coa_opinion_type(
                            op_text
                        )
                        author = self._extract_coa_author(op_text)
                        opinions.append(
                            {
                                "download_url": pdf_url,
                                "type": opinion_type,
                                "author": author,
                                "published": "Memorandum" not in op_text,
                            }
                        )

                if not opinions and pdf_links:
                    # Fallback: just get any PDF links
                    for pdf_link in pdf_links:
                        pdf_url = urljoin(
                            response.url, pdf_link.get("href", "")
                        )
                        opinions.append(
                            {
                                "download_url": pdf_url,
                                "type": "opinion",
                                "author": judges[0] if judges else None,
                                "published": True,
                            }
                        )

                if not opinions:
                    # Orders without PDFs
                    cluster = TexasOpinionCluster(
                        court_id=court_id,
                        court_code=court_code,
                        court_name=court_name,
                        case_name=case_name or case_number,
                        docket_number=case_number,
                        date_decided=handdown_date,
                        disposition=disposition,
                        judges=judges,
                        lower_court=lower_court,
                        county=county,
                        case_type=case_type,
                        source_url=response.url,
                        opinions=[],
                    )
                    yield ParsedData(cluster)
                else:
                    cluster_data: dict[str, Any] = {
                        "court_id": court_id,
                        "court_code": court_code,
                        "court_name": court_name,
                        "case_name": case_name or case_number,
                        "docket_number": case_number,
                        "date_decided": handdown_date.isoformat()
                        if handdown_date
                        else None,
                        "disposition": disposition,
                        "judges": judges,
                        "lower_court": lower_court,
                        "county": county,
                        "case_type": case_type,
                        "source_url": response.url,
                        "opinions_data": opinions,
                        "pending_downloads": len(opinions),
                        "completed_downloads": 0,
                        "downloaded_paths": {},
                    }

                    first_url = opinions[0]["download_url"]
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

        # Move to next court if this was the last date
        if is_last_date and remaining_coa_codes:
            yield from self._yield_next_court_request(
                remaining_coa_codes, sc_requested, date_gte_str, date_lte_str
            )

    def _parse_coa_style(
        self, style_text: str
    ) -> tuple[str | None, str | None, str | None]:
        """Parse COA style cell into case name, lower court, and county.

        Format: "Party v. Party\nAppeal from Nth District Court of County County"
        """
        lines = [
            line.strip()
            for line in style_text.strip().split("\n")
            if line.strip()
        ]
        case_name = lines[0] if lines else None

        lower_court = None
        county = None
        if len(lines) > 1:
            appeal_line = lines[1]
            lower_court = appeal_line
            # Extract county
            county_match = re.search(
                r"(?:of|from)\s+([A-Za-z\s]+?)(?:\s+County)?$",
                appeal_line,
                re.IGNORECASE,
            )
            if county_match:
                county = county_match.group(1).strip()

        return case_name, lower_court, county

    def _parse_judges(self, judges_text: str) -> list[str]:
        """Parse judges from text, typically separated by newlines."""
        judges = []
        for line in judges_text.split("\n"):
            judge = line.strip()
            if judge and ("Justice" in judge or "Chief Justice" in judge):
                judges.append(judge)
        return judges

    def _determine_coa_opinion_type(self, text: str) -> str:
        """Determine opinion type from COA opinion text."""
        text_lower = text.lower()
        if "concurring" in text_lower and "dissenting" in text_lower:
            return "concurrence_dissent"
        if "dissent" in text_lower:
            return "dissent"
        if "concur" in text_lower:
            return "concurrence"
        if "per curiam" in text_lower:
            return "per_curiam"
        if "order" in text_lower:
            return "order"
        if "memorandum" in text_lower:
            return "memorandum"
        return "opinion"

    def _extract_coa_author(self, text: str) -> str | None:
        """Extract author from COA opinion text like 'by Justice Smith'."""
        match = re.search(
            r"by\s+((?:Chief\s+)?Justice\s+[A-Za-z\-\']+)", text, re.IGNORECASE
        )
        if match:
            return match.group(1).strip()
        return None

    # =========================================================================
    # PDF Download Handling
    # =========================================================================

    @step
    def handle_opinion_download(
        self,
        response: ArchiveResponse,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[TexasOpinionCluster], None, None]:
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
            # Download next PDF
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
    ) -> Generator[ScraperYield[TexasOpinionCluster], None, None]:
        """Build and yield the final OpinionCluster with all PDFs downloaded."""
        opinions = []
        for i, op_data in enumerate(accumulated_data["opinions_data"]):
            local_path = accumulated_data["downloaded_paths"].get(i)
            opinions.append(
                TexasOpinion(
                    download_url=op_data["download_url"],
                    type=op_data.get("type", "opinion"),
                    local_path=local_path,
                    author=op_data.get("author"),
                    published=op_data.get("published", True),
                )
            )

        date_decided = None
        if accumulated_data.get("date_decided"):
            date_decided = date.fromisoformat(accumulated_data["date_decided"])

        cluster = TexasOpinionCluster(
            court_id=accumulated_data["court_id"],
            court_code=accumulated_data.get("court_code"),
            court_name=accumulated_data.get("court_name"),
            case_name=accumulated_data["case_name"],
            docket_number=accumulated_data["docket_number"],
            date_decided=date_decided,
            disposition=accumulated_data.get("disposition"),
            judges=accumulated_data.get("judges", []),
            author=opinions[0].author if opinions else None,
            lower_court=accumulated_data.get("lower_court"),
            county=accumulated_data.get("county"),
            case_type=accumulated_data.get("case_type"),
            category=accumulated_data.get("category"),
            opinions=opinions,
            source_url=accumulated_data.get("source_url"),
        )

        yield ParsedData(cluster)

    # =========================================================================
    # Helper Methods
    # =========================================================================

    def _yield_next_court_request(
        self,
        remaining_coa_codes: list[str],
        sc_requested: bool,
        date_gte_str: str | None,
        date_lte_str: str | None,
    ) -> Generator[NavigatingRequest, None, None]:
        """Yield a request for the next court to process."""
        if remaining_coa_codes:
            next_code = remaining_coa_codes[0]
            court_num = int(next_code[3:])
            yield NavigatingRequest(
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url=self.COA_CALENDAR_URL.format(court_num=court_num),
                ),
                continuation=self.parse_coa_calendar,
                accumulated_data={
                    "court_code": next_code,
                    "remaining_coa_codes": remaining_coa_codes[1:],
                    "sc_requested": sc_requested,
                    "date_gte": date_gte_str,
                    "date_lte": date_lte_str,
                },
            )
        # Supreme Court not yet implemented
