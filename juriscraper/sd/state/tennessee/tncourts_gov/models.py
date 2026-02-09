"""Data models for Tennessee appellate courts scraper.

These models extend ConsumerModel types from base.py to capture
Tennessee Supreme Court, Court of Appeals, and Court of Criminal Appeals data.

Mapping to base.py types:
- TennJudge -> Person (judge/justice profile with photo)
- TennOpinion -> Opinion (individual opinion document)
- TennOpinionCluster -> OpinionCluster (group of related opinions)
- TennOralArgument -> Audio (oral argument - YouTube video)
- TennDocket -> Docket (case docket information)
- TennDocketEntry -> DocketEntry (individual docket entry/filing)

Supported courts:
- tenn: Tennessee Supreme Court
- tennctapp: Court of Appeals of Tennessee
- tenncrimapp: Court of Criminal Appeals of Tennessee
"""

from __future__ import annotations

from datetime import date
from typing import TypedDict

from juriscraper.scraper_driver.common.models.base import (
    Audio,
    Docket,
    DocketEntry,
    Opinion,
    OpinionCluster,
    Person,
)

# Court ID mapping
COURT_IDS = {
    "tenn": "Tennessee Supreme Court",
    "tennctapp": "Court of Appeals of Tennessee",
    "tenncrimapp": "Court of Criminal Appeals of Tennessee",
}


class CourtConfigEntry(TypedDict):
    """Type definition for court configuration entries."""

    name: str
    court_path: str
    judges_url: str
    opinions_url: str
    oral_args_c: int


# Court configuration for scraping
COURT_CONFIG: dict[str, CourtConfigEntry] = {
    "tenn": {
        "name": "Tennessee Supreme Court",
        "court_path": "supreme-court",
        "judges_url": "https://www.tncourts.gov/courts/supreme-court/judges",
        "opinions_url": "https://www.tncourts.gov/courts/supreme-court/opinions",
        "oral_args_c": 27,  # ?c= param for oral arguments
    },
    "tennctapp": {
        "name": "Court of Appeals of Tennessee",
        "court_path": "court-of-appeals",
        "judges_url": "https://www.tncourts.gov/courts/court-of-appeals/judges",
        "opinions_url": "https://www.tncourts.gov/courts/court-of-appeals/opinions",
        "oral_args_c": 28,
    },
    "tenncrimapp": {
        "name": "Court of Criminal Appeals of Tennessee",
        "court_path": "court-of-criminal-appeals",
        "judges_url": "https://www.tncourts.gov/courts/court-of-criminal-appeals/judges",
        "opinions_url": "https://www.tncourts.gov/courts/court-of-criminal-appeals/opinions",
        "oral_args_c": 29,
    },
}

# Docket configuration (pch.tncourts.gov)
DOCKET_CONFIG = {
    "base_url": "https://pch.tncourts.gov",
    "case_detail_url": "https://pch.tncourts.gov/CaseDetails.aspx",
}


class TennJudge(Person):
    """A judge/justice from Tennessee appellate courts.

    Extends Person from base.py with fields for Tennessee court judges.
    Photos are archived via ArchiveRequest.
    """

    # === Searchable fields ===
    slug: str
    """URL slug for the judge (e.g., 'jeffrey-s-bivins')"""

    court_id: str
    """Court identifier: 'tenn', 'tennctapp', or 'tenncrimapp'"""

    # === Required fields ===
    name_first: str
    """First name"""

    name_last: str
    """Last name"""

    title: str
    """Title (e.g., 'Chief Justice', 'Justice', 'Judge')"""

    # === Optional biography fields ===
    biography: str | None = None
    """Full biography text"""

    year_elected: int | None = None
    """Year elected or appointed"""

    prior_judicial_experience: str | None = None
    """Prior judicial experience text"""

    previous_employment: str | None = None
    """Previous employment text"""

    education: list[str] = []
    """List of education entries"""

    memberships: str | None = None
    """Professional memberships text"""

    community_involvement: str | None = None
    """Community involvement text"""

    contact_info: str | None = None
    """Contact information"""

    address: str | None = None
    """Physical address"""

    # === Photo (archived) ===
    photo_url: str | None = None
    """URL to the judge's photo (original)"""

    photo_local_path: str | None = None
    """Local filesystem path where the photo was downloaded (set by driver)"""

    # === Position type for linking ===
    position_type: str | None = None
    """Position type code: 'c-jus' (Chief Justice), 'jus' (Justice), 'jud' (Judge)"""

    # === Source tracking ===
    source_url: str | None = None
    """URL of the judge's profile page"""


