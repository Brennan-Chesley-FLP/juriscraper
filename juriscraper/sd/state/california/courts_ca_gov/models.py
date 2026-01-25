"""Data models for California appellate courts scraper.

These models extend ConsumerModel types from base.py to capture
California Supreme Court and Courts of Appeal data.

Mapping to base.py types:
- CalOpinion -> Opinion (individual opinion document)
- CalOpinionCluster -> OpinionCluster (group of related opinions)
- CalSupremeBriefDocket -> Docket (case with briefs)
- CalSupremeBriefEntry -> DocketEntry (individual brief filing)
- CalSupremeOralArgument -> Audio (oral argument webcast)

Supported courts:
- cal: California Supreme Court (case prefix: S)
- calctapp1d: 1st District Court of Appeal (case prefix: A)
- calctapp2d: 2nd District Court of Appeal (case prefix: B)
- calctapp3d: 3rd District Court of Appeal (case prefix: C)
- calctapp4d: 4th District Court of Appeal, Division 1/2/3 (case prefix: D/E/G)
- calctapp5d: 5th District Court of Appeal (case prefix: F)
- calctapp6d: 6th District Court of Appeal (case prefix: H)
- calappdeptsuper: Appellate Division (various prefixes)
"""

from __future__ import annotations

from datetime import date
from typing import Annotated

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

# Court ID mapping - maps case number prefix to court_id
# S = Supreme Court, A = 1st DCA, B = 2nd DCA, C = 3rd DCA,
# D = 4th DCA Div 1, E = 4th DCA Div 2, G = 4th DCA Div 3,
# F = 5th DCA, H = 6th DCA
CASE_PREFIX_TO_COURT = {
    "S": "cal",
    "A": "calctapp1d",
    "B": "calctapp2d",
    "C": "calctapp3d",
    "D": "calctapp4d",  # 4th District, Division One
    "E": "calctapp4d",  # 4th District, Division Two
    "G": "calctapp4d",  # 4th District, Division Three
    "F": "calctapp5d",
    "H": "calctapp6d",
}

# District ID mapping for search URLs
# URL: https://appellatecases.courtinfo.ca.gov/search.cfm?dist={district_id}
COURT_TO_DISTRICT_ID = {
    "cal": 0,  # Supreme Court
    "calctapp1d": 1,  # 1st District
    "calctapp2d": 2,  # 2nd District
    "calctapp3d": 3,  # 3rd District
    "calctapp4d_div1": 41,  # 4th District, Division 1
    "calctapp4d_div2": 42,  # 4th District, Division 2
    "calctapp4d_div3": 43,  # 4th District, Division 3
    "calctapp5d": 5,  # 5th District
    "calctapp6d": 6,  # 6th District
}

# Case prefix to district ID (for speculative enumeration)
CASE_PREFIX_TO_DISTRICT_ID = {
    "S": 0,  # Supreme Court
    "A": 1,  # 1st District
    "B": 2,  # 2nd District
    "C": 3,  # 3rd District
    "D": 41,  # 4th District, Division 1
    "E": 42,  # 4th District, Division 2
    "G": 43,  # 4th District, Division 3
    "F": 5,  # 5th District
    "H": 6,  # 6th District
}

# Source names from dropdown values
SOURCE_TO_COURT = {
    "Supreme Court": "cal",
    "1st District Court of Appeal": "calctapp1d",
    "2nd District Court of Appeal": "calctapp2d",
    "3rd District Court of Appeal": "calctapp3d",
    "4th District Court of Appeal, Division One": "calctapp4d",
    "4th District Court of Appeal, Division Two": "calctapp4d",
    "4th District Court of Appeal, Division Three": "calctapp4d",
    "5th District Court of Appeal": "calctapp5d",
    "6th District Court of Appeal": "calctapp6d",
    "Appellate Division": "calappdeptsuper",
}

COURT_IDS = {
    "cal": "California Supreme Court",
    "calctapp1d": "California Court of Appeal, First Appellate District",
    "calctapp2d": "California Court of Appeal, Second Appellate District",
    "calctapp3d": "California Court of Appeal, Third Appellate District",
    "calctapp4d": "California Court of Appeal, Fourth Appellate District",
    "calctapp5d": "California Court of Appeal, Fifth Appellate District",
    "calctapp6d": "California Court of Appeal, Sixth Appellate District",
    "calappdeptsuper": "California Superior Court, Appellate Division",
}


class CalOpinion(Opinion):
    """An individual opinion document from California appellate courts.

    Extends Opinion from base.py with required fields for CA courts.
    """

    download_url: str  # Required - URL to PDF
    """URL to the opinion PDF"""

    type: str = "majority"
    """Opinion type: 'majority' for main opinion (CA doesn't typically separate)"""

    local_path: str | None = None
    """Local filesystem path where the PDF was downloaded (set by driver)"""


