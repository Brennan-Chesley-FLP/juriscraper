"""Data models for the Maryland Judiciary Case Search appellate scraper.

Site: https://casesearch.courts.state.md.us/casesearch/

Supported courts (CourtListener IDs):

- ``md``           — Supreme Court of Maryland   (case prefix ``SCM-*``)
- ``mdctspecapp``  — Appellate Court of Maryland (case prefix ``ACM-*``)

The two courts were renamed by constitutional amendment in 2022 (formerly the
Court of Appeals of Maryland and the Court of Special Appeals of Maryland);
CourtListener still keys them by the historical IDs.

The portal serves all docket data as JSON (no HTML/PDF), so a single
``MdAppellateDocket`` carries everything from one case-detail payload.

Field names follow [`../../CL_MODELS.md`](../../CL_MODELS.md): the CourtListener
court-id string is ``court`` (not ``court_id``), the case number is
``docket_number`` (with a verbatim ``docket_number_raw``), and dates use the
``date_*`` prefix.
"""

from __future__ import annotations

from datetime import date
from typing import ClassVar

from jkent.common.data_models import ScrapedData

from juriscraper.state.common_models import CleanString, HarmonizedCaseName

# CourtListener court id -> display name.
COURT_IDS: dict[str, str] = {
    "md": "Supreme Court of Maryland",
    "mdctspecapp": "Appellate Court of Maryland",
}

# Three-letter site court prefix -> CourtListener court id.
COURT_PREFIX_TO_ID: dict[str, str] = {
    "SCM": "md",
    "ACM": "mdctspecapp",
}


# =========================================================================
# Site constants
# =========================================================================

SITE_BASE: str = "https://casesearch.courts.state.md.us"
SEARCH_FORM_URL: str = f"{SITE_BASE}/casesearch/inquiry-search"
DETAIL_API: str = f"{SITE_BASE}/api-casedetails/v1/public/cases"
DETAIL_PAGE: str = f"{SITE_BASE}/casesearch/case-detail-page"


# =========================================================================
# Nested data models
# =========================================================================


class MdAppellateAddress(ScrapedData):
    """A postal address for a party or attorney.

    Maps to CourtListener ``AttorneyOrganization`` address fields
    (``address1``/``address2``/``city``/``state``/``zip_code``)."""

    address_type: CleanString | None = None
    """Site address-type label (e.g. ``Business``, ``Home``)."""
    address_line_1: CleanString | None = None
    address_line_2: CleanString | None = None
    address_line_3: CleanString | None = None
    city: CleanString | None = None
    state: CleanString | None = None
    """Two-letter USPS state code, as published."""
    zip_code: CleanString | None = None
    is_current: bool | None = None
    """Whether the site flags this as the current address."""


class MdAppellateAttorney(ScrapedData):
    """An attorney representing a party.

    Maps to CourtListener ``Attorney`` (+ ``AttorneyOrganization`` for the
    address)."""

    name: CleanString
    appearance_date: date | None = None
    """Date the attorney entered an appearance on the case."""
    removal_date: date | None = None
    """Date the attorney was removed/withdrew, if any."""
    addresses: list[MdAppellateAddress] = []


class MdAppellateParty(ScrapedData):
    """A party + the attorneys representing them.

    Maps to CourtListener ``Party`` (+ ``PartyType`` for the role on this
    docket)."""

    name: CleanString
    party_type: CleanString | None = None
    """Role on appeal: ``Appellant`` / ``Appellee`` / ``Petitioner`` /
    ``Respondent`` / etc. (CL ``PartyType.name``)."""
    party_type_code: CleanString | None = None
    """Site short code for the party type."""
    addresses: list[MdAppellateAddress] = []
    attorneys: list[MdAppellateAttorney] = []


class MdAppellateDocketEntry(ScrapedData):
    """One row from ``caseEventInfo`` (the register of actions).

    Maps to CourtListener ``DocketEntry``."""

    date_filed: date | None = None
    """``fileDate`` for the entry."""
    description: CleanString | None = None
    """Document/event name (CL ``DocketEntry.description``)."""
    internal_event_id: int | None = None
    """Site internal numeric event id."""
    created_date: CleanString | None = None
    """Raw ISO timestamp the entry was created (kept verbatim)."""


