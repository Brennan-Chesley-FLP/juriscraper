"""Data models for the Tennessee Public Case History scraper.

This site (``pch.tncourts.gov``) is an ASP.NET WebForms C-Track deployment
that publishes structured appellate docket data — case overview, milestones,
parties, the case-history register of actions, and record information — as
plain HTML tables. The models below mirror the on-page structure so a single
``TnDocket`` instance carries everything displayed on a case-detail page.

One site, three courts, distinguished by the case-number suffix:

- ``tenn``         — Tennessee Supreme Court              (suffix ``SC``)
- ``tennctapp``    — Tennessee Court of Appeals           (suffix ``COA``)
- ``tenncrimapp``  — Tennessee Court of Criminal Appeals  (suffix ``CCA``)

Field names follow [`../../CL_MODELS.md`](../../CL_MODELS.md): the
CourtListener court-id string is ``court`` (not ``court_id``), the docket
number is ``docket_number`` (not ``case_number``), and dates use the
``date_*`` prefix.
"""

from __future__ import annotations

from datetime import date

from jkent.common.data_models import ScrapedData

from juriscraper.state.common_models import CleanString, HarmonizedCaseName

# Site code (third dash-separated segment of the docket number) → CL court id.
SUFFIX_TO_COURT: dict[str, str] = {
    "SC": "tenn",
    "COA": "tennctapp",
    "CCA": "tenncrimapp",
}

COURT_NAMES: dict[str, str] = {
    "tenn": "Tennessee Supreme Court",
    "tennctapp": "Tennessee Court of Appeals",
    "tenncrimapp": "Tennessee Court of Criminal Appeals",
}


# =========================================================================
# Data models
# =========================================================================


class TnMilestone(ScrapedData):
    """A row from the Case Milestones table.

    Standard descriptions: Application Filed, Application Disposition,
    Record Filed, Appellant(s)/Appellee(s) Briefing Complete, Oral
    Argument/Submission, Decision Date, Decision Type, Disposition,
    Panel, Closed Date.
    """

    description: CleanString
    """Milestone label verbatim from the Description column."""
    date_milestone: date | None = None
    """Date column value, when the milestone carries a date."""


class TnParty(ScrapedData):
    """A row from the Parties table on the case-detail page.

    Maps to CourtListener ``Party`` (+ ``PartyType`` for the role)."""

    name: CleanString
    """Party name verbatim from the Names column."""
    role: CleanString | None = None
    """Role on appeal (CL ``PartyType.name``): ``Appellant`` /
    ``Appellee`` / etc."""
    counsel: CleanString | None = None
    """Counsel of record text from the Counsel column."""


class TnRecordEntry(ScrapedData):
    """A row from the Record Information table on the case-detail page."""

    volume_type: CleanString
    """e.g. ``Technical Record``, ``Transcript of Evidence``,
    ``Exhibits``."""
    volumes: CleanString | None = None
    """Number of volumes, as text."""
    record_type: CleanString | None = None
    """e.g. ``Original``, ``Supplemental``."""


class TnDocketEntry(ScrapedData):
    """A row from the Case History table (the docket / register of actions).

    Maps loosely to CourtListener ``DocketEntry``."""

    date_filed: date | None = None
    """Date column value for the event."""
    event: CleanString
    """Event description from the Event column."""
    filer: CleanString | None = None
    """Filer name from the Filer column, if any."""
    postback_target: str | None = None
    """ASP.NET ``__doPostBack`` argument for the attached PDF, if one is
    present (e.g. ``ListView10$ctrl2$ListView12$ctrl0$LinkButton1``) — not
    a real URL. The PDF body is retrieved by re-POSTing the case-detail
    page with this value as ``__EVENTTARGET``."""


class TnDocument(ScrapedData):
    """An archived PDF from a docket-history row.

    Yielded as a separate top-level record so it can be joined back to its
    parent docket via ``docket_number`` and to the originating row via
    ``entry_index``. Maps to CourtListener ``RECAPDocument``.
    """

    docket_number: str
    """Full appeal number (e.g. ``M2013-02744-SC-R11-CD``)."""

    court: str
    """One of ``tenn``, ``tennctapp``, ``tenncrimapp``."""

    entry_index: int | None = None
    """Index of the docket-history row this document came from (0-based)."""

    description: CleanString | None = None
    """Event description from the docket-history row this PDF belongs to."""

    source_url: str | None = None
    """The case-detail URL the PDF was downloaded from (the postback target
    is identified by ``__EVENTTARGET``, but the URL itself is the case
    detail page)."""

    filepath_local: str | None = None
    """Filesystem path where the driver archived this document."""


class TnDocket(ScrapedData):
    """A complete appellate case docket from pch.tncourts.gov.

    A single sequence-number search returns rows from any combination of the
    three Tennessee appellate courts; ``court`` is derived from the third
    dash-separated segment of ``docket_number``. Maps to CourtListener
    ``Docket`` (+ its per-court side tables).
    """

    # === Identity ===
    docket_number: str
    """Full appeal number, e.g. ``M2013-02744-SC-R11-CD``."""

    court: str
    """``tenn``, ``tennctapp``, or ``tenncrimapp`` — derived from the
    ``SC``/``COA``/``CCA`` segment of the docket number."""

    case_name: HarmonizedCaseName
    """Case style/caption, e.g. ``State of Tennessee v. Michael
    Crockett``."""

    date_filed: date | None = None
    """Application/Record-filed date from the Case Milestones table, when
    available."""

    internal_case_id: str | None = None
    """C-Track MastCastID (numeric) — the ``id=`` URL parameter on
    ``CaseDetails.aspx``."""

    # === Case Overview fields ===
    intermediate_docket_number: CleanString | None = None
    """The ``Inter. Case No.`` field — the underlying intermediate-court
    docket number when this is a Supreme Court application/review."""

    trial_court: CleanString | None = None
    """Trial court name and division, e.g. ``Rutherford County Circuit
    Court (CIVIL)`` (CL ``OriginatingCourtInformation``)."""

    assigned_to_str: CleanString | None = None
    """Trial-court judge name as ``Last, First`` (CL ``assigned_to_str``
    on the originating court)."""

    trial_court_docket_number: CleanString | None = None
    """Trial-court case number, e.g. ``F70116``."""

    # === Closure / disposition ===
    date_closed: date | None = None
    """``Closed Date`` milestone, if present."""

    date_decision: date | None = None
    """``Decision Date`` milestone, if present."""

    disposition: CleanString | None = None
    """``Disposition`` milestone value, if present."""

    decision_type: CleanString | None = None
    """``Decision Type`` milestone value, if present."""

    panel_str: CleanString | None = None
    """``Panel`` milestone value, if present (CL ``panel_str``)."""

    # === Nested data ===
    milestones: list[TnMilestone] = []
    parties: list[TnParty] = []
    entries: list[TnDocketEntry] = []
    record_info: list[TnRecordEntry] = []

    # === Provenance ===
    source_url: str | None = None
    """URL of the case-detail page this docket was scraped from."""

    source_entry_point: str | None = None
    """Entry point used to reach this docket (e.g.
    ``dockets_by_number``)."""


# =========================================================================
# Site constants
# =========================================================================

BASE_URL: str = "https://pch.tncourts.gov"
INDEX_URL: str = f"{BASE_URL}/index.aspx"
SEARCH_RESULTS_URL: str = f"{BASE_URL}/SearchResults.aspx"
CASE_DETAILS_URL: str = f"{BASE_URL}/CaseDetails.aspx"
