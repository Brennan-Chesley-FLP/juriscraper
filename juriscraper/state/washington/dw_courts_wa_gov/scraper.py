"""Washington DW Courts docket scraper (dw.courts.wa.gov).

Scrapes appellate-court dockets from the Washington State court data
warehouse search at https://dw.courts.wa.gov/.

The site uses Material Design Components for the search form and a
Tabulator table (client-side JS) for docket entries, plus a reCAPTCHA
before each search.  The driver must provide ``RCAP_HANDLER`` and
``CHROME_ALIKE`` (and ``JS_EVAL``).

Supported courts (searched as "Appellate Courts" → "Search by case number"):

============================  =====================
CourtListener id              DW ``CRT_ITL_NU``
============================  =====================
``wash``                      ``A08`` — Supreme Court
``washctappdiv1``             ``A01`` — CoA Div I
``washctappdiv2``             ``A02`` — CoA Div II
``washctappdiv3``             ``A03`` — CoA Div III
============================  =====================

Entry point (§4): one speculative docket-number probe addressed by court
id. The driver dispatches a speculative entry with ONLY its speculative
param, so the target court rides in :class:`DwCourtRange` (a ``CourtRange``
subclass that translates the CL court id into the DW court code). Seed once
per court. See ``SCRAPER_STANDARDS.md`` §4 ("Multi-court speculative
entries").

Per-page HTML extraction lives in the ``parsers`` package
(``SearchResultsParser``, ``CaseDetailDomParser``); the steps keep
navigation (form submit / reCAPTCHA, the single case-link follow, and the
inline-JS docket-array parse off ``response.text``).

Flow::

    1. dockets_by_number    → GET search page
    2. fill_search_form     → find <form id="searchform">, set hidden fields,
                              submit via POST (RCAP_HANDLER solves reCAPTCHA)
    3. parse_search_results → extract participant cards, follow the case link
    4. parse_case_detail    → parse inline JS ``data = [...]`` array (or fall
                              back to the Tabulator DOM), yield DWWADocket
"""

from __future__ import annotations

import re
from datetime import date
from typing import TYPE_CHECKING, ClassVar
from urllib.parse import urljoin

from jkent.common.decorators import entry, step
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
    XPath,
)
from pyrate_limiter import Duration, Rate

from juriscraper.state.common.params import CourtRange

from .models import (
    DW_COURTS,
    DWWADocket,
    DWWADocketEntry,
    DWWAParticipant,
)
from .parsers import CaseDetailDomParser, SearchResultsParser
from .parsers._common import parse_dw_date

if TYPE_CHECKING:
    from collections.abc import Generator

    from jkent.common.page_element import PageElement
    from jkent.data_types import ScraperYield

# =============================================================================
# URLs and constants
# =============================================================================

BASE_URL = "https://dw.courts.wa.gov"
SEARCH_URL = (
    f"{BASE_URL}/index.cfm?fa=home.casesearch&terms=accept&flashform=0&tab=clj"
)

# XPath for the search form.
SEARCH_FORM_XPATH = "//form[@id='searchform']"

# Regex for the inline Tabulator data array in the case-detail page source.
# The server renders:  data = [ { eventDate:"...", ... }, ... ];
_ENTRY_RE = re.compile(
    r'eventDate:\s*"([^"]*)"\s*,'
    r'\s*eventDescription:\s*"([^"]*)"\s*,'
    r'\s*action:\s*"([^"]*)"',
)


