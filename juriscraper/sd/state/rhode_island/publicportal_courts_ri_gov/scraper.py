"""Rhode Island Judiciary Public Portal scraper.

Scrapes appellate dockets from the Supreme Court of Rhode Island
via the Tyler Odyssey Public Portal at
``https://publicportal.courts.ri.gov/PublicPortal/Home/Dashboard/29``.

The portal is reCAPTCHA-gated and shielded by DataDome at the edge —
both require Playwright. The driver requirements
(``JS_EVAL`` + ``CHROME_ALIKE`` + ``RCAP_HANDLER``) cause kent to drive
a real browser through DataDome and to solve the reCAPTCHA before each
form submit.

This is the canonical RCAP_HANDLER + ``page.find_form().submit()``
pattern; see ``washington/dw_courts_wa_gov`` for the reference flow.

Flow::

    1. fetch_supreme_docket(rid)  → GET dashboard (renders the form)
    2. submit_search_form         → fill SearchCriteria + CourtLocation,
                                    POST via form.submit() (RCAP_HANDLER
                                    inserts a fresh g-recaptcha-response
                                    token before the request goes out)
    3. parse_search_results       → extract one row per case match,
                                    yield an ``RIDocket`` per row.

Case-detail and document-download steps are reserved for v2 — see
``DESIGN.md`` "Known Gaps".
"""

from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING, ClassVar
from urllib.parse import urljoin

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
    DASHBOARD_URL,
    PORTAL_URL,
    RI_COURTS,
    RIDocket,
)

if TYPE_CHECKING:
    from collections.abc import Generator

    from jkent.data_types import ScraperYield


# XPath for the Smart Search form. The form has no id on this Tyler
# build, so we identify it by its action URL — unique on the page.
SEARCH_FORM_XPATH = (
    "//form[contains(@action, 'SmartSearch/SmartSearch/SmartSearch')]"
)


