"""Data models for the Alaska appellate courts scraper.

Records map onto CourtListener's ``Docket`` graph (see ``CL_MODELS.md``);
field names follow CL where a clean 1:1 exists (``docket_number``,
``court``, ``case_name_full``, ``DocketEntry.entry_number`` /
``description`` / ``date_filed``) and stay faithful to the Alaska CMS
otherwise.

Supported courts:
- ``ak``: Alaska Supreme Court (case numbers ``S#####``)
- ``akctapp``: Alaska Court of Appeals (case numbers ``A#####``)
"""

from __future__ import annotations

from datetime import date

from jkent.common.data_models import ScrapedData


class AkOpinion(ScrapedData):
    """An opinion row from the Case Summary page."""

    number: str | None = None
    """The opinion's number/ordinal as shown in the Opinions table."""
    opinion_type: str | None = None
    """E.g. ``Opinion``, ``Order``, ``Memorandum``."""
    decision: str | None = None
    """Disposition text (e.g. ``Affirmed``)."""
    opinion_date: date | None = None
    citation: str | None = None
    document_url: str | None = None
    """URL the opinion PDF was (or would be) downloaded from."""
    local_path: str | None = None
    """Filesystem path where the driver archived the opinion, if available."""


class AkLowerCourtInfo(ScrapedData):
    """Lower court / agency row from Case Summary (maps to CL
    ``OriginatingCourtInformation`` / ``TrialCourtData``)."""

    docket_number: str | None = None
    """Lower-court case number."""
    judgment_date: date | None = None
    distribution_date: date | None = None
    court_or_agency: str | None = None
    """Name of the lower court or agency as shown on the page."""
    judge_str: str | None = None
    """Lower-court judge, as a raw string."""


class AkRelatedCase(ScrapedData):
    """A related appellate case from Case Summary."""

    docket_number: str | None = None
    case_name: str | None = None
    case_type: str | None = None
    relationship: str | None = None
    status: str | None = None
    internal_id: str | None = None
    """Encrypted ``q`` token from the related case's URL."""


class AkAttorney(ScrapedData):
    """An attorney representing a party (maps to CL ``Attorney``)."""

    name: str | None = None
    contact_raw: str | None = None
    """Raw address block, newlines collapsed to ``, ``."""
    phone: str | None = None


class AkParty(ScrapedData):
    """A participant and their attorneys (maps to CL ``Party`` /
    ``PartyType``).

    A single party can be represented by multiple attorneys (e.g.
    co-counsel from the same firm), each rendered as a separate
    ``<address>`` block in the participant's cell.
    """

    name: str = ""
    role: str | None = None
    """Role/type on this docket (``Appellant``, ``Appellee``, …)."""
    side: str | None = None
    attorneys: list[AkAttorney] = []
    representation_status: str | None = None
    """What the Attorney cell says when it names no attorney:
    ``Unassigned`` or ``Self-represented litigant``."""


class AkRecordEntry(ScrapedData):
    """A record entry from the Record tab."""

    trial_court_case: str | None = None
    """Source file number this record belongs to (cases with multiple
    source files group records under each)."""
    source_type: str | None = None
    """What kind of file ``trial_court_case`` names, per the section
    heading: ``Trial Court Case``, ``ABA File Number`` (Alaska Bar
    Association) or ``AWCB Case Number`` (Workers' Compensation Board)."""
    record_type: str | None = None
    status: str | None = None
    record_date: date | None = None
    filed_or_issued_by: str | None = None
    role: str | None = None


class AkDocketEntry(ScrapedData):
    """A row on the Docket tab (maps to CL ``DocketEntry``)."""

    entry_number: str | None = None
    """The ``Dkt#`` ordinal of the entry on the docket page."""
    description: str | None = None
    """The docket item / event text."""
    status: str | None = None
    date_filed: date | None = None
    """Date the entry was filed or issued."""
    filed_or_issued_by: str | None = None
    category: str | None = None
    """The entry's category, as used by the page's "Docket By Category"
    grouping: ``Motion``, ``Notice``, ``Brief``, ``Other``."""
    category_code: str | None = None
    """The CMS's numeric code for ``category``."""
    document_url: str | None = None
    local_path: str | None = None


class AkMotionFlag(ScrapedData):
    """A checkbox flag on a motion-detail page.

    Each flag is rendered as a glyphicon next to a free-text label
    (e.g. ``Moving party says motion is Unopposed``, ``Emergency``,
    ``Full Court``). The label set is open-ended on the upstream
    site, so we store the verbatim label plus its boolean state.
    """

    motion_flag: str
    motion_value: bool


class AkMotionOpposition(ScrapedData):
    """A row of the Oppositions and Responses table on a motion-detail
    page."""

    entry_number: str | None = None
    """The ``Dkt#`` ordinal of the opposition/response."""
    opposition_type: str | None = None
    """E.g. ``Opposition``, ``Response``, ``Reply``."""
    party: str | None = None
    """Filing party and counsel, newlines collapsed to ``, ``."""
    status: str | None = None
    date_filed: date | None = None
    document_url: str | None = None


