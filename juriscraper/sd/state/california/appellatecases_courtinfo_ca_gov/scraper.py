from __future__ import annotations

import re
from datetime import date
from typing import TYPE_CHECKING, ClassVar
from urllib.parse import parse_qs, urlencode, urlparse

from jkent.common.decorators import entry, step
from jkent.common.exceptions import TransientException
from jkent.common.page_element import PageElement, ViaLink
from jkent.common.param_models import SpeculativeRange
from jkent.data_types import (
    BaseScraper,
    DriverRequirement,
    HttpMethod,
    HTTPRequestParams,
    ParsedData,
    Request,
    Response,
    ScraperStatus,
    WaitForLoadState,
    WaitForSelector,
)
from pyrate_limiter import Duration, Rate

from .models import (
    BASE_URL,
    COURT_CONFIG,
    COURT_IDS,
    CaAppAttorney,
    CaAppBrief,
    CaAppCaseUnavailable,
    CaAppCoaCaseLink,
    CaAppDisposition,
    CaAppDocket,
    CaAppDocketEntry,
    CaAppLowerCourtInfo,
    CaAppOpinionFile,
    CaAppParty,
    CaAppTrialCourtInfo,
)

if TYPE_CHECKING:
    from collections.abc import Generator

    from jkent.data_types import ScraperYield


def _parse_date(text: str) -> date | None:
    """Parse mm/dd/yyyy date string, returning None for empty/invalid."""
    text = text.strip()
    if not text:
        return None
    m = re.match(r"(\d{2})/(\d{2})/(\d{4})", text)
    if not m:
        return None
    return date(int(m.group(3)), int(m.group(1)), int(m.group(2)))


def _clean_text(text: str | None) -> str | None:
    """Strip and return None for empty strings."""
    if text is None:
        return None
    text = text.strip()
    return text if text else None


def _build_tab_url(response_url: str, tab_page: str) -> str:
    """Build a tab URL reusing dist, doc_id, doc_no, and request_token
    from the current case page URL."""
    parsed = urlparse(response_url)
    params = parse_qs(parsed.query)
    query = urlencode(
        {
            "dist": params["dist"][0],
            "doc_id": params["doc_id"][0],
            "doc_no": params["doc_no"][0],
            "request_token": params["request_token"][0],
        }
    )
    base = response_url.rsplit("/", 1)[0]
    return f"{base}/{tab_page}?{query}"


