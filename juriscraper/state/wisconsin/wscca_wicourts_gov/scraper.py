"""Wisconsin Supreme Court & Court of Appeals docket scraper (WSCCA).

Scrapes dockets from https://wscca.wicourts.gov/case-search.

The site is a PureScript SPA backed by a JSON API. The case-search
endpoints are gated by an invisible hCaptcha that intermittently
escalates to an image challenge — so date-driven bulk searches are
not the v1 strategy. Instead the scraper relies on two endpoints
that work cleanly inside a Playwright browser context without
captcha:

- ``GET /api/case/{caseNo}``  — full case JSON (404 for unknown ids)
- ``GET /api/case/{caseNo}/document/{docId}``  — document PDF

This is a **JSON-only** scraper (no HTML parsing): the steps decode the
JSON body directly, so there is no ``parsers/`` package (per
SCRAPER_STANDARDS §3.5 / the arkansas & nevada JSON scrapers).

Wisconsin appellate case numbers share a single sequence per year per
type prefix. ``YYYYAP000NNN`` (Appeal) is the dominant prefix and
covers both Court of Appeals and Supreme Court cases (the case stays
under the same number when the SC accepts review; the API's
``courtType`` field reflects the current owner). The scraper uses a
:class:`YearlySpeculativeRange` entry to enumerate AP cases by
``(year, sequence)``; per-case ``courtType`` then routes the
:class:`WiDocket` to ``wis`` or ``wisctapp``.

Other Wisconsin appellate type prefixes (``XX``, ``BC``, ``AD``,
``AM``, ``OK``, etc.) are far rarer and can be added as additional
entries once usage demands.

Entry points (§4):
    - dockets_by_number(docket_number)   — speculative enumeration over
      the ``YYYYAP######`` numbering. Multi-court speculative: the court
      is decided per-response by ``courtType``, so the entry takes ONLY
      its speculative param (SCRAPER_STANDARDS §4).
    - docket_by_number(court_id, docket_number) — direct fetch of one
      known canonical case number.

Flow per case::

    docket_by_number / dockets_by_number
      -> parse_case_detail   # GET /api/case/{caseNo} (JSON in body)
                             # builds WiDocket, yields ParsedData,
                             # enqueues archive Request per document
      -> handle_document     # yields WiDownloadedDocument
"""

from __future__ import annotations

import json
from datetime import date
from typing import TYPE_CHECKING, Any, ClassVar

from jkent.common.decorators import entry, step
from jkent.data_types import (
    BaseScraper,
    DriverRequirement,
    HttpMethod,
    HTTPRequestParams,
    ParsedData,
    Request,
    ScraperStatus,
)
from pyrate_limiter import Duration, Rate

from juriscraper.state.common.params import YearlySpeculativeRange

from .models import (
    COURT_IDS,
    SITE_COURT_TYPE_TO_CL_ID,
    WiAttorney,
    WiCircuitCourtCase,
    WiCitation,
    WiDocket,
    WiDocketEntry,
    WiDocument,
    WiDownloadedDocument,
    WiParty,
)

if TYPE_CHECKING:
    from collections.abc import Generator

    from jkent.data_types import ScraperYield

BASE_URL = "https://wscca.wicourts.gov"
CASE_API_TEMPLATE = f"{BASE_URL}/api/case/{{docket_number}}"
DOCUMENT_API_TEMPLATE = (
    f"{BASE_URL}/api/case/{{docket_number}}/document/{{doc_id}}"
)
SOURCE_URL_TEMPLATE = f"{BASE_URL}/case/{{docket_number}}"
RSS_URL_TEMPLATE = f"{BASE_URL}/rss/case/{{docket_number}}"

_Yield = WiDocket | WiDownloadedDocument