class CalOpinionCluster(OpinionCluster):
    """A cluster of opinions from California appellate courts.

    This is the main output type yielded by the scraper.
    Each cluster represents a case opinion. California typically
    publishes opinions as single PDFs (not separated by majority/dissent).

    Supports California Supreme Court and all Districts of the
    Courts of Appeal.
    """

    # === Searchable fields ===
    case_number: Annotated[str, UniqueMatch()]  # Required, searchable
    """Case number (e.g., 'S275272M' for Supreme Court, 'A172153' for 1st DCA)"""

    court_id: Annotated[str, SetFilter()]  # Required, searchable
    """Court identifier: 'cal', 'calctapp1d', 'calctapp2d', etc."""

    date_filed: Annotated[date, DateRange()]  # Required, searchable
    """Date the opinion was filed/published"""

    # === Required fields from base ===
    case_name: str  # Required
    """Case name (e.g., 'L.A. Police Protective League v. City of L.A.')"""

    # === Related data ===
    opinions: list[CalOpinion] = []
    """All opinions in this cluster (typically just one for CA)"""

    # === California-specific fields ===
    precedential_status: str = "Published"
    """Publication status: 'Published' or 'Unpublished'"""

    source_court: str | None = None
    """Source court name as shown on website (e.g., '2nd District Court of Appeal')"""

    division: str | None = None
    """Court division if applicable (e.g., 'Division One', 'CA2/6')"""

    related_cases: list[str] = []
    """Related case numbers (some opinions have consolidated/related cases)"""

    case_info_url: str | None = None
    """URL to case information search page for this case"""

    other_formats_url: str | None = None
    """URL to other formats page for this opinion"""

    # === Source tracking ===
    source_url: str | None = None
    """URL of the opinions list page where this was found"""


# =============================================================================
# Supreme Court Briefs Models
# =============================================================================


class CalSupremeBriefEntry(DocketEntry):
    """An individual brief filing from California Supreme Court.

    Represents a single brief document (PDF) filed in a Supreme Court case.
    Examples: Petition for Review, Opening Brief on the Merits, Amicus Brief.
    """

    description: str
    """Brief description (e.g., 'Appellant's Opening Brief on the Merits')"""

    date_filed: date
    """Date the brief was filed"""

    download_url: str
    """URL to download the PDF"""

    local_path: str | None = None
    """Local filesystem path where the PDF was downloaded"""

    brief_type: str | None = None
    """Categorized brief type (petition, opening, answer, reply, amicus, etc.)"""


class CalSupremeBriefDocket(Docket):
    """A Supreme Court case docket containing briefs.

    Represents a case that has been argued (or scheduled for argument)
    before the California Supreme Court, with all associated briefs.

    This is the main output type yielded by the briefs scraper.
    """

    # === Searchable fields ===
    case_number: Annotated[str, UniqueMatch()]
    """Case number (e.g., 'S289430')"""

    court_id: Annotated[str, SetFilter()] = "cal"
    """Court identifier - always 'cal' for Supreme Court"""

    oral_argument_date: Annotated[date, DateRange()]
    """Date of the oral argument session"""

    # === Required fields ===
    case_name: str
    """Case name (e.g., 'IN RE Z.G.')"""

    # === Related data ===
    briefs: list[CalSupremeBriefEntry] = []
    """All briefs filed in this case"""

    # === California Supreme Court specific fields ===
    assigned_justice: str | None = None
    """Assigned justice pro tempore (e.g., 'Baltodano, J.')"""

    consolidated_with: list[str] = []
    """List of case numbers this case is consolidated with"""

    # === Source tracking ===
    source_url: str | None = None
    """URL of the briefs page where this was found"""

    session_url: str | None = None
    """URL of the oral argument session page"""


# =============================================================================
# Supreme Court Oral Arguments Models
# =============================================================================


class CalSupremeOralArgument(Audio):
    """An oral argument webcast from California Supreme Court.

    Represents a recorded oral argument available via the Granicus
    video player, with embedding information and metadata.

    This is the main output type yielded by the oral arguments scraper.
    """

    # === Searchable fields ===
    case_number: Annotated[str, UniqueMatch()]
    """Case number (e.g., 'S286493')"""

    court_id: Annotated[str, SetFilter()] = "cal"
    """Court identifier - always 'cal' for Supreme Court"""

    date_argued: Annotated[date, DateRange()]
    """Date the oral argument was held"""

    # === Required fields ===
    case_name: str
    """Case name (e.g., 'People v. Morgan (Henry)')"""

    granicus_url: str
    """URL to the Granicus video player page"""

    # === Video/embed information ===
    embed_url: str | None = None
    """Embeddable URL for the video (from Granicus embed code)"""

    video_download_url: str | None = None
    """Direct download URL for the video file (MP4)"""

    clip_id: str | None = None
    """Granicus clip ID extracted from URL"""

    meta_id: str | None = None
    """Granicus meta_id for this specific case within a session"""

    # === Related content ===
    opinion_pdf_url: str | None = None
    """URL to the opinion PDF, if the opinion has been issued"""

    # === Additional metadata ===
    assigned_justice: str | None = None
    """Assigned justice pro tempore, if listed"""

    is_automatic_appeal: bool = False
    """Whether this is an automatic appeal (death penalty case)"""

    consolidated_cases: list[str] = []
    """List of consolidated case numbers, if any"""

    # === Source tracking ===
    source_url: str | None = None
    """URL of the webcast library page where this was found"""


