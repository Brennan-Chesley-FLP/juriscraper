"""Data models for Connecticut appellate courts scraper.

These models extend ConsumerModel types from base.py to capture
Connecticut Supreme Court and Appellate Court opinion, oral argument,
and docket data.

Mapping to base.py types:
- ConnOpinion -> Opinion (individual opinion document)
- ConnOpinionCluster -> OpinionCluster (group of related opinions)
- ConnOralArgument -> Audio (oral argument recording)
- ConnDocket -> Docket (case docket information)
- ConnDocketEntry -> DocketEntry (individual docket entry/filing)

Supported courts:
- conn: Connecticut Supreme Court (docket prefix: SC)
- connappct: Connecticut Appellate Court (docket prefix: AC)
"""

from __future__ import annotations

from datetime import date
from typing import Annotated

from pydantic import BaseModel

from juriscraper.scraper_driver.common.models.base import (
    Audio,
    Docket,
    DocketEntry,
    Opinion,
    OpinionCluster,
)
from juriscraper.scraper_driver.common.searchable import (
    DateRange,
    SetFilter,
    SpeculativeID,
    UniqueMatch,
)

# Court ID mapping
COURT_IDS = {
    "conn": "Connecticut Supreme Court",
    "connappct": "Connecticut Appellate Court",
}

# Docket prefixes by court
DOCKET_PREFIX_TO_COURT = {
    "SC": "conn",
    "AC": "connappct",
}

COURT_TO_DOCKET_PREFIX = {
    "conn": "SC",
    "connappct": "AC",
}


class ConnOpinion(Opinion):
    """An individual opinion document from Connecticut appellate courts.

    Extends Opinion from base.py with required fields for CT courts.
    """

    download_url: str  # Required - URL to PDF
    """URL to the opinion PDF"""

    type: str  # Required - opinion type
    """Opinion type: 'majority', 'dissent', 'concurrence', etc."""

    local_path: str | None = None
    """Local filesystem path where the PDF was downloaded (set by driver)"""


class ConnOpinionCluster(OpinionCluster):
    """A cluster of opinions from Connecticut appellate courts.

    This is the main output type yielded by the scraper.
    Each cluster represents a case that may have multiple opinions
    (majority, dissents, concurrences, appendices).

    Supports both Connecticut Supreme Court (conn) and
    Connecticut Appellate Court (connappct).
    """

    # === Searchable fields ===
    # Note: Base OpinionCluster has docket_id: int | None but CT uses string docket numbers
    docket_id: Annotated[str, UniqueMatch()]  # type: ignore[assignment]
    """Docket number (e.g., 'SC21125' for Supreme Court, 'AC12345' for Appellate)"""

    court_id: Annotated[str, SetFilter()]  # Required, searchable
    """Court identifier: 'conn' (Supreme Court) or 'connappct' (Appellate Court)"""

    date_filed: Annotated[date, DateRange()]  # Required, searchable
    """Publication date in Connecticut Law Journal"""

    # === Required fields from base ===
    case_name: str  # Required
    """Case name (e.g., 'State v. Enrrique H.')"""

    # === Related data ===
    opinions: list[ConnOpinion] = []
    """All opinions in this cluster (majority, dissents, concurrences)"""

    # === Source tracking ===
    source_url: str | None = None
    """URL of the archive page where this was found"""

    publication_year: int | None = None
    """Year of publication (from archive page)"""

    law_journal_date: str | None = None
    """Full text of publication date header (e.g., 'December 30, 2025')"""

    publication_name: str | None = None
    """Name of the publication (e.g., 'Connecticut Law Journal', 'the Law Journal')"""


