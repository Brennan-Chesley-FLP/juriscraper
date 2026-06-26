"""Data models for the Supreme Court of Ohio (ECMS) docket scraper.

The site backs a single CourtListener court (``ohio``). Public docket
numbers follow ``YYYY-NNNN`` (e.g. ``2026-0197``); the sequence resets each
calendar year. The database covers cases filed on or after 1985-01-01
(1989-01-01 for practice-of-law cases).

Field names follow [`../../CL_MODELS.md`](../../CL_MODELS.md): the
CourtListener court-id string is ``court`` (not ``court_id``); the public
case number is ``docket_number`` (not ``case_number``/``docket_id``); dates
use the ``date_*`` prefix; a party's role is ``role`` (CL
``PartyType.name``). ``CleanString``/``HarmonizedCaseName`` are used for
text/caption cleaning.
"""

from __future__ import annotations

from datetime import date

from jkent.common.data_models import ScrapedData

from juriscraper.state.common_models import CleanString, HarmonizedCaseName

COURT_IDS: dict[str, str] = {
    "ohio": "Supreme Court of Ohio",
}
"""Map from the CourtListener court id to its display name."""

COURT_ID: str = "ohio"


class OhioSupremeCourtAttorney(ScrapedData):
    """An attorney attached to a party on the case.

    Maps to CourtListener ``Attorney`` (+ ``Role`` for the relationship)."""

    name: CleanString
    """As reported by the API, ``"Last, First Middle"``."""

    ar_number: CleanString | None = None
    """Ohio Attorney Registration number (links to the bar directory)."""

    counsel_of_record: bool = False


class OhioSupremeCourtParty(ScrapedData):
    """A party in the case (one entry per party, with attorneys nested).

    Maps to CourtListener ``Party`` (+ ``PartyType`` for the role)."""

    name: CleanString
    role: CleanString = ""
    """Role on this docket: ``"Appellant"``, ``"Appellee"``,
    ``"Relator"`` (CL ``PartyType.name``)."""

    pro_se: bool = False
    attorneys: list[OhioSupremeCourtAttorney] = []


class OhioSupremeCourtDocketEntry(ScrapedData):
    """A row from the case's docket-items list (Register of Actions).

    Maps to CourtListener ``DocketEntry``."""

    date_filed: date | None = None
    description: CleanString
    filing_parties: CleanString | None = None
    """Free-text filer label as shown on the docket, e.g. ``"Appellant"``."""

    item_id: int | None = None
    """The ECMS internal numeric id; doubles as the PDF filename stem."""

    code: CleanString | None = None
    """ECMS internal action code (numeric string)."""

    document_name: CleanString | None = None
    """The PDF filename, e.g. ``"998679.pdf"``. None for entries with no attachment."""

    document_url: str | None = None
    """Resolved download URL for the attachment, when present."""


class OhioSupremeCourtDecision(ScrapedData):
    """A row from the case's decision/disposition list.

    Maps loosely to CourtListener ``DocketEntry`` (a disposition row)."""

    release_date: date | None = None
    description: CleanString
    """May contain HTML markup (anchors to opinion PDFs)."""

    disposes_case: bool = False
    document_name: CleanString | None = None
    document_url: str | None = None


class OhioSupremeCourtPriorCourt(ScrapedData):
    """The lower court / prior jurisdiction block on a Supreme Court appeal.

    Maps to CourtListener ``OriginatingCourtInformation``."""

    name: CleanString | None = None
    """e.g. ``"11th District Court of Appeals"``, ``"Public Utilities Commission"``."""

    county: CleanString | None = None
    prior_decision_date: date | None = None
    prior_case_numbers: list[str] = []
    """Trial-court / lower-appellate docket numbers."""


class OhioSupremeCourtDocument(ScrapedData):
    """A single archived PDF download referenced from the case file.

    Yielded as a separate top-level record, joinable back to the parent
    :class:`OhioSupremeCourtDocket` via ``docket_number``. Maps to
    CourtListener ``RECAPDocument``."""

    docket_number: str
    """The owning case's ``YYYY-NNNN`` docket number."""

    court: str = COURT_ID
    """CourtListener court id (``ohio``)."""

    document_id: int
    """The ECMS internal numeric id (PDF filename stem)."""

    document_url: str
    section: str
    """``"DocketItems"`` or ``"DecisionItems"``."""

    local_path: str | None = None
    """Filesystem path where the driver archived this document."""


class OhioSupremeCourtDocket(ScrapedData):
    """A complete Supreme Court of Ohio docket — main scraper output.

    Maps to CourtListener ``Docket`` (+ its nested entry/party tables)."""

    # === Searchable fields ===
    docket_number: str
    """Public case number, ``YYYY-NNNN``."""

    court: str = COURT_ID
    """CourtListener court id (``ohio``)."""

    date_filed: date | None = None
    case_name: HarmonizedCaseName
    """The full case caption; multi-line on the API (``A\\nv.\\nB``),
    collapsed to a single line before harmonizing."""

    # === Case metadata ===
    case_id: int | None = None
    """ECMS internal numeric id. Stable provenance key."""

    case_type: CleanString | None = None
    """e.g. ``"Jurisdictional Appeal"``, ``"Original Action in Mandamus"``."""

    status: CleanString | None = None
    """``"Open"`` or ``"Closed"``."""

    # === Nested data ===
    prior_court: OhioSupremeCourtPriorCourt | None = None
    parties: list[OhioSupremeCourtParty] = []
    entries: list[OhioSupremeCourtDocketEntry] = []
    decisions: list[OhioSupremeCourtDecision] = []
    issues: list[str] = []
    """Free-text issue statements when the case is on the Issues Accepted list."""

    source_url: str | None = None
    """Absolute URL of the case-detail view this record was scraped from."""

    source_entry_point: str | None = None
    """Entry point used to reach this docket (e.g. ``dockets_by_number``)."""
