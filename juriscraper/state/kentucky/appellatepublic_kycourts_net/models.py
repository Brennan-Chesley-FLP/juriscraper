"""Data models for the Kentucky appellate courts scraper.

Source: https://appellatepublic.kycourts.net (Thomson Reuters
"C-Track Public Access" — the JSON-API variant, distinct from both the
"TR Portal" product handled by ``juriscraper.state.common.tr`` and the
older HTML-form C-Track handled by ``juriscraper.state.common.ctrack``).

Field names follow [`../../CL_MODELS.md`](../../CL_MODELS.md): the
CourtListener court-id string is ``court`` (not ``court_id``), the case
number is ``docket_number`` (with a verbatim ``docket_number_raw``), and
dates use the ``date_*`` prefix. ``CleanString``/``HarmonizedCaseName``
clean the free-text caption fields.
"""

from __future__ import annotations

from datetime import date

from jkent.common.data_models import ScrapedData

from juriscraper.state.common_models import CleanString, HarmonizedCaseName

API_BASE_URL = "https://appellatepublic.kycourts.net/api/api/v1"
PORTAL_URL = "https://appellatepublic.kycourts.net"

# Site court name (from /cases/{id}.court) -> CourtListener court id.
SITE_COURT_TO_ID: dict[str, str] = {
    "Kentucky Supreme Court": "ky",
    "Kentucky Court of Appeals": "kyctapp",
}

# CourtListener court id -> case-number prefix component (e.g. "SC", "CA").
COURT_CASE_PREFIX: dict[str, str] = {
    "ky": "SC",
    "kyctapp": "CA",
}

# CourtListener court id -> human-readable name.
COURT_NAMES: dict[str, str] = {
    "ky": "Kentucky Supreme Court",
    "kyctapp": "Kentucky Court of Appeals",
}


class KyDocketEntry(ScrapedData):
    """A single docket entry row on a Kentucky appellate case.

    Maps loosely to CourtListener ``DocketEntry``."""

    docket_entry_id: str
    """C-Track docketEntryID (hash). Stable identifier for the entry."""

    date_filed: date | None = None
    """When the entry was filed."""

    entry_type: CleanString | None = None
    """docketEntryType — broad category (e.g. 'FINALITY',
    'DISPOSITION - OPINION AND ORDER')."""

    entry_subtype: CleanString | None = None
    """docketEntrySubtype — narrower classification."""

    description: CleanString | None = None
    """docketEntryDescription — human-readable label for this entry
    (CL ``DocketEntry.description``)."""

    submitted_by: CleanString | None = None
    """Filer / submitter, when present."""

    comments: CleanString | None = None
    """Free-text comments from customFields.Comments."""

    is_opinion: bool = False
    """The 'opinion' flag set by C-Track on dispositional opinion entries."""

    has_documents: bool = False
    """Whether the entry has at least one attached document available
    via /publicaccessdocuments."""


class KyParty(ScrapedData):
    """A party on a Kentucky appellate case.

    Maps to CourtListener ``Party`` (+ ``PartyType`` for the role on this
    docket); nested attorneys map to ``Attorney`` (+ ``Role``)."""

    name: CleanString | None = None
    """Party display name (CL ``Party.name``)."""

    role: CleanString | None = None
    """Role on this docket: ``Appellant`` / ``Appellee`` / etc.
    (CL ``PartyType.name``)."""

    status: CleanString | None = None
    """Party status text from C-Track (partyStatus)."""

    pro_se: bool = False
    """Whether the party is self-represented."""

    address: CleanString | None = None
    """Flattened single-line address (CL ``Attorney.contact_raw`` analog)."""

    attorneys: list[KyAttorney] = []
    """Attorneys representing this party."""


class KyAttorney(ScrapedData):
    """An attorney representing a party. Maps to CourtListener ``Attorney``."""

    name: CleanString | None = None
    """Attorney display name (CL ``Attorney.name``)."""

    role: CleanString | None = None
    """Attorney role string when present (CL ``Role.role_raw``)."""

    address: CleanString | None = None
    """Flattened single-line address (CL ``Attorney.contact_raw``)."""

    bar_number: CleanString | None = None
    """Kentucky bar number."""


