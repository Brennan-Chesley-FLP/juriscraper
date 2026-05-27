"""Data models for Alabama appellate courts scraper.

These models extend ScrapedData from jkent to capture
Alabama Supreme Court, Court of Civil Appeals, and Court of Criminal Appeals data.

Supported courts:
- ala: Alabama Supreme Court
- alactapp: Alabama Court of Civil Appeals
- alacrimapp: Alabama Court of Criminal Appeals
"""

from __future__ import annotations

from datetime import date

from jkent.common.data_models import ScrapedData

from juriscraper.sd.state.common.tr.models import (
    TRCourtConfig,
    TRDocket,
    TRDocketEntry,
    TRDocument,
    TROralArgument,
)

# Court ID mapping
COURT_IDS = {
    "ala": "Alabama Supreme Court",
    "alactapp": "Alabama Court of Civil Appeals",
    "alacrimapp": "Alabama Court of Criminal Appeals",
}


class AlaCourtConfig(TRCourtConfig):
    """Alabama court configuration entry.

    Extends the TR Portal court config with Alabama-only fields used
    for the historical (pre-May 2023) release-list scraper on
    judicial.alabama.gov.
    """

    clerk_name: str
    decisions_url: str


# Court configuration for scraping.
# numeric_id matches the courtID values the case-search endpoint
# returns: "1" = Supreme, "2" = Criminal Appeals, "3" = Civil Appeals.
# (The events endpoint also uses this scheme; case detail responses
# return a different numeric — 68/69/70 — but it is not consumed by
# the scraper.)
COURT_CONFIG: dict[str, AlaCourtConfig] = {
    "ala": {
        "name": "Alabama Supreme Court",
        "court_guid": "68f021c4-6a44-4735-9a76-5360b2e8af13",
        "numeric_id": "1",
        "abbreviation": "Alabama Supreme Court",
        "clerk_name": "Megan B. Rhodebeck",
        "decisions_url": "https://judicial.alabama.gov/decision/supremecourtdecisions",
    },
    "alactapp": {
        "name": "Alabama Court of Civil Appeals",
        "court_guid": "1da1a297-c391-4e4f-9480-1bc68b46f21a",
        "numeric_id": "3",
        "abbreviation": "Alabama Court of Civil Appeals",
        "clerk_name": "Seth Rhodebeck",
        "decisions_url": "https://judicial.alabama.gov/decision/civildecisions",
    },
    "alacrimapp": {
        "name": "Alabama Court of Criminal Appeals",
        "court_guid": "b82b30d5-bd3c-46d7-9451-1cb05e470873",
        "numeric_id": "2",
        "abbreviation": "Alabama Court of Criminal Appeals",
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


class AlaOpinion(ScrapedData):
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


class AlaOpinionCluster(ScrapedData):
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


class AlaOrder(ScrapedData):
    """An order or non-opinion document from Alabama appellate courts.

    Items where documentName is NOT 'Opinion' or 'Decision' produce
    AlaOrder objects. These include rehearing orders, cert denials,
    special writings, rehearing notices, and other non-opinion dispositions.

    Supports Alabama Supreme Court (ala), Court of Civil Appeals (alactapp),
    and Court of Criminal Appeals (alacrimapp).
    """

    # === Searchable fields ===
    case_number: str
    """Case number (e.g., 'SC-2024-0492')"""

    court_id: str
    """Court identifier: 'ala', 'alactapp', or 'alacrimapp'"""

    date_filed: date
    """Date the order was filed/published (from publication date)"""

    # === Required fields ===
    case_name: str
    """Case name/title"""

    # === Order-specific fields ===
    document_name: str | None = None
    """Document name from the API (e.g., 'Order', 'Special Writing', 'Rehearing Notice')"""

    decision_text: str | None = None
    """Decision/outcome text (e.g., 'Rehearing - Overruled - No Opinion.')"""

    # === Publication metadata ===
    publication_number: str | None = None
    """Publication/release number (e.g., 'SC-RELEASE-2023-11-09')"""

    publication_uuid: str | None = None
    """UUID for the publication/release list"""

    publication_item_uuid: str | None = None
    """UUID for this specific item in the publication"""

    case_instance_uuid: str | None = None
    """UUID for the case instance"""

    # === Judge/authoring info ===
    authoring_judge: str | None = None
    """Name of the authoring judge/justice (from groupName)"""

    per_curiam: bool = False
    """Whether this is a per curiam order"""

    on_rehearing: bool = False
    """Whether this is marked 'On Rehearing'"""

    # === Lower court info ===
    lower_court: str | None = None
    """Lower court name (extracted from case title parenthetical)"""

    lower_court_number: str | None = None
    """Lower court case number (extracted from case title parenthetical)"""

    # === Document ===
    download_url: str | None = None
    """URL to the document PDF"""

    local_path: str | None = None
    """Local filesystem path where the PDF was downloaded (set by driver)"""

    # === Source tracking ===
    source_url: str | None = None
    """URL of the publication/release list"""


class AlaOralArgument(TROralArgument):
    """An oral argument from Alabama appellate courts.

    Extends the TR Portal oral-argument schema with optional YouTube
    video links (Alabama posts oral arguments to YouTube).
    """

    youtube_url: str | None = None
    """Full YouTube URL for the oral argument video (if available)"""

    youtube_video_id: str | None = None
    """YouTube video ID (extracted from URL)"""


class AlaDocketEntry(TRDocketEntry):
    """An individual docket entry from Alabama appellate courts.

    Represents a single filing/document in the case Documents tab.
    Inherits the full TR Portal entry schema.
    """


class AlaDocket(TRDocket):
    """A docket from Alabama appellate courts (publicportal.alappeals.gov).

    Represents a complete case with all its metadata from the
    case detail page. Inherits the full TR Portal docket schema.
    """

    entries: list[AlaDocketEntry] = []
    """All docket entries (Documents tab)"""


class AlaDocument(TRDocument):
    """A document attached to a docket entry on an Alabama appellate court.

    Alabama's appellate documents are paywalled, so anonymous archive
    requests for the file body will typically fail and the resulting
    record will have ``local_path=None``. Metadata (name, content type,
    size, etc.) is still captured.
    """


class AlaHistoricalReleaseList(ScrapedData):
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
