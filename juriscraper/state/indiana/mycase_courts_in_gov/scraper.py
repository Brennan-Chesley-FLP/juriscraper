"""Indiana MyCase appellate-court scraper.

Scrapes the Indiana Supreme Court, Court of Appeals, and Tax Court via
the public MyCase JSON API at ``public.courts.in.gov/mycase``. The
public site is an Angular SPA backed by a plain ASP.NET MVC REST
endpoint; no Playwright is required.

Entry points (§4):

- ``dockets_by_filing_date(court_ids, date_range)`` — fans out one
  date-range search per requested court (``ind`` → Supreme Court,
  ``indctapp`` → Court of Appeals, ``indtc`` → Tax Court).
- ``docket_by_number(court_id, docket_number)``    — single-case lookup
  by exact docket number.

For each case hit the scraper fetches CaseSummary, yields an ``InDocket``,
then schedules an archive download for every PDF reference. Each
downloaded PDF is emitted as a separate ``InDocument``.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING, Any, ClassVar
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

from juriscraper.state.common.params import InferrableDateRange

from .models import (
    COURT_CODE_TO_COURT_ID,
    COURT_ID_TO_COURT_ITEM_ID,
    COURT_ITEM_ID_ALL_ODYSSEY,
    InAddress,
    InAttorney,
    InCrossReference,
    InDocket,
    InDocketEntry,
    InDocument,
    InEventDocument,
    InParty,
    InRelatedCase,
)

if TYPE_CHECKING:
    from collections.abc import Generator

    from jkent.data_types import ScraperYield


BASE_URL = "https://public.courts.in.gov"
SEARCH_URL = f"{BASE_URL}/mycase/Search/SearchCases"
CASE_SUMMARY_URL = f"{BASE_URL}/mycase/Case/CaseSummary"

# All four standard category keys must be sent — empty list returns nothing.
DEFAULT_CATEGORIES: list[str] = ["CR", "CV", "FAM", "PR"]

# Server caps TotalResults at 1001; the SPA renders a "too many matches"
# warning at >1000. When we hit the cap we bisect the date range.
SEARCH_RESULT_CAP = 1000

# The API accepts up to 100/page in practice; default UI page size is 20.
DEFAULT_PAGE_SIZE = 100


class IndianaAppellateScraper(BaseScraper[InDocket | InDocument]):
    """Indiana Supreme Court, Court of Appeals, and Tax Court.

    Speaks the MyCase JSON API directly. Emits two top-level record types:

    - ``InDocket`` — one per case, with nested parties and docket entries.
    - ``InDocument`` — one per archived PDF (Briefs, Opinions, Orders, …).
    """

    court_ids: ClassVar[set[str]] = {"ind", "indctapp", "indtc"}
    court_url: ClassVar[str] = BASE_URL
    data_types: ClassVar[set[str]] = {"dockets"}
    status: ClassVar[ScraperStatus] = ScraperStatus.IN_DEVELOPMENT
    version: ClassVar[str] = "2026-06-27"
    last_verified: ClassVar[str] = "2026-05-03"
    requires_auth: ClassVar[bool] = False
    # Plain JSON REST API: reachable directly with httpx — no Cloudflare, no
    # JS challenge, no required cookies. Runs under plain HTTP.
    driver_requirements: ClassVar[list[DriverRequirement]] = []
    rate_limits: ClassVar[list[Rate] | None] = [Rate(2, Duration.SECOND)]

    # =========================================================================
    # Entry points (§4)
    # =========================================================================

    @entry(InDocket)
    def dockets_by_filing_date(
        self, court_ids: set[str], date_range: DateRange
    ) -> Generator[Request, None, None]:
        """Date-based search; fans out one search per requested court.

        ``court_ids`` is a set of CourtListener court ids (``ind``,
        ``indctapp``, ``indtc``); each is dispatched to its per-court
        ``CourtItemID``. Unknown ids are rejected so a typo fails loudly
        rather than silently scraping nothing.

        The Court of Appeals (``indctapp``) is high-volume (~286
        cases/month): date ranges over ~3 months will hit the 1000-result
        cap and trigger automatic bisection. Supreme Court (~35/month) and
        Tax Court (~2-3/month) are safe over multi-month/year ranges.
        """
        unknown = sorted(
            cid for cid in court_ids if cid not in COURT_ID_TO_COURT_ITEM_ID
        )
        if unknown:
            raise ValueError(
                f"Unknown Indiana court id(s): {unknown}. "
                f"Supported: {sorted(COURT_ID_TO_COURT_ITEM_ID)}."
            )
        for court_id in sorted(court_ids):
            yield self._build_search_request(
                court_item_id=COURT_ID_TO_COURT_ITEM_ID[court_id],
                date_range=date_range,
                skip=0,
            )

    @entry(InDocket)
    def docket_by_number(
        self, court_id: str, docket_number: str
    ) -> Generator[Request, None, None]:
        """Look up one case by its exact docket number.

        Accepts any of the three appellate formats:
            ``YYS-XX-NNNNN``  Supreme Court (e.g. ``26S-DI-00136``)
            ``YYA-XX-NNNNN``  Court of Appeals (e.g. ``26A-CR-00794``)
            ``YYT-TA-NNNNN``  Tax Court (e.g. ``26T-TA-00009``)

        Uses CourtItemID 92 (All Odyssey Courts) so the caller need not
        know which appellate court issued the number; trial-court hits
        are filtered out at parse time. ``court_id`` is carried through so
        the resulting docket is attributed even if the response omits a
        recognizable CourtCode.
        """
        body = self._search_body(
            mode="ByCase",
            court_item_id=COURT_ITEM_ID_ALL_ODYSSEY,
            case_number=docket_number,
            date_range=None,
            skip=0,
            advanced=False,
        )
        yield Request(
            request=HTTPRequestParams(
                method=HttpMethod.POST,
                url=SEARCH_URL,
                headers=_search_headers(),
                data=_encode_json_body(body),
            ),
            continuation=self.parse_search_results,
            accumulated_data={
                "mode": "ByCase",
                "case_number": docket_number,
                "court_item_id": COURT_ITEM_ID_ALL_ODYSSEY,
                "skip": 0,
                "date_range": None,
                "appellate_only": True,
                "court_id": court_id,
            },
            deduplication_key=f"docket_by_number:{docket_number}",
        )

    # =========================================================================
    # Step 1: parse search results, dispatch detail fetches, paginate / bisect
    # =========================================================================

    @step(priority=3)
    def parse_search_results(
        self,
        json_content: dict,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[InDocket], None, None]:
        """Dispatch a CaseSummary fetch for each hit; paginate or bisect."""
        total = int(json_content.get("TotalResults") or 0)
        results = json_content.get("Results") or []
        skip = int(accumulated_data.get("skip") or 0)

        # Bisect when we hit the server cap. The cap is 1000 visible rows
        # (TotalResults occasionally reports 1001 as the "too many" sentinel).
        if (
            skip == 0
            and total >= SEARCH_RESULT_CAP
            and accumulated_data.get("date_range")
        ):
            yield from self._bisect_date_range(accumulated_data)
            return

        appellate_only = bool(accumulated_data.get("appellate_only"))

        for hit in results:
            case_token = hit.get("CaseToken")
            case_number = hit.get("CaseNumber")
            court_code = (hit.get("CourtCode") or "").strip()
            if not case_token or not case_number:
                continue
            court_id = COURT_CODE_TO_COURT_ID.get(
                court_code
            ) or accumulated_data.get("court_id")
            if appellate_only and court_id is None:
                # Trial-court hit on the all-Odyssey lookup — skip.
                continue

            yield Request(
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url=CASE_SUMMARY_URL,
                    params={"SRCT": "", "CaseToken": case_token},
                    headers=_xhr_headers(),
                ),
                continuation=self.parse_case_detail,
                accumulated_data={
                    "case_number": case_number,
                    "court_id": court_id,
                    "court_code": court_code,
                    "case_id": hit.get("CaseID"),
                    "preview_style": hit.get("Style"),
                    "preview_file_date": hit.get("FileDate"),
                },
                deduplication_key=f"case_detail:{case_number}",
            )

        # Paginate if there are more hits in this search.
        next_skip = skip + DEFAULT_PAGE_SIZE
        if (
            results
            and next_skip < min(total, SEARCH_RESULT_CAP)
            and accumulated_data.get("mode") != "ByCase"
        ):
            next_body = self._search_body(
                mode=accumulated_data.get("mode") or "ByParty",
                court_item_id=int(accumulated_data["court_item_id"]),
                case_number=accumulated_data.get("case_number"),
                date_range=_date_range_from_accumulated(accumulated_data),
                skip=next_skip,
                advanced=True,
            )
            yield Request(
                request=HTTPRequestParams(
                    method=HttpMethod.POST,
                    url=SEARCH_URL,
                    headers=_search_headers(),
                    data=_encode_json_body(next_body),
                ),
                continuation=self.parse_search_results,
                accumulated_data={**accumulated_data, "skip": next_skip},
                deduplication_key=SkipDeduplicationCheck(),
            )

    # =========================================================================
    # Step 2: parse case detail
    # =========================================================================

    @step(priority=2)
    def parse_case_detail(
        self,
        json_content: dict,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[InDocket | InDocument], None, None]:
        """Build an InDocket and schedule document downloads."""
        # Token expired or restricted — surface as a soft skip.
        if (
            json_content.get("InvalidToken")
            or json_content.get("CaseNotFound")
            or json_content.get("AccessDenied")
        ):
            return

        court_code = (json_content.get("CourtCode") or "").strip() or (
            accumulated_data.get("court_code") or ""
        )
        court_id = COURT_CODE_TO_COURT_ID.get(
            court_code
        ) or accumulated_data.get("court_id")
        if not court_id:
            # Not an appellate court — silently drop.
            return

        case_key = str(json_content.get("CaseKey") or "")
        docket_number = (
            json_content.get("CaseNumber") or accumulated_data["case_number"]
        )

        parties = _parse_parties(json_content.get("Parties") or [])
        entries, doc_requests = self._parse_events(
            json_content.get("Events") or [],
            response_url=response.url,
            docket_number=docket_number,
            court=court_id,
            case_key=case_key,
        )
        cross_refs = _parse_cross_refs(json_content.get("CrossRefs") or [])
        related = _parse_related(json_content.get("Related") or [])
        trial_case_number, trial_case_key = _pick_trial_court(related)

        is_active = json_content.get("IsActive")
        if isinstance(is_active, str):
            is_active = is_active.lower() == "active"

        docket = InDocket.raw(
            docket_number=docket_number,
            court=court_id,
            case_key=case_key,
            date_filed=_parse_us_date(json_content.get("FileDate")),
            case_name=(
                json_content.get("Style")
                or accumulated_data.get("preview_style")
                or docket_number
            ),
            case_type=json_content.get("CaseType"),
            case_type_code=json_content.get("CaseTypeCode"),
            case_sub_type=json_content.get("CaseSubType"),
            case_category=json_content.get("CaseCategoryGroup"),
            case_category_code=json_content.get("CaseCategoryKey"),
            case_status=json_content.get("CaseStatus"),
            case_status_date=_parse_us_date(
                json_content.get("CaseStatusDate")
            ),
            is_active=is_active if isinstance(is_active, bool) else None,
            is_public=json_content.get("IsPublic"),
            trial_court_case_number=trial_case_number,
            trial_court_case_key=trial_case_key,
            cross_references=cross_refs,
            related_cases=related,
            parties=parties,
            entries=entries,
            source_url=response.url,
        )
        yield ParsedData(data=docket)

        yield from doc_requests

    # =========================================================================
    # Step 3: document download completion
    # =========================================================================

    @step()
    def download_document(
        self,
        local_filepath: str | None,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[InDocument], None, None]:
        """Emit an InDocument record for an archived file.

        Priority is left at the ``archive=True`` default (1); the download
        Request that lands here was scheduled with ``archive=True``.
        """
        date_raw = accumulated_data.get("date_filed")
        yield ParsedData(
            data=InDocument.raw(
                docket_number=accumulated_data["docket_number"],
                court=accumulated_data["court"],
                case_key=accumulated_data["case_key"],
                document_id=int(accumulated_data["document_id"]),
                event_key=accumulated_data["event_key"],
                name=accumulated_data.get("name") or "",
                download_url=response.url,
                date_filed=(
                    date.fromisoformat(date_raw) if date_raw else None
                ),
                page_count=accumulated_data.get("page_count"),
                filename=accumulated_data.get("filename"),
                local_path=local_filepath,
            )
        )

    # =========================================================================
    # Helpers
    # =========================================================================

    def _build_search_request(
        self,
        *,
        court_item_id: int,
        date_range: InferrableDateRange,
        skip: int,
    ) -> Request:
        body = self._search_body(
            mode="ByParty",
            court_item_id=court_item_id,
            case_number=None,
            date_range=date_range,
            skip=skip,
            advanced=True,
        )
        return Request(
            request=HTTPRequestParams(
                method=HttpMethod.POST,
                url=SEARCH_URL,
                headers=_search_headers(),
                data=_encode_json_body(body),
            ),
            continuation=self.parse_search_results,
            accumulated_data={
                "mode": "ByParty",
                "court_item_id": court_item_id,
                "case_number": None,
                "skip": skip,
                "date_range": {
                    "start": date_range.start.isoformat(),
                    "end": date_range.end.isoformat(),
                },
            },
            deduplication_key=SkipDeduplicationCheck(),
        )

    @staticmethod
    def _search_body(
        *,
        mode: str,
        court_item_id: int,
        case_number: str | None,
        date_range: DateRange | None,
        skip: int,
        advanced: bool,
    ) -> dict[str, Any]:
        file_start = (
            date_range.start.strftime("%m/%d/%Y") if date_range else None
        )
        file_end = date_range.end.strftime("%m/%d/%Y") if date_range else None
        return {
            "Mode": mode,
            "CaseNum": case_number,
            "CiteNum": None,
            "CrossRefNum": None,
            "First": None,
            "Middle": None,
            "Last": None,
            "Business": None,
            "DoBStart": None,
            "DoBEnd": None,
            "OANum": None,
            "BarNum": None,
            "SoundEx": False,
            "CourtItemID": court_item_id,
            "Categories": list(DEFAULT_CATEGORIES),
            "Limits": None,
            "Advanced": advanced,
            "ActiveFlag": "All",
            "FileStart": file_start,
            "FileEnd": file_end,
            "CountyCode": None,
            "NewSearch": True,
            "CaptchaAnswer": None,
            "Skip": skip,
            "Take": DEFAULT_PAGE_SIZE,
            "Sort": "FileDate DESC",
        }

    def _bisect_date_range(
        self, accumulated_data: dict
    ) -> Generator[Request, None, None]:
        """Split a capped date range in half and re-issue both halves."""
        date_range = _date_range_from_accumulated(accumulated_data)
        if not date_range or date_range.start >= date_range.end:
            return
        midpoint = date_range.start + (date_range.end - date_range.start) // 2
        first = DateRange(start=date_range.start, end=midpoint)
        second = DateRange(
            start=midpoint + timedelta(days=1), end=date_range.end
        )
        court_item_id = int(accumulated_data["court_item_id"])
        yield self._build_search_request(
            court_item_id=court_item_id, date_range=first, skip=0
        )
        yield self._build_search_request(
            court_item_id=court_item_id, date_range=second, skip=0
        )

    def _parse_events(
        self,
        events: list[dict],
        *,
        response_url: str,
        docket_number: str,
        court: str,
        case_key: str,
    ) -> tuple[list[InDocketEntry], list[Request]]:
        entries: list[InDocketEntry] = []
        archive_reqs: list[Request] = []

        for ev in events:
            case_event = ev.get("CaseEvent") or {}
            event_documents: list[InEventDocument] = []
            event_key = str(ev.get("EventKey") or "")
            entry_date = _parse_us_date(ev.get("EventDate"))
            related_parties = [
                (p.get("Name") or "").strip()
                for p in (case_event.get("Parties") or [])
                if (p.get("Name") or "").strip()
            ]

            for doc in ev.get("EventDocuments") or []:
                document_id = doc.get("DocumentID")
                if document_id is None:
                    continue
                effective = _parse_iso_date(doc.get("EffectiveDate"))
                doc_url = doc.get("DownUrl")
                full_url = urljoin(BASE_URL, doc_url) if doc_url else None
                event_documents.append(
                    InEventDocument(
                        document_id=int(document_id),
                        name=doc.get("Name") or "",
                        description=doc.get("Desc"),
                        date_filed=effective,
                        page_count=doc.get("PageCount"),
                        filename=doc.get("Filename"),
                        extension=doc.get("Ext"),
                        download_url=full_url,
                    )
                )
                if full_url:
                    archive_reqs.append(
                        Request(
                            archive=True,
                            request=HTTPRequestParams(
                                method=HttpMethod.GET, url=full_url
                            ),
                            continuation=self.download_document,
                            expected_type="pdf",
                            accumulated_data={
                                "docket_number": docket_number,
                                "court": court,
                                "case_key": case_key,
                                "document_id": int(document_id),
                                "event_key": event_key,
                                "name": doc.get("Name") or "",
                                "filename": doc.get("Filename"),
                                "page_count": doc.get("PageCount"),
                                "date_filed": (
                                    effective.isoformat()
                                    if effective
                                    else None
                                ),
                            },
                            # File-download keys are used in filenames, so
                            # avoid colons (§6).
                            deduplication_key=(
                                f"{docket_number}-{document_id}-"
                                f"{doc.get('Filename') or 'document'}"
                            ),
                        )
                    )

            entries.append(
                InDocketEntry(
                    event_key=event_key,
                    event_type=ev.get("EventType") or "",
                    base_event_type=ev.get("BaseEventTypeKey"),
                    date_filed=entry_date,
                    description=ev.get("Description") or "",
                    judge=ev.get("Judge"),
                    is_docketable=bool(ev.get("IsDocketable")),
                    comment=case_event.get("Comment"),
                    secondary_date=_parse_us_date(case_event.get("Date2")),
                    secondary_date_label=case_event.get("Date2Label"),
                    related_parties=related_parties,
                    documents=event_documents,
                )
            )

        return entries, archive_reqs


# =============================================================================
# Module-level parsing helpers
# =============================================================================


def _parse_parties(parties_raw: list[dict]) -> list[InParty]:
    parsed: list[InParty] = []
    for p in parties_raw:
        name = (p.get("Name") or "").strip()
        if not name:
            continue
        attorneys = [
            _attorney_from_payload(a) for a in (p.get("Attorneys") or [])
        ]
        parsed.append(
            InParty(
                name=name,
                name_formatted=p.get("NameFMLS"),
                role=p.get("ExtConnCodeDesc"),
                role_code=p.get("ExtConnCode"),
                base_role=p.get("BaseConnKey"),
                address=_address_from_payload(p.get("Address")),
                attorneys=attorneys,
            )
        )
    return parsed


def _attorney_from_payload(a: dict) -> InAttorney:
    name = (a.get("Name") or "").strip()
    is_pro_se = name.lower() == "pro se"
    return InAttorney(
        name=name,
        bar_number=a.get("BarNumber"),
        lead=bool(a.get("Lead")),
        label=a.get("Label"),
        work_phone=a.get("WorkPhone"),
        address=_address_from_payload(a.get("Address")),
        is_pro_se=is_pro_se,
    )


def _address_from_payload(addr: dict | None) -> InAddress | None:
    if not addr:
        return None
    line_1 = addr.get("Line1") or None
    line_2 = addr.get("Line2") or None
    line_3 = addr.get("Line3") or None
    line_4 = addr.get("Line4") or None
    city = addr.get("City") or None
    state = addr.get("State") or None
    zip_code = addr.get("Zip") or None
    zip_4 = addr.get("Zip4") or None
    if not any([line_1, line_2, line_3, line_4, city, state, zip_code, zip_4]):
        return None
    return InAddress(
        line_1=line_1,
        line_2=line_2,
        line_3=line_3,
        line_4=line_4,
        city=city,
        state=state,
        zip_code=zip_code,
        zip_4=zip_4,
        masked=bool(addr.get("Masked")),
    )


def _parse_cross_refs(payload: list[dict]) -> list[InCrossReference]:
    refs: list[InCrossReference] = []
    for group in payload:
        type_label = group.get("Type") or ""
        for item in group.get("Items") or []:
            value = item.get("Value")
            if not value:
                continue
            refs.append(
                InCrossReference(
                    type=type_label,
                    key=item.get("Key"),
                    value=value,
                )
            )
    return refs


def _parse_related(payload: list[dict]) -> list[InRelatedCase]:
    related: list[InRelatedCase] = []
    for r in payload:
        rel_key = str(r.get("RelCaseKey") or "")
        rel_num = r.get("RelNumber") or ""
        if not rel_key or not rel_num:
            continue
        related.append(
            InRelatedCase(
                related_case_key=rel_key,
                related_case_number=rel_num,
                description=r.get("RelDesc"),
            )
        )
    return related


def _pick_trial_court(
    related: list[InRelatedCase],
) -> tuple[str | None, str | None]:
    """Find the lower-trial-court entry from the Related list, if any."""
    for r in related:
        if r.description and "trial court" in r.description.lower():
            return r.related_case_number, r.related_case_key
    return None, None


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


def _parse_us_date(value: str | None) -> date | None:
    """Parse ``MM/DD/YYYY`` (the format used everywhere by MyCase)."""
    if not value:
        return None
    try:
        return datetime.strptime(value.strip(), "%m/%d/%Y").date()
    except ValueError:
        return None


def _parse_iso_date(value: str | None) -> date | None:
    """Parse ``YYYY-MM-DDT…`` (used on EventDocument.EffectiveDate)."""
    if not value:
        return None
    try:
        cleaned = value.replace("Z", "+00:00")
        return datetime.fromisoformat(cleaned).date()
    except ValueError:
        return None


def _encode_json_body(payload: dict[str, Any]) -> bytes:
    """Encode a JSON request body for kent's persistent driver.

    kent's persistent driver does not propagate ``HTTPRequestParams.json``
    through serialize → DB → dispatch (only ``data`` is forwarded to
    httpx). Encode the body ourselves and pass it via ``data=`` as bytes.
    The leading UTF-8 BOM forces kent's rebuild path to keep the body as
    bytes — without it, ``json.loads(body.decode("utf-8"))`` would
    round-trip back to a dict and httpx's ``data=dict`` would form-encode
    it. The MyCase API ignores the BOM.
    """
    return b"\xef\xbb\xbf" + json.dumps(payload).encode("utf-8")


def _search_headers() -> dict[str, str]:
    return {
        "Content-Type": "application/json",
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "X-Requested-With": "XMLHttpRequest",
    }


def _xhr_headers() -> dict[str, str]:
    return {
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "X-Requested-With": "XMLHttpRequest",
    }
