"""Data models for Maryland appellate courts scraper.

Supported courts:
- md: Supreme Court of Maryland (case prefix SCM-*)
- mdctspecapp: Appellate Court of Maryland (case prefix ACM-*)

The two courts were renamed in 2022 (formerly Court of Appeals of Maryland
and Court of Special Appeals of Maryland respectively); CourtListener still
uses the historical IDs.
"""

from __future__ import annotations

from datetime import date

from jkent.common.data_models import ScrapedData

COURT_IDS: dict[str, str] = {
    "md": "Supreme Court of Maryland",
    "mdctspecapp": "Appellate Court of Maryland",
}


class MdAppellateAddress(ScrapedData):
    """A postal address for a party or attorney."""

    address_type: str | None = None
    address_line_1: str | None = None
    address_line_2: str | None = None
    address_line_3: str | None = None
    city: str | None = None
    state: str | None = None
    zip_code: str | None = None
    is_current: bool | None = None


class MdAppellateAttorney(ScrapedData):
    """An attorney representing a party in an appellate case."""

    name: str
    appearance_date: date | None = None
    removal_date: date | None = None
    addresses: list[MdAppellateAddress] = []


class MdAppellateParty(ScrapedData):
    """A party (Appellant, Appellee, Petitioner, etc.) in the case."""

    name: str
    party_type: str | None = None
    party_type_code: str | None = None
    addresses: list[MdAppellateAddress] = []
    attorneys: list[MdAppellateAttorney] = []


class MdAppellateDocketEntry(ScrapedData):
    """A single row from caseEventInfo (Register of Actions)."""

    file_date: date | None = None
    document_name: str | None = None
    internal_event_id: int | None = None
    created_date: str | None = None


class MdAppellateHearing(ScrapedData):
    """A scheduled hearing or session entry."""

    event_type: str | None = None
    event_date: date | None = None
    event_time: str | None = None
    location: str | None = None
    result: str | None = None
    internal_hearing_event_id: int | None = None


class MdAppellateJudgment(ScrapedData):
    """A judgment / disposition event."""

    judgment_event_type: str | None = None
    issue_date: date | None = None
    comments: list[str] = []


class MdAppellateRelatedCase(ScrapedData):
    """A related case or cross-reference (trial-court case, transfers, etc.)."""

    case_number: str
    reason: str | None = None
    internal_case_id: str | None = None
    cross_reference_type: str | None = None


class MdAppellateDocket(ScrapedData):
    """A complete Maryland appellate court docket."""

    # === Searchable fields ===
    docket_id: str
    """Site case number, e.g. 'ACM-REG-2487-2024' or 'SCM-PET-0192-2025'."""

    court_id: str
    """CourtListener court id: 'md' or 'mdctspecapp'."""

    date_filed: date | None = None
    """Filing date of the appellate case."""

    case_name: str
    """Case caption / title (e.g. 'KIRBY v. State of Maryland')."""

    # === Identifiers ===
    internal_id: int | None = None
    """Site internal numeric id (caseDetail.internalId)."""

    case_id_param: str | None = None
    """The dashless caseId used in URLs, e.g. 'ACMREG24872024'."""

    # === Case info ===
    court_system: str | None = None
    """Display name from the site (e.g. 'Appellate Court of Maryland')."""

    case_category: str | None = None
    """Site category code (e.g. 'AP', 'CV')."""

    case_type: str | None = None
    """Site case type (e.g. 'Appeal of Criminal Case')."""

    case_status: str | None = None
    """Status text from caseStatus.caseStatusType."""

    case_status_date: date | None = None

    # === Nested data ===
    entries: list[MdAppellateDocketEntry] = []
    hearings: list[MdAppellateHearing] = []
    judgments: list[MdAppellateJudgment] = []
    parties: list[MdAppellateParty] = []
    related_cases: list[MdAppellateRelatedCase] = []
    cross_references: list[MdAppellateRelatedCase] = []

    # === Source ===
    source_url: str | None = None