class ConnOralArgument(Audio):
    """An oral argument recording from Connecticut appellate courts.

    Extends Audio from base.py with required fields for CT courts.
    """

    # === Searchable fields ===
    # Note: Using docket_number (str) instead of base docket_id (int) for CT docket strings
    docket_number: Annotated[str, UniqueMatch()]  # Required, searchable
    """Docket number (e.g., 'SC21125' for Supreme Court, 'AC47230' for Appellate)"""

    court_id: Annotated[str, SetFilter()]  # Required, searchable
    """Court identifier: 'conn' (Supreme Court) or 'connappct' (Appellate Court)"""

    date_argued: Annotated[date, DateRange()]  # Required, searchable
    """Date the oral argument was heard"""

    # === Required fields ===
    case_name: str  # Required
    """Case name (e.g., 'STATE OF CONNECTICUT v. HARALAMBOS SIDIROPOULOS')"""

    download_url: str  # Required
    """URL to the MP3 audio file"""

    # === Optional fields ===
    local_path: str | None = None
    """Local filesystem path where the audio was downloaded (set by driver)"""

    source_url: str | None = None
    """URL of the page where this was found"""

    court_year: str | None = None
    """Court year (e.g., '2025-2026')"""

    term: str | None = None
    """Court term (e.g., 'First Term', 'Second Term')"""

    case_detail_url: str | None = None
    """URL to the case detail page on appellateinquiry.jud.ct.gov"""

    audio_id: int | None = None
    """Internal audio ID from the CT system (e.g., 2365 from PlayAudio.aspx?ID=2365)"""


class ConnPreliminaryPaper(BaseModel):
    """Preliminary paper information for a party.

    Represents the preliminary papers filed by a party including statement
    of issues, clerk appendix designation, transcript certificate, etc.
    """

    party_name: str
    """Name of the party who filed the preliminary papers"""

    preliminary_statement_of_issues: date | None = None
    """Date the Preliminary Statement of Issues was filed"""

    designation_clerk_appendix: date | None = None
    """Date the Designation of Proposed Contents of Clerk Appendix was filed"""

    certificate_transcript_received: date | None = None
    """Date the Certificate re Transcript Received was filed"""

    docketing_statement: date | None = None
    """Date the Docketing Statement was filed"""

    pac_statement: date | None = None
    """Date the PAC Statement was filed"""

    constitutionality_notice: date | None = None
    """Date the Constitutionality Notice was filed"""

    sealing_notice: date | None = None
    """Date the Sealing Notice was filed"""

    certificate_interested_entities: date | None = None
    """Date the Certificate of Interested Entities was filed"""


class ConnTranscriptInfo(BaseModel):
    """Transcript and exhibit information for a party.

    Represents transcript ordering and delivery information for a party.
    """

    party_name: str
    """Name of the party"""

    transcripts_ordered: date | None = None
    """Date transcripts were ordered"""

    estimated_delivery_date: date | None = None
    """Estimated delivery date for transcripts"""

    delivered_to_party: date | None = None
    """Date transcripts were delivered to party"""

    pages: int | None = None
    """Number of transcript pages"""

    delivered_to_court: date | None = None
    """Date transcripts were delivered to court"""


class ConnDocketEntry(DocketEntry):
    """An individual docket entry from Connecticut appellate courts.

    Represents a single filing/activity in the Case Activity section.
    Yielded separately from the parent ConnDocket to simplify document downloads.
    """

    # === Foreign key to parent docket ===
    docket_id: Annotated[str, UniqueMatch()]  # type: ignore[assignment]
    """Parent docket number (e.g., 'AC 48343' for Appellate, 'SC 21125' for Supreme)"""

    # === Required fields ===
    activity_type: str  # Required - e.g., "APPEAL", "MOTION", "ORDER"
    """Activity type (e.g., 'APPEAL', 'MOTION', 'ORDER', 'DISPOSITION')"""

    # === Optional fields ===
    number: str | None = None
    """Activity number (e.g., 'AC 48343', 'AC 243237')"""

    date_filed: date | None = None
    """Date the activity was filed"""

    initiated_by: str | None = None
    """Who initiated this activity (party name or 'Court')"""

    description: str | None = None
    """Description of the activity"""

    action: str | None = None
    """Action taken (e.g., 'Filed', 'Granted', 'Disposed')"""

    action_date: date | None = None
    """Date of the action"""

    notice_date: date | None = None
    """Date notice was sent"""

    document_url: str | None = None
    """URL to the PDF document (if available)"""

    document_local_path: str | None = None
    """Local file path to the downloaded PDF document"""

    is_paperless: bool = False
    """Whether this is a paperless filing"""


