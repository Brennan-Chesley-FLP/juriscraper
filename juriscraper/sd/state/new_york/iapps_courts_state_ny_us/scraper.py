"""NYSCEF Appellate Case Scraper (iapps.courts.state.ny.us).

This module scrapes appellate case data from the New York State Courts
Electronic Filing system (NYSCEF).

Entry points::

    - @entry(NYSCEFCase, speculative=YearlySpeculation(...))
      fetch_case(year, number)

Fetch Case Flow::

    1. fetch_case(year, number) → GET CaseSearch
    2. parse_search_page → fill case number form, submit
    3. parse_search_results → if no table, return (miss);
       extract docketId, basic info → GET CaseDetails
    4. parse_case_detail → extract parties, originating court,
       full caption → GET DocumentList
    5. parse_document_list → extract all documents, yield ParsedData

Design decisions:
- Uses YearlySpeculation since case numbers follow YYYY-NNNNN pattern
- Site returns 403 for plain HTTP; requires PlaywrightDriver
- Three pages per case: SearchResults → CaseDetail → DocumentList
- Documents are not downloaded by default (metadata only); download
  can be added by yielding archive requests for each ViewDocument URL
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING, ClassVar
from urllib.parse import urljoin

from kent.common.decorators import entry, step
from kent.common.page_element import PageElement
from kent.common.speculation_types import YearlySpeculation, YearPartition
from kent.data_types import (
    BaseScraper,
    HttpMethod,
    HTTPRequestParams,
    ParsedData,
    Request,
    Response,
    ScraperStatus,
)
from pyrate_limiter import Duration, Rate

from .models import (
    NYSCEFAttorneyRep,
    NYSCEFCase,
    NYSCEFDocument,
    NYSCEFParty,
)

if TYPE_CHECKING:
    from collections.abc import Generator

    from kent.data_types import ScraperYield

# Base URL
NYSCEF_BASE = "https://iapps.courts.state.ny.us/nyscef"
CASE_SEARCH_URL = f"{NYSCEF_BASE}/CaseSearch"

# Form selector
SEARCH_FORM = "//form[@id='form']"


class NYSCEFScraper(BaseScraper[NYSCEFCase]):
    """Scraper for NYSCEF appellate case data.

    NYSCEF (iapps.courts.state.ny.us/nyscef) hosts electronic filing
    records for New York State courts including all four Appellate
    Division departments. Case numbers follow a YYYY-NNNNN pattern.

    The site returns 403 for non-browser requests, requiring
    PlaywrightDriver for all interactions.
    """

    # === Metadata ===
    court_ids: ClassVar[set[str]] = {
        "nyappd1",
        "nyappd2",
        "nyappd3",
        "nyappd4",
    }
    court_url: ClassVar[str] = NYSCEF_BASE
    data_types: ClassVar[set[str]] = {"dockets"}
    status: ClassVar[ScraperStatus] = ScraperStatus.IN_DEVELOPMENT
    version: ClassVar[str] = "2026-03-02"
    requires_auth: ClassVar[bool] = False

    rate_limits: ClassVar[list[Rate] | None] = [Rate(1, Duration.SECOND * 2)]

    # =================================================================
    # Entry Point
    # =================================================================

    @entry(
        NYSCEFCase,
        speculative=YearlySpeculation(
            backfill=(
                YearPartition(year=2024, number=(1, 5000), frozen=True),
                YearPartition(year=2025, number=(1, 5000), frozen=False),
            ),
            trailing_period=timedelta(days=90),
            largest_observed_gap=20,
        ),
    )
    def fetch_case(self, year: int, number: int) -> Request:
        """Fetch a single NYSCEF case by year and sequence number.

        Constructs case number as YYYY-NNNNN and searches NYSCEF.
        """
        case_number = f"{year}-{number:05d}"
        return Request(
            request=HTTPRequestParams(
                method=HttpMethod.GET,
                url=CASE_SEARCH_URL,
            ),
            continuation=self.parse_search_page,
            accumulated_data={"case_number": case_number},
            is_speculative=True,
        )

    # =================================================================
    # Step 1: Fill search form
    # =================================================================

    @step()
    def parse_search_page(
        self,
        page: PageElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[NYSCEFCase], None, None]:
        """Fill in case number on the search form and submit."""
        case_number = accumulated_data["case_number"]

        form = page.find_form(SEARCH_FORM, "case search form")
        yield form.submit(
            data={"txtCaseIdentifierNumber": case_number},
            continuation=self.parse_search_results,
            accumulated_data=accumulated_data,
            is_speculative=True,
        )

    # =================================================================
    # Step 2: Parse search results
    # =================================================================

    @step(xsd="xsds/search_results.xsd")
    def parse_search_results(
        self,
        page: PageElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[NYSCEFCase], None, None]:
        """Parse search results table.

        If no results table is present, this is a speculative miss.
        If results exist, extract basic info and navigate to Case Detail.
        """
        # Results are in table.NewSearchResults
        rows = page.query_selector_all(
            "//table[contains(@class, 'NewSearchResults')]//tr[position()>1]"
        )
        if not rows:
            # No results — speculative miss
            return

        # Parse first result row (case number search should return one)
        row = rows[0]
        cells = row.query_selector_all("td")
        if len(cells) < 4:
            return

        # Cell 0: case # (link) + received date
        case_link = cells[0].query_selector("a")
        if not case_link:
            return

        link_href = case_link.get_attribute("href")
        case_number_text = case_link.text_content().strip()

        # Extract received date from cell text (after the link)
        cell0_text = cells[0].text_content().strip()
        received_date = self._parse_date_from_text(
            cell0_text.replace(case_number_text, "").strip()
        )

        # Cell 1: eFiling Status + Case Status
        cell1_text = cells[1].text_content().strip()
        # The status text may contain both eFiling status and case status
        efiling_status = cell1_text if cell1_text else None

        # Cell 2: Caption
        caption = cells[2].text_content().strip()

        # Cell 3: Court + Case Type
        cell3_texts = [
            t.strip()
            for t in cells[3].text_content().strip().split("\n")
            if t.strip()
        ]
        court = cell3_texts[0] if cell3_texts else ""
        case_type = cell3_texts[1] if len(cell3_texts) > 1 else None

        # Extract docketId from link URL
        docket_id = self._extract_docket_id(link_href)

        # Build case detail URL
        detail_url = urljoin(
            response.url,
            f"CaseDetails?docketId={docket_id}",
        )

        accumulated_data.update(
            {
                "case_number": case_number_text,
                "court": court,
                "docket_id": docket_id,
                "short_caption": caption,
                "case_type": case_type,
                "efiling_status": efiling_status,
                "received_date": received_date,
                "link_href": link_href,
            }
        )

        yield Request(
            request=HTTPRequestParams(
                method=HttpMethod.GET,
                url=detail_url,
            ),
            continuation=self.parse_case_detail,
            accumulated_data=accumulated_data,
        )

    # =================================================================
    # Step 3: Parse case detail
    # =================================================================

    @step(xsd="xsds/case_detail.xsd")
    def parse_case_detail(
        self,
        page: PageElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[NYSCEFCase], None, None]:
        """Parse the Case Detail page for parties and originating court."""
        # Full caption
        caption_el = page.query_selector(
            "//div[contains(@class, 'DataEntry_InnerBox')]"
            "//span[contains(@class, 'DataRow')]"
        )
        if caption_el:
            full_text = caption_el.text_content().strip()
            # Remove "Full Caption" prefix
            full_caption = re.sub(r"^Full\s+Caption\s*", "", full_text).strip()
            accumulated_data["full_caption"] = full_caption

        # Originating court info
        info_div = page.query_selector(
            "//span[@class='Title' and contains(text(), "
            "'Information from Court of Original Instance')]"
            "/following-sibling::div[contains(@class, 'CaseSummary')]"
        )
        if info_div:
            self._parse_originating_court(info_div, accumulated_data)

        # Parties
        parties: list[dict] = []
        party_sections = page.query_selector_all(
            "//div[contains(@class, 'tableHeading')]"
        )
        for section in party_sections:
            group_name = section.text_content().strip()
            if group_name in ("Petitioners", "Respondents"):
                table = section.query_selector("following-sibling::table[1]")
                if table:
                    parties.extend(self._parse_party_table(table, group_name))

        accumulated_data["parties"] = parties

        # Navigate to Document List
        docket_id = accumulated_data["docket_id"]
        doc_list_url = urljoin(
            response.url,
            f"DocumentList?docketId={docket_id}&display=all",
        )

        yield Request(
            request=HTTPRequestParams(
                method=HttpMethod.GET,
                url=doc_list_url,
            ),
            continuation=self.parse_document_list,
            accumulated_data=accumulated_data,
        )

    # =================================================================
    # Step 4: Parse document list
    # =================================================================

    @step(xsd="xsds/document_list.xsd")
    def parse_document_list(
        self,
        page: PageElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[NYSCEFCase], None, None]:
        """Parse the Document List page and emit final NYSCEFCase."""
        documents: list[dict] = []

        rows = page.query_selector_all(
            "//table[contains(@summary, 'all documents')]//tr[position()>1]"
        )

        for row in rows:
            cells = row.query_selector_all("td")
            if len(cells) < 4:
                continue

            # Cell 0: Document number
            doc_num_text = cells[0].text_content().strip()
            try:
                doc_number = int(doc_num_text)
            except ValueError:
                continue

            # Cell 1: Document type (link) + optional description
            doc_link = cells[1].query_selector("a")
            if doc_link:
                document_type = doc_link.text_content().strip()
                href = doc_link.get_attribute("href")
                download_url = urljoin(response.url, href) if href else None
            else:
                document_type = cells[1].text_content().strip()
                download_url = None

            # Extra description text after the link
            cell1_full = cells[1].text_content().strip()
            description = cell1_full.replace(document_type, "").strip() or None

            # Cell 2: Filed By + dates
            cell2_text = cells[2].text_content().strip()
            filed_by, filed_date, received_date = self._parse_filed_by_cell(
                cell2_text
            )

            # Cell 3: Status
            status_el = cells[3].query_selector("strong")
            status = status_el.text_content().strip() if status_el else None

            documents.append(
                {
                    "doc_number": doc_number,
                    "document_type": document_type,
                    "description": description,
                    "filed_by": filed_by,
                    "filed_date": filed_date,
                    "received_date": received_date,
                    "status": status,
                    "download_url": download_url,
                }
            )

        accumulated_data["documents"] = documents

        # Emit final result
        yield self._build_parsed_data(accumulated_data, response.url)

    # =================================================================
    # Helpers
    # =================================================================

    def _parse_date_from_text(self, text: str) -> date | None:
        """Parse MM/DD/YYYY date from text."""
        match = re.search(r"(\d{1,2}/\d{1,2}/\d{4})", text)
        if match:
            try:
                return datetime.strptime(match.group(1), "%m/%d/%Y").date()
            except ValueError:
                pass
        return None

    def _extract_docket_id(self, href: str) -> str:
        """Extract docketId parameter from a URL."""
        match = re.search(r"docketId=([^&]+)", href)
        return match.group(1) if match else ""

    def _parse_originating_court(
        self, info_div: PageElement, accumulated_data: dict
    ) -> None:
        """Parse originating court info from the CaseSummary div."""
        text = info_div.text_content()

        # Index/Court
        index_link = info_div.query_selector("a")
        if index_link:
            accumulated_data["originating_court_index"] = (
                index_link.text_content().strip()
            )

        # Court name (in <strong> after the link)
        strong_els = info_div.query_selector_all("strong")
        for el in strong_els:
            el_text = el.text_content().strip()
            # First strong after Index/Court is the court name
            if el_text and ":" not in el_text and "/" not in el_text:
                # Check context
                pass

        # Parse labeled fields via regex on the full text
        label_patterns = {
            "originating_court_name": r"Index/Court:.*?-\s*(.*?)(?:\n|Judge:|$)",
            "originating_court_judge": r"Judge:\s*(.*?)(?:\n|Order|$)",
            "order_appealing_from_date": r"Order Appealing From Date:\s*(\d{1,2}/\d{1,2}/\d{4})",
            "notice_of_appeal_date": r"Notice of Appeal Date:\s*(\d{1,2}/\d{1,2}/\d{4})",
            "order_entered_date": r"Order Entered Date:\s*(\d{1,2}/\d{1,2}/\d{4})",
            "notice_of_appeal_filed_date": r"Notice of Appeal Filed Date:\s*(\d{1,2}/\d{1,2}/\d{4})",
            "requested_argument_time": r"Requested Argument Time:\s*(.*?)$",
        }

        for field, pattern in label_patterns.items():
            match = re.search(pattern, text, re.MULTILINE)
            if match:
                value = match.group(1).strip()
                if (
                    "date" in field.lower()
                    and field != "requested_argument_time"
                ):
                    accumulated_data[field] = self._parse_date_from_text(value)
                else:
                    accumulated_data[field] = value

    def _parse_party_table(
        self, table: PageElement, group_name: str
    ) -> list[dict]:
        """Parse a party table (Petitioners or Respondents)."""
        parties: list[dict] = []
        rows = table.query_selector_all("//tbody/tr")

        for row in rows:
            cells = row.query_selector_all("td")
            if len(cells) < 2:
                continue

            # Cell 0: "Party Name , Role"
            name_text = cells[0].text_content().strip()
            name, role = self._parse_party_name_role(name_text)

            # Cell 1: Attorney representations
            rep_text = cells[1].text_content().strip()
            attorneys = self._parse_attorney_reps(rep_text)

            parties.append(
                {
                    "name": name,
                    "role": role,
                    "party_group": group_name,
                    "attorneys": attorneys,
                }
            )

        return parties

    def _parse_party_name_role(self, text: str) -> tuple[str, str]:
        """Parse 'Party Name , Role' into (name, role).

        Examples:
            'Melissa Fawer , Appellant' → ('Melissa Fawer', 'Appellant')
            'AC 31, LLC , Respondent' → ('AC 31, LLC', 'Respondent')
        """
        # Role is after the LAST comma-space-word pattern
        # Known roles: Appellant, Respondent, Petitioner, Mailing Party
        role_pattern = re.compile(
            r",\s*(Appellant|Respondent|Petitioner|Intervenor|"
            r"Mailing Party|Amicus Curiae)\s*$"
        )
        match = role_pattern.search(text)
        if match:
            role = match.group(1).strip()
            name = text[: match.start()].strip()
            return name, role
        return text.strip(), ""

    def _parse_attorney_reps(self, text: str) -> list[dict]:
        """Parse attorney representation text into structured records.

        Text format:
            ATTORNEY_NAME on MM/DD/YYYY
            Firm Name

            ATTORNEY_NAME on MM/DD/YYYY
            Firm Name
        """
        attorneys: list[dict] = []
        if not text or text == "none recorded":
            return attorneys

        # Split into blocks by double-newline or the "on MM/DD/YYYY" pattern
        blocks = re.split(r"\n\s*\n", text)

        for block in blocks:
            block = block.strip()
            if not block:
                continue

            # Pattern: "ATTORNEY_NAME on MM/DD/YYYY\nFirm Name"
            match = re.match(
                r"(.+?)\s+on\s+(\d{1,2}/\d{1,2}/\d{4})\s*(.*)",
                block,
                re.DOTALL,
            )
            if match:
                attorney_name = match.group(1).strip()
                consent_date = self._parse_date_from_text(match.group(2))
                firm = match.group(3).strip() or None
                attorneys.append(
                    {
                        "attorney_name": attorney_name,
                        "firm": firm,
                        "consent_date": consent_date,
                    }
                )
            else:
                # Fallback: just a name
                attorneys.append(
                    {
                        "attorney_name": block.split("\n")[0].strip(),
                        "firm": None,
                        "consent_date": None,
                    }
                )

        return attorneys

    def _parse_filed_by_cell(
        self, text: str
    ) -> tuple[str | None, date | None, date | None]:
        """Parse the 'Filed By' cell text.

        Format:
            FILED_BY_NAME
            Filed: MM/DD/YYYY
            Received: MM/DD/YYYY
        """
        lines = [line.strip() for line in text.split("\n") if line.strip()]
        filed_by = lines[0] if lines else None
        filed_date = None
        received_date = None

        for line in lines:
            if line.startswith("Filed:"):
                filed_date = self._parse_date_from_text(line)
            elif line.startswith("Received:"):
                received_date = self._parse_date_from_text(line)

        return filed_by, filed_date, received_date

    def _build_parsed_data(
        self, data: dict, source_url: str
    ) -> ParsedData[NYSCEFCase]:
        """Build final NYSCEFCase from accumulated data."""
        # Build party models
        parties = [
            NYSCEFParty(
                name=p["name"],
                role=p["role"],
                party_group=p["party_group"],
                attorneys=[
                    NYSCEFAttorneyRep(**a) for a in p.get("attorneys", [])
                ],
            )
            for p in data.get("parties", [])
        ]

        # Build document models
        documents = [NYSCEFDocument(**d) for d in data.get("documents", [])]

        case = NYSCEFCase(
            case_number=data["case_number"],
            court=data.get("court", ""),
            docket_id=data.get("docket_id"),
            short_caption=data.get("short_caption"),
            full_caption=data.get("full_caption"),
            case_type=data.get("case_type"),
            efiling_status=data.get("efiling_status"),
            case_status=data.get("case_status"),
            received_date=data.get("received_date"),
            originating_court_index=data.get("originating_court_index"),
            originating_court_name=data.get("originating_court_name"),
            originating_court_judge=data.get("originating_court_judge"),
            order_appealing_from_date=data.get("order_appealing_from_date"),
            notice_of_appeal_date=data.get("notice_of_appeal_date"),
            order_entered_date=data.get("order_entered_date"),
            notice_of_appeal_filed_date=data.get(
                "notice_of_appeal_filed_date"
            ),
            requested_argument_time=data.get("requested_argument_time"),
            parties=parties,
            documents=documents,
            source_url=source_url,
        )

        return ParsedData(data=case)
