"""Data models for the Oklahoma appellate courts scraper (oscn.net).

The OSCN appellate database serves all Oklahoma appellate courts in a
single backend. The actual court is determined from the case caption
on each case page and mapped to a CourtListener court_id.
"""

from __future__ import annotations

from datetime import date

from jkent.common.data_models import ScrapedData

# CourtListener court IDs for the appellate courts served by OSCN.
COURT_IDS: dict[str, str] = {
    "okla": "Supreme Court of Oklahoma",
    "oklacivapp": "Court of Civil Appeals of Oklahoma",
    "oklacrimapp": "Court of Criminal Appeals of Oklahoma",
    "oklacoj": "Court on the Judiciary of Oklahoma",
    "oklajeap": "Oklahoma Judicial Ethics Advisory Panel",
}


class OkDocketEntry(ScrapedData):
    """A single docket-table row on an OSCN case page."""

    date_filed: date | None = None
    """Date displayed in the Date column."""

    code: str | None = None
    """Bracketed event code from the Code column (e.g. "CASE", "ORDR", "TEXT")."""

    description: str | None = None
    """Full text of the Description column with whitespace normalized."""

    color: str | None = None
    """Hex color (without leading '#') of the row's <font color="..."> tags
    (e.g. "0000FF"). The site uses color to mark significance; semantics
    are undocumented but we preserve the value for downstream interpretation."""

    count: str | None = None
    """Count column value, when present."""

    party: str | None = None
    """Party column value, when present."""

    amount: str | None = None
    """Amount column value, when present."""

    document_id: str | None = None
    """The bcN value referenced as `Document Available (#NNNNNNN)`, when
    a document is attached to the entry."""

    tiff_url: str | None = None
    """Absolute URL to the TIFF version of the attached document."""

    pdf_url: str | None = None
    """Absolute URL to the PDF version of the attached document."""

    tiff_local_path: str | None = None
    """Local archive path of the downloaded TIFF, set after archiving."""

    pdf_local_path: str | None = None
    """Local archive path of the downloaded PDF, set after archiving."""


class OkParty(ScrapedData):
    """A party on the case."""

    name: str
    """Party name as displayed."""

    role: str | None = None
    """Party role / type (e.g. "Petitioner", "Respondent", "Complainant")."""


class OkAttorney(ScrapedData):
    """An attorney record from the Attorneys table."""

    name: str
    """Attorney display name."""

    bar_number: str | None = None
    """Oklahoma bar number, parsed from `(Bar #NNNNN)`."""

    address: str | None = None
    """Mailing address text (newline-separated as displayed)."""

    represented_parties: list[str] = []
    """Names of parties represented by this attorney."""


class OkEvent(ScrapedData):
    """A scheduled or completed event from the Events section."""

    event_date: date | None = None
    """Event date if extractable."""

    description: str
    """Event description text."""


class OkLowerCourtCount(ScrapedData):
    """A row from the "Lower Court Counts and Other Information" table."""

    count: str | None = None
    case_number: str | None = None
    statute: str | None = None
    crime: str | None = None
    sentence: str | None = None
    judge: str | None = None
    reporter: str | None = None


class OkLowerCourtCase(ScrapedData):
    """The trial-court docket page that the appellate case originated from.

    Populated by following the appellate page's lower-court reference to
    `?db={county}&number={case_number}`. Mirrors the appellate Docket
    schema in miniature.
    """

    court_db: str
    """OSCN database identifier — typically a lowercased Oklahoma county
    name (e.g. "tulsa")."""

    case_number: str
    """Trial court case number (e.g. "CV-2020-84")."""

    case_name: str | None = None
    """Case caption / short style as displayed on the trial-court page."""

    date_filed: date | None = None

    parties: list[OkParty] = []
    attorneys: list[OkAttorney] = []
    entries: list[OkDocketEntry] = []

    source_url: str | None = None
    """Absolute URL of the trial-court case page."""


class OkDocket(ScrapedData):
    """An Oklahoma appellate case docket scraped from oscn.net."""

    # === Searchable fields ===
    case_number: str
    """Canonical case number (from the embedded `json_style` block; may
    differ from the URL `number=` parameter for prefixed case types)."""

    court_id: str
    """CourtListener court identifier (one of `COURT_IDS`)."""

    date_filed: date | None = None
    """Case filing date."""

    # === Required fields ===
    case_name: str
    """Full case caption / style."""

    # === Case metadata ===
    case_classification: str | None = None
    """Classification text shown next to the case number (e.g.
    "Disciplinary Rule 6")."""

    cmid: str | None = None
    """Internal case management ID from the embedded JSON block."""

    court_name: str | None = None
    """Court name as displayed in the case heading (e.g. "IN THE COURT
    OF CIVIL APPEALS OF THE STATE OF OKLAHOMA Tulsa")."""

    # === Nested data ===
    parties: list[OkParty] = []
    attorneys: list[OkAttorney] = []
    entries: list[OkDocketEntry] = []
    events: list[OkEvent] = []
    lower_court_counts: list[OkLowerCourtCount] = []
    """Structured rows from the Lower Court Counts table on the appellate
    page."""

    lower_court_case: OkLowerCourtCase | None = None
    """Trial-court docket fetched by following the lower-court reference,
    when resolution succeeded."""

    # === Opinion / citations ===
    opinion_url: str | None = None
    """URL of the published opinion / order from the case heading."""

    opinion_citation: str | None = None
    """Citation text of the published opinion (e.g. "2026 OK 26")."""

    # === Subscription / source links ===
    track_case_url: str | None = None
    """URL constructed from the embedded `casetracker.js` variables —
    `https://app.oscn.net/cases/?act={court}&acn={case_number}`."""

    source_url: str | None = None
    """Canonical case page URL."""
