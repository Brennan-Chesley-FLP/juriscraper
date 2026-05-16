"""Iowa Appellate Courts Scraper.

Scrapes docket data from the Iowa Judicial Branch's Iowa Courts Online
(ESAWebApp) system at iowacourts.state.ia.us.

Supported courts:

- Supreme Court of Iowa (``iowa``)
- Court of Appeals of Iowa (``iowactapp``)

Both share a unified ``YY-NNNN`` docket number space; cases sit at the
Supreme Court until a ``TRANSFERRED TO COURT OF APPEALS`` docket event
moves them to the CoA. The scraper emits ``court_id`` based on the
presence of that event.

Entry points:

- ``get_dockets_by_date(date_range)`` — incremental scrape via the
  advanced search, splitting the requested window into one-day slices to
  stay below the server's 2 000-row cap.
- ``fetch_iowa_docket(case_id: YearlySpeculativeRange)`` — backlog
  speculation, one probe per ``YY-NNNN`` directly against ``AViewCase``.

The site requires Playwright: the Akamai Bot Manager fronting the
application returns HTTP 200 with an empty body to non-browser clients.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING, ClassVar

from jkent.common.decorators import entry, step
from jkent.common.page_element import PageElement
from jkent.common.param_models import DateRange, YearlySpeculativeRange
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

if TYPE_CHECKING:
    from collections.abc import Generator

    from jkent.data_types import ScraperYield


# Docket numbers are exactly ``YY-NNNN``.
DOCKET_RE = re.compile(r"^\d{2}-\d{4}$")

# Pattern attorney/party links use to identify the underlying record:
# /ESAWebApp/AViewAttorney?AT0014845  or  ?SC1000371  or  ?STATEIOWA
ATTORNEY_LINK_RE = re.compile(r"AViewAttorney\?(.+)$")

# Soft-404 signal: real cases render an EDMS span; non-existent cases
# render an HTML comment ``<!-- !EDMS -->`` (note the leading bang).
SOFT_404_RE = re.compile(r"<!--\s*!EDMS\s*-->")


class IowaAppellateScraper(BaseScraper[IowaDocket]):
    """Scraper for Iowa Supreme Court and Court of Appeals dockets.

    Usage::

        # Scrape last 24h of activity (default)
        scraper = IowaAppellateScraper()

        # Scrape an explicit date range
        params = IowaAppellateScraper.params()
        params.IowaDocket.date_filed.gte = date(2026, 4, 20)
        params.IowaDocket.date_filed.lte = date(2026, 4, 22)
        scraper = IowaAppellateScraper(params=params)
    """

    court_ids: ClassVar[set[str]] = {"iowa", "iowactapp"}
    court_url: ClassVar[str] = (
        "https://www.iowacourts.state.ia.us/ESAWebApp/SelectFrame"
    )
    data_types: ClassVar[set[str]] = {"dockets"}
    status: ClassVar[ScraperStatus] = ScraperStatus.IN_DEVELOPMENT
    version: ClassVar[str] = "2026-05-03"
    requires_auth: ClassVar[bool] = False

    rate_limits: ClassVar[list[Rate] | None] = [Rate(2, Duration.SECOND)]

    driver_requirements: ClassVar[list[DriverRequirement]] = [
        DriverRequirement.JS_EVAL,
        DriverRequirement.FF_ALIKE,
    ]

    # =========================================================================
    # Helpers
    # =========================================================================

    @staticmethod
    def _parse_date(value: str | None) -> date | None:
        """Parse a ``MM/DD/YYYY`` date string."""
        if not value:
            return None
        s = value.strip()
        if not s:
            return None
        try:
            return datetime.strptime(s, "%m/%d/%Y").date()
        except ValueError:
            return None

    @staticmethod
    def _clean_text(text: str | None) -> str:
        """Collapse whitespace and trim non-breaking spaces."""
        if not text:
            return ""
        return re.sub(r"\s+", " ", text.replace("\xa0", " ")).strip()

    def _get_date_window(self) -> tuple[date, date]:
        """Resolve the active scraper params into a date window.

        Falls back to the most recent day of activity when no params are
        supplied (the typical "incremental" run mode).
        """
        date_gte: date | None = None
        date_lte: date | None = None
        if self._params is not None:
            try:
                proxy = self._params.IowaDocket
                searchable = proxy.get_searchable_fields()
                date_field = searchable.get("date_filed")
                if date_field is not None:
                    date_gte = getattr(date_field, "gte", None)
                    date_lte = getattr(date_field, "lte", None)
            except AttributeError:
                pass

        if date_lte is None:
            date_lte = date.today()
        if date_gte is None:
            date_gte = date_lte - timedelta(days=1)

        return date_gte, date_lte

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

    # =========================================================================
    # Entry points
    # =========================================================================

    @entry(IowaDocket)
    def get_dockets(self) -> Generator[Request, None, None]:
        """Scrape based on the scraper's active params (default: yesterday)."""
        start, end = self._get_date_window()
        yield from self._yield_daily_searches(start, end)

    @entry(IowaDocket)
    def get_dockets_by_date(
        self, date_range: DateRange
    ) -> Generator[Request, None, None]:
        """Scrape every day in ``date_range`` (inclusive)."""
        yield from self._yield_daily_searches(date_range.start, date_range.end)

    @entry(IowaDocket)
    def fetch_iowa_docket(self, case_id: YearlySpeculativeRange) -> Request:
        """Speculative ``YY-NNNN`` lookup against the Summary tab."""
        docket_id = f"{case_id.year % 100:02d}-{case_id.min:04d}"
        return Request(
            request=HTTPRequestParams(
                method=HttpMethod.GET,
                url=CASE_SUMMARY_URL,
                params={"caseid": docket_id, "screen": "null"},
            ),
            continuation=self.parse_case_summary,
            accumulated_data={
                "docket_id": docket_id,
                "source_url": (
                    f"{CASE_SUMMARY_URL}?caseid={docket_id}&screen=null"
                ),
            },
            deduplication_key=f"iowa-docket-{docket_id}",
        )

    # =========================================================================
    # Search-side flow
    # =========================================================================

    def _yield_daily_searches(
        self, start: date, end: date
    ) -> Generator[Request, None, None]:
        """One advanced-search POST per calendar day in the window.

        The 2 000-row server cap limits each window to roughly a single day
        of statewide activity (~170 cases / day → ~1 900 rows when each
        case spans several party rows).
        """
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
                accumulated_data={"search_date": day.isoformat()},
                deduplication_key=SkipDeduplicationCheck(),
            )
            day += timedelta(days=1)

    @step()
    def parse_search_results(
        self,
        page: PageElement,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[IowaDocket], None, None]:
        """Pull every ``YY-NNNN`` link out of the result table.

        Each case appears once as a clickable docket-number anchor with
        ``href="javascript:mySubmit('YY-NNNN')"``; the other rows in the
        same case repeat the empty cells without an anchor. Deduping on
        the docket id is handled at request-yield time via
        ``deduplication_key``.
        """
        # The clickable docket-number cells are <a href="javascript:mySubmit('YY-NNNN')">YY-NNNN</a>.
        anchors = page.query_xpath(
            "//a[starts-with(@href, 'javascript:mySubmit')]",
            "search-result docket links",
            min_count=0,
        )

        seen: set[str] = set()
        for anchor in anchors:
            text = self._clean_text(anchor.text_content())
            if not DOCKET_RE.match(text) or text in seen:
                continue
            seen.add(text)
            yield Request(
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url=CASE_SUMMARY_URL,
                    params={"caseid": text, "screen": "null"},
                ),
                continuation=self.parse_case_summary,
                accumulated_data={
                    "docket_id": text,
                    "source_url": (
                        f"{CASE_SUMMARY_URL}?caseid={text}&screen=null"
                    ),
                },
                deduplication_key=f"iowa-docket-{text}",
            )

    # =========================================================================
    # Soft-404 detection
    # =========================================================================

    def fails_successfully(self, response: Response) -> bool:
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

    @step()
    def parse_case_summary(
        self,
        page: PageElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[IowaDocket], None, None]:
        """Extract Summary fields and chain into the Long Title tab."""
        docket_id = accumulated_data.get("docket_id")

        short_title_cells = page.query_xpath_strings(
            "//b[normalize-space()='Summary']/following::text()[contains(., 'Short Title:')][1]",
            "short title text",
            min_count=0,
            max_count=1,
        )
        case_name = ""
        if short_title_cells:
            raw = self._clean_text(short_title_cells[0])
            case_name = raw.split(":", 1)[-1].strip()

        # The four primary cells (Docket No., Case Type, Status, Trial
        # Court Judge) sit in the row immediately after the header row.
        # Iterate <td> elements (not their text nodes) so empty cells keep
        # their position.
        primary_tds = page.query_xpath(
            "//tr[td/b/u[normalize-space()='Docket No.']]/following-sibling::tr[1]/td",
            "summary primary cells",
            min_count=0,
        )
        primary_text = [
            self._clean_text(td.text_content()) for td in primary_tds
        ]
        case_type = primary_text[1] if len(primary_text) > 1 else None
        status = primary_text[2] if len(primary_text) > 2 else None
        trial_court_judge = primary_text[3] if len(primary_text) > 3 else None
        # Normalize empty-string to None.
        case_type = case_type or None
        status = status or None
        trial_court_judge = trial_court_judge or None

        # Appellate Judges section (or "No Judges Listed").
        judges_cells = page.query_xpath_strings(
            "//tr[td/b/u[normalize-space()='Appellate Judges/Justices']]/following-sibling::tr[1]/td/text()",
            "appellate judge cells",
            min_count=0,
        )
        appellate_judges: list[str] = []
        for raw in judges_cells:
            cleaned = self._clean_text(raw).strip('"')
            if cleaned and "No Judges Listed" not in cleaned:
                appellate_judges.append(cleaned)

        # Trial Court Case ID + Originating County row.
        tc_cells = page.query_xpath_strings(
            "//tr[td/b/u[normalize-space()='Trial Court Case ID']]/following-sibling::tr[1]/td/text()",
            "trial court info cells",
            min_count=0,
        )
        tc_clean = [
            self._clean_text(c) for c in tc_cells if self._clean_text(c)
        ]
        trial_court_case_id: str | None = None
        trial_court_county: str | None = None
        if tc_clean and "No Trial Court Cases Listed" not in tc_clean[0]:
            trial_court_case_id = tc_clean[0]
            if len(tc_clean) > 1:
                trial_court_county = tc_clean[1]

        # Cite section.
        cite_cells = page.query_xpath_strings(
            "//tr[td/b/u[normalize-space()='Cite']]/following-sibling::tr[1]/td/text()",
            "cite cells",
            min_count=0,
        )
        citation: str | None = None
        for raw in cite_cells:
            cleaned = self._clean_text(raw).strip('"')
            if cleaned and "No Cite Listed" not in cleaned:
                citation = cleaned
                break

        accumulated_data.update(
            {
                "case_name": case_name,
                "case_type": case_type or None,
                "status": status or None,
                "trial_court_judge": trial_court_judge,
                "appellate_judges": appellate_judges,
                "trial_court_case_id": trial_court_case_id,
                "trial_court_county": trial_court_county,
                "citation": citation,
            }
        )

        yield Request(
            request=HTTPRequestParams(
                method=HttpMethod.GET,
                url=CASE_LONG_TITLE_URL,
                params={"caseid": docket_id, "screen": "null"},
            ),
            continuation=self.parse_long_title,
            accumulated_data=accumulated_data,
        )

    @step()
    def parse_long_title(
        self,
        page: PageElement,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[IowaDocket], None, None]:
        """Pull the formal caption (often empty) and chain into Docket."""
        docket_id = accumulated_data.get("docket_id")

        # The caption sits inside a <font face="Courier New"> block in the
        # row that follows the header. Empty cases render an empty <br>.
        long_title_parts = page.query_xpath_strings(
            "//font[contains(@face, 'Courier')]//text()",
            "long-title text",
            min_count=0,
        )
        cleaned = self._clean_text(" ".join(long_title_parts))
        accumulated_data["case_name_full"] = cleaned or None

        yield Request(
            request=HTTPRequestParams(
                method=HttpMethod.GET,
                url=CASE_DOCKET_URL,
                params={"caseid": docket_id, "screen": "null"},
            ),
            continuation=self.parse_docket_entries,
            accumulated_data=accumulated_data,
        )

    @step()
    def parse_docket_entries(
        self,
        page: PageElement,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[IowaDocket], None, None]:
        """Walk the Register of Actions and chain into the Parties tab."""
        docket_id = accumulated_data.get("docket_id")

        # Each event sits in a <tr> whose first comment is "<!-- Event ID #N -->".
        # The follow-on <tr> with the optional Comments: text is a sibling.
        event_rows = page.query_xpath(
            "//tr[comment()[contains(., 'Event ID #')]]",
            "docket event rows",
            min_count=0,
        )

        entries: list[dict] = []
        for row in event_rows:
            # <td> in row order; preserves empty cells (Date Served and
            # Due Date are frequently blank).
            tds = row.query_xpath("./td", "event row cells", min_count=0)
            cells = [self._clean_text(td.text_content()) for td in tds]
            if not cells or len(cells) < 3:
                continue

            # Pull the event id from the leading <!-- Event ID #N --> comment
            # by searching the row's raw HTML — XPath string-coercion of a
            # comment node is unreliable across lxml versions.
            event_id: str | None = None
            m = re.search(r"Event ID #(\d+)", row.inner_html())
            if m:
                event_id = m.group(1)

            # Cell order: [date_filed, date_served, event, filed_by, due_date].
            date_filed = self._parse_date(cells[0])
            date_served = (
                self._parse_date(cells[1]) if len(cells) > 1 else None
            )
            event_text = cells[2] if len(cells) > 2 else ""
            filed_by = cells[3] if len(cells) > 3 else None
            due_date = self._parse_date(cells[4]) if len(cells) > 4 else None

            # Comments row is the next sibling <tr> when present.
            notes: str | None = None
            comment_texts = row.query_xpath_strings(
                "following-sibling::tr[1][.//i[normalize-space()='Comments:']]"
                "//td//text()",
                "comments cell text",
                min_count=0,
            )
            if comment_texts:
                blob = self._clean_text(" ".join(comment_texts))
                blob = re.sub(r"^Comments:\s*", "", blob)
                notes = blob or None

            entries.append(
                {
                    "date_filed": date_filed.isoformat()
                    if date_filed
                    else None,
                    "date_served": (
                        date_served.isoformat() if date_served else None
                    ),
                    "event": event_text,
                    "filed_by": filed_by or None,
                    "due_date": due_date.isoformat() if due_date else None,
                    "notes": notes,
                    "event_id": event_id,
                }
            )

        accumulated_data["entries"] = entries

        yield Request(
            request=HTTPRequestParams(
                method=HttpMethod.GET,
                url=CASE_PARTIES_URL,
                params={"caseid": docket_id, "screen": "null"},
            ),
            continuation=self.parse_parties,
            accumulated_data=accumulated_data,
        )

    @step()
    def parse_parties(
        self,
        page: PageElement,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[IowaDocket], None, None]:
        """Read the Parties table and assemble the final IowaDocket."""
        # Skip the header row (Name | Role | Status); every subsequent row
        # has three cells in the same order.
        rows = page.query_xpath(
            "//tr[td[a[contains(@href, 'AViewAttorney')]]]",
            "party rows",
            min_count=0,
        )

        parties: list[dict] = []
        for row in rows:
            anchors = row.query_xpath(
                ".//a[contains(@href, 'AViewAttorney')]",
                "party link",
                min_count=0,
                max_count=1,
            )
            if not anchors:
                continue
            name = self._clean_text(anchors[0].text_content())
            href = anchors[0].get_attribute("href") or ""
            site_id_match = ATTORNEY_LINK_RE.search(href)
            site_id = site_id_match.group(1) if site_id_match else None

            tds = row.query_xpath("./td", "party cells", min_count=0)
            cell_texts = [self._clean_text(td.text_content()) for td in tds]
            # cells == [name, role, status]
            role = cell_texts[1] if len(cell_texts) > 1 else ""
            status = (
                cell_texts[2]
                if len(cell_texts) > 2 and cell_texts[2]
                else None
            )

            parties.append(
                {
                    "name": name,
                    "role": role,
                    "status": status,
                    "site_id": site_id,
                }
            )

        accumulated_data["parties"] = parties

        yield from self._assemble_docket(accumulated_data)

    # =========================================================================
    # Final assembly
    # =========================================================================

    def _assemble_docket(
        self, accumulated_data: dict
    ) -> Generator[ScraperYield[IowaDocket], None, None]:
        """Combine accumulated tab data into a single IowaDocket."""
        entries = [
            IowaDocketEntry(
                date_filed=(
                    date.fromisoformat(e["date_filed"])
                    if e.get("date_filed")
                    else None
                ),
                date_served=(
                    date.fromisoformat(e["date_served"])
                    if e.get("date_served")
                    else None
                ),
                event=e["event"],
                filed_by=e.get("filed_by"),
                due_date=(
                    date.fromisoformat(e["due_date"])
                    if e.get("due_date")
                    else None
                ),
                notes=e.get("notes"),
                event_id=e.get("event_id"),
            )
            for e in accumulated_data.get("entries", [])
        ]

        parties = [
            IowaParty(
                name=p["name"],
                role=p["role"],
                status=p.get("status"),
                site_id=p.get("site_id"),
            )
            for p in accumulated_data.get("parties", [])
        ]

        court_id = self._derive_court_id(entries)
        date_filed = self._derive_filing_date(entries)

        docket = IowaDocket(
            docket_id=accumulated_data["docket_id"],
            court_id=court_id,
            date_filed=date_filed,
            case_name=accumulated_data.get("case_name") or "",
            case_name_full=accumulated_data.get("case_name_full"),
            case_type=accumulated_data.get("case_type"),
            status=accumulated_data.get("status"),
            citation=accumulated_data.get("citation"),
            appellate_judges=accumulated_data.get("appellate_judges") or [],
            trial_court_case_id=accumulated_data.get("trial_court_case_id"),
            trial_court_county=accumulated_data.get("trial_court_county"),
            trial_court_judge=accumulated_data.get("trial_court_judge"),
            entries=entries,
            parties=parties,
            source_url=accumulated_data.get("source_url"),
        )
        yield ParsedData(data=docket)

    @staticmethod
    def _derive_court_id(entries: list[IowaDocketEntry]) -> str:
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
