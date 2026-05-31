from __future__ import annotations

from datetime import date

from jkent.common.data_models import ScrapedData

# Court ID mapping: CourtListener ID → display name
COURT_IDS: dict[str, str] = {
    "cal": "California Supreme Court",
    "calctapp1d": "California Court of Appeal, First Appellate District",
    "calctapp2d": "California Court of Appeal, Second Appellate District",
    "calctapp3d": "California Court of Appeal, Third Appellate District",
    "calctapp4d": "California Court of Appeal, Fourth Appellate District",
    "calctapp5d": "California Court of Appeal, Fifth Appellate District",
    "calctapp6d": "California Court of Appeal, Sixth Appellate District",
}

# Site internal court config: prefix → (dist param, CourtListener ID)
COURT_CONFIG: dict[str, tuple[str, str]] = {
    "S": ("0", "cal"),
    "A": ("1", "calctapp1d"),
    "B": ("2", "calctapp2d"),
    "C": ("3", "calctapp3d"),
    "D": ("41", "calctapp4d"),
    "E": ("42", "calctapp4d"),
    "G": ("43", "calctapp4d"),
    "F": ("5", "calctapp5d"),
    "H": ("6", "calctapp6d"),
}

BASE_URL = "https://appellatecases.courtinfo.ca.gov"
SEARCH_URL = f"{BASE_URL}/search.cfm"


class CaAppCaseUnavailable(ScrapedData):
    """Yielded when a speculative case number search returns 'Case Not Found'.

    This may indicate the case doesn't exist, the number was never assigned,
    or the case is confidential.
    """

    docket_id: str
    """The case number that was searched (e.g., 'H000001')."""

    court_id: str
    """CourtListener court ID (e.g., 'calctapp6d')."""


class CaAppDocketEntry(ScrapedData):
    """A single entry from the Docket (Register of Actions) tab."""

    date_filed: date | None = None
    """Date of the docket entry (mm/dd/yyyy on site)."""

    description: str
    """Description of the action (e.g., 'Petition for review filed')."""

    notes: str | None = None
    """Additional notes, may contain party/attorney names."""


class CaAppBrief(ScrapedData):
    """A brief filing record from the Briefs tab."""

    brief_type: str
    """Type/description (e.g., 'Opening brief on the merits filed')."""

    date_filed: date | None = None
    """Date the brief was filed."""

    party_attorney: str | None = None
    """Party and attorney associated with the brief."""

    notes: str | None = None
    """Additional notes."""


class CaAppDisposition(ScrapedData):
    """Disposition information. Structure differs between SC and CoA.

    For Supreme Court: date + description (e.g., "Opinion: Affirmed").
    For Courts of Appeal: structured fields including type, publication
    status, author, and participants.
    """

    description: str
    """Disposition description (e.g., 'Voluntary dismissal')."""

    disposition_date: date | None = None
    """Disposition date."""

    disposition_type: str | None = None
    """E.g., 'Final'. CoA only."""

    publication_status: str | None = None
    """Publication status. CoA only."""

    author: str | None = None
    """Opinion author. CoA only."""

    participants: str | None = None
    """Participating justices. CoA only."""

    case_citation: str | None = None
    """Case citation if assigned."""


class CaAppAttorney(ScrapedData):
    """Attorney representation record."""

    name: str
    """Attorney name."""

    firm: str | None = None
    """Firm or organization name."""

    address: str | None = None
    """Full address (multi-line joined)."""


class CaAppParty(ScrapedData):
    """A party in the case."""

    name: str
    """Party name."""

    role: str | None = None
    """Role in the case (e.g., 'Defendant and Appellant')."""

    address: str | None = None
    """Party address if provided."""

    attorneys: list[CaAppAttorney] = []
    """Attorneys representing this party."""


class CaAppTrialCourtInfo(ScrapedData):
    """Trial court information from the Trial Court tab (CoA cases)."""

    trial_court_name: str | None = None
    """E.g., 'San Francisco County Superior Court - Main'."""

    county: str | None = None
    """County name."""

    trial_court_case_number: str | None = None
    """Trial court case number."""

    trial_court_judge: str | None = None
    """Name of the trial court judge."""

    judgment_date: date | None = None
    """Trial court judgment date."""


