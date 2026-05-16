"""Minnesota P-MACS appellate docket scraper.

Scrapes case dockets from the public P-MACS C-Track site at
``macsnc.courts.state.mn.us``. The site sits behind an F5/Volterra
JavaScript challenge so the scraper requires a Playwright driver.

Pipeline:

- ``get_dockets_by_date`` posts the disclaimer-acceptance form so the
  rest of the session is authorised.
- ``_after_disclaimer`` posts a ``publicCaseSearch.do`` query covering
  the requested date range (sorted ASC by filing date so the boundary
  resume strategy below works).
- ``parse_search_results`` walks the paginated result table; for each
  row it yields a case-detail Request and tracks the ``min`` and
  ``max`` filing dates seen across pages.
- When the cap is hit (``total_records == 1000``) and at least two
  dates were seen, the step yields a resume search starting at
  ``max_filing_date_seen``. If every record in the cap shares one
  date the scraper raises ``SearchVolumeAssumptionError``.
- ``parse_case_detail`` parses the case info, party table, and docket
  table, then yields a fetch for the ``ORCA Info`` page so the
  originating-court info is attached before the entry walk starts.
- ``parse_orca_info`` parses the ``publicLowerCourtSummary.jsp`` page
  (Appeal From, Court/Agency, Other, Orig. Case Number / Title,
  Related Case Number(s), Decisionmakers) and attaches the
  ``MnOrcaInfo`` record to the docket. If any docket entry exposes a
  detail-page URL, the step walks them sequentially via
  ``parse_docket_entry_page`` to enumerate attached documents; the
  populated ``MnDocket`` is yielded after the walk completes.
- ``parse_docket_entry_page`` parses one ``docketEntry.do`` page,
  attaches the ``MnDocument`` records to the current entry, and yields
  ``archive=True`` Requests for each ``document.do`` URL it finds. The
  individual file downloads run in parallel even though the entry
  walks themselves are sequential.
- ``handle_document_download`` is a no-op continuation; kent's
  archive store records the file by deduplication key.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING, ClassVar
from urllib.parse import parse_qs, urljoin, urlparse

from jkent.common.decorators import entry, step
from jkent.common.exceptions import (
    ScraperAssumptionException,
)
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

from .models import (
    COURT_IDS,
    JURISDICTION_TO_COURT_ID,
    MnDocket,
    MnDocketEntry,
    MnDocument,
    MnOrcaInfo,
    MnParty,
)

if TYPE_CHECKING:
    from collections.abc import Generator

    from jkent.data_types import ScraperYield


BASE_URL = "https://macsnc.courts.state.mn.us"
LOGIN_URL = f"{BASE_URL}/ctrack/publicLogin.do"
SEARCH_URL = f"{BASE_URL}/ctrack/search/publicCaseSearch.do"
CASE_DETAIL_PATH = "/ctrack/view/publicCaseMaintenance.do"
ORCA_PATH = "/ctrack/view/publicLowerCourtSummary.jsp"

# Server-side display cap on the search results page.
RESULTS_CAP = 1000
PAGE_SIZE = 50

# Default lookback when no params are supplied.
DEFAULT_LOOKBACK_DAYS = 7

# Separator we use to join multi-select option text into the
# ``details`` dict-of-strings. Each individual option may contain ``;``
# or ``,`` (e.g. ``"Williams, Dale Allen, Sr.; Appellant: o/b/o Pro Se"``)
# so a generic separator like ``";"`` would split it. ``" || "`` is
# unlikely to appear in any displayed option text.
MULTI_VALUE_SEP = " || "


class SearchVolumeAssumptionError(ScraperAssumptionException):
    """Raised when a P-MACS date-range search returns the 1000-row cap
    on a single-day window — meaning more than 1000 cases were filed
    on the same day and the date-bisection trick can't subdivide
    further."""


class MinnesotaScraper(BaseScraper[MnDocket]):
    """Scraper for the Minnesota Supreme Court and Court of Appeals
    via the P-MACS public site.

    Usage:
        # Default: dockets filed in the last 7 days
        scraper = MinnesotaScraper()

        # Explicit date range
        params = MinnesotaScraper.params()
        params.MnDocket.date_filed.gte = date(2026, 4, 15)
        params.MnDocket.date_filed.lte = date(2026, 4, 30)
        scraper = MinnesotaScraper(params=params)
    """

    # === Metadata ===
    court_ids: ClassVar[set[str]] = set(COURT_IDS.keys())
    court_url: ClassVar[str] = "https://macsnc.courts.state.mn.us/"
    data_types: ClassVar[set[str]] = {"dockets"}
    status: ClassVar[ScraperStatus] = ScraperStatus.IN_DEVELOPMENT
    version: ClassVar[str] = "2026-04-30"
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
    def _parse_date(text: str | None) -> date | None:
        """Parse P-MACS date strings (``MM/DD/YYYY``)."""
        if not text:
            return None
        text = text.strip()
        for fmt in ("%m/%d/%Y", "%Y-%m-%d"):
            try:
                return datetime.strptime(text, fmt).date()
            except ValueError:
                continue
        return None

    @staticmethod
    def _normalize_ws(text: str | None) -> str:
        if not text:
            return ""
        return re.sub(r"\s+", " ", text).strip()

    @staticmethod
    def _split_br_lines(inner_html: str) -> list[str]:
        """Split a cell's inner HTML on ``<br>`` and return cleaned lines.

        The Attorney(s) column separates names with ``<br>`` tags which
        ``text_content()`` collapses; we recover them by stripping
        markup off each ``<br>``-delimited chunk.
        """
        if not inner_html:
            return []
        chunks = re.split(r"(?i)<br\s*/?>", inner_html)
        out: list[str] = []
        for chunk in chunks:
            stripped = re.sub(r"<[^>]+>", "", chunk)
            stripped = stripped.replace("\xa0", " ").replace("&nbsp;", " ")
            stripped = re.sub(r"\s+", " ", stripped).strip()
            if stripped:
                out.append(stripped)
        return out

    @staticmethod
    def _cell_lines(cell: PageElement) -> list[str]:
        """``<br>``-aware text extraction for a table cell."""
        try:
            inner = cell.inner_html() or ""
        except AttributeError:
            inner = ""
        leading = ""
        try:
            elem = cell._element._element  # type: ignore[attr-defined]
            leading = elem.text or ""
        except AttributeError:
            leading = ""
        return MinnesotaScraper._split_br_lines(leading + inner)

    def _get_param_date_range(self) -> tuple[date, date]:
        """Resolve a ``(date_gte, date_lte)`` pair from scraper params."""
        date_gte: date | None = None
        date_lte: date | None = None
        if self._params is not None:
            try:
                proxy = self._params.MnDocket  # type: ignore[attr-defined]
            except AttributeError:
                proxy = None
            if proxy is not None:
                searchable = proxy.get_searchable_fields()
                date_field = searchable.get("date_filed")
                if date_field and date_field.is_set():
                    date_gte = date_field.gte
                    date_lte = date_field.lte
        if date_lte is None:
            date_lte = date.today()
        if date_gte is None:
            date_gte = date_lte - timedelta(days=DEFAULT_LOOKBACK_DAYS)
        return date_gte, date_lte

    @staticmethod
    def _build_search_form(
        from_dt: date,
        to_dt: date,
        start_row: int = 1,
    ) -> dict[str, str]:
        """Build the POST body for the case-search form."""
        return {
            "csNumber": "",
            "shortTitle": "",
            "csGroupID": " ",
            "jurisdictionID": " ",
            "csStatusVal": " ",
            "csTypeID": " ",
            "fromDt": from_dt.strftime("%m/%d/%Y"),
            "toDt": to_dt.strftime("%m/%d/%Y"),
            "csSubTypeID": " ",
            "startRow": str(start_row),
            "displayRows": str(PAGE_SIZE),
            "orderBy": "SQLFileDt",
            # ASC so paginating to the last page yields the latest
            # filed-date in the result set, which is the resume
            # boundary on cap hits.
            "orderDir": "ASC",
            "hrefName": "/ctrack/cases/caseMaintenance.do?",
            "restrictBy": "",
            "submitValue": "Search" if start_row == 1 else "Sort",
            "action": "",
            "button": "Search",
        }

    def _yield_search_request(
        self,
        from_dt: date,
        to_dt: date,
        start_row: int = 1,
        accumulated_data: dict | None = None,
    ) -> Request:
        """Build a search Request for the given window + start row."""
        accumulated_data = dict(accumulated_data or {})
        accumulated_data.setdefault("from_dt", from_dt.isoformat())
        accumulated_data.setdefault("to_dt", to_dt.isoformat())
        accumulated_data["start_row"] = start_row
        return Request(
            request=HTTPRequestParams(
                method=HttpMethod.POST,
                url=SEARCH_URL,
                data=self._build_search_form(from_dt, to_dt, start_row),
            ),
            continuation=self.parse_search_results,
            accumulated_data=accumulated_data,
            deduplication_key=SkipDeduplicationCheck(),
        )

    # =========================================================================
    # Entry points
    # =========================================================================

    @entry(MnDocket)
    def get_dockets(self) -> Generator[Request, None, None]:
        """Date-range scan based on scraper params (defaults to the last
        ``DEFAULT_LOOKBACK_DAYS`` days)."""
        date_gte, date_lte = self._get_param_date_range()
        yield self._begin_session(date_gte, date_lte)

    @entry(MnDocket)
    def get_dockets_by_date(
        self,
        date_range: DateRange,
    ) -> Generator[Request, None, None]:
        """Date-range scan with explicit start / end dates."""
        yield self._begin_session(date_range.start, date_range.end)

    def _begin_session(self, from_dt: date, to_dt: date) -> Request:
        """Yield the disclaimer-acceptance POST so the rest of the
        session is authorised. The continuation kicks off the actual
        search."""
        return Request(
            request=HTTPRequestParams(
                method=HttpMethod.POST,
                url=LOGIN_URL,
                data={"submitValue": "Accept"},
            ),
            continuation=self._after_disclaimer,
            accumulated_data={
                "from_dt": from_dt.isoformat(),
                "to_dt": to_dt.isoformat(),
            },
            deduplication_key=SkipDeduplicationCheck(),
        )

    # =========================================================================
    # Step: post-disclaimer kicks off the date-range search
    # =========================================================================

    @step()
    def _after_disclaimer(
        self,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[MnDocket], None, None]:
        """After the disclaimer Accept POST settles, fire the first
        page of the date-range search."""
        from_dt = date.fromisoformat(accumulated_data["from_dt"])
        to_dt = date.fromisoformat(accumulated_data["to_dt"])
        yield self._yield_search_request(from_dt, to_dt, start_row=1)

    # =========================================================================
    # Step: parse a results page
    # =========================================================================

    @step()
    def parse_search_results(
        self,
        page: PageElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[MnDocket], None, None]:
        """Parse a P-MACS search-results page.

        Walks the result table, yields case-detail Requests for each
        row, paginates via ``startRow``, and resumes the scan with a
        new ``fromDt`` when the 1000-row cap was hit. Raises
        ``SearchVolumeAssumptionError`` if the cap is hit on a
        single-day window.
        """
        from_dt = date.fromisoformat(accumulated_data["from_dt"])
        to_dt = date.fromisoformat(accumulated_data["to_dt"])

        # === Pagination indicator ===
        # The page text contains a phrase like
        # ``1 to 50 of 128 records are displayed.`` — extract it.
        body_text = response.text or ""
        m = re.search(
            r"(\d+)\s+to\s+(\d+)\s+of\s+(\d+)\s+records",
            body_text,
        )
        if not m:
            # No results table at all (empty result set).
            return
        start_idx, end_idx, total = (int(m.group(i)) for i in (1, 2, 3))

        # === Result rows ===
        rows = page.query_xpath(
            "//tr[contains(@class, 'OddRow') or contains(@class, 'EvenRow')]"
            "[.//a[contains(@href, 'publicCaseMaintenance.do')]]",
            "result table rows",
            min_count=0,
        )

        page_dates: list[date] = []
        seen_in_request: set[str] = set()
        for row in rows:
            cells = row.query_xpath("./td", "result row cells", min_count=0)
            if len(cells) < 7:
                continue
            anchor_nodes = cells[0].query_xpath(
                ".//a", "case-number anchor", min_count=0, max_count=1
            )
            if not anchor_nodes:
                continue
            href = anchor_nodes[0].get_attribute("href")
            case_number = self._normalize_ws(anchor_nodes[0].text_content())
            jurisdiction = self._normalize_ws(cells[1].text_content())
            filing_date_str = self._normalize_ws(cells[6].text_content())
            row_date = self._parse_date(filing_date_str)
            if row_date is not None:
                page_dates.append(row_date)

            court_id = JURISDICTION_TO_COURT_ID.get(jurisdiction)
            if not court_id:
                # Skip rows whose jurisdiction isn't one of the two
                # appellate courts we model (e.g. Commitment Appeal
                # Panel).
                continue

            if not href:
                continue
            absolute = urljoin(response.url, href)
            if absolute in seen_in_request:
                continue
            seen_in_request.add(absolute)

            yield Request(
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url=absolute,
                ),
                continuation=self.parse_case_detail,
                accumulated_data={
                    "search_jurisdiction": jurisdiction,
                    "search_case_number": case_number,
                    "search_court_id": court_id,
                },
                deduplication_key=case_number or absolute,
            )

        # === Track min/max filing dates across pages ===
        min_seen_str = accumulated_data.get("min_date_seen")
        max_seen_str = accumulated_data.get("max_date_seen")
        min_seen = date.fromisoformat(min_seen_str) if min_seen_str else None
        max_seen = date.fromisoformat(max_seen_str) if max_seen_str else None
        if page_dates:
            page_min = min(page_dates)
            page_max = max(page_dates)
            min_seen = (
                page_min if min_seen is None else min(min_seen, page_min)
            )
            max_seen = (
                page_max if max_seen is None else max(max_seen, page_max)
            )

        # === Pagination: more pages remain in this interval? ===
        if end_idx < total:
            next_start = end_idx + 1
            yield self._yield_search_request(
                from_dt,
                to_dt,
                start_row=next_start,
                accumulated_data={
                    "min_date_seen": min_seen.isoformat()
                    if min_seen
                    else None,
                    "max_date_seen": max_seen.isoformat()
                    if max_seen
                    else None,
                    "total_records": total,
                },
            )
            return

        # === Last page of this interval — handle the cap ===
        if total < RESULTS_CAP:
            return

        if min_seen is None or max_seen is None:
            raise SearchVolumeAssumptionError(
                "P-MACS reports the 1000-row cap but no filing dates "
                "were parseable; cannot resume the search.",
                response.url,
            )

        if min_seen == max_seen:
            raise SearchVolumeAssumptionError(
                f"P-MACS returned the 1000-row cap on a single-day "
                f"window ({min_seen.isoformat()}); date bisection "
                f"cannot subdivide further.",
                response.url,
            )

        if max_seen >= to_dt:
            # Cap boundary is at the user's end date — nothing left to
            # scan.
            return

        # Resume scan from ``max_seen`` (boundary day inclusive — the
        # case-instance dedup key filters duplicates from the overlap).
        yield self._yield_search_request(
            max_seen,
            to_dt,
            start_row=1,
        )

    # =========================================================================
    # Step: parse a case-detail page
    # =========================================================================

    @step()
    def parse_case_detail(
        self,
        page: PageElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[MnDocket], None, None]:
        """Parse a ``publicCaseMaintenance.do`` case page into a single
        ``MnDocket``.
        """
        court_id = accumulated_data.get("search_court_id")
        if not court_id:
            # Fallback: derive from page jurisdiction text.
            jur = self._extract_label(page, "Jurisdiction")
            court_id = JURISDICTION_TO_COURT_ID.get(jur or "", "")
        if not court_id:
            return

        case_number = (
            self._extract_label(page, "Case Number")
            or accumulated_data.get("search_case_number")
            or ""
        )
        date_filed = self._parse_date(self._extract_label(page, "Filing Date"))
        jurisdiction = self._extract_label(page, "Jurisdiction")
        status = self._extract_label(page, "Status")
        orca = self._extract_label(page, "ORCA")
        hearing_type = self._extract_label(page, "Hearing Type")
        classification = self._extract_label(page, "Classification")
        short_title = self._extract_label(page, "Short Title")
        full_title = self._extract_label(page, "Full Title")
        summary = self._extract_label(page, "Summary")
        citation = self._extract_label(page, "Citation")

        # CSName/Instance ids — pull from the URL or the hidden form
        # inputs on the page.
        cs_name_id, cs_instance_id = self._extract_case_ids(response.url, page)

        parties = self._parse_parties(page)
        entries = self._parse_docket_entries(page, response.url)

        case_name = short_title or full_title or case_number

        docket = MnDocket(
            case_number=case_number,
            court_id=court_id,
            date_filed=date_filed,
            case_name=case_name,
            short_title=short_title or None,
            full_title=full_title or None,
            summary=summary or None,
            citation=citation or None,
            classification=classification or None,
            status=status or None,
            jurisdiction=jurisdiction or None,
            orca=orca or None,
            hearing_type=hearing_type or None,
            parties=parties,
            entries=entries,
            source_url=response.url,
            cs_name_id=cs_name_id,
            cs_instance_id=cs_instance_id,
        )

        # Fetch the ORCA Info (originating-court summary) page first
        # so its data is on the docket before we start the entry walk.
        # ``parse_orca_info`` then kicks off the entry walk, which
        # eventually emits the populated ``MnDocket``.
        if not cs_name_id or not cs_instance_id:
            # No ids — skip ORCA and go straight to the entry walk.
            yield from self._walk_next_entry(docket, prev_idx=-1)
            return

        orca_url = (
            f"{BASE_URL}{ORCA_PATH}"
            f"?csNameID={cs_name_id}&csInstanceID={cs_instance_id}"
        )
        yield Request(
            request=HTTPRequestParams(
                method=HttpMethod.GET,
                url=orca_url,
                headers={"Referer": response.url},
            ),
            continuation=self.parse_orca_info,
            accumulated_data={"docket": docket.model_dump(mode="json")},
            deduplication_key=f"orca:{docket.case_number}",
        )

    # =========================================================================
    # Step: parse the ORCA Info / Originating Court summary page
    # =========================================================================

    @step()
    def parse_orca_info(
        self,
        page: PageElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[MnDocket], None, None]:
        """Parse the ``publicLowerCourtSummary.jsp`` page and attach an
        ``MnOrcaInfo`` record to the docket before starting the entry
        walk."""
        docket = MnDocket.model_validate(accumulated_data["docket"])

        appeal_from = self._extract_label(page, "Appeal From")
        court_agency = self._extract_label(page, "Court/Agency")
        other = self._extract_label(page, "Other")
        orig_case_number = self._extract_label(page, "Orig. Case Number")
        orig_case_title = self._extract_label(page, "Orig. Case Title")
        related_raw = self._extract_label(page, "Related Case Number(s)")
        related_case_numbers = (
            [v.strip() for v in re.split(r",\s*", related_raw) if v.strip()]
            if related_raw
            else []
        )

        decisionmakers = self._parse_orca_decisionmakers(page)

        # Only attach the record if at least one field actually has a
        # value — empty ORCA pages would otherwise contribute a stub
        # record with no signal.
        any_value = any(
            [
                appeal_from,
                court_agency,
                other,
                orig_case_number,
                orig_case_title,
                related_case_numbers,
                decisionmakers,
            ]
        )
        if any_value:
            docket.orca_info = MnOrcaInfo(
                appeal_from=appeal_from or None,
                court_agency=court_agency or None,
                other=other or None,
                orig_case_number=orig_case_number or None,
                orig_case_title=orig_case_title or None,
                related_case_numbers=related_case_numbers,
                decisionmakers=decisionmakers,
                source_url=response.url,
            )

        yield from self._walk_next_entry(docket, prev_idx=-1)

    def _parse_orca_decisionmakers(self, page: PageElement) -> list[str]:
        """Collect every decisionmaker name listed under the
        ``Decisionmaker(s)`` subheading.

        Each name lives in a ``<td>`` inside a small inner ``<table>``
        immediately following the subheading row; subsequent
        decisionmakers repeat the same pattern but without re-printing
        the subheading. We anchor on the subheading and pick up every
        leaf ``<td>`` that follows in document order until we hit
        another subheading."""
        names: list[str] = []
        anchor_nodes = page.query_xpath(
            "//tr[contains(@class, 'TableSubHeading')]"
            "/td[contains(normalize-space(), 'Decisionmaker')]",
            "Decisionmaker(s) subheading",
            min_count=0,
            max_count=1,
        )
        if not anchor_nodes:
            return names

        following = page.query_xpath(
            "//tr[contains(@class, 'TableSubHeading')]"
            "/td[contains(normalize-space(), 'Decisionmaker')]"
            "/following::td[normalize-space() and not(*)"
            " and not(ancestor::tr[contains(@class, 'TableSubHeading')])"
            " and not(contains(@class, 'Label'))]",
            "decisionmaker name cells",
            min_count=0,
        )
        for node in following:
            name = self._normalize_ws(node.text_content())
            if name and name not in names:
                names.append(name)
        return names

    # =========================================================================
    # Step: parse a docket-entry detail page (per-entry document fetch)
    # =========================================================================

    @step()
    def parse_docket_entry_page(
        self,
        page: PageElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[MnDocket], None, None]:
        """Parse a ``docketEntry.do`` page.

        Captures the full set of entry-specific metadata fields (filing
        date/time, filed-by party list, signed-by judges, method of
        receipt/service, disposition type/details, …) plus every
        ``MnDocument`` attachment, then queues an ``archive=True``
        Request per document and chains to the next entry.
        """
        docket = MnDocket.model_validate(accumulated_data["docket"])
        entry_idx = accumulated_data["entry_idx"]
        entry = docket.entries[entry_idx]

        # === Entry detail fields ===
        details = self._parse_entry_detail_fields(page)
        entry.details = details
        self._populate_entry_typed_fields(entry, details)

        # === Document attachments + archive Requests ===
        anchors = page.query_xpath(
            "//a[contains(@href, '/ctrack/document.do?document=')]",
            "document.do download anchors",
            min_count=0,
        )

        documents: list[MnDocument] = []
        for anchor in anchors:
            href = anchor.get_attribute("href")
            if not href:
                continue
            absolute = urljoin(response.url, href)
            label = self._normalize_ws(anchor.text_content())
            documents.append(
                MnDocument(
                    label=label or "(unlabeled)",
                    document_url=absolute,
                    doc_entry_id=entry.doc_entry_id,
                )
            )

            doc_hash = self._extract_document_hash(absolute)
            yield Request(
                archive=True,
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url=absolute,
                ),
                continuation=self.handle_document_download,
                expected_type="pdf",
                accumulated_data={
                    "case_number": docket.case_number,
                    "doc_entry_id": entry.doc_entry_id,
                    "document_hash": doc_hash,
                    "label": label,
                },
                deduplication_key=(
                    f"doc:{docket.case_number}:{entry.doc_entry_id}:"
                    f"{doc_hash[:16]}"
                ),
            )

        entry.documents = documents
        yield from self._walk_next_entry(docket, prev_idx=entry_idx)

    # =========================================================================
    # Step: archive download handler (no-op)
    # =========================================================================

    @step()
    def handle_document_download(
        self,
        local_filepath: str | None,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[MnDocket], None, None]:
        """No-op continuation for archived ``document.do`` downloads.

        kent's archive store records the file location keyed by the
        Request's deduplication key; the already-emitted ``MnDocket``
        records the document URL alongside the entry, so the join back
        to the file is ``(case_number, doc_entry_id, document_url)``.
        """
        if False:
            yield  # pragma: no cover

    # =========================================================================
    # Helpers for the document walk
    # =========================================================================

    def _walk_next_entry(
        self,
        docket: MnDocket,
        prev_idx: int,
    ) -> Generator[ScraperYield[MnDocket], None, None]:
        """Yield the Request for the next entry after ``prev_idx`` that
        has an ``entry_url``. If there are no more entries to walk,
        yield the populated ``MnDocket`` instead."""
        next_idx = prev_idx + 1
        while next_idx < len(docket.entries):
            if docket.entries[next_idx].entry_url:
                break
            next_idx += 1
        if next_idx >= len(docket.entries):
            yield ParsedData(data=docket)
            return

        entry = docket.entries[next_idx]
        yield Request(
            request=HTTPRequestParams(
                method=HttpMethod.GET,
                url=entry.entry_url,  # type: ignore[arg-type]
            ),
            continuation=self.parse_docket_entry_page,
            accumulated_data={
                "docket": docket.model_dump(mode="json"),
                "entry_idx": next_idx,
            },
            deduplication_key=(
                f"entry:{docket.case_number}:{entry.doc_entry_id}"
            ),
        )

    @staticmethod
    def _extract_document_hash(url: str) -> str:
        """Pull the ``document=`` value out of a ``document.do`` URL."""
        try:
            qs = parse_qs(urlparse(url).query)
        except Exception:
            return url
        values = qs.get("document") or []
        return values[0] if values else url

    # =========================================================================
    # Entry-detail field harvesting
    # =========================================================================

    def _parse_entry_detail_fields(self, page: PageElement) -> dict[str, str]:
        """Return every label / value pair from the entry-specific
        section of a ``docketEntry.do`` page.

        The page repeats the parent case info up top (``class="label"``,
        lowercase) and then renders the entry-specific section using
        ``class="Label"`` (uppercase). We scope to the uppercase
        variant via an exact match so the case-info repeat is filtered
        out.

        Each value cell can render as:
        - One or more ``<option selected="...">``
        - One or more ``<input type="radio" checked="...">``
        - One or more ``<input type="checkbox" checked="...">``
        - Plain text
        """
        label_cells = page.query_xpath(
            "//td[@class='Label']",
            "entry-section label cells",
            min_count=0,
        )
        fields: dict[str, str] = {}
        for label_cell in label_cells:
            label_text = self._normalize_ws(label_cell.text_content()).rstrip(
                ":"
            )
            if not label_text:
                continue
            value_cells = label_cell.query_xpath(
                "./following-sibling::td[1]",
                "value cell after label",
                min_count=0,
                max_count=1,
            )
            if not value_cells:
                continue
            value = self._extract_field_value(value_cells[0])
            if value:
                fields[label_text] = value
        return fields

    def _extract_field_value(self, cell: PageElement) -> str:
        """Read the displayed value out of a label/value cell.

        Selects: read ``<option selected>`` text(s), joining with
        ``"; "`` for multi-selects.
        Radios: read the text adjacent to the ``checked`` input.
        Plain text: ``text_content()``.
        """
        # 1. Selected <option> values.
        selected_opts = cell.query_xpath(
            ".//option[@selected]",
            "selected options",
            min_count=0,
        )
        if selected_opts:
            texts = [
                self._normalize_ws(o.text_content()) for o in selected_opts
            ]
            return MULTI_VALUE_SEP.join(t for t in texts if t)

        # 2. Checked radio button — its tail text is the visible label.
        checked_radios = cell.query_xpath(
            ".//input[@type='radio'][@checked]",
            "checked radio inputs",
            min_count=0,
            max_count=1,
        )
        if checked_radios:
            try:
                elem = checked_radios[0]._element._element  # type: ignore[attr-defined]
                tail = elem.tail or ""
            except AttributeError:
                tail = ""
            return self._normalize_ws(tail)

        # 3. Empty <select> with no selected option — treat as blank.
        unselected_select = cell.query_xpath(
            ".//select",
            "any select",
            min_count=0,
            max_count=1,
        )
        if unselected_select:
            return ""

        # 4. Plain text.
        return self._normalize_ws(cell.text_content())

    def _populate_entry_typed_fields(
        self,
        entry: MnDocketEntry,
        details: dict[str, str],
    ) -> None:
        """Promote well-known label/value pairs into typed fields on
        ``MnDocketEntry``. Unknown labels remain only in
        ``entry.details``."""
        entry.entry_status = details.get("Status") or None
        entry.thread_to = details.get("Thread to") or None
        entry.method_of_receipt = details.get("Method of Receipt") or None
        entry.method_of_service = details.get("Method of Service") or None
        entry.method_of_payment = details.get("Method of Payment") or None
        entry.indicate_service = details.get("Indicate Service") or None
        entry.filing_fee = details.get("Filing Fee") or None
        entry.filing_date_time = details.get("Filing Date") or None
        entry.docket_entry_date_time = details.get("Docket Entry Date") or None
        entry.disposition_type = details.get("Order Disposition Type") or None
        entry.disposition_details = details.get("Disposition Details") or None
        entry.other_signatures = details.get("Other Signatures") or None
        entry.reporters = details.get("Reporter(s)") or None
        entry.date_of_hearings = details.get("Date of Hearing(s)") or None
        entry.comments = details.get("Comments") or None
        entry.other_deficiencies = details.get("Other Deficiencies") or None

        postmark_raw = details.get("Postmark Date (if by mail)") or ""
        entry.postmark_date = self._parse_date(postmark_raw)

        # Multi-select fields: split on the unique ``MULTI_VALUE_SEP``
        # we used in ``_extract_field_value``.
        filed_by_raw = details.get("Filed By") or ""
        entry.filed_by = (
            [v for v in filed_by_raw.split(MULTI_VALUE_SEP) if v.strip()]
            if filed_by_raw
            else []
        )
        signed_by_raw = details.get("Signed By") or ""
        entry.signed_by = (
            [v for v in signed_by_raw.split(MULTI_VALUE_SEP) if v.strip()]
            if signed_by_raw
            else []
        )

    # =========================================================================
    # Section parsers
    # =========================================================================

    def _extract_label(self, page: PageElement, label: str) -> str:
        """Return the value cell that follows a label cell.

        Case Information uses ``<td class="label">{Label}:</td><td>
        {Value}</td>`` pairs; the ORCA page uses ``class="Label"``
        (capital L). The XPath below is case-insensitive on the class
        attribute so it works for both."""
        nodes = page.query_xpath(
            f"//td[contains(translate(@class, 'L', 'l'), 'label') and "
            f"normalize-space(text())='{label}:']/following-sibling::td[1]",
            f"label cell for {label!r}",
            min_count=0,
            max_count=1,
        )
        if not nodes:
            return ""
        return self._normalize_ws(nodes[0].text_content())

    def _extract_case_ids(
        self, url: str, page: PageElement
    ) -> tuple[str | None, str | None]:
        """Pull the ``csNameID`` / ``csInstanceID`` ids out of the URL
        first; fall back to the hidden form inputs on the page."""
        try:
            qs = parse_qs(urlparse(url).query)
        except Exception:
            qs = {}
        cs_name_id = (qs.get("csNameID") or [None])[0]
        cs_instance_id = (qs.get("csInstanceID") or [None])[0]
        if cs_name_id and cs_instance_id:
            return cs_name_id, cs_instance_id

        for field, target in (
            ("csNameID", "name"),
            ("csInstanceID", "instance"),
        ):
            nodes = page.query_xpath(
                f"//input[@type='hidden' and @name='{field}']",
                f"hidden {field} input",
                min_count=0,
                max_count=1,
            )
            value = nodes[0].get_attribute("value") if nodes else None
            if target == "name" and value:
                cs_name_id = value
            elif target == "instance" and value:
                cs_instance_id = value
        return cs_name_id, cs_instance_id

    def _parse_parties(self, page: PageElement) -> list[MnParty]:
        rows = page.query_xpath(
            "//tr[contains(@class, 'TableHeading')]"
            "/td[normalize-space()='Party Information']"
            "/ancestor::table[1]"
            "//tr[contains(@class, 'OddRow') or contains(@class, 'EvenRow')]",
            "party rows",
            min_count=0,
        )
        parties: list[MnParty] = []
        for row in rows:
            cells = row.query_xpath("./td", "party cells", min_count=0)
            if len(cells) < 4:
                continue
            macs_id = self._normalize_ws(cells[0].text_content()) or None
            role = self._normalize_ws(cells[1].text_content()) or None
            name = self._normalize_ws(cells[2].text_content())
            if not name:
                continue
            attorney_lines = self._cell_lines(cells[3])
            attorneys = [
                line for line in attorney_lines if line.lower() != "pro se"
            ]
            parties.append(
                MnParty(
                    macs_id=macs_id,
                    role=role,
                    name=name,
                    attorneys=attorneys,
                )
            )
        return parties

    def _parse_docket_entries(
        self, page: PageElement, base_url: str
    ) -> list[MnDocketEntry]:
        rows = page.query_xpath(
            "//tr[contains(@class, 'TableHeading')]"
            "/td[normalize-space()='Docket Information']"
            "/ancestor::table[1]"
            "//tr[contains(@class, 'OddRow') or contains(@class, 'EvenRow')]",
            "docket rows",
            min_count=0,
        )
        entries: list[MnDocketEntry] = []
        for row in rows:
            cells = row.query_xpath("./td", "docket cells", min_count=0)
            if len(cells) < 6:
                continue
            description = self._normalize_ws(cells[0].text_content())
            jurisdiction = self._normalize_ws(cells[1].text_content())
            filing_date = self._parse_date(
                self._normalize_ws(cells[2].text_content())
            )
            entry_type = self._normalize_ws(cells[3].text_content())
            filing_type = self._normalize_ws(cells[4].text_content())
            status = self._normalize_ws(cells[5].text_content())

            entry_url = None
            doc_entry_id = None
            anchor_nodes = cells[0].query_xpath(
                ".//a", "entry anchor", min_count=0, max_count=1
            )
            if anchor_nodes:
                href = anchor_nodes[0].get_attribute("href")
                if href:
                    entry_url = urljoin(base_url, href)
                    qs = parse_qs(urlparse(entry_url).query)
                    doc_entry_id = (qs.get("deID") or [None])[0]

            entries.append(
                MnDocketEntry(
                    date_filed=filing_date,
                    description=description or None,
                    docket_entry_type=entry_type or None,
                    filing_type=filing_type or None,
                    status=status or None,
                    jurisdiction=jurisdiction or None,
                    doc_entry_id=doc_entry_id,
                    entry_url=entry_url,
                )
            )
        return entries
