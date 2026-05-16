"""Data models for the Supreme Court of Ohio (ECMS) docket scraper.

The site backs a single CourtListener court (``ohio``). Public case numbers
follow ``YYYY-NNNN`` (e.g. ``2026-0197``); the sequence resets each
calendar year. The database covers cases filed on or after 1985-01-01
(1989-01-01 for practice-of-law cases).
"""

from __future__ import annotations

from datetime import date

from jkent.common.data_models import ScrapedData

COURT_IDS: dict[str, str] = {
    "ohio": "Supreme Court of Ohio",
}


class OhioSupremeCourtAttorney(ScrapedData):
    """An attorney attached to a party on the case."""

    name: str
    """As reported by the API, ``"Last, First Middle"``."""

    ar_number: str | None = None
    """Ohio Attorney Registration number (links to the bar directory)."""

    counsel_of_record: bool = False


class OhioSupremeCourtParty(ScrapedData):
    """A party in the case (one entry per party, with attorneys nested)."""

    name: str
    party_type: str
    """e.g. ``"Appellant"``, ``"Appellee"``, ``"Relator"``."""

    pro_se: bool = False
    attorneys: list[OhioSupremeCourtAttorney] = []


class OhioSupremeCourtDocketEntry(ScrapedData):
    """A row from the case's docket-items list (Register of Actions)."""

    date_filed: date | None = None
    description: str
    filing_parties: str | None = None
    """Free-text filer label as shown on the docket, e.g. ``"Appellant"``."""

    item_id: int | None = None
    """The ECMS internal numeric id; doubles as the PDF filename stem."""

    code: str | None = None
    """ECMS internal action code (numeric string)."""

    document_name: str | None = None
    """The PDF filename, e.g. ``"998679.pdf"``. None for entries with no attachment."""

    document_url: str | None = None
    """Resolved download URL for the attachment, when present."""


class OhioSupremeCourtDecision(ScrapedData):
    """A row from the case's decision/disposition list."""

    release_date: date | None = None
    description: str
    """May contain HTML markup (anchors to opinion PDFs)."""

    disposes_case: bool = False
    document_name: str | None = None
    document_url: str | None = None


class OhioSupremeCourtPriorCourt(ScrapedData):
    """The lower court / prior jurisdiction block on a Supreme Court appeal."""

    name: str | None = None
    """e.g. ``"11th District Court of Appeals"``, ``"Public Utilities Commission"``."""

    county: str | None = None
    prior_decision_date: date | None = None
    prior_case_numbers: list[str] = []


class OhioSupremeCourtDocument(ScrapedData):
    """A single archived PDF download referenced from the case file."""

    docket_id: str
    """The owning case's ``YYYY-NNNN`` docket number."""

    document_id: int
    """The ECMS internal numeric id (PDF filename stem)."""

    document_url: str
    section: str
    """``"DocketItems"`` or ``"DecisionItems"``."""

    local_path: str | None = None


class OhioSupremeCourtDocket(ScrapedData):
    """A complete Supreme Court of Ohio docket."""

    # === Searchable fields ===
    docket_id: str
    """Public case number, ``YYYY-NNNN``."""

    court_id: str = "ohio"
    date_filed: date | None = None
    case_name: str
    """The full case caption; multi-line on the API (``A\\nv.\\nB``)."""

    # === Case metadata ===
    case_id: int | None = None
    """ECMS internal numeric id."""

    case_type: str | None = None
    """e.g. ``"Jurisdictional Appeal"``, ``"Original Action in Mandamus"``."""

    status: str | None = None
    """``"Open"`` or ``"Closed"``."""

    # === Nested data ===
    prior_court: OhioSupremeCourtPriorCourt | None = None
    parties: list[OhioSupremeCourtParty] = []
    entries: list[OhioSupremeCourtDocketEntry] = []
    decisions: list[OhioSupremeCourtDecision] = []
    issues: list[str] = []
    """Free-text issue statements when the case is on the Issues Accepted list."""

    source_url: str | None = None
