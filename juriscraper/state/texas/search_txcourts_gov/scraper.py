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

See ``CC_NOTES.md`` in this directory for the full site analysis.

Per-page HTML extraction (and the legacy → ``ScrapedData`` adaptation)
lives in the ``parsers`` package: ``SearchResultsParser`` for the result
grid, ``CaseDetailParser`` for a single case page. ``CaseDetailParser``
routes on the docket number's format (or the URL's ``coa=`` parameter) to
the proven per-court legacy parsers in ``juriscraper.state.texas.*`` and
adapts the result to a ``TexasDocket``. The steps here keep only
navigation (the search POST, pagination, window splitting, and the
per-document archive fan-out).
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import TYPE_CHECKING, ClassVar

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
    SkipDeduplicationCheck,
)
from pyrate_limiter import Duration, Rate

from juriscraper.state.common.params import InferrableDateRange

from .models import BASE_URL, SEARCH_URL, TexasDocket, TexasDocument
from .parsers import CaseDetailParser, SearchResultsParser

if TYPE_CHECKING:
    from collections.abc import Generator

    from jkent.common.page_element import PageElement
    from jkent.data_types import ScraperYield

# =========================================================================
# Site constants
# =========================================================================

# TAMES caps each search at the most recent 1000 rows. When a date window
# returns exactly this many we split it in half and re-search each half.
MAX_RESULTS_PER_SEARCH = 1000

# All 17 appellate-court checkboxes on the form. Indexes 0 and 1 are the
# Supreme Court and Court of Criminal Appeals; 2..16 are the 15 COAs.
ALL_APPELLATE_CHECKBOX_INDEXES = tuple(range(17))


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

# Shared parser instances (parsers are stateless extraction callables).
_RESULTS_PARSER = SearchResultsParser()
_DETAIL_PARSER = CaseDetailParser()


