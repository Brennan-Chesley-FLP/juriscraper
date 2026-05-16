"""Maryland Judiciary Case Search & Record Portal scraper.

Scrapes appellate dockets from
https://casesearch.courts.state.md.us/casesearch/.

Supported courts:
- Supreme Court of Maryland (``md``) — case prefix ``SCM-*``
- Appellate Court of Maryland (``mdctspecapp``) — case prefix ``ACM-*``

The portal is fronted by DataDome bot protection, so the scraper must run
under a real browser (FF_ALIKE / JS_EVAL). Once the DataDome cookie is
issued, the underlying JSON APIs become callable:

- ``GET /api-casedetails/v1/public/cases/{caseId}``  — single case detail
- ``POST /api-caselist/v1/cases``                    — last-name search

There is no public way to enumerate cases by date alone (every search form
requires a Last Name), so we lean on speculative entry against the case
detail API. Case numbers follow ``{COURT3}-{TYPE3}-{NNNN}-{YYYY}`` with a
new sequence each year, and the URL strips the dashes:
``caseId={COURT3}{TYPE3}{NNNN}{YYYY}``. Invalid case IDs return HTTP 400,
which the speculation driver records as a normal "miss".
"""

from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING, ClassVar

from jkent.common.decorators import entry, step
from jkent.common.param_models import YearlySpeculativeRange
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

from .models import (
    MdAppellateAddress,
    MdAppellateAttorney,
    MdAppellateDocket,
    MdAppellateDocketEntry,
    MdAppellateHearing,
    MdAppellateJudgment,
    MdAppellateParty,
    MdAppellateRelatedCase,
)

if TYPE_CHECKING:
    from collections.abc import Generator

    from jkent.data_types import ScraperYield


SITE_BASE = "https://casesearch.courts.state.md.us"
DETAIL_API = f"{SITE_BASE}/api-casedetails/v1/public/cases"
DETAIL_PAGE = f"{SITE_BASE}/casesearch/case-detail-page"


# (court_id, court3, type3) per @entry method.
_PREFIXES: dict[str, tuple[str, str, str]] = {
    "fetch_acm_reg_docket": ("mdctspecapp", "ACM", "REG"),
    "fetch_acm_ala_docket": ("mdctspecapp", "ACM", "ALA"),
    "fetch_scm_pet_docket": ("md", "SCM", "PET"),
    "fetch_scm_misc_docket": ("md", "SCM", "MISC"),
    "fetch_scm_reg_docket": ("md", "SCM", "REG"),
}


