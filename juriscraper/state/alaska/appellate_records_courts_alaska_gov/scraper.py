"""Alaska Appellate Courts scraper (appellate-records.courts.alaska.gov).

Scrapes docket data from the Alaska Supreme Court (``ak``, case numbers
``S#####``) and Court of Appeals (``akctapp``, case numbers ``A#####``)
CMS. Plain HTTP; the CMS returns up to 1000 matches per CaseNumber search
with all rows in the HTML (client-side pagination only).

Entry points (see ``CC_NOTES.md`` for the full flow):
  - ``dockets_by_number_prefix(court_ids, prefix)`` — bulk-enumerate by a
    3-digit case-number prefix (``S012`` matches S01200–S01299).
  - ``dockets_by_number(court_ids, docket_number)`` — speculative probe of
    sequential 5-digit case numbers.
  - ``docket_by_number(court_id, docket_number)`` — fetch one known case.

Per-case flow: search → case general → participants → record → docket →
motions → motion details → briefs → brief histories, accumulating a single
``AkDocket`` and emitting ``AkDocument`` records for each archived file.
"""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING, Any, ClassVar

from jkent.common.decorators import entry, step
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
    XPath,
)
from pyrate_limiter import Duration, Rate

from .models import AkDocket, AkDocument
from .parsers import (
    BriefHistoryParser,
    BriefsParser,
    CaseGeneralParser,
    DocketParser,
    MotionDetailParser,
    MotionsParser,
    PartiesParser,
    RecordParser,
    SearchResultsParser,
)

if TYPE_CHECKING:
    from collections.abc import Generator

    from jkent.common.page_element import PageElement
    from jkent.data_types import ScraperYield

BASE_URL = "https://appellate-records.courts.alaska.gov/CMSPublic"

# Tab order within a case; ``_continue_chain`` walks it.
_TAB_CHAIN = ("parties", "records", "docket", "motions", "briefs")

_Yield = AkDocket | AkDocument


