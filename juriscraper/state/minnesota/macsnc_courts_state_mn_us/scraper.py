"""Minnesota P-MACS appellate docket scraper.

Site: https://macsnc.courts.state.mn.us/ctrack/

Scrapes case dockets from the public P-MACS C-Track site. The site sits
behind an F5/Volterra JavaScript challenge so the scraper requires a
Playwright driver (``JS_EVAL`` + ``FF_ALIKE``). P-MACS is the older
Java/JSP C-Track variant (sibling of the SC/DC HTML-form C-Track sites in
``juriscraper.state.common.ctrack``); it differs enough — a Volterra
challenge, a disclaimer-accept handshake, per-entry ``docketEntry.do``
document pages instead of DWR, an ORCA originating-court page, and a
1000-row search cap — that it carries its own form/parsing logic.

Per-page HTML extraction lives in the ``parsers`` package; the steps keep
navigation (the disclaimer POST, pagination, the cap date-bisection, the
ORCA fetch, the per-entry document walk, and the archive fan-out).

Entry points (§4):
    - dockets_by_filing_date(court_ids, date_range) — POST the date-range
      search; the server searches by filing date.
    - docket_by_number(court_id, docket_number)     — look up one docket
      by its appellate case number (e.g. ``A26-0748``).

Flow:
    entry → (POST publicLogin.do Accept) → after_disclaimer
          → POST publicCaseSearch.do → parse_search_results
              ├─ (per row) GET publicCaseMaintenance.do → parse_case_detail
              │     → ParsedData(MnDocket-stub) → GET ORCA → parse_orca_info
              │         → (per entry) GET docketEntry.do → parse_docket_entry_page
              │             ├─ ParsedData(MnDocket)  (after walk completes)
              │             └─ (per doc) archive document.do → handle_document_download
              └─ pagination / cap date-bisection re-POST → parse_search_results
"""

from __future__ import annotations

import re
from datetime import date
from typing import TYPE_CHECKING, ClassVar
from urllib.parse import parse_qs, urljoin, urlparse

from jkent.common.decorators import entry, step
from jkent.common.exceptions import ScraperAssumptionException
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

from .models import (
    BASE_URL,
    COURT_IDS,
    LOGIN_URL,
    ORCA_PATH,
    PAGE_SIZE,
    RESULTS_CAP,
    SEARCH_URL,
    MnDocket,
    MnDocument,
    MnOrcaInfo,
)
from .parsers import (
    CaseDetailParser,
    DocketEntryParser,
    OrcaInfoParser,
    SearchListingParser,
    populate_entry_typed_fields,
)

if TYPE_CHECKING:
    from collections.abc import Generator

    from jkent.common.page_element import PageElement
    from jkent.data_types import ScraperYield


class SearchVolumeAssumptionError(ScraperAssumptionException):
    """Raised when a P-MACS date-range search returns the 1000-row cap
    on a single-day window — meaning more than 1000 cases were filed on
    the same day and the date-bisection trick can't subdivide further."""


