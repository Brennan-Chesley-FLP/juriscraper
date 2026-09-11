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

    parse_case_summary (priority 8) → parse_docket (7) → parse_briefs (6)
      → parse_disposition (5) → parse_parties (4)
        → parse_scheduled_actions (3, Courts of Appeal only)
          → parse_trial_court (2)
            → _assemble_docket (emit CaAppDocket [+ CaUnavailableOpinion])

Documents linked off the summary page -- opinions and, on the Supreme Court,
orders -- are downloaded as separate ``CaDocument`` records (archive requests,
priority 1), joined back to the docket via ``docket_number`` + ``court``. Where
the site shows a published opinion but links no file at all, a
``CaUnavailableOpinion`` records the gap instead, carrying what is needed to
fetch the text from the Official Reports.

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
from jkent.common.page_element import Link, PageElement, ViaLink
from jkent.data_types import (
    CSS,
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
    CaDocument,
    CaDocumentType,
    CaOpinionEvidence,
    CaUnavailableOpinion,
)
from .parsers import (
    BriefsParser,
    CaseSummaryParser,
    DispositionParser,
    DocketEntriesParser,
    PartiesParser,
    ScheduledActionsParser,
    TrialCourtParser,
)
from .parsers._common import tab_header

if TYPE_CHECKING:
    from collections.abc import Generator

    from jkent.data_types import ScraperYield

_Yield = CaAppDocket | CaAppCaseUnavailable | CaDocument | CaUnavailableOpinion

# Case-summary anchor id -> what the document behind it is. The id is the only
# reliable signal of kind: an order and an opinion are both served as .pdf.
# ``a#doc`` covers .DOCX and, on older cases, .DOC.
_DOCUMENT_LINK_IDS: dict[str, CaDocumentType] = {
    "pdf": CaDocumentType.OPINION,
    "doc": CaDocumentType.OPINION,
    "courtOrders": CaDocumentType.ORDER,
}

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


#: Matches a panel spinner that has *not* finished. The site renders each AJAX
#: panel (Summary, Docket, Briefs, ...) as a button reading "…Loading...", then
#: hides it with an inline ``display: none`` once that panel's JS has swapped in
#: real content. The buttons stay in the DOM either way, so "still loading"
#: means "a Loading button that has not been hidden".
#:
#: This single XPath is both what the driver waits for (``_SPINNER_CLEARED``)
#: and what the page is asserted against (``_check_loading_spinners``). Keeping
#: them one expression is the point: waiting on a *different* predicate than the
#: one asserted lets the wait pass while panels are still spinning, and the
#: assertion then raises a transient on a page that was merely a moment from
#: ready — which is a self-inflicted failure, indistinguishable downstream from
#: the server actually being in distress.
_SPINNER_XPATH = (
    "//button[contains(., 'Loading') and "
    "not(contains(@style, 'display: none'))]"
)

#: Wait until *zero* spinners remain visible.
#:
#: The XPath above is self-filtering — a hidden spinner stops matching it — so
#: as each panel finishes it drops out of the match set. That matters because
#: Playwright resolves a selector to its *first* match: waiting on a predicate
#: that keeps matching finished panels would be satisfied by whichever panel
#: happened to load first. Here the match set shrinks to empty, and the
#: ``hidden`` state (which "no such element" satisfies) is reached only once the
#: last panel has been hidden.
_SPINNER_CLEARED = WaitForSelector(
    f"xpath={_SPINNER_XPATH}", state="hidden", timeout=20000
)

