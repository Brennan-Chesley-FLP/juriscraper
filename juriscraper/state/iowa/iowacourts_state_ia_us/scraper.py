"""Iowa Appellate Courts Scraper.

Scrapes docket data from the Iowa Judicial Branch's Iowa Courts Online
(ESAWebApp) system at iowacourts.state.ia.us.

Supported courts:

- Supreme Court of Iowa (``iowa``)
- Court of Appeals of Iowa (``iowactapp``)

Both share a unified ``YY-NNNN`` docket number space; cases sit at the
Supreme Court until a ``TRANSFERRED TO COURT OF APPEALS`` docket event
moves them to the CoA. The scraper emits ``court`` based on the presence
of that event.

Per-page HTML extraction lives in the ``parsers`` package; the steps keep
navigation concerns (the search POST, the per-case tab chain, and final
assembly).

Entry points (§4):
    - dockets_by_activity_date(court_ids, date_range) — incremental scrape
      via the advanced search, splitting the window into one-day slices to
      stay below the server's 2 000-row cap (the search filters on *any*
      docket activity in the window, not the filing date).
    - dockets_by_number(docket_number)               — backlog speculation,
      one probe per ``YY-NNNN`` directly against ``AViewCase``.

The site requires Playwright: the Akamai Bot Manager fronting the
application returns HTTP 200 with an empty body to non-browser clients.

Flow:
    dockets_by_activity_date → (per day) parse_search_results
        └→ (per case) parse_case_summary → parse_long_title
              → parse_docket_entries → parse_parties → ParsedData
    dockets_by_number ──────────────────→ parse_case_summary → … → ParsedData
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import TYPE_CHECKING, ClassVar

from jkent.common.decorators import entry, step
from jkent.common.page_element import PageElement
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
)
from pyrate_limiter import Duration, Rate

from juriscraper.state.common.params import YearlySpeculativeRange

from .models import (
    ADV_SEARCH_URL,
    CASE_DOCKET_URL,
    CASE_LONG_TITLE_URL,
    CASE_PARTIES_URL,
    CASE_SUMMARY_URL,
    COA_TRANSFER_SIGNAL,
    DEFAULT_COURT_ID,
    IowaDocket,
    IowaDocketEntry,
    IowaParty,
)
from .parsers import (
    CaseSummaryParser,
    DocketEntriesParser,
    LongTitleParser,
    PartiesParser,
    SearchResultsParser,
)
from .parsers.search_results import SOFT_404_RE

if TYPE_CHECKING:
    from collections.abc import Generator

    from jkent.data_types import ScraperYield


class IowaAppellateScraper(BaseScraper[IowaDocket]):
    """Scraper for Iowa Supreme Court and Court of Appeals dockets.

    Captures the case summary, formal caption, register of actions, and
    parties/attorneys for each appellate case off the ESAWebApp case
    tabs, deriving ``iowa`` vs ``iowactapp`` from the docket events.
    """

    # === Metadata (§3) ===
    court_ids: ClassVar[set[str]] = {"iowa", "iowactapp"}
    court_url: ClassVar[str] = (
        "https://www.iowacourts.state.ia.us/ESAWebApp/SelectFrame"
    )
    data_types: ClassVar[set[str]] = {"dockets"}
    status: ClassVar[ScraperStatus] = ScraperStatus.IN_DEVELOPMENT
    version: ClassVar[str] = "2026-06-27"
    last_verified: ClassVar[str] = "2026-05-03"
    requires_auth: ClassVar[bool] = False
    driver_requirements: ClassVar[list[DriverRequirement]] = [
        DriverRequirement.JS_EVAL,
        DriverRequirement.FF_ALIKE,
    ]
    rate_limits: ClassVar[list[Rate] | None] = [Rate(2, Duration.SECOND)]

    # =========================================================================
    # Helpers
    # =========================================================================

    @staticmethod
    def _build_search_data(day: date) -> dict[str, str]:
        """Form-encoded body for a single-day advanced search.

        The form has two party slots (``last``/``first``/``role`` repeated),
        joined by an ``and/or`` field whose name literally contains a
        slash. Empty values for the party/issue/casetype/status/event
        filters search every kind of docket activity.
        """
        ymd = day.strftime("%m/%d/%Y")
        return {
            "last": "",
            "first": "",
            "role": "ALL",
            "and/or": "and",
            "issues1": "ALL",
            "issuesAndOr": "AND",
            "issues2": "ALL",
            "casetype": "ALL",
            "status": "ALL",
            "event": "ALL",
            "fromDate": ymd,
            "toDate": ymd,
            "searchtype": "A",
            "search": "Search",
        }

    def _case_summary_request(
        self, docket_number: str, *, entry_point: str
    ) -> Request:
        """Build the first tab fetch (Summary) for one ``YY-NNNN`` case.

        ``AViewCase`` both sets the session's active caseid and returns the
        Summary tab; the rest of the tab chain follows from
        :meth:`parse_case_summary`.
        """
        return Request(
            request=HTTPRequestParams(
                method=HttpMethod.GET,
                url=CASE_SUMMARY_URL,
                params={"caseid": docket_number, "screen": "null"},
            ),
            continuation=self.parse_case_summary,
            accumulated_data={
                "docket_number": docket_number,
                "entry_point": entry_point,
                "source_url": (
                    f"{CASE_SUMMARY_URL}?caseid={docket_number}&screen=null"
                ),
            },
            deduplication_key=f"case_summary:{docket_number}",
        )

    # =========================================================================
    # Entry points (§4)
    # =========================================================================

    @entry(IowaDocket)
    def dockets_by_activity_date(
        self, court_ids: set[str], date_range: DateRange
    ) -> Generator[Request, None, None]:
        """Scrape every day in ``date_range`` (inclusive).

        The advanced search filters on *any* docket activity in the
        window (not the filing date), so the addressing mode is activity
        date. One POST per calendar day keeps each window under the
        2 000-row server cap (~170 cases/day → ~1 900 party rows).
        """
        start, end = date_range.start, date_range.end
        if start > end:
            start, end = end, start
        day = start
        while day <= end:
            yield Request(
                request=HTTPRequestParams(
                    method=HttpMethod.POST,
                    url=ADV_SEARCH_URL,
                    data=self._build_search_data(day),
                    headers={
                        "Content-Type": "application/x-www-form-urlencoded",
                    },
                ),
                continuation=self.parse_search_results,
                accumulated_data={
                    "search_date": day.isoformat(),
                    "entry_point": "dockets_by_activity_date",
                },
                deduplication_key=SkipDeduplicationCheck(),
            )
            day += timedelta(days=1)

    @entry(IowaDocket)
    def dockets_by_number(
        self, docket_number: YearlySpeculativeRange
    ) -> Request:
        """Speculative ``YY-NNNN`` lookup against the Summary tab.

        Speculative entries take only their speculative param (§4); the
        per-docket court is derived at assemble time, so this single entry
        covers both Iowa appellate courts.
        """
        number = f"{docket_number.year % 100:02d}-{docket_number.min:04d}"
        return self._case_summary_request(
            number, entry_point="dockets_by_number"
        )

    # =========================================================================
    # Search-side flow
    # =========================================================================

    @step(priority=6)
    def parse_search_results(
        self,
        page: PageElement,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[IowaDocket], None, None]:
        """Dispatch a case-detail fetch for each unique ``YY-NNNN`` link.

        Each case appears once as a clickable docket-number anchor; the
        other rows for the same case repeat the empty cells without an
        anchor. ``SearchResultsParser`` de-duplicates the docket numbers.
        """
        entry_point = accumulated_data.get("entry_point")
        for docket_number in SearchResultsParser()(page):
            yield self._case_summary_request(
                docket_number, entry_point=entry_point
            )

    # =========================================================================
    # Soft-404 detection (§10)
    # =========================================================================

    def actually_successful(self, response: Response) -> bool:
        """Return False when the Summary tab is the soft-404 placeholder.

        Non-existent dockets render an empty Summary template with the
        sentinel ``<!-- !EDMS -->`` HTML comment in place of the live
        ``EDMS`` span. We only apply this check to ``AViewCase`` URLs;
        other endpoints can fail genuinely.
        """
        if not response.url or "AViewCase" not in response.url:
            return True
        text = response.text or ""
        return not SOFT_404_RE.search(text)

    # =========================================================================
    # Case-detail flow (one chained step per tab)
    # =========================================================================

    @step(priority=5)
    def parse_case_summary(
        self,
        page: PageElement,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[IowaDocket], None, None]:
        """Extract Summary fields and chain into the Long Title tab."""
        docket_number = accumulated_data.get("docket_number")
        accumulated_data.update(CaseSummaryParser()(page))
        yield Request(
            request=HTTPRequestParams(
                method=HttpMethod.GET,
                url=CASE_LONG_TITLE_URL,
                params={"caseid": docket_number, "screen": "null"},
            ),
            continuation=self.parse_long_title,
            accumulated_data=accumulated_data,
        )

    @step(priority=4)
    def parse_long_title(
        self,
        page: PageElement,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[IowaDocket], None, None]:
        """Pull the formal caption (often empty) and chain into Docket."""
        docket_number = accumulated_data.get("docket_number")
        accumulated_data["case_name_full"] = LongTitleParser()(page)
        yield Request(
            request=HTTPRequestParams(
                method=HttpMethod.GET,
                url=CASE_DOCKET_URL,
                params={"caseid": docket_number, "screen": "null"},
            ),
            continuation=self.parse_docket_entries,
            accumulated_data=accumulated_data,
        )

    @step(priority=3)
    def parse_docket_entries(
        self,
        page: PageElement,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[IowaDocket], None, None]:
        """Walk the Register of Actions and chain into the Parties tab."""
        docket_number = accumulated_data.get("docket_number")
        accumulated_data["entries"] = [
            dv.confirm() for dv in DocketEntriesParser()(page)
        ]
        yield Request(
            request=HTTPRequestParams(
                method=HttpMethod.GET,
                url=CASE_PARTIES_URL,
                params={"caseid": docket_number, "screen": "null"},
            ),
            continuation=self.parse_parties,
            accumulated_data=accumulated_data,
        )

    @step(priority=2)
    def parse_parties(
        self,
        page: PageElement,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[IowaDocket], None, None]:
        """Read the Parties table and assemble the final IowaDocket."""
        accumulated_data["parties"] = [
            dv.confirm() for dv in PartiesParser()(page)
        ]
        yield from self._assemble_docket(accumulated_data)

    # =========================================================================
    # Final assembly
    # =========================================================================

    def _assemble_docket(
        self, accumulated_data: dict
    ) -> Generator[ScraperYield[IowaDocket], None, None]:
        """Combine accumulated tab data into a single IowaDocket."""
        entries: list[IowaDocketEntry] = accumulated_data.get("entries", [])
        parties: list[IowaParty] = accumulated_data.get("parties", [])

        court = self._derive_court(entries)
        date_filed = self._derive_filing_date(entries)

        yield ParsedData(
            IowaDocket.raw(
                docket_number=accumulated_data["docket_number"],
                court=court,
                date_filed=date_filed,
                case_name=accumulated_data.get("case_name") or "",
                case_name_full=accumulated_data.get("case_name_full"),
                case_type=accumulated_data.get("case_type"),
                status=accumulated_data.get("status"),
                citation=accumulated_data.get("citation"),
                appellate_judges=accumulated_data.get("appellate_judges")
                or [],
                trial_court_case_id=accumulated_data.get(
                    "trial_court_case_id"
                ),
                trial_court_county=accumulated_data.get("trial_court_county"),
                assigned_to_str=accumulated_data.get("assigned_to_str"),
                entries=entries,
                parties=parties,
                source_url=accumulated_data.get("source_url"),
                source_entry_point=accumulated_data.get("entry_point"),
            )
        )

    @staticmethod
    def _derive_court(entries: list[IowaDocketEntry]) -> str:
        """Determine ``iowa`` vs ``iowactapp`` from the docket events.

        Any ``TRANSFERRED TO COURT OF APPEALS`` event flips the case to
        the Court of Appeals; without one, it sits at the Supreme Court.
        """
        for docket_entry in entries:
            if COA_TRANSFER_SIGNAL in (docket_entry.event or "").upper():
                return "iowactapp"
        return DEFAULT_COURT_ID

    @staticmethod
    def _derive_filing_date(
        entries: list[IowaDocketEntry],
    ) -> date | None:
        """Earliest entry date — typically the Notice of Appeal."""
        dates = [e.date_filed for e in entries if e.date_filed]
        if not dates:
            return None
        return min(dates)