class WisconsinWsccaScraper(BaseScraper[_Yield]):
    """Scraper for the Wisconsin Supreme Court and Court of Appeals.

    Both courts share a single case-number space; the API's
    ``courtType`` (``"SC"`` / ``"CA"``) routes each docket to its
    CourtListener court id. The scraper relies on the JSON case-detail
    endpoint (no captcha) and treats the SPA's case-search front door
    as out of scope for v1 because of its invisible-hCaptcha gate.
    """

    # === Metadata (§3) ===
    court_ids: ClassVar[set[str]] = set(
        COURT_IDS.keys()
    )  # {"wis", "wisctapp"}
    court_url: ClassVar[str] = f"{BASE_URL}/case-search"
    data_types: ClassVar[set[str]] = {"dockets"}
    status: ClassVar[ScraperStatus] = ScraperStatus.IN_DEVELOPMENT
    version: ClassVar[str] = "2026-05-05"
    last_verified: ClassVar[str] = "2026-05-05"
    requires_auth: ClassVar[bool] = False

    # The site appears tolerant of moderate request rates from a real
    # browser session; throttle conservatively until we observe rate
    # limiting in production.
    rate_limits: ClassVar[list[Rate] | None] = [Rate(2, Duration.SECOND)]

    # The /api/* endpoints 403 to plain HTTP clients (TLS-fingerprint /
    # sec-fetch-* checks) and only respond to a real browser context.
    # Whole scraper is Playwright; per-step driver_requirements are
    # not used.
    driver_requirements: ClassVar[list[DriverRequirement]] = [
        DriverRequirement.JS_EVAL,
        DriverRequirement.FF_ALIKE,
        DriverRequirement.HCAP_HANDLER,
    ]

    # =========================================================================
    # Entry points (§4)
    # =========================================================================

    @entry(WiDocket)
    def docket_by_number(
        self, court_id: str, docket_number: str
    ) -> Generator[Request, None, None]:
        """Fetch a single docket by canonical case number.

        Args:
            court_id: CourtListener id this lookup is scoped to (``wis``
                or ``wisctapp``). Used only as a fallback display hint —
                the docket's authoritative court is read from the API's
                ``courtType`` field.
            docket_number: 12-character canonical case number, e.g.
                ``"2022AP000001"``. The site itself accepts shorter
                forms (``22AP1``) and normalizes them; we require the
                canonical form here so the CourtListener id stays
                deterministic.
        """
        yield self._build_case_request(
            docket_number, entry_point="docket_by_number"
        )

    @entry(WiDocket)
    def dockets_by_number(
        self, docket_number: YearlySpeculativeRange
    ) -> Generator[Request, None, None]:
        """Speculative docket fetch over the ``YYYYAP######`` numbering
        for Wisconsin appellate cases.

        Wisconsin's appellate court system shares one case-number
        sequence per year per type prefix. The ``AP`` prefix is the
        common case (Notice of Appeal); other prefixes (``XX``,
        ``BC``, ``AD``, ``AM``, ``OK``, ...) are rare and are not
        enumerated here.

        This is a **multi-court** speculative entry: the same number
        space serves both ``wis`` and ``wisctapp``, and the owning court
        is decided per-response from ``courtType`` — never seeded. Per
        SCRAPER_STANDARDS §4 a speculative entry therefore takes ONLY
        its speculative param (no ``court_ids``).

        Seed shape::

            [{"dockets_by_number": {"docket_number": {"year": 2025,
                                                      "min": 1,
                                                      "soft_max": 4000,
                                                      "gap": 20}}}]
        """
        canonical = f"{docket_number.year}AP{docket_number.min:06d}"
        yield self._build_case_request(
            canonical, entry_point="dockets_by_number"
        )

    # =========================================================================
    # Request builder
    # =========================================================================

    def _build_case_request(
        self, docket_number: str, *, entry_point: str
    ) -> Request:
        """Build the ``GET /api/case/{caseNo}`` request.

        The Playwright driver navigates the page to the API URL; the
        response body is the raw JSON object, available as ``text`` in
        the continuation.
        """
        return Request(
            request=HTTPRequestParams(
                method=HttpMethod.GET,
                url=CASE_API_TEMPLATE.format(docket_number=docket_number),
                headers={"Accept": "application/json"},
            ),
            continuation=self.parse_case_detail,
            accumulated_data={
                "docket_number": docket_number,
                "source_entry_point": entry_point,
            },
            deduplication_key=f"docket_by_number:{docket_number}",
        )

    # =========================================================================
    # Case-detail JSON parser (§5)
    # =========================================================================

    @step(priority=2)
    def parse_case_detail(
        self,
        text: str,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[_Yield], None, None]:
        """Parse the ``/api/case/{caseNo}`` JSON body and emit a
        :class:`WiDocket` plus one archive Request per document.
        """
        docket_number: str = accumulated_data["docket_number"]

        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            # Soft-404s on this endpoint return real HTTP 404, which the
            # driver classifies as a speculation miss before we get
            # here. A JSON decode error therefore means an unexpected
            # body shape — bail without yielding.
            return

        result = (payload or {}).get("result")
        if not isinstance(result, dict):
            return

        case_data = result.get("caseData") or {}
        court_type_code = case_data.get("courtType") or ""
        court = SITE_COURT_TYPE_TO_CL_ID.get(court_type_code)
        if court is None:
            # Unknown courtType — skip rather than guess.
            return

        docket = WiDocket(
            docket_number=case_data.get("sccaCaseNo") or docket_number,
            court=court,
            court_type_code=court_type_code,
            case_name=case_data.get("shortCaption") or docket_number,
            case_name_full=_clean(case_data.get("longCaption")),
            date_filed=_parse_api_date(case_data.get("filingDate")),
            case_status_code=case_data.get("statusCode"),
            case_status_description=case_data.get("statusDescr"),
            class_code=case_data.get("wcisClsCode"),
            class_code_description=case_data.get("wcisClsCodeDescr"),
            filing_district=case_data.get("filingDistrictNo"),
            current_district=case_data.get("districtNo"),
            panel_str=_clean(case_data.get("casePanelSize")),
            county_name=case_data.get("countyName"),
            county_no=case_data.get("countyNo"),
            disposition_code=case_data.get("dispoCode"),
            disposition_description=case_data.get("dispoCodeDescr"),
            date_disposition=_parse_api_date(case_data.get("dispoDate")),
            is_confidential=bool(case_data.get("isConfidential")),
            case_suffix=_clean(case_data.get("caseSuffix")),
            parties=[_party(p) for p in (result.get("parties") or [])],
            entries=[
                _docket_entry(e, is_future=False)
                for e in (result.get("pastEvents") or [])
            ]
            + [
                _docket_entry(e, is_future=True)
                for e in (result.get("upcomingEvents") or [])
            ],
            documents=[
                _document(d, docket_number)
                for d in (result.get("documents") or [])
            ],
            citations=[_citation(c) for c in (result.get("citnData") or [])],
            circuit_court_cases=[
                _cc_case(c) for c in (result.get("ccCaseData") or [])
            ],
            rss_url=RSS_URL_TEMPLATE.format(docket_number=docket_number),
            source_url=SOURCE_URL_TEMPLATE.format(docket_number=docket_number),
            source_entry_point=accumulated_data.get("source_entry_point"),
        )
        yield ParsedData(data=docket)

        for d in docket.documents:
            yield Request(
                archive=True,
                expected_type="pdf",
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url=d.download_url,
                    headers={"Accept": "application/pdf, */*"},
                ),
                continuation=self.handle_document,
                accumulated_data={
                    "court": court,
                    "docket_number": docket.docket_number,
                    "doc_id": d.doc_id,
                    "download_url": d.download_url,
                },
                # File-download key: avoid colons (§6).
                deduplication_key=(
                    f"{docket.docket_number}-{d.doc_id}-{d.doc_name}"
                ),
            )

    # =========================================================================
    # Archive download handler
    # =========================================================================

    @step()
    def handle_document(
        self,
        local_filepath: str | None,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[_Yield], None, None]:
        """Emit a :class:`WiDownloadedDocument` after archiving completes."""
        yield ParsedData(
            data=WiDownloadedDocument(
                court=accumulated_data["court"],
                docket_number=accumulated_data["docket_number"],
                doc_id=accumulated_data["doc_id"],
                download_url=accumulated_data["download_url"],
                local_path=local_filepath,
            )
        )


