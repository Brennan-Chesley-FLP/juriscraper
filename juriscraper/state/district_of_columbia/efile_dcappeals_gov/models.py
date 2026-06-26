"""Data models for the DC Court of Appeals scraper.

The site's events table maps directly onto our standard
``ScrapedData`` shape; nothing about DC's payload requires a
deviation from the SC model layout. The party shape is the one
substantive difference — DC's table has 6 columns (Role, Name, IFP,
Attorneys, Arguing Attorney, E-Filer) versus SC's 4 — so we model
each party flag explicitly rather than collapsing them.

Field names track CourtListener (see ``CL_MODELS.md``): ``docket_number``,
``court`` (a CourtListener court-id string), and ``date_*`` for dates.
"""

from __future__ import annotations

from datetime import date

from jkent.common.data_models import ScrapedData

COURT_IDS: dict[str, str] = {
    "dc": "District of Columbia Court of Appeals",
}
"""CourtListener court IDs scraped by this scraper.

DC has a single appellate court, so this dict has a single entry.
Kept for human reference and for parity with multi-court siblings.
"""


class DCAppDocketEntry(ScrapedData):
    """A row of the Events table on a DC Court of Appeals case page.

    The C-Track Events table is the docket / register of actions for
    the case; each row is one filing or court-side event. Maps onto
    CourtListener ``DocketEntry``.
    """

    date_filed: date | None = None
    """Event Date column (``MM/DD/YYYY``)."""

    status: str | None = None
    """Status column. Typically ``Filed``; other observed: ``Dismissed``."""

    description: str
    """Description column — free-text label of the event."""

    result: str | None = None
    """Result column. Usually empty; populated on terminal events."""

    event_id: str | None = None
    """C-Track ``deID`` extracted from the document-icon ``name`` attribute.

    Set only when the row exposes a ``<img class="documentLink">``
    icon. Used as the second positional parameter of the DWR
    ``getViewDocumentLinks`` call.
    """

    document_link_flag: str | None = None
    """First positional parameter of the DWR document-links call.

    Encoded in the ``documentLink`` icon's ``name`` attribute as
    ``"{flag}:{deID}:{csIID}"`` — observed value is always ``"50"`` in
    samples so far, but kept per-entry in case it varies.
    """

    has_documents: bool = False
    """True iff the event row carried a ``documentLink`` icon."""


class DCAppParty(ScrapedData):
    """A row of the Party Information table.

    Captures the 6-column shape unique to DC: Appellate Role, Party
    Name, IFP flag, Attorneys, Arguing Attorney, E-Filer flag. Maps onto
    CourtListener ``Party`` + ``PartyType`` (role) + ``Attorney``.
    """

    role: str
    """Appellate Role: ``Appellant``, ``Appellee``, ``Petitioner``,
    ``Respondent``, ``Intervenor``, ``Real Party in Interest``."""

    name: str
    """Party Name."""

    ifp: bool | None = None
    """In forma pauperis flag (Y/N column). ``None`` if the cell was empty."""

    attorneys: list[str] = []
    """Attorney(s) cell — one entry per attorney, or a single
    ``"Pro Se"`` sentinel."""

    arguing_attorney: str | None = None
    """Arguing Attorney cell — usually empty until argument is scheduled."""

    e_filer: bool | None = None
    """E-Filer flag (Y/N column)."""


class DCAppDocket(ScrapedData):
    """A complete DC Court of Appeals case docket.

    Maps onto CourtListener ``Docket``.
    """

    # === Searchable / identity fields ===
    docket_number: str
    """Appellate docket number (e.g. ``26-CV-0339``)."""

    court: str
    """CourtListener court ID. Always ``"dc"`` for this scraper."""

    site_case_id: str
    """Site-internal ``csIID`` as a string. Stable join key for
    ``DCAppDocument`` and for re-fetching the case page."""

    date_filed: date | None = None
    """Filed Date from the case-info table."""

    case_name: str
    """Short Caption from the case-info table."""

    # === Case metadata ===
    classification: str | None = None
    """Combined ``Group - Type - Subtype`` from the case-info table."""

    case_status: str | None = None
    """Case Status field (e.g. ``Pending``, ``Decided/Dismissed``)."""

    lower_court_case_number: str | None = None
    """Superior Court or Agency Case Number (the lower-court docket)."""

    date_opening_event: date | None = None
    date_record_completed: date | None = None
    date_briefs_completed: date | None = None
    date_argued: date | None = None
    """Argued/Submitted date (CL ``date_argued``)."""
    date_mandate_issued: date | None = None

    disposition: str | None = None
    """Disposition free-text field. Usually empty before disposition."""

    next_scheduled_action: str | None = None
    """Next Scheduled Action free-text field."""

    post_decision_matter_pending: str | None = None
    """Post-Decision Matter Pending free-text field."""

    costs_waived: bool = False
    """Whether the Costs Waived flag-row is present in the case info."""

    # === Nested data ===
    parties: list[DCAppParty] = []
    docket_entries: list[DCAppDocketEntry] = []

    # === Source tracking ===
    source_url: str | None = None
    """URL of the case-detail page used for this record."""


class DCAppDocument(ScrapedData):
    """A single PDF attached to a DC Court of Appeals docket entry.

    Maps onto CourtListener ``RECAPDocument``. Yielded as a top-level
    record so consumers can join back to the parent ``DCAppDocket`` via
    ``(docket_number, event_id)`` or to a specific document via
    ``document_number``.
    """

    docket_number: str
    """Parent appellate docket number."""

    court: str
    """CourtListener court ID — ``"dc"``."""

    event_id: str
    """C-Track ``deID`` of the parent docket entry."""

    document_number: str
    """C-Track ``documentID`` — the stable key for the file itself
    (CL ``document_number``)."""

    url: str
    """Full URL the driver fetched (``/document/view.do?...``)."""

    description: str
    """Anchor text from the DWR reply, e.g. ``"Briefing Order"``."""

    filepath_local: str | None = None
    """Filesystem path the archive driver wrote the file to."""