class CaAppCoaCaseLink(ScrapedData):
    """A single Court of Appeal case linked from an SC Lower Court tab."""

    district_division: str | None = None
    """Court of Appeal district/division (e.g., 'Fourth Appellate District, Division Three')."""

    case_number: str | None = None
    """Court of Appeal case number (e.g., 'G001513')."""

    case_link: str | None = None
    """URL to the Court of Appeal case page."""

    is_lead: bool = False
    """Whether this is the lead CoA case."""


class CaAppLowerCourtInfo(ScrapedData):
    """Lower court information from the Lower Court tab (SC cases).

    An SC case may have multiple linked CoA cases and multiple trial
    courts (e.g., consolidated appeals from different lower courts).
    """

    coa_cases: list[CaAppCoaCaseLink] = []
    """Court of Appeal cases linked from this SC case."""

    coa_disposition: str | None = None
    """CoA disposition (e.g., 'Affirmed in full')."""

    coa_disposition_date: date | None = None
    """CoA disposition date."""

    trial_courts: list[dict[str, str | None]] = []
    """Trial court entries, each with 'name' and 'case_number' keys."""


class CaAppOpinionFile(ScrapedData):
    """An opinion file (PDF / DOC / DOCX) archived from a case summary page.

    Yielded separately from ``CaAppDocket`` so that consumers can stitch the
    file back to its docket via ``docket_id`` + ``court_id``. One instance
    per file, so a case with both PDF and DOC produces two records.
    """

    docket_id: str
    """Case number (e.g., 'A081492'), matches CaAppDocket.docket_id."""

    court_id: str
    """CourtListener court ID, matches CaAppDocket.court_id."""

    document_type: str
    """File extension, lowercased (e.g., 'pdf', 'doc', 'docx')."""

    source_url: str
    """Original URL the file was downloaded from."""

    local_path: str | None = None
    """Path returned by the archive handler. None if the download was skipped."""


class CaAppDocket(ScrapedData):
    """Main output model -- a complete California appellate case docket."""

    # Identifiers
    docket_id: str
    """Case number (e.g., 'S295804', 'A170000')."""

    court_id: str
    """CourtListener court ID (e.g., 'cal', 'calctapp1d')."""

    # Case metadata
    case_name: str
    """Case caption (e.g., 'PEOPLE v. SMITH')."""

    case_type: str | None = None
    """Case category (SC) or case type (CoA)."""

    division: str | None = None
    """Division number or name (e.g., '4', 'SF')."""

    date_filed: date | None = None
    """Filing date (CoA) or start date (SC)."""

    completion_date: date | None = None
    """Completion date. CoA only."""

    case_status: str | None = None
    """Case status (e.g., 'closed; remittitur issued'). SC only."""

    oral_argument_date: str | None = None
    """Oral argument date/time. CoA only."""

    issues: str | None = None
    """Issues text. SC only."""

    case_citation: str | None = None
    """Case citation if assigned."""

    # Opinion links (SC only)
    opinion_pdf_url: str | None = None
    """URL to opinion PDF."""

    opinion_docx_url: str | None = None
    """URL to opinion DOCX."""

    # Related case numbers
    coa_case_numbers: list[str] = []
    """Court of Appeal case numbers linked from SC case."""

    trial_court_case_numbers: list[str] = []
    """Trial court case numbers associated with this CoA case.

    Usually one entry (taken from the case summary "Trial Court Case"
    field). When a docket number matches multiple rows on the search-
    results page (consolidated lower-court matters under a single CoA
    docket), all of the row's trial-court numbers are collected here.
    """

    cross_referenced_cases: list[str] = []
    """Cross-referenced case numbers."""

    # Nested data
    entries: list[CaAppDocketEntry] = []
    """Docket entries from the Register of Actions."""

    briefs: list[CaAppBrief] = []
    """Brief filings."""

    dispositions: list[CaAppDisposition] = []
    """Disposition records."""

    parties: list[CaAppParty] = []
    """Parties and their attorneys."""

    trial_court_info: CaAppTrialCourtInfo | None = None
    """Trial court details. CoA only."""

    lower_court_info: CaAppLowerCourtInfo | None = None
    """Lower court details. SC only."""

    source_url: str | None = None
    """URL of the case summary page."""

    subscription_urls: list[str] = []
    """URLs to subscribe to email notifications for this case."""
