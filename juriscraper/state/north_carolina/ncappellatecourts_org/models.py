"""Data models for the North Carolina Appellate Courts scraper.

Two cooperating sites cover the NC Court of Appeals and Supreme Court:

- ``www.ncappellatecourts.org/search-results.php`` — eFiling document
  library (used as the date-range entry point).
- ``appellate.nccourts.org/dockets.php?…&pdf=1`` — rich HTML docket
  sheet (the primary record). Both ``nc`` and ``ncctapp`` cases share
  the same docket-sheet layout, so a single ``NCAppealsDocket`` model
  serves both courts.

Field names follow [`../../CL_MODELS.md`](../../CL_MODELS.md): the
CourtListener court-id string is ``court`` (not ``court_id``), the case
number is ``docket_number`` (not ``case_number``/``docket_id``), and
dates use the ``date_*`` prefix. ``CleanString``/``HarmonizedCaseName``
do the field-level cleaning.
"""

from __future__ import annotations

from datetime import date

from jkent.common.data_models import ScrapedData

from juriscraper.state.common_models import CleanString, HarmonizedCaseName

# CourtListener court IDs.
COURT_SC = "nc"
COURT_COA = "ncctapp"

COURT_IDS: dict[str, str] = {
    COURT_SC: "Supreme Court of North Carolina",
    COURT_COA: "North Carolina Court of Appeals",
}

# Site-internal numeric court id used in dockets.php?court=N
SITE_COURT_ID: dict[str, int] = {
    COURT_SC: 1,
    COURT_COA: 2,
}

# Reverse map for parsing the internal docket id ("1-…" / "2-…").
COURT_ID_FROM_SITE: dict[int, str] = {
    1: COURT_SC,
    2: COURT_COA,
}

# === Site constants ===
DOCKETS_BASE = "https://appellate.nccourts.org/dockets.php"
SEARCH_RESULTS_URL = "https://www.ncappellatecourts.org/search-results.php"
COURT_URL = "https://www.ncappellatecourts.org/"

PAGE_SIZE = 50  # search-results.php pages 50 cases at a time


class NCAppealsAttorney(ScrapedData):
    """An attorney appearance under a party block.

    Maps to CourtListener ``Attorney`` (+ ``AttorneyOrganization`` for
    the firm)."""

    name: CleanString
    """Full attorney name as displayed (e.g. ``Ms. Callie S. Thomas``)."""

    role: CleanString | None = None
    """Bracketed role tag if present (e.g. ``Primary Attorney``)."""

    title: CleanString | None = None
    """Free-text title line under the name (e.g. ``Assistant Appellate
    Defender``)."""

    firm: CleanString | None = None
    """Firm name pulled from the shared address block."""

    address: CleanString | None = None
    """Multi-line postal address from the shared address block."""

    phone: CleanString | None = None
    """Phone number from the shared address block."""


class NCAppealsParty(ScrapedData):
    """A party row from the case-detail Parties table.

    Maps to CourtListener ``Party`` (+ ``PartyType`` for the role on
    this docket)."""

    name: CleanString
    """Party name as displayed (e.g. ``Sings, Janice Elaine``)."""

    role: CleanString | None = None
    """Role text (e.g. ``Defendant-Appellant``, ``Plaintiff-Appellee``)
    — CL ``PartyType.name``."""

    attorneys: list[NCAppealsAttorney] = []
    """Attorneys representing this party (best-effort grouping; the
    site shares one address block per party, so all attorneys under a
    party share ``firm`` / ``address`` / ``phone``)."""


class NCAppealsDocketEntry(ScrapedData):
    """A row from the Documents (register-of-actions) table.

    Each row pairs a structured "Documents" table cell with a free-text
    expansion below the table that adds the filer / for-party / order
    text. Both are merged into this model. Maps loosely to CourtListener
    ``DocketEntry``.
    """

    number: int
    """Ordinal index as printed (``(1)``, ``(2)``, …) — CL
    ``DocketEntry.entry_number``."""

    document_type: CleanString
    """Document type label (e.g. ``RECORD``, ``M-SEAL``,
    ``NOTICE OF APPEARANCE``)."""

    date_received: date | None = None
    """``Date Recvd`` column."""

    cert_of_service: date | None = None
    """``Cert of Service`` column."""

    rec_brf_due: CleanString | None = None
    """``Rec/Brf Due`` column (free text — sometimes a date, sometimes
    a status keyword)."""

    response_due: CleanString | None = None
    """``Resp. Due`` column."""

    response_received: date | None = None
    """``Resp. Recvd`` column."""

    mailed_out: date | None = None
    """``Mailed Out`` column."""

    ruling: CleanString | None = None
    """``Ruling`` column (e.g. ``Allowed``, ``Denied``)."""

    ruling_date: date | None = None
    """``Ruling Date`` column."""

    filed_at: CleanString | None = None
    """Filed timestamp as printed in the free-text expansion (e.g.
    ``04-02-2026 @ 09:27:38``)."""

    filed_for: CleanString | None = None
    """``FOR:`` line (e.g. ``Defendant-Appellant Sings, Janice
    Elaine``)."""

    filed_by: CleanString | None = None
    """``BY:`` line (attorney + firm, joined with a space)."""

    order_text: CleanString | None = None
    """Body of the ``<blockquote>`` that holds the issued order, when
    the entry was ruled on."""