# =============================================================================
# Helpers
# =============================================================================


def _clean(value: Any) -> str | None:
    """Trim whitespace; return None for empty / non-string values."""
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    return cleaned or None


def _parse_api_date(value: Any) -> date | None:
    """Parse the WSCCA API's ``{"m": int, "d": int, "y": int}`` shape."""
    if not isinstance(value, dict):
        return None
    try:
        m = int(value.get("m"))
        d = int(value.get("d"))
        y = int(value.get("y"))
        return date(y, m, d)
    except (TypeError, ValueError):
        return None


def _name_parts(name_obj: Any) -> dict[str, str | None]:
    """Unpack the API's ``{nameL, nameF, nameM, suffix}`` name shape."""
    if not isinstance(name_obj, dict):
        return {
            "name_last": None,
            "name_first": None,
            "name_middle": None,
            "name_suffix": None,
        }
    return {
        "name_last": _clean(name_obj.get("nameL")),
        "name_first": _clean(name_obj.get("nameF")),
        "name_middle": _clean(name_obj.get("nameM")),
        "name_suffix": _clean(name_obj.get("suffix")),
    }


def _attorney(raw: Any) -> WiAttorney:
    raw = raw if isinstance(raw, dict) else {}
    return WiAttorney(
        **_name_parts(raw.get("name")),
        entered_date=_parse_api_date(raw.get("enteredDate")),
        withdrew_date=_parse_api_date(raw.get("withdrewDate")),
        atty_seq_no=raw.get("attySeqNo"),
    )


