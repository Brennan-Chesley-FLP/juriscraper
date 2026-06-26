"""California Appellate Courts Case Information scraper.

Scrapes docket data for the California Supreme Court and all six Courts of
Appeal (including the three divisions of the Fourth District) from
appellatecases.courtinfo.ca.gov. The site is a ColdFusion app behind an
Imperva/Incapsula JS challenge, so it requires a Playwright driver.

Addressing: speculative case-number enumeration. Every court uses a
single-letter prefix + 6-digit sequential number. A single speculative entry,
``dockets_by_number``, covers all nine courts/divisions; the target court
rides in the speculative param (``CaCourtRange``, a shared ``CourtRange``)
and is seeded once per court. The request navigates to the search-results URL
for one case number; the site redirects to the case-detail page, and the
scraper then walks the tabs:

    parse_case_summary (priority 7) → parse_docket (6) → parse_briefs (5)
      → parse_disposition (4) → parse_parties (3) → parse_trial_court (2)
        → _assemble_docket (emit CaAppDocket)

Opinion files linked off the summary page are downloaded as separate
``CaAppOpinionFile`` records (archive requests, priority 1), joined back to
the docket via ``docket_number`` + ``court``.

Per-page HTML extraction lives in the ``parsers`` package; the steps keep
navigation concerns (tab-URL building, the multi-result fan-out, archive
requests, and transient-page detection).
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, ClassVar
from urllib.parse import parse_qs, urlencode, urlparse

from jkent.common.decorators import entry, step
from jkent.common.exceptions import TransientException
from jkent.common.page_element import PageElement, ViaLink
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
    XPath,
)
from pyrate_limiter import Duration, Rate

from juriscraper.state.common.params import CourtRange

from .models import (
    BASE_URL,
    COURT_CONFIG,
    COURT_IDS,
    CaAppCaseUnavailable,
    CaAppDocket,
    CaAppOpinionFile,
)
from .parsers import (
    BriefsParser,
    CaseSummaryParser,
    DispositionParser,
    DocketEntriesParser,
    PartiesParser,
    TrialCourtParser,
)

if TYPE_CHECKING:
    from collections.abc import Generator

    from jkent.data_types import ScraperYield

_Yield = CaAppDocket | CaAppCaseUnavailable | CaAppOpinionFile

# Speculation seed hints: highest case number observed per court as of
# 2026-04-03 (largest_observed_gap was 100 for every court). Use these as the
# ``min``/``soft_max`` when seeding ``dockets_by_number`` once per court.
SEED_HINTS: dict[str, int] = {
    "cal": 295928,
    "calctapp_1st": 175975,
    "calctapp_2nd": 343601,
    "calctapp_3rd": 102353,
    "calctapp_4th_div1": 87818,
    "calctapp_4th_div2": 88098,
    "calctapp_4th_div3": 66312,
    "calctapp_5th": 91244,
    "calctapp_6th": 53901,
}


class CaCourtRange(CourtRange):
    """``CourtRange`` that maps a CA court id to its case-number prefix.

    California addresses each court/division by a single-letter case-number
    prefix (S/A/B/C/D/E/G/F/H). ``court_id`` carries the CourtListener id (the
    seed key); ``search_key`` translates it to the site prefix via the inverse
    of ``COURT_CONFIG``. ``from_int`` (driver advancement) preserves
    ``court_id`` because it copies via ``model_copy``.
    """

    # CourtListener court id -> case-number prefix (inverse of COURT_CONFIG).
    COURT_PREFIX: ClassVar[dict[str, str]] = {
        court: prefix for prefix, (_dist, court) in COURT_CONFIG.items()
    }

    def search_key(self) -> str:
        return self.COURT_PREFIX[self.court_id]


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


class CaAppScraper(BaseScraper[_Yield]):
    """Scraper for California Appellate Courts Case Information.

    Covers the California Supreme Court and all six Courts of Appeal
    (including three divisions of the Fourth District). The site returns a
    403/JS challenge for plain HTTP, so a Playwright driver is required.
    """

    # === Metadata ===
    court_ids: ClassVar[set[str]] = set(COURT_IDS.keys())
    court_url: ClassVar[str] = BASE_URL
    data_types: ClassVar[set[str]] = {"dockets"}
    status: ClassVar[ScraperStatus] = ScraperStatus.IN_DEVELOPMENT
    version: ClassVar[str] = "2026-06-26"
    last_verified: ClassVar[str] = "2026-04-03"
    requires_auth: ClassVar[bool] = False
    rate_limits: ClassVar[list[Rate] | None] = [Rate(3, Duration.SECOND)]
    driver_requirements: ClassVar[list[DriverRequirement]] = [
        DriverRequirement.JS_EVAL,
        DriverRequirement.CHROME_ALIKE,
        DriverRequirement.CFCAP_HANDLER,
    ]

    # =========================================================================
    # Entry point: one speculative docket-number probe, addressed by court id.
    #
    # A speculative entry is dispatched by the driver with ONLY its
    # speculative param — a separate ``court_ids: set[str]`` argument can't be
    # supplied (see SCRAPER_STANDARDS §4, "Multi-court speculative entries").
    # So the target court rides inside the speculative param: ``CaCourtRange``
    # (a shared ``CourtRange``) carries the CourtListener ``court_id`` and
    # translates it to the site's case-number prefix. Seed once per court; each
    # seed gets its own speculation state, and ``from_int`` preserves
    # ``court_id`` as the driver advances.
    # =========================================================================

    @entry(CaAppDocket)
    def dockets_by_number(self, docket_number: CaCourtRange) -> Request:
        """Speculatively fetch one docket by case number for one court.

        ``docket_number.court_id`` selects the court/division; the driver
        probes ``{prefix}{n:06d}`` for ascending ``n`` and advances until
        ``gap`` consecutive misses. Seed once per court, e.g.::

            seed_params = [
                {"dockets_by_number": {"docket_number":
                    {"court_id": "cal", "min": 295928, "soft_max": 295928, "gap": 100}}},
                {"dockets_by_number": {"docket_number":
                    {"court_id": "calctapp_1st", "min": 175975, "soft_max": 175975, "gap": 100}}},
                # ... one per court; SEED_HINTS lists each highest_observed.
            ]
        """
        return self._make_search_request(
            docket_number.search_key(), docket_number.min
        )

    def _make_search_request(self, prefix: str, case_number: int) -> Request:
        """Build a GET request to search by case number.

        Navigates directly to the search results URL with the case number
        as a query parameter, bypassing the search form. The site accepts
        this and redirects to the case detail page (via JS in Playwright).
        This avoids bot protection issues with form POST + cached page replay.
        """
        dist, court = COURT_CONFIG[prefix]
        docket_number = f"{prefix}{case_number:06d}"
        search_results_url = (
            f"{BASE_URL}/search/searchResults.cfm"
            f"?dist={dist}&search=number"
            f"&query_caseNumber={docket_number}"
        )
        return Request(
            request=HTTPRequestParams(
                method=HttpMethod.GET,
                url=search_results_url,
            ),
            continuation=self.parse_case_summary,
            reseedable=True,
            accumulated_data={
                "prefix": prefix,
                "dist": dist,
                "court": court,
                "docket_number": docket_number,
                "is_supreme": prefix == "S",
                "entry_point": "dockets_by_number",
            },
            deduplication_key=f"parse_case_summary:{docket_number}",
        )

    # =========================================================================
    # Step: Case Summary tab
    # =========================================================================

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
        priority=7,
    )
    def parse_case_summary(
        self,
        page: PageElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[_Yield], None, None]:
        """Extract case summary fields, then navigate to the docket tab.

        If the page is a "Case Not Found" results page, yields
        CaAppCaseUnavailable instead. If it is a multi-result search page,
        fans out one request per unique case.
        """
        self._check_transient_errors(page)

        # Detect "Case Not Found" page.
        not_found = page.query(
            XPath("//h4[contains(., 'Case Not Found')]"),
            "case not found heading",
            min_count=0,
            max_count=1,
        )
        if not_found:
            yield ParsedData(
                data=CaAppCaseUnavailable(
                    docket_number=accumulated_data["docket_number"],
                    court=accumulated_data["court"],
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

        bag = CaseSummaryParser(is_supreme=is_supreme)(page)[0].raw_data

        # Archive any opinion files (PDF / DOC / DOCX) linked from this page.
        yield from self._yield_opinion_archives(
            bag.pop("opinion_file_urls", []), accumulated_data
        )

        # CoA only: fall back to the case-summary "Trial Court Case" field
        # only if the multi-result fan-out hasn't already supplied a list.
        single_tc = bag.pop("trial_court_case_single", None)
        if not accumulated_data.get("trial_court_case_numbers"):
            accumulated_data["trial_court_case_numbers"] = (
                [single_tc] if single_tc else []
            )

        # Merge the remaining (model-field) summary data forward.
        accumulated_data.update(bag)

        # Navigate to the Docket tab.
        docket_url = _build_tab_url(response.url, "dockets.cfm")
        yield Request(
            request=HTTPRequestParams(method=HttpMethod.GET, url=docket_url),
            continuation=self.parse_docket,
            accumulated_data=accumulated_data,
            deduplication_key=(
                f"parse_docket:{accumulated_data['docket_number']}"
            ),
        )

    def _yield_opinion_archives(
        self,
        opinion_file_urls: list[dict],
        accumulated_data: dict,
    ) -> Generator[Request, None, None]:
        """Yield an archive Request for each opinion file on the case page.

        ``opinion_file_urls`` are the ``{"url", "ext"}`` dicts produced by
        ``CaseSummaryParser``. Each becomes one ``CaAppOpinionFile`` via
        ``archive_opinion_file``.
        """
        docket_number = accumulated_data["docket_number"]
        for f in opinion_file_urls:
            url = f["url"]
            ext = f["ext"]
            filename = url.rsplit("/", 1)[-1].split("?")[0]
            yield Request(
                archive=True,
                request=HTTPRequestParams(method=HttpMethod.GET, url=url),
                continuation=self.archive_opinion_file,
                expected_type=ext,
                accumulated_data={
                    "docket_number": docket_number,
                    "court": accumulated_data["court"],
                    "document_type": ext,
                    "source_url": url,
                },
                deduplication_key=f"{docket_number}-{filename}",
            )

    @step()
    def archive_opinion_file(
        self,
        accumulated_data: dict,
        local_filepath: str | None,
    ) -> Generator[ScraperYield[_Yield], None, None]:
        """Yield a CaAppOpinionFile referring to the archived opinion file."""
        yield ParsedData(
            data=CaAppOpinionFile(
                docket_number=accumulated_data["docket_number"],
                court=accumulated_data["court"],
                document_type=accumulated_data["document_type"],
                source_url=accumulated_data["source_url"],
                local_path=local_filepath,
            )
        )

    def _fan_out_multi_result(
        self,
        page: PageElement,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[_Yield], None, None]:
        """Yield one Request per unique doc_id on a multi-result page.

        Each row's trial-court case number (column 2) is collected into
        the group for its doc_id and stashed on accumulated_data so the
        next ``parse_case_summary`` pass sees them as the authoritative
        list (overriding the singular "Trial Court Case" dt/dd field).
        """
        rows = page.query(
            XPath("//table//tbody//tr"), "multi-result rows", min_count=0
        )
        groups: dict[str, dict] = {}
        for row in rows:
            cells = row.query(XPath("td"), "row cells", min_count=0)
            if len(cells) < 2:
                continue
            row_links = row.find_links(
                XPath(".//a[contains(@href, 'mainCaseScreen.cfm')]"),
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

    # =========================================================================
    # Step: Docket (Register of Actions) tab
    # =========================================================================

    @step(
        await_list=[
            WaitForLoadState("networkidle", timeout=30000),
            WaitForSelector("button[disabled]", state="hidden", timeout=15000),
        ],
        priority=6,
    )
    def parse_docket(
        self,
        page: PageElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[_Yield], None, None]:
        """Extract docket entries, then navigate to the briefs tab."""
        self._check_transient_errors(page)

        # Extract division from the docket header if not already set.
        if not accumulated_data.get("division"):
            div_texts = page.query_strings(
                XPath(
                    "//div[contains(@class, 'caseInfo')]"
                    "//text()[contains(., 'Division')]"
                ),
                "division text",
                min_count=0,
            )
            for t in div_texts:
                m = re.search(r"Division\s+(\S+)", t)
                if m:
                    accumulated_data["division"] = m.group(1)
                    break

        accumulated_data["entries"] = [
            e.raw_data for e in DocketEntriesParser()(page)
        ]

        briefs_url = _build_tab_url(response.url, "briefing.cfm")
        yield Request(
            request=HTTPRequestParams(method=HttpMethod.GET, url=briefs_url),
            continuation=self.parse_briefs,
            accumulated_data=accumulated_data,
            deduplication_key=(
                f"parse_briefs:{accumulated_data['docket_number']}"
            ),
        )

    # =========================================================================
    # Step: Briefs tab
    # =========================================================================

    @step(
        await_list=[
            WaitForLoadState("networkidle", timeout=30000),
            WaitForSelector("button[disabled]", state="hidden", timeout=15000),
        ],
        priority=5,
    )
    def parse_briefs(
        self,
        page: PageElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[_Yield], None, None]:
        """Extract brief records, then navigate to the disposition tab."""
        self._check_transient_errors(page)

        accumulated_data["briefs"] = [b.raw_data for b in BriefsParser()(page)]

        dispo_url = _build_tab_url(response.url, "disposition.cfm")
        yield Request(
            request=HTTPRequestParams(method=HttpMethod.GET, url=dispo_url),
            continuation=self.parse_disposition,
            accumulated_data=accumulated_data,
            deduplication_key=(
                f"parse_disposition:{accumulated_data['docket_number']}"
            ),
        )

    # =========================================================================
    # Step: Disposition tab
    # =========================================================================

    @step(
        await_list=[
            WaitForLoadState("networkidle", timeout=30000),
            WaitForSelector("button[disabled]", state="hidden", timeout=15000),
        ],
        priority=4,
    )
    def parse_disposition(
        self,
        page: PageElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[_Yield], None, None]:
        """Extract disposition data. Structure differs SC vs CoA."""
        self._check_transient_errors(page)
        is_supreme = accumulated_data["is_supreme"]

        parser = DispositionParser(is_supreme=is_supreme)
        dispositions = [d.raw_data for d in parser(page)]
        accumulated_data["dispositions"] = dispositions

        # Promote a case citation onto the docket. SC keeps it in a
        # standalone block; CoA carries it on the disposition row.
        if is_supreme:
            citation = DispositionParser.extract_case_citation(page)
            if citation:
                accumulated_data["case_citation"] = citation
        else:
            for d in dispositions:
                if d.get("case_citation"):
                    accumulated_data["case_citation"] = d["case_citation"]

        parties_url = _build_tab_url(response.url, "partiesAndAttorneys.cfm")
        yield Request(
            request=HTTPRequestParams(method=HttpMethod.GET, url=parties_url),
            continuation=self.parse_parties,
            accumulated_data=accumulated_data,
            deduplication_key=(
                f"parse_parties:{accumulated_data['docket_number']}"
            ),
        )

    # =========================================================================
    # Step: Parties and Attorneys tab
    # =========================================================================

    @step(
        await_list=[
            WaitForLoadState("networkidle", timeout=30000),
            WaitForSelector("button[disabled]", state="hidden", timeout=15000),
        ],
        priority=3,
    )
    def parse_parties(
        self,
        page: PageElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[_Yield], None, None]:
        """Extract parties and their attorneys, then navigate to trial court."""
        self._check_transient_errors(page)

        accumulated_data["parties"] = [
            p.raw_data for p in PartiesParser()(page)
        ]

        tc_url = _build_tab_url(response.url, "trialCourt.cfm")
        yield Request(
            request=HTTPRequestParams(method=HttpMethod.GET, url=tc_url),
            continuation=self.parse_trial_court,
            accumulated_data=accumulated_data,
            deduplication_key=(
                f"parse_trial_court:{accumulated_data['docket_number']}"
            ),
        )

    # =========================================================================
    # Step: Trial Court / Lower Court tab
    # =========================================================================

    @step(
        await_list=[
            WaitForLoadState("networkidle", timeout=30000),
            WaitForSelector("button[disabled]", state="hidden", timeout=15000),
        ],
        priority=2,
    )
    def parse_trial_court(
        self,
        page: PageElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[_Yield], None, None]:
        """Extract trial/lower court info, then assemble the docket."""
        self._check_transient_errors(page)
        is_supreme = accumulated_data["is_supreme"]

        info = TrialCourtParser(is_supreme=is_supreme)(page)[0].raw_data
        if is_supreme:
            accumulated_data["lower_court_info"] = info
        else:
            accumulated_data["trial_court_info"] = info

        yield from self._assemble_docket(accumulated_data)

    # =========================================================================
    # Final assembly
    # =========================================================================

    def _assemble_docket(
        self, data: dict
    ) -> Generator[ScraperYield[_Yield], None, None]:
        """Build and yield the final CaAppDocket from accumulated data.

        Nested records (entries, briefs, dispositions, parties) and the
        trial/lower court blocks arrive as the parsers' ``raw_data`` dicts;
        ``CaAppDocket.raw`` coerces them (and re-parses ISO dates) at confirm.
        """
        docket = CaAppDocket.raw(
            docket_number=data["docket_number"],
            court=data["court"],
            case_name=data.get("case_name", ""),
            case_type=data.get("case_type"),
            division=data.get("division"),
            date_filed=data.get("date_filed"),
            date_terminated=data.get("date_terminated"),
            case_status=data.get("case_status"),
            date_argued=data.get("date_argued"),
            issues=data.get("issues"),
            case_citation=data.get("case_citation"),
            opinion_pdf_url=data.get("opinion_pdf_url"),
            opinion_docx_url=data.get("opinion_docx_url"),
            coa_case_numbers=data.get("coa_case_numbers", []),
            trial_court_case_numbers=data.get("trial_court_case_numbers", []),
            cross_referenced_cases=data.get("cross_referenced_cases", []),
            entries=data.get("entries", []),
            briefs=data.get("briefs", []),
            dispositions=data.get("dispositions", []),
            parties=data.get("parties", []),
            trial_court_info=data.get("trial_court_info"),
            lower_court_info=data.get("lower_court_info"),
            source_url=data.get("source_url"),
            source_entry_point=data.get("entry_point"),
            subscription_urls=data.get("subscription_urls", []),
        )
        yield ParsedData(data=docket)

    # =========================================================================
    # Transient error detection
    # =========================================================================

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
        errors = page.query(
            XPath("//h2[contains(., 'Error 503')]"),
            "503 error heading",
            min_count=0,
            max_count=1,
        )
        if errors:
            raise TransientException("F5 503 challenge page")

    @staticmethod
    def _check_502_bad_gateway(page: PageElement) -> None:
        """Raise TransientException if the page is a 502 Bad Gateway."""
        errors = page.query(
            XPath("//h1[contains(., '502 Bad Gateway')]"),
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
        notice = page.query(
            XPath("//strong[contains(., 'NOTICE: MAINTENANCE')]"),
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
        spinners = page.query(
            XPath(
                "//button[contains(., 'Loading') and "
                "not(contains(@style, 'display: none'))]"
            ),
            "visible loading spinner buttons",
            min_count=0,
        )
        if spinners:
            labels = [s.text_content().strip() for s in spinners]
            raise TransientException(
                f"Page still loading (spinners present: {labels})"
            )

    # =========================================================================
    # Soft-404 detection
    # =========================================================================

    def actually_successful(self, response: Response) -> bool:
        """Return False for soft-404 pages.

        The site redirects to the search page with an ``inputError``
        parameter for malformed case numbers. "Case Not Found" results
        pages are let through (return True) so ``parse_case_summary`` can
        yield ``CaAppCaseUnavailable``.
        """
        return "inputError" not in response.url