class MdAppellateHearing(ScrapedData):
    """A scheduled hearing or session row from ``hearing[]``.

    Future/scheduled hearings are modelled here as part of the docket
    payload (not as a separate record type)."""

    event_type: CleanString | None = None
    event_date: date | None = None
    event_time: CleanString | None = None
    """Free-text time (e.g. ``10:00 AM``)."""
    location: CleanString | None = None
    result: CleanString | None = None
    """Outcome, when present (e.g. ``Cancelled - Reason: ...``)."""
    internal_hearing_event_id: int | None = None


class MdAppellateJudgment(ScrapedData):
    """A judgment / disposition event from ``judgmentEventInfo[]``."""

    judgment_event_type: CleanString | None = None
    """e.g. ``Denied``, ``Granted``, ``Affirmed``."""
    issue_date: date | None = None
    comments: list[str] = []
    """Free-text comment lines attached to the judgment."""


class MdAppellateRelatedCase(ScrapedData):
    """A related case or cross-reference (trial-court case, transfers, …).

    Maps loosely to CourtListener ``CaseTransfer`` /
    ``OriginatingCourtInformation`` depending on the reference type."""

    docket_number: CleanString
    """The related/cross-referenced case number."""
    reason: CleanString | None = None
    """Relationship reason, for ``relatedCases`` entries."""
    cross_reference_type: CleanString | None = None
    """Cross-reference type, for ``caseCrossReferences`` entries."""
    internal_case_id: CleanString | None = None
    """Site internal id of the referenced case, when present."""


# =========================================================================
# Top-level docket
# =========================================================================


class MdAppellateDocket(ScrapedData):
    """A complete Maryland appellate case docket — main scraper output.

    Maps to CourtListener ``Docket`` (+ nested entries/parties/etc.)."""

    docket_number: str
    """Site case number, e.g. ``ACM-REG-2487-2024`` or
    ``SCM-PET-0192-2025``."""

    docket_number_raw: str | None = None
    """Verbatim ``caseNumber`` from the payload (before any cleanup)."""

    court: str
    """CourtListener court id: ``md`` or ``mdctspecapp``."""

    case_name: HarmonizedCaseName
    """Case caption / title (e.g. ``Kirby v. State of Maryland``)."""

    date_filed: date | None = None
    """Filing date of the appellate case."""

    # === Identifiers ===
    internal_id: int | None = None
    """Site internal numeric id (``caseDetail.internalId``)."""

    case_id_param: str | None = None
    """The dashless ``caseId`` used in URLs, e.g. ``ACMREG24872024``."""

    # === Case info ===
    court_system: CleanString | None = None
    """Display name from the site (e.g. ``Appellate Court of Maryland``)."""
    case_category: CleanString | None = None
    """Site category code (e.g. ``AP``, ``CV``)."""
    case_type: CleanString | None = None
    """Site case type (e.g. ``Appeal of Criminal Case``)."""
    case_status: CleanString | None = None
    """Status text from ``caseStatus.caseStatusType``."""
    case_status_date: date | None = None
    """Date associated with the current case status."""

    # === Nested data ===
    entries: list[MdAppellateDocketEntry] = []
    hearings: list[MdAppellateHearing] = []
    judgments: list[MdAppellateJudgment] = []
    parties: list[MdAppellateParty] = []
    related_cases: list[MdAppellateRelatedCase] = []
    cross_references: list[MdAppellateRelatedCase] = []

    # === Provenance ===
    source_url: str | None = None
    """Absolute URL of the case-detail page this record was scraped from."""
    source_entry_point: str | None = None
    """Entry point used to reach this docket (e.g. ``dockets_by_number``)."""


class _MdConfig:
    """Site configuration constants, kept off the public model classes."""

    SITE_BASE: ClassVar[str] = SITE_BASE
    SEARCH_FORM_URL: ClassVar[str] = SEARCH_FORM_URL
    DETAIL_API: ClassVar[str] = DETAIL_API
    DETAIL_PAGE: ClassVar[str] = DETAIL_PAGE
    COURT_IDS: ClassVar[dict[str, str]] = COURT_IDS
    COURT_PREFIX_TO_ID: ClassVar[dict[str, str]] = COURT_PREFIX_TO_ID
