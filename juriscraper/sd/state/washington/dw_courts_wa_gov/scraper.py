"""Washington DW Courts docket scraper (dw.courts.wa.gov).

Scrapes appellate-court dockets from the Washington State court data
warehouse search at https://dw.courts.wa.gov/.

The site uses Material Design Components for the search form and a
Tabulator table (client-side JS) for docket entries, plus a reCAPTCHA
before each search.  The driver must provide ``RCAP_HANDLER`` and
``CHROME_ALIKE``.

Supported courts (searched as "Appellate Courts" → "Search by case number"):

============================  =====================
CourtListener id              DW ``crt_itl_nu``
============================  =====================
``wash``                      ``A08`` — Supreme Court
``washctappdiv1``             ``A01`` — CoA Div I
``washctappdiv2``             ``A02`` — CoA Div II
``washctappdiv3``             ``A03`` — CoA Div III
============================  =====================

Entry points (speculative, one per court):

- ``docket_search_supreme_court(rid)``
- ``docket_search_div1(rid)``
- ``docket_search_div2(rid)``
- ``docket_search_div3(rid)``

Flow::

    1. docket_search_*      → GET search page
    2. fill_search_form     → find <form id="searchform">, set hidden fields,
                              submit via POST (RCAP_HANDLER solves reCAPTCHA)
    3. parse_search_results → extract participant cards (.dw-search-result),
                              deduplicate on case_key, follow first link
    4. parse_case_detail    → extract inline JS ``data = [...]`` array for
                              docket entries, yield DWWADocket
"""

from __future__ import annotations

import re
from datetime import date
from typing import TYPE_CHECKING, ClassVar
from urllib.parse import parse_qs, urljoin, urlparse

from jkent.common.decorators import entry, step
from jkent.common.page_element import PageElement
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
    WaitForSelector,
)
from pyrate_limiter import Duration, Rate

from .models import (
    DW_COURTS,
    DWWADocket,
    DWWADocketEntry,
    DWWAParticipant,
)

if TYPE_CHECKING:
    from collections.abc import Generator

    from jkent.data_types import ScraperYield

# =============================================================================
# URLs and constants
# =============================================================================

BASE_URL = "https://dw.courts.wa.gov"
SEARCH_URL = (
    f"{BASE_URL}/index.cfm?fa=home.casesearch&terms=accept&flashform=0&tab=clj"
)

# XPath for the search form
SEARCH_FORM_XPATH = "//form[@id='searchform']"

# Date format used on the site: MM-DD-YY
_DW_DATE_RE = re.compile(r"^(\d{2})-(\d{2})-(\d{2})$")

# Regex for the inline Tabulator data array in the case-detail page source.
# The server renders:  data = [ { eventDate:"...", ... }, ... ];
_ENTRY_RE = re.compile(
    r'eventDate:\s*"([^"]*)"\s*,'
    r'\s*eventDescription:\s*"([^"]*)"\s*,'
    r'\s*action:\s*"([^"]*)"',
)


# =============================================================================
# Scraper
# =============================================================================


