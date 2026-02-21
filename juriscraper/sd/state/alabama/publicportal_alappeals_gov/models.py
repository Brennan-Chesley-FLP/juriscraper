"""Data models for Alabama appellate courts scraper.

These models extend base model types from kent to capture
Alabama Supreme Court, Court of Civil Appeals, and Court of Criminal Appeals data.

Mapping to base.py types:
- AlaOpinion -> Opinion (individual opinion document)
- AlaOpinionCluster -> OpinionCluster (group of related opinions from release lists)
- AlaHistoricalReleaseList -> OpinionCluster (weekly PDF bundles, pre-May 2023)
- AlaOralArgument -> Audio (oral argument information)
- AlaDocket -> Docket (case docket information)
- AlaDocketEntry -> DocketEntry (individual docket entry/filing)

Supported courts:
- ala: Alabama Supreme Court
- alactapp: Alabama Court of Civil Appeals
- alacrimapp: Alabama Court of Criminal Appeals
"""

from __future__ import annotations

from datetime import date
from typing import TypedDict

from kent.common.models.base import (
    Audio,
    Docket,
    DocketEntry,
    Opinion,
    OpinionCluster,
)

# Court ID mapping
COURT_IDS = {
    "ala": "Alabama Supreme Court",
    "alactapp": "Alabama Court of Civil Appeals",
    "alacrimapp": "Alabama Court of Criminal Appeals",
}


class CourtConfigEntry(TypedDict):
    """Type definition for court configuration entries."""

    name: str
    court_guid: str
    clerk_name: str
    decisions_url: str  # Historical decisions page on judicial.alabama.gov


# Court configuration for scraping
# GUIDs from the task description
COURT_CONFIG: dict[str, CourtConfigEntry] = {
    "ala": {
        "name": "Alabama Supreme Court",
        "court_guid": "68f021c4-6a44-4735-9a76-5360b2e8af13",
        "clerk_name": "Megan B. Rhodebeck",
        "decisions_url": "https://judicial.alabama.gov/decision/supremecourtdecisions",
    },
    "alactapp": {
        "name": "Alabama Court of Civil Appeals",
        "court_guid": "1da1a297-c391-4e4f-9480-1bc68b46f21a",
        "clerk_name": "Seth Rhodebeck",
        "decisions_url": "https://judicial.alabama.gov/decision/civildecisions",
    },
    "alacrimapp": {
        "name": "Alabama Court of Criminal Appeals",
        "court_guid": "b82b30d5-bd3c-46d7-9451-1cb05e470873",
        "clerk_name": "D. Scott Mitchell",
        "decisions_url": "https://judicial.alabama.gov/decision/criminaldecisions",
    },
}

# API configuration
API_CONFIG = {
    "base_url": "https://publicportal-api.alappeals.gov",
    "portal_url": "https://publicportal.alappeals.gov",
    "publications_endpoint": "/courts/cms/publications",
    "case_search_endpoint": "/portal/search/case",
    "publication_search_endpoint": "/portal/search/publication",
    "calendar_search_endpoint": "/portal/search/calendar",
    "events_endpoint": "/courts/cms/events",
}


class AlaOpinion(Opinion):
    """An individual opinion document from Alabama appellate courts.

    Extends Opinion from base.py with required fields for Alabama courts.
    """

    download_url: str
    """URL to the opinion PDF (required)"""

    type: str = "majority"
    """Opinion type: 'majority', 'dissent', 'concurrence', etc."""

    local_path: str | None = None
    """Local filesystem path where the PDF was downloaded (set by driver)"""

    # Alabama-specific fields
    authoring_judge: str | None = None
    """Name of the authoring judge/justice"""

    decision_text: str | None = None
    """Decision/outcome text (e.g., 'Affirmed', 'Reversed and Remanded')"""


class AlaOpinionCluster(OpinionCluster):
    """A cluster of opinions from Alabama appellate courts.

    This is the main output type yielded by the scraper for opinions.
    Each cluster represents a case from the weekly release lists.

    Supports Alabama Supreme Court (ala), Court of Civil Appeals (alactapp),
    and Court of Criminal Appeals (alacrimapp).
    """

    # === Searchable fields ===
    case_number: str
    """Case number (e.g., 'SC-2023-0123')"""

    court_id: str
    """Court identifier: 'ala', 'alactapp', or 'alacrimapp'"""

    date_filed: date
    """Date the opinion was filed/published (from release list scheduled date)"""

    # === Required fields ===
    case_name: str
    """Case name/title"""

    # === Alabama-specific fields ===
    publication_number: str | None = None
    """Publication/release number (e.g., 'SC-RELEASE-2023-11-09')"""

    authoring_judge: str | None = None
    """Name of the authoring judge/justice (from groupName)"""

    decision_text: str | None = None
    """Decision/outcome text (e.g., 'Affirmed', 'Reversed and Remanded')"""

    lower_court: str | None = None
    """Lower court name (extracted from case title parenthetical)"""

    lower_court_number: str | None = None
    """Lower court case number (extracted from case title parenthetical)"""

    per_curiam: bool = False
    """Whether this is a per curiam opinion"""

    on_rehearing: bool = False
    """Whether this is marked 'On Rehearing'"""

    # === Publication metadata ===
    publication_uuid: str | None = None
    """UUID for the publication/release list"""

    publication_item_uuid: str | None = None
    """UUID for this specific item in the publication"""

    case_instance_uuid: str | None = None
    """UUID for the case instance"""

    # === Related data ===
    opinions: list[AlaOpinion] = []
    """All opinions in this cluster"""

    # === Source tracking ===
    source_url: str | None = None
    """URL of the publication/release list"""


