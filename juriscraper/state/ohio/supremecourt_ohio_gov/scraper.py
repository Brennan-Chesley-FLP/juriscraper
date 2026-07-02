"""Supreme Court of Ohio (ECMS) docket scraper.

Scrapes the public docket data exposed by the Clerk's Electronic Case
Management System at https://www.supremecourt.ohio.gov/clerk/ecms/.

The visible UI is an SPA, but every action dispatches a single
``POST .../clerk/ecms/Ajax.ashx`` form-encoded request and renders the
returned JSON client-side. The API requires a static CSRF token
(hard-coded in the site's JS bundle) and a ``Referer`` header; nothing
else. This is a pure JSON API spoken directly over HTTP — there is no HTML
to parse, so (per the standards) there is no ``parsers/`` package; the
small payload-shaping helpers live at module level.

Entry points (§4):

- ``docket_by_number(court_id, docket_number)`` — ad-hoc single-case lookup
  by its public ``YYYY-NNNN`` number.
- ``dockets_by_number(docket_number: YearlySpeculativeRange)`` — speculative
  scan over a year's case-number sequence (the bulk strategy). A speculative
  entry takes only its speculative param (§4); the single court ``ohio`` is
  carried as a constant.

Both produce the same ``action=GetCaseDetails`` request and dispatch to the
same ``parse_case_detail`` step, which yields one
:class:`OhioSupremeCourtDocket` plus an archive request per attached PDF.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import TYPE_CHECKING, Any, ClassVar
from urllib.parse import quote

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
)
from pyrate_limiter import Duration, Rate

from juriscraper.state.common.params import YearlySpeculativeRange

from .models import (
    COURT_ID,
    COURT_IDS,
    OhioSupremeCourtAttorney,
    OhioSupremeCourtDecision,
    OhioSupremeCourtDocket,
    OhioSupremeCourtDocketEntry,
    OhioSupremeCourtDocument,
    OhioSupremeCourtParty,
    OhioSupremeCourtPriorCourt,
)

if TYPE_CHECKING:
    from collections.abc import Generator

    from jkent.data_types import ScraperYield


# =============================================================================
# Endpoints and constants
# =============================================================================

BASE_URL = "https://www.supremecourt.ohio.gov/clerk/ecms"
AJAX_URL = f"{BASE_URL}/Ajax.ashx"
REFERER = f"{BASE_URL}/"
PDF_VIEWER_URL = "https://www.supremecourt.ohio.gov/pdf_viewer/pdf_viewer.aspx"

# CSRF token hard-coded in scripts/dist/site.min.js (the same token is sent
# by every visitor; the server only checks that *some* matching value is
# present). Update if the JS bundle ever rotates it.
CSRF_TOKEN = "hP3ZyrdvKmaPk4kVjgko7xxNUob"

# The API silently returns an empty 200 to clients with the default httpx
# User-Agent; a browser-shaped string is enough to satisfy it.
_BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/147.0.0.0 Safari/537.36"
)

# Docket numbers always render as YYYY-NNNN (4-digit year, 4-digit sequence).
_DOCKET_ID_RE = re.compile(r"^\s*(\d{4})\s*-\s*(\d{1,4})\s*$")

# The API returns this JSON-encoded string for any miss (no match or
# multi-match prefix). Real hits return a JSON object.
_SOFT_404_BODY = '"Too many results"'


_Yield = OhioSupremeCourtDocket | OhioSupremeCourtDocument


# =============================================================================
# Scraper
# =============================================================================


class OhioSupremeCourtScraper(BaseScraper[_Yield]):
    """Scraper for the Supreme Court of Ohio public docket (ECMS).

    Speaks the site's ``Ajax.ashx`` JSON API directly over HTTP. Emits one
    :class:`OhioSupremeCourtDocket` per case and an
    :class:`OhioSupremeCourtDocument` per archived PDF (joinable back to the
    docket via ``docket_number``).
    """

    # === Metadata ===
    court_ids: ClassVar[set[str]] = set(COURT_IDS.keys())
    court_url: ClassVar[str] = f"{BASE_URL}/"
    data_types: ClassVar[set[str]] = {"dockets"}
    status: ClassVar[ScraperStatus] = ScraperStatus.IN_DEVELOPMENT
    version: ClassVar[str] = "2026-06-27"
    last_verified: ClassVar[str] = "2026-05-06"
    requires_auth: ClassVar[bool] = False
    driver_requirements: ClassVar[list[DriverRequirement]] = []
    rate_limits: ClassVar[list[Rate] | None] = [Rate(2, Duration.SECOND)]

    # =========================================================================
    # Entry points (§4)
    # =========================================================================

    @entry(OhioSupremeCourtDocket)
    def docket_by_number(
        self, court_id: str, docket_number: str
    ) -> Generator[Request, None, None]:
        """Fetch a single docket by its public ``YYYY-NNNN`` case number.

        The user supplies the docket number directly (no enumeration).
        Invalid formats are dropped silently; the API never matches them
        anyway.
        """
        match = _DOCKET_ID_RE.match(docket_number or "")
        if not match:
            return
        year = int(match.group(1))
        number = int(match.group(2))
        yield self._build_case_request(
            year, number, entry_point="docket_by_number"
        )

    @entry(OhioSupremeCourtDocket)
    def dockets_by_number(
        self, docket_number: YearlySpeculativeRange
    ) -> Request:
        """Speculative scan over a year's case-number sequence (bulk).

        This is a speculative entry, so it takes only its speculative param
        (§4 "Multi-court speculative entries") — the single court ``ohio``
        is carried as a constant. Seed shape per year::

            {"dockets_by_number": {"docket_number":
                {"year": 2026, "min": 1, "soft_max": 600, "gap": 25}}}

        Year rollover is the operator's responsibility — add a new seed
        entry each January.
        """
        return self._build_case_request(
            docket_number.year,
            docket_number.min,
            entry_point="dockets_by_number",
        )

    # =========================================================================
    # Request builder
    # =========================================================================

    def _build_case_request(
        self, year: int, number: int, *, entry_point: str
    ) -> Request:
        docket_number = f"{year:04d}-{number:04d}"
        return Request(
            request=HTTPRequestParams(
                method=HttpMethod.POST,
                url=AJAX_URL,
                data={
                    "paramCaseNumber": f"{number:04d}",
                    "paramCaseYear": f"{year:04d}",
                    "isLoading": "true",
                    "action": "GetCaseDetails",
                    "caseId": "0",
                    "caseNumber": "",
                    "caseType": "",
                    "dateFiled": "",
                    "caseStatus": "",
                    "caseCaption": "",
                    "priorJurisdiction": "",
                    "showParties": "true",
                    "showDocket": "true",
                    "showDecision": "true",
                    "showIssues": "true",
                    "subscriptionId": "",
                    "subUserId": "",
                    "noResult": "false",
                    "isSealed": "false",
                },
                headers={
                    "X-CSRF-TOKEN": CSRF_TOKEN,
                    "X-Requested-With": "XMLHttpRequest",
                    "Referer": REFERER,
                    "Accept": "application/json, text/plain, */*",
                    "User-Agent": _BROWSER_USER_AGENT,
                },
            ),
            nonnavigating=True,
            continuation=self.parse_case_detail,
            accumulated_data={
                "docket_number": docket_number,
                "entry_point": entry_point,
            },
            deduplication_key=f"docket_by_number:{docket_number}",
        )

    # =========================================================================
    # Soft-404 detection
    # =========================================================================

    def actually_successful(self, response: Response) -> bool:
        """Return False when the API returned its miss sentinel.

        ``GetCaseDetails`` returns the JSON-encoded literal
        ``"Too many results"`` for both no-match and multi-match prefix
        searches; the driver treats a False here as a speculation soft
        failure. Real hits return a JSON object.
        """
        body = (response.text or "").strip()
        return body != _SOFT_404_BODY

    # =========================================================================
    # Step 1: parse case detail JSON
    # =========================================================================

    @step(priority=2)
    def parse_case_detail(
        self,
        json_content: Any,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[_Yield], None, None]:
        """Convert the GetCaseDetails JSON into a docket plus PDF archives."""
        # The miss sentinel is a JSON string, not an object. Belt-and-braces
        # against the soft-404 detector — also covers the case where the
        # body is empty or otherwise malformed.
        if not isinstance(json_content, dict):
            return

        case_info = json_content.get("CaseInfo") or {}
        if not case_info or not case_info.get("ID"):
            return

        docket_number = (
            case_info.get("CaseNumber")
            or accumulated_data.get("docket_number")
            or ""
        ).strip()
        if not docket_number:
            return

        prior_court = _build_prior_court(json_content.get("CaseJurisdiction"))
        parties = _build_parties(json_content.get("Parties") or [])
        entries, entry_documents = _build_entries(
            docket_number, json_content.get("DocketItems") or []
        )
        decisions, decision_documents = _build_decisions(
            docket_number, json_content.get("DecisionItems") or []
        )
        issues = _build_issues(json_content.get("CaseIssues") or [])

        docket = OhioSupremeCourtDocket.raw(
            docket_number=docket_number,
            court=COURT_ID,
            date_filed=_parse_iso_date(case_info.get("DateFiled")),
            case_name=_clean_caption(case_info.get("Caption"))
            or docket_number,
            case_id=_safe_int(case_info.get("ID")),
            case_type=_clean(case_info.get("CaseType")),
            status=_clean(case_info.get("Status")),
            prior_court=prior_court,
            parties=parties,
            entries=entries,
            decisions=decisions,
            issues=issues,
            source_url=(
                f"{BASE_URL}/#/caseinfo/"
                f"{docket_number[:4]}/{docket_number[5:]}"
            ),
            source_entry_point=accumulated_data.get("entry_point"),
        )
        yield ParsedData(data=docket)

        for doc in entry_documents:
            yield self._build_archive_request(doc)
        for doc in decision_documents:
            yield self._build_archive_request(doc)

    def _build_archive_request(
        self, doc: tuple[str, int, str, str]
    ) -> Request:
        docket_number, document_id, document_url, section = doc
        return Request(
            archive=True,
            request=HTTPRequestParams(
                method=HttpMethod.GET,
                url=document_url,
                headers={
                    "Accept": "application/pdf, */*",
                    "Referer": REFERER,
                    "User-Agent": _BROWSER_USER_AGENT,
                },
            ),
            continuation=self.handle_document_download,
            expected_type="pdf",
            accumulated_data={
                "docket_number": docket_number,
                "document_id": document_id,
                "document_url": document_url,
                "section": section,
            },
            # File-download key — no colons (used in filenames, §6).
            deduplication_key=f"{docket_number}-{document_id}-{section}",
        )

    # =========================================================================
    # Step 2: archived-PDF completion
    # =========================================================================

    @step()
    def handle_document_download(
        self,
        local_filepath: str | None,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[_Yield], None, None]:
        """Emit a downloaded-document record once the PDF is on disk."""
        yield ParsedData(
            data=OhioSupremeCourtDocument.raw(
                docket_number=accumulated_data["docket_number"],
                court=COURT_ID,
                document_id=accumulated_data["document_id"],
                document_url=accumulated_data["document_url"],
                section=accumulated_data["section"],
                local_path=local_filepath,
            )
        )


# =============================================================================
# Module-level helpers
# =============================================================================


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    text = value.strip()
    return text or None


def _clean_caption(value: str | None) -> str | None:
    """Collapse the caption's embedded line breaks into single spaces."""
    if value is None:
        return None
    parts = [p.strip() for p in value.replace("\r", "\n").split("\n")]
    text = " ".join(p for p in parts if p)
    return text or None


