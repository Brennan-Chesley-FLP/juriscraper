"""Data models for the Kentucky appellate courts scraper.

Source: https://appellatepublic.kycourts.net (Thomson Reuters
"C-Track Public Access" — distinct from the "TR Portal" product handled
by ``juriscraper.sd.state.common.tr``).
"""

from __future__ import annotations

from datetime import date

from jkent.common.data_models import ScrapedData

API_BASE_URL = "https://appellatepublic.kycourts.net/api/api/v1"
PORTAL_URL = "https://appellatepublic.kycourts.net"

# Site court name (from caseHeader.court) -> CourtListener court_id
SITE_COURT_TO_ID: dict[str, str] = {
    "Kentucky Supreme Court": "ky",
    "Kentucky Court of Appeals": "kyctapp",
}

# CourtListener court_id -> case-number prefix component (e.g. "SC", "CA")
COURT_CASE_PREFIX: dict[str, str] = {
    "ky": "SC",
    "kyctapp": "CA",
}

# CourtListener court_id -> human-readable name
COURT_NAMES: dict[str, str] = {
    "ky": "Kentucky Supreme Court",
    "kyctapp": "Kentucky Court of Appeals",
}


class KyDocketEntry(ScrapedData):
    """A single docket entry row on a Kentucky appellate case."""

    docket_entry_id: str
    """C-Track docketEntryID (hash). Stable identifier for the entry."""

    date_filed: date | None = None
    """When the entry was filed."""

    entry_type: str | None = None
    """docketEntryType — broad category (e.g. 'FINALITY', 'DISPOSITION - OPINION AND ORDER')."""

    entry_subtype: str | None = None
    """docketEntrySubtype — narrower classification."""

    description: str | None = None
    """docketEntryDescription — human-readable label for this entry."""

    submitted_by: str | None = None
    """Filer / submitter, when present."""

    comments: str | None = None
    """Free-text comments from customFields.Comments."""

    is_opinion: bool = False
    """The 'opinion' flag set by C-Track on dispositional opinion entries."""

    has_documents: bool = False
    """Whether the entry has at least one attached document available
    via /publicaccessdocuments."""


class KyDocket(ScrapedData):
    """A complete Kentucky appellate docket."""

    # === Searchable fields ===
    case_id: str
    """C-Track caseID (hash). Primary key for the case."""

    case_number: str
    """Public case number, e.g. '2026-SC-0005' or '2024-CA-0134'."""

    court_id: str
    """CourtListener court_id ('ky' or 'kyctapp')."""

    date_filed: date | None = None
    """When the case was filed in the appellate court."""

    # === Required fields ===
    case_name: str
    """Case caption (shortTitle from C-Track)."""

    # === Case metadata ===
    case_type: str | None = None
    """High-level type (e.g. 'CIVIL', 'CRIMINAL', 'FAMILY', 'WRIT')."""

    case_classification: str | None = None
    """Detailed classification string."""

    case_status: str | None = None
    """Case status text (e.g. 'FINAL', 'PENDING')."""

    status_date: date | None = None
    """Date of the most recent status change."""

    closed: bool = False
    """Whether the case is closed."""

    court_level: str | None = None
    """Court level string from C-Track ('Supreme Court' or 'Court of Appeals')."""

    case_category: str | None = None
    """Case category from C-Track (typically 'Appellate')."""

    full_title: str | None = None
    """Long-form caption when available (often null)."""

    # === Nested data ===
    entries: list[KyDocketEntry] = []
    """All docket entries on this case."""

    parties: list[dict] = []
    """List of parties. Each entry has keys: name, role, status,
    pro_se, address, attorneys (list of {name, address, bar_number})."""

    trial_courts: list[dict] = []
    """Originating courts. Each entry has keys: name, case_number,
    case_title."""

    # === Source tracking ===
    source_url: str | None = None
    """Public case detail URL on appellatepublic.kycourts.net."""


class KyDocument(ScrapedData):
    """A document attached to a docket entry on a Kentucky appellate case.

    Yielded as a separate top-level record so it joins back to the parent
    KyDocket via ``case_id`` and to the specific docket entry via
    ``docket_entry_id``.
    """

    case_id: str
    """C-Track caseID — joins back to the parent KyDocket."""

    case_number: str
    """Public case number this document belongs to."""

    court_id: str
    """CourtListener court_id."""

    docket_entry_id: str | None = None
    """The docketEntryID this document hangs off (parentID)."""

    document_id: str
    """C-Track documentID (hash). Used in the download URL."""

    dms_document_id: str | None = None
    """Numeric DMS identifier (less stable; documentID is preferred)."""

    document_name: str | None = None
    document_description: str | None = None

    parent_type: str | None = None
    """The parent docket entry's docketEntryType."""

    parent_subtype: str | None = None
    """The parent docket entry's docketEntrySubtype."""

    parent_date: date | None = None
    """The parent docket entry's filed date."""

    mime_type: str | None = None
    """e.g. 'application/pdf'."""

    download_url: str | None = None
    local_path: str | None = None
    """Filesystem path where the driver archived this document."""