class ConnDocketUnavailable(Docket):
    """Represents an unavailable docket from Connecticut appellate courts.

    These are cases that exist in the system but are not available for
    public viewing. The CaseDetail page shows a message like:
    "AC 48093 - This case is not available at this time."

    This is a distinct model from ConnDocket because these pages contain
    minimal information - just the docket number and an unavailable message.
    """

    # === Searchable fields ===
    crn: Annotated[int, SpeculativeID()]  # Required, searchable
    """Case Record Number - internal monotonically increasing ID used by CT courts"""

    docket_id: Annotated[str, UniqueMatch()]  # Required, searchable
    """Docket number (e.g., 'AC 48343' for Appellate, 'SC 21125' for Supreme)"""

    court_id: Annotated[str, SetFilter()]  # Required, searchable
    """Court identifier: 'conn' (Supreme Court) or 'connappct' (Appellate Court)"""

    # === Source tracking ===
    source_url: str | None = None
    """URL of the CaseDetail page"""

    message: str | None = None
    """The unavailable message text from the page"""


class ConnDocket(Docket):
    """A docket from Connecticut appellate courts.

    Represents a complete case with all its metadata from the
    appellateinquiry.jud.ct.gov CaseDetail page.
    """

    # === Searchable fields ===
    crn: Annotated[int, SpeculativeID()]  # Required, searchable
    """Case Record Number - internal monotonically increasing ID used by CT courts"""

    docket_id: Annotated[str, UniqueMatch()]  # Required, searchable
    """Docket number (e.g., 'AC 48343' for Appellate, 'SC 21125' for Supreme)"""

    court_id: Annotated[str, SetFilter()]  # Required, searchable
    """Court identifier: 'conn' (Supreme Court) or 'connappct' (Appellate Court)"""

    date_filed: Annotated[date | None, DateRange()] = (
        None  # Optional, searchable
    )
    """Date the appeal was filed"""

    # === Required fields ===
    case_name: str  # Required
    """Case name (e.g., 'DEUTSCHE BANK v. ALVIN POLLARD ET AL.')"""

    status: str  # Required
    """Case status (e.g., 'Disposed', 'Pending', 'Disposed/Transfer')"""

    # === Appeal case information ===
    appeal_by: str | None = None
    """Who filed the appeal (e.g., 'Defendant', 'Plaintiff')"""

    disposition_method: str | None = None
    """How the case was disposed (e.g., 'Party Motion', 'Transferred')"""

    argued_date: date | None = None
    """Date oral arguments were heard"""

    disposition_date: date | None = None
    """Date the case was disposed"""

    submitted_on_briefs_date: date | None = None
    """Date submitted on briefs"""

    cite: str | None = None
    """Citation (if published)"""

    panel: str | None = None
    """Panel of judges"""

    response_due_date: date | None = None
    """Response to docket due date"""

    # === Trial court information ===
    trial_court_docket_number: str | None = None
    """Trial court docket number (e.g., 'HHDCV156062121S')"""

    trial_court_docket_url: str | None = None
    """URL to trial court case detail"""

    judgment_for: str | None = None
    """Who won at trial court (e.g., 'Plaintiff', 'Defendant')"""

    trial_court: str | None = None
    """Trial court name (e.g., 'JD COURTHOUSE AT HARTFORD')"""

    trial_judge: str | None = None
    """Trial judge name(s)"""

    judgment_date: date | None = None
    """Date of trial court judgment"""

    case_type: str | None = None
    """Case type (e.g., 'CIVIL - FORECLOSURE')"""

    # === Related data ===
    # Note: ConnDocketEntry objects are yielded separately with docket_id reference
    # to avoid complex accumulated_data threading for document downloads

    parties: list[dict] = []
    """List of parties with their attorneys and roles"""

    preliminary_papers: list[ConnPreliminaryPaper] = []
    """Preliminary papers filed by each party"""

    transcripts: list[ConnTranscriptInfo] = []
    """Transcript information for each party"""

    exhibits_received_by_court: date | None = None
    """Date exhibits were received by the court"""

    # === Source tracking ===
    source_url: str | None = None
    """URL of the CaseDetail page"""

    subscription_url: str | None = None
    """URL to subscribe to email notifications for this case"""

    is_efiled: bool = False
    """Whether the case was e-filed"""


class ConnTrialCaseUnavailable(Docket):
    """Represents an unavailable trial court case from civilinquiry.jud.ct.gov.

    When an appellate docket links to a trial court case that no longer exists
    in the civil inquiry system, the page returns a redirect or empty content.
    This model captures the trial court docket number (from the appellate docket)
    so we know which cases are unavailable.
    """

    trial_docket_id: str
    """Trial court docket number (e.g., 'HHDCV910391250S')"""

    appellate_docket_id: str | None = None
    """Associated appellate docket number that linked to this trial case"""

    source_url: str | None = None
    """URL of the trial court page that was attempted"""

    message: str | None = None
    """Description of why the case is unavailable"""