class RhodeIslandPublicPortalScraper(BaseScraper[RIDocket]):
    """Scraper for the Supreme Court of Rhode Island via the Tyler
    Odyssey Public Portal.

    v1 supports speculative single-case lookups by docket number.
    See ``DESIGN.md`` for the v2 roadmap (date-range entry, full
    case-detail parse, document downloads).
    """

    # === Metadata ===
    court_ids: ClassVar[set[str]] = set(RI_COURTS.keys())
    court_url: ClassVar[str] = DASHBOARD_URL
    data_types: ClassVar[set[str]] = {"dockets"}
    status: ClassVar[ScraperStatus] = ScraperStatus.IN_DEVELOPMENT
    version: ClassVar[str] = "2026-05-04"
    requires_auth: ClassVar[bool] = False
    driver_requirements: ClassVar[list[DriverRequirement]] = [
        DriverRequirement.JS_EVAL,
        DriverRequirement.CHROME_ALIKE,
        DriverRequirement.RCAP_HANDLER,
    ]

    rate_limits: ClassVar[list[Rate] | None] = [Rate(1, Duration.SECOND)]

    # =========================================================================
    # Entry point — speculative by case number, Supreme Court only.
    # =========================================================================

    @entry(RIDocket)
    def fetch_supreme_docket(self, rid: SpeculativeRange) -> Request:
        """Speculative single-case lookup at the Rhode Island Supreme Court.

        The site's "Smart Search" box accepts a free-text docket number.
        Operators seed ``SpeculativeRange`` with the appropriate sequence;
        this scraper passes the integer through unchanged so the seed
        format can match whichever docket-number convention is in use
        (legacy ``YYYY-NNN-Appeal.`` or Tyler-internal forms — see
        ``DESIGN.md``).
        """
        return Request(
            request=HTTPRequestParams(
                method=HttpMethod.GET,
                url=DASHBOARD_URL,
            ),
            continuation=self.submit_search_form,
            accumulated_data={
                "court_id": "ri",
                "case_number_query": str(rid.number),
            },
        )

    # =========================================================================
    # Step 1: fill and submit the search form.
    # =========================================================================

    @step()
    def submit_search_form(
        self,
        page: PageElement,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[RIDocket], None, None]:
        """Fill SearchCriteria + CourtLocation and submit the form.

        ``RCAP_HANDLER`` injects a fresh ``g-recaptcha-response`` token
        before the POST is dispatched; all other hidden fields
        (``Settings.CaptchaEnabled``, ``caseCriteria.SearchBy``, …) are
        preserved automatically by ``find_form().submit()``.
        """
        court_id = accumulated_data["court_id"]
        court_location = RI_COURTS[court_id]
        case_number_query = accumulated_data["case_number_query"]

        form = page.find_form(SEARCH_FORM_XPATH, "smart search form")
        yield form.submit(
            data={
                "caseCriteria.SearchCriteria": case_number_query,
                "caseCriteria.CourtLocation": court_location,
                "caseCriteria.CourtLocation_input": court_location,
            },
            continuation=self.parse_search_results,
            accumulated_data=accumulated_data,
        )

    # =========================================================================
    # Step 2: parse the rendered search-results page.
    # =========================================================================

    @step(
        await_list=[
            WaitForSelector(
                "table, .k-grid, .ssSearchResultList, .smartSearchResults",
                timeout=15000,
            ),
        ],
    )
    def parse_search_results(
        self,
        page: PageElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[RIDocket], None, None]:
        """Extract one ``RIDocket`` per match from the result table.

        Tyler Odyssey Public Portal renders results in a kendo grid
        wrapping a ``<table>`` whose rows carry the case fields as
        ``<td>`` cells. The first cell typically holds an ``<a>`` whose
        ``href`` is the case-detail URL (``/PublicPortal/Case/CaseDetail
        ?caseId=…``).

        v1 yields a lightweight ``RIDocket`` from the row alone — the
        case-detail follow-up is wired into v2 once the detail page
        structure is verified against a captcha-solving deploy.
        """
        court_id = accumulated_data["court_id"]

        rows = page.query_xpath(
            "//table//tr[.//a[contains(@href, 'CaseDetail') "
            "or contains(@href, 'caseId=') or contains(@href, 'CaseID=')]]",
            "search result rows",
            min_count=0,
        )
        if not rows:
            # Speculative miss — no case found for this number, OR the
            # result-page DOM did not match the expected Tyler shape.
            # The DESIGN.md "Known Gaps" section calls this out — the
            # first post-deploy run should validate.
            return

        for row in rows:
            link_els = row.query_xpath(
                ".//a[contains(@href, 'CaseDetail') "
                "or contains(@href, 'caseId=') or contains(@href, 'CaseID=')]",
                "case detail link",
                min_count=0,
                max_count=1,
            )
            if not link_els:
                continue
            href = link_els[0].get_attribute("href") or ""
            source_url = urljoin(response.url or PORTAL_URL, href)
            case_number = (link_els[0].text_content() or "").strip()
            if not case_number:
                continue

            cells = row.query_xpath(".//td", "row cells", min_count=0)
            cell_texts = [(c.text_content() or "").strip() for c in cells]
            case_name = cell_texts[1] if len(cell_texts) > 1 else case_number
            date_filed = _find_date_in_cells(cell_texts)
            case_type = _pick_cell(
                cell_texts, contains_any=["Appeal", "Petition", "Writ"]
            )
            case_status = _pick_cell(
                cell_texts,
                contains_any=["Pending", "Closed", "Disposed", "Active"],
            )

            yield ParsedData(
                data=RIDocket(
                    case_number=case_number,
                    court_id=court_id,
                    case_name=case_name or case_number,
                    date_filed=date_filed,
                    case_type=case_type,
                    case_status=case_status,
                    source_url=source_url,
                )
            )


# =============================================================================
# Helpers
# =============================================================================


def _find_date_in_cells(cell_texts: list[str]) -> date | None:
    """Return the first ``mm/dd/yyyy`` value found in any cell."""
    for text in cell_texts:
        for token in text.split():
            try:
                return datetime.strptime(token, "%m/%d/%Y").date()
            except ValueError:
                continue
    return None


def _pick_cell(
    cell_texts: list[str], *, contains_any: list[str]
) -> str | None:
    """Return the first cell whose text contains any of the markers."""
    for text in cell_texts:
        if any(marker.lower() in text.lower() for marker in contains_any):
            return text
    return None
