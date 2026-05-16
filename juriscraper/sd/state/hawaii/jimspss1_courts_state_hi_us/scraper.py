"""Hawaii eCourt Kōkua appellate-docket scraper.

Scrapes appellate dockets from the Hawaiʻi Judiciary's eCourt Kōkua
portal at ``http://jimspss1.courts.state.hi.us:8080/eCourt/ECC/``.

Supported courts:

- ``haw``    — Supreme Court of Hawaiʻi (case prefixes ``SC{TT}-``)
- ``hawapp`` — Hawaii Intermediate Court of Appeals (prefixes ``CA{TT}-``)

The portal is JSF 2.0 / IceFaces 4. Every search submission is gated by
**invisible** reCAPTCHA v2; kent's ``RCAP_HANDLER`` only handles the
visible-checkbox variant today, so this scraper ships
``status=IN_DEVELOPMENT`` until kent gains an invisible-reCAPTCHA solver.
See ``DESIGN.md`` for details.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING, ClassVar
from urllib.parse import urljoin

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
    ICA_CASE_TYPES,
    SC_CASE_TYPES,
    SITE_COURT_TO_CL,
    HiAppAttorney,
    HiAppDocket,
    HiAppDocketEntry,
    HiAppDocument,
    HiAppParty,
)

if TYPE_CHECKING:
    from collections.abc import Generator

    from jkent.data_types import ScraperYield


SITE_BASE = "http://jimspss1.courts.state.hi.us:8080/eCourt/ECC"
DISCLAIMER_URL = f"{SITE_BASE}/ECCDisclaimer.iface"
CASE_SEARCH_URL = f"{SITE_BASE}/CaseSearch.iface"
DATE_SEARCH_URL = f"{SITE_BASE}/FilingDateSearch.iface"

# Hawaii eCourt date entry / display format (e.g. "01-APR-2026"). Server
# strictly enforces this; lowercased month names are silently truncated.
SITE_DATE_FORMAT = "%d-%b-%Y"

# Server-side cap on Filing Date Search ranges.
MAX_DATE_RANGE_DAYS = 60

DISCLAIMER_FORM_XPATH = "//form[@id='frm']"
SEARCH_FORM_XPATH = "//form[@id='frm']"

RESULT_TABLE_XPATH = "//table[contains(@class, 'iceDatTbl')]"
NO_RESULTS_SENTINEL = "no records found"


class HiAppellateScraper(BaseScraper[HiAppDocket]):
    """Scraper for Hawaiʻi appellate dockets on the eCourt Kōkua portal.

    Two date-range entries (one per appellate court) and four high-volume
    speculative case-id entries. All paths route through:

    1. ``ensure_disclaimer`` — accept the disclaimer once per session
       (invisible reCAPTCHA gate).
    2. ``fill_date_search_form`` / ``fill_caseid_search_form`` — submit
       the search form (invisible reCAPTCHA gate).
    3. ``parse_search_results`` — iterate the result table and queue
       case-detail fetches.
    4. ``parse_case_detail`` — assemble the ``HiAppDocket``.
    """

    court_ids: ClassVar[set[str]] = {"haw", "hawapp"}
    court_url: ClassVar[str] = f"{SITE_BASE}/CaseSearch.iface"
    data_types: ClassVar[set[str]] = {"dockets"}
    status: ClassVar[ScraperStatus] = ScraperStatus.IN_DEVELOPMENT
    version: ClassVar[str] = "2026-05-06"
    requires_auth: ClassVar[bool] = False

    rate_limits: ClassVar[list[Rate] | None] = [Rate(1, Duration.SECOND)]

    # Invisible reCAPTCHA v2 on disclaimer + every search submission.
    # ``RCAP_HANDLER`` declares intent; today it solves visible reCAPTCHA
    # only. See DESIGN.md "Known Gaps".
    driver_requirements: ClassVar[list[DriverRequirement]] = [
        DriverRequirement.JS_EVAL,
        DriverRequirement.FF_ALIKE,
        DriverRequirement.RCAP_HANDLER,
    ]

    # =========================================================================
    # Date-range entry points (Filing Date Search, one per court)
    # =========================================================================

    @entry(HiAppDocket)
    def get_supreme_court_dockets_by_date(
        self, date_range: DateRange
    ) -> Generator[Request, None, None]:
        """Filing Date Search restricted to the Supreme Court of Hawaiʻi."""
        yield from self._date_search_requests(
            site_court_type="SC",
            site_court="SC",
            site_location="SC",
            date_range=date_range,
        )

    @entry(HiAppDocket)
    def get_ica_dockets_by_date(
        self, date_range: DateRange
    ) -> Generator[Request, None, None]:
        """Filing Date Search restricted to the Intermediate Court of Appeals."""
        yield from self._date_search_requests(
            site_court_type="ICA",
            site_court="CA",
            site_location="CA",
            date_range=date_range,
        )

    def _date_search_requests(
        self,
        *,
        site_court_type: str,
        site_court: str,
        site_location: str,
        date_range: DateRange,
    ) -> Generator[Request, None, None]:
        """Chunk ``date_range`` into <= 60-day windows and queue one search
        per window. Each window navigates through the disclaimer first."""
        for window_start, window_end in _chunk_date_range(
            date_range.start, date_range.end, MAX_DATE_RANGE_DAYS
        ):
            yield Request(
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url=DISCLAIMER_URL,
                ),
                continuation=self.ensure_disclaimer,
                accumulated_data={
                    "search_mode": "date",
                    "site_court_type": site_court_type,
                    "site_court": site_court,
                    "site_location": site_location,
                    "begin_date": window_start.strftime(
                        SITE_DATE_FORMAT
                    ).upper(),
                    "end_date": window_end.strftime(SITE_DATE_FORMAT).upper(),
                    "court_id": SITE_COURT_TO_CL[site_court],
                },
                deduplication_key=SkipDeduplicationCheck(),
            )

    # =========================================================================
    # Speculative case-ID entries (one per high-volume prefix)
    # =========================================================================

    @entry(HiAppDocket)
    def fetch_scap_docket(self, case_id: YearlySpeculativeRange) -> Request:
        """Speculative fetch — Supreme Court Appeal (``SCAP-YY-NNNNNNN``)."""
        return self._caseid_search_request("SC", "AP", case_id)

    @entry(HiAppDocket)
    def fetch_scwc_docket(self, case_id: YearlySpeculativeRange) -> Request:
        """Speculative fetch — Supreme Court Writ of Certiorari Application
        (``SCWC-YY-NNNNNNN``)."""
        return self._caseid_search_request("SC", "WC", case_id)

    @entry(HiAppDocket)
    def fetch_scpw_docket(self, case_id: YearlySpeculativeRange) -> Request:
        """Speculative fetch — Supreme Court Petition for Writ
        (``SCPW-YY-NNNNNNN``)."""
        return self._caseid_search_request("SC", "PW", case_id)

    @entry(HiAppDocket)
    def fetch_caap_docket(self, case_id: YearlySpeculativeRange) -> Request:
        """Speculative fetch — ICA Appeal (``CAAP-YY-NNNNNNN``)."""
        return self._caseid_search_request("CA", "AP", case_id)

    def _caseid_search_request(
        self,
        site_court: str,
        type_code: str,
        case_id: YearlySpeculativeRange,
    ) -> Request:
        yy = case_id.year % 100
        docket_id = f"{site_court}{type_code}-{yy:02d}-{case_id.min:07d}"
        return Request(
            request=HTTPRequestParams(
                method=HttpMethod.GET,
                url=DISCLAIMER_URL,
            ),
            continuation=self.ensure_disclaimer,
            accumulated_data={
                "search_mode": "case_id",
                "docket_id": docket_id,
                "court_id": SITE_COURT_TO_CL[site_court],
            },
            deduplication_key=f"hi-case-{docket_id}",
        )

    # =========================================================================
    # Step: accept the disclaimer (or pass through if already accepted)
    # =========================================================================

    @step()
    def ensure_disclaimer(
        self,
        page: PageElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[HiAppDocket], None, None]:
        """Accept the JIMS disclaimer when present, then queue a fresh GET
        for the search page. The ``RCAP_HANDLER`` driver requirement is
        responsible for solving the invisible reCAPTCHA before the accept
        POST is dispatched.

        After a successful accept the server returns ``ECC.iface`` (Home)
        with a session flag; ``ice.window`` and ``ice.view`` view tokens
        change per page render, so we re-fetch the search page rather
        than submitting from a stale form."""
        if "ECCDisclaimer.iface" in (response.url or ""):
            form = page.find_form(
                DISCLAIMER_FORM_XPATH, "disclaimer accept form"
            )
            yield form.submit(
                data={"frm:acceptButtonCaptcha": ""},
                continuation=self.navigate_to_search,
                accumulated_data=accumulated_data,
                deduplication_key=SkipDeduplicationCheck(),
            )
            return
        yield from self.navigate_to_search(
            page=page,
            response=response,
            accumulated_data=accumulated_data,
        )

    @step()
    def navigate_to_search(
        self,
        page: PageElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[HiAppDocket], None, None]:
        """Issue a fresh GET to the appropriate search page so we can
        capture a current ViewState / ice.view triple."""
        if accumulated_data.get("search_mode") == "case_id":
            target = CASE_SEARCH_URL
            continuation = self.fill_caseid_search_form
        else:
            target = DATE_SEARCH_URL
            continuation = self.fill_date_search_form
        yield Request(
            request=HTTPRequestParams(method=HttpMethod.GET, url=target),
            continuation=continuation,
            accumulated_data=accumulated_data,
            deduplication_key=SkipDeduplicationCheck(),
        )

    # =========================================================================
    # Step: fill and submit the Filing Date Search form
    # =========================================================================

    @step()
    def fill_date_search_form(
        self,
        page: PageElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[HiAppDocket], None, None]:
        """Submit the FilingDateSearch form for the chosen court+window.

        The form lives at ``frm`` and IceFaces partial-postback dependencies
        between the court-type / court / location selects mean we set them
        in one shot and rely on server-side validation to accept the
        consistent triple (``SC/SC/SC`` or ``ICA/CA/CA``)."""
        form = page.find_form(SEARCH_FORM_XPATH, "filing date search form")
        yield form.submit(
            data={
                "frm:j_idt22:courtTypeSelect": accumulated_data[
                    "site_court_type"
                ],
                "frm:j_idt22:courtSelect": accumulated_data["site_court"],
                "frm:j_idt22:locationSelect": accumulated_data[
                    "site_location"
                ],
                "frm:beginDate": accumulated_data["begin_date"],
                "frm:endDate": accumulated_data["end_date"],
                "frm:caseType": "",
                "frm:searchButtonCaptcha": "",
            },
            continuation=self.parse_search_results,
            accumulated_data=accumulated_data,
        )

    # =========================================================================
    # Step: fill and submit the Case ID Search form (speculative)
    # =========================================================================

    @step()
    def fill_caseid_search_form(
        self,
        page: PageElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[HiAppDocket], None, None]:
        """Submit the CaseSearch form for a single docket id."""
        form = page.find_form(SEARCH_FORM_XPATH, "case id search form")
        yield form.submit(
            data={
                "frm:caseId": accumulated_data["docket_id"],
                "frm:searchButtonCaptcha": "",
            },
            continuation=self.parse_search_results,
            accumulated_data=accumulated_data,
        )

    # =========================================================================
    # Step: parse the IceFaces result table
    # =========================================================================

    @step()
    def parse_search_results(
        self,
        page: PageElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[HiAppDocket], None, None]:
        """Walk the result table; queue a detail fetch per case row.

        TODO(empirical): result-table column layout is inferred from the
        site's form schema and standard IceFaces conventions. Validate
        on first operational run and adjust the XPaths below."""
        # Soft-404: IceFaces re-renders the same page with a "no records"
        # message rather than emitting an HTTP error.
        body = (response.text or "").lower()
        if NO_RESULTS_SENTINEL in body:
            return

        rows = page.query_xpath(
            f"{RESULT_TABLE_XPATH}//tbody/tr",
            "result-table rows",
            min_count=0,
        )
        if not rows:
            return

        for row in rows:
            link_els = row.query_xpath(
                ".//a[contains(@href, 'CaseSearchView') "
                "or contains(@id, 'caseId')]",
                "case detail link",
                min_count=0,
                max_count=1,
            )
            if not link_els:
                continue
            href = link_els[0].get_attribute("href")
            if not href:
                continue

            row_text_cells = row.query_xpath_strings(
                ".//td//text()",
                "row cell texts",
                min_count=0,
            )
            row_docket_id = (
                row_text_cells[0].strip() if row_text_cells else None
            )

            child_data = dict(accumulated_data)
            child_data["docket_id"] = row_docket_id or accumulated_data.get(
                "docket_id"
            )

            yield Request(
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url=urljoin(response.url, href),
                ),
                continuation=self.parse_case_detail,
                accumulated_data=child_data,
                deduplication_key=child_data["docket_id"],
            )

    # =========================================================================
    # Step: parse the case-detail page
    # =========================================================================

    @step()
    def parse_case_detail(
        self,
        page: PageElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[HiAppDocket], None, None]:
        """Assemble a :class:`HiAppDocket` from the case detail page.

        TODO(empirical): the layout is not yet verified end-to-end. The
        XPaths below match the JSF/IceFaces conventions used elsewhere in
        the JIMS portal (label-then-value table cells, register-of-actions
        in an ``iceDatTbl``). Validate on first operational run."""
        docket_id = accumulated_data.get("docket_id") or ""
        court_id = accumulated_data["court_id"]

        case_name = (
            _value_for_label(page, "Caption")
            or _value_for_label(page, "Case Title")
            or docket_id
        )
        case_type_label = _value_for_label(page, "Case Type")
        case_status = _value_for_label(
            page, "Case Status"
        ) or _value_for_label(page, "Status")
        date_filed = _parse_site_date(_value_for_label(page, "Filing Date"))
        date_terminated = _parse_site_date(
            _value_for_label(page, "Disposition Date")
            or _value_for_label(page, "Closed Date")
        )
        panel = _value_for_label(page, "Panel") or _value_for_label(
            page, "Division"
        )
        lower_court_case_number = _value_for_label(
            page, "Trial Court Case Number"
        ) or _value_for_label(page, "Lower Court Case Number")
        lower_court_judge = _value_for_label(page, "Trial Court Judge")

        type_code = _extract_type_code(docket_id)
        type_label = _case_type_label(docket_id, type_code) or case_type_label

        docket = HiAppDocket(
            docket_id=docket_id,
            court_id=court_id,
            case_name=case_name,
            date_filed=date_filed,
            case_type_code=type_code,
            case_type=type_label,
            case_status=case_status,
            date_terminated=date_terminated,
            panel=panel,
            lower_court_case_number=lower_court_case_number,
            lower_court_judge=lower_court_judge,
            entries=_parse_docket_entries(page),
            parties=_parse_parties(page),
            documents=_parse_documents(page, response.url),
            source_url=response.url,
        )
        yield ParsedData(data=docket)

    # =========================================================================
    # Soft-404 detection (per request)
    # =========================================================================

    def fails_successfully(self, response: Response) -> bool:
        """Return False for the JSF re-render that signals a search miss.

        The case-id search re-renders ``CaseSearch.iface`` with a "no
        records found" message rather than redirecting or 404-ing. The
        driver treats False as a speculation miss."""
        if response.status_code != 200:
            return True
        body = (response.text or "").lower()
        return NO_RESULTS_SENTINEL not in body


# =============================================================================
# Date-range chunking
# =============================================================================


def _chunk_date_range(
    start: date, end: date, max_days: int
) -> list[tuple[date, date]]:
    """Split ``[start, end]`` into inclusive sub-ranges of at most
    ``max_days`` days each."""
    if start > end:
        return []
    chunks: list[tuple[date, date]] = []
    cursor = start
    step = timedelta(days=max_days - 1)
    while cursor <= end:
        chunk_end = min(cursor + step, end)
        chunks.append((cursor, chunk_end))
        cursor = chunk_end + timedelta(days=1)
    return chunks


# =============================================================================
# Detail-page parsing helpers
# =============================================================================


def _value_for_label(page: PageElement, label: str) -> str | None:
    """Return the text in the cell immediately following a label cell.

    The Hawaiʻi case summary is rendered as ``<td>Label:</td><td>value</td>``
    pairs; matching is case-insensitive and tolerant of trailing colons."""
    candidates = page.query_xpath_strings(
        f"//td[normalize-space(translate(text(),"
        f" 'ABCDEFGHIJKLMNOPQRSTUVWXYZ',"
        f" 'abcdefghijklmnopqrstuvwxyz'))="
        f" '{label.lower()}:' or normalize-space(translate(text(),"
        f" 'ABCDEFGHIJKLMNOPQRSTUVWXYZ',"
        f" 'abcdefghijklmnopqrstuvwxyz'))="
        f" '{label.lower()}']/following-sibling::td[1]//text()",
        f"value for label {label!r}",
        min_count=0,
    )
    text = " ".join(s.strip() for s in candidates if s.strip())
    return text or None


def _parse_site_date(value: str | None) -> date | None:
    """Parse the eCourt date format (``DD-MMM-YYYY``)."""
    if not value:
        return None
    try:
        return datetime.strptime(
            value.strip().upper(), SITE_DATE_FORMAT
        ).date()
    except ValueError:
        return None


def _extract_type_code(docket_id: str) -> str | None:
    """Pull the 2-letter case type out of a docket id like ``SCAP-22-...``."""
    if not docket_id or "-" not in docket_id:
        return None
    prefix = docket_id.split("-", 1)[0]
    if len(prefix) >= 4 and prefix[:2] in ("SC", "CA"):
        return prefix[2:4]
    return None


def _case_type_label(docket_id: str, type_code: str | None) -> str | None:
    if not type_code:
        return None
    if docket_id.startswith("SC"):
        return SC_CASE_TYPES.get(type_code)
    if docket_id.startswith("CA"):
        return ICA_CASE_TYPES.get(type_code)
    return None


def _parse_docket_entries(page: PageElement) -> list[HiAppDocketEntry]:
    """Parse the register-of-actions table.

    TODO(empirical): column order on the actual page is unverified."""
    rows = page.query_xpath(
        "//table[contains(@class, 'iceDatTbl')]"
        "[.//th[contains(translate(text(),"
        " 'ABCDEFGHIJKLMNOPQRSTUVWXYZ',"
        " 'abcdefghijklmnopqrstuvwxyz'), 'docket')]"
        " or .//th[contains(translate(text(),"
        " 'ABCDEFGHIJKLMNOPQRSTUVWXYZ',"
        " 'abcdefghijklmnopqrstuvwxyz'), 'register')]]"
        "//tbody/tr",
        "docket entry rows",
        min_count=0,
    )
    out: list[HiAppDocketEntry] = []
    for row in rows:
        cells = row.query_xpath_strings(
            ".//td//text()", "docket cell texts", min_count=0
        )
        cells = [c.strip() for c in cells if c.strip()]
        if not cells:
            continue
        date_filed = _parse_site_date(cells[0]) if cells else None
        description = cells[1] if len(cells) > 1 else cells[0]
        notes = cells[2] if len(cells) > 2 else None
        out.append(
            HiAppDocketEntry(
                date_filed=date_filed,
                description=description,
                notes=notes,
            )
        )
    return out


def _parse_parties(page: PageElement) -> list[HiAppParty]:
    """Parse the parties section.

    TODO(empirical): JSF portals here typically render parties as nested
    tables or repeated panels; refine selectors after a real run."""
    blocks = page.query_xpath(
        "//*[contains(translate(@id, 'PARTIES', 'parties'), 'parties')]"
        "//table[contains(@class, 'iceDatTbl')]//tbody/tr",
        "party rows",
        min_count=0,
    )
    out: list[HiAppParty] = []
    for row in blocks:
        cells = row.query_xpath_strings(
            ".//td//text()", "party cell texts", min_count=0
        )
        cells = [c.strip() for c in cells if c.strip()]
        if len(cells) < 2:
            continue
        name, role, *rest = cells
        attorney_text = rest[0] if rest else None
        attorneys: list[HiAppAttorney] = []
        if attorney_text:
            attorneys.append(HiAppAttorney(name=attorney_text))
        out.append(HiAppParty(name=name, role=role, attorneys=attorneys))
    return out


def _parse_documents(
    page: PageElement, source_url: str | None
) -> list[HiAppDocument]:
    """Collect document links surfaced on the case detail page.

    These often link to a viewer / Subscriptions paywall rather than a
    direct PDF, so we record metadata only."""
    out: list[HiAppDocument] = []
    links = page.query_xpath(
        "//a[contains(@href, 'Document') or contains(@href, 'Opinion') "
        "or contains(@href, '.pdf')]",
        "document links",
        min_count=0,
    )
    for link in links:
        href = link.get_attribute("href")
        if not href:
            continue
        text = (link.text_content() or "").strip()
        out.append(
            HiAppDocument(
                download_url=urljoin(source_url or "", href),
                description=text or None,
            )
        )
    return out