class DwCourtRange(CourtRange):
    """``CourtRange`` that maps a CL court id to the DW court code.

    The site searches by ``CRT_ITL_NU`` (``A08``/``A01``/``A02``/``A03``);
    ``court_id`` carries the CourtListener id (the seed key) and
    :meth:`search_key` translates it via ``DW_COURTS``. ``from_int``
    (driver advancement) preserves ``court_id`` because it copies via
    ``model_copy``.
    """

    # CL court id -> DW court code.
    DW_CODE: ClassVar[dict[str, str]] = {
        court: code for court, (code, _name) in DW_COURTS.items()
    }

    def search_key(self) -> str:
        return self.DW_CODE[self.court_id]


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
    version: ClassVar[str] = "2026-06-27"
    last_verified: ClassVar[str] = "2026-04-16"
    requires_auth: ClassVar[bool] = False
    driver_requirements: ClassVar[list[DriverRequirement]] = [
        DriverRequirement.JS_EVAL,
        DriverRequirement.CHROME_ALIKE,
        DriverRequirement.RCAP_HANDLER,
    ]
    rate_limits: ClassVar[list[Rate] | None] = [Rate(2, Duration.SECOND)]

    # =========================================================================
    # Entry point (speculative, one DwCourtRange per court)
    # =========================================================================

    @entry(DWWADocket)
    def dockets_by_number(self, docket_number: DwCourtRange) -> Request:
        """Speculatively search one case number for one court.

        ``docket_number.court_id`` selects the court (``wash`` /
        ``washctappdiv{1,2,3}``); :meth:`DwCourtRange.search_key` maps it
        to the DW court code. Seed once per court, e.g.::

            seed_params = [
                {"dockets_by_number": {"docket_number":
                    {"court_id": "wash", "min": 1048343, "gap": 5}}},
                {"dockets_by_number": {"docket_number":
                    {"court_id": "washctappdiv1", "min": 871463, "gap": 5}}},
            ]
        """
        return self._make_search_request(
            docket_number.court_id,
            docket_number.search_key(),
            docket_number.min,
        )

    # =========================================================================
    # Request builder
    # =========================================================================

    def _make_search_request(
        self, court_id: str, court_code: str, case_number: int
    ) -> Request:
        """Navigate to the search page so we can fill and submit the form."""
        return Request(
            request=HTTPRequestParams(
                method=HttpMethod.GET,
                url=SEARCH_URL,
            ),
            continuation=self.fill_search_form,
            accumulated_data={
                "court": court_id,
                "court_code": court_code,
                "docket_number": str(case_number),
                "entry_point": "dockets_by_number",
            },
            deduplication_key=f"search_page:{court_id}:{case_number}",
        )

    # =========================================================================
    # Step 1: Fill and submit the search form
    # =========================================================================

    @step(priority=4)
    def fill_search_form(
        self,
        page: PageElement,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[DWWADocket], None, None]:
        """Set the hidden form fields for an appellate case-number search
        and submit.  The ``RCAP_HANDLER`` driver requirement causes the
        framework to solve the reCAPTCHA before the POST is issued.
        """
        form = page.find_form(XPath(SEARCH_FORM_XPATH), "case search form")
        yield form.submit(
            data={
                "courtType": "C",
                "searchType": "2",
                "CRT_ITL_NU_appellate": accumulated_data["court_code"],
                "caseNumber": accumulated_data["docket_number"],
            },
            continuation=self.parse_search_results,
            accumulated_data=accumulated_data,
        )

    # =========================================================================
    # Step 2: Parse search result cards
    # =========================================================================

    @step(
        priority=3,
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
        parsed = SearchResultsParser().parse(page)

        case_link_href = parsed["case_link_href"]
        case_key = parsed["case_key"]
        if not case_link_href or not case_key:
            # Speculative miss — no resolvable case at this number.
            return

        case_link = urljoin(response.url, case_link_href)
        date_filed = parsed["date_filed"]

        accumulated_data.update(
            {
                "case_key": case_key,
                "court_name": parsed["court_name"],
                "date_filed": (date_filed.isoformat() if date_filed else None),
                "participants": [
                    p.model_dump(mode="json") for p in parsed["participants"]
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
            deduplication_key=f"case_detail:{case_key}",
        )

    # =========================================================================
    # Step 3: Parse case detail (docket entries)
    # =========================================================================

    @step(
        priority=2,
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

        Primary strategy: parse the inline JS ``data = [...]`` array from
        ``response.text`` (the Playwright DOM snapshot includes
        ``<script>`` tags).

        Fallback: when the regex finds nothing (e.g. the site starts
        loading data via AJAX), ``CaseDetailDomParser`` extracts the
        visible ``.tabulator-row`` elements from the rendered DOM.
        """
        court_id = accumulated_data["court"]
        docket_number = accumulated_data["docket_number"]
        case_key = accumulated_data["case_key"]

        # --- Primary: parse entries from inline JS data array ---
        entries: list[DWWADocketEntry] = []
        for m in _ENTRY_RE.finditer(response.text):
            entries.append(
                DWWADocketEntry(
                    date_filed=parse_dw_date(m.group(1)),
                    description=m.group(2),
                    action=m.group(3),
                )
            )

        # --- Fallback: read visible Tabulator DOM rows ---
        if not entries:
            entries = [d.confirm() for d in CaseDetailDomParser()(page)]

        # Reconstruct participants from accumulated_data.
        participants = [
            DWWAParticipant.model_validate(p)
            for p in accumulated_data.get("participants", [])
        ]

        date_filed_str = accumulated_data.get("date_filed")
        date_filed = (
            date.fromisoformat(date_filed_str) if date_filed_str else None
        )

        yield ParsedData(
            data=DWWADocket.raw(
                docket_number=docket_number,
                court=court_id,
                case_key=case_key,
                date_filed=date_filed,
                court_name=accumulated_data.get("court_name"),
                participants=participants,
                entries=entries,
                source_url=response.url,
                source_entry_point=accumulated_data.get("entry_point"),
            )
        )
