from __future__ import annotations

from datetime import date

from jkent.common.data_models import ScrapedData

from juriscraper.state.common_models import CleanString, HarmonizedCaseName

# Court ID mapping: CourtListener ID → display name. IDs match the classic
# juriscraper opinion scrapers (juriscraper/opinions/.../state/calctapp_*),
# which give each Fourth-District division its own id — so every site
# case-number prefix maps to a distinct CourtListener court.
COURT_IDS: dict[str, str] = {
    "cal": "California Supreme Court",
    "calctapp_1st": "California Court of Appeal, First Appellate District",
    "calctapp_2nd": "California Court of Appeal, Second Appellate District",
    "calctapp_3rd": "California Court of Appeal, Third Appellate District",
    "calctapp_4th_div1": "California Court of Appeal, Fourth Appellate District, Division 1",
    "calctapp_4th_div2": "California Court of Appeal, Fourth Appellate District, Division 2",
    "calctapp_4th_div3": "California Court of Appeal, Fourth Appellate District, Division 3",
    "calctapp_5th": "California Court of Appeal, Fifth Appellate District",
    "calctapp_6th": "California Court of Appeal, Sixth Appellate District",
}

# Site internal court config: prefix → (dist param, CourtListener ID)
COURT_CONFIG: dict[str, tuple[str, str]] = {
    "S": ("0", "cal"),
    "A": ("1", "calctapp_1st"),
    "B": ("2", "calctapp_2nd"),
    "C": ("3", "calctapp_3rd"),
    "D": ("41", "calctapp_4th_div1"),
    "E": ("42", "calctapp_4th_div2"),
    "G": ("43", "calctapp_4th_div3"),
    "F": ("5", "calctapp_5th"),
    "H": ("6", "calctapp_6th"),
}

BASE_URL = "https://appellatecases.courtinfo.ca.gov"
SEARCH_URL = f"{BASE_URL}/search.cfm"


class CaAppCaseUnavailable(ScrapedData):
    """Yielded when a speculative case number search returns 'Case Not Found'.

    This may indicate the case doesn't exist, the number was never assigned,
    or the case is confidential.
    """

    docket_number: str
    """The case number that was searched (e.g., 'H000001')."""

    court: str
    """CourtListener court ID (e.g., 'calctapp_6th')."""


class CaAppDocketEntry(ScrapedData):
    """A single entry from the Docket (Register of Actions) tab.

    Maps to CourtListener ``DocketEntry``.
    """

    date_filed: date | None = None
    """Date of the docket entry (mm/dd/yyyy on site)."""

    description: CleanString
    """Description of the action (e.g., 'Petition for review filed')."""

    notes: CleanString | None = None
    """Additional notes, may contain party/attorney names."""


class CaAppBrief(ScrapedData):
    """A brief filing record from the Briefs tab."""

    brief_type: CleanString
    """Type/description (e.g., 'Opening brief on the merits filed')."""

    date_filed: date | None = None
    """Date the brief was filed."""

    party_attorney: CleanString | None = None
    """Party and attorney associated with the brief."""

    notes: CleanString | None = None
    """Additional notes."""


class CaAppDisposition(ScrapedData):
    """Disposition information. Structure differs between SC and CoA.

    For Supreme Court: date + description (e.g., "Opinion: Affirmed").
    For Courts of Appeal: structured fields including type, publication
    status, author, and participants.
    """

    description: CleanString
    """Disposition description (e.g., 'Voluntary dismissal')."""

    disposition_date: date | None = None
    """Disposition date."""

    disposition_type: CleanString | None = None
    """E.g., 'Final'. CoA only."""

    publication_status: CleanString | None = None
    """Publication status. CoA only."""

    author: CleanString | None = None
    """Opinion author. CoA only."""

    participants: CleanString | None = None
    """Participating justices. CoA only."""

    case_citation: CleanString | None = None
    """Case citation if assigned."""


class CaAppAttorney(ScrapedData):
    """Attorney representation record.

    Maps to CourtListener ``Attorney`` (+ ``AttorneyOrganization`` for the
    firm).
    """

    name: CleanString
    """Attorney name."""

    firm: CleanString | None = None
    """Firm or organization name."""

    address: CleanString | None = None
    """Full address (multi-line joined)."""