class TennOpinion(Opinion):
    """An individual opinion document from Tennessee appellate courts.

    Extends Opinion from base.py with required fields for TN courts.
    """

    download_url: str
    """URL to the opinion PDF (required)"""

    type: str = "majority"
    """Opinion type: 'majority', 'dissent', 'concurrence', etc."""

    local_path: str | None = None
    """Local filesystem path where the PDF was downloaded (set by driver)"""

    # Tennessee-specific fields
    authoring_judge: str | None = None
    """Name of the authoring judge"""

    trial_court_judge: str | None = None
    """Name of the trial court judge"""


class TennOpinionCluster(OpinionCluster):
    """A cluster of opinions from Tennessee appellate courts.

    This is the main output type yielded by the scraper for opinions.
    Each cluster represents a case that may have multiple opinions
    (majority, dissents, concurrences).

    Supports Tennessee Supreme Court (tenn), Court of Appeals (tennctapp),
    and Court of Criminal Appeals (tenncrimapp).
    """

    # === Searchable fields ===
    case_number: str
    """Case number (e.g., 'M2023-01234-SC-R11-CV')"""

    court_id: str
    """Court identifier: 'tenn', 'tennctapp', or 'tenncrimapp'"""

    date_filed: date
    """Date the opinion was filed/published"""

    # === Required fields ===
    case_name: str
    """Case name (e.g., 'State v. Smith')"""

    # === Tennessee-specific fields ===
    authoring_judge: str | None = None
    """Name of the authoring judge"""

    trial_court_judge: str | None = None
    """Name of the trial court judge"""

    county: str | None = None
    """County of origin"""

    # === Related data ===
    opinions: list[TennOpinion] = []
    """All opinions in this cluster (majority, dissents, concurrences)"""

    # === Source tracking ===
    source_url: str | None = None
    """URL of the opinions listing page"""


class TennOralArgument(Audio):
    """An oral argument from Tennessee appellate courts (YouTube videos).

    Extends Audio from base.py. Tennessee oral arguments are hosted on
    YouTube, so we capture the video URL rather than downloading.
    """

    # === Searchable fields ===
    case_number: str
    """Case number"""

    court_id: str
    """Court identifier: 'tenn', 'tennctapp', or 'tenncrimapp'"""

    date_argued: date
    """Date the oral argument was heard"""

    # === Required fields ===
    case_name: str
    """Case name"""

    youtube_url: str
    """Full YouTube URL for the oral argument video"""

    # === YouTube-specific fields ===
    youtube_video_id: str | None = None
    """YouTube video ID (extracted from URL)"""

    youtube_playlist_id: str | None = None
    """YouTube playlist ID (if part of a playlist)"""

    # === Source tracking ===
    source_url: str | None = None
    """URL of the oral arguments page where this was found"""

    argument_year: int | None = None
    """Year of the oral argument"""


class TennDocketEntry(DocketEntry):
    """An individual docket entry from Tennessee appellate courts.

    Represents a single filing/activity in the Document History section
    of pch.tncourts.gov.
    """

    date_filed: date | None = None
    """Date the document/event was filed"""

    event: str | None = None
    """Event type (e.g., 'Application Filed', 'Record Filed', 'Briefing')"""

    filer: str | None = None
    """Who filed this document"""

    document_url: str | None = None
    """URL to the PDF document (if available)"""


class TennDocket(Docket):
    """A docket from Tennessee appellate courts (pch.tncourts.gov).

    Represents a complete case with all its metadata from the
    PCH Case Details page.
    """

    # === Searchable fields ===
    pch_id: int
    """PCH internal ID - the ?id= parameter (auto-incrementing)"""

    case_number: str
    """Intermediate Case Number (e.g., from 'Inter. Case No.' field)"""

    court_id: str
    """Court identifier: 'tenn', 'tennctapp', or 'tenncrimapp'"""

    date_filed: date | None = None
    """Date the application was filed"""

    # === Required fields ===
    case_name: str
    """Case name/style"""

    # === Case overview ===
    trial_court: str | None = None
    """Trial court name"""

    trial_court_judge: str | None = None
    """Trial court judge name"""

    trial_court_number: str | None = None
    """Trial court case number"""

    # === Case milestones ===
    application_filed_date: date | None = None
    """Date application was filed"""

    disposition_date: date | None = None
    """Date of disposition"""

    disposition: str | None = None
    """Disposition result"""

    record_filed_date: date | None = None
    """Date record was filed"""

    briefing_complete_date: date | None = None
    """Date briefing was completed"""

    oral_argument_date: date | None = None
    """Date of oral argument"""

    decision_date: date | None = None
    """Date of decision"""

    # === Parties ===
    parties: list[dict] = []
    """List of parties with their roles and counsel"""

    # === Document history ===
    entries: list[TennDocketEntry] = []
    """All docket entries (Document History section)"""

    # === Source tracking ===
    source_url: str | None = None
    """URL of the CaseDetails page"""
