"""Data models for the Arkansas appellate courts scraper.

Supported courts:
- ark:       Arkansas Supreme Court    (caseinfo court name "STATE OF ARKANSAS SUPREME COURT")
- arkctapp:  Arkansas Court of Appeals (caseinfo court name "STATE OF ARKANSAS COURT OF APPEALS")
"""

from __future__ import annotations

from datetime import date

from jkent.common.data_models import ScrapedData

COURT_NAME_TO_ID: dict[str, str] = {
    "STATE OF ARKANSAS SUPREME COURT": "ark",
    "STATE OF ARKANSAS COURT OF APPEALS": "arkctapp",
}
"""Map from caseinfo's `courtName` field to the CourtListener court id."""

COURT_ID_TO_NAME: dict[str, str] = {v: k for k, v in COURT_NAME_TO_ID.items()}
"""Map from the CourtListener court id to caseinfo's `courtName` field."""


class ArDocketEntry(ScrapedData):
    """A single entry from the case's ``caseDockets`` array."""

    docket_seq_no: int | None = None
    docket_type: str | None = None
    """Site-internal type code (e.g. ``ACCV``, ``ACF49``, ``PA90``)."""

    description: str | None = None
    """Human-readable description (``docketDesc``)."""

    text: str | None = None
    """Freeform notes (``docketText``)."""

    date_filed: date | None = None

    entity_id: int | None = None
    entity_name: str | None = None
    """Filing party / counsel name when the API attaches one."""


class ArParty(ScrapedData):
    """A row from ``caseParticipants``.

    The site does not encode attorney-of-record relationships; counsel
    appear as separate rows with ``role`` = ``APPELLANT COUNSEL`` /
    ``APPELLEE COUNSEL``. This model preserves that flat structure.
    """

    seq_no: int | None = None
    name: str
    role: str
    """``partyType`` from the API (``APPELLANT``, ``APPELLEE``,
    ``APPELLANT COUNSEL``, ``LOWER COURT JUDGE``, etc.)."""

    entity_id: int | None = None
    aliases: list[str] = []


class ArMilestone(ScrapedData):
    """A briefing-track milestone (``caseMilestones[]``)."""

    milestone_code: str | None = None
    """Track grouping code (e.g. ``BRIEFING``)."""

    description: str | None = None
    """Step description (e.g. ``APPELLANT'S BRIEF``, ``REPLY BRIEF``)."""

    seq_no: int | None = None
    order_seq_no: int | None = None
    due_date: date | None = None
    changed_due_date: date | None = None
    filing_date: date | None = None


class ArDocument(ScrapedData):
    """A downloaded document from a docket entry.

    Yielded as a separate top-level record so it can be joined back to the
    parent ``ArDocket`` via ``docket_number``. The ``document_file_id`` doubles as
    the document's natural primary key — it is opaque, stable, and unique
    across the entire site.
    """

    docket_number: str
    """Public docket number this document belongs to (e.g. ``CV-26-294``)."""

    court_id: str
    """CourtListener court id: ``ark`` or ``arkctapp``."""

    document_file_id: str
    """Opaque site token; primary key for the document."""

    document_name: str | None = None
    description: str | None = None

    # === Parent docket entry ===
    # Identifies the specific ArDocketEntry this document hangs off of.
    # Join back to it via (docket_number, docket_seq_no); the description
    # and filing date are denormalized here so an ArDocument is legible
    # on its own without re-fetching the docket.
    docket_seq_no: int | None = None
    """``docketSeqNo`` of the parent docket entry — the per-case key for
    the ``ArDocketEntry`` this document belongs to."""

    docket_entry_description: str | None = None
    """``docketDesc`` of the parent docket entry (e.g. ``OPINION``)."""

    docket_entry_date_filed: date | None = None
    """``docketFilingDate`` of the parent docket entry."""

    upload_date: date | None = None
    download_url: str
    """Presigned S3 URL the bytes were fetched from. The presigned token
    expires ~10 minutes after issuance, so this is preserved for
    traceability rather than as a long-lived link."""

    local_path: str | None = None
    """Filesystem path where the driver archived this document."""


class ArDocket(ScrapedData):
    """A complete Arkansas appellate docket.

    Aggregates everything the case-detail endpoint
    (``GET /opad/api/cases/{caseId}``) returns. Empty arrays from the API
    (``caseEvents``, ``caseOffenses``, ``caseSentences``) are preserved as
    raw JSON so we don't silently drop data if the site starts populating
    them upstream.
    """

    # === Searchable fields ===
    docket_number: str
    """Public docket number (e.g. ``CR-26-228``, ``CV-26-294``,
    ``D-26-259``). Format: ``{TYPE}-{YY}-{SEQ}``."""

    court_id: str
    """CourtListener court id: ``ark`` (Supreme Court) or ``arkctapp``
    (Court of Appeals)."""

    date_filed: date | None = None
    case_name: str

    # === Case metadata ===
    case_title: str | None = None
    """Long form (``caseTitle``); often the same as ``case_name`` plus a
    ``NON-TRIAL`` / trial suffix."""

    case_type: str | None = None
    """e.g. ``CIVIL APPEAL CIRCUIT``, ``POST CONVICTION APPEAL``."""

    trial_desc: str | None = None
    """``caseTrialDesc`` — usually ``NON-TRIAL`` or absent."""

    status: str | None = None
    """``statusDesc`` — usually ``ACTIVE`` or absent on closed cases."""

    court_name: str
    """Full caseinfo court name; the ``court_id`` above is derived from it."""

    court_location: str | None = None
    """e.g. ``SUPREME COURT``."""

    sealed_flag: str | None = None
    """Raw ``caseSealed`` value (``"0"`` / ``"1"``). The "1" value does
    *not* hide the case from the public API — meaning is not documented
    upstream — so we preserve the raw value rather than coerce to a bool."""

    security_level: int | None = None
    """Raw ``caseSecurity`` value."""

    # === Nested data ===
    entries: list[ArDocketEntry] = []
    parties: list[ArParty] = []
    milestones: list[ArMilestone] = []

    raw_events: list[dict] = []
    """Passthrough of ``caseEvents``; empty in every appellate case
    observed but preserved if upstream starts populating it."""

    raw_offenses: list[dict] = []
    """Passthrough of ``caseOffenses``."""

    raw_sentences: list[dict] = []
    """Passthrough of ``caseSentences``."""

    source_url: str | None = None
    """The case-detail API URL used to build this record."""
