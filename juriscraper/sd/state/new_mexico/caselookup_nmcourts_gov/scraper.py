"""New Mexico Case Lookup scraper.

Scrapes appellate dockets from the Tapestry-based case lookup portal at
https://caselookup.nmcourts.gov/caselookup/ for the two appellate
courts:

- ``nm`` — New Mexico Supreme Court (case prefix ``S-1-SC-``)
- ``nmctapp`` — New Mexico Court of Appeals (case prefix ``A-1-CA-``)

The site has no usable date filter or party-name search for appellate
cases, so the scraper relies on **speculative entry** against
``S-1-SC-{N}`` / ``A-1-CA-{N}`` where ``{N}`` is a continuous integer
sequence (no zero padding — the form accepts the raw number).

Per-case flow (one ``@entry`` invocation, one case):

  GET /caselookup/                              ← disclaimer or welcome
       │
       ▼
  bootstrap_session
       │
       ├── (disclaimer page) → form.submit() → fetch_search_form
       │                                         └─ GET search-form-url
       │                                              └─ parse_search_form
       │                                                   └─ form.submit()
       │                                                        └─ parse_case_detail
       │                                                             └─ ParsedData
       └── (welcome page — already accepted) → GET search-form-url → ...

After the first call's bootstrap, the same ``JSESSIONID`` cookie carries
the disclaimer-accepted state through the rest of the run, so
subsequent calls skip the disclaimer-form submit and run with three
round-trips instead of four.

Soft-404: missing case IDs return a 200 response containing the
literal text ``No results found.``. The session can also expire,
producing ``Stale Session`` or ``Your session has timed out`` pages.
``fails_successfully`` treats all three as misses; the next entry call
re-bootstraps from scratch.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import TYPE_CHECKING, ClassVar

from jkent.common.decorators import entry, step
from jkent.common.page_element import PageElement
from jkent.common.param_models import SpeculativeRange
from jkent.data_types import (
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
    NmDocket,
    NmDocketEntry,
    NmJudgeAssignment,
    NmParty,
)

if TYPE_CHECKING:
    from collections.abc import Generator

    from jkent.data_types import ScraperYield


BASE_URL = "https://caselookup.nmcourts.gov/caselookup"
LANDING_URL = f"{BASE_URL}/"
APP_URL = f"{BASE_URL}/app"
SEARCH_FORM_URL = (
    f"{APP_URL}?component=dl2&page=NameSearch&service=direct&session=T"
)


class NewMexicoCaseLookupScraper(BaseScraper[NmDocket]):
    """Scraper for the New Mexico Supreme Court and Court of Appeals.

    One speculative ``@entry`` per court so the driver advances each
    court's docket-number sequence independently. Each invocation walks
    the disclaimer / search-form / case-detail chain for a single
    docket id.
    """

    # === Metadata ===
    court_ids: ClassVar[set[str]] = {"nm", "nmctapp"}
    court_url: ClassVar[str] = LANDING_URL
    data_types: ClassVar[set[str]] = {"dockets"}
    status: ClassVar[ScraperStatus] = ScraperStatus.IN_DEVELOPMENT
    version: ClassVar[str] = "2026-05-04"
    requires_auth: ClassVar[bool] = False

    # The site rate-limits aggressively (a 60-second hard block triggers
    # at roughly one request per second during probing). Stay well clear
    # at one request every three seconds.
    rate_limits: ClassVar[list[Rate] | None] = [
        Rate(1, Duration.SECOND * 3),
    ]

    # =========================================================================
    # Entry points (one per court)
    # =========================================================================

    @entry(NmDocket)
    def fetch_supreme_court_docket(self, rid: SpeculativeRange) -> Request:
        """Speculative fetch for ``S-1-SC-{N}`` (Supreme Court)."""
        return self._build_speculative_request(
            court_type="S",
            court_location="1",
            case_category="SC",
            case_number=rid.min,
            court_id="nm",
        )

    @entry(NmDocket)
    def fetch_court_of_appeals_docket(self, rid: SpeculativeRange) -> Request:
        """Speculative fetch for ``A-1-CA-{N}`` (Court of Appeals)."""
        return self._build_speculative_request(
            court_type="A",
            court_location="1",
            case_category="CA",
            case_number=rid.min,
            court_id="nmctapp",
        )

    def _build_speculative_request(
        self,
        *,
        court_type: str,
        court_location: str,
        case_category: str,
        case_number: int,
        court_id: str,
    ) -> Request:
        """Build the bootstrap GET that opens a per-case chain.

        The returned request hits the disclaimer landing page; the
        chain of step functions handles disclaimer acceptance (when
        needed), the search-form fetch, and the search submission.
        """
        docket_id = (
            f"{court_type}-{court_location}-{case_category}-{case_number}"
        )
        return Request(
            request=HTTPRequestParams(
                method=HttpMethod.GET,
                url=LANDING_URL,
            ),
            continuation=self.bootstrap_session,
            accumulated_data={
                "docket_id": docket_id,
                "court_id": court_id,
                "court_type": court_type,
                "court_location": court_location,
                "case_category": case_category,
                "case_number": str(case_number),
            },
            deduplication_key=docket_id,
        )

    # =========================================================================
    # Soft-404 / session detection
    # =========================================================================

    def fails_successfully(self, response: Response) -> bool:
        """Return False for misses and session failures.

        Three failure modes share HTTP 200:

        - ``No results found.`` — the docket id does not exist (true miss).
        - ``Your session has timed out`` — server-side session expired.
        - ``Stale Session`` — request reached a guarded page without an
          accepted-disclaimer session.

        All three are treated as misses; the speculation driver
        advances the gap counter and the next ``@entry`` call rebuilds
        the session from scratch.

        Intermediate pages in the bootstrap chain (the disclaimer page,
        the welcome page, the search form) never carry these markers,
        so they are correctly reported as successes.
        """
        text = response.text
        if "No results found" in text:
            return False
        if "Your session has timed out" in text:
            return False
        return "Stale Session" not in text

    # =========================================================================
    # Step 1: bootstrap session (disclaimer or welcome)
    # =========================================================================

    @step()
    def bootstrap_session(
        self,
        page: PageElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[NmDocket], None, None]:
        """Either accept the disclaimer or skip straight to the form.

        On a fresh ``JSESSIONID`` the landing URL renders the
        disclaimer page; once accepted, subsequent visits in the same
        session render the welcome page directly. Detect by looking
        for the ``disclaimerForm`` component marker.
        """
        if "disclaimerForm" in response.text:
            form = page.find_form(
                "//form[.//input[@name='component'"
                " and @value='disclaimerForm']]",
                "disclaimer form",
            )
            yield form.submit(
                data={
                    "If": "T",
                    "If_0": "F",
                    "If_1": "T",
                    "Submit": "I Accept",
                },
                continuation=self.fetch_search_form,
                accumulated_data=accumulated_data,
            )
            return

        # Welcome page — disclaimer already accepted earlier in this run.
        yield from self._yield_search_form_request(accumulated_data)

    # =========================================================================
    # Step 2a: after disclaimer accept, fetch the search form
    # =========================================================================

    @step()
    def fetch_search_form(
        self,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[NmDocket], None, None]:
        """Issue the GET that renders the case-number search form."""
        yield from self._yield_search_form_request(accumulated_data)

    def _yield_search_form_request(
        self, accumulated_data: dict
    ) -> Generator[Request, None, None]:
        yield Request(
            request=HTTPRequestParams(
                method=HttpMethod.GET,
                url=SEARCH_FORM_URL,
            ),
            continuation=self.parse_search_form,
            accumulated_data=accumulated_data,
        )

    # =========================================================================
    # Step 3: submit the case-number search
    # =========================================================================

    @step()
    def parse_search_form(
        self,
        page: PageElement,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[NmDocket], None, None]:
        """Submit the search form with the speculative case-id components."""
        form = page.find_form(
            "//form[.//input[@name='component'"
            " and @value='caseNumberSearchForm']]",
            "case-number search form",
        )
        yield form.submit(
            data={
                "courtType": accumulated_data["court_type"],
                "courtLocation": accumulated_data["court_location"],
                "caseCategory": accumulated_data["case_category"],
                "caseNumber": accumulated_data["case_number"],
                "Submit": "Case Number Search",
            },
            continuation=self.parse_case_detail,
            accumulated_data=accumulated_data,
        )

    # =========================================================================
    # Step 4: parse the case detail page
    # =========================================================================

    @step()
    def parse_case_detail(
        self,
        page: PageElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[NmDocket], None, None]:
        """Parse the single-page case detail and emit one ``NmDocket``.

        ``fails_successfully`` already filters out the soft-404 / stale
        session / timeout pages, so by the time this step runs the
        response is the real case-detail page. We still re-check
        defensively so a structural mismatch doesn't crash the run.
        """
        text = response.text
        if (
            "No results found" in text
            or "Your session has timed out" in text
            or "Stale Session" in text
        ):
            return

        case_name = self._extract_case_name(page)
        case_number, current_judge, filing_date, court = (
            self._extract_case_summary(page)
        )

        # Trust the docket id we constructed; the page sometimes shows a
        # different, related case-id when no exact match exists, but
        # ``fails_successfully`` handles that path. If the page *does*
        # show a docket id, prefer it over our constructed value.
        docket_id = case_number or accumulated_data["docket_id"]

        docket = NmDocket(
            docket_id=docket_id,
            court_id=accumulated_data["court_id"],
            date_filed=filing_date,
            case_name=case_name or docket_id,
            current_judge=current_judge,
            court=court,
            entries=(
                self._extract_hearings(page)
                + self._extract_register_of_actions(page)
            ),
            parties=self._extract_parties(page),
            judge_assignments=self._extract_judge_assignments(page),
            source_url=response.url,
        )
        yield ParsedData(data=docket)

    # =========================================================================
    # Parsing helpers
    # =========================================================================

    def _extract_case_name(self, page: PageElement) -> str | None:
        """Pull the case caption from the page heading."""
        headings = page.query_xpath(
            "//h2//span[1]",
            "case name heading",
            min_count=0,
            max_count=1,
        )
        if headings:
            return _clean(headings[0].text_content())
        # Fall back to the bare h2 text
        h2s = page.query_xpath(
            "//h2", "case name h2", min_count=0, max_count=1
        )
        if h2s:
            return _clean(h2s[0].text_content())
        return None

    def _extract_case_summary(
        self, page: PageElement
    ) -> tuple[str | None, str | None, date | None, str | None]:
        """Parse the four-cell row beneath the ``Case Detail`` heading.

        Returns ``(case_number, current_judge, filing_date, court)``.
        """
        rows = self._rows_under_section(page, "Case Detail")
        # Skip the column-header row; the data row sits below it.
        for row in rows:
            cells = row.query_xpath(".//td", "case-summary cells", min_count=0)
            if len(cells) < 4:
                continue
            texts = [_clean(c.text_content()) for c in cells]
            # The header row has labels; data row has actual values.
            if any(texts) and "Case Number" in texts[0]:
                continue
            return (
                texts[0] or None,
                texts[1] or None,
                _parse_us_date(texts[2]),
                texts[3] or None,
            )
        return None, None, None, None

    def _extract_parties(self, page: PageElement) -> list[NmParty]:
        """Parse the ``Parties to this Case`` table."""
        out: list[NmParty] = []
        for row in self._rows_under_section(page, "Parties to this Case"):
            cells = row.query_xpath(".//td", "party cells", min_count=0)
            if len(cells) < 4:
                continue
            texts = [_clean(c.text_content()) for c in cells]
            if texts[0] == "Party Type":  # column-header row
                continue
            if not texts[0] and not texts[3]:
                continue
            out.append(
                NmParty(
                    party_type=texts[0] or "",
                    party_description=texts[1] or None,
                    party_number=texts[2] or None,
                    name=texts[3] or "",
                )
            )
        return out

    def _extract_hearings(self, page: PageElement) -> list[NmDocketEntry]:
        """Parse the ``Hearings for this Case`` table.

        Hearings are folded into ``entries`` with ``entry_kind='hearing'``
        per the project convention that future-calendar / scheduled-
        hearing items are docket-entries, not a parallel data type.
        """
        out: list[NmDocketEntry] = []
        for row in self._rows_under_section(page, "Hearings for this Case"):
            cells = row.query_xpath(".//td", "hearing cells", min_count=0)
            if len(cells) < 6:
                continue
            texts = [_clean(c.text_content()) for c in cells]
            if texts[0] == "Hearing Date":
                continue
            if not texts[0] and not texts[2]:
                continue
            out.append(
                NmDocketEntry(
                    entry_kind="hearing",
                    date_filed=_parse_us_date(texts[0]),
                    description=texts[2] or "",
                    hearing_time=texts[1] or None,
                    hearing_judge=texts[3] or None,
                    court=texts[4] or None,
                    court_room=texts[5] or None,
                )
            )
        return out

    def _extract_register_of_actions(
        self, page: PageElement
    ) -> list[NmDocketEntry]:
        """Parse the ``Register of Actions Activity`` table.

        Some rows are 2-cell sub-rows carrying free-text supplemental
        content (motion title, brief title, attorney name) — those
        are appended to the preceding event's ``notes`` rather than
        being modelled as their own entry.
        """
        out: list[NmDocketEntry] = []
        for row in self._rows_under_section(
            page, "Register of Actions Activity"
        ):
            cells = row.query_xpath(".//td", "action cells", min_count=0)
            if not cells:
                continue
            texts = [_clean(c.text_content()) for c in cells]

            # Column-header row is exactly the labels:
            if texts[0] == "Event Date":
                continue

            # Sub-row: typically 2 cells, the second carrying notes.
            if len(cells) <= 2:
                note_text = next((t for t in texts if t), "")
                if out and note_text:
                    out[-1] = _append_notes(out[-1], note_text)
                continue

            # Standard 6-column event row.
            if len(cells) < 6:
                continue
            out.append(
                NmDocketEntry(
                    entry_kind="action",
                    date_filed=_parse_us_date(texts[0]),
                    description=texts[1] or "",
                    event_result=texts[2] or None,
                    party_type=texts[3] or None,
                    party_number=texts[4] or None,
                    amount=texts[5] or None,
                )
            )
        return out

    def _extract_judge_assignments(
        self, page: PageElement
    ) -> list[NmJudgeAssignment]:
        """Parse the ``Judge Assignment History`` table."""
        out: list[NmJudgeAssignment] = []
        for row in self._rows_under_section(page, "Judge Assignment History"):
            cells = row.query_xpath(
                ".//td", "judge-assignment cells", min_count=0
            )
            if len(cells) < 4:
                continue
            texts = [_clean(c.text_content()) for c in cells]
            if texts[0] == "Assignment Date":
                continue
            if not any(texts):
                continue
            out.append(
                NmJudgeAssignment(
                    assignment_date=_parse_us_date(texts[0]),
                    judge_name=texts[1] or None,
                    sequence_number=texts[2] or None,
                    assignment_event_description=texts[3] or None,
                )
            )
        return out

    def _rows_under_section(
        self, page: PageElement, section_title: str
    ) -> list[PageElement]:
        """Return all data rows in the table whose first cell matches.

        The case-detail page renders each section as its own ``<table>``
        whose first ``<tr>`` is a single-cell heading row carrying the
        section title (``Case Detail``, ``Parties to this Case``, etc.).
        Locate that table, then return every row *after* the heading.
        """
        return page.query_xpath(
            f"//table[.//tr[1]/td[normalize-space(.)="
            f"{_xpath_string(section_title)}]]"
            f"//tr[position() > 1]",
            f"{section_title} rows",
            min_count=0,
        )


# =============================================================================
# Module-level helpers
# =============================================================================

_DATE_RE = re.compile(r"\b(\d{1,2}/\d{1,2}/\d{4})\b")


def _clean(text: str | None) -> str:
    """Collapse whitespace and trim."""
    if not text:
        return ""
    return re.sub(r"\s+", " ", text).strip()


def _parse_us_date(value: str | None) -> date | None:
    """Parse ``MM/DD/YYYY`` from a (possibly noisy) cell value."""
    if not value:
        return None
    match = _DATE_RE.search(value)
    if not match:
        return None
    try:
        return datetime.strptime(match.group(1), "%m/%d/%Y").date()
    except ValueError:
        return None


def _append_notes(entry: NmDocketEntry, extra: str) -> NmDocketEntry:
    """Return a copy of ``entry`` with ``extra`` folded into ``notes``."""
    if not extra:
        return entry
    notes = f"{entry.notes} | {extra}" if entry.notes else extra
    return entry.model_copy(update={"notes": notes})


def _xpath_string(value: str) -> str:
    """Produce an XPath string literal that survives embedded quotes.

    XPath 1.0 has no escape sequence inside string literals. If the
    text contains both kinds of quotes, fall back to ``concat()``;
    otherwise wrap in the safer quote.
    """
    if "'" not in value:
        return f"'{value}'"
    if '"' not in value:
        return f'"{value}"'
    parts = value.split("'")
    joined = ', "\'", '.join(f"'{p}'" for p in parts)
    return f"concat({joined})"