class ConnTrialCourtParty(BaseModel):
    """Party information from Connecticut trial court docket.

    Represents a party and their attorney(s) on a trial court case
    from civilinquiry.jud.ct.gov.
    """

    party_number: str
    """Party identifier (e.g., 'P-01', 'D-01', 'L-01')"""

    name: str
    """Party name"""

    party_type: str | None = None
    """Party type (e.g., 'Plaintiff', 'Defendant', 'For Notice Only')"""

    self_represented: bool = False
    """Whether party is self-represented (no attorney)"""

    attorneys: list[dict] = []
    """List of attorneys with name, juris_number, firm, address, file_date"""


class ConnTrialCourtDocketEntry(DocketEntry):
    """Individual entry from Connecticut trial court docket.

    Represents a single filing/document from the "Motions/Pleadings/Documents/
    Case Status" section of civilinquiry.jud.ct.gov.
    """

    # === Foreign key to parent docket ===
    trial_docket_id: Annotated[str, UniqueMatch()]
    """Parent trial court docket number (e.g., 'HHD-CV23-5076142-S')"""

    # === Entry fields ===
    conn_entry_number: str | None = None
    """Entry number (e.g., '100.30', '101.00')"""

    date_filed: date | None = None
    """Date the entry was filed"""

    filed_by: str | None = None
    """Who filed this entry (e.g., 'P', 'D', 'C' for Plaintiff, Defendant, Court)"""

    description: str | None = None
    """Description of the filing (e.g., 'SUMMONS', 'COMPLAINT', 'MOTION')"""

    additional_description: str | None = None
    """Additional description or notes"""

    result: str | None = None
    """Result of motion/filing (e.g., 'Granted 8/28/2023 HON DAVID SHERIDAN')"""

    arguable: bool = False
    """Whether this is an arguable motion"""

    document_url: str | None = None
    """URL to the document (DocumentInquiry.aspx?DocumentNo=XXX)"""

    document_local_path: str | None = None
    """Local file path to the downloaded document"""


class ConnTrialCourtDocket(Docket):
    """Connecticut Superior Court (trial court) docket.

    Represents a trial court case from civilinquiry.jud.ct.gov.
    These cases can be linked from appellate dockets via trial_court_docket_url.
    """

    # === Searchable fields ===
    trial_docket_id: Annotated[str, UniqueMatch()]
    """Trial court docket number (e.g., 'HHD-CV23-5076142-S')"""

    appellate_docket_id: str | None = None
    """Associated appellate docket number if navigated from appellate case"""

    # === Required fields ===
    case_name: str
    """Case name (e.g., 'BALTAS, JOE J.  v. CONNECTICUT OF DEPARTMENT OF CORRECTIONS Et Al')"""

    # === Case Information ===
    case_type: str | None = None
    """Case type code (e.g., 'P90')"""

    case_type_description: str | None = None
    """Full case type description (e.g., 'P90 - Property - All other')"""

    suffix: str | None = None
    """Case suffix"""

    court_location: str | None = None
    """Court location (e.g., 'HARTFORD JD')"""

    list_type: str | None = None
    """List type classification"""

    # === Dates ===
    file_date: date | None = None
    """Date the case was filed"""

    return_date: date | None = None
    """Return date"""

    disposition_date: date | None = None
    """Date of disposition"""

    last_updated: date | None = None
    """Date information was last updated"""

    # === Disposition ===
    disposition: str | None = None
    """Disposition description (e.g., 'JUDGMENT OF DISMISSAL')"""

    judge: str | None = None
    """Judge name"""

    # === Related data ===
    # Note: ConnTrialCourtDocketEntry objects are yielded separately
    # with trial_docket_id reference to support document downloads

    parties: list[ConnTrialCourtParty] = []
    """List of parties and their attorneys"""

    # === Source tracking ===
    source_url: str | None = None
    """URL of the trial court docket page"""


# Backwards compatibility aliases
ConnSupremeCourtOpinion = ConnOpinion
ConnSupremeCourtOpinionCluster = ConnOpinionCluster