def _safe_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _parse_iso_date(value: str | None) -> date | None:
    """Parse the API's ``YYYY-MM-DDTHH:MM:SS`` strings into ``date``."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value).date()
    except ValueError:
        # Some entries come back as just YYYY-MM-DD or similar.
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None


def _document_url(docket_number: str, document_name: str, section: str) -> str:
    """Build the public PDF-viewer URL for a docket-item / decision PDF."""
    # The site uses a literal backslash between the case number and the
    # section folder; it must be URL-encoded as %5C.
    subdirectory = f"{docket_number}\\{section}"
    return (
        f"{PDF_VIEWER_URL}"
        f"?pdf={quote(document_name, safe='')}"
        f"&subdirectory={quote(subdirectory, safe='')}"
        f"&source=DL_Clerk"
    )


def _build_prior_court(
    raw: dict | None,
) -> OhioSupremeCourtPriorCourt | None:
    if not raw:
        return None
    name = _clean(raw.get("Name"))
    county = _clean(raw.get("County"))
    decision_date = _parse_iso_date(raw.get("PriorDecisionDate"))
    numbers = [
        _clean(item.get("Number"))
        for item in raw.get("PriorCaseNumbers") or []
        if isinstance(item, dict)
    ]
    numbers = [n for n in numbers if n]
    if not (name or county or decision_date or numbers):
        return None
    return OhioSupremeCourtPriorCourt(
        name=name,
        county=county,
        prior_decision_date=decision_date,
        prior_case_numbers=numbers,
    )


def _build_parties(raw: list) -> list[OhioSupremeCourtParty]:
    out: list[OhioSupremeCourtParty] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        name = _clean(item.get("Name"))
        if not name:
            continue
        attorneys = [
            OhioSupremeCourtAttorney(
                name=a_name,
                ar_number=_clean(att.get("ARNumber")),
                counsel_of_record=bool(att.get("CounselOfRecord")),
            )
            for att in item.get("Attorneys") or []
            if isinstance(att, dict)
            and (a_name := _clean(att.get("Name"))) is not None
        ]
        out.append(
            OhioSupremeCourtParty(
                name=name,
                role=_clean(item.get("Type")) or "",
                pro_se=bool(item.get("ProSe")),
                attorneys=attorneys,
            )
        )
    return out


def _build_entries(
    docket_number: str, raw: list
) -> tuple[list[OhioSupremeCourtDocketEntry], list[tuple[str, int, str, str]]]:
    entries: list[OhioSupremeCourtDocketEntry] = []
    documents: list[tuple[str, int, str, str]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        description = _clean(item.get("Description"))
        if not description:
            continue
        item_id = _safe_int(item.get("ID"))
        document_name = _clean(item.get("DocumentName"))
        # The DocketItems list interleaves decision rows (Type=DECISION)
        # whose PDFs live in the DecisionItems folder, not DocketItems.
        section = (
            "DecisionItems"
            if (item.get("Type") or "").upper() == "DECISION"
            else "DocketItems"
        )
        document_url = (
            _document_url(docket_number, document_name, section)
            if document_name
            else None
        )
        entries.append(
            OhioSupremeCourtDocketEntry(
                date_filed=_parse_iso_date(item.get("DateFiled")),
                description=description,
                filing_parties=_clean(item.get("FilingParties")),
                item_id=item_id,
                code=_clean(item.get("Code")),
                document_name=document_name,
                document_url=document_url,
            )
        )
        if document_name and document_url and item_id is not None:
            documents.append((docket_number, item_id, document_url, section))
    return entries, documents


def _build_decisions(
    docket_number: str, raw: list
) -> tuple[list[OhioSupremeCourtDecision], list[tuple[str, int, str, str]]]:
    decisions: list[OhioSupremeCourtDecision] = []
    documents: list[tuple[str, int, str, str]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        description = _clean(item.get("Description"))
        if not description:
            continue
        document_name = _clean(item.get("DocumentName"))
        document_url = (
            _document_url(docket_number, document_name, "DecisionItems")
            if document_name
            else None
        )
        decisions.append(
            OhioSupremeCourtDecision(
                release_date=_parse_iso_date(item.get("ReleaseDate")),
                description=description,
                disposes_case=bool(item.get("DisposesCase")),
                document_name=document_name,
                document_url=document_url,
            )
        )
        if document_name and document_url:
            # Decision items don't always include an ID; derive one from the
            # filename stem when possible to give the dedup key something
            # stable.
            stem = document_name.rsplit(".", 1)[0]
            doc_id = _safe_int(stem)
            if doc_id is not None:
                documents.append(
                    (docket_number, doc_id, document_url, "DecisionItems")
                )
    return decisions, documents


def _build_issues(raw: list) -> list[str]:
    out: list[str] = []
    for item in raw:
        if isinstance(item, str):
            text = _clean(item)
            if text:
                out.append(text)
        elif isinstance(item, dict):
            for key in ("Description", "Issue", "Text", "Name"):
                text = _clean(item.get(key))
                if text:
                    out.append(text)
                    break
    return out