class DWCourtsScraper(BaseScraper[DWWADocket]):
    """Scraper for Washington appellate dockets via dw.courts.wa.gov."""

    # === Metadata ===
    court_ids: ClassVar[set[str]] = set(DW_COURTS.keys())
    court_url: ClassVar[str] = f"{BASE_URL}/"
    data_types: ClassVar[set[str]] = {"dockets"}
    status: ClassVar[ScraperStatus] = ScraperStatus.IN_DEVELOPMENT
    version: ClassVar[str] = "2026-04-16"
    requires_auth: ClassVar[bool] = False
    driver_requirements: ClassVar[list[DriverRequirement]] = [
        DriverRequirement.JS_EVAL,
        DriverRequirement.CHROME_ALIKE,
        DriverRequirement.RCAP_HANDLER,
    ]

    rate_limits: ClassVar[list[Rate] | None] = [Rate(2, Duration.SECOND)]

    # =========================================================================
    # Entry points (speculative, one per court)
    # =========================================================================

    @entry(DWWADocket)
    def docket_search_supreme_court(self, rid: SpeculativeRange) -> Request:
        """Speculative search — Washington Supreme Court."""
        return self._make_search_request("wash", rid.number)

    @entry(DWWADocket)
    def docket_search_div1(self, rid: SpeculativeRange) -> Request:
        """Speculative search — Court of Appeals Division I."""
        return self._make_search_request("washctappdiv1", rid.number)

    @entry(DWWADocket)
    def docket_search_div2(self, rid: SpeculativeRange) -> Request:
        """Speculative search — Court of Appeals Division II."""
        return self._make_search_request("washctappdiv2", rid.number)

    @entry(DWWADocket)
    def docket_search_div3(self, rid: SpeculativeRange) -> Request:
        """Speculative search — Court of Appeals Division III."""
        return self._make_search_request("washctappdiv3", rid.number)

    # =========================================================================
    # Request builder
    # =========================================================================

    def _make_search_request(self, court_id: str, case_number: int) -> Request:
        """Navigate to the search page so we can fill and submit the form."""
        court_code, _name = DW_COURTS[court_id]
        return Request(
            request=HTTPRequestParams(
                method=HttpMethod.GET,
                url=SEARCH_URL,
            ),
            continuation=self.fill_search_form,
            accumulated_data={
                "court_id": court_id,
                "court_code": court_code,
                "case_number": str(case_number),
            },
        )

    # =========================================================================
    # Step 1: Fill and submit the search form
    # =========================================================================

    @step()
    def fill_search_form(
        self,
        page: PageElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[DWWADocket], None, None]:
        """Set the hidden form fields for an appellate case-number search
        and submit.  The ``RCAP_HANDLER`` driver requirement causes the
        framework to solve the reCAPTCHA before the POST is issued.
        """
        form = page.find_form(SEARCH_FORM_XPATH, "case search form")
        yield form.submit(
            data={
                "courtType": "C",
                "searchType": "2",
                "CRT_ITL_NU_appellate": accumulated_data["court_code"],
                "caseNumber": accumulated_data["case_number"],
            },
            continuation=self.parse_search_results,
            accumulated_data=accumulated_data,
        )

    # =========================================================================
    # Step 2: Parse search result cards
    # =========================================================================

    @step(
        await_list=[
            WaitForSelector(
                ".dw-search-result, .dw-no-results",
                timeout=15000,
            ),
        ],
    )
    def parse_search_results(
        self,
        page: PageElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[DWWADocket], None, None]:
        """Extract participant info from the result cards and navigate
        to the case-detail page.

        All cards for a given case share the same ``case_key`` and link
        URL; we only need to follow one.
        """

        # Each card is a .dw-search-result that contains both -left and -right
        cards = page.query_xpath(
            "//div[contains(@class, 'dw-search-result')"
            " and .//div[contains(@class, 'dw-search-result-left')]"
            " and .//div[contains(@class, 'dw-search-result-right')]]",
            "search result cards",
            min_count=0,
        )

        if not cards:
            # Speculative miss — no case at this number.
            return

        participants: list[DWWAParticipant] = []
        case_key: str | None = None
        case_link: str | None = None
        filing_date: date | None = None
        court_name: str | None = None

        for card in cards:
            # --- Left side: participant info ---
            name = _extract_field(card, "Name")
            participant_code = _extract_field(card, "Participant Code")
            review_type = _extract_field(card, "Review Type")

            if name:
                participants.append(
                    DWWAParticipant(
                        name=name,
                        participant_code=participant_code,
                        review_type=review_type,
                    )
                )

            # --- Right side: case link, filing date ---
            if case_link is None:
                links = card.query_xpath(
                    ".//a[contains(@href, 'casekey')]",
                    "case detail link",
                    min_count=0,
                    max_count=1,
                )
                if links:
                    href = links[0].get_attribute("href")
                    if href:
                        case_link = urljoin(response.url, href)
                        params = parse_qs(urlparse(case_link).query)
                        case_key = (params.get("casekey") or [None])[0]
                        court_name_raw = (params.get("courtname") or [None])[0]
                        if court_name_raw:
                            court_name = court_name_raw

            if filing_date is None:
                # Filing date is in the right side as "File Date: MM-DD-YY"
                right_els = card.query_xpath(
                    ".//div[contains(@class, 'dw-search-result-right')]",
                    "card right panel",
                    min_count=0,
                    max_count=1,
                )
                if right_els:
                    right_text = right_els[0].text_content()
                    fd_match = re.search(r"File Date:\s*([\d-]+)", right_text)
                    if fd_match:
                        filing_date = _parse_dw_date(fd_match.group(1))

        if not case_link or not case_key:
            return

        accumulated_data.update(
            {
                "case_key": case_key,
                "court_name": court_name,
                "filing_date": (
                    filing_date.isoformat() if filing_date else None
                ),
                "participants": [
                    p.model_dump(mode="json") for p in participants
                ],
            }
        )

        yield Request(
            request=HTTPRequestParams(
                method=HttpMethod.GET,
                url=case_link,
            ),
            continuation=self.parse_case_detail,
            accumulated_data=accumulated_data,
        )

    # =========================================================================
    # Step 3: Parse case detail (docket entries)
    # =========================================================================

    @step(
        await_list=[
            WaitForSelector(".tabulator", timeout=15000),
        ],
    )
    def parse_case_detail(
        self,
        page: PageElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[DWWADocket], None, None]:
        """Extract docket entries and yield the final :class:`DWWADocket`.

        The case-detail page requires a valid session from the search
        form submission.  When accessed through Playwright with the
        session intact, the server embeds a Tabulator data array in an
        inline ``<script>``::

            data = [
              { eventDate:"08-29-24",
                eventDescription: "Notice of Appeal",
                action: "Filed" },
              ...
            ];

        Primary strategy: parse that array from ``response.text``
        (the Playwright DOM snapshot includes ``<script>`` tags).

        Fallback: if the regex finds nothing (e.g. the site starts
        loading data via AJAX), extract the visible ``.tabulator-row``
        elements from the rendered DOM instead.
        """
        court_id = accumulated_data["court_id"]
        case_number = accumulated_data["case_number"]
        case_key = accumulated_data["case_key"]

        # --- Primary: parse entries from inline JS data array ---
        entries: list[DWWADocketEntry] = []
        for m in _ENTRY_RE.finditer(response.text):
            entries.append(
                DWWADocketEntry(
                    event_date=_parse_dw_date(m.group(1)),
                    event_description=m.group(2),
                    action=m.group(3),
                )
            )

        # --- Fallback: read visible Tabulator DOM rows ---
        if not entries:
            rows = page.query_xpath(
                "//div[contains(@class, 'tabulator-row')]",
                "tabulator rows",
                min_count=0,
            )
            for row in rows:
                cells = row.query_xpath(
                    ".//div[contains(@class, 'tabulator-cell')]",
                    "tabulator cells",
                    min_count=0,
                )
                if len(cells) >= 3:
                    entries.append(
                        DWWADocketEntry(
                            event_date=_parse_dw_date(
                                cells[0].text_content().strip()
                            ),
                            event_description=cells[1].text_content().strip(),
                            action=cells[2].text_content().strip(),
                        )
                    )

        # Reconstruct participants from accumulated_data
        participants = [
            DWWAParticipant.model_validate(p)
            for p in accumulated_data.get("participants", [])
        ]

        filing_date_str = accumulated_data.get("filing_date")
        filing_date = (
            date.fromisoformat(filing_date_str) if filing_date_str else None
        )

        yield ParsedData(
            data=DWWADocket(
                case_number=case_number,
                court_id=court_id,
                case_key=case_key,
                filing_date=filing_date,
                court_name=accumulated_data.get("court_name"),
                participants=participants,
                entries=entries,
                source_url=response.url,
            )
        )