class NCAppealsLowerCourt(ScrapedData):
    """One Lower Court Number block from the docket sheet.

    The docket sheet may list multiple lower-court entries per case;
    most cases have exactly one. Maps to CourtListener
    ``OriginatingCourtInformation`` / ``TrialCourtData``.
    """

    location: CleanString | None = None
    """County or court-of-origin (e.g. ``Mecklenburg (26)``)."""

    judge: CleanString | None = None
    """Lower-court judge's name (CL ``assigned_to_str``)."""

    docket_number: CleanString | None = None
    """Trial-court docket number (e.g. ``21CR004309-590``) — CL
    ``OriginatingCourtInformation.docket_number``."""


class NCAppealsDocument(ScrapedData):
    """An e-filed document associated with a case.

    Pulled from the per-case page at
    ``ncappellatecourts.org/search-results.php?sDocketSearch=…&exact=1``.
    The page gives one row per filing; the docket-sheet pages on
    ``appellate.nccourts.org`` carry the structured register-of-actions
    (with rulings + dates) but not the document URLs, so the two are
    yielded as parallel records and joined downstream by
    ``docket_number`` + ``date_filed`` + ``document_type``. Maps to
    CourtListener ``RECAPDocument``.

    Sealed filings expose their type / sub-type / filer / date but
    have no downloadable URL. Those rows are still yielded with
    ``is_sealed=True`` so the join sees them, just with
    ``document_id`` and ``document_url`` left empty.
    """

    docket_number: str
    """Visible docket number (joins back to ``NCAppealsDocket``)."""

    court: str
    """CourtListener court id (``nc`` or ``ncctapp``)."""

    document_type: CleanString
    """Top-level document type (e.g. ``Record``, ``Motion``,
    ``Petition``, ``Response``, ``Notice``, ``Appellant Brief``,
    ``Appellee Brief``, ``Other Brief``, ``Notice of Appeal``)."""

    document_subtype: CleanString | None = None
    """Site sub-type code shown in parentheses (e.g. ``m-ext-pr``,
    ``phc``, ``record (printed)``, ``notice of appearance``)."""

    filer: CleanString | None = None
    """Display name of the filing party / attorney as printed on the
    page (after ``Filed By:``)."""

    date_filed: date | None = None
    """Date the document was e-filed."""

    is_sealed: bool = False
    """True if the row was rendered with the ``(Sealed)`` marker (no
    download URL is available in that case)."""

    document_id: CleanString | None = None
    """Site-internal numeric id from ``show-file.php?document_id={id}``
    — empty for sealed filings."""

    document_url: str | None = None
    """Absolute URL of the PDF — empty for sealed filings."""

    local_path: str | None = None
    """Filesystem path the driver archived the file to (CL
    ``filepath_local``)."""


class NCAppealsDocket(ScrapedData):
    """A complete appellate docket sheet from appellate.nccourts.org.

    Maps to CourtListener ``Docket`` (+ its per-court side tables)."""

    # ── Searchable / required ──────────────────────────────────────────
    docket_number: str
    """User-facing docket number (e.g. ``26-310``, ``P26-334``,
    ``15P26``)."""

    court: str
    """CourtListener court id: ``nc`` or ``ncctapp``."""

    case_name: HarmonizedCaseName
    """Caption / long title."""

    date_filed: date | None = None
    """File Date from the docket-information block."""

    # ── Header fields ──────────────────────────────────────────────────
    case_type: CleanString | None = None
    """Free-text case type (e.g. ``Criminal (Felony Other)``)."""

    case_closed: bool | None = None
    """True if the docket sheet flags the case as closed."""

    date_closed: date | None = None
    """Close date when ``case_closed`` is True (``Case Close Date``)."""

    mediation: bool | None = None
    """Mediation flag from the docket-info block."""

    docket_date: date | None = None
    """``Docket Date`` from the docket-information block."""

    file_time: CleanString | None = None
    """``File Time`` (raw text)."""

    acquire_date: date | None = None
    """``Acquire Date`` from the docket-information block."""

    bond_collection: bool | None = None
    docket_fee: bool | None = None
    pauper: bool | None = None
    print_deposit: bool | None = None
    state_appeals: bool | None = None
    """Boolean flags from the second docket-info row."""

    as_of_date: date | None = None
    """``As of`` date the docket sheet was rendered (the live ledger's
    snapshot timestamp). Useful for staleness tracking."""

    # ── History block ──────────────────────────────────────────────────
    venue: CleanString | None = None
    """Origin venue (e.g. ``Mecklenburg (26)``)."""

    heard_in: CleanString | None = None
    """Lower court level (e.g. ``Superior Court``)."""

    previous_venue: CleanString | None = None
    """``Previous Venue`` (Supreme Court only — populated when the
    case came up from the Court of Appeals)."""

    to_sc: CleanString | None = None
    """Cross-reference: SC docket the case progressed to (when this
    is a COA case)."""

    from_sc: CleanString | None = None
    """Cross-reference: SC docket the case came from."""

    # ── Lower court ────────────────────────────────────────────────────
    lower_courts: list[NCAppealsLowerCourt] = []
    """Lower-court number blocks (typically one)."""

    # ── Aggregates ─────────────────────────────────────────────────────
    parties: list[NCAppealsParty] = []
    """Parties with their attorneys."""

    entries: list[NCAppealsDocketEntry] = []
    """Register-of-actions rows."""

    # ── Provenance ─────────────────────────────────────────────────────
    source_url: str | None = None
    """The docket-sheet URL the data was fetched from."""

    source_entry_point: str | None = None
    """Entry point used to reach this docket (e.g. ``dockets_by_number``)."""