class MarylandJudiciaryCaseSearchScraper(BaseScraper[MdAppellateDocket]):
    """Scraper for the Maryland Judiciary Case Search & Record Portal.

    One speculative ``@entry`` per ``(court, case-type)`` combination so the
    driver advances each prefix's sequence independently. Each invocation
    fetches a single case from the detail JSON API.
    """

    # === Metadata ===
    court_ids: ClassVar[set[str]] = {"md", "mdctspecapp"}
    court_url: ClassVar[str] = f"{SITE_BASE}/casesearch/inquiry-search"
    data_types: ClassVar[set[str]] = {"dockets"}
    status: ClassVar[ScraperStatus] = ScraperStatus.IN_DEVELOPMENT
    version: ClassVar[str] = "2026-05-03"
    requires_auth: ClassVar[bool] = False

    rate_limits: ClassVar[list[Rate] | None] = [Rate(2, Duration.SECOND)]

    # DataDome JS challenge gates every request, so we need a real browser.
    driver_requirements: ClassVar[list[DriverRequirement]] = [
        DriverRequirement.JS_EVAL,
        DriverRequirement.FF_ALIKE,
    ]

    # =========================================================================
    # Entry points (one per (court, type) prefix)
    # =========================================================================

    @entry(MdAppellateDocket)
    def fetch_acm_reg_docket(self, case_id: YearlySpeculativeRange) -> Request:
        """Speculative fetch for ACM-REG-{NNNN}-{YYYY} (regular appeal)."""
        return self._build_speculative_request(case_id, "ACM", "REG")

    @entry(MdAppellateDocket)
    def fetch_acm_ala_docket(self, case_id: YearlySpeculativeRange) -> Request:
        """Speculative fetch for ACM-ALA-{NNNN}-{YYYY} (leave to appeal)."""
        return self._build_speculative_request(case_id, "ACM", "ALA")

    @entry(MdAppellateDocket)
    def fetch_scm_pet_docket(self, case_id: YearlySpeculativeRange) -> Request:
        """Speculative fetch for SCM-PET-{NNNN}-{YYYY} (cert petition)."""
        return self._build_speculative_request(case_id, "SCM", "PET")

    @entry(MdAppellateDocket)
    def fetch_scm_misc_docket(
        self, case_id: YearlySpeculativeRange
    ) -> Request:
        """Speculative fetch for SCM-MISC-{NNNN}-{YYYY} (miscellaneous)."""
        return self._build_speculative_request(case_id, "SCM", "MISC")

    @entry(MdAppellateDocket)
    def fetch_scm_reg_docket(self, case_id: YearlySpeculativeRange) -> Request:
        """Speculative fetch for SCM-REG-{NNNN}-{YYYY} (regular SCM matter)."""
        return self._build_speculative_request(case_id, "SCM", "REG")

    def _build_speculative_request(
        self,
        case_id: YearlySpeculativeRange,
        court3: str,
        type3: str,
    ) -> Request:
        case_id_param = f"{court3}{type3}{case_id.min:04d}{case_id.year}"
        case_number = f"{court3}-{type3}-{case_id.min:04d}-{case_id.year}"
        court_id = "mdctspecapp" if court3 == "ACM" else "md"
        return Request(
            request=HTTPRequestParams(
                method=HttpMethod.GET,
                url=f"{DETAIL_API}/{case_id_param}",
                headers={"Accept": "application/json"},
            ),
            continuation=self.parse_case_detail,
            accumulated_data={
                "case_id_param": case_id_param,
                "docket_id": case_number,
                "court_id": court_id,
            },
            deduplication_key=f"md-case-{case_id_param}",
        )

    # =========================================================================
    # Step 1: case detail JSON
    # =========================================================================

    @step()
    def parse_case_detail(
        self,
        json_content: dict,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[MdAppellateDocket], None, None]:
        """Parse the case detail JSON payload into a ``MdAppellateDocket``."""
        detail = json_content.get("caseDetail") or {}

        case_id_param = accumulated_data["case_id_param"]
        docket_id = detail.get("caseNumber") or accumulated_data["docket_id"]

        status_block = detail.get("caseStatus") or {}

        docket = MdAppellateDocket(
            docket_id=docket_id,
            court_id=accumulated_data["court_id"],
            date_filed=_parse_us_date(detail.get("filedDate")),
            case_name=detail.get("caseTitle") or docket_id,
            internal_id=detail.get("internalId"),
            case_id_param=case_id_param,
            court_system=detail.get("courtSystem"),
            case_category=detail.get("caseCategory"),
            case_type=detail.get("caseType"),
            case_status=status_block.get("caseStatusType"),
            case_status_date=_parse_us_date(status_block.get("date")),
            entries=_parse_entries(detail.get("caseEventInfo")),
            hearings=_parse_hearings(detail.get("hearing")),
            judgments=_parse_judgments(detail.get("judgmentEventInfo")),
            parties=_parse_parties(detail.get("involvedParties")),
            related_cases=_parse_related(detail.get("relatedCases")),
            cross_references=_parse_cross_refs(
                detail.get("caseCrossReferences")
            ),
            source_url=f"{DETAIL_PAGE}?caseId={case_id_param}",
        )
        yield ParsedData(data=docket)


# =============================================================================
# Module-level parsing helpers
# =============================================================================


def _parse_us_date(value: str | None) -> date | None:
    """Parse a ``MM/DD/YYYY`` date string."""
    if not value:
        return None
    try:
        return datetime.strptime(value.strip(), "%m/%d/%Y").date()
    except ValueError:
        return None


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    text = value.strip()
    return text or None