class AlaOralArgument(Audio):
    """An oral argument from Alabama appellate courts.

    Extends Audio from base.py. Alabama oral arguments include scheduled
    information and may have YouTube video links.
    """

    # === Searchable fields ===
    case_number: str
    """Case number"""

    court_id: str
    """Court identifier: 'ala', 'alactapp', or 'alacrimapp'"""

    date_argued: date
    """Date the oral argument is/was scheduled"""

    # === Required fields ===
    case_name: str
    """Case name"""

    # === YouTube-specific fields (if available) ===
    youtube_url: str | None = None
    """Full YouTube URL for the oral argument video (if available)"""

    youtube_video_id: str | None = None
    """YouTube video ID (extracted from URL)"""

    # === Source tracking ===
    source_url: str | None = None
    """URL of the calendar/oral arguments page where this was found"""

    # === Calendar metadata ===
    calendar_uuid: str | None = None
    """UUID for the calendar entry"""

    case_instance_uuid: str | None = None
    """UUID for the case instance"""


class AlaDocketEntry(DocketEntry):
    """An individual docket entry from Alabama appellate courts.

    Represents a single filing/document in the case Documents tab.
    """

    date_filed: date | None = None
    """Date the document was filed"""

    document_type: str | None = None
    """Document type (e.g., 'Brief', 'Motion', 'Order')"""

    document_subtype: str | None = None
    """Document subtype (more specific classification)"""

    description: str | None = None
    """Document description"""

    document_url: str | None = None
    """URL to the PDF document (if available)"""

    document_uuid: str | None = None
    """UUID for the document"""


class AlaDocket(Docket):
    """A docket from Alabama appellate courts (publicportal.alappeals.gov).

    Represents a complete case with all its metadata from the
    case detail page.
    """

    # === Searchable fields ===
    case_instance_uuid: str
    """Case instance UUID - the unique identifier for the case"""

    case_number: str
    """Case number (e.g., 'SC-2023-0123')"""

    court_id: str
    """Court identifier: 'ala', 'alactapp', or 'alacrimapp'"""

    date_filed: date | None = None
    """Date the case was filed"""

    # === Required fields ===
    case_name: str
    """Case name/style"""

    # === Case metadata ===
    case_classification: str | None = None
    """Case classification/type"""

    originating_court: str | None = None
    """Originating/lower court name"""

    originating_court_number: str | None = None
    """Originating court case number"""

    # === Case status ===
    status: str | None = None
    """Current case status"""

    # === Parties ===
    parties: list[dict] = []
    """List of parties with their roles, attorneys, and status"""

    # === Document history ===
    entries: list[AlaDocketEntry] = []
    """All docket entries (Documents tab)"""

    # === Oral arguments ===
    oral_arguments: list[dict] = []
    """Scheduled oral arguments for this case"""

    # === Source tracking ===
    source_url: str | None = None
    """URL of the case detail page"""

    # === API metadata ===
    court_guid: str | None = None
    """Court GUID used in API calls"""


class AlaHistoricalReleaseList(OpinionCluster):
    """A weekly release list from Alabama appellate courts (pre-May 2023).

    This represents a weekly release list PDF document from acis.alabama.gov.
    The PDF contains multiple opinions grouped by authoring judge/justice.

    These historical opinions were released before May 19, 2023, when Alabama
    transitioned to the Public Portal system at publicportal.alappeals.gov.

    Note: This scraper captures the release list PDFs. Extracting individual
    opinions from these PDFs requires additional PDF parsing not included here.
    """

    # === Searchable fields ===
    court_id: str
    """Court identifier: 'ala', 'alactapp', or 'alacrimapp'"""

    date_filed: date
    """Date the release list was published (the Friday of release)"""

    # === Required fields ===
    case_name: str
    """Description of the release list (e.g., 'Decisions on Friday, May 19, 2023')"""

    # === PDF document ===
    pdf_url: str
    """URL to the release list PDF on acis.alabama.gov"""

    local_path: str | None = None
    """Local filesystem path where the PDF was downloaded (set by driver)"""

    # === Source tracking ===
    source_url: str | None = None
    """URL of the decisions listing page on judicial.alabama.gov"""

    # === ACIS metadata ===
    acis_doc_no: str | None = None
    """Document number from acis.alabama.gov URL (the 'no' parameter)"""

    acis_event: str | None = None
    """Event code from acis.alabama.gov URL (the 'event' parameter)"""
