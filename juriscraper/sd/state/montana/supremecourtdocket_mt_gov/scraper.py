"""Montana Supreme Court Scraper.

Scrapes docket data from the Montana Supreme Court public docket search at
supremecourtdocket.mt.gov via its JSON API. No HTML parsing is needed; the
public web app is an Angular SPA that calls a plain REST backend.

Entry points (one per site category, plus a by-number lookup):

- active_dockets_by_date(date_range)      — caseStatus 0 (Active)
- closed_dockets_by_date(date_range)      — caseStatus 1 (Closed 2006+)
- archived_dockets_by_date(date_range)    — caseStatus 2 (Closed 1979-2005)
- fetch_docket_by_number(case_number)     — case number lookup across all
                                             three categories.

For each matching case, the scraper fetches case-info, yields MtDocket,
then schedules an archive download for every referenced document unless
the document is marked "Unavailable.pdf" (sealed) — in which case it
yields an MtSealedDocument instead.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from typing import TYPE_CHECKING, Any, ClassVar
from urllib.parse import quote

from jkent.common.decorators import entry, step
from jkent.common.param_models import DateRange
from jkent.data_types import (
    BaseScraper,
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
    MtAttorney,
    MtDocket,
    MtDocketEntry,
    MtDocument,
    MtParty,
    MtSealedDocument,
)

if TYPE_CHECKING:
    from collections.abc import Generator

    from jkent.data_types import ScraperYield


BASE_URL = "https://supremecourtdocket.mt.gov"
SEARCH_URL = f"{BASE_URL}/api/docket/search"
CASE_INFO_URL = f"{BASE_URL}/api/docket/case-info"
CASE_INFO_PRE_2006_URL = f"{BASE_URL}/api/docket/case-info-pre-2006"
DOC_MODERN_URL = f"{BASE_URL}/api/filenet/get-content-by-ctrack-id"
DOC_ARCHIVE_URL = f"{BASE_URL}/api/filenet/get-content"

DEFAULT_PAGE_SIZE = 100

# case-info payload flags a sealed document with these exact values.
SEALED_DOCUMENT_LOCATION = "Unavailable.pdf"
SEALED_DOCUMENT_ID = "0"
SEALED_FILENET_ID = "{0}"

# Site categories mapped to the API's caseStatus integer.
CATEGORY_ACTIVE = "active"
CATEGORY_CLOSED = "closed"
CATEGORY_ARCHIVE = "archive"

CATEGORY_STATUS: dict[str, int] = {
    CATEGORY_ACTIVE: 0,
    CATEGORY_CLOSED: 1,
    CATEGORY_ARCHIVE: 2,
}


class MontanaSupremeCourtScraper(
    BaseScraper[MtDocket | MtDocument | MtSealedDocument]
):
    """Scraper for the Montana Supreme Court public docket search.

    Speaks the site's JSON API directly. Emits three record types:

    - ``MtDocket`` — one per case, with nested parties and entry manifest.
    - ``MtDocument`` — one per archived file download.
    - ``MtSealedDocument`` — one per "Unavailable.pdf" reference; no
      download is scheduled for these.
    """

    court_ids: ClassVar[set[str]] = {"mont"}
    court_url: ClassVar[str] = BASE_URL
    data_types: ClassVar[set[str]] = {"dockets"}
    status: ClassVar[ScraperStatus] = ScraperStatus.IN_DEVELOPMENT
    version: ClassVar[str] = "2026-04-17"
    requires_auth: ClassVar[bool] = False
    rate_limits: ClassVar[list[Rate] | None] = [Rate(3, Duration.SECOND)]

    # =========================================================================
    # Entry points
    # =========================================================================

    @entry(MtDocket)
    def active_dockets_by_date(
        self, date_range: DateRange
    ) -> Generator[Request, None, None]:
        """Active Dockets: caseStatus=0, filtered by caseFilingDate."""
        yield self._build_search_request(CATEGORY_ACTIVE, date_range, page=0)

    @entry(MtDocket)
    def closed_dockets_by_date(
        self, date_range: DateRange
    ) -> Generator[Request, None, None]:
        """Closed Dockets (2006+): caseStatus=1, filtered by caseFilingDate."""
        yield self._build_search_request(CATEGORY_CLOSED, date_range, page=0)

    @entry(MtDocket)
    def archived_dockets_by_date(
        self, date_range: DateRange
    ) -> Generator[Request, None, None]:
        """Closed Dockets (1979-2005): caseStatus=2.

        The archive endpoint does not meaningfully support filing-date
        filtering today (server returns 500 when only dates are supplied;
        otherwise ``caseFilingDate`` is null on archive records so the
        filter matches nothing). The request is still sent so the scraper
        will pick up results automatically if/when the upstream API is
        fixed.
        """
        yield self._build_search_request(CATEGORY_ARCHIVE, date_range, page=0)

    @entry(MtDocket)
    def fetch_docket_by_number(
        self, case_number: str
    ) -> Generator[Request, None, None]:
        """Look up a case by its public docket number.

        Because docket numbers are reused between the three categories and
        the API requires a caseStatus, a search is dispatched for each of
        the three categories. The first one that returns the case will
        drive the detail fetch; subsequent hits dedupe on the case's
        detail URL.
        """
        for category in (CATEGORY_ACTIVE, CATEGORY_CLOSED, CATEGORY_ARCHIVE):
            yield Request(
                request=HTTPRequestParams(
                    method=HttpMethod.POST,
                    url=SEARCH_URL,
                    headers={"Content-Type": "application/json"},
                    data=_encode_json_body(
                        self._build_search_body(
                            category=category,
                            date_range=None,
                            case_number=case_number,
                            page=0,
                        )
                    ),
                ),
                continuation=self.parse_search_results,
                accumulated_data={
                    "category": category,
                    "date_range": None,
                    "case_number": case_number,
                    "page": 0,
                },
                deduplication_key=f"mt-search-{category}-num-{case_number}",
            )

    # =========================================================================
    # Step 1: parse search results + paginate
    # =========================================================================

    @step(json_model="api_models.SearchResponse")
    def parse_search_results(
        self,
        json_content: dict,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[MtDocket], None, None]:
        """Dispatch a detail fetch for each hit and page through results."""
        content = json_content.get("content") or []
        category = accumulated_data["category"]

        for hit in content:
            case_id = hit.get("caseId")
            docket_number = hit.get("caseNumber") or ""
            if not docket_number:
                continue

            if case_id is not None:
                detail_url = f"{CASE_INFO_URL}?caseId={case_id}"
                dedup_key = f"mt-case-id-{case_id}"
            else:
                detail_url = f"{CASE_INFO_PRE_2006_URL}?caseNumber={quote(docket_number)}"
                dedup_key = f"mt-case-num-{docket_number}"

            yield Request(
                request=HTTPRequestParams(
                    method=HttpMethod.GET, url=detail_url
                ),
                continuation=self.parse_case_detail,
                accumulated_data={
                    "category": category,
                    "case_id": case_id,
                    "docket_number": docket_number,
                    "preview_title": hit.get("caseTitle"),
                },
                deduplication_key=dedup_key,
            )

        page_info = json_content.get("page") or {}
        current_page = int(page_info.get("number", 0))
        total_pages = int(page_info.get("totalPages", 0))
        if current_page + 1 < total_pages:
            next_page = current_page + 1
            date_range = self._date_range_from_accumulated(accumulated_data)
            yield Request(
                request=HTTPRequestParams(
                    method=HttpMethod.POST,
                    url=SEARCH_URL,
                    headers={"Content-Type": "application/json"},
                    data=_encode_json_body(
                        self._build_search_body(
                            category=category,
                            date_range=date_range,
                            case_number=accumulated_data.get("case_number"),
                            page=next_page,
                        )
                    ),
                ),
                continuation=self.parse_search_results,
                accumulated_data={
                    **accumulated_data,
                    "page": next_page,
                },
                deduplication_key=SkipDeduplicationCheck(),
            )

    # =========================================================================
    # Step 2: parse case detail
    # =========================================================================

    @step(json_model="api_models.CaseInfoResponse")
    def parse_case_detail(
        self,
        json_content: dict,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[
        ScraperYield[MtDocket | MtDocument | MtSealedDocument], None, None
    ]:
        """Build an MtDocket and schedule document downloads."""
        category = accumulated_data["category"]
        # The search hit's caseId / docket_number are authoritative when the
        # detail payload omits them (pre-2006 records have caseId=null).
        case_id = json_content.get("caseId") or accumulated_data.get("case_id")
        docket_number = (
            json_content.get("caseNumber") or accumulated_data["docket_number"]
        )

        parties = self._parse_parties(json_content)
        entries, docs_to_archive, sealed_docs = self._parse_dockets(
            json_content, case_id=case_id, docket_number=docket_number
        )

        extra = json_content.get("extraCaseInfo") or {}

        docket = MtDocket(
            docket_number=docket_number,
            court_id="mont",
            case_id=case_id,
            date_filed=_parse_iso_date(json_content.get("caseFilingDate")),
            case_name=(
                json_content.get("shortTitle")
                or accumulated_data.get("preview_title")
                or docket_number
            ),
            case_type=json_content.get("caseType"),
            case_status=json_content.get("caseStatus"),
            full_caption=json_content.get("fullTitle"),
            summary=json_content.get("summary"),
            citation=json_content.get("citation"),
            original_court=json_content.get("originalCourt"),
            original_case_number=json_content.get("originalCaseNumber"),
            trial_court_judge=extra.get("trialCourtJudge"),
            category=category,
            parties=parties,
            entries=entries,
            source_url=response.url,
        )
        yield ParsedData(data=docket)

        for sealed in sealed_docs:
            yield ParsedData(data=sealed)

        yield from docs_to_archive

    # =========================================================================
    # Step 3: document download completion
    # =========================================================================

    @step()
    def download_document(
        self,
        local_filepath: str | None,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[MtDocument], None, None]:
        """Emit an MtDocument record for an archived file."""
        date_raw = accumulated_data.get("date_filed")
        case_id = accumulated_data.get("case_id")
        yield ParsedData(
            data=MtDocument(
                docket_number=accumulated_data["docket_number"],
                case_id=int(case_id) if case_id is not None else None,
                document_id=accumulated_data["document_id"],
                document_location=accumulated_data["document_location"],
                download_url=response.url,
                date_filed=date.fromisoformat(date_raw) if date_raw else None,
                description=accumulated_data.get("description"),
                local_path=local_filepath,
            )
        )

    # =========================================================================
    # Helpers
    # =========================================================================

    def _build_search_request(
        self,
        category: str,
        date_range: DateRange | None,
        *,
        page: int,
        case_number: str | None = None,
    ) -> Request:
        return Request(
            request=HTTPRequestParams(
                method=HttpMethod.POST,
                url=SEARCH_URL,
                headers={"Content-Type": "application/json"},
                data=_encode_json_body(
                    self._build_search_body(
                        category=category,
                        date_range=date_range,
                        case_number=case_number,
                        page=page,
                    )
                ),
            ),
            continuation=self.parse_search_results,
            accumulated_data={
                "category": category,
                "date_range": (
                    {
                        "start": date_range.start.isoformat(),
                        "end": date_range.end.isoformat(),
                    }
                    if date_range
                    else None
                ),
                "case_number": case_number,
                "page": page,
            },
            deduplication_key=SkipDeduplicationCheck(),
        )

    @staticmethod
    def _build_search_body(
        *,
        category: str,
        date_range: DateRange | None,
        case_number: str | None,
        page: int,
    ) -> dict[str, Any]:
        date_from = None
        date_to = None
        if date_range is not None:
            date_from = f"{date_range.start.isoformat()}T00:00:00.000Z"
            date_to = f"{date_range.end.isoformat()}T23:59:59.999Z"
        return {
            "caseStatus": CATEGORY_STATUS[category],
            "caseNumber": case_number,
            "partyName": None,
            "attorneyName": None,
            "dateFrom": date_from,
            "dateTo": date_to,
            "page": page,
            "pageSize": DEFAULT_PAGE_SIZE,
            "sortDirection": "asc",
            "sortColumn": "caseNumber",
        }

    @staticmethod
    def _date_range_from_accumulated(
        accumulated_data: dict,
    ) -> DateRange | None:
        raw = accumulated_data.get("date_range")
        if not raw:
            return None
        return DateRange(
            start=date.fromisoformat(raw["start"]),
            end=date.fromisoformat(raw["end"]),
        )

    @staticmethod
    def _parse_parties(payload: dict) -> list[MtParty]:
        """Parse the ``parties`` list from a modern or pre-2006 payload.

        Modern payload: ``parties`` is a list of objects with appellateRole,
        partyName, comment, attorney (comma-joined string).

        Pre-2006 payload: ``parties`` is null. Split
        ``extraCaseInfo.partysList`` into one MtParty per name with no role
        or attorneys. (Attorney names live in ``extraCaseInfo.attorneysList``
        without party mapping and are discarded here; consumers that need
        them can re-fetch the case-info endpoint directly.)
        """
        parties_raw = payload.get("parties")
        if parties_raw:
            result: list[MtParty] = []
            for p in parties_raw:
                name = (p.get("partyName") or "").strip()
                if not name:
                    continue
                attorneys = [
                    MtAttorney(name=a.strip())
                    for a in (p.get("attorney") or "").split(",")
                    if a.strip() and a.strip().lower() != "pro se"
                ]
                result.append(
                    MtParty(
                        name=name,
                        role=p.get("appellateRole") or None,
                        comment=p.get("comment") or None,
                        attorneys=attorneys,
                    )
                )
            return result

        extra = payload.get("extraCaseInfo") or {}
        partys_list = extra.get("partysList") or ""
        return [
            MtParty(name=n.strip())
            for n in partys_list.split(",")
            if n.strip()
        ]

    def _parse_dockets(
        self,
        payload: dict,
        *,
        case_id: int | None,
        docket_number: str,
    ) -> tuple[list[MtDocketEntry], list[Request], list[MtSealedDocument]]:
        """Walk the ``dockets`` list, emitting entries + archive requests.

        For each referenced document:
        - If it's a sealed placeholder, a ``MtSealedDocument`` is added.
        - Otherwise, an archive Request is produced for
          ``download_document`` to finalize as an ``MtDocument``.
        """
        entries: list[MtDocketEntry] = []
        archive_reqs: list[Request] = []
        sealed: list[MtSealedDocument] = []

        for dkt in payload.get("dockets") or []:
            description = dkt.get("documentDescription") or ""
            entry_date = _parse_api_date(dkt.get("filingDate"))
            doc_numbers: list[str] = []
            has_sealed = False

            for index, doc in enumerate(dkt.get("documents") or []):
                doc_id = str(doc.get("documentId") or "").strip()
                filenet_id = str(doc.get("filenetObjectId") or "").strip()
                location = (doc.get("documentLocation") or "").strip()

                is_sealed = location == SEALED_DOCUMENT_LOCATION or (
                    doc_id == SEALED_DOCUMENT_ID
                    and filenet_id == SEALED_FILENET_ID
                )
                if is_sealed:
                    has_sealed = True
                    sealed.append(
                        MtSealedDocument(
                            docket_number=docket_number,
                            case_id=case_id,
                            document_index=index,
                            date_filed=entry_date,
                            description=description or None,
                        )
                    )
                    continue

                # Pick the preferred identifier + download URL.
                if doc_id and doc_id != SEALED_DOCUMENT_ID:
                    identifier = doc_id
                    download_url = (
                        f"{DOC_MODERN_URL}?ctrackId={quote(doc_id)}"
                        f"&filename={quote(location or 'document.pdf')}"
                    )
                elif filenet_id and filenet_id != SEALED_FILENET_ID:
                    identifier = filenet_id
                    download_url = (
                        f"{DOC_ARCHIVE_URL}?objectId={quote(filenet_id)}"
                        f"&filename={quote(location or 'document.pdf')}"
                    )
                else:
                    # Neither usable id — treat as sealed defensively.
                    has_sealed = True
                    sealed.append(
                        MtSealedDocument(
                            docket_number=docket_number,
                            case_id=case_id,
                            document_index=index,
                            date_filed=entry_date,
                            description=description or None,
                        )
                    )
                    continue

                doc_numbers.append(identifier)
                archive_reqs.append(
                    Request(
                        archive=True,
                        request=HTTPRequestParams(
                            method=HttpMethod.GET, url=download_url
                        ),
                        continuation=self.download_document,
                        expected_type="pdf",
                        accumulated_data={
                            "docket_number": docket_number,
                            "case_id": case_id,
                            "document_id": identifier,
                            "document_location": location,
                            "date_filed": (
                                entry_date.isoformat() if entry_date else None
                            ),
                            "description": description or None,
                        },
                        deduplication_key=f"mt-doc-{identifier}",
                    )
                )

            entries.append(
                MtDocketEntry(
                    date_filed=entry_date,
                    description=description,
                    document_numbers=doc_numbers,
                    has_sealed_documents=has_sealed,
                )
            )
        return entries, archive_reqs, sealed


def _encode_json_body(payload: dict[str, Any]) -> bytes:
    """Encode a JSON request body for kent's persistent driver.

    Workaround: kent's persistent driver does not propagate
    ``HTTPRequestParams.json`` through serialize → DB → dispatch (only
    ``data`` is forwarded to httpx). Encode the body ourselves and pass it
    via ``data=`` as bytes. The leading UTF-8 BOM forces kent's rebuild
    path to keep the body as bytes — without it,
    ``json.loads(body.decode("utf-8"))`` would round-trip back to a dict
    and httpx's ``data=dict`` would form-encode it. The Montana API
    ignores the BOM.
    """
    return b"\xef\xbb\xbf" + json.dumps(payload).encode("utf-8")


def _parse_iso_date(value: str | None) -> date | None:
    """Parse a ``YYYY-MM-DD`` string from a case-info payload."""
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _parse_api_date(value: str | None) -> date | None:
    """Parse a timestamped ISO date like ``2004-05-18T22:39:16.000+00:00``."""
    if not value:
        return None
    try:
        # Normalize Z to +00:00 for datetime.fromisoformat in older Pythons.
        cleaned = value.replace("Z", "+00:00")
        return datetime.fromisoformat(cleaned).date()
    except ValueError:
        return None
