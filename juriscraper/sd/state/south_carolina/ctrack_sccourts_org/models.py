"""Pydantic models for the South Carolina C-Track appellate scraper.

Covers the SC Supreme Court (`sc`) and SC Court of Appeals (`scctapp`),
both served from a single C-Track install at ctrack.sccourts.org.
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
# Useful when narrowing a search to a single court.
SITE_COURT_ID_BY_COURTLISTENER_ID: dict[str, int] = {
    "sc": 10001,
    "scctapp": 10002,
}


class SCAppDocument(ScrapedData):
    """A downloadable document attached to a docket event.

    Yielded as a top-level record alongside the parent ``SCAppDocket``
    so the data pipeline can join on (``docket_id``, ``event_id``).
    Populated by calling the DWR ``AJAX.getViewDocumentLinks`` endpoint
    once per ``event_id`` and then archiving each PDF link.
    """

    docket_id: str
    """Public appellate case number of the parent docket — join key."""

    court_id: str
    """CourtListener court ID of the parent docket — `sc` or `scctapp`."""

    event_id: str
    """Docket event (`deID`) this document belongs to — join key into
    the parent docket's ``entries`` list."""

    document_id: str
    """The `documentID` query parameter from the download URL.
    Stable site identifier for the file."""

    download_url: str
    """Absolute URL of the document on ctrack.sccourts.org."""

    label: str
    """Display label as rendered in the document-link popup,
    e.g. "Cover Letter for Filing Fee - Receipt"."""

    local_path: str | None = None
    """Filesystem path after the kent driver archives the file."""


class SCAppDocketEntry(ScrapedData):
    """One row of the case-detail "Event Information" table."""

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
    """One row of the case-detail "Party Information" table."""

    role: str
    """Appellate role, e.g. "Appellant", "Respondent", "Petitioner"."""

    name: str
    """Party name as displayed."""

    is_former: bool = False
    """True when the "Former" column is "Y" — party no longer active."""

    attorneys: list[str] = []
    """Attorney names. Single value `["Self Represented"]` for pro-se parties."""


class SCAppDocket(ScrapedData):
    """A complete South Carolina appellate case record."""

    # === Identity ===
    docket_id: str
    """Public appellate case number, e.g. "2026-000911"."""

    court_id: str
    """CourtListener court ID — `sc` or `scctapp`."""

    site_case_id: str
    """C-Track internal case ID (`csIID`) — used in the source URL."""

    # === Caption ===
    case_name: str
    """Short title, e.g. "Charity Lynn Miller v. James S. Blanton"."""

    full_title: str | None = None
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

    oral_argument_date: date | None = None
    """Scheduled oral-argument date, when set."""

    disposition_date: date | None = None
    """Date the disposition was filed."""

    disposition_type: str | None = None
    """Disposition type, e.g. "Order", "Opinion"."""

    remittitur_date: date | None = None
    """Date remittitur was issued."""

    # === Lower court ===
    lower_court: str | None = None
    """Lower-court / tribunal name with embedded case number,
    e.g. "Spartanburg (2022CP4200573)"."""

    # === Nested ===
    parties: list[SCAppParty] = []

    entries: list[SCAppDocketEntry] = []
    """Docket events in display order (descending by default)."""

    # === Provenance ===
    source_url: str | None = None
    """Canonical case-detail URL for re-fetch."""