class AkMotion(ScrapedData):
    """A motion from Motions and Orders, with optional detail data."""

    # From the motions list
    entry_number: str | None = None
    """The motion's ``Dkt#`` ordinal."""
    motion_type: str | None = None
    filed_or_issued_by: str | None = None
    motion_date: date | None = None
    status: str | None = None
    document_url: str | None = None
    detail_url: str | None = None

    # From the motion detail page
    response_due_date: str | None = None
    extension_number: str | None = None
    total_extensions: str | None = None
    days_requested: str | None = None
    days_extended: str | None = None
    total_days_extended: str | None = None
    current_due_date: str | None = None
    requested_due_date: str | None = None

    flags: list[AkMotionFlag] = []
    oppositions: list[AkMotionOpposition] = []
    orders: list[dict] = []


class AkBriefingRound(ScrapedData):
    """One briefing round on the Briefs tab.

    The tab groups briefs under a round heading with its own status; a
    round can be open with nothing filed yet, so rounds are recorded
    separately rather than inferred from the briefs.
    """

    round_name: str | None = None
    """``Original Briefing``, ``Supplemental Briefing``,
    ``Briefing After Remand``."""
    status: str | None = None
    """``Open``, ``Complete``, ``Vacated``."""
    status_date: date | None = None
    """When the status was set; ``None`` when the page says
    "Time status set unknown"."""
    status_raw: str | None = None
    """The verbatim status line, e.g. ``Status: Complete 5/1/2001``."""


class AkBrief(ScrapedData):
    """A brief from the Briefs tab, with optional history."""

    entry_number: str | None = None
    """The brief's ``Dkt#`` ordinal."""
    briefing_round: str | None = None
    """``round_name`` of the ``AkBriefingRound`` this brief is listed
    under."""
    brief_type: str | None = None
    party: str | None = None
    status: str | None = None
    brief_date: date | None = None
    document_url: str | None = None
    history_url: str | None = None

    # From the brief history page
    filing_party: str | None = None
    history: list[dict] = []


class AkDocument(ScrapedData):
    """An archived document, joined back to its ``AkDocket`` via
    ``docket_number`` and to the originating row via ``entry_number`` +
    ``source`` (maps to CL ``RECAPDocument``)."""

    docket_number: str
    """Case number this document belongs to (e.g. ``S19019``)."""
    court: str
    """``ak`` (Supreme Court) or ``akctapp`` (Court of Appeals)."""
    entry_number: str | None = None
    """The ``Dkt#`` ordinal of the row the document is attached to."""
    source: str | None = None
    """Which tab the document came from: ``opinion``, ``docket``,
    ``motion``, ``order``, ``opposition``, ``brief``,
    ``brief_history``."""
    document_url: str | None = None
    local_path: str | None = None
    """Filesystem path where the driver archived this document."""
    missing_redirected: bool = False
    """True when the document endpoint 302-redirected to the search page
    instead of serving a file. The CMS does this for opinions from
    roughly the pre-2012 historical-coverage gap. ``local_path`` still
    points to the archived (HTML) response body; consumers should treat
    the document as unavailable."""


class AkDocket(ScrapedData):
    """A complete docket from the Alaska appellate courts (maps to CL
    ``Docket``).

    Aggregates data from all case tabs: General, Participants, Record,
    Docket, Motions, and Briefs.
    """

    # === Identity (CL-aligned) ===
    docket_number: str
    """Cleaned case number (e.g. ``S19019``, ``A14988``)."""
    docket_number_raw: str | None = None
    """Verbatim case number as shown on the site (e.g. ``S-19019``)."""
    court: str
    """CourtListener court id: ``ak`` or ``akctapp``."""
    case_name: str
    """Case name/title."""
    case_name_full: str | None = None
    """Full case caption from the Case Summary page."""
    date_filed: date | None = None

    # === Identifiers ===
    internal_case_id: str | None = None
    """Encrypted ``q`` parameter token from case URLs."""

    # === Case info (from the General page) ===
    case_type: str | None = None
    case_status: str | None = None
    special_status_flags: list[str] = []
    """Badges on the case-title block, spelled out from their tooltips
    (e.g. ``Expedited``)."""
    trial_court_numbers: list[str] = []
    """Lower-court case numbers listed in the search row's Trial Court
    Number column. ``lower_court_info`` carries the same numbers with
    their judgment dates when the Case Summary page lists them."""
    contact_case_manager: str | None = None
    case_manager_email: str | None = None
    cross_appeal_docket_number: str | None = None
    cross_appeal_internal_id: str | None = None

    # === Oral argument ===
    oral_argument_status: str | None = None
    oral_argument_datetime: str | None = None
    oral_argument_min_per_side: str | None = None
    oral_argument_location: str | None = None
    oral_argument_video_url: str | None = None

    # === Note ===
    note: str | None = None

    # === Child records ===
    opinions: list[AkOpinion] = []
    lower_court_info: list[AkLowerCourtInfo] = []
    related_cases: list[AkRelatedCase] = []
    parties: list[AkParty] = []
    records: list[AkRecordEntry] = []
    docket_entries: list[AkDocketEntry] = []
    motions: list[AkMotion] = []
    briefing_rounds: list[AkBriefingRound] = []
    briefs: list[AkBrief] = []

    # === Provenance ===
    source_url: str | None = None
    source_entry_point: str | None = None