# =============================================================================
# Helpers
# =============================================================================


def _extract_field(card: PageElement, label: str) -> str | None:
    """Extract a labeled value from a search-result card.

    Card fields are rendered as::

        <span class="semi-bold ...">Label: </span>
        <span class="...">Value</span>

    within ``.dw-icon-row`` divs.
    """
    rows = card.query_xpath(
        f".//div[contains(@class, 'dw-icon-row')]"
        f"[.//span[contains(text(), '{label}')]]",
        f"card row for {label}",
        min_count=0,
    )
    if not rows:
        return None
    # The value is the last .mdc-typography--body2 span that isn't semi-bold
    spans = rows[0].query_xpath(
        ".//span[contains(@class, 'mdc-typography--body2')]"
        "[not(contains(@class, 'semi-bold'))]",
        f"value span for {label}",
        min_count=0,
    )
    if spans:
        text = spans[-1].text_content().strip()
        return text if text else None
    return None


def _parse_dw_date(text: str) -> date | None:
    """Parse ``MM-DD-YY`` into a :class:`date`.

    Two-digit years are interpreted as 2000-2099 (the site doesn't
    carry data before 2000).
    """
    if not text:
        return None
    m = _DW_DATE_RE.match(text.strip())
    if not m:
        return None
    month, day, year_2 = int(m.group(1)), int(m.group(2)), int(m.group(3))
    year = 2000 + year_2
    try:
        return date(year, month, day)
    except ValueError:
        return None


Site = DWCourtsScraper
