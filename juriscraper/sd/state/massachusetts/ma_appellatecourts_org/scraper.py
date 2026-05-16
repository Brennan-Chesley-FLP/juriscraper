"""Massachusetts Appellate Courts Scraper.

Scrapes dockets and oral arguments from the Massachusetts SJC and
Appeals Court at https://www.ma-appellatecourts.org.

Supported courts:

- ``mass`` — Supreme Judicial Court of Massachusetts
- ``massappct`` — Massachusetts Appeals Court

The site is fronted by Cloudflare's managed challenge so the scraper
must run under a real browser (``JS_EVAL`` + ``FF_ALIKE``). Once the
challenge is satisfied we lean on the fact that *every* case is
reachable at ``/docket/{docket_id}`` regardless of the search path.

Entry strategy:

- One **speculative** entry per (court, case-type) combination. The
  driver advances each docket-number sequence independently.
- Four oral-argument calendar entries (one per calendar type). The
  calendar pages only show the *current* month, so these have no
  date-range parameter.

Per-case flow:

  fetch_*_docket
       │
       ▼
  parse_case_detail
       │
       ├── ParsedData(MaDocket)
       └── for each PDF link:
              archive Request → handle_document_download
                                    │
                                    ▼
                                ParsedData(MaDocument)

Soft-404 detection: invalid docket URLs *redirect* to ``/docket`` (the
search landing) rather than returning 404. ``fails_successfully``
detects this by checking the final response URL.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import TYPE_CHECKING, ClassVar
from urllib.parse import urljoin

from jkent.common.decorators import entry, step
from jkent.common.page_element import PageElement
from jkent.common.param_models import SpeculativeRange, YearlySpeculativeRange
from jkent.data_types import (
    BaseScraper,
    DriverRequirement,
    HttpMethod,
    HTTPRequestParams,
    ParsedData,
    Request,
    Response,
    ScraperStatus,
)
from pyrate_limiter import Duration, Rate

from .models import (
    CASE_TYPE_NAMES,
    COURT_APPEALS,
    COURT_SJC,
    MaAttorney,
    MaDocket,
    MaDocketEntry,
    MaDocument,
    MaOralArgument,
    MaOralArgumentCase,
    MaParty,
    MaScheduledHearing,
)

if TYPE_CHECKING:
    from collections.abc import Generator

    from jkent.data_types import ScraperYield


BASE_URL = "https://www.ma-appellatecourts.org"
DOCKET_URL = f"{BASE_URL}/docket"


# ─── Regexes for parsing surface strings ─────────────────────────────
_DATE_RE = re.compile(r"\b(\d{1,2}/\d{1,2}/\d{4})\b")
_ATTORNEY_ID_RE = re.compile(r"/attorney/(\d+)")
_SESSION_DATE_RE = re.compile(
    r"(?P<wd>\w+),\s+(?P<mon>\w+)\s+(?P<day>\d+)(?:st|nd|rd|th)?\s+"
    r"(?P<year>\d{4}),\s+(?P<time>\d{1,2}:\d{2}\s*[AP]M)",
    re.IGNORECASE,
)


# Per-entry-method config:
# (court_id, case_category_label, formatter)
_FORMATTERS: dict[str, tuple[str, str, str]] = {
    "fetch_sjc_full_court_docket": (COURT_SJC, "fc", "SJC-{n:05d}"),
    "fetch_sjc_original_entry_docket": (COURT_SJC, "oe", "OE-{n:04d}"),
    "fetch_sjc_far_application_docket": (COURT_SJC, "ar", "FAR-{n:05d}"),
    "fetch_sjc_single_justice_docket": (COURT_SJC, "sj", "SJ-{y}-{n:04d}"),
    "fetch_sjc_bar_docket": (COURT_SJC, "bd", "BD-{y}-{n:03d}"),
    "fetch_appeals_panel_docket": (COURT_APPEALS, "ac", "{y}-P-{n:04d}"),
    "fetch_appeals_single_justice_docket": (
        COURT_APPEALS,
        "aj",
        "{y}-J-{n:04d}",
    ),
}


class MassachusettsAppellateScraper(
    BaseScraper[MaDocket | MaDocument | MaOralArgument]
):
    """Scraper for the Massachusetts SJC and Appeals Court.

    All seven case-type categories share the same case-detail page
    layout, so a single ``parse_case_detail`` step services every
    speculative entry.
    """

    # === Metadata ===
    court_ids: ClassVar[set[str]] = {COURT_SJC, COURT_APPEALS}
    court_url: ClassVar[str] = BASE_URL
    data_types: ClassVar[set[str]] = {"dockets", "oral_arguments"}
    status: ClassVar[ScraperStatus] = ScraperStatus.IN_DEVELOPMENT
    version: ClassVar[str] = "2026-05-03"
    requires_auth: ClassVar[bool] = False

    rate_limits: ClassVar[list[Rate] | None] = [Rate(2, Duration.SECOND)]

    # Cloudflare managed challenge gates everything, so we need a
    # real browser.
    driver_requirements: ClassVar[list[DriverRequirement]] = [
        DriverRequirement.JS_EVAL,
        DriverRequirement.FF_ALIKE,
    ]

    # =========================================================================
    # Entry points — one per (court, case-type) combination
    # =========================================================================

    @entry(MaDocket)
    def fetch_sjc_full_court_docket(self, rid: SpeculativeRange) -> Request:
        """Speculative fetch for ``SJC-NNNNN`` (SJC Full Court Cases)."""
        return self._build_speculative_request(
            "fetch_sjc_full_court_docket", rid.min
        )

    @entry(MaDocket)
    def fetch_sjc_original_entry_docket(
        self, rid: SpeculativeRange
    ) -> Request:
        """Speculative fetch for ``OE-NNNN`` (SJC Original Entry)."""
        return self._build_speculative_request(
            "fetch_sjc_original_entry_docket", rid.min
        )

    @entry(MaDocket)
    def fetch_sjc_far_application_docket(
        self, rid: SpeculativeRange
    ) -> Request:
        """Speculative fetch for ``FAR-NNNNN`` (DAR/FAR applications)."""
        return self._build_speculative_request(
            "fetch_sjc_far_application_docket", rid.min
        )

    @entry(MaDocket)
    def fetch_sjc_single_justice_docket(
        self, rid: YearlySpeculativeRange
    ) -> Request:
        """Speculative fetch for ``SJ-YYYY-NNNN`` (SJC Single Justice)."""
        return self._build_speculative_request(
            "fetch_sjc_single_justice_docket", rid.min, year=rid.year
        )

    @entry(MaDocket)
    def fetch_sjc_bar_docket(self, rid: YearlySpeculativeRange) -> Request:
        """Speculative fetch for ``BD-YYYY-NNN`` (SJC Bar Docket)."""
        return self._build_speculative_request(
            "fetch_sjc_bar_docket", rid.min, year=rid.year
        )

    @entry(MaDocket)
    def fetch_appeals_panel_docket(
        self, rid: YearlySpeculativeRange
    ) -> Request:
        """Speculative fetch for ``YYYY-P-NNNN`` (Appeals Court Panel)."""
        return self._build_speculative_request(
            "fetch_appeals_panel_docket", rid.min, year=rid.year
        )

    @entry(MaDocket)
    def fetch_appeals_single_justice_docket(
        self, rid: YearlySpeculativeRange
    ) -> Request:
        """Speculative fetch for ``YYYY-J-NNNN`` (Appeals Single Justice)."""
        return self._build_speculative_request(
            "fetch_appeals_single_justice_docket", rid.min, year=rid.year
        )

    def _build_speculative_request(
        self, formatter_key: str, n: int, year: int | None = None
    ) -> Request:
        court_id, category, fmt = _FORMATTERS[formatter_key]
        if year is None:
            docket_id = fmt.format(n=n)
        else:
            docket_id = fmt.format(n=n, y=year)
        url = f"{DOCKET_URL}/{docket_id}"
        return Request(
            request=HTTPRequestParams(
                method=HttpMethod.GET,
                url=url,
                headers={"Accept": "text/html"},
            ),
            continuation=self.parse_case_detail,
            accumulated_data={
                "docket_id": docket_id,
                "court_id": court_id,
                "case_category": CASE_TYPE_NAMES.get(category),
                "site_category": category,
            },
            deduplication_key=docket_id,
        )

    # =========================================================================
    # Calendar entry points (one per calendar type)
    # =========================================================================

    @entry(MaOralArgument)
    def get_sjc_full_court_calendar(self) -> Generator[Request, None, None]:
        """Scrape the SJC Full Court current-month sitting list."""
        yield from self._build_calendar_request("fc", COURT_SJC)

    @entry(MaOralArgument)
    def get_sjc_single_justice_calendar(
        self,
    ) -> Generator[Request, None, None]:
        """Scrape the SJC Single Justice current-month sitting list."""
        yield from self._build_calendar_request("sj", COURT_SJC)

    @entry(MaOralArgument)
    def get_appeals_panel_calendar(self) -> Generator[Request, None, None]:
        """Scrape the Appeals Court Panel current-month sitting list."""
        yield from self._build_calendar_request("ac", COURT_APPEALS)

    @entry(MaOralArgument)
    def get_appeals_single_justice_calendar(
        self,
    ) -> Generator[Request, None, None]:
        """Scrape the Appeals Court Single Justice current-month list."""
        yield from self._build_calendar_request("aj", COURT_APPEALS)

    def _build_calendar_request(
        self, calendar_type: str, court_id: str
    ) -> Generator[Request, None, None]:
        url = f"{BASE_URL}/calendar/{calendar_type}"
        yield Request(
            request=HTTPRequestParams(
                method=HttpMethod.GET,
                url=url,
                headers={"Accept": "text/html"},
            ),
            continuation=self.parse_calendar,
            accumulated_data={
                "calendar_type": calendar_type,
                "court_id": court_id,
            },
        )

    # =========================================================================
    # Soft-404 detection
    # =========================================================================

    def fails_successfully(self, response: Response) -> bool:
        """Return False for speculative misses on case-detail GETs.

        The site redirects unknown docket IDs back to ``/docket`` (the
        search landing) rather than 404'ing. Detect this by checking
        whether the final response URL still includes the requested
        docket id in its path. Calendar URLs always succeed and so are
        passed through unchanged.
        """
        url = response.url or ""
        if "/docket/" not in url:
            # Either a calendar URL (always OK) or the redirect to the
            # bare /docket landing — i.e. a miss.
            return "/calendar/" in url
        return True

    # =========================================================================
    # Step: parse a case-detail page
    # =========================================================================

    @step()
    def parse_case_detail(
        self,
        page: PageElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[MaDocket | MaDocument], None, None]:
        """Parse a ``/docket/{id}`` page into a ``MaDocket`` (and yield
        an ``archive=True`` request for each PDF in the DOCUMENTS
        block)."""
        docket_id = accumulated_data["docket_id"]
        court_id = accumulated_data["court_id"]

        case_name = _first(page, "//div[@class='docket-header-1'][2]/text()")
        is_impounded = bool(
            page.query_xpath_strings(
                "//div[contains(@class,'docket-header')]"
                "//*[contains(text(),'IMPOUNDED')]/text()",
                "impounded marker",
                min_count=0,
            )
        )

        header = _collect_header_fields(page)

        docket = MaDocket(
            docket_id=docket_id,
            court_id=court_id,
            case_name=(case_name or docket_id).strip(),
            date_filed=_parse_date(header.get("Entry Date")),
            case_category=accumulated_data.get("case_category"),
            case_type=header.get("Case Type"),
            nature=header.get("Nature"),
            appellant=header.get("Appellant"),
            applicant=header.get("Applicant"),
            is_impounded=is_impounded,
            case_status=header.get("Case Status"),
            status_date=_parse_date(header.get("Status Date")),
            brief_status=header.get("Brief Status"),
            brief_due=header.get("Brief Due"),
            argued_date=_parse_date(
                header.get("Argued Date") or header.get("Arg/Submitted")
            ),
            decision_date=_parse_date(header.get("Decision Date")),
            response_date=_parse_date(header.get("Response Date")),
            panel=header.get("Panel"),
            quorum=header.get("Quorum"),
            citation=header.get("Citation"),
            sjc_number=header.get("SJC Number"),
            appeals_court_number=(
                header.get("Appeals Ct Number") or header.get("AC/SJ Number")
            ),
            sj_number=header.get("SJ Number"),
            far_number=(
                header.get("FAR Number") or header.get("DAR/FAR Number")
            ),
            full_court_number=header.get("Full Ct Number"),
            route_to_sjc=header.get("Route to SJC"),
            lower_court=header.get("Lower Court"),
            lower_court_number=(
                header.get("TC Number") or header.get("Lower Ct Number")
            ),
            lower_court_judge=header.get("Lower Ct Judge"),
            lower_court_entry_date=_parse_date(header.get("TC Entry Date")),
            additional_information=_extract_additional_information(page),
            parties=_extract_parties(page),
            entries=_extract_docket_entries(page),
            scheduled_hearings=_extract_scheduled_hearings(page),
            document_urls=_extract_document_urls(page, response.url),
            source_url=response.url,
        )

        yield ParsedData(data=docket)

        for url in docket.document_urls:
            description = _document_label_for_url(page, url)
            yield Request(
                archive=True,
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url=url,
                    headers={"Accept": "application/pdf"},
                ),
                continuation=self.handle_document_download,
                expected_type="pdf",
                accumulated_data={
                    "docket_id": docket_id,
                    "court_id": court_id,
                    "description": description,
                    "document_url": url,
                },
            )

    @step()
    def handle_document_download(
        self,
        accumulated_data: dict,
        local_filepath: str | None = None,
    ) -> Generator[ScraperYield[MaDocument], None, None]:
        """Emit an ``MaDocument`` for an archived PDF."""
        yield ParsedData(
            data=MaDocument(
                docket_id=accumulated_data["docket_id"],
                court_id=accumulated_data["court_id"],
                description=accumulated_data.get("description"),
                document_url=accumulated_data["document_url"],
                local_path=local_filepath,
            )
        )

    # =========================================================================
    # Step: parse a calendar page
    # =========================================================================

    @step()
    def parse_calendar(
        self,
        page: PageElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[MaOralArgument], None, None]:
        """Parse one calendar page into ``MaOralArgument`` rows."""
        calendar_type = accumulated_data["calendar_type"]
        court_id = accumulated_data["court_id"]

        for session in _extract_calendar_sessions(page, response.url):
            yield ParsedData(
                data=MaOralArgument(
                    court_id=court_id,
                    calendar_type=calendar_type,
                    session_date=session["session_date"],
                    session_time=session["session_time"],
                    location=session["location"],
                    presiding=session["presiding"],
                    cases=session["cases"],
                    source_url=response.url,
                )
            )


# =============================================================================
# Module-level parsing helpers
# =============================================================================


def _first(page: PageElement, xpath: str) -> str | None:
    values = page.query_xpath_strings(xpath, xpath, min_count=0, max_count=1)
    if not values:
        return None
    text = values[0].strip()
    return text or None


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    text = " ".join(value.split())
    return text or None


def _parse_date(value: str | None) -> date | None:
    """Parse the ``MM/DD/YYYY`` dates the site uses."""
    if not value:
        return None
    match = _DATE_RE.search(value)
    if not match:
        return None
    try:
        return datetime.strptime(match.group(1), "%m/%d/%Y").date()
    except ValueError:
        return None


def _collect_header_fields(page: PageElement) -> dict[str, str]:
    """Extract the CASE HEADER label/value pairs into a dict.

    Each row is rendered as ``<span class="flex_span ds-bold">{label}
    <span class="flex_rt ds-normal">{value}</span></span>``. We pull
    the label from the outer span's first text node and the value from
    the inner ``flex_rt*`` span.
    """
    out: dict[str, str] = {}
    spans = page.query_xpath(
        "//section[contains(@class,'docket')]"
        "//span[contains(@class,'flex_span') or "
        "contains(@class,'flex_span_wide')]"
        "[span[contains(@class,'flex_rt') or "
        "contains(@class,'flex_rt_wide')]]",
        "header label spans",
        min_count=0,
    )
    for span in spans:
        # The label is the leading text node before the inner span.
        label_parts = span.query_xpath_strings(
            "./text()[1]", "label text", min_count=0, max_count=1
        )
        value_parts = span.query_xpath_strings(
            ".//span[contains(@class,'flex_rt') or "
            "contains(@class,'flex_rt_wide')]//text()",
            "value text",
            min_count=0,
        )
        label = _clean(label_parts[0] if label_parts else None)
        value = _clean(" ".join(value_parts))
        if label and value:
            out[label] = value
    return out


def _extract_additional_information(page: PageElement) -> str | None:
    """Pull the free-text ADDITIONAL INFORMATION block, when present."""
    text_parts = page.query_xpath_strings(
        "//section[contains(@class,'docket')]"
        "[.//div[contains(@class,'section_title')]"
        "//*[contains(text(),'ADDITIONAL INFORMATION')]]"
        "//div[contains(@class,'pl-2')]//text()",
        "additional information body",
        min_count=0,
    )
    text = " ".join(t.strip() for t in text_parts if t.strip())
    return _clean(text)


def _extract_parties(page: PageElement) -> list[MaParty]:
    """Pull party rows from the INVOLVED PARTY / ATTORNEY APPEARANCE
    section."""
    party_rows = page.query_xpath(
        "//div[contains(@class,'row party')]",
        "party rows",
        min_count=0,
    )
    parties: list[MaParty] = []
    for row in party_rows:
        # Left column: name + role + statuses
        left_lines = row.query_xpath_strings(
            ".//div[contains(@class,'col-12') and not(contains(@class,'indent'))]"
            "//span[contains(@class,'flex_span')]//text()",
            "party left text",
            min_count=0,
        )
        name = None
        role = None
        extras: list[str] = []
        # The bold name is wrapped in <b>; pull it explicitly.
        bold = row.query_xpath_strings(
            ".//div[contains(@class,'col-12') and not(contains(@class,'indent'))]"
            "//b[1]/text()",
            "party name bold",
            min_count=0,
            max_count=1,
        )
        if bold:
            name = _clean(bold[0])
        # Reconstruct the role + extra status lines from the remaining
        # text nodes (skipping the bold name's text).
        cleaned_lines: list[str] = []
        for raw in left_lines:
            stripped = raw.strip()
            if not stripped:
                continue
            if name and stripped == name:
                continue
            cleaned_lines.append(stripped)
        if cleaned_lines:
            role = cleaned_lines[0]
            extras = cleaned_lines[1:]

        brief_status = extras[0] if extras else None
        enlargement = extras[1] if len(extras) > 1 else None

        # Right column: attorney appearances.
        attorney_spans = row.query_xpath(
            ".//div[contains(@class,'indent')]"
            "//span[contains(@class,'flex_span')]",
            "attorney spans",
            min_count=0,
        )
        attorneys: list[MaAttorney] = []
        for span in attorney_spans:
            attorneys.append(_parse_attorney_span(span))

        parties.append(
            MaParty(
                name=name or "",
                role=role,
                brief_status=brief_status,
                enlargement_summary=enlargement,
                attorneys=[a for a in attorneys if a is not None],
            )
        )
    return parties


def _parse_attorney_span(span: PageElement) -> MaAttorney:
    """Parse a single attorney appearance span."""
    link_url = None
    attorney_id = None
    name_text = None
    title = None

    href_values = span.query_xpath_strings(
        ".//a/@href", "attorney href", min_count=0, max_count=1
    )
    if href_values:
        link_url = href_values[0]
        match = _ATTORNEY_ID_RE.search(link_url)
        if match:
            attorney_id = match.group(1)

    link_text_parts = span.query_xpath_strings(
        ".//a//text()", "attorney link text", min_count=0
    )
    if link_text_parts:
        joined = " ".join(t.strip() for t in link_text_parts if t.strip())
        joined = _clean(joined) or ""
        # The link text is "Name, Title" — split on the *last* comma.
        if "," in joined:
            head, _, tail = joined.rpartition(",")
            name_text = _clean(head)
            title = _clean(tail)
        else:
            name_text = joined or None

    if not name_text:
        # Pro-se / non-linked attorneys: take the span's whole text.
        all_text = span.query_xpath_strings(
            ".//text()", "attorney text", min_count=0
        )
        joined = " ".join(t.strip() for t in all_text if t.strip())
        joined = _clean(joined) or ""
        if "," in joined:
            head, _, tail = joined.rpartition(",")
            name_text = _clean(head)
            title = _clean(tail)
        else:
            name_text = joined or None

    span_text = " ".join(
        t.strip()
        for t in span.query_xpath_strings(
            ".//text()", "withdraw probe", min_count=0
        )
        if t.strip()
    )
    withdrawn = "Withdrawn" in span_text

    return MaAttorney(
        name=name_text or "",
        title=title,
        withdrawn=withdrawn,
        attorney_url=link_url,
        attorney_id=attorney_id,
    )


def _extract_docket_entries(page: PageElement) -> list[MaDocketEntry]:
    """Parse the DOCKET ENTRIES table."""
    rows = page.query_xpath(
        "//table[contains(@class,'docket_entries')]//tr[not(contains(@class,'subhead'))]",
        "docket entry rows",
        min_count=0,
    )
    entries: list[MaDocketEntry] = []
    for row in rows:
        cells = row.query_xpath_strings("./td", "docket cells", min_count=0)
        if len(cells) < 3:
            continue
        date_text, paper, description = cells[0], cells[1], cells[2]
        entry_date = _parse_date(date_text)
        description_clean = _clean(description) or ""
        if not (entry_date or paper.strip() or description_clean):
            continue
        entries.append(
            MaDocketEntry(
                entry_date=entry_date,
                paper_number=_clean(paper),
                description=description_clean,
            )
        )
    return entries


def _extract_scheduled_hearings(page: PageElement) -> list[MaScheduledHearing]:
    """Pull rows from the optional FUTURE CALENDAR block."""
    blocks = page.query_xpath(
        "//section[contains(@class,'docket')]"
        "[.//div[contains(@class,'section_title')]"
        "//*[contains(text(),'FUTURE CALENDAR')]]"
        "//div[contains(@class,'calendar-results-date') or "
        "contains(@class,'calendar-results-presiding')]",
        "future calendar blocks",
        min_count=0,
    )
    out: list[MaScheduledHearing] = []
    current_when: str | None = None
    current_location: str | None = None
    for block in blocks:
        classes = " ".join(
            block.query_xpath_strings("./@class", "block class", min_count=0)
        )
        text_lines = [
            t.strip()
            for t in block.query_xpath_strings(
                ".//text()", "lines", min_count=0
            )
            if t.strip()
        ]
        if "calendar-results-date" in classes:
            current_when = text_lines[0] if text_lines else None
            current_location = text_lines[1] if len(text_lines) > 1 else None
        elif "calendar-results-presiding" in classes:
            presiding = next(
                (
                    line[len("Presiding:") :].strip()
                    for line in text_lines
                    if line.lower().startswith("presiding:")
                ),
                None,
            )
            out.append(
                MaScheduledHearing(
                    scheduled_for=current_when,
                    presiding=presiding,
                    location=current_location,
                )
            )
    return out


def _extract_document_urls(page: PageElement, base_url: str) -> list[str]:
    """Pull the unique PDF links from the DOCUMENTS block."""
    hrefs = page.query_xpath_strings(
        "//div[contains(@class,'documents_list')]//li/a/@href",
        "document hrefs",
        min_count=0,
    )
    seen: list[str] = []
    for href in hrefs:
        absolute = urljoin(base_url or BASE_URL, href)
        if absolute not in seen:
            seen.append(absolute)
    return seen


def _document_label_for_url(page: PageElement, url: str) -> str | None:
    """Find the visible label for a document link."""
    labels = page.query_xpath_strings(
        f"//div[contains(@class,'documents_list')]//li"
        f"/a[contains(@href,'{url.rsplit('/', 1)[-1]}')][1]/text()",
        "document label",
        min_count=0,
        max_count=1,
    )
    return _clean(labels[0]) if labels else None


# =============================================================================
# Calendar parsing
# =============================================================================


def _extract_calendar_sessions(page: PageElement, base_url: str) -> list[dict]:
    """Group calendar entries into one session per (date, presiding panel).

    The page renders the date heading once (``calendar-results-date``)
    and then one or more presiding-panel blocks
    (``calendar-results-presiding`` plus any cases listed under the
    same panel inside the surrounding ``calendar-results-indent``
    wrapper). Each presiding panel becomes one ``MaOralArgument``.
    """
    sessions: list[dict] = []

    date_blocks = page.query_xpath(
        "//div[contains(@class,'calendar-results-date')]",
        "calendar date headers",
        min_count=0,
    )
    for date_block in date_blocks:
        date_text_lines = [
            t.strip()
            for t in date_block.query_xpath_strings(
                ".//text()", "date lines", min_count=0
            )
            if t.strip()
        ]
        when = date_text_lines[0] if date_text_lines else ""
        location = date_text_lines[1] if len(date_text_lines) > 1 else None
        session_date, session_time = _parse_session_when(when)

        # Each presiding-panel block follows the date header inside the
        # same ``calendar-results-indent`` wrapper.
        presiding_blocks = date_block.query_xpath(
            "./following-sibling::div[contains(@class,'calendar-results-indent')]"
            "[1]/div[contains(., 'Presiding')]",
            "presiding blocks",
            min_count=0,
        )
        for pres in presiding_blocks:
            presiding = _clean(
                next(
                    (
                        line[len("Presiding:") :].strip()
                        for line in (
                            t.strip()
                            for t in pres.query_xpath_strings(
                                ".//text()", "presiding text", min_count=0
                            )
                        )
                        if line.lower().startswith("presiding:")
                    ),
                    "",
                )
            )

            cases: list[MaOralArgumentCase] = []
            case_blocks = pres.query_xpath(
                ".//div[contains(@class,'calendar-results-case-block')]",
                "case blocks",
                min_count=0,
            )
            for case_block in case_blocks:
                docket_links = case_block.query_xpath_strings(
                    ".//a[contains(@class,'docket-number-link')]/text()",
                    "docket id",
                    min_count=0,
                    max_count=1,
                )
                name_lines = case_block.query_xpath_strings(
                    ".//div[contains(@class,'col text-left')]//text()",
                    "case name",
                    min_count=0,
                )
                docket_id = _clean(docket_links[0]) if docket_links else None
                case_name = _clean(" ".join(name_lines)) or ""
                if docket_id:
                    cases.append(
                        MaOralArgumentCase(
                            docket_id=docket_id,
                            case_name=case_name,
                        )
                    )

            sessions.append(
                {
                    "session_date": session_date,
                    "session_time": session_time,
                    "location": location,
                    "presiding": presiding or None,
                    "cases": cases,
                }
            )

    return sessions


def _parse_session_when(text: str) -> tuple[date | None, str | None]:
    """Parse a calendar heading like ``Monday, May 4th 2026, 9:00 AM``."""
    if not text:
        return None, None
    match = _SESSION_DATE_RE.search(text)
    if not match:
        return None, None
    raw_date = (
        f"{match.group('mon')} {match.group('day')} {match.group('year')}"
    )
    try:
        parsed = datetime.strptime(raw_date, "%B %d %Y").date()
    except ValueError:
        parsed = None
    time_part = match.group("time").upper().strip()
    return parsed, time_part
