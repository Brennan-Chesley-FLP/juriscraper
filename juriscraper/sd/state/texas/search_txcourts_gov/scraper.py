"""Kent scraper for all Texas appellate courts via TAMES.

TAMES (https://search.txcourts.gov/CaseSearch.aspx) is an ASP.NET WebForms
+ Telerik RadGrid application that exposes a single "Date Filed" range
search across every Texas appellate court. This scraper covers all 17:

- Texas Supreme Court (``coa=cossup`` → CL ``tex``)
- Court of Criminal Appeals (``coa=coscca`` → CL ``texcrimapp``)
- 15 intermediate Courts of Appeals (``coa=coa01``..``coa15`` → CL
  ``texapp``, with the district preserved on the docket via ``coa_district``)

The site has no Cloudflare / captcha — plain httpx works — but the search
endpoint is rate-limited (HTTP 403 on bursts) and the search form requires
ASP.NET hidden fields (``__VIEWSTATE`` &c.) plus a pair of Telerik
``ClientState`` JSON blobs per date input. The scraper extracts those from
the initial GET response and reuses them on subsequent POSTs.

See ``DESIGN.md`` in this directory for the full site analysis.

The case-detail step routes on the final URL's ``coa=`` query parameter to
the appropriate legacy parser in ``juriscraper.state.texas.*`` (Supreme
Court, Court of Criminal Appeals, or Court of Appeals); the result is then
adapted to the kent ``TexasDocket`` ``ScrapedData``.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING, ClassVar
from urllib.parse import urljoin

from jkent.common.decorators import entry, step
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

from juriscraper.state.texas.common import COA_ORDINAL_MAP, CourtID
from juriscraper.state.texas.court_of_appeals import (
    TexasCourtOfAppealsScraper as LegacyCoaParser,
)
from juriscraper.state.texas.court_of_criminal_appeals import (
    TexasCourtOfCriminalAppealsScraper as LegacyCcaParser,
)
from juriscraper.state.texas.supreme_court import (
    TexasSupremeCourtScraper as LegacySupremeCourtParser,
)

from .models import (
    COA_DISTRICT_NAMES,
    TexasAppealsCourtRef,
    TexasDocket,
    TexasDocketEntry,
    TexasDocument,
    TexasOriginatingCourt,
    TexasParty,
    TexasTransfer,
)

if TYPE_CHECKING:
    from collections.abc import Generator

    from jkent.common.page_element import PageElement
    from jkent.data_types import ScraperYield

# =========================================================================
# Site constants
# =========================================================================

BASE_URL = "https://search.txcourts.gov"
SEARCH_URL = f"{BASE_URL}/CaseSearch.aspx"

# TAMES caps each search at the most recent 1000 rows. When a date window
# returns exactly this many we split it in half and re-search each half.
MAX_RESULTS_PER_SEARCH = 1000

# All 17 appellate-court checkboxes on the form. Indexes 0 and 1 are the
# Supreme Court and Court of Criminal Appeals; 2..16 are the 15 COAs.
ALL_APPELLATE_CHECKBOX_INDEXES = tuple(range(17))

# Court routing keyed off the final URL's ``coa=`` query parameter
# (``cossup`` → SC, ``coscca`` → CCA, ``coa01``..``coa15`` → COAs).
COA_PARAM_RE = re.compile(r"[?&]coa=([a-z0-9]+)", re.IGNORECASE)

_COA_DOCKET_RE = re.compile(r"^(\d{2})-\d{2}-\d{5}-\w{2}$")

# Per-court docket-number patterns. Used to route ``parse_case_detail`` to
# the right legacy parser when the persistent driver doesn't surface the
# final (redirected) URL in ``response.url``. Order matters: COA is
# checked first because the COA suffix is the most distinctive; CCA next;
# SC last (SC formats are short and could otherwise be greedy).
_CCA_DOCKET_RE = re.compile(
    r"^(?:WR-[\d,]+-\d{2}|AP-[\d,]+|[A-Z]{2}-\d{4}-\d{2})$",
)
_SC_LETTER_DOCKET_RE = re.compile(r"^[ABC]-\d+(?:-A)?$")
_SC_MODERN_DOCKET_RE = re.compile(r"^\d{1,2}[bB]?-\d{4}$")
_SC_WRIT_DOCKET_RE = re.compile(r"^\d{4,5}$")
# Oddly-numbered SC dockets that appear in the legacy DOCKET_NUMBER_REGEXES.
_SC_ODDBALL_DOCKETS = {"B-3872A", "D-0190", "D-2169", "D-4261"}


# Headers split between GET and POST to mirror what real browsers send and
# to keep the rate-limiter from flagging the scraper as obviously automated.
_GET_HEADERS: dict[str, str] = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "sec-fetch-site": "none",
    "sec-fetch-mode": "navigate",
    "sec-fetch-user": "?1",
    "sec-fetch-dest": "document",
}
_POST_HEADERS: dict[str, str] = {
    **_GET_HEADERS,
    "Origin": BASE_URL,
    "Referer": f"{SEARCH_URL}?coa=cossup",
    "sec-fetch-site": "same-origin",
    "Content-Type": "application/x-www-form-urlencoded",
}


_Yield = TexasDocket | TexasDocument


class TexasTamesScraper(BaseScraper[_Yield]):
    """Scraper for all 17 Texas appellate courts via TAMES.

    Walks the ``/CaseSearch.aspx`` Date-Filed search across every appellate
    court at once, recursively halving the date window whenever the
    1000-row cap is hit, paginating each leaf search, fetching each
    case-detail page (routing to the right per-court parser based on the
    URL's ``coa=`` parameter), and archiving every document linked from
    the docket.
    """

    # === Metadata ===
    court_ids: ClassVar[set[str]] = {"tex", "texcrimapp", "texapp"}
    court_url: ClassVar[str] = SEARCH_URL
    data_types: ClassVar[set[str]] = {"dockets"}
    status: ClassVar[ScraperStatus] = ScraperStatus.IN_DEVELOPMENT
    version: ClassVar[str] = "2026-05-21"
    requires_auth: ClassVar[bool] = False

    # The site silently 302s /CaseSearch.aspx → /CaseSearch.aspx?coa=cossup
    # on first GET, and /Case.aspx?cn=... → /Case.aspx?cn=...&coa=coaNN. We
    # rely on both redirects to land on the canonical pages.
    driver_requirements: ClassVar[list[DriverRequirement]] = [
        DriverRequirement.FOLLOW_REDIRECTS,
    ]

    # The search endpoint 403s on bursts; case-detail is more permissive.
    # Using a single conservative limit covers both.
    rate_limits: ClassVar[list[Rate] | None] = [Rate(1, Duration.SECOND)]

    # =========================================================================
    # Entry points
    # =========================================================================

    @entry(TexasDocket)
    def get_dockets_by_date(
        self, date_range: DateRange
    ) -> Generator[Request, None, None]:
        """Walk the TAMES Date-Filed search for the requested window.

        Emits a single GET against the search form; the chain
        (``fetch_search_form`` → ``submit_search`` → ``parse_search_results``)
        takes over from there.
        """
        yield self._build_form_get_request(date_range.start, date_range.end)

    @entry(TexasDocket)
    def fetch_docket(
        self, docket_number: str
    ) -> Generator[Request, None, None]:
        """Fetch a single docket directly by its number, bypassing search.

        TAMES resolves the COA from the leading two digits of the docket
        number server-side, so ``/Case.aspx?cn={docket_number}`` 302s to
        ``/Case.aspx?cn={docket_number}&coa=coaNN`` automatically — no need
        to pre-compute the ``coa=`` query parameter on our side. With
        ``FOLLOW_REDIRECTS`` already declared the persistent driver lands
        on the canonical case page in one hop.
        """
        case_url = f"{BASE_URL}/Case.aspx?cn={docket_number}"
        yield Request(
            request=HTTPRequestParams(
                method=HttpMethod.GET,
                url=case_url,
                headers=_GET_HEADERS,
            ),
            continuation=self.parse_case_detail,
            accumulated_data={
                "docket_id": docket_number,
                "source_url": case_url,
            },
            deduplication_key=f"tames-case:{docket_number}",
        )

    # =========================================================================
    # Step: GET the search form so we can capture the ASP.NET hidden fields
    # =========================================================================

    @step()
    def fetch_search_form(
        self,
        page: PageElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield, None, None]:
        """Extract the hidden ASP.NET fields and submit the search."""
        hidden_fields = self._extract_hidden_fields(page)
        start_date = date.fromisoformat(accumulated_data["start_date"])
        end_date = date.fromisoformat(accumulated_data["end_date"])

        form_data = self._build_search_form_data(
            hidden_fields, start_date, end_date
        )

        yield Request(
            request=HTTPRequestParams(
                method=HttpMethod.POST,
                url=SEARCH_URL,
                data=form_data,
                headers=_POST_HEADERS,
            ),
            continuation=self.parse_search_results,
            accumulated_data={
                **accumulated_data,
                "form_data": form_data,
                "page_num": 1,
            },
            # Different (start, end) pairs may produce identical search-URL
            # POSTs; embed both into the dedup key so each window's first
            # POST is actually issued.
            deduplication_key=(
                f"tames-search:{start_date.isoformat()}:{end_date.isoformat()}"
            ),
        )

    # =========================================================================
    # Step: parse a results page, handle pagination + window splitting
    # =========================================================================

    @step()
    def parse_search_results(
        self,
        page: PageElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield, None, None]:
        """Walk one page of search results, paginate, or split the window."""
        page_num = int(accumulated_data.get("page_num", 1))
        start_date = date.fromisoformat(accumulated_data["start_date"])
        end_date = date.fromisoformat(accumulated_data["end_date"])

        # Window-split decision is only made on the first page; once we've
        # committed to paginating we don't re-evaluate.
        if page_num == 1:
            result_count = self._extract_result_count(page)
            if (
                result_count >= MAX_RESULTS_PER_SEARCH
                and start_date < end_date
            ):
                yield from self._split_window(start_date, end_date)
                return

        case_rows = page.query_xpath(
            "//table[@id='ctl00_ContentPlaceHolder1_grdCases_ctl00']"
            "//tr[contains(@class, 'rgRow') or contains(@class, 'rgAltRow')]",
            "search result rows",
            min_count=0,
        )

        for row in case_rows:
            yield from self._yield_case_request(row, accumulated_data)

        # Pagination: rgPageNext is a submit button that re-POSTs the form
        # with __EVENTTARGET pointing at the next-page control. We harvest
        # its name+value, re-extract VIEWSTATE (it changes on each POST),
        # and emit a new search POST.
        next_buttons = page.query_xpath(
            "//input[contains(@class, 'rgPageNext')]",
            "rgPageNext button",
            min_count=0,
            max_count=2,
        )
        current_page_has_next = page.query_xpath(
            "//span[contains(@class, 'rgCurrentPage')]/following-sibling::a",
            "current+next page anchor",
            min_count=0,
            max_count=2,
        )
        if next_buttons and current_page_has_next:
            submit_name = next_buttons[0].get_attribute("name") or ""
            submit_val = next_buttons[0].get_attribute("value") or ""
            hidden_fields = self._extract_hidden_fields(page)

            # ASP.NET decides the server-side handler from the submitter
            # field name; sending both btnSearch and rgPageNext is invalid.
            base_form = {
                k: v
                for k, v in accumulated_data["form_data"].items()
                if k != "ctl00$ContentPlaceHolder1$btnSearch"
            }
            next_form_data = {
                **base_form,
                **hidden_fields,
                submit_name: submit_val,
            }

            yield Request(
                request=HTTPRequestParams(
                    method=HttpMethod.POST,
                    url=SEARCH_URL,
                    data=next_form_data,
                    headers=_POST_HEADERS,
                ),
                continuation=self.parse_search_results,
                accumulated_data={
                    **accumulated_data,
                    "form_data": next_form_data,
                    "page_num": page_num + 1,
                },
                # Pagination requests must always run even when their URL
                # collides with prior pages on the same search.
                deduplication_key=SkipDeduplicationCheck(),
            )

    # =========================================================================
    # Step: parse a single case-detail page and emit a TexasDocket
    # =========================================================================

    @step()
    def parse_case_detail(
        self,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield, None, None]:
        """Parse Case.aspx, routing on the court detected from the docket.

        TAMES 302s ``/Case.aspx?cn={docket_number}`` to the canonical URL
        with a ``coa=`` query parameter identifying the issuing court, but
        the persistent driver does not consistently surface the final
        (redirected) URL in ``response.url``, so we route on the docket
        number's format instead — the prefix unambiguously identifies the
        court. Falls back to extracting ``coa=`` from the URL if the
        docket number isn't present in ``accumulated_data`` (which would
        be unusual).

        After emitting the ``TexasDocket``, an ``archive=True`` Request is
        issued for every document attached to any docket entry.
        """
        docket_id = accumulated_data.get("docket_id", "")
        court_code = self._court_code_from_docket(
            docket_id
        ) or self._extract_coa_param(response.url or "")
        legacy = self._make_legacy_parser(court_code)
        legacy._parse_text(response.text)
        legacy_data = legacy.data

        docket = self._adapt_legacy_docket(
            legacy_data, court_code, response.url, accumulated_data
        )
        yield ParsedData(data=docket)

        # Fan out an archive request per document. The docket already has
        # the same `TexasDocument` objects embedded for snapshot/joining;
        # the archive handler emits a standalone copy with `local_path` set.
        # Loop var named ``docket_entry`` to avoid shadowing the imported
        # ``entry`` decorator.
        for docket_entry in docket.entries:
            for doc in docket_entry.documents:
                if not doc.download_url:
                    continue
                yield Request(
                    archive=True,
                    request=HTTPRequestParams(
                        method=HttpMethod.GET,
                        url=doc.download_url,
                        headers=_GET_HEADERS,
                    ),
                    continuation=self.handle_document_download,
                    expected_type="pdf",
                    accumulated_data={
                        "docket_id": docket.docket_id,
                        "entry_kind": docket_entry.kind,
                        "entry_number": docket_entry.entry_number,
                        "document": doc.model_dump(mode="json"),
                    },
                    # MediaID is the durable identifier for a document;
                    # MediaVersionID changes on revisions. Dedupe on the
                    # versioned pair so we re-archive across revisions but
                    # not within the same scrape window.
                    deduplication_key=(
                        f"tames-doc:{doc.media_id}:{doc.media_version_id}"
                        if doc.media_id
                        else f"tames-doc-url:{doc.download_url}"
                    ),
                )

    @step()
    def handle_document_download(
        self,
        response: Response,
        accumulated_data: dict,
        local_filepath: str | None = None,
    ) -> Generator[ScraperYield, None, None]:
        """Emit a standalone ``TexasDocument`` with the archive path."""
        raw_doc = accumulated_data.get("document") or {}
        yield ParsedData(
            data=TexasDocument(
                download_url=raw_doc.get("download_url", ""),
                media_id=raw_doc.get("media_id"),
                media_version_id=raw_doc.get("media_version_id"),
                document_type=raw_doc.get("document_type"),
                description=raw_doc.get("description"),
                file_size_bytes=raw_doc.get("file_size_bytes"),
                file_size_str=raw_doc.get("file_size_str"),
                local_path=local_filepath,
                docket_id=accumulated_data.get("docket_id"),
                docket_entry_kind=accumulated_data.get("entry_kind"),
                docket_entry_number=accumulated_data.get("entry_number"),
            )
        )

    # =========================================================================
    # Soft-404 detection
    # =========================================================================

    def fails_successfully(self, response: Response) -> bool:
        """An invalid case number redirects to
        ``/CaseSearch.aspx?ex=InvalidCaseNumber&...`` — detect that.

        Returns False (i.e. "this is a soft-404") only on that one
        redirect-style miss. Real cases land on ``/Case.aspx?cn=...`` and
        pass the check.
        """
        url = response.url or ""
        return "ex=InvalidCaseNumber" not in url

    # =========================================================================
    # Helpers — court detection / parser routing
    # =========================================================================

    @staticmethod
    def _extract_coa_param(url: str) -> str | None:
        """Return the ``coa=`` query param value, lowercased, or None.

        E.g. ``cossup`` (Supreme), ``coscca`` (CCA), ``coa07`` (7th COA).
        Used as a fallback when the docket number isn't present in
        ``accumulated_data``.
        """
        match = COA_PARAM_RE.search(url)
        return match.group(1).lower() if match else None

    @staticmethod
    def _court_code_from_docket(docket_id: str) -> str | None:
        """Map a Texas appellate docket number to its TAMES ``coa=`` code.

        Returns ``cossup`` / ``coscca`` / ``coa01``..``coa15``, or
        ``None`` if the docket number doesn't match any known format.
        Patterns derive from
        ``juriscraper.state.texas.common.DOCKET_NUMBER_REGEXES``.
        """
        if not docket_id:
            return None
        # 1st-15th Courts of Appeals — most distinctive pattern, check first.
        match = _COA_DOCKET_RE.match(docket_id)
        if match:
            ord_num = int(match.group(1))
            if 1 <= ord_num <= 15:
                return f"coa{ord_num:02d}"
        # Court of Criminal Appeals: WR-... / AP-... / PD-NNNN-NN.
        if _CCA_DOCKET_RE.match(docket_id):
            return "coscca"
        # Supreme Court — three legacy patterns plus a handful of oddballs.
        if docket_id in _SC_ODDBALL_DOCKETS:
            return "cossup"
        if _SC_LETTER_DOCKET_RE.match(docket_id):
            return "cossup"
        if _SC_MODERN_DOCKET_RE.match(docket_id):
            return "cossup"
        if _SC_WRIT_DOCKET_RE.match(docket_id):
            return "cossup"
        return None

    @staticmethod
    def _make_legacy_parser(court_code: str | None):
        """Pick the legacy parser class based on the resolved ``coa=`` code."""
        if court_code == "cossup":
            return LegacySupremeCourtParser()
        if court_code == "coscca":
            return LegacyCcaParser()
        # ``coa01``..``coa15`` — or a missing / unrecognised code, in which
        # case we still try the COA parser since COA pages have the broadest
        # field surface.
        return LegacyCoaParser(court_id=CourtID.UNKNOWN.value)

    @staticmethod
    def _court_id_from_court_code(court_code: str | None) -> str:
        if court_code == "cossup":
            return "tex"
        if court_code == "coscca":
            return "texcrimapp"
        return "texapp"

    @staticmethod
    def _court_name_from_court_code(court_code: str | None) -> str | None:
        if court_code == "cossup":
            return "Texas Supreme Court"
        if court_code == "coscca":
            return "Court of Criminal Appeals of Texas"
        if court_code and court_code.startswith("coa"):
            try:
                ordinal = int(court_code.removeprefix("coa"))
            except ValueError:
                return None
            return COA_DISTRICT_NAMES.get(ordinal)
        return None

    # =========================================================================
    # Helpers — form building
    # =========================================================================

    def _build_form_get_request(
        self, start_date: date, end_date: date
    ) -> Request:
        """Construct the initial GET against the search form."""
        return Request(
            request=HTTPRequestParams(
                method=HttpMethod.GET,
                url=SEARCH_URL,
                headers=_GET_HEADERS,
            ),
            continuation=self.fetch_search_form,
            accumulated_data={
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
            },
            deduplication_key=(
                f"tames-form:{start_date.isoformat()}:{end_date.isoformat()}"
            ),
        )

    @staticmethod
    def _extract_hidden_fields(page: PageElement) -> dict[str, str]:
        """Collect all <input type=hidden> name/value pairs from the page.

        ASP.NET WebForms requires ``__VIEWSTATE``, ``__VIEWSTATEGENERATOR``,
        ``__EVENTVALIDATION``, ``__EVENTTARGET``, ``__EVENTARGUMENT`` and
        a handful of Telerik state inputs to be re-submitted on each POST.
        """
        hidden_fields: dict[str, str] = {}
        hidden_inputs = page.query_xpath(
            "//input[@type='hidden']",
            "ASP.NET hidden fields",
            min_count=0,
        )
        for elem in hidden_inputs:
            name = elem.get_attribute("name") or ""
            if not name:
                continue
            hidden_fields[name] = elem.get_attribute("value") or ""
        return hidden_fields

    @classmethod
    def _build_search_form_data(
        cls,
        hidden_fields: dict[str, str],
        start_date: date,
        end_date: date,
    ) -> dict[str, str]:
        """Compose the POST body for a date-range search across all 15 COAs."""
        start_str = start_date.strftime("%-m/%-d/%Y")
        end_str = end_date.strftime("%-m/%-d/%Y")

        form_data: dict[str, str] = {
            **hidden_fields,
            "ctl00$ContentPlaceHolder1$txtDateFiledStart": start_str,
            "ctl00$ContentPlaceHolder1$txtDateFiledStart$dateInput": start_str,
            "ctl00$ContentPlaceHolder1$txtDateFiledEnd": end_str,
            "ctl00$ContentPlaceHolder1$txtDateFiledEnd$dateInput": end_str,
            "ctl00_ContentPlaceHolder1_txtDateFiledStart_dateInput_ClientState": (
                cls._make_telerik_date_client_state(start_date, start_str)
            ),
            "ctl00_ContentPlaceHolder1_txtDateFiledEnd_dateInput_ClientState": (
                cls._make_telerik_date_client_state(end_date, end_str)
            ),
            "ctl00_ContentPlaceHolder1_txtDateFiledStart_ClientState": (
                '{"minDateStr":"1900-01-01-00-00-00",'
                '"maxDateStr":"2099-12-31-00-00-00"}'
            ),
            "ctl00_ContentPlaceHolder1_txtDateFiledEnd_ClientState": (
                '{"minDateStr":"1900-01-01-00-00-00",'
                '"maxDateStr":"2099-12-31-00-00-00"}'
            ),
            "ctl00$ContentPlaceHolder1$btnSearch": "Search",
        }
        # Tick all 17 appellate-court checkboxes (SC, CCA, and the 15 COAs).
        for idx in ALL_APPELLATE_CHECKBOX_INDEXES:
            form_data[f"ctl00$ContentPlaceHolder1$chkListCourts${idx}"] = "on"

        return form_data

    @staticmethod
    def _make_telerik_date_client_state(date_obj: date, date_str: str) -> str:
        """Build the Telerik RadDatePicker per-input ClientState JSON.

        Without these blobs the server-side validator silently rejects the
        search and re-renders the empty form — no error, no results.
        """
        date_formatted = date_obj.strftime("%Y-%m-%d")
        return (
            '{"enabled":true,"emptyMessage":"",'
            f'"validationText":"{date_formatted}-00-00-00",'
            f'"valueAsString":"{date_formatted}-00-00-00",'
            '"minDateStr":"1900-01-01-00-00-00",'
            '"maxDateStr":"2099-12-31-00-00-00",'
            f'"lastSetTextBoxValue":"{date_str}"'
            "}"
        )

    # =========================================================================
    # Helpers — result-page parsing
    # =========================================================================

    @staticmethod
    def _extract_result_count(page: PageElement) -> int:
        """Read the "N items in M pages" string from the RadGrid footer."""
        info_parts = page.query_xpath_strings(
            "//div[contains(@class, 'rgInfoPart')]//text()",
            "rgInfoPart",
            min_count=0,
        )
        joined = " ".join(t.strip() for t in info_parts if t.strip())
        match = re.search(
            r"(\d+)\s+items?\s+in\s+\d+\s+pages?", joined, re.IGNORECASE
        )
        return int(match.group(1)) if match else 0

    def _split_window(
        self, start_date: date, end_date: date
    ) -> Generator[Request, None, None]:
        """Fan out two new searches when the 1000-row cap is hit."""
        span = (end_date - start_date).days
        mid = start_date + timedelta(days=span // 2)
        yield self._build_form_get_request(start_date, mid)
        yield self._build_form_get_request(mid + timedelta(days=1), end_date)

    def _yield_case_request(
        self, row: PageElement, accumulated_data: dict
    ) -> Generator[Request, None, None]:
        """Emit a case-detail Request for one search-results row."""
        case_links = row.query_xpath(
            ".//a[contains(@href, 'Case.aspx')]",
            "case-detail link",
            min_count=0,
            max_count=1,
        )
        if not case_links:
            return
        href = case_links[0].get_attribute("href") or ""
        if not href:
            return
        case_url = urljoin(BASE_URL, href)
        docket_id = case_links[0].text_content().strip()

        yield Request(
            request=HTTPRequestParams(
                method=HttpMethod.GET,
                url=case_url,
                headers=_GET_HEADERS,
            ),
            continuation=self.parse_case_detail,
            accumulated_data={
                "docket_id": docket_id,
                "source_url": case_url,
            },
            # Same case may show up in overlapping splits — dedupe on docket.
            deduplication_key=f"tames-case:{docket_id}",
        )

    # =========================================================================
    # Helpers — TypedDict → ScrapedData adapters
    # =========================================================================

    @staticmethod
    def _coa_district_from_docket(docket_id: str) -> int | None:
        match = _COA_DOCKET_RE.match(docket_id)
        if not match:
            return None
        ordinal = int(match.group(1))
        if 1 <= ordinal <= 15:
            return ordinal
        return None

    @staticmethod
    def _other_court_district(court_name: str) -> int | None:
        """Map a COA name (e.g. "First Court of Appeals") to its ordinal."""
        first = court_name.split()[0].lower() if court_name else ""
        cid = COA_ORDINAL_MAP.get(first)
        if cid is None:
            return None
        # CourtID values are "texas_coaNN" — strip prefix to recover the number.
        suffix = cid.value.removeprefix("texas_coa")
        try:
            return int(suffix)
        except ValueError:
            return None

    @classmethod
    def _adapt_legacy_docket(
        cls,
        legacy: dict,
        court_code: str | None,
        source_url: str | None,
        accumulated_data: dict,
    ) -> TexasDocket:
        """Convert a legacy parser's TypedDict to a ``TexasDocket``.

        Handles output from any of the three parsers (COA, SC, CCA) by
        falling back to ``.get()`` on per-court keys (``publication_service``,
        ``transfer_from``, ``transfer_to`` for COAs; ``appeals_court`` for
        SC / CCA; ``remarks`` on SC events / briefs).
        """
        docket_id = legacy["docket_number"]
        court_id = cls._court_id_from_court_code(court_code)
        coa_district = (
            cls._coa_district_from_docket(docket_id)
            if court_id == "texapp"
            else None
        )
        court_name = cls._court_name_from_court_code(court_code) or (
            COA_DISTRICT_NAMES.get(coa_district)
            if coa_district is not None
            else None
        )

        # TAMES sorts each table newest-first. Number bottom-to-top within
        # each kind so the oldest row in each table is entry_number=1.
        legacy_events = list(legacy.get("case_events") or [])
        legacy_briefs = list(legacy.get("appellate_briefs") or [])

        entries: list[TexasDocketEntry] = []
        documents: list[TexasDocument] = []

        for i, ev in enumerate(legacy_events):
            entry_documents = [
                cls._adapt_document(d) for d in (ev.get("attachments") or [])
            ]
            entries.append(
                TexasDocketEntry(
                    kind="event",
                    entry_number=len(legacy_events) - i,
                    date_filed=cls._coerce_date(ev.get("date")),
                    event_type=ev.get("type", ""),
                    disposition=ev.get("disposition") or None,
                    remarks=ev.get("remarks") or None,
                    documents=entry_documents,
                )
            )
            documents.extend(entry_documents)

        for i, brief in enumerate(legacy_briefs):
            brief_documents = [
                cls._adapt_document(d)
                for d in (brief.get("attachments") or [])
            ]
            entries.append(
                TexasDocketEntry(
                    kind="brief",
                    entry_number=len(legacy_briefs) - i,
                    date_filed=cls._coerce_date(brief.get("date")),
                    event_type=brief.get("type", ""),
                    description=brief.get("description") or None,
                    remarks=brief.get("remarks") or None,
                    documents=brief_documents,
                )
            )
            documents.extend(brief_documents)

        parties = [
            TexasParty(
                name=p.get("name", ""),
                role=p.get("type", ""),
                representatives=list(p.get("representatives") or []),
            )
            for p in (legacy.get("parties") or [])
        ]

        originating = cls._adapt_originating_court(
            legacy.get("originating_court")
        )

        transfer_from = cls._adapt_transfer(legacy.get("transfer_from"))
        transfer_to = cls._adapt_transfer(legacy.get("transfer_to"))

        appeals_court_ref = cls._adapt_appeals_court_ref(
            legacy.get("appeals_court")
        )

        return TexasDocket(
            docket_id=docket_id,
            court_id=court_id,
            coa_district=coa_district,
            court_name=court_name,
            case_name=legacy.get("case_name", ""),
            case_name_full=legacy.get("case_name_full", ""),
            case_type=legacy.get("case_type") or None,
            date_filed=cls._coerce_date(legacy.get("date_filed")),
            parties=parties,
            originating_court=originating,
            entries=entries,
            documents=documents,
            publication_service=legacy.get("publication_service") or None,
            transfer_from=transfer_from,
            transfer_to=transfer_to,
            appeals_court_ref=appeals_court_ref,
            source_url=source_url or accumulated_data.get("source_url"),
        )

    @staticmethod
    def _coerce_date(value) -> date | None:
        if value is None or value == "":
            return None
        if isinstance(value, date) and not isinstance(value, datetime):
            return value
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, str):
            try:
                return datetime.strptime(value, "%m/%d/%Y").date()
            except ValueError:
                try:
                    return date.fromisoformat(value)
                except ValueError:
                    return None
        return None

    @staticmethod
    def _adapt_document(legacy_doc: dict) -> TexasDocument:
        url = legacy_doc.get("document_url", "")
        # The legacy parser already absolute-resolves the URL via lxml's
        # rewrite_links; fall back to manual urljoin just in case.
        if url and not url.startswith("http"):
            url = urljoin(BASE_URL, url)
        size_bytes = legacy_doc.get("file_size_bytes")
        return TexasDocument(
            download_url=url,
            media_id=legacy_doc.get("media_id") or None,
            media_version_id=legacy_doc.get("media_version_id") or None,
            description=legacy_doc.get("description") or None,
            file_size_bytes=int(size_bytes) if size_bytes else None,
            file_size_str=legacy_doc.get("file_size_str") or None,
        )

    @classmethod
    def _adapt_originating_court(
        cls, legacy_oc: dict | None
    ) -> TexasOriginatingCourt | None:
        if not legacy_oc:
            return None
        return TexasOriginatingCourt(
            name=legacy_oc.get("name", ""),
            court_type=legacy_oc.get("court_type", ""),
            county=legacy_oc.get("county") or None,
            judge=legacy_oc.get("judge") or None,
            case_number=legacy_oc.get("case") or None,
            reporter=legacy_oc.get("reporter") or None,
            punishment=legacy_oc.get("punishment") or None,
            district=legacy_oc.get("district"),
            court_id=legacy_oc.get("court_id"),
        )

    @classmethod
    def _adapt_transfer(
        cls, legacy_transfer: dict | None
    ) -> TexasTransfer | None:
        if not legacy_transfer:
            return None
        # The legacy TypedDict stores ``court_id`` (e.g. "texas_coa07"), not
        # a display name; rebuild the display name from our ordinal map.
        other_court_id = legacy_transfer.get("court_id") or ""
        suffix = other_court_id.removeprefix("texas_coa")
        try:
            other_district = int(suffix)
        except ValueError:
            other_district = None
        other_name = (
            COA_DISTRICT_NAMES.get(other_district, other_court_id)
            if other_district is not None
            else other_court_id
        )

        return TexasTransfer(
            other_court_name=other_name,
            other_coa_district=other_district,
            transfer_date=cls._coerce_date(legacy_transfer.get("date")),
            origin_docket=legacy_transfer.get("origin_docket") or None,
        )

    @classmethod
    def _adapt_appeals_court_ref(
        cls, legacy_ac: dict | None
    ) -> TexasAppealsCourtRef | None:
        """Adapt the SC / CCA ``appeals_court`` TypedDict to ScrapedData.

        Maps the legacy ``texas_coaNN`` court ID to CourtListener's
        ``texapp`` and parses the COA district from the printed label.
        """
        if not legacy_ac:
            return None
        district_label = legacy_ac.get("district") or ""
        coa_district = (
            cls._other_court_district(district_label)
            if district_label
            else None
        )
        legacy_court_id = legacy_ac.get("court_id") or ""
        if legacy_court_id.startswith("texas_coa"):
            cl_court_id = "texapp"
        elif not legacy_court_id or legacy_court_id == CourtID.UNKNOWN.value:
            cl_court_id = None
        else:
            cl_court_id = legacy_court_id
        return TexasAppealsCourtRef(
            case_number=legacy_ac.get("case_number") or None,
            case_url=legacy_ac.get("case_url") or None,
            disposition=legacy_ac.get("disposition") or None,
            opinion_cite=legacy_ac.get("opinion_cite") or None,
            district=district_label or None,
            court_id=cl_court_id,
            coa_district=coa_district,
            justice=legacy_ac.get("justice") or None,
        )
