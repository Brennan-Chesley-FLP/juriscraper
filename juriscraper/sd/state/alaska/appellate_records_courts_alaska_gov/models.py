"""Data models for Alaska appellate courts scraper.

Supported courts:
- ak: Alaska Supreme Court (case numbers S#####)
- akctapp: Alaska Court of Appeals (case numbers A#####)
"""

from __future__ import annotations

from datetime import date

from jkent.common.data_models import ScrapedData


class AkOpinion(ScrapedData):
    """An opinion from the Case Summary page."""

    number: str | None = None
    opinion_type: str | None = None
    decision: str | None = None
    opinion_date: date | None = None
    citation: str | None = None
    document_url: str | None = None
    local_path: str | None = None


class AkLowerCourtInfo(ScrapedData):
    """Lower court or agency information from Case Summary."""

    case_number: str | None = None
    judgment_date: date | None = None
    distribution_date: date | None = None
    court_or_agency: str | None = None
    judge: str | None = None


class AkRelatedCase(ScrapedData):
    """A related appellate case from Case Summary."""

    case_number: str | None = None
    case_name: str | None = None
    case_type: str | None = None
    relationship: str | None = None
    status: str | None = None
    internal_id: str | None = None


class AkAttorney(ScrapedData):
    """An attorney representing a party."""

    name: str | None = None
    address: str | None = None
    phone: str | None = None


class AkParty(ScrapedData):
    """A participant and their attorneys from Participants & Attorneys.

    A single party can be represented by multiple attorneys (e.g.,
    co-counsel from the same firm), each rendered as a separate
    ``<address>`` block in the participant's cell.
    """

    name: str = ""
    role: str | None = None
    side: str | None = None
    attorneys: list[AkAttorney] = []


class AkRecordEntry(ScrapedData):
    """A record entry from the Record tab."""

    trial_court_case: str | None = None
    record_type: str | None = None
    status: str | None = None
    record_date: date | None = None
    filed_or_issued_by: str | None = None
    role: str | None = None


class AkDocketEntry(ScrapedData):
    """A docket entry from the Docket tab."""

    docket_number: str | None = None
    item: str | None = None
    status: str | None = None
    date_filed_or_issued: date | None = None
    filed_or_issued_by: str | None = None
    document_url: str | None = None
    local_path: str | None = None


class AkMotionFlag(ScrapedData):
    """A checkbox flag on a motion-detail page.

    Each flag is rendered as a glyphicon next to a free-text label
    (e.g., ``Moving party says motion is Unopposed``, ``Emergency``,
    ``Full Court``). The label set is open-ended on the upstream
    site, so we store the verbatim label plus its boolean state.
    """

    motion_flag: str
    motion_value: bool


class AkMotion(ScrapedData):
    """A motion from Motions and Orders, with optional detail data."""

    # From motions list
    docket_number: str | None = None
    motion_type: str | None = None
    filed_or_issued_by: str | None = None
    motion_date: date | None = None
    status: str | None = None
    document_url: str | None = None
    detail_url: str | None = None

    # From motion detail page
    response_due_date: str | None = None
    extension_number: str | None = None
    total_extensions: str | None = None
    days_requested: str | None = None
    days_extended: str | None = None
    total_days_extended: str | None = None
    current_due_date: str | None = None
    requested_due_date: str | None = None

    flags: list[AkMotionFlag] = []
    oppositions: list[dict] = []
    orders: list[dict] = []


class AkDocument(ScrapedData):
    """An archived document from a case.

    Yielded as a separate top-level record so it can be joined back to
    the parent AkDocket via ``case_number``, and to the specific entry
    that referenced it via ``docket_number`` + ``source``.
    """

    case_number: str
    """Case number this document belongs to (e.g., 'S19019')."""

    court_id: str
    """'ak' (Supreme Court) or 'akctapp' (Court of Appeals)."""

    docket_number: str | None = None
    """The 'dkt#' ordinal of the entry the document is attached to."""

    source: str | None = None
    """Which tab the document came from: 'opinion', 'docket', 'motion',
    'order', 'brief', 'brief_history'."""

    document_url: str | None = None
    """URL the file was downloaded from."""

    local_path: str | None = None
    """Filesystem path where the driver archived this document."""

    missing_redirected: bool = False
    """True when the document endpoint 302-redirected to the search page
    instead of serving a file. The CMS does this for opinions from
    roughly the pre-2012 historical-coverage gap. The path in
    ``local_path`` still points to the archived (HTML) response body;
    consumers should treat the document as unavailable."""


class AkBrief(ScrapedData):
    """A brief from the Briefs tab, with optional history."""

    docket_number: str | None = None
    brief_type: str | None = None
    party: str | None = None
    status: str | None = None
    brief_date: date | None = None
    document_url: str | None = None
    history_url: str | None = None

    # From brief history page
    filing_party: str | None = None
    history: list[dict] = []


class AkDocket(ScrapedData):
    """A complete docket from the Alaska appellate courts.

    Aggregates data from all case tabs: General, Participants,
    Record, Docket, Motions, and Briefs.
    """

    # === Searchable fields ===
    case_number: str
    """Case number (e.g., 'S19019', 'A14988')"""

    court_id: str
    """Court: 'ak' (Supreme Court) or 'akctapp' (Court of Appeals)"""

    date_filed: date | None = None
    """Date the case was filed"""

    # === Required ===
    case_name: str
    """Case name/title"""

    # === Identifiers ===
    internal_case_id: str | None = None
    """Encrypted q parameter token from case URLs"""

    # === Case info (from General page) ===
    case_type: str | None = None
    case_status: str | None = None
    full_caption: str | None = None
    contact_case_manager: str | None = None
    case_manager_email: str | None = None
    cross_appeal_case_number: str | None = None
    cross_appeal_internal_id: str | None = None

    # === Oral argument ===
    oral_argument_status: str | None = None
    oral_argument_datetime: str | None = None
    oral_argument_min_per_side: str | None = None
    oral_argument_location: str | None = None
    oral_argument_video_url: str | None = None

    # === Note ===
    note: str | None = None

    # === Opinions ===
    opinions: list[AkOpinion] = []

    # === Lower court info ===
    lower_court_info: list[AkLowerCourtInfo] = []

    # === Related cases ===
    related_cases: list[AkRelatedCase] = []

    # === Parties ===
    parties: list[AkParty] = []

    # === Records ===
    records: list[AkRecordEntry] = []

    # === Docket entries ===
    entries: list[AkDocketEntry] = []

    # === Motions ===
    motions: list[AkMotion] = []

    # === Briefs ===
    briefs: list[AkBrief] = []

    # === Source ===
    source_url: str | None = None