#: Per-attempt navigation budget, in seconds.
#:
#: Held well under the old 60s because a page slower than this is not going to
#: satisfy the spinner wait either — the attempt is already lost, and the only
#: question is how long it takes to find that out. That cost is paid twice over:
#: once by the request, and again by the circuit breaker, whose half-open probe
#: is drawn from exactly this pool of requeued requests. A long navigation
#: timeout makes every probe expensive, which is what turns a short cool-down
#: into a multi-minute stall.
_NAV_TIMEOUT_S = 25


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
                timeout=_NAV_TIMEOUT_S,
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
            WaitForSelector("#centerColumn", timeout=15000),
            WaitForLoadState("networkidle", timeout=15000),
            _SPINNER_CLEARED,
        ],
        priority=8,
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
            yield from self._fan_out_multi_result(
                page, response, accumulated_data
            )
            return

        accumulated_data["source_url"] = response.url

        # In rare cases, search will key off the trial court number
        # And show us multiple results for a different case here.
        # But it redirects us to that case and we can grab the actual
        # docket number from the doc_no param in the url.
        doc_no = parse_qs(urlparse(response.url).query).get("doc_no")
        if doc_no and doc_no[0]:
            accumulated_data["docket_number"] = doc_no[0]

        is_supreme = accumulated_data["is_supreme"]

        bag = CaseSummaryParser(is_supreme=is_supreme)(page)[0].raw_data

        # Archive the documents linked from this page. The links are found
        # here, not in the parser, so each Link keeps the selector the
        # Playwright driver clicks to trigger the download. Each is addressed
        # by its element id, which is also what tells us the document's kind:
        # the opinion is offered as ``a#pdf`` plus ``a#doc`` (the latter serving
        # both .DOCX and, on older cases, .DOC), while a court order is a
        # separate ``a#courtOrders`` under its own "Supreme Court Order" label.
        #
        # The id is *not* unique on the page: a Supreme Court case with several
        # orders repeats ``id="courtOrders"`` once per order, invalid HTML that
        # the site emits anyway (S263043 carries two, each a distinct PDF with
        # its own date). So every match is taken, not just the first -- capping
        # this at one failed the whole docket rather than dropping the extras.
        document_links = [
            (document_type, link)
            for elem_id, document_type in _DOCUMENT_LINK_IDS.items()
            for link in page.find_links(
                CSS(f"a#{elem_id}"),
                f"{document_type.value} {elem_id} link",
                min_count=0,
            )
        ]
        # Recorded so _assemble_docket can tell "no opinion offered" apart from
        # "opinion offered": a docket the disposition says was published but
        # that links no file becomes a CaUnavailableOpinion.
        accumulated_data["document_links_found"] = len(document_links)

        yield from self._yield_document_archives(
            document_links, accumulated_data
        )

        # Fall back to the case-summary "Trial Court Case" block only if the
        # multi-result fan-out hasn't already supplied an authoritative list.
        # The CoA prints a single number there; the SC prints one court
        # name/number pair per consolidated matter, so the two branches yield
        # different shapes and are unpacked separately.
        single_tc = bag.pop("trial_court_case_single", None)
        summary_trial_courts = bag.pop("summary_trial_courts", [])
        accumulated_data["summary_trial_courts"] = summary_trial_courts
        if not accumulated_data.get("trial_court_case_numbers"):
            accumulated_data["trial_court_case_numbers"] = [
                number
                for court in summary_trial_courts
                if (number := court.get("case_number"))
            ] or ([single_tc] if single_tc else [])

        # Merge the remaining (model-field) summary data forward.
        accumulated_data.update(bag)

        # Navigate to the Docket tab.
        docket_url = _build_tab_url(response.url, "dockets.cfm")
        yield Request(
            request=HTTPRequestParams(
                method=HttpMethod.GET, url=docket_url, timeout=_NAV_TIMEOUT_S
            ),
            continuation=self.parse_docket,
            accumulated_data=accumulated_data,
            deduplication_key=(
                f"parse_docket:{accumulated_data['docket_number']}"
            ),
        )

    def _yield_document_archives(
        self,
        document_links: list[tuple[CaDocumentType, Link]],
        accumulated_data: dict,
    ) -> Generator[Request, None, None]:
        """Yield an archive Request for each document on the case page.

        Each ``Link`` carries the selector the Playwright driver clicks to
        trigger the download (an archive request needs a
        ``ViaLink``/``ViaFormSubmit``, not just a URL), so the request is built
        with ``Link.follow``. Each becomes one ``CaDocument`` via
        ``archive_document``.

        The kind comes from the anchor id the caller matched, not from the URL —
        an order and an opinion are both ``.pdf``, so the file format cannot
        tell them apart.
        """
        docket_number = accumulated_data["docket_number"]
        for document_type, link in document_links:
            url = link.url
            m = re.search(r"\.([A-Za-z]{2,4})(?:$|\?)", url)
            ext = m.group(1).lower() if m else "bin"
            filename = url.rsplit("/", 1)[-1].split("?")[0]
            collection = re.search(r"/opinions/([^/]+)/", url)
            yield link.follow(
                archive=True,
                continuation=self.archive_document,
                bypass_rate_limit=True,
                expected_type=ext,
                accumulated_data={
                    "docket_number": docket_number,
                    "court": accumulated_data["court"],
                    "document_type": document_type.value,
                    "file_format": ext,
                    "source_collection": (
                        collection.group(1).lower() if collection else None
                    ),
                    "source_url": url,
                },
                deduplication_key=f"{docket_number}-{filename}",
            )

    @step()
    def archive_document(
        self,
        accumulated_data: dict,
        local_filepath: str | None,
    ) -> Generator[ScraperYield[_Yield], None, None]:
        """Yield a CaDocument referring to the archived file."""
        yield ParsedData(
            data=CaDocument(
                docket_number=accumulated_data["docket_number"],
                court=accumulated_data["court"],
                document_type=accumulated_data["document_type"],
                file_format=accumulated_data["file_format"],
                source_collection=accumulated_data.get("source_collection"),
                source_url=accumulated_data["source_url"],
                local_path=local_filepath,
            )
        )

    def _fan_out_multi_result(
        self,
        page: PageElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[_Yield], None, None]:
        """Walk every page of a multi-result set, then fan out per doc_id.

        Each row's trial-court case number (column 2) is collected into the
        group for its doc_id and stashed on accumulated_data so the next
        ``parse_case_summary`` pass sees them as the authoritative list
        (overriding the singular "Trial Court Case" dt/dd field).

        A multi-result page does *not* always mean "one CoA case, several
        lower-court matters": a search by a shared number (e.g. a trial-court
        number that several appeals reference) returns several *distinct*
        appellate cases. Each fanned-out child therefore lands on a case page
        with its own ``doc_no``; ``parse_case_summary`` adopts that as the
        child's ``docket_number``, keeping the sibling chains distinct.

        **The result set paginates at 25 rows**, so the fan-out cannot happen
        on the page it was handed. ``searchResults.cfm`` offers the remainder
        behind ``<a class="nextprev">next &gt;&gt;</a>`` → ``&start=26``;
        B302074 holds 38 rows over two pages, all of them the same doc_id, so
        reading only the first page silently dropped 13 of that case's
        trial-court numbers. Groups are therefore accumulated across pages in
        ``multi_result_groups`` and only fanned out once a page arrives with
        no next link.

        The walk exists because the fan-out has to *click*: a row's href
        carries ``request_token=auth``, a placeholder, and navigating to it
        directly lands back on the search form. So each case is reached by
        clicking its row, which means reaching it from a page that has that
        row -- see ``_fan_out_groups``.
        """
        groups: dict[str, dict] = accumulated_data.get(
            "multi_result_groups", {}
        )
        # A revisit (see ``_fan_out_groups``) is here for one stranded case
        # only. Its page carries every other row too, and merging those would
        # re-fan cases the first pass already emitted -- harmless, since the
        # dedup key stops them, but it would put a pile of doomed requests on
        # the queue for nothing.
        wanted = (
            set(groups)
            if accumulated_data.get("multi_result_single")
            else None
        )
        page_url = response.url
        for row in page.query(
            XPath("//table//tbody//tr"), "multi-result rows", min_count=0
        ):
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
            if wanted is not None and doc_id not in wanted:
                continue
            tc_number = cells[1].text_content().strip()
            group = groups.setdefault(
                doc_id,
                {"url": url, "page_url": page_url, "trial_court_numbers": []},
            )
            # Keep the *latest* page a doc_id was seen on, so the fan-out
            # prefers a page it can still click the row on.
            group["url"] = url
            group["page_url"] = page_url
            if tc_number and tc_number not in group["trial_court_numbers"]:
                group["trial_court_numbers"].append(tc_number)

        # Only the "next" control carries class="nextprev" -- "<< previous" is
        # a plain a.btnSmaller -- but the text is asserted too rather than
        # resting on that asymmetry. Its absence is what ends the walk: the
        # last page has no nextprev link at all.
        next_links = page.find_links(
            XPath("//a[contains(@class, 'nextprev') and contains(., 'next')]"),
            "multi-result next-page link",
            min_count=0,
        )
        if next_links and not accumulated_data.get("multi_result_single"):
            accumulated_data["multi_result_groups"] = groups
            yield Request(
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url=next_links[0].url,
                    timeout=_NAV_TIMEOUT_S,
                ),
                continuation=self.parse_case_summary,
                accumulated_data=accumulated_data,
                deduplication_key=f"multi_result_page:{next_links[0].url}",
            )
            return

        yield from self._fan_out_groups(groups, page_url, accumulated_data)

    def _fan_out_groups(
        self,
        groups: dict[str, dict],
        page_url: str,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[_Yield], None, None]:
        """Emit one case Request per accumulated doc_id.

        A case is reached by clicking its row, so it can only be fanned out
        from a page that still shows that row. Every doc_id seen on the final
        page is fanned out there; one seen only on an earlier page gets a
        request back to *that* page carrying ``multi_result_single``, which
        re-enters this walk with pagination switched off so it fans out from
        the page its row is on. In the one paginated set observed every page
        repeated the same doc_id, so this second hop is expected to stay rare
        -- but it is what keeps a stranded case from being dropped in silence.
        """
        for doc_id, group in groups.items():
            new_data = {
                key: value
                for key, value in accumulated_data.items()
                if key not in ("multi_result_groups", "multi_result_single")
            }

            if group["page_url"] != page_url:
                revisit = dict(new_data)
                revisit["multi_result_groups"] = {doc_id: group}
                revisit["multi_result_single"] = True
                yield Request(
                    request=HTTPRequestParams(
                        method=HttpMethod.GET,
                        url=group["page_url"],
                        timeout=_NAV_TIMEOUT_S,
                    ),
                    continuation=self.parse_case_summary,
                    accumulated_data=revisit,
                    deduplication_key=f"multi_result_revisit:{doc_id}",
                )
                continue

            new_data["trial_court_case_numbers"] = group["trial_court_numbers"]
            yield Request(
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url=group["url"],
                    timeout=_NAV_TIMEOUT_S,
                ),
                via=ViaLink(
                    selector=(
                        CSS(
                            f'a.btnSmaller[href*="doc_id={doc_id}"]'
                            f'[href*="mainCaseScreen.cfm"]'
                        )
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
            WaitForSelector("#DispoList"),
            _SPINNER_CLEARED,
        ],
        priority=7,
    )
    def parse_docket(
        self,
        page: PageElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[_Yield], None, None]:
        """Extract docket entries, then navigate to the briefs tab."""
        self._check_transient_errors(page)
        self._read_tab_header(page, accumulated_data)

        accumulated_data["entries"] = [
            e.raw_data for e in DocketEntriesParser()(page)
        ]

        briefs_url = _build_tab_url(response.url, "briefing.cfm")
        yield Request(
            request=HTTPRequestParams(
                method=HttpMethod.GET, url=briefs_url, timeout=_NAV_TIMEOUT_S
            ),
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
            # Same reasoning as parse_case_summary: assert site chrome that
            # only exists once CF has cleared. Without a positive condition
            # this list is satisfied by the challenge page itself —
            # networkidle settles on it, and a "hidden" wait passes when
            # button[disabled] is merely absent — so the driver treated the
            # interstitial as real content and never ran the CF handler.
            WaitForSelector("#centerColumn", timeout=15000),
            WaitForLoadState("networkidle", timeout=15000),
            _SPINNER_CLEARED,
        ],
        priority=6,
    )
    def parse_briefs(
        self,
        page: PageElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[_Yield], None, None]:
        """Extract brief records, then navigate to the disposition tab."""
        self._check_transient_errors(page)
        self._read_tab_header(page, accumulated_data)

        accumulated_data["briefs"] = [b.raw_data for b in BriefsParser()(page)]

        dispo_url = _build_tab_url(response.url, "disposition.cfm")
        yield Request(
            request=HTTPRequestParams(
                method=HttpMethod.GET, url=dispo_url, timeout=_NAV_TIMEOUT_S
            ),
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
            # Same reasoning as parse_case_summary: assert site chrome that
            # only exists once CF has cleared. Without a positive condition
            # this list is satisfied by the challenge page itself —
            # networkidle settles on it, and a "hidden" wait passes when
            # button[disabled] is merely absent — so the driver treated the
            # interstitial as real content and never ran the CF handler.
            WaitForSelector("#centerColumn", timeout=15000),
            WaitForLoadState("networkidle", timeout=15000),
            _SPINNER_CLEARED,
        ],
        priority=5,
    )
    def parse_disposition(
        self,
        page: PageElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[_Yield], None, None]:
        """Extract disposition data. Structure differs SC vs CoA."""
        self._check_transient_errors(page)
        self._read_tab_header(page, accumulated_data)
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
            request=HTTPRequestParams(
                method=HttpMethod.GET, url=parties_url, timeout=_NAV_TIMEOUT_S
            ),
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
            # Same reasoning as parse_case_summary: assert site chrome that
            # only exists once CF has cleared. Without a positive condition
            # this list is satisfied by the challenge page itself —
            # networkidle settles on it, and a "hidden" wait passes when
            # button[disabled] is merely absent — so the driver treated the
            # interstitial as real content and never ran the CF handler.
            WaitForSelector("#centerColumn", timeout=15000),
            WaitForLoadState("networkidle", timeout=15000),
            _SPINNER_CLEARED,
        ],
        priority=4,
    )
    def parse_parties(
        self,
        page: PageElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[_Yield], None, None]:
        """Extract parties and their attorneys, then navigate to trial court."""
        self._check_transient_errors(page)
        self._read_tab_header(page, accumulated_data)

        accumulated_data["parties"] = [
            p.raw_data for p in PartiesParser()(page)
        ]

        # Detour through Scheduled Actions when the case has that tab. Gated
        # on the site's own signal -- the ``a#actionTab`` anchor in the tab
        # strip, repeated on every tab page -- rather than on ``is_supreme``.
        # It happens to be exactly the Courts of Appeal that carry it today
        # (Supreme Court pages have six tabs, not seven), but the anchor is
        # what actually says so.
        if page.find_links(
            CSS("a#actionTab"),
            "Scheduled Actions tab link",
            min_count=0,
            max_count=1,
        ):
            yield self._tab_request(
                response,
                "scheduledActions.cfm",
                self.parse_scheduled_actions,
                accumulated_data,
            )
            return

        yield self._tab_request(
            response,
            "trialCourt.cfm",
            self.parse_trial_court,
            accumulated_data,
        )

    def _tab_request(
        self,
        response: Response,
        tab_page: str,
        continuation: object,
        accumulated_data: dict,
    ) -> Request:
        """Build the request for one case tab, reusing the current page's URL."""
        return Request(
            request=HTTPRequestParams(
                method=HttpMethod.GET,
                url=_build_tab_url(response.url, tab_page),
                timeout=_NAV_TIMEOUT_S,
            ),
            continuation=continuation,
            accumulated_data=accumulated_data,
            deduplication_key=(
                f"{continuation.__name__}:{accumulated_data['docket_number']}"
            ),
        )

    # =========================================================================
    # Step: Scheduled Actions tab (Courts of Appeal only)
    #
    # Sits *before* the Trial Court tab rather than after it so that
    # ``parse_trial_court`` remains the one place a docket is assembled. Put
    # last, it would have had to assemble too -- two assembly sites, and a
    # docket that silently disappears whenever this one tab fails to load.
    # =========================================================================

    @step(
        await_list=[
            # Same reasoning as parse_case_summary: assert site chrome that
            # only exists once CF has cleared.
            WaitForSelector("#centerColumn", timeout=15000),
            WaitForLoadState("networkidle", timeout=15000),
            _SPINNER_CLEARED,
        ],
        priority=3,
    )
    def parse_scheduled_actions(
        self,
        page: PageElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[_Yield], None, None]:
        """Read the case's outstanding deadlines, then go to trial court.

        The rows land in ``CaAppDocket.scheduled_actions``, not in
        ``entries``: they are deadlines the court is waiting on, not things
        that happened -- see ``CaAppScheduledAction``.
        """
        self._check_transient_errors(page)
        self._read_tab_header(page, accumulated_data)

        accumulated_data["scheduled_actions"] = [
            a.raw_data for a in ScheduledActionsParser()(page)
        ]

        yield self._tab_request(
            response,
            "trialCourt.cfm",
            self.parse_trial_court,
            accumulated_data,
        )

    # =========================================================================
    # Step: Trial Court / Lower Court tab
    # =========================================================================

    @step(
        await_list=[
            # Same reasoning as parse_case_summary: assert site chrome that
            # only exists once CF has cleared. Without a positive condition
            # this list is satisfied by the challenge page itself —
            # networkidle settles on it, and a "hidden" wait passes when
            # button[disabled] is merely absent — so the driver treated the
            # interstitial as real content and never ran the CF handler.
            WaitForSelector("#centerColumn", timeout=15000),
            WaitForLoadState("networkidle", timeout=15000),
            _SPINNER_CLEARED,
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
        self._read_tab_header(page, accumulated_data)
        is_supreme = accumulated_data["is_supreme"]

        info = TrialCourtParser(is_supreme=is_supreme)(page)[0].raw_data
        if is_supreme:
            # The Lower Court tab has no data at all on roughly half of SC
            # cases (139,775 of 302,103 in a full sweep) -- typically the
            # older ones and those that never reached a Court of Appeal. The
            # summary page still names their trial court, so it stands in
            # rather than the whole block being left empty.
            if not info.get("trial_courts"):
                info["trial_courts"] = accumulated_data.get(
                    "summary_trial_courts", []
                )
            accumulated_data["lower_court_info"] = info
        else:
            accumulated_data["trial_court_info"] = info

        yield from self._assemble_docket(accumulated_data)

    @staticmethod
    def _read_tab_header(page: PageElement, accumulated_data: dict) -> None:
        """Adopt the case-name / division banner every case tab repeats.

        The division is the reason this runs on every tab rather than just
        one: a Supreme Court summary has no Division term at all, so the
        banner ("Division SF", "Division LA", ...) is the only place the SC's
        sitting location is printed. The case name is taken only as a
        fallback -- the summary's Case Caption is authoritative where it has
        one.
        """
        case_name, division = tab_header(page)
        if division and not accumulated_data.get("division"):
            accumulated_data["division"] = division
        if case_name and not accumulated_data.get("case_name"):
            accumulated_data["case_name"] = case_name

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
            coa_case_numbers=data.get("coa_case_numbers", []),
            supreme_court_case_number=data.get("supreme_court_case_number"),
            trial_court_case_numbers=data.get("trial_court_case_numbers", []),
            cross_referenced_cases=data.get("cross_referenced_cases", []),
            entries=data.get("entries", []),
            scheduled_actions=data.get("scheduled_actions", []),
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
        yield from self._yield_unavailable_opinions(data)

    @staticmethod
    def _is_published(status: str | None) -> bool:
        """True when a publication status says the opinion *was* published.

        Substring matching has two traps this avoids: "Unpublished" contains
        "published", and so does "Depublished" (a publication later withdrawn,
        which must not count as published).
        """
        if not status:
            return False
        lowered = status.lower()
        return (
            "published" in lowered
            and "unpublished" not in lowered
            and "depublished" not in lowered
        )

    @classmethod
    def _opinion_evidence(
        cls, disposition: dict, is_supreme: bool
    ) -> CaOpinionEvidence | None:
        """Which signal, if any, shows this disposition is a published opinion.

        The courts state it differently. A Court of Appeal disposition carries a
        Publication Status. The Supreme Court has no such field at all, but its
        opinions are published as a matter of course, so a description reading
        "Opinion: Reversed" is the equivalent signal — and it does have to be
        the description, since the overwhelming majority of Supreme Court
        dispositions ("Petition for review denied") are not opinions.
        """
        if cls._is_published(disposition.get("publication_status")):
            return CaOpinionEvidence.PUBLICATION_STATUS
        description = (disposition.get("description") or "").strip().lower()
        if is_supreme and description.startswith("opinion"):
            return CaOpinionEvidence.OPINION_DISPOSITION
        return None

    def _yield_unavailable_opinions(
        self, data: dict
    ) -> Generator[ScraperYield[_Yield], None, None]:
        """Emit a CaUnavailableOpinion per published-but-unserved opinion.

        The site documents far more published opinions than it offers files for
        — courts.ca.gov only serves them for a limited window, so the older ones
        have to be fetched from the Official Reports. When the disposition says
        published and the summary page linked no document at all, that gap is
        recorded as data rather than passed over silently.

        Keyed on ``document_links_found`` being 0 rather than on the absence of
        a ``CaDocument``: the archive requests are still in flight when the
        docket is assembled, so their results cannot be consulted here.
        """
        if data.get("document_links_found"):
            return
        is_supreme = bool(data.get("is_supreme"))
        for disposition in data.get("dispositions", []):
            evidence = self._opinion_evidence(disposition, is_supreme)
            if evidence is None:
                continue
            yield ParsedData(
                data=CaUnavailableOpinion.raw(
                    docket_number=data["docket_number"],
                    court=data["court"],
                    evidence=evidence.value,
                    publication_status=disposition.get("publication_status"),
                    case_name=data.get("case_name"),
                    case_citation=(
                        disposition.get("case_citation")
                        or data.get("case_citation")
                    ),
                    disposition_description=disposition.get("description"),
                    disposition_date=disposition.get("disposition_date"),
                    disposition_type=disposition.get("disposition_type"),
                    author=disposition.get("author"),
                    participants=disposition.get("participants"),
                    date_filed=data.get("date_filed"),
                    date_terminated=data.get("date_terminated"),
                    trial_court_case_numbers=data.get(
                        "trial_court_case_numbers", []
                    ),
                    supreme_court_case_number=data.get(
                        "supreme_court_case_number"
                    ),
                    source_url=data.get("source_url"),
                )
            )

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
        cls._check_application_error(page)
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
    def _check_application_error(page: PageElement) -> None:
        """Raise TransientException on the site's ColdFusion error page.

        Unlike the 502/503 pages, this one does not *replace* the content --
        it interrupts it. On S297578's Lower Court tab the site rendered the
        tab strip, the case banner, and the first two fields of the
        trial-court block, then emitted "We're sorry - An Error Occurred"
        where the rest belonged. Nothing marks the page as broken, so the
        parser read the two fields it got and produced a truncated
        ``CaAppTrialCourtInfo`` -- worse than no docket, because it looks
        like a case whose county the court simply never recorded.

        Rare: 3 pages across a 1.8M-request Supreme Court sweep, all found by
        the residual ledger rather than by any error. Retrying is the right
        response -- the same URLs served normally on a later run.
        """
        errors = page.query(
            XPath("//h1[contains(., 'An Error Occurred')]"),
            "ColdFusion application error heading",
            min_count=0,
            max_count=1,
        )
        if errors:
            raise TransientException("Site application error page")

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

        Reads :data:`_SPINNER_XPATH` — the same expression the driver waited on
        via :data:`_SPINNER_CLEARED`. Sharing it is the point: this check only
        ever runs on a page the wait already passed, so any drift between the
        two predicates turns "one panel is still slow" into a transient
        failure, and pool-wide into a circuit-breaker trip.
        """
        spinners = page.query(
            XPath(_SPINNER_XPATH),
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
        return ("inputError" not in response.url) and (
            "Case Not Found" not in response.text
        )
