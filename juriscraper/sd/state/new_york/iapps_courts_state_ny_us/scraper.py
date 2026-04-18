"""NYSCEF Appellate Case Scraper (iapps.courts.state.ny.us).

This module scrapes appellate case data from the New York State Courts
Electronic Filing system (NYSCEF).

Entry points::

    - @entry(NYSCEFCase)
      fetch_case(year, number)
        Direct lookup by docket number (YYYY-NNNNN).

    - @entry(NYSCEFCase)
      search_by_filing_date(date_range, court)
        Search by filing date range and court.  Issues 9 searches
        (digits 1-9) to cover all case numbers in the range.  Uses
        iapps_internal_docket_id as deduplication_key to avoid
        visiting the same case twice across digit searches.

Fetch Case Flow::

    1. fetch_case(year, number) → GET CaseSearch
    2. parse_search_page → fill case number form, submit
    3. parse_search_results → if no table, return (miss);
       extract docketId, basic info → GET CaseDetails
    4. parse_case_detail → extract parties, originating court,
       full caption → GET DocumentList
    5. parse_document_list → extract all documents, yield ParsedData

Search by Filing Date Flow::

    1. search_by_filing_date(date_range, court) → 9× GET CaseSearch
    2. fill_date_search_form → fill digit/county/dates, submit
    3. parse_date_search_results → for each row, extract docketId,
       yield GET CaseDetails (deduplication_key=docketId)
    4. parse_case_detail → (shared) → GET DocumentList
    5. parse_document_list → (shared) → yield ParsedData

Design decisions:
- Site returns 403 for plain HTTP; requires PlaywrightDriver
- Three pages per case: SearchResults → CaseDetail → DocumentList
- Documents are not downloaded by default (metadata only); download
  can be added by yielding archive requests for each ViewDocument URL
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import TYPE_CHECKING, ClassVar
from urllib.parse import urljoin

from jkent.common.decorators import entry, step
from jkent.common.page_element import PageElement, ViaLink
from jkent.common.param_models import DateRange
from jkent.data_types import (
    BaseScraper,
    DriverRequirement,
    HttpMethod,
    HTTPRequestParams,
    ParsedData,
    Request,
    Response,
    ScraperStatus,
    SkipDeduplicationCheck,
    WaitForLoadState,
    WaitForSelector,
)
from pyrate_limiter import Duration, Rate

from .models import (
    NYSCEFAttorneyRep,
    NYSCEFCase,
    NYSCEFDocketEntry,
    NYSCEFDownloadedDocument,
    NYSCEFParty,
)

_Yield = NYSCEFCase | NYSCEFDownloadedDocument

if TYPE_CHECKING:
    from collections.abc import Generator

    from jkent.data_types import ScraperYield

# Base URL
NYSCEF_BASE = "https://iapps.courts.state.ny.us/nyscef"
CASE_SEARCH_URL = f"{NYSCEF_BASE}/CaseSearch"

# Form selector
SEARCH_FORM = "//form[@id='form']"

# Mapping from court_id to the <select name="txtCounty"> option value
# on the NYSCEF CaseSearch form.
COURT_TO_COUNTY: dict[str, str] = {
    "nyappd1": "95",  # Appellate Division - 1st Dept
    "nyappd2": "96",  # Appellate Division - 2nd Dept
    "nyappd3": "97",  # Appellate Division - 3rd Dept
    "nyappd4": "98",  # Appellate Division - 4th Dept
    "nysctcl": "99",  # NYS Court of Claims
}


class NYSCEFScraper(BaseScraper[_Yield]):
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
        "nysctcl",
    }
    court_url: ClassVar[str] = NYSCEF_BASE
    data_types: ClassVar[set[str]] = {"dockets"}
    status: ClassVar[ScraperStatus] = ScraperStatus.IN_DEVELOPMENT
    version: ClassVar[str] = "2026-03-02"
    requires_auth: ClassVar[bool] = False
    driver_requirements: ClassVar[list[DriverRequirement]] = [
        DriverRequirement.JS_EVAL,
        DriverRequirement.FF_ALIKE,
        DriverRequirement.HCAP_HANDLER,
    ]

    rate_limits: ClassVar[list[Rate] | None] = [Rate(2, Duration.SECOND)]

    # =================================================================
    # Entry Point: fetch_case (direct lookup by docket number)
    # =================================================================

    @entry(NYSCEFCase)
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
        )

    # =================================================================
    # Entry Point: search_by_filing_date (date range + court)
    # =================================================================

    @entry(NYSCEFCase)
    def search_by_filing_date(
        self, date_range: DateRange, court: str
    ) -> Generator[Request, None, None]:
        """Search for cases filed within a date range at a given court.

        Issues 9 searches with digits 1-9 as partial case numbers in the
        "Case Number and Year Separated" section, filtered by court and
        filing date range.  This covers all case numbers since every
        non-zero case number contains at least one digit 1-9.

        Uses iapps_internal_docket_id as deduplication_key so that a case
        appearing in multiple digit searches is only visited once.
        """
        county_value = COURT_TO_COUNTY[court]
        start_str = date_range.start.strftime("%m/%d/%Y")
        end_str = date_range.end.strftime("%m/%d/%Y")

        for digit in range(1, 10):
            yield Request(
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url=CASE_SEARCH_URL,
                ),
                continuation=self.fill_date_search_form,
                accumulated_data={
                    "digit": str(digit),
                    "county_value": county_value,
                    "start_date": start_str,
                    "end_date": end_str,
                },
                deduplication_key=SkipDeduplicationCheck(),
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
    ) -> Generator[ScraperYield[_Yield], None, None]:
        """Fill in case number on the search form and submit."""
        case_number = accumulated_data["case_number"]

        form = page.find_form(SEARCH_FORM, "case search form")
        yield form.submit(
            data={"txtCaseIdentifierNumber": case_number},
            continuation=self.parse_search_results,
            accumulated_data=accumulated_data,
        )

    # =================================================================
    # Step 1b: Fill date search form (search_by_filing_date flow)
    # =================================================================

    @step()
    def fill_date_search_form(
        self,
        page: PageElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[_Yield], None, None]:
        """Fill the date-based search form and submit.

        Uses the "Case Number and Year Separated" section with a single
        digit, combined with the county and filing date filters under
        "Narrow Your Results".
        """
        form = page.find_form(SEARCH_FORM, "case search form")
        yield form.submit(
            data={
                "txtIndexNumber": accumulated_data["digit"],
                "txtCounty": accumulated_data["county_value"],
                "txtFilingDateFrom": accumulated_data["start_date"],
                "txtFilingDateTo": accumulated_data["end_date"],
            },
            submit_selector="(//button[@name='btnSubmit'])[2]",
            continuation=self.parse_date_search_results,
            accumulated_data=accumulated_data,
            deduplication_key=SkipDeduplicationCheck(),
        )

    # =================================================================
    # Step 1c: Parse date search results (search_by_filing_date flow)
    # =================================================================

    @step(
        xsd="xsds/search_results.xsd",
        await_list=[
            WaitForLoadState("networkidle", timeout=30000),
            WaitForSelector(
                "div.h-captcha, table.NewSearchResults",
                timeout=15000,
            ),
        ],
    )
    def parse_date_search_results(
        self,
        page: PageElement,
        response: Response,
    ) -> Generator[ScraperYield[_Yield], None, None]:
        """Parse date search results and yield a request per case.

        Iterates every row in the results table and navigates to
        CaseDetails for each.  The docketId is used as deduplication_key
        so overlapping digit searches skip already-seen cases.
        """

        rows = page.query_xpath(
            "//table[contains(@class, 'NewSearchResults')]//tr[position()>1]",
            "search result rows",
            min_count=0,
        )

        for row in rows:
            cells = row.query_xpath(".//td", "row cells", min_count=0)
            if len(cells) < 4:
                continue

            # Cell 0: case # (link) + received date
            case_links = cells[0].query_xpath(
                ".//a", "case link", min_count=0, max_count=1
            )
            if not case_links:
                continue
            case_link = case_links[0]

            link_href = case_link.get_attribute("href")
            case_number_text = case_link.text_content().strip()

            cell0_text = cells[0].text_content().strip()
            received_date = self._parse_date_from_text(
                cell0_text.replace(case_number_text, "").strip()
            )

            # Cell 1: eFiling Status
            efiling_status = cells[1].text_content().strip() or None

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

            detail_url = urljoin(
                response.url,
                f"CaseDetails?docketId={docket_id}",
            )

            yield Request(
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url=detail_url,
                ),
                continuation=self.parse_case_detail,
                accumulated_data={
                    "case_number": case_number_text,
                    "court": court,
                    "iapps_internal_docket_id": docket_id,
                    "short_caption": caption,
                    "case_type": case_type,
                    "efiling_status": efiling_status,
                    "received_date": received_date,
                    "link_href": link_href,
                },
                deduplication_key=docket_id,
            )

        # --- Pagination: follow the ">>" (next page) link only ---
        # The ">>" link text is "&gt;&gt;" in HTML, rendered as ">>".
        # Only following "next" avoids re-visiting earlier pages.
        next_links = page.query_xpath(
            "//span[@class='pageNumbers']"
            "//a[@class='pageOff' and contains(text(), '>>')]",
            "next page link",
            min_count=0,
        )
        if next_links:
            href = next_links[0].get_attribute("href")
            if href:
                next_url = urljoin(response.url, href)
                yield Request(
                    request=HTTPRequestParams(
                        method=HttpMethod.GET,
                        url=next_url,
                    ),
                    continuation=self.parse_date_search_results,
                    deduplication_key=SkipDeduplicationCheck(),
                )

    # =================================================================
    # Step 2: Parse search results (fetch_case flow)
    # =================================================================

    @step(xsd="xsds/search_results.xsd")
    def parse_search_results(
        self,
        page: PageElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[_Yield], None, None]:
        """Parse search results table (fetch_case flow).

        If no results table is present, the case number was not found.
        If results exist, extract basic info and navigate to Case Detail.
        """
        # Results are in table.NewSearchResults
        rows = page.query_xpath(
            "//table[contains(@class, 'NewSearchResults')]//tr[position()>1]",
            "search result rows",
            min_count=0,
        )
        if not rows:
            # No results — case number not found
            return

        # Parse first result row (case number search should return one)
        row = rows[0]
        cells = row.query_xpath(".//td", "row cells", min_count=0)
        if len(cells) < 4:
            return

        # Cell 0: case # (link) + received date
        case_links = cells[0].query_xpath(
            ".//a", "case link", min_count=0, max_count=1
        )
        if not case_links:
            return
        case_link = case_links[0]

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
                "iapps_internal_docket_id": docket_id,
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
            deduplication_key=docket_id,
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
    ) -> Generator[ScraperYield[_Yield], None, None]:
        """Parse the Case Detail page for parties and originating court."""
        # Full caption
        caption_els = page.query_xpath(
            "//div[contains(@class, 'DataEntry_InnerBox')]"
            "//span[contains(@class, 'DataRow')]",
            "full caption element",
            min_count=0,
        )
        if caption_els:
            full_text = caption_els[0].text_content().strip()
            # Remove "Full Caption" prefix
            full_caption = re.sub(r"^Full\s+Caption\s*", "", full_text).strip()
            accumulated_data["full_caption"] = full_caption

        # Originating court info
        info_divs = page.query_xpath(
            "//span[@class='Title' and contains(text(), "
            "'Information from Court of Original Instance')]"
            "/following-sibling::div[contains(@class, 'CaseSummary')]",
            "originating court info",
            min_count=0,
            max_count=1,
        )
        if info_divs:
            self._parse_originating_court(info_divs[0], accumulated_data)

        # Parties
        parties: list[dict] = []
        party_sections = page.query_xpath(
            "//div[contains(@class, 'tableHeading')]",
            "party section headings",
            min_count=0,
        )
        for section in party_sections:
            group_name = section.text_content().strip()
            if group_name in ("Petitioners", "Respondents"):
                tables = section.query_xpath(
                    "following-sibling::table[1]",
                    "party table",
                    min_count=0,
                    max_count=1,
                )
                if tables:
                    parties.extend(
                        self._parse_party_table(tables[0], group_name)
                    )

        accumulated_data["parties"] = parties

        # Navigate to Document List
        docket_id = accumulated_data["iapps_internal_docket_id"]
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
    ) -> Generator[ScraperYield[_Yield], None, None]:
        """Parse the Document List page and emit final NYSCEFCase."""
        documents: list[dict] = []

        rows = page.query_xpath(
            "//table[contains(@summary, 'all documents')]//tr[position()>1]",
            "document rows",
            min_count=0,
        )

        for row in rows:
            cells = row.query_xpath(".//td", "document cells", min_count=0)
            if len(cells) < 4:
                continue

            # Cell 0: Document number
            doc_num_text = cells[0].text_content().strip()
            try:
                doc_number = int(doc_num_text)
            except ValueError:
                continue

            # Cell 1: Document type (link) + optional description.
            # Target only ViewDocument links; the cell may also contain
            # an unrelated link (e.g. Redaction notice PDF).
            doc_links = cells[1].query_xpath(
                ".//a[contains(@href, 'ViewDocument')]",
                "document link",
                min_count=0,
                max_count=1,
            )
            if doc_links:
                document_type = doc_links[0].text_content().strip()
                href = doc_links[0].get_attribute("href")
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

            # Cell 3: Status + optional Confirmation Notice link
            status_els = cells[3].query_xpath(
                ".//strong", "status element", min_count=0, max_count=1
            )
            status = (
                status_els[0].text_content().strip() if status_els else None
            )

            confirmation_links = cells[3].query_xpath(
                ".//a[contains(@href, 'ConfirmationNotice')]",
                "confirmation notice link",
                min_count=0,
                max_count=1,
            )
            confirmation_notice_url = None
            if confirmation_links:
                cn_href = confirmation_links[0].get_attribute("href")
                if cn_href:
                    confirmation_notice_url = urljoin(response.url, cn_href)

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
                    "confirmation_notice_url": confirmation_notice_url,
                }
            )

        accumulated_data["documents"] = documents

        # Emit final case result
        yield self._build_parsed_data(accumulated_data, response.url)

        # Yield archive requests for each downloadable document.
        # Each needs a ViaLink so the Playwright driver clicks the <a>
        # on the parent DocumentList page (the site blocks direct GETs).
        docket_id = accumulated_data["iapps_internal_docket_id"]
        for doc in documents:
            # Primary document (ViewDocument link)
            if doc.get("download_url"):
                yield Request(
                    request=HTTPRequestParams(
                        method=HttpMethod.GET,
                        url=doc["download_url"],
                    ),
                    via=ViaLink(
                        selector=f'a[href*="ViewDocument"][href*="{self._extract_doc_index(doc["download_url"])}"]',
                        description=f"document #{doc['doc_number']} download",
                    ),
                    archive=True,
                    expected_type="pdf",
                    continuation=self.handle_document_download,
                    accumulated_data={
                        "iapps_internal_docket_id": docket_id,
                        "doc_number": doc["doc_number"],
                        "document_type": doc["document_type"],
                        "download_url": doc["download_url"],
                    },
                )

            # Confirmation Notice (ConfirmationNotice link in status cell)
            if doc.get("confirmation_notice_url"):
                yield Request(
                    request=HTTPRequestParams(
                        method=HttpMethod.GET,
                        url=doc["confirmation_notice_url"],
                    ),
                    via=ViaLink(
                        selector=f'a[href*="ConfirmationNotice"][href*="{self._extract_doc_index(doc["confirmation_notice_url"])}"]',
                        description=f"confirmation notice #{doc['doc_number']} download",
                    ),
                    archive=True,
                    expected_type="pdf",
                    continuation=self.handle_document_download,
                    accumulated_data={
                        "iapps_internal_docket_id": docket_id,
                        "doc_number": doc["doc_number"],
                        "document_type": "CONFIRMATION NOTICE",
                        "download_url": doc["confirmation_notice_url"],
                    },
                )

    # =================================================================
    # Step 5: Handle document download
    # =================================================================

    @step()
    def handle_document_download(
        self,
        local_filepath: str | None,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[_Yield], None, None]:
        """Handle a downloaded document file.

        Yields an NYSCEFDownloadedDocument with the local path and
        iapps_internal_docket_id so it can be joined with the parent
        NYSCEFCase in post-processing.
        """
        yield ParsedData(
            data=NYSCEFDownloadedDocument(
                iapps_internal_docket_id=accumulated_data[
                    "iapps_internal_docket_id"
                ],
                doc_number=accumulated_data["doc_number"],
                document_type=accumulated_data["document_type"],
                download_url=accumulated_data["download_url"],
                local_path=local_filepath,
            )
        )

    # =================================================================
    # Helpers
    # =================================================================

    @staticmethod
    def _extract_doc_index(url: str) -> str:
        """Extract the docIndex or docId value from a document URL.

        Works for both ViewDocument?docIndex=... and
        ConfirmationNotice?docId=... URLs.
        """
        match = re.search(r"(?:docIndex|docId)=([^&]+)", url)
        return match.group(1) if match else ""

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
        index_links = info_div.query_xpath(
            ".//a", "index/court link", min_count=0, max_count=1
        )
        if index_links:
            accumulated_data["originating_court_index"] = (
                index_links[0].text_content().strip()
            )

        # Court name (in <strong> after the link)
        strong_els = info_div.query_xpath(
            ".//strong", "strong elements", min_count=0
        )
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
        rows = table.query_xpath(".//tbody/tr", "party rows", min_count=0)

        for row in rows:
            cells = row.query_xpath(".//td", "party cells", min_count=0)
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
        # Role is after the LAST comma-space pattern.
        # Roles may be simple (Appellant) or compound (Plaintiff-Appellant,
        # Defendant-Respondent).
        role_pattern = re.compile(
            r",\s*((?:Plaintiff|Defendant|Third-Party[\s-]?\w*)?-?"
            r"(?:Appellant|Respondent|Petitioner|Intervenor|"
            r"Mailing Party|Amicus Curiae))\s*$"
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
        documents = [NYSCEFDocketEntry(**d) for d in data.get("documents", [])]

        case = NYSCEFCase(
            case_number=data["case_number"],
            court=data.get("court", ""),
            iapps_internal_docket_id=data.get("iapps_internal_docket_id"),
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
