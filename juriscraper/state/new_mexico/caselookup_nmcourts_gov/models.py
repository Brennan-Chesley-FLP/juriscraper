"""Data models for the New Mexico Case Lookup scraper.

This site (``caselookup.nmcourts.gov/caselookup/``) is a server-rendered
Apache Tapestry app that publishes appellate docket data — case summary,
parties, hearings, register-of-actions activity, and judge-assignment
history — as plain HTML tables. No PDFs are linked: it is a
docket-information service only.

Supported courts:

- ``nm`` — New Mexico Supreme Court (case prefix ``S-1-SC-``)
- ``nmctapp`` — New Mexico Court of Appeals (case prefix ``A-1-CA-``)

Field names follow [`../../CL_MODELS.md`](../../CL_MODELS.md): the
CourtListener court-id string is ``court`` (not ``court_id``), the docket
number is ``docket_number`` (not ``case_number``/``docket_id``), and dates
use the ``date_*`` prefix.
"""

from __future__ import annotations

from datetime import date

from jkent.common.data_models import ScrapedData

from juriscraper.state.common_models import CleanString, HarmonizedCaseName

# CourtListener id → display name mapping (documentation only; the
# speculative entry knows its own court ids via the seeded ``NmCourtRange``).
COURT_IDS: dict[str, str] = {
    "nm": "New Mexico Supreme Court",
    "nmctapp": "New Mexico Court of Appeals",
}

# CourtListener id → the site's case-number components
# ``(court_type, court_location, case_category)``.
COURT_CONFIG: dict[str, tuple[str, str, str]] = {
    "nm": ("S", "1", "SC"),
    "nmctapp": ("A", "1", "CA"),
}

# Site constants.
BASE_URL: str = "https://caselookup.nmcourts.gov/caselookup"
LANDING_URL: str = f"{BASE_URL}/"
APP_URL: str = f"{BASE_URL}/app"
SEARCH_FORM_URL: str = (
    f"{APP_URL}?component=dl2&page=NameSearch&service=direct&session=T"
)


class NmDocketEntry(ScrapedData):
    """A row in the case detail page.

    Carries both **register-of-actions** rows (filings, motions, orders,
    opinions) and **hearings** (oral arguments, both past and future).
    The ``entry_kind`` field disambiguates so downstream consumers can
    filter to one or the other. Maps loosely to CourtListener
    ``DocketEntry``.
    """

    entry_kind: str
    """``"action"`` for register-of-actions rows; ``"hearing"`` for hearings."""

    date_filed: date | None = None
    """Event date for actions; hearing date for hearings."""

    description: str
    """Event description (action) or hearing-type label."""

    notes: CleanString | None = None
    """Free-text supplemental row content (e.g. brief title, motion outcome)."""

    event_result: CleanString | None = None
    """Disposition string for action rows (e.g. ``Granted In Part``)."""

    party_type: CleanString | None = None
    """Coded party type for action rows (e.g. ``PAPT``, ``DAPE``)."""

    party_number: CleanString | None = None
    """Sequence within the party type."""

    amount: CleanString | None = None
    """Fee amount, when applicable; almost always blank."""

    hearing_time: CleanString | None = None
    """Time-of-day string for hearings (e.g. ``9:30 AM``)."""

    hearing_judge: CleanString | None = None
    """Judge presiding at the hearing, when listed."""

    court: CleanString | None = None
    """Hearing court (often the bare string ``NEW MEXICO``)."""

    court_room: CleanString | None = None
    """Hearing court room, when listed."""

    document_url: str | None = None
    """Always ``None`` on this site — kept for forward compatibility."""


class NmParty(ScrapedData):
    """A party in an appellate case.

    Maps to CourtListener ``Party`` (+ ``PartyType`` for the role on this
    docket).
    """

    party_type: CleanString
    """Coded role (e.g. ``PAPT`` Plaintiff-Appellant, ``DAPE`` Defendant-Appellee)."""

    party_description: CleanString | None = None
    """Human-readable role label (e.g. ``Plaintiff - Appellant``)."""

    party_number: CleanString | None = None
    """Sequence within ``party_type``."""

    name: CleanString
    """Party name (``LAST FIRST MIDDLE`` for individuals, org name otherwise)."""


class NmJudgeAssignment(ScrapedData):
    """A row in the Judge Assignment History table."""

    assignment_date: date | None = None
    """Date the assignment took effect."""

    judge_name: CleanString | None = None
    """Assigned judge."""

    sequence_number: CleanString | None = None
    """Assignment sequence within the case."""

    assignment_event_description: CleanString | None = None
    """Free-text reason/description for the assignment event."""


class NmDocket(ScrapedData):
    """A complete docket from the New Mexico appellate courts.

    Maps to CourtListener ``Docket``.
    """

    # === Searchable / identifying fields ===
    docket_number: str
    """Full docket number, e.g. ``S-1-SC-39473`` or ``A-1-CA-41454``."""

    court: str
    """CourtListener court id: ``nm`` (Supreme Court) or ``nmctapp``
    (Court of Appeals)."""

    date_filed: date | None = None
    """Filing date from the case-summary table."""

    # === Required ===
    case_name: HarmonizedCaseName
    """Case heading, e.g. ``State v. Houidobre``."""

    # === Case metadata ===
    current_judge: CleanString | None = None
    """Current assigned judge (often blank for appellate matters)."""

    court_name: CleanString | None = None
    """Uppercase court name from the case-summary table
    (e.g. ``NEW MEXICO SUPREME COURT``)."""

    # === Nested data ===
    entries: list[NmDocketEntry] = []
    """Register-of-actions rows and hearings (see ``entry_kind``)."""

    parties: list[NmParty] = []
    """Parties with their coded role and party number."""

    judge_assignments: list[NmJudgeAssignment] = []
    """Judge assignment history rows."""

    # === Provenance ===
    source_url: str | None = None
    """URL of the case detail page (best-effort; site uses POST + session)."""

    source_entry_point: str | None = None
    """Entry point used to reach this docket (e.g. ``dockets_by_number``)."""