class KyTrialCourt(ScrapedData):
    """Lower / originating court info.

    Maps to CourtListener ``OriginatingCourtInformation``."""

    name: CleanString | None = None
    """Lower-court name (lowerCourtName)."""

    docket_number: CleanString | None = None
    """Lower-court case number (lowerCourtCaseNumber; CL
    ``OriginatingCourtInformation.docket_number``)."""

    case_title: CleanString | None = None
    """Lower-court case title (lowerCourtCaseTitle)."""


class KyDocket(ScrapedData):
    """A complete Kentucky appellate docket — main scraper output.

    Maps to CourtListener ``Docket``."""

    case_id: str
    """C-Track caseID (hash). Primary key for the case in C-Track."""

    docket_number: str
    """Public case number, e.g. '2026-SC-0005' or '2024-CA-0134'
    (CL ``Docket.docket_number``)."""

    docket_number_raw: str | None = None
    """Verbatim case number as returned by the site, before any cleaning."""

    court: str
    """CourtListener court id ('ky' or 'kyctapp')."""

    date_filed: date | None = None
    """When the case was filed in the appellate court."""

    case_name: HarmonizedCaseName
    """Case caption (shortTitle from C-Track; CL ``Docket.case_name``)."""

    case_name_full: CleanString | None = None
    """Long-form caption when available (fullTitle; often null)."""

    # === Case metadata ===
    case_type: CleanString | None = None
    """High-level type (e.g. 'CIVIL', 'CRIMINAL', 'FAMILY', 'WRIT')."""

    case_classification: CleanString | None = None
    """Detailed classification string."""

    case_status: CleanString | None = None
    """Case status text (e.g. 'FINAL', 'PENDING')."""

    date_status: date | None = None
    """Date of the most recent status change (caseStatusDate)."""

    closed: bool = False
    """Whether the case is closed."""

    court_level: CleanString | None = None
    """Court level string ('Supreme Court' or 'Court of Appeals')."""

    case_category: CleanString | None = None
    """Case category from C-Track (typically 'Appellate')."""

    # === Nested data ===
    entries: list[KyDocketEntry] = []
    """All docket entries on this case."""

    parties: list[KyParty] = []
    """All parties on this case (with nested attorneys)."""

    trial_courts: list[KyTrialCourt] = []
    """Originating / lower courts."""

    # === Source tracking ===
    source_url: str | None = None
    """Public case-detail URL on appellatepublic.kycourts.net."""

    source_entry_point: str | None = None
    """Entry point used to reach this docket (e.g. ``dockets_by_number``)."""


class KyDocument(ScrapedData):
    """A document attached to a docket entry on a Kentucky appellate case.

    Yielded as a separate top-level record so it joins back to the parent
    ``KyDocket`` via ``case_id`` / ``docket_number`` and to the specific
    docket entry via ``docket_entry_id``. Maps to CourtListener
    ``RECAPDocument``."""

    case_id: str
    """C-Track caseID — joins back to the parent KyDocket."""

    docket_number: str
    """Public case number this document belongs to."""

    court: str
    """CourtListener court id."""

    docket_entry_id: str | None = None
    """The docketEntryID this document hangs off (parentID)."""

    document_id: str
    """C-Track documentID (hash). Used in the download URL."""

    dms_document_id: CleanString | None = None
    """Numeric DMS identifier (less stable; documentID is preferred)."""

    document_name: CleanString | None = None
    document_description: CleanString | None = None

    parent_type: CleanString | None = None
    """The parent docket entry's docketEntryType."""

    parent_subtype: CleanString | None = None
    """The parent docket entry's docketEntrySubtype."""

    parent_date: date | None = None
    """The parent docket entry's filed date."""

    mime_type: CleanString | None = None
    """e.g. 'application/pdf'."""

    download_url: str | None = None
    """Public download URL for the file."""

    filepath_local: str | None = None
    """Filesystem path where the driver archived this document
    (CL ``RECAPDocument.filepath_local``)."""