def _parse_entries(events: list[dict] | None) -> list[MdAppellateDocketEntry]:
    if not events:
        return []
    out = []
    for e in events:
        out.append(
            MdAppellateDocketEntry(
                file_date=_parse_us_date(e.get("fileDate")),
                document_name=_clean(e.get("documentName")),
                internal_event_id=e.get("internalEventID"),
                created_date=_clean(e.get("createdDate")),
            )
        )
    return out


def _parse_hearings(hearings: list[dict] | None) -> list[MdAppellateHearing]:
    if not hearings:
        return []
    out = []
    for h in hearings:
        out.append(
            MdAppellateHearing(
                event_type=_clean(h.get("eventType")),
                event_date=_parse_us_date(h.get("eventDate")),
                event_time=_clean(h.get("eventTime")),
                location=_clean(h.get("location")),
                result=_clean(h.get("result")),
                internal_hearing_event_id=h.get("internalHearingEventID"),
            )
        )
    return out


def _parse_judgments(
    judgments: list[dict] | None,
) -> list[MdAppellateJudgment]:
    if not judgments:
        return []
    out = []
    for j in judgments:
        comments = j.get("comment") or []
        out.append(
            MdAppellateJudgment(
                judgment_event_type=_clean(j.get("judgmentEventType")),
                issue_date=_parse_us_date(j.get("issueDate")),
                comments=[c for c in (str(x).strip() for x in comments) if c],
            )
        )
    return out


def _parse_address(addr: dict) -> MdAppellateAddress:
    current = addr.get("currentAddress")
    is_current: bool | None = None
    if isinstance(current, str):
        is_current = current.strip().lower() == "yes"
    elif isinstance(current, bool):
        is_current = current
    return MdAppellateAddress(
        address_type=_clean(addr.get("addressType")),
        address_line_1=_clean(addr.get("addressLine1")),
        address_line_2=_clean(addr.get("addressLine2")),
        address_line_3=_clean(addr.get("addressLine3")),
        city=_clean(addr.get("city")),
        state=_clean(addr.get("state")),
        zip_code=_clean(addr.get("zip")),
        is_current=is_current,
    )


def _parse_attorneys(
    attorneys: list[dict] | None,
) -> list[MdAppellateAttorney]:
    if not attorneys:
        return []
    out = []
    for a in attorneys:
        addresses = [
            _parse_address(addr) for addr in (a.get("attorneyAddress") or [])
        ]
        out.append(
            MdAppellateAttorney(
                name=_clean(a.get("attorneyName")) or "",
                appearance_date=_parse_us_date(a.get("appearanceDate")),
                removal_date=_parse_us_date(a.get("removalDate")),
                addresses=addresses,
            )
        )
    return out


def _parse_parties(parties: list[dict] | None) -> list[MdAppellateParty]:
    if not parties:
        return []
    out = []
    for p in parties:
        addresses = [
            _parse_address(addr)
            for addr in (p.get("involvedPartyAddresses") or [])
        ]
        out.append(
            MdAppellateParty(
                name=_clean(p.get("partyName")) or "",
                party_type=_clean(p.get("partyType")),
                party_type_code=_clean(p.get("partyTypeCode")),
                addresses=addresses,
                attorneys=_parse_attorneys(p.get("attorneyInfo")),
            )
        )
    return out


def _parse_related(
    related: list[dict] | None,
) -> list[MdAppellateRelatedCase]:
    if not related:
        return []
    out = []
    for r in related:
        out.append(
            MdAppellateRelatedCase(
                case_number=_clean(r.get("caseNumber")) or "",
                reason=_clean(r.get("reason")),
                internal_case_id=_clean(r.get("caseID")),
            )
        )
    return [r for r in out if r.case_number]


def _parse_cross_refs(
    refs: list[dict] | None,
) -> list[MdAppellateRelatedCase]:
    if not refs:
        return []
    out = []
    for r in refs:
        out.append(
            MdAppellateRelatedCase(
                case_number=_clean(r.get("crossCaseNumber")) or "",
                cross_reference_type=_clean(r.get("caseCrossReferenceType")),
                internal_case_id=_clean(r.get("caseCrossReferenceID")),
            )
        )
    return [r for r in out if r.case_number]