class AlaskaScraper(BaseScraper[_Yield]):
    """Scraper for Alaska appellate court dockets."""

    # === Metadata ===
    court_ids: ClassVar[set[str]] = {"ak", "akctapp"}
    court_url: ClassVar[str] = "https://appellate-records.courts.alaska.gov/"
    data_types: ClassVar[set[str]] = {"dockets"}
    status: ClassVar[ScraperStatus] = ScraperStatus.IN_DEVELOPMENT
    version: ClassVar[str] = "2026-07-28"
    last_verified: ClassVar[str] = "2026-06-24"
    requires_auth: ClassVar[bool] = False
    rate_limits: ClassVar[list[Rate] | None] = [Rate(4, Duration.SECOND)]
    driver_requirements: ClassVar[list[DriverRequirement]] = [
        DriverRequirement.H11_HEADER_FIXES,
        DriverRequirement.FOLLOW_REDIRECTS,
    ]

    COURT_LETTER: ClassVar[dict[str, str]] = {"ak": "S", "akctapp": "A"}

    # =========================================================================
    # Entry points
    # =========================================================================

    @entry(AkDocket)
    def dockets_by_number_prefix(
        self, court_ids: set[str], prefix: int
    ) -> Generator[Request, None, None]:
        """Bulk-enumerate dockets by a 3-digit case-number prefix.

        ``prefix`` is zero-padded to 3 digits and prepended with the
        per-court letter. A 3-digit prefix matches up to 100 of the
        5-digit case numbers (``S012`` → S01200–S01299), well under the
        server's 1000-result cap, and ``parse_search_results`` walks every
        match row, so one request per court yields all hits.
        """
        for court_id in sorted(court_ids & set(self.COURT_LETTER)):
            search_term = f"{self.COURT_LETTER[court_id]}{prefix:03d}"
            yield self._search_request(search_term, "dockets_by_number_prefix")

    @entry(AkDocket)
    def dockets_by_number(
        self, court_ids: set[str], docket_number: SpeculativeRange
    ) -> Generator[Request, None, None]:
        """Speculatively probe sequential 5-digit case numbers.

        The driver advances ``docket_number`` across the seed range and
        beyond until ``gap`` consecutive soft-404s (see
        ``actually_successful``). One probe is emitted per court; seed a
        single court per speculation for the cleanest gap tracking.
        """
        for court_id in sorted(court_ids & set(self.COURT_LETTER)):
            search_term = (
                f"{self.COURT_LETTER[court_id]}{docket_number.min:05d}"
            )
            yield self._search_request(search_term, "dockets_by_number")

    @entry(AkDocket)
    def docket_by_number(
        self, court_id: str, docket_number: str
    ) -> Generator[Request, None, None]:
        """Fetch one already-known docket by its case number.

        ``docket_number`` is the case number with or without the hyphen
        (``S-19019`` / ``S19019``); the CMS search accepts either.
        """
        yield self._search_request(docket_number, "docket_by_number")

    def _search_request(self, search_term: str, entry_point: str) -> Request:
        return Request(
            request=HTTPRequestParams(
                method=HttpMethod.GET,
                url=f"{BASE_URL}/Search/CaseNumber?CaseNumber={search_term}",
                headers={"Accept": "text/html"},
            ),
            continuation=self.parse_search_results,
            accumulated_data={"entry_point": entry_point},
            deduplication_key=f"search:{search_term}",
        )

    # =========================================================================
    # Soft-404 detection (for speculative probing)
    # =========================================================================

    def actually_successful(self, response: Response) -> bool:
        """Treat empty CaseNumber search pages as soft-404s.

        The search endpoint returns HTTP 200 even when a case number does
        not exist; the placeholder ``No Results Found`` row lacks the
        ``class="search-link"`` anchor that real result rows always carry.
        """
        if "/Search/CaseNumber" not in response.url:
            return True
        return "search-link" in response.text

    # =========================================================================
    # Step 1 — search results
    # =========================================================================

    @step()
    def parse_search_results(
        self,
        page: PageElement,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[_Yield], None, None]:
        """Walk the search-result rows and dispatch a case-general fetch
        for each match."""
        entry_point = accumulated_data.get("entry_point")
        for dv in SearchResultsParser()(page):
            docket_data = self._json_safe(dv.raw_data)
            docket_data["source_entry_point"] = entry_point
            source_url = docket_data.get("source_url")
            if not source_url:
                continue
            yield Request(
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url=source_url,
                    headers={"Accept": "text/html"},
                ),
                continuation=self.parse_case_general,
                accumulated_data={"docket_data": docket_data, "tab_urls": {}},
                deduplication_key=(
                    f"case_general:{docket_data['docket_number']}"
                ),
            )

    # =========================================================================
    # Step 2 — case summary (general)
    # =========================================================================

    @step(priority=8)
    def parse_case_general(
        self,
        page: PageElement,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[_Yield], None, None]:
        """Merge the Case Summary fields and chain into the tab flow."""
        docket_data = accumulated_data["docket_data"]
        docket_data.update(
            self._json_safe(CaseGeneralParser()(page)[0].raw_data)
        )

        tab_urls = self._extract_tab_urls(page)

        for opinion in docket_data.get("opinions", []):
            yield from self._archive(
                opinion.get("document_url"),
                docket_data,
                entry_number=opinion.get("number"),
                source="opinion",
            )

        yield from self._continue_chain(docket_data, tab_urls, "parties")

    # =========================================================================
    # Step 3 — participants & attorneys
    # =========================================================================

    @step(priority=7)
    def parse_case_parties(
        self,
        page: PageElement,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[_Yield], None, None]:
        docket_data = accumulated_data["docket_data"]
        docket_data["parties"] = [
            self._json_safe(dv.raw_data) for dv in PartiesParser()(page)
        ]
        yield from self._continue_chain(
            docket_data, accumulated_data["tab_urls"], "records"
        )

    # =========================================================================
    # Step 4 — record
    # =========================================================================

    @step(priority=6)
    def parse_case_records(
        self,
        page: PageElement,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[_Yield], None, None]:
        docket_data = accumulated_data["docket_data"]
        docket_data["records"] = [
            self._json_safe(dv.raw_data) for dv in RecordParser()(page)
        ]
        yield from self._continue_chain(
            docket_data, accumulated_data["tab_urls"], "docket"
        )

    # =========================================================================
    # Step 5 — docket
    # =========================================================================

    @step(priority=5)
    def parse_case_docket(
        self,
        page: PageElement,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[_Yield], None, None]:
        docket_data = accumulated_data["docket_data"]
        entries = [self._json_safe(dv.raw_data) for dv in DocketParser()(page)]
        docket_data["docket_entries"] = entries
        for entry_row in entries:
            yield from self._archive(
                entry_row.get("document_url"),
                docket_data,
                entry_number=entry_row.get("entry_number"),
                source="docket",
            )
        yield from self._continue_chain(
            docket_data, accumulated_data["tab_urls"], "motions"
        )

    # =========================================================================
    # Step 6 — motions and orders (list)
    # =========================================================================

    @step(priority=4)
    def parse_case_motions(
        self,
        page: PageElement,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[_Yield], None, None]:
        docket_data = accumulated_data["docket_data"]
        tab_urls = accumulated_data["tab_urls"]
        motions = [
            self._json_safe(dv.raw_data) for dv in MotionsParser()(page)
        ]
        docket_data["motions"] = motions

        pending: list[dict] = []
        for idx, motion in enumerate(motions):
            yield from self._archive(
                motion.get("document_url"),
                docket_data,
                entry_number=motion.get("entry_number"),
                source="motion",
            )
            if motion.get("detail_url"):
                pending.append({"index": idx, "url": motion["detail_url"]})

        if pending:
            yield self._motion_detail_request(docket_data, tab_urls, pending)
        else:
            yield from self._continue_chain(docket_data, tab_urls, "briefs")

    # =========================================================================
    # Step 7 — motion detail (sequential chain)
    # =========================================================================

    @step(priority=3)
    def parse_motion_detail(
        self,
        page: PageElement,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[_Yield], None, None]:
        """Merge one motion-detail page into its motion, then continue the
        sequential detail chain (or move on to briefs)."""
        docket_data = accumulated_data["docket_data"]
        tab_urls = accumulated_data["tab_urls"]
        motion_index = accumulated_data["motion_index"]
        pending = accumulated_data["pending_motion_details"]

        motions = docket_data.get("motions", [])
        if motion_index < len(motions):
            motion = motions[motion_index]
            motion.update(
                self._json_safe(MotionDetailParser()(page)[0].raw_data)
            )
            for order in motion.get("orders", []):
                yield from self._archive(
                    order.get("document_url"),
                    docket_data,
                    entry_number=order.get("entry_number"),
                    source="order",
                )
            for opposition in motion.get("oppositions", []):
                yield from self._archive(
                    opposition.get("document_url"),
                    docket_data,
                    entry_number=opposition.get("entry_number"),
                    source="opposition",
                )

        if pending:
            yield self._motion_detail_request(docket_data, tab_urls, pending)
        else:
            yield from self._continue_chain(docket_data, tab_urls, "briefs")

    def _motion_detail_request(
        self, docket_data: dict, tab_urls: dict, pending: list[dict]
    ) -> Request:
        nxt, rest = pending[0], pending[1:]
        return Request(
            request=HTTPRequestParams(
                method=HttpMethod.GET,
                url=nxt["url"],
                headers={"Accept": "text/html"},
            ),
            continuation=self.parse_motion_detail,
            accumulated_data={
                "docket_data": docket_data,
                "tab_urls": tab_urls,
                "motion_index": nxt["index"],
                "pending_motion_details": rest,
            },
            deduplication_key=(
                f"motion_detail:{docket_data['docket_number']}:{nxt['index']}"
            ),
        )

    # =========================================================================
    # Step 8 — briefs (list)
    # =========================================================================

    @step(priority=3)
    def parse_case_briefs(
        self,
        page: PageElement,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[_Yield], None, None]:
        docket_data = accumulated_data["docket_data"]
        tab_urls = accumulated_data["tab_urls"]
        briefs = [self._json_safe(dv.raw_data) for dv in BriefsParser()(page)]
        docket_data["briefs"] = briefs
        docket_data["briefing_rounds"] = self._json_safe(
            BriefsParser.parse_rounds(page)
        )

        pending: list[dict] = []
        for idx, brief in enumerate(briefs):
            yield from self._archive(
                brief.get("document_url"),
                docket_data,
                entry_number=brief.get("entry_number"),
                source="brief",
            )
            if brief.get("history_url"):
                pending.append({"index": idx, "url": brief["history_url"]})

        if pending:
            yield self._brief_history_request(docket_data, tab_urls, pending)
        else:
            yield from self._emit(docket_data)

    # =========================================================================
    # Step 9 — brief history (sequential chain)
    # =========================================================================

    @step(priority=2)
    def parse_brief_history(
        self,
        page: PageElement,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[_Yield], None, None]:
        docket_data = accumulated_data["docket_data"]
        tab_urls = accumulated_data["tab_urls"]
        brief_index = accumulated_data["brief_index"]
        pending = accumulated_data["pending_brief_histories"]

        briefs = docket_data.get("briefs", [])
        if brief_index < len(briefs):
            brief = briefs[brief_index]
            brief.update(
                self._json_safe(BriefHistoryParser()(page)[0].raw_data)
            )
            for hist in brief.get("history", []):
                yield from self._archive(
                    hist.get("document_url"),
                    docket_data,
                    entry_number=hist.get("entry_number"),
                    source="brief_history",
                )

        if pending:
            yield self._brief_history_request(docket_data, tab_urls, pending)
        else:
            yield from self._emit(docket_data)

    def _brief_history_request(
        self, docket_data: dict, tab_urls: dict, pending: list[dict]
    ) -> Request:
        nxt, rest = pending[0], pending[1:]
        return Request(
            request=HTTPRequestParams(
                method=HttpMethod.GET,
                url=nxt["url"],
                headers={"Accept": "text/html"},
            ),
            continuation=self.parse_brief_history,
            accumulated_data={
                "docket_data": docket_data,
                "tab_urls": tab_urls,
                "brief_index": nxt["index"],
                "pending_brief_histories": rest,
            },
            deduplication_key=(
                f"brief_history:{docket_data['docket_number']}:{nxt['index']}"
            ),
        )

    # =========================================================================
    # Document download handler
    # =========================================================================

    @step()
    def handle_document_download(
        self,
        response: Response,
        local_filepath: str | None,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[_Yield], None, None]:
        """Emit an ``AkDocument`` for an archived file.

        The CMS 302-redirects to ``/CMSPublic/Search`` for documents it
        does not have on file (most opinions from before ~2012). The driver
        follows the redirect and archives the search-page HTML; we detect
        this via the final ``Content-Type`` and surface it as
        ``missing_redirected``.
        """
        content_type = (response.headers.get("content-type") or "").lower()
        yield ParsedData(
            AkDocument.raw(
                docket_number=accumulated_data["docket_number"],
                court=accumulated_data["court"],
                entry_number=accumulated_data.get("entry_number"),
                source=accumulated_data.get("source"),
                document_url=accumulated_data.get("document_url"),
                local_path=local_filepath,
                missing_redirected="application/pdf" not in content_type,
            )
        )

    # =========================================================================
    # Helpers
    # =========================================================================

    @staticmethod
    def _json_safe(data: Any) -> Any:
        """Round-trip ``data`` through JSON so it survives storage in
        ``accumulated_data`` (``date`` objects become ISO strings, which
        ``AkDocket.raw`` re-coerces at confirm time)."""
        return json.loads(json.dumps(data, default=str))

    @staticmethod
    def _extract_tab_urls(page: PageElement) -> dict[str, str]:
        """Map the case sub-navigation tabs to their URLs."""
        tab_urls: dict[str, str] = {}
        nav_links = page.find_links(
            XPath("//ul[contains(@class, 'cms-submenu')]//a"),
            "nav tabs",
            min_count=0,
        )
        for link in nav_links:
            text = (link.text or "").strip().lower()
            if "participant" in text:
                tab_urls["parties"] = link.url
            elif "record" in text:
                tab_urls["records"] = link.url
            elif "docket" in text:
                tab_urls["docket"] = link.url
            elif "motion" in text:
                tab_urls["motions"] = link.url
            elif "brief" in text:
                tab_urls["briefs"] = link.url
        return tab_urls

    def _archive(
        self,
        url: str | None,
        docket_data: dict,
        *,
        entry_number: str | None,
        source: str,
    ) -> Generator[Request, None, None]:
        """Yield an archive request for ``url`` (if any), emitting an
        ``AkDocument`` on completion."""
        if not url:
            return
        docket_number = docket_data["docket_number"]
        url_hash = hashlib.sha1(url.encode()).hexdigest()[:10]
        yield Request(
            archive=True,
            request=HTTPRequestParams(method=HttpMethod.GET, url=url),
            continuation=self.handle_document_download,
            accumulated_data={
                "docket_number": docket_number,
                "court": docket_data["court"],
                "entry_number": entry_number,
                "source": source,
                "document_url": url,
            },
            deduplication_key=(
                f"{docket_number}-{source}-{entry_number or 'na'}-{url_hash}"
            ),
        )

    def _continue_chain(
        self,
        docket_data: dict,
        tab_urls: dict[str, str],
        next_tab: str,
    ) -> Generator[ScraperYield[_Yield], None, None]:
        """Navigate to the next available tab at or after ``next_tab``;
        emit the finished docket when the chain is exhausted."""
        continuations = {
            "parties": self.parse_case_parties,
            "records": self.parse_case_records,
            "docket": self.parse_case_docket,
            "motions": self.parse_case_motions,
            "briefs": self.parse_case_briefs,
        }
        start = (
            _TAB_CHAIN.index(next_tab)
            if next_tab in _TAB_CHAIN
            else len(_TAB_CHAIN)
        )
        for tab in _TAB_CHAIN[start:]:
            url = tab_urls.get(tab)
            if url:
                yield Request(
                    request=HTTPRequestParams(
                        method=HttpMethod.GET,
                        url=url,
                        headers={"Accept": "text/html"},
                    ),
                    continuation=continuations[tab],
                    accumulated_data={
                        "docket_data": docket_data,
                        "tab_urls": tab_urls,
                    },
                    deduplication_key=(
                        f"{continuations[tab].__name__}:"
                        f"{docket_data['docket_number']}"
                    ),
                )
                return
        yield from self._emit(docket_data)

    def _emit(
        self, docket_data: dict
    ) -> Generator[ScraperYield[_Yield], None, None]:
        """Emit the accumulated docket as a deferred-validation record."""
        yield ParsedData(AkDocket.raw(**docket_data))