class CaAppScraper(
    BaseScraper[CaAppDocket | CaAppCaseUnavailable | CaAppOpinionFile]
):
    """Scraper for California Appellate Courts Case Information.

    Covers the California Supreme Court and all six Courts of Appeal
    (including three divisions of the Fourth District).

    Site returns 403/JS challenge for plain HTTP; requires PlaywrightDriver.

    Approach: speculative case number enumeration. Each court uses a
    single-letter prefix + 6-digit sequential number. One entry point
    per court prefix navigates to the search page, submits the case
    number, and then scrapes all tabs (Case Summary, Docket, Briefs,
    Disposition, Parties & Attorneys, Trial/Lower Court).
    """

    court_ids: ClassVar[set[str]] = set(COURT_IDS.keys())
    court_url: ClassVar[str] = BASE_URL
    data_types: ClassVar[set[str]] = {"dockets"}
    status: ClassVar[ScraperStatus] = ScraperStatus.IN_DEVELOPMENT
    version: ClassVar[str] = "2026-04-03"
    requires_auth: ClassVar[bool] = False
    rate_limits: ClassVar[list[Rate] | None] = [Rate(3, Duration.SECOND)]
    driver_requirements: ClassVar[list[DriverRequirement]] = [
        DriverRequirement.JS_EVAL,
        DriverRequirement.CHROME_ALIKE,
        DriverRequirement.CFCAP_HANDLER,
    ]

    # ──────────────────────────────────────────────
    # Entry points: one per court prefix
    # ──────────────────────────────────────────────

    # highest_observed=295928, largest_observed_gap=100 (2026-04-03)
    @entry(CaAppDocket)
    def fetch_supreme_court_docket(self, rid: SpeculativeRange) -> Request:
        """Speculative docket fetcher for the California Supreme Court."""
        return self._make_search_request("S", rid.min)

    # highest_observed=175975, largest_observed_gap=100 (2026-04-03)
    @entry(CaAppDocket)
    def fetch_dist1_docket(self, rid: SpeculativeRange) -> Request:
        """Speculative docket fetcher for 1st Appellate District."""
        return self._make_search_request("A", rid.min)

    # highest_observed=343601, largest_observed_gap=100 (2026-04-03)
    @entry(CaAppDocket)
    def fetch_dist2_docket(self, rid: SpeculativeRange) -> Request:
        """Speculative docket fetcher for 2nd Appellate District."""
        return self._make_search_request("B", rid.min)

    # highest_observed=102353, largest_observed_gap=100 (2026-04-03)
    @entry(CaAppDocket)
    def fetch_dist3_docket(self, rid: SpeculativeRange) -> Request:
        """Speculative docket fetcher for 3rd Appellate District."""
        return self._make_search_request("C", rid.min)

    # highest_observed=87818, largest_observed_gap=100 (2026-04-03)
    @entry(CaAppDocket)
    def fetch_dist4d1_docket(self, rid: SpeculativeRange) -> Request:
        """Speculative docket fetcher for 4th Appellate District Div 1."""
        return self._make_search_request("D", rid.min)

    # highest_observed=88098, largest_observed_gap=100 (2026-04-03)
    @entry(CaAppDocket)
    def fetch_dist4d2_docket(self, rid: SpeculativeRange) -> Request:
        """Speculative docket fetcher for 4th Appellate District Div 2."""
        return self._make_search_request("E", rid.min)

    # highest_observed=66312, largest_observed_gap=100 (2026-04-03)
    @entry(CaAppDocket)
    def fetch_dist4d3_docket(self, rid: SpeculativeRange) -> Request:
        """Speculative docket fetcher for 4th Appellate District Div 3."""
        return self._make_search_request("G", rid.min)

    # highest_observed=91244, largest_observed_gap=100 (2026-04-03)
    @entry(CaAppDocket)
    def fetch_dist5_docket(self, rid: SpeculativeRange) -> Request:
        """Speculative docket fetcher for 5th Appellate District."""
        return self._make_search_request("F", rid.min)

    # highest_observed=53901, largest_observed_gap=100 (2026-04-03)
    @entry(CaAppDocket)
    def fetch_dist6_docket(self, rid: SpeculativeRange) -> Request:
        """Speculative docket fetcher for 6th Appellate District."""
        return self._make_search_request("H", rid.min)

    def _make_search_request(self, prefix: str, case_number: int) -> Request:
        """Build a GET request to search by case number.

        Navigates directly to the search results URL with the case number
        as a query parameter, bypassing the search form. The site accepts
        this and redirects to the case detail page (via JS in Playwright).
        This avoids bot protection issues with form POST + cached page replay.
        """
        dist, court_id = COURT_CONFIG[prefix]
        docket_id = f"{prefix}{case_number:06d}"
        search_results_url = (
            f"{BASE_URL}/search/searchResults.cfm"
            f"?dist={dist}&search=number"
            f"&query_caseNumber={docket_id}"
        )
        return Request(
            request=HTTPRequestParams(
                method=HttpMethod.GET,
                url=search_results_url,
            ),
            continuation=self.parse_case_summary,
            hateoas=True,
            accumulated_data={
                "prefix": prefix,
                "dist": dist,
                "court_id": court_id,
                "docket_id": docket_id,
                "is_supreme": prefix == "S",
            },
        )

    # ──────────────────────────────────────────────
    # Step: Parse Case Summary tab
    # ──────────────────────────────────────────────

    @step(
        await_list=[
            # Cloudflare interstitial: wait for site chrome that is only
            # present once CF has cleared and the real ColdFusion document
            # has loaded. #centerColumn is shared across all destination
            # states (single-result mainCaseScreen.cfm, multi-result
            # searchResults.cfm, and Case Not Found) but is absent from the
            # Cloudflare challenge page.
            WaitForSelector("#centerColumn", timeout=60000),
            WaitForLoadState("networkidle", timeout=30000),
            WaitForSelector("button[disabled]", state="hidden", timeout=15000),
        ],
        priority=8,
    )
    def parse_case_summary(
        self,
        page: PageElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield, None, None]:
        """Extract case summary fields, then navigate to docket tab.

        If the page is a "Case Not Found" results page, yields
        CaAppCaseUnavailable instead.
        """
        self._check_transient_errors(page)

        # Detect "Case Not Found" page
        not_found = page.query_xpath(
            "//h4[contains(., 'Case Not Found')]",
            "case not found heading",
            min_count=0,
            max_count=1,
        )
        if not_found:
            yield ParsedData(
                data=CaAppCaseUnavailable(
                    docket_id=accumulated_data["docket_id"],
                    court_id=accumulated_data["court_id"],
                )
            )
            return

        # Detect multi-result search page. The site normally auto-redirects
        # from searchResults.cfm to mainCaseScreen.cfm when a query matches
        # exactly one record. When several rows match the same docket number
        # (typically one CoA case consolidating multiple lower-court
        # matters), the redirect is suppressed and we land on the results
        # table. Group rows by doc_id, then fan out one Request per unique
        # doc_id, carrying that group's trial-court case numbers forward.
        if "searchResults.cfm" in response.url:
            yield from self._fan_out_multi_result(page, accumulated_data)
            return

        accumulated_data["source_url"] = response.url
        is_supreme = accumulated_data["is_supreme"]

        # Extract all email notification subscription URLs
        sub_links = page.find_links(
            "//a[contains(@href, '/email.cfm')]",
            "email notification links",
            min_count=0,
        )
        accumulated_data["subscription_urls"] = [
            link.url for link in sub_links
        ]

        # Build a dict from dt/dd pairs in the definition list
        dts = page.query_xpath(
            "//dl/dt", "summary definition terms", min_count=0
        )
        dds = page.query_xpath(
            "//dl/dd", "summary definition values", min_count=0
        )
        fields: dict[str, str] = {}
        for dt_el, dd_el in zip(dts, dds):
            key = dt_el.text_content().strip().rstrip(":")
            val = dd_el.text_content().strip()
            fields[key] = val

        if is_supreme:
            accumulated_data["case_name"] = fields.get("Case Caption", "")
            accumulated_data["case_type"] = _clean_text(
                fields.get("Case Category")
            )
            # Store dates as strings (accumulated_data must be JSON-serializable)
            accumulated_data["date_filed_str"] = fields.get("Start Date", "")
            accumulated_data["case_status"] = _clean_text(
                fields.get("Case Status")
            )
            accumulated_data["issues"] = _clean_text(fields.get("Issues"))
            accumulated_data["case_citation"] = _clean_text(
                fields.get("Case Citation")
            )
            # Opinion links
            pdf_links = page.query_xpath(
                "//a[contains(@href, '.PDF')]/@href",
                "opinion PDF link",
                min_count=0,
                max_count=1,
            )
            docx_links = page.query_xpath(
                "//a[contains(@href, '.DOCX')]/@href",
                "opinion DOCX link",
                min_count=0,
                max_count=1,
            )
            accumulated_data["opinion_pdf_url"] = (
                pdf_links[0].text_content() if pdf_links else None
            )
            accumulated_data["opinion_docx_url"] = (
                docx_links[0].text_content() if docx_links else None
            )
            # CoA case numbers
            coa_links = page.find_links(
                "//dd//a[starts-with(@href, 'mainCaseScreen')]",
                "CoA case links",
                min_count=0,
            )
            accumulated_data["coa_case_numbers"] = [
                link.text for link in coa_links
            ]
        else:
            accumulated_data["case_name"] = fields.get("Case Caption", "")
            accumulated_data["case_type"] = _clean_text(
                fields.get("Case Type")
            )
            accumulated_data["division"] = _clean_text(fields.get("Division"))
            accumulated_data["date_filed_str"] = fields.get("Filing Date", "")
            accumulated_data["completion_date_str"] = fields.get(
                "Completion Date", ""
            )
            accumulated_data["oral_argument_date"] = _clean_text(
                fields.get("Oral Argument Date/Time")
            )
            # Only fall back to the case-summary "Trial Court Case" field
            # if the multi-result fan-out hasn't already supplied a list.
            if not accumulated_data.get("trial_court_case_numbers"):
                single_tc = _clean_text(fields.get("Trial Court Case"))
                accumulated_data["trial_court_case_numbers"] = (
                    [single_tc] if single_tc else []
                )

        # Archive any opinion files (PDF / DOC / DOCX) linked from this page.
        yield from self._yield_opinion_archives(page, accumulated_data)

        # Navigate to Docket tab
        docket_url = _build_tab_url(response.url, "dockets.cfm")
        yield Request(
            request=HTTPRequestParams(method=HttpMethod.GET, url=docket_url),
            continuation=self.parse_docket,
            accumulated_data=accumulated_data,
        )

    def _yield_opinion_archives(
        self,
        page: PageElement,
        accumulated_data: dict,
    ) -> Generator[Request, None, None]:
        """Yield an archive Request for each opinion file on the case page.

        Both Supreme Court and Courts of Appeal case-summary pages render
        opinion downloads as `<a id="pdf">` / `<a id="doc">` anchors. The
        href filename uses `.PDF` and `.DOC` or `.DOCX` (varies by year).
        Each link becomes one ``CaAppOpinionFile`` via
        ``archive_opinion_file``.
        """
        opinion_links = page.find_links(
            "//a[@id='pdf' or @id='doc']",
            "opinion file links",
            min_count=0,
        )
        for link in opinion_links:
            url = link.url
            m = re.search(r"\.([A-Za-z]{2,4})(?:$|\?)", url)
            ext = m.group(1).lower() if m else "bin"
            yield Request(
                archive=True,
                request=HTTPRequestParams(method=HttpMethod.GET, url=url),
                continuation=self.archive_opinion_file,
                expected_type=ext,
                accumulated_data={
                    "docket_id": accumulated_data["docket_id"],
                    "court_id": accumulated_data["court_id"],
                    "document_type": ext,
                    "source_url": url,
                },
            )

    @step()
    def archive_opinion_file(
        self,
        accumulated_data: dict,
        local_filepath: str | None,
    ) -> Generator[ScraperYield, None, None]:
        """Yield a CaAppOpinionFile referring to the archived opinion file."""
        yield ParsedData(
            data=CaAppOpinionFile(
                docket_id=accumulated_data["docket_id"],
                court_id=accumulated_data["court_id"],
                document_type=accumulated_data["document_type"],
                source_url=accumulated_data["source_url"],
                local_path=local_filepath,
            )
        )

    def _fan_out_multi_result(
        self,
        page: PageElement,
        accumulated_data: dict,
    ) -> Generator[ScraperYield, None, None]:
        """Yield one Request per unique doc_id on a multi-result page.

        Each row's trial-court case number (column 2) is collected into
        the group for its doc_id and stashed on accumulated_data so the
        next ``parse_case_summary`` pass sees them as the authoritative
        list (overriding the singular "Trial Court Case" dt/dd field).
        """
        rows = page.query_xpath(
            "//table//tbody//tr", "multi-result rows", min_count=0
        )
        groups: dict[str, dict] = {}
        for row in rows:
            cells = row.query_xpath("td", "row cells", min_count=0)
            if len(cells) < 2:
                continue
            row_links = row.find_links(
                ".//a[contains(@href, 'mainCaseScreen.cfm')]",
                "row case link",
                min_count=0,
            )
            if not row_links:
                continue
            url = row_links[0].url
            m = re.search(r"doc_id=(\d+)", url)
            if not m:
                continue
            doc_id = m.group(1)
            tc_number = cells[1].text_content().strip()
            group = groups.setdefault(
                doc_id, {"url": url, "trial_court_numbers": []}
            )
            if tc_number and tc_number not in group["trial_court_numbers"]:
                group["trial_court_numbers"].append(tc_number)

        for doc_id, group in groups.items():
            new_data = dict(accumulated_data)
            new_data["trial_court_case_numbers"] = group["trial_court_numbers"]
            yield Request(
                request=HTTPRequestParams(
                    method=HttpMethod.GET, url=group["url"]
                ),
                via=ViaLink(
                    selector=(
                        f'a.btnSmaller[href*="doc_id={doc_id}"]'
                        f'[href*="mainCaseScreen.cfm"]'
                    ),
                    description=f"multi-result case link doc_id={doc_id}",
                ),
                continuation=self.parse_case_summary,
                accumulated_data=new_data,
                deduplication_key=f"parse_case_summary:{doc_id}",
            )

    # ──────────────────────────────────────────────
    # Step: Parse Docket (Register of Actions) tab
    # ──────────────────────────────────────────────

    @step(
        await_list=[
            WaitForLoadState("networkidle", timeout=30000),
            WaitForSelector("button[disabled]", state="hidden", timeout=15000),
        ],
        priority=7,
    )
    def parse_docket(
        self,
        page: PageElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield, None, None]:
        """Extract docket entries, then navigate to briefs tab."""
        self._check_transient_errors(page)

        # Extract division from the docket header if not already set
        if not accumulated_data.get("division"):
            div_texts = page.query_xpath_strings(
                "//div[contains(@class, 'caseInfo')]//text()[contains(., 'Division')]",
                "division text",
                min_count=0,
            )
            for t in div_texts:
                m = re.search(r"Division\s+(\S+)", t)
                if m:
                    accumulated_data["division"] = m.group(1)
                    break

        rows = page.query_xpath(
            "//table//tbody//tr", "docket entry rows", min_count=0
        )
        entries: list[dict] = []
        for row in rows:
            cells = row.query_xpath("td", "row cells", min_count=0)
            if len(cells) >= 2:
                entries.append(
                    {
                        "date_filed_str": cells[0].text_content().strip(),
                        "description": cells[1].text_content().strip(),
                        "notes": (
                            _clean_text(cells[2].text_content())
                            if len(cells) > 2
                            else None
                        ),
                    }
                )
        accumulated_data["entries"] = entries

        # Navigate to Briefs tab
        briefs_url = _build_tab_url(response.url, "briefing.cfm")
        yield Request(
            request=HTTPRequestParams(method=HttpMethod.GET, url=briefs_url),
            continuation=self.parse_briefs,
            accumulated_data=accumulated_data,
        )

    # ──────────────────────────────────────────────
    # Step: Parse Briefs tab
    # ──────────────────────────────────────────────

    @step(
        await_list=[
            WaitForLoadState("networkidle", timeout=30000),
            WaitForSelector("button[disabled]", state="hidden", timeout=15000),
        ],
        priority=6,
    )
    def parse_briefs(
        self,
        page: PageElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield, None, None]:
        """Extract brief records, then navigate to disposition tab."""
        self._check_transient_errors(page)

        rows = page.query_xpath(
            "//table//tbody//tr", "brief rows", min_count=0
        )
        briefs: list[dict] = []
        for row in rows:
            cells = row.query_xpath("td", "brief cells", min_count=0)
            if len(cells) >= 2:
                briefs.append(
                    {
                        "brief_type": cells[0].text_content().strip(),
                        "date_filed_str": cells[1].text_content().strip(),
                        "party_attorney": (
                            _clean_text(cells[2].text_content())
                            if len(cells) > 2
                            else None
                        ),
                        "notes": (
                            _clean_text(cells[3].text_content())
                            if len(cells) > 3
                            else None
                        ),
                    }
                )
        accumulated_data["briefs"] = briefs

        # Navigate to Disposition tab
        dispo_url = _build_tab_url(response.url, "disposition.cfm")
        yield Request(
            request=HTTPRequestParams(method=HttpMethod.GET, url=dispo_url),
            continuation=self.parse_disposition,
            accumulated_data=accumulated_data,
        )

    # ──────────────────────────────────────────────
    # Step: Parse Disposition tab
    # ──────────────────────────────────────────────

    @step(
        await_list=[
            WaitForLoadState("networkidle", timeout=30000),
            WaitForSelector("button[disabled]", state="hidden", timeout=15000),
        ],
        priority=5,
    )
    def parse_disposition(
        self,
        page: PageElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield, None, None]:
        """Extract disposition data. Structure differs SC vs CoA."""
        self._check_transient_errors(page)
        is_supreme = accumulated_data["is_supreme"]
        dispositions: list[dict] = []

        if is_supreme:
            # SC disposition: table with Date and Description columns
            rows = page.query_xpath(
                "//table//tbody//tr", "SC disposition rows", min_count=0
            )
            for row in rows:
                cells = row.query_xpath("td", "dispo cells", min_count=0)
                if len(cells) >= 2:
                    dispositions.append(
                        {
                            "disposition_date_str": cells[0]
                            .text_content()
                            .strip(),
                            "description": cells[1].text_content().strip(),
                        }
                    )
            # Case citation from disposition page
            citation_texts = page.query_xpath_strings(
                "//div[contains(text(), 'Case Citation')]"
                "/following-sibling::div/text()",
                "citation text",
                min_count=0,
            )
            if citation_texts:
                val = _clean_text(citation_texts[0])
                if val and val != "none":
                    accumulated_data["case_citation"] = val
        else:
            # CoA disposition: key-value table with rowheader/cell
            headers = page.query_xpath(
                "//table//th | //table//td[@class='rowheader'] | //table//tr/th",
                "CoA disposition headers",
                min_count=0,
            )
            values = page.query_xpath(
                "//table//td[not(@class='rowheader')]",
                "CoA disposition values",
                min_count=0,
            )
            if headers and values:
                dispo: dict = {}
                for h, v in zip(headers, values):
                    key = h.text_content().strip().rstrip(":")
                    val = v.text_content().strip()
                    if key == "Description":
                        dispo["description"] = val
                    elif key == "Date":
                        dispo["disposition_date_str"] = val
                    elif key == "Disposition Type":
                        dispo["disposition_type"] = _clean_text(val)
                    elif key == "Publication Status":
                        dispo["publication_status"] = _clean_text(val)
                    elif key == "Author":
                        dispo["author"] = _clean_text(val)
                    elif key == "Participants":
                        dispo["participants"] = _clean_text(val)
                    elif key == "Case Citation":
                        citation = _clean_text(val)
                        if citation and citation != "none":
                            dispo["case_citation"] = citation
                            accumulated_data["case_citation"] = citation
                if dispo.get("description"):
                    dispositions.append(dispo)

        accumulated_data["dispositions"] = dispositions

        # Navigate to Parties and Attorneys tab
        parties_url = _build_tab_url(response.url, "partiesAndAttorneys.cfm")
        yield Request(
            request=HTTPRequestParams(method=HttpMethod.GET, url=parties_url),
            continuation=self.parse_parties,
            accumulated_data=accumulated_data,
        )

    # ──────────────────────────────────────────────
    # Step: Parse Parties and Attorneys tab
    # ──────────────────────────────────────────────

    @step(
        await_list=[
            WaitForLoadState("networkidle", timeout=30000),
            WaitForSelector("button[disabled]", state="hidden", timeout=15000),
        ],
        priority=4,
    )
    def parse_parties(
        self,
        page: PageElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield, None, None]:
        """Extract parties and their attorneys."""
        self._check_transient_errors(page)

        rows = page.query_xpath(
            "//table//tbody//tr", "party rows", min_count=0
        )
        parties: list[dict] = []
        for row in rows:
            cells = row.query_xpath("td", "party cells", min_count=0)
            if len(cells) < 2:
                continue

            # Parse party cell: "Name : Role\nAddress lines"
            party_text = cells[0].text_content().strip()
            party_lines = [
                ln.strip() for ln in party_text.split("\n") if ln.strip()
            ]
            name = ""
            role = None
            address_lines: list[str] = []
            if party_lines:
                # First line is "Name : Role" or just "Name"
                first = party_lines[0]
                if " : " in first:
                    name, role = first.split(" : ", 1)
                else:
                    name = first
                address_lines = party_lines[1:]

            # Parse attorney cell: "Name\nFirm\nAddress lines"
            attorney_text = cells[1].text_content().strip()
            attorney_lines = [
                ln.strip() for ln in attorney_text.split("\n") if ln.strip()
            ]
            attorneys: list[dict] = []
            if attorney_lines:
                atty_name = attorney_lines[0]
                atty_firm = (
                    attorney_lines[1] if len(attorney_lines) > 1 else None
                )
                atty_address = (
                    ", ".join(attorney_lines[2:])
                    if len(attorney_lines) > 2
                    else None
                )
                attorneys.append(
                    {
                        "name": atty_name,
                        "firm": atty_firm,
                        "address": atty_address,
                    }
                )

            parties.append(
                {
                    "name": name.strip(),
                    "role": _clean_text(role),
                    "address": (
                        ", ".join(address_lines) if address_lines else None
                    ),
                    "attorneys": attorneys,
                }
            )
        accumulated_data["parties"] = parties

        # Navigate to Trial Court / Lower Court tab
        tab_page = "trialCourt.cfm"  # Same URL for both SC and CoA
        tc_url = _build_tab_url(response.url, tab_page)
        yield Request(
            request=HTTPRequestParams(method=HttpMethod.GET, url=tc_url),
            continuation=self.parse_trial_court,
            accumulated_data=accumulated_data,
        )

    # ──────────────────────────────────────────────
    # Step: Parse Trial Court / Lower Court tab
    # ──────────────────────────────────────────────

    @step(
        await_list=[
            WaitForLoadState("networkidle", timeout=30000),
            WaitForSelector("button[disabled]", state="hidden", timeout=15000),
        ],
        priority=3,
    )
    def parse_trial_court(
        self,
        page: PageElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield, None, None]:
        """Extract trial/lower court info, then assemble the docket."""
        self._check_transient_errors(page)

        is_supreme = accumulated_data["is_supreme"]

        # Build field dict from dt/dd pairs
        dts = page.query_xpath("//dl/dt", "tc definition terms", min_count=0)
        dds = page.query_xpath("//dl/dd", "tc definition values", min_count=0)
        fields: dict[str, str] = {}
        for dt_el, dd_el in zip(dts, dds):
            key = dt_el.text_content().strip().rstrip(":")
            val = dd_el.text_content().strip()
            fields[key] = val

        if is_supreme:
            # SC lower court tabs can have multiple CoA cases and
            # trial courts.  Walk dt/dd pairs in order to collect them.
            coa_cases: list[dict] = []
            trial_courts: list[dict[str, str | None]] = []
            current_district: str | None = None
            current_trial_court: str | None = None

            for dt_el, dd_el in zip(dts, dds):
                key = dt_el.text_content().strip().rstrip(":")
                if key == "Court of Appeal District/Division":
                    current_district = _clean_text(dd_el.text_content())
                elif key == "Court of Appeal Case Number":
                    # The dd contains a link to the CoA case
                    links = dd_el.find_links(
                        ".//a[contains(@href, 'searchResults.cfm')]",
                        "CoA case link",
                        min_count=0,
                    )
                    case_number = links[0].text if links else None
                    case_link = links[0].url if links else None
                    is_lead = "(lead)" in dd_el.text_content()
                    coa_cases.append(
                        {
                            "district_division": current_district,
                            "case_number": case_number,
                            "case_link": case_link,
                            "is_lead": is_lead,
                        }
                    )
                    current_district = None
                elif key == "Trial Court":
                    current_trial_court = _clean_text(dd_el.text_content())
                elif key == "Trial Court Case Number":
                    trial_courts.append(
                        {
                            "name": current_trial_court,
                            "case_number": _clean_text(dd_el.text_content()),
                        }
                    )
                    current_trial_court = None

            accumulated_data["lower_court_info"] = {
                "coa_cases": coa_cases,
                "coa_disposition": _clean_text(fields.get("Disposition")),
                "coa_disposition_date_str": fields.get("Disposition Date", ""),
                "trial_courts": trial_courts,
            }
        else:
            accumulated_data["trial_court_info"] = {
                "trial_court_name": _clean_text(
                    fields.get("Trial Court Name")
                ),
                "county": _clean_text(fields.get("County")),
                "trial_court_case_number": _clean_text(
                    fields.get("Trial Court Case Number")
                ),
                "trial_court_judge": _clean_text(
                    fields.get("Trial Court Judge")
                ),
                "judgment_date_str": fields.get(
                    "Trial Court Judgment Date", ""
                ),
            }

        yield from self._assemble_docket(accumulated_data)

    # ──────────────────────────────────────────────
    # Final assembly
    # ──────────────────────────────────────────────

    def _assemble_docket(
        self, data: dict
    ) -> Generator[ScraperYield, None, None]:
        """Build and yield the final CaAppDocket from accumulated data.

        All dates are stored as strings (``*_str`` keys) in accumulated_data
        for JSON serialization and parsed to ``date`` objects here.
        """
        # Build nested model instances, parsing date strings
        entries = [
            CaAppDocketEntry(
                date_filed=_parse_date(e.get("date_filed_str", "")),
                description=e["description"],
                notes=e.get("notes"),
            )
            for e in data.get("entries", [])
        ]
        briefs = [
            CaAppBrief(
                brief_type=b["brief_type"],
                date_filed=_parse_date(b.get("date_filed_str", "")),
                party_attorney=b.get("party_attorney"),
                notes=b.get("notes"),
            )
            for b in data.get("briefs", [])
        ]
        dispositions = [
            CaAppDisposition(
                description=d["description"],
                disposition_date=_parse_date(
                    d.get("disposition_date_str", "")
                ),
                disposition_type=d.get("disposition_type"),
                publication_status=d.get("publication_status"),
                author=d.get("author"),
                participants=d.get("participants"),
                case_citation=d.get("case_citation"),
            )
            for d in data.get("dispositions", [])
        ]
        parties = [
            CaAppParty(
                name=p["name"],
                role=p.get("role"),
                address=p.get("address"),
                attorneys=[CaAppAttorney(**a) for a in p.get("attorneys", [])],
            )
            for p in data.get("parties", [])
        ]

        trial_court_info = None
        if data.get("trial_court_info"):
            tc = data["trial_court_info"]
            trial_court_info = CaAppTrialCourtInfo(
                trial_court_name=tc.get("trial_court_name"),
                county=tc.get("county"),
                trial_court_case_number=tc.get("trial_court_case_number"),
                trial_court_judge=tc.get("trial_court_judge"),
                judgment_date=_parse_date(tc.get("judgment_date_str", "")),
            )

        lower_court_info = None
        if data.get("lower_court_info"):
            lc = data["lower_court_info"]
            lower_court_info = CaAppLowerCourtInfo(
                coa_cases=[
                    CaAppCoaCaseLink(
                        district_division=c.get("district_division"),
                        case_number=c.get("case_number"),
                        case_link=c.get("case_link"),
                        is_lead=c.get("is_lead", False),
                    )
                    for c in lc.get("coa_cases", [])
                ],
                coa_disposition=lc.get("coa_disposition"),
                coa_disposition_date=_parse_date(
                    lc.get("coa_disposition_date_str", "")
                ),
                trial_courts=lc.get("trial_courts", []),
            )

        docket = CaAppDocket(
            docket_id=data["docket_id"],
            court_id=data["court_id"],
            case_name=data.get("case_name", ""),
            case_type=data.get("case_type"),
            division=data.get("division"),
            date_filed=_parse_date(data.get("date_filed_str", "")),
            completion_date=_parse_date(data.get("completion_date_str", "")),
            case_status=data.get("case_status"),
            oral_argument_date=data.get("oral_argument_date"),
            issues=data.get("issues"),
            case_citation=data.get("case_citation"),
            opinion_pdf_url=data.get("opinion_pdf_url"),
            opinion_docx_url=data.get("opinion_docx_url"),
            coa_case_numbers=data.get("coa_case_numbers", []),
            trial_court_case_numbers=data.get("trial_court_case_numbers", []),
            cross_referenced_cases=data.get("cross_referenced_cases", []),
            entries=entries,
            briefs=briefs,
            dispositions=dispositions,
            parties=parties,
            trial_court_info=trial_court_info,
            lower_court_info=lower_court_info,
            source_url=data.get("source_url"),
            subscription_urls=data.get("subscription_urls", []),
        )
        yield ParsedData(data=docket)

    # ──────────────────────────────────────────────
    # Transient error detection
    # ──────────────────────────────────────────────

    @classmethod
    def _check_transient_errors(cls, page: PageElement) -> None:
        """Raise TransientException for any known transient failure mode.

        Bundles every transient-page detector so each step can guard its
        entry with a single call.
        """
        cls._check_502_bad_gateway(page)
        cls._check_503_challenge(page)
        cls._check_maintenance(page)
        cls._check_loading_spinners(page)

    @staticmethod
    def _check_503_challenge(page: PageElement) -> None:
        """Raise TransientException if the page is an F5 503 challenge."""
        errors = page.query_xpath(
            "//h2[contains(., 'Error 503')]",
            "503 error heading",
            min_count=0,
            max_count=1,
        )
        if errors:
            raise TransientException("F5 503 challenge page")

    @staticmethod
    def _check_502_bad_gateway(page: PageElement) -> None:
        """Raise TransientException if the page is a 502 Bad Gateway."""
        errors = page.query_xpath(
            "//h1[contains(., '502 Bad Gateway')]",
            "502 bad gateway heading",
            min_count=0,
            max_count=1,
        )
        if errors:
            raise TransientException("502 Bad Gateway")

    @staticmethod
    def _check_maintenance(page: PageElement) -> None:
        """Raise TransientException if the site is in a maintenance window.

        During scheduled maintenance the site serves a stub page whose body
        contains ``NOTICE: MAINTENANCE`` in place of the real ColdFusion
        content. The URL bar still shows the requested ``searchResults.cfm``/
        tab URL but all case data is gone, so downstream URL-builders that
        rely on ``doc_id``/``dist`` parameters surface obscure KeyErrors.
        """
        notice = page.query_xpath(
            "//strong[contains(., 'NOTICE: MAINTENANCE')]",
            "maintenance notice",
            min_count=0,
            max_count=1,
        )
        if notice:
            raise TransientException("Site in maintenance window")

    @staticmethod
    def _check_loading_spinners(page: PageElement) -> None:
        """Raise TransientException if spinner buttons are still visible.

        The site uses disabled buttons with "Loading..." text as
        placeholders while JavaScript replaces them with real links.
        Once loaded, JS sets ``style="display: none;"`` on these buttons
        but they remain in the DOM.  Only match spinners that are NOT
        hidden via inline style.
        """
        spinners = page.query_xpath(
            "//button[contains(., 'Loading') and not(contains(@style, 'display: none'))]",
            "visible loading spinner buttons",
            min_count=0,
        )
        if spinners:
            labels = [s.text_content().strip() for s in spinners]
            raise TransientException(
                f"Page still loading (spinners present: {labels})"
            )

    # ──────────────────────────────────────────────
    # Soft-404 detection
    # ──────────────────────────────────────────────

    def fails_successfully(self, response: Response) -> bool:
        """Return False for soft-404 pages.

        The site redirects to the search page with an inputError parameter
        for malformed case numbers. We let "Case Not Found" results pages
        through (return True) so parse_case_summary can yield
        CaAppCaseUnavailable.
        """
        return "inputError" not in response.url


Site = CaAppScraper
