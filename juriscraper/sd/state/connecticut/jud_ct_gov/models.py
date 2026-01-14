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


class ConnDocketEntry(DocketEntry):
    """An individual docket entry from Connecticut appellate courts.

    Represents a single filing/activity in the Case Activity section.
    """

    activity_type: str  # Required - e.g., "APPEAL", "MOTION", "ORDER"
    """Activity type (e.g., 'APPEAL', 'MOTION', 'ORDER', 'DISPOSITION')"""

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

    is_paperless: bool = False
    """Whether this is a paperless filing"""


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
    entries: list[ConnDocketEntry] = []
    """All docket entries (Case Activity section)"""

    parties: list[dict] = []
    """List of parties with their attorneys and roles"""

    # === Source tracking ===
    source_url: str | None = None
    """URL of the CaseDetail page"""

    is_efiled: bool = False
    """Whether the case was e-filed"""


# Backwards compatibility aliases
ConnSupremeCourtOpinion = ConnOpinion
ConnSupremeCourtOpinionCluster = ConnOpinionCluster