class TexasTamesScraper(BaseScraper[_Yield]):
    """Scraper for all 17 Texas appellate courts via TAMES.

    Walks the ``/CaseSearch.aspx`` Date-Filed search across every appellate
    court at once, recursively halving the date window whenever the
    1000-row cap is hit, paginating each leaf search, fetching each
    case-detail page (routing to the right per-court parser based on the
    docket number / ``coa=`` parameter), and archiving every document
    linked from the docket.
    """

    # === Metadata (§3) ===
    court_ids: ClassVar[set[str]] = {"tex", "texcrimapp", "texapp"}
    court_url: ClassVar[str] = SEARCH_URL
    data_types: ClassVar[set[str]] = {"dockets"}
    status: ClassVar[ScraperStatus] = ScraperStatus.IN_DEVELOPMENT
    version: ClassVar[str] = "2026-06-27"
    last_verified: ClassVar[str] = "2026-05-21"
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
    # Entry points (§4)
    # =========================================================================

    @entry(TexasDocket)
    def dockets_by_filing_date(
        self, court_ids: set[str], date_range: InferrableDateRange
    ) -> Generator[Request, None, None]:
        """Walk the TAMES Date-Filed search for the requested window.

        Emits a single GET against the search form; the chain
        (``fetch_search_form`` → ``parse_search_results``) takes over from
        there. The server enforces the date window across all 17 appellate
        courts at once, so ``court_ids`` is informational here (the full
        appellate set is always covered).
        """
        yield self._build_form_get_request(date_range.start, date_range.end)

    @entry(TexasDocket)
    def docket_by_number(
        self, court_id: str, docket_number: str
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
                "docket_number": docket_number,
                "source_url": case_url,
                "entry_point": "docket_by_number",
            },
            deduplication_key=f"case_detail:{docket_number}",
        )

    # =========================================================================
    # Step: GET the search form so we can capture the ASP.NET hidden fields
    # =========================================================================

    @step(priority=4)
    def fetch_search_form(
        self,
        page: PageElement,
        accumulated_data: dict,
    ) -> Generator[ScraperYield, None, None]:
        """Extract the hidden ASP.NET fields and submit the search."""
        hidden_fields = _RESULTS_PARSER.hidden_fields(page)
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
                f"search_results:{start_date.isoformat()}:{end_date.isoformat()}"
            ),
        )

    # =========================================================================
    # Step: parse a results page, handle pagination + window splitting
    # =========================================================================

    @step(priority=3)
    def parse_search_results(
        self,
        page: PageElement,
        accumulated_data: dict,
    ) -> Generator[ScraperYield, None, None]:
        """Walk one page of search results, paginate, or split the window."""
        page_num = int(accumulated_data.get("page_num", 1))
        start_date = date.fromisoformat(accumulated_data["start_date"])
        end_date = date.fromisoformat(accumulated_data["end_date"])

        # Window-split decision is only made on the first page; once we've
        # committed to paginating we don't re-evaluate.
        if page_num == 1:
            result_count = _RESULTS_PARSER.result_count(page)
            if (
                result_count >= MAX_RESULTS_PER_SEARCH
                and start_date < end_date
            ):
                yield from self._split_window(start_date, end_date)
                return

        for row in _RESULTS_PARSER.case_rows(page):
            yield Request(
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url=row.case_url,
                    headers=_GET_HEADERS,
                ),
                continuation=self.parse_case_detail,
                accumulated_data={
                    "docket_number": row.docket_number,
                    "source_url": row.case_url,
                    "entry_point": "dockets_by_filing_date",
                },
                # Same case may show up in overlapping splits — dedupe on docket.
                deduplication_key=f"case_detail:{row.docket_number}",
            )

        # Pagination: rgPageNext is a submit button that re-POSTs the form
        # with __EVENTTARGET pointing at the next-page control. We harvest
        # its name+value, re-extract VIEWSTATE (it changes on each POST),
        # and emit a new search POST.
        submitter = _RESULTS_PARSER.next_page_submitter(page)
        if submitter is not None:
            submit_name, submit_val = submitter
            hidden_fields = _RESULTS_PARSER.hidden_fields(page)

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

    @step(priority=2)
    def parse_case_detail(
        self,
        page: PageElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield, None, None]:
        """Parse Case.aspx and emit a ``TexasDocket``.

        ``CaseDetailParser`` owns the page extraction and per-court routing;
        the step stamps the provenance fields not present on the page
        (``source_url``, ``source_entry_point``), emits the docket, then
        fans out an ``archive=True`` Request for every attached document.
        ``raw_data`` returns a copy, so we re-wrap with the merged fields
        rather than mutating the parser's deferred value in place.
        """
        deferred = _DETAIL_PARSER(page)[0]
        raw = deferred.raw_data
        raw["source_url"] = accumulated_data.get("source_url") or response.url
        raw["source_entry_point"] = accumulated_data.get("entry_point")
        docket = TexasDocket.raw(**raw)
        yield ParsedData(docket)

        # Fan out an archive request per document. The docket already has
        # the same `TexasDocument` objects embedded for snapshot/joining;
        # the archive handler emits a standalone copy with `local_path` set.
        # Loop var named ``docket_entry`` to avoid shadowing the imported
        # ``entry`` decorator.
        docket_number = raw.get("docket_number")
        for docket_entry in raw.get("entries", []):
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
                        "docket_number": docket_number,
                        "entry_kind": docket_entry.kind,
                        "entry_number": docket_entry.entry_number,
                        "document": doc.model_dump(mode="json"),
                    },
                    # MediaID is the durable identifier for a document;
                    # MediaVersionID changes on revisions. Dedupe on the
                    # versioned pair so we re-archive across revisions but
                    # not within the same scrape window. File-download keys
                    # avoid colons (they become filenames).
                    deduplication_key=(
                        f"doc-{doc.media_id}-{doc.media_version_id}"
                        if doc.media_id
                        else f"doc-url-{abs(hash(doc.download_url))}"
                    ),
                )

    @step(priority=0)
    def handle_document_download(
        self,
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
                docket_number=accumulated_data.get("docket_number"),
                docket_entry_kind=accumulated_data.get("entry_kind"),
                docket_entry_number=accumulated_data.get("entry_number"),
            )
        )

    # =========================================================================
    # HTTP status handling (§10)
    # =========================================================================

    HTTP_CODE_TYPES: ClassVar[dict] = {}

    def actually_successful(self, response: Response) -> bool:
        """Detect the soft-404 for an invalid case number.

        An invalid case number redirects to
        ``/CaseSearch.aspx?ex=InvalidCaseNumber&...``. Real cases land on
        ``/Case.aspx?cn=...`` and pass the check.
        """
        url = response.url or ""
        return "ex=InvalidCaseNumber" not in url

    # =========================================================================
    # Helpers — form building / navigation
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
                f"search_form:{start_date.isoformat()}:{end_date.isoformat()}"
            ),
        )

    @classmethod
    def _build_search_form_data(
        cls,
        hidden_fields: dict[str, str],
        start_date: date,
        end_date: date,
    ) -> dict[str, str]:
        """Compose the POST body for a date-range search across all courts."""
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

    def _split_window(
        self, start_date: date, end_date: date
    ) -> Generator[Request, None, None]:
        """Fan out two new searches when the 1000-row cap is hit."""
        span = (end_date - start_date).days
        mid = start_date + timedelta(days=span // 2)
        yield self._build_form_get_request(start_date, mid)
        yield self._build_form_get_request(mid + timedelta(days=1), end_date)
