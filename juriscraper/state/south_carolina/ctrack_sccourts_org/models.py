"""Pydantic models for the South Carolina C-Track appellate scraper.

Covers the SC Supreme Court (`sc`) and SC Court of Appeals (`scctapp`),
both served from a single C-Track install at ctrack.sccourts.org.

Field names track CourtListener (see ``CL_MODELS.md``): ``docket_number``,
``court`` (a CourtListener court-id string), and ``date_*`` for dates.
"""

from __future__ import annotations

from datetime import date

from jkent.common.data_models import ScrapedData

# CourtListener IDs to display names. Documentation only — the scraper
# resolves the court from the per-case "Court:" field text rather than
# from a site-wide identifier mapping.
COURT_IDS: dict[str, str] = {
    "sc": "Supreme Court of South Carolina",
    "scctapp": "Court of Appeals of South Carolina",
}

# Internal C-Track court IDs as seen on the form's `courtID` select.
# Used to narrow a search to a single court when the seeded court set is
# a single CourtListener id.
SITE_COURT_ID_BY_COURT: dict[str, int] = {
    "sc": 10001,
    "scctapp": 10002,
}


class SCAppDocument(ScrapedData):
    """A downloadable document attached to a docket event.

    Maps onto CourtListener ``RECAPDocument``. Yielded as a top-level
    record alongside the parent ``SCAppDocket`` so the pipeline can join
    on (``docket_number``, ``event_id``). Populated by calling the DWR
    ``AJAX.getViewDocumentLinks`` endpoint once per ``event_id`` and then
    archiving each PDF link.
    """

    docket_number: str
    """Public appellate case number of the parent docket — join key."""

    court: str
    """CourtListener court ID of the parent docket — `sc` or `scctapp`."""

    event_id: str
    """Docket event (`deID`) this document belongs to — join key into
    the parent docket's ``docket_entries`` list."""

    document_number: str
    """The `documentID` query parameter from the download URL.
    Stable site identifier for the file (CL ``document_number``)."""

    url: str
    """Absolute URL of the document on ctrack.sccourts.org."""

    description: str
    """Display label as rendered in the document-link popup,
    e.g. "Cover Letter for Filing Fee - Receipt"."""

    filepath_local: str | None = None
    """Filesystem path after the kent driver archives the file."""


class SCAppDocketEntry(ScrapedData):
    """One row of the case-detail "Event Information" table.

    Maps onto CourtListener ``DocketEntry``.
    """

    date_filed: date | None = None
    """Filed date for this docket event."""

    description: str
    """Event description, e.g. "Notice of Appeal (Civil) - Initial"."""

    event_id: str | None = None
    """Internal C-Track docket-event ID (the `deID` value).

    Present whenever the row has an attached document icon. The ID is
    the join key into the corresponding ``SCAppDocument`` records.
    """

    has_documents: bool = False
    """True if the row had a `documentLink` icon (single or multi)."""


class SCAppParty(ScrapedData):
    """One row of the case-detail "Party Information" table.

    Maps onto CourtListener ``Party`` + ``PartyType`` (role) +
    ``Attorney``.
    """

    role: str
    """Appellate role, e.g. "Appellant", "Respondent", "Petitioner"."""

    name: str
    """Party name as displayed."""

    is_former: bool = False
    """True when the "Former" column is "Y" — party no longer active."""

    attorneys: list[str] = []
    """Attorney names. Single value `["Self Represented"]` for pro-se parties."""


class SCAppDocket(ScrapedData):
    """A complete South Carolina appellate case record.

    Maps onto CourtListener ``Docket``.
    """

    # === Identity ===
    docket_number: str
    """Public appellate case number, e.g. "2026-000911"."""

    court: str
    """CourtListener court ID — `sc` or `scctapp`."""

    site_case_id: str
    """C-Track internal case ID (`csIID`) — used in the source URL."""

    # === Caption ===
    case_name: str
    """Short title, e.g. "Charity Lynn Miller v. James S. Blanton"."""

    case_name_full: str | None = None
    """Long-form caption with party-role labels, when present."""

    # === Classification ===
    classification: str | None = None
    """Combined Group - Type - Subtype string, e.g. "Appeal - Common Pleas - Other"."""

    case_status: str | None = None
    """Current status, e.g. "Pending", "Decision Filed", "Remittitur"."""

    consolidated: str | None = None
    """Free-text list of consolidated case numbers, when present."""

    # === Dates ===
    date_filed: date | None = None
    """Filed date for the appellate case."""

    date_argued: date | None = None
    """Scheduled oral-argument date, when set (CL ``date_argued``)."""

    date_disposed: date | None = None
    """Date the disposition was filed."""

    disposition_type: str | None = None
    """Disposition type, e.g. "Order", "Opinion"."""

    date_remittitur: date | None = None
    """Date remittitur was issued."""

    # === Lower court ===
    appeal_from_str: str | None = None
    """Lower-court / tribunal name with embedded case number, as a raw
    string (CL ``appeal_from_str``),
    e.g. "Spartanburg (2022CP4200573)"."""

    # === Nested ===
    parties: list[SCAppParty] = []

    docket_entries: list[SCAppDocketEntry] = []
    """Docket events in display order (descending by default)."""

    # === Provenance ===
    source_url: str | None = None
    """Canonical case-detail URL for re-fetch."""