class CaAppParty(ScrapedData):
    """A party in the case.

    Maps to CourtListener ``Party`` (+ ``PartyType`` for the role on this
    docket).
    """

    name: CleanString
    """Party name."""

    role: CleanString | None = None
    """Role in the case (e.g., 'Defendant and Appellant')."""

    address: CleanString | None = None
    """Party address if provided."""

    attorneys: list[CaAppAttorney] = []
    """Attorneys representing this party."""


class CaAppTrialCourtInfo(ScrapedData):
    """Trial court information from the Trial Court tab (CoA cases).

    Maps to CourtListener ``OriginatingCourtInformation`` /
    ``TrialCourtData``.
    """

    trial_court_name: CleanString | None = None
    """E.g., 'San Francisco County Superior Court - Main' (CL ``court_name``)."""

    county: CleanString | None = None
    """County name."""

    trial_court_case_number: str | None = None
    """Trial court case number (CL ``docket_number_raw``)."""

    trial_court_judge: CleanString | None = None
    """Name of the trial court judge (CL ``judge_str``)."""

    judgment_date: date | None = None
    """Trial court judgment date (CL ``date_judgment``)."""


class CaAppCoaCaseLink(ScrapedData):
    """A single Court of Appeal case linked from an SC Lower Court tab."""

    district_division: CleanString | None = None
    """Court of Appeal district/division (e.g., 'Fourth Appellate District, Division Three')."""

    docket_number: str | None = None
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

    coa_disposition: CleanString | None = None
    """CoA disposition (e.g., 'Affirmed in full')."""

    coa_disposition_date: date | None = None
    """CoA disposition date."""

    trial_courts: list[dict[str, str | None]] = []
    """Trial court entries, each with 'name' and 'case_number' keys."""


class CaAppOpinionFile(ScrapedData):
    """An opinion file (PDF / DOC / DOCX) archived from a case summary page.

    Yielded separately from ``CaAppDocket`` so that consumers can stitch the
    file back to its docket via ``docket_number`` + ``court``. One instance
    per file, so a case with both PDF and DOC produces two records. Maps to
    CourtListener ``RECAPDocument``.
    """

    docket_number: str
    """Case number (e.g., 'A081492'), matches CaAppDocket.docket_number."""

    court: str
    """CourtListener court ID, matches CaAppDocket.court."""

    document_type: str
    """File extension, lowercased (e.g., 'pdf', 'doc', 'docx')."""

    source_url: str
    """Original URL the file was downloaded from."""

    local_path: str | None = None
    """Path returned by the archive handler. None if the download was skipped."""


class CaAppDocket(ScrapedData):
    """Main output model -- a complete California appellate case docket.

    Maps to CourtListener ``Docket`` (+ its per-court side tables).
    """

    # Identifiers
    docket_number: str
    """Case number (e.g., 'S295804', 'A170000')."""

    court: str
    """CourtListener court ID (e.g., 'cal', 'calctapp_1st')."""

    # Case metadata
    case_name: HarmonizedCaseName
    """Case caption (e.g., 'PEOPLE v. SMITH')."""

    case_type: CleanString | None = None
    """Case category (SC) or case type (CoA)."""

    division: CleanString | None = None
    """Division number or name (e.g., '4', 'SF')."""

    date_filed: date | None = None
    """Filing date (CoA) or start date (SC)."""

    date_terminated: date | None = None
    """Completion date. CoA only (CL ``date_terminated``)."""

    case_status: CleanString | None = None
    """Case status (e.g., 'closed; remittitur issued'). SC only."""

    date_argued: str | None = None
    """Oral argument date/time, raw text. CoA only (CL ``date_argued``)."""

    issues: CleanString | None = None
    """Issues text. SC only."""

    case_citation: CleanString | None = None
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

    source_entry_point: str | None = None
    """Entry point used to reach this docket (e.g., 'dockets_by_number')."""

    subscription_urls: list[str] = []
    """URLs to subscribe to email notifications for this case."""
