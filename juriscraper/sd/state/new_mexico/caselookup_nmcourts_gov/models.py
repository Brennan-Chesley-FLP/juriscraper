"""Data models for the New Mexico Case Lookup scraper.

Supported courts:
- ``nm`` — New Mexico Supreme Court (case prefix ``S-1-SC-``)
- ``nmctapp`` — New Mexico Court of Appeals (case prefix ``A-1-CA-``)
"""

from __future__ import annotations

from datetime import date

from jkent.common.data_models import ScrapedData

# CourtListener id → display name mapping (documentation only; the
# speculative entry methods know their own court ids).
COURT_IDS: dict[str, str] = {
    "nm": "New Mexico Supreme Court",
    "nmctapp": "New Mexico Court of Appeals",
}


class NmDocketEntry(ScrapedData):
    """A row in the case detail page.

    Carries both **register-of-actions** rows (filings, motions, orders,
    opinions) and **hearings** (oral arguments, both past and future).
    The ``entry_kind`` field disambiguates so downstream consumers can
    filter to one or the other.
    """

    entry_kind: str
    """``"action"`` for register-of-actions rows; ``"hearing"`` for hearings."""

    date_filed: date | None = None
    """Event date for actions; hearing date for hearings."""

    description: str
    """Event description (action) or hearing-type label."""

    notes: str | None = None
    """Free-text supplemental row content (e.g. brief title, motion outcome)."""

    event_result: str | None = None
    """Disposition string for action rows (e.g. ``Granted In Part``)."""

    party_type: str | None = None
    """Coded party type for action rows (e.g. ``PAPT``, ``DAPE``)."""

    party_number: str | None = None
    """Sequence within the party type."""

    amount: str | None = None
    """Fee amount, when applicable; almost always blank."""

    hearing_time: str | None = None
    """Time-of-day string for hearings (e.g. ``9:30 AM``)."""

    hearing_judge: str | None = None
    """Judge presiding at the hearing, when listed."""

    court: str | None = None
    """Hearing court (often the bare string ``NEW MEXICO``)."""

    court_room: str | None = None
    """Hearing court room, when listed."""

    document_url: str | None = None
    """Always ``None`` on this site — kept for forward compatibility."""


class NmParty(ScrapedData):
    """A party in an appellate case."""

    party_type: str
    """Coded role (e.g. ``PAPT`` Plaintiff-Appellant, ``DAPE`` Defendant-Appellee)."""

    party_description: str | None = None
    """Human-readable role label (e.g. ``Plaintiff - Appellant``)."""

    party_number: str | None = None
    """Sequence within ``party_type``."""

    name: str
    """Party name (``LAST FIRST MIDDLE`` for individuals, org name otherwise)."""


class NmJudgeAssignment(ScrapedData):
    """A row in the Judge Assignment History table."""

    assignment_date: date | None = None
    judge_name: str | None = None
    sequence_number: str | None = None
    assignment_event_description: str | None = None


class NmDocket(ScrapedData):
    """A complete docket from the New Mexico appellate courts."""

    # === Searchable fields ===
    docket_id: str
    """Full docket number, e.g. ``S-1-SC-39473`` or ``A-1-CA-41454``."""

    court_id: str
    """``nm`` (Supreme Court) or ``nmctapp`` (Court of Appeals)."""

    date_filed: date | None = None
    """Filing date from the case-summary table."""

    # === Required ===
    case_name: str
    """Case heading, e.g. ``State v. Houidobre``."""

    # === Case metadata ===
    current_judge: str | None = None
    """Current assigned judge (often blank for appellate matters)."""

    court: str | None = None
    """Uppercase court name from the case-summary table."""

    # === Nested data ===
    entries: list[NmDocketEntry] = []
    """Register-of-actions rows and hearings (see ``entry_kind``)."""

    parties: list[NmParty] = []
    """Parties with their coded role and party number."""

    judge_assignments: list[NmJudgeAssignment] = []
    """Judge assignment history rows."""

    source_url: str | None = None
    """URL of the case detail page (best-effort; site uses POST + session)."""