class MinnesotaScraper(BaseScraper[MnDocket | MnDocument]):
    """Scraper for the Minnesota Supreme Court and Court of Appeals
    via the P-MACS public C-Track site."""

    # === Metadata ===
    court_ids: ClassVar[set[str]] = set(COURT_IDS.keys())
    court_url: ClassVar[str] = f"{BASE_URL}/ctrack/"
    data_types: ClassVar[set[str]] = {"dockets"}
    status: ClassVar[ScraperStatus] = ScraperStatus.IN_DEVELOPMENT
    version: ClassVar[str] = "2026-06-27"
    last_verified: ClassVar[str] = "2026-04-30"
    requires_auth: ClassVar[bool] = False

    rate_limits: ClassVar[list[Rate] | None] = [Rate(2, Duration.SECOND)]
    driver_requirements: ClassVar[list[DriverRequirement]] = [
        DriverRequirement.JS_EVAL,
        DriverRequirement.FF_ALIKE,
    ]

    # =========================================================================
    # Search-form construction
    # =========================================================================

    @staticmethod
    def _build_search_form(
        *,
        from_dt: date | None = None,
        to_dt: date | None = None,
        cs_number: str = "",
        start_row: int = 1,
    ) -> dict[str, str]:
        """Build the POST body for the case-search form.

        ``orderDir=ASC`` so paginating to the last page reveals the latest
        filed-date in the result set, which is the resume boundary on cap
        hits.
        """
        return {
            "csNumber": cs_number,
            "shortTitle": "",
            "csGroupID": " ",
            "jurisdictionID": " ",
            "csStatusVal": " ",
            "csTypeID": " ",
            "fromDt": from_dt.strftime("%m/%d/%Y") if from_dt else "",
            "toDt": to_dt.strftime("%m/%d/%Y") if to_dt else "",
            "csSubTypeID": " ",
            "startRow": str(start_row),
            "displayRows": str(PAGE_SIZE),
            "orderBy": "SQLFileDt",
            "orderDir": "ASC",
            "hrefName": "/ctrack/cases/caseMaintenance.do?",
            "restrictBy": "",
            "submitValue": "Search" if start_row == 1 else "Sort",
            "action": "",
            "button": "Search",
        }

    def _begin_session(
        self, accumulated: dict, *, deduplication_key: str
    ) -> Request:
        """POST the disclaimer-acceptance form so the rest of the session
        is authorised. The continuation kicks off the actual search."""
        return Request(
            request=HTTPRequestParams(
                method=HttpMethod.POST,
                url=LOGIN_URL,
                data={"submitValue": "Accept"},
            ),
            continuation=self.after_disclaimer,
            accumulated_data=accumulated,
            deduplication_key=deduplication_key,
        )

    def _yield_search_request(
        self,
        from_dt: date,
        to_dt: date,
        start_row: int = 1,
        accumulated_data: dict | None = None,
    ) -> Request:
        """Build a date-range search Request for the given window + row."""
        accumulated_data = dict(accumulated_data or {})
        accumulated_data.setdefault("from_dt", from_dt.isoformat())
        accumulated_data.setdefault("to_dt", to_dt.isoformat())
        accumulated_data["start_row"] = start_row
        return Request(
            request=HTTPRequestParams(
                method=HttpMethod.POST,
                url=SEARCH_URL,
                data=self._build_search_form(
                    from_dt=from_dt, to_dt=to_dt, start_row=start_row
                ),
            ),
            continuation=self.parse_search_results,
            accumulated_data=accumulated_data,
            # Paginating POSTs re-issue the same form with an advanced
            # startRow / a new fromDt; dedup would collapse them.
            deduplication_key=SkipDeduplicationCheck(),
        )

    # =========================================================================
    # Entry points (§4)
    # =========================================================================

    @entry(MnDocket)
    def dockets_by_filing_date(
        self, court_ids: set[str], date_range: InferrableDateRange
    ) -> Generator[Request, None, None]:
        """Scan every appellate filing in a filed-date window.

        The disclaimer Accept POST is fired first; ``after_disclaimer``
        then launches the date-range search. ``target_courts`` rides the
        request chain so the listing rows are filtered to the seeded set.
        """
        yield self._begin_session(
            {
                "from_dt": date_range.start.isoformat(),
                "to_dt": date_range.end.isoformat(),
                "target_courts": sorted(court_ids),
                "entry_point": "dockets_by_filing_date",
            },
            deduplication_key=(
                f"session_seed:filing_date:"
                f"{date_range.start.isoformat()}:{date_range.end.isoformat()}"
            ),
        )

    @entry(MnDocket)
    def docket_by_number(
        self, court_id: str, docket_number: str
    ) -> Generator[Request, None, None]:
        """Look up one docket by its appellate case number (e.g. ``A26-0748``)."""
        clean = docket_number.strip()
        yield self._begin_session(
            {
                "cs_number": clean,
                "target_courts": [court_id],
                "entry_point": "docket_by_number",
            },
            deduplication_key=f"session_seed:number:{clean}",
        )

    # =========================================================================
    # Step: post-disclaimer kicks off the search
    # =========================================================================

    @step(priority=6)
    def after_disclaimer(
        self, accumulated_data: dict
    ) -> Generator[ScraperYield[MnDocket], None, None]:
        """After the disclaimer Accept POST settles, fire the search."""
        if accumulated_data.get("cs_number"):
            yield Request(
                request=HTTPRequestParams(
                    method=HttpMethod.POST,
                    url=SEARCH_URL,
                    data=self._build_search_form(
                        cs_number=accumulated_data["cs_number"]
                    ),
                ),
                continuation=self.parse_search_results,
                accumulated_data=accumulated_data,
                deduplication_key=(
                    f"search:number:{accumulated_data['cs_number']}"
                ),
            )
            return

        from_dt = date.fromisoformat(accumulated_data["from_dt"])
        to_dt = date.fromisoformat(accumulated_data["to_dt"])
        yield self._yield_search_request(
            from_dt,
            to_dt,
            start_row=1,
            accumulated_data={
                "target_courts": accumulated_data["target_courts"],
                "entry_point": accumulated_data["entry_point"],
            },
        )

    # =========================================================================
    # Step: parse a results page
    # =========================================================================

    @step(priority=5)
    def parse_search_results(
        self,
        page: PageElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[MnDocket], None, None]:
        """Parse a P-MACS search-results page.

        Delegates row extraction to ``SearchListingParser``, yields a
        case-detail Request per row (filtered to the seeded courts),
        paginates via ``startRow``, and resumes the scan with a new
        ``fromDt`` when the 1000-row cap was hit. Raises
        ``SearchVolumeAssumptionError`` if the cap is hit on a single-day
        window.
        """
        target_courts = set(accumulated_data.get("target_courts", []))
        entry_point = accumulated_data.get("entry_point")

        # === Pagination indicator ===
        # The page text contains "1 to 50 of 128 records are displayed."
        m = re.search(
            r"(\d+)\s+to\s+(\d+)\s+of\s+(\d+)\s+records", response.text or ""
        )
        if not m:
            return  # No results table at all (empty result set).
        _, end_idx, total = (int(m.group(i)) for i in (1, 2, 3))

        page_dates: list[date] = []
        seen_in_request: set[str] = set()
        for dv in SearchListingParser()(page):
            row = dv.raw_data
            court = row["court"]
            if target_courts and court not in target_courts:
                continue
            row_date_str = row.get("row_filing_date")
            if row_date_str:
                page_dates.append(date.fromisoformat(row_date_str))

            href = row.get("detail_href")
            if not href:
                continue
            absolute = urljoin(response.url, href)
            if absolute in seen_in_request:
                continue
            seen_in_request.add(absolute)

            yield Request(
                request=HTTPRequestParams(method=HttpMethod.GET, url=absolute),
                continuation=self.parse_case_detail,
                accumulated_data={
                    "search_court": court,
                    "search_docket_number": row["docket_number"],
                    "entry_point": entry_point,
                },
                deduplication_key=f"docket_detail:{row['docket_number']}",
            )

        # === Track min/max filing dates across pages (cap bisection) ===
        min_seen_str = accumulated_data.get("min_date_seen")
        max_seen_str = accumulated_data.get("max_date_seen")
        min_seen = date.fromisoformat(min_seen_str) if min_seen_str else None
        max_seen = date.fromisoformat(max_seen_str) if max_seen_str else None
        if page_dates:
            page_min, page_max = min(page_dates), max(page_dates)
            min_seen = (
                page_min if min_seen is None else min(min_seen, page_min)
            )
            max_seen = (
                page_max if max_seen is None else max(max_seen, page_max)
            )

        # A case-number lookup doesn't carry a date window; nothing to
        # paginate / bisect.
        if "from_dt" not in accumulated_data:
            return

        from_dt = date.fromisoformat(accumulated_data["from_dt"])
        to_dt = date.fromisoformat(accumulated_data["to_dt"])

        # === Pagination: more pages remain in this interval? ===
        if end_idx < total:
            yield self._yield_search_request(
                from_dt,
                to_dt,
                start_row=end_idx + 1,
                accumulated_data={
                    "target_courts": sorted(target_courts),
                    "entry_point": entry_point,
                    "min_date_seen": (
                        min_seen.isoformat() if min_seen else None
                    ),
                    "max_date_seen": (
                        max_seen.isoformat() if max_seen else None
                    ),
                    "total_records": total,
                },
            )
            return

        # === Last page of this interval — handle the cap ===
        if total < RESULTS_CAP:
            return

        if min_seen is None or max_seen is None:
            raise SearchVolumeAssumptionError(
                "P-MACS reports the 1000-row cap but no filing dates were "
                "parseable; cannot resume the search.",
                response.url,
            )
        if min_seen == max_seen:
            raise SearchVolumeAssumptionError(
                f"P-MACS returned the 1000-row cap on a single-day window "
                f"({min_seen.isoformat()}); date bisection cannot subdivide "
                f"further.",
                response.url,
            )
        if max_seen >= to_dt:
            return  # Cap boundary is at the user's end date.

        # Resume scan from ``max_seen`` (boundary day inclusive — the
        # docket-number dedup key filters duplicates from the overlap).
        yield self._yield_search_request(
            max_seen,
            to_dt,
            start_row=1,
            accumulated_data={
                "target_courts": sorted(target_courts),
                "entry_point": entry_point,
            },
        )

    # =========================================================================
    # Step: parse a case-detail page
    # =========================================================================

    @step(priority=4)
    def parse_case_detail(
        self,
        page: PageElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[MnDocket], None, None]:
        """Parse a ``publicCaseMaintenance.do`` page into an ``MnDocket``.

        ``CaseDetailParser`` owns the page extraction; the step stamps the
        court/source fields and decides whether to fetch the ORCA page
        before starting the entry walk.
        """
        raw = CaseDetailParser(base_url=response.url)(page)[0].raw_data
        court = raw.get("court") or accumulated_data.get("search_court") or ""
        docket_number = (
            raw.get("docket_number")
            or accumulated_data.get("search_docket_number")
            or ""
        )
        if not court:
            return

        # Prefer the csNameID / csInstanceID parsed from the URL.
        url_ids = self._extract_url_case_ids(response.url)
        cs_name_id = url_ids[0] or raw.get("cs_name_id")
        cs_instance_id = url_ids[1] or raw.get("cs_instance_id")

        raw.update(
            {
                "court": court,
                "docket_number": docket_number,
                "case_name": raw.get("case_name") or docket_number,
                "source_url": response.url,
                "source_entry_point": accumulated_data.get("entry_point"),
                "cs_name_id": cs_name_id,
                "cs_instance_id": cs_instance_id,
            }
        )
        docket = MnDocket(**raw)

        # Fetch the ORCA Info page first so its data is on the docket
        # before the entry walk; ORCA then kicks off the walk, which
        # emits the populated MnDocket.
        if not cs_name_id or not cs_instance_id:
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
            deduplication_key=f"orca:{docket.docket_number}",
        )

    # =========================================================================
    # Step: parse the ORCA Info / Originating Court summary page
    # =========================================================================

    @step(priority=3)
    def parse_orca_info(
        self,
        page: PageElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[MnDocket], None, None]:
        """Parse ``publicLowerCourtSummary.jsp`` and attach an
        ``MnOrcaInfo`` to the docket before the entry walk."""
        docket = MnDocket.model_validate(accumulated_data["docket"])

        parsed = OrcaInfoParser()(page)
        if parsed:
            orca = MnOrcaInfo(**parsed[0].raw_data)
            orca.source_url = response.url
            docket.orca_info = orca

        yield from self._walk_next_entry(docket, prev_idx=-1)

    # =========================================================================
    # Step: parse a docket-entry detail page (per-entry document fetch)
    # =========================================================================

    @step(priority=2)
    def parse_docket_entry_page(
        self,
        page: PageElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[MnDocket], None, None]:
        """Parse a ``docketEntry.do`` page: harvest the entry-specific
        detail fields and queue an ``archive=True`` Request per attached
        document, then chain to the next entry."""
        docket = MnDocket.model_validate(accumulated_data["docket"])
        entry_idx = accumulated_data["entry_idx"]
        entry_obj = docket.entries[entry_idx]

        parser = DocketEntryParser(
            base_url=response.url, doc_entry_id=entry_obj.doc_entry_id
        )

        # === Entry detail fields ===
        details = parser.parse_detail_fields(page)
        entry_obj.details = details
        populate_entry_typed_fields(entry_obj, details)

        # === Document attachments + archive Requests ===
        documents: list[MnDocument] = []
        for dv in parser(page):
            doc = MnDocument(**dv.raw_data)
            documents.append(doc)
            doc_hash = self._extract_document_hash(doc.document_url)
            yield Request(
                archive=True,
                request=HTTPRequestParams(
                    method=HttpMethod.GET, url=doc.document_url
                ),
                continuation=self.handle_document_download,
                expected_type="pdf",
                accumulated_data={
                    "docket_number": docket.docket_number,
                    "court": docket.court,
                    "doc_entry_id": entry_obj.doc_entry_id,
                    "document_url": doc.document_url,
                    "label": doc.label,
                },
                # File-download key — no colons (used in filenames).
                deduplication_key=(
                    f"{docket.docket_number}-{entry_obj.doc_entry_id}-"
                    f"{doc_hash[:16]}"
                ),
            )

        entry_obj.documents = documents
        yield from self._walk_next_entry(docket, prev_idx=entry_idx)

    # =========================================================================
    # Step: archive download handler
    # =========================================================================

    @step()
    def handle_document_download(
        self,
        accumulated_data: dict,
        local_filepath: str | None = None,
    ) -> Generator[ScraperYield[MnDocument], None, None]:
        """Emit one ``MnDocument`` for an archived ``document.do`` file."""
        yield ParsedData(
            data=MnDocument(
                label=accumulated_data["label"],
                document_url=accumulated_data["document_url"],
                doc_entry_id=accumulated_data.get("doc_entry_id"),
            )
        )

    # =========================================================================
    # Helpers for the entry walk
    # =========================================================================

    def _walk_next_entry(
        self, docket: MnDocket, prev_idx: int
    ) -> Generator[ScraperYield[MnDocket], None, None]:
        """Yield the Request for the next entry after ``prev_idx`` that has
        an ``entry_url``. If there are no more entries to walk, yield the
        populated ``MnDocket`` instead."""
        next_idx = prev_idx + 1
        while next_idx < len(docket.entries):
            if docket.entries[next_idx].entry_url:
                break
            next_idx += 1
        if next_idx >= len(docket.entries):
            yield ParsedData(data=docket)
            return

        entry_obj = docket.entries[next_idx]
        yield Request(
            request=HTTPRequestParams(
                method=HttpMethod.GET,
                url=entry_obj.entry_url,  # type: ignore[arg-type]
            ),
            continuation=self.parse_docket_entry_page,
            accumulated_data={
                "docket": docket.model_dump(mode="json"),
                "entry_idx": next_idx,
            },
            deduplication_key=(
                f"docket_entry:{docket.docket_number}:{entry_obj.doc_entry_id}"
            ),
        )

    @staticmethod
    def _extract_url_case_ids(url: str) -> tuple[str | None, str | None]:
        """Pull ``csNameID`` / ``csInstanceID`` out of a case-detail URL."""
        try:
            qs = parse_qs(urlparse(url).query)
        except Exception:  # noqa: BLE001
            return None, None
        return (qs.get("csNameID") or [None])[0], (
            qs.get("csInstanceID") or [None]
        )[0]

    @staticmethod
    def _extract_document_hash(url: str) -> str:
        """Pull the ``document=`` value out of a ``document.do`` URL."""
        try:
            qs = parse_qs(urlparse(url).query)
        except Exception:  # noqa: BLE001
            return url
        values = qs.get("document") or []
        return values[0] if values else url