def _party(raw: Any) -> WiParty:
    raw = raw if isinstance(raw, dict) else {}
    party_types_raw = raw.get("partyTypes") or []
    party_types = [t for t in party_types_raw if isinstance(t, str)]
    return WiParty(
        **_name_parts(raw.get("name")),
        party_types=party_types,
        party_seq_no=raw.get("partySeqNo"),
        attorneys=[_attorney(a) for a in (raw.get("attorneys") or [])],
    )


def _docket_entry(raw: Any, *, is_future: bool) -> WiDocketEntry:
    raw = raw if isinstance(raw, dict) else {}
    return WiDocketEntry(
        event_seq_no=int(raw.get("eventSeqNo") or 0),
        date_filed=_parse_api_date(raw.get("filingDate")),
        description=_clean(raw.get("descr")) or "",
        sub_event_text=_clean(raw.get("subEventText")),
        additional_text=_clean(raw.get("additionalText")),
        due_date=_parse_api_date(raw.get("dueDate")),
        event_status_code=_clean(raw.get("eventStatusCode")),
        court_type_code=_clean(raw.get("courtTypeCode")),
        is_future=is_future,
    )


def _document(raw: Any, docket_number: str) -> WiDocument:
    raw = raw if isinstance(raw, dict) else {}
    doc_id_raw = raw.get("docId")
    try:
        doc_id = int(doc_id_raw)
    except (TypeError, ValueError):
        doc_id = 0
    return WiDocument(
        doc_id=doc_id,
        doc_name=_clean(raw.get("docName")) or "",
        event_descr=_clean(raw.get("eventDescr")),
        event_code=_clean(raw.get("eventCode")),
        event_seq_no=raw.get("eventSeqNo"),
        pages=_clean(raw.get("pages")),
        doc_stamp_date=_parse_api_date(raw.get("docStampDate")),
        download_url=DOCUMENT_API_TEMPLATE.format(
            docket_number=raw.get("sccaCaseNo") or docket_number, doc_id=doc_id
        ),
    )


def _citation(raw: Any) -> WiCitation:
    raw = raw if isinstance(raw, dict) else {}
    page_raw = raw.get("page")
    try:
        page_val: int | None = int(page_raw) if page_raw is not None else None
    except (TypeError, ValueError):
        page_val = None
    doc_seq_raw = raw.get("docSeqNo")
    try:
        doc_seq: int | None = (
            int(doc_seq_raw) if doc_seq_raw is not None else None
        )
    except (TypeError, ValueError):
        doc_seq = None
    return WiCitation(
        volume=_clean(raw.get("volume")),
        publisher=_clean(raw.get("publisher")),
        page=page_val,
        court_type_code=_clean(raw.get("courtTypeCode")),
        doc_seq_no=doc_seq,
    )


def _cc_case(raw: Any) -> WiCircuitCourtCase:
    raw = raw if isinstance(raw, dict) else {}
    legacy = raw.get("legacyCaseLink")
    if isinstance(legacy, str) and legacy:
        # The API already returns absolute URLs for these; keep them as-is.
        legacy_url = legacy
    else:
        legacy_url = None
    return WiCircuitCourtCase(
        cc_case_no=_clean(raw.get("ccCaseNo")) or "",
        cc_county=_clean(raw.get("ccCounty")),
        cc_county_no=raw.get("ccCountyNo"),
        judge_name=_clean(raw.get("ctofcName")),
        responsible_judge_name=_clean(raw.get("respCtofcName")),
        legacy_case_link=legacy_url,
    )