# =============================================================================
# Appellate Court Docket Models (from appellatecases.courtinfo.ca.gov)
# =============================================================================


class CalDocketEntry(DocketEntry):
    """An individual docket entry from California appellate courts.

    Represents a single event/filing in the case register of actions.
    """

    entry_date: date
    """Date of the docket entry"""

    description: str
    """Description of the action/event"""

    notes: str | None = None
    """Additional notes for this entry"""


class CalBriefEntry(DocketEntry):
    """A brief filing from California appellate courts.

    Represents a single brief document filed in a case.
    """

    brief_type: str
    """Type of brief (e.g., 'Opening Brief', 'Reply Brief')"""

    filing_party: str | None = None
    """Party who filed the brief"""

    date_filed: date | None = None
    """Date the brief was filed"""

    date_due: date | None = None
    """Due date for the brief"""

    pages: int | None = None
    """Number of pages"""

    download_url: str | None = None
    """URL to download the brief PDF"""

    local_path: str | None = None
    """Local filesystem path where the PDF was downloaded"""


class CalScheduledAction(DocketEntry):
    """A scheduled future action for a California appellate case."""

    action_type: str
    """Type of scheduled action"""

    scheduled_date: date | None = None
    """Date of the scheduled action"""

    scheduled_time: str | None = None
    """Time of the scheduled action"""

    location: str | None = None
    """Location of the action"""


class CalDisposition(DocketEntry):
    """A disposition entry for a California appellate case."""

    disposition_date: date
    """Date of the disposition"""

    description: str
    """Description of the disposition"""

    citation: str | None = None
    """Case citation if published"""


class CalParty(DocketEntry):
    """A party in a California appellate case."""

    name: str
    """Party name"""

    party_type: str
    """Party type (e.g., 'Appellant', 'Respondent', 'Petitioner')"""

    address: str | None = None
    """Party address"""

    attorneys: list[str] = []
    """List of attorney names representing this party"""


class CalTrialCourtInfo(DocketEntry):
    """Trial court information for a California appellate case."""

    trial_court_case: str | None = None
    """Trial court case number"""

    trial_court_name: str | None = None
    """Name of the trial court"""

    trial_judge: str | None = None
    """Name of the trial judge"""

    judgment_date: date | None = None
    """Date of the trial court judgment"""


class CalAppellateDocket(Docket):
    """A docket from California appellate courts.

    Represents a complete case record from the appellatecases.courtinfo.ca.gov
    search system. Contains data from all tabs: Case Summary, Docket, Briefs,
    Scheduled Actions, Disposition, Parties and Attorneys, and Trial Court.

    This is the main output type yielded by the docket scraper.
    """

    # === Searchable fields ===
    case_number: Annotated[str, UniqueMatch()]
    """Case number (e.g., 'S275000', 'A170000', 'B330000')"""

    court_id: Annotated[str, SetFilter()]
    """Court identifier: 'cal', 'calctapp1d', 'calctapp2d', etc."""

    speculative_case_num: Annotated[int, SpeculativeID()]
    """Numeric portion of case number for speculative enumeration"""

    # === Case Summary fields ===
    case_name: str
    """Case caption (e.g., 'The People v. Carter')"""

    case_type: str | None = None
    """Case type code (e.g., 'CV' for civil, 'CR' for criminal)"""

    case_category: str | None = None
    """Case category (Supreme Court only, e.g., 'Original Proceeding - Civil')"""

    division: str | None = None
    """Court division (e.g., '4', '8')"""

    filing_date: date | None = None
    """Date the case was filed"""

    completion_date: date | None = None
    """Date the case was completed"""

    case_status: str | None = None
    """Case status (e.g., 'case closed')"""

    disposition_date: date | None = None
    """Date of disposition"""

    case_citation: str | None = None
    """Case citation if published"""

    issues: str | None = None
    """Case issues (Supreme Court)"""

    oral_argument_datetime: str | None = None
    """Oral argument date/time"""

    # === Related cases ===
    trial_court_case: str | None = None
    """Trial court case number"""

    court_of_appeal_case: str | None = None
    """Court of Appeal case number (for Supreme Court cases)"""

    cross_referenced_cases: list[str] = []
    """Cross-referenced case numbers"""

    # === Related data ===
    docket_entries: list[CalDocketEntry] = []
    """Register of actions (docket entries)"""

    briefs: list[CalBriefEntry] = []
    """Brief filings"""

    scheduled_actions: list[CalScheduledAction] = []
    """Future scheduled actions"""

    dispositions: list[CalDisposition] = []
    """Disposition entries"""

    parties: list[CalParty] = []
    """Parties and their attorneys"""

    trial_court_info: CalTrialCourtInfo | None = None
    """Trial court information"""

    # === Source tracking ===
    doc_id: int | None = None
    """Internal document ID from the court system"""

    source_url: str | None = None
    """URL of the case summary page"""

    request_token: str | None = None
    """Session token used to access this case"""
