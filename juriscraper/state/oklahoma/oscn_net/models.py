"""Data models for the Oklahoma appellate courts scraper (oscn.net).

The OSCN appellate database (``db=appellate``) serves all Oklahoma
appellate courts in a single backend. The actual court is determined from
the case caption heading on each case page and mapped to a CourtListener
court id.

Field names follow [`../../CL_MODELS.md`](../../CL_MODELS.md): the
CourtListener court-id string is ``court`` (not ``court_id``), the case
number is ``docket_number`` (with a verbatim ``docket_number_raw``), and
dates use the ``date_*`` prefix.
"""

from __future__ import annotations

from datetime import date
from typing import ClassVar

from jkent.common.data_models import ScrapedData

from juriscraper.state.common_models import CleanString, HarmonizedCaseName

# CourtListener court IDs for the appellate courts served by OSCN.
COURT_IDS: dict[str, str] = {
    "okla": "Supreme Court of Oklahoma",
    "oklacivapp": "Court of Civil Appeals of Oklahoma",
    "oklacrimapp": "Court of Criminal Appeals of Oklahoma",
    "oklacoj": "Court on the Judiciary of Oklahoma",
    "oklajeap": "Oklahoma Judicial Ethics Advisory Panel",
}


class OkDocketEntry(ScrapedData):
    """A single docket-table row on an OSCN case page.

    Maps loosely to CourtListener ``DocketEntry`` (+ ``RECAPDocument`` for
    any attached document)."""

    date_filed: date | None = None
    """Date displayed in the Date column."""

    code: CleanString | None = None
    """Bracketed event code from the Code column (e.g. "CASE", "ORDR", "TEXT")."""

    description: CleanString | None = None
    """Full text of the Description column with whitespace normalized."""

    color: str | None = None
    """Hex color (without leading '#') of the row's <font color="..."> tags
    (e.g. "0000FF"). The site uses color to mark significance; semantics
    are undocumented but we preserve the value for downstream interpretation."""

    count: CleanString | None = None
    """Count column value, when present."""

    party: CleanString | None = None
    """Party column value, when present."""

    amount: CleanString | None = None
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
    """A party on the case.

    Maps to CourtListener ``Party`` (+ ``PartyType`` for the role)."""

    name: CleanString
    """Party name as displayed."""

    role: CleanString | None = None
    """Party role / type (e.g. "Petitioner", "Respondent", "Complainant")."""


class OkAttorney(ScrapedData):
    """An attorney record from the Attorneys table.

    Maps to CourtListener ``Attorney`` (+ ``Role``)."""

    name: CleanString
    """Attorney display name."""

    bar_number: str | None = None
    """Oklahoma bar number, parsed from `(Bar #NNNNN)`."""

    address: CleanString | None = None
    """Mailing address text (newline-separated as displayed)."""

    represented_parties: list[str] = []
    """Names of parties represented by this attorney."""


class OkEvent(ScrapedData):
    """A scheduled or completed event from the Events section.

    Future-calendar / scheduled-hearing items are modelled here as part
    of the docket (not as a separate record type)."""

    date_event: date | None = None
    """Event date if extractable."""

    description: CleanString
    """Event description text."""


class OkLowerCourtCount(ScrapedData):
    """A row from the "Lower Court Counts and Other Information" table.

    Maps loosely to CourtListener ``OriginatingCourtInformation`` /
    ``TrialCourtData`` (the originating trial-court counts)."""

    count: CleanString | None = None
    docket_number: CleanString | None = None
    """Trial-court case number in the Case Number column."""
    statute: CleanString | None = None
    crime: CleanString | None = None
    sentence: CleanString | None = None
    judge: CleanString | None = None
    reporter: CleanString | None = None


class OkLowerCourtCase(ScrapedData):
    """The trial-court docket page that the appellate case originated from.

    Populated by following the appellate page's lower-court reference to
    ``?db={county}&number={docket_number}``. Mirrors the appellate Docket
    schema in miniature. Maps to CourtListener
    ``OriginatingCourtInformation`` / ``TrialCourtData``.
    """

    court_db: str
    """OSCN database identifier — typically a lowercased Oklahoma county
    name (e.g. "tulsa")."""

    docket_number: CleanString
    """Trial court case number (e.g. "CV-2020-84")."""

    case_name: HarmonizedCaseName | None = None
    """Case caption / short style as displayed on the trial-court page."""

    date_filed: date | None = None
    """Date filed in the trial court."""

    parties: list[OkParty] = []
    attorneys: list[OkAttorney] = []
    entries: list[OkDocketEntry] = []

    source_url: str | None = None
    """Absolute URL of the trial-court case page."""


class OkDocket(ScrapedData):
    """An Oklahoma appellate case docket scraped from oscn.net.

    Maps to CourtListener ``Docket`` (+ its per-court side tables)."""

    # === Searchable / identity fields ===
    docket_number: CleanString
    """Canonical case number (from the embedded `json_style` block; may
    differ from the URL `number=` parameter for prefixed case types)."""

    docket_number_raw: str | None = None
    """Verbatim case number as found on the source, no cleaning. Set when
    it differs from the canonical `docket_number`."""

    court: str
    """CourtListener court identifier (one of `COURT_IDS`)."""

    date_filed: date | None = None
    """Case filing date."""

    # === Required fields ===
    case_name: HarmonizedCaseName
    """Full case caption / style."""

    # === Case metadata ===
    case_classification: CleanString | None = None
    """Classification text shown next to the case number (e.g.
    "Disciplinary Rule 6")."""

    cmid: str | None = None
    """Internal case management ID from the embedded JSON block."""

    court_name: CleanString | None = None
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

    opinion_citation: CleanString | None = None
    """Citation text of the published opinion (e.g. "2026 OK 26")."""

    # === Subscription / source links ===
    track_case_url: str | None = None
    """URL constructed from the embedded `casetracker.js` variables —
    `https://app.oscn.net/cases/?act={court}&acn={docket_number}`."""

    source_url: str | None = None
    """Canonical case page URL."""

    source_entry_point: str | None = None
    """Entry point used to reach this docket (e.g. `dockets_by_filing_date`)."""


# =========================================================================
# Site constants
# =========================================================================

BASE_URL: str = "https://www.oscn.net"
SEARCH_RESULTS_URL: str = f"{BASE_URL}/dockets/Results.aspx"
CASE_INFO_URL: str = f"{BASE_URL}/dockets/GetCaseInformation.aspx"
TRACK_CASE_URL_TEMPLATE: str = (
    "https://app.oscn.net/cases/?act={court}&acn={docket_number}"
)


class _OscnConfig:
    """Site configuration constants, kept off the public model classes."""

    BASE_URL: ClassVar[str] = BASE_URL
    SEARCH_RESULTS_URL: ClassVar[str] = SEARCH_RESULTS_URL
    CASE_INFO_URL: ClassVar[str] = CASE_INFO_URL
    TRACK_CASE_URL_TEMPLATE: ClassVar[str] = TRACK_CASE_URL_TEMPLATE
    COURT_IDS: ClassVar[dict[str, str]] = COURT_IDS
