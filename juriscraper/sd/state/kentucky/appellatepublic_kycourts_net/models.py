"""Data models for Kentucky appellate courts scraper.

These models extend base model types from kent to capture
Kentucky Supreme Court and Court of Appeals opinion data from
the C-Track Public Access system.

Mapping to base.py types:
- KentuckyOpinion -> Opinion (individual opinion document)
- KentuckyOpinionCluster -> OpinionCluster (opinion metadata with documents)

Supported courts:
- ky: Kentucky Supreme Court (case prefix: SC)
- kyctapp: Kentucky Court of Appeals (case prefix: CA)

Data source: https://appellatepublic.kycourts.net/search/opinion
"""

from __future__ import annotations

from datetime import date

from kent.common.models.base import (
    Opinion,
    OpinionCluster,
)

# Court ID mapping to CourtListener IDs
COURT_IDS = {
    "ky": "Kentucky Supreme Court",
    "kyctapp": "Court of Appeals of Kentucky",
}

# Case number prefixes by court
# Supreme Court: YYYY-SC-NNNN
# Court of Appeals: YYYY-CA-NNNN
CASE_PREFIX_TO_COURT = {
    "SC": "ky",
    "CA": "kyctapp",
}

COURT_TO_CASE_PREFIX = {
    "ky": ["SC"],
    "kyctapp": ["CA"],
}

# Site court names to court IDs
SITE_COURT_NAME_TO_ID = {
    "Kentucky Supreme Court": "ky",
    "Kentucky Court of Appeals": "kyctapp",
}


class KentuckyOpinion(Opinion):
    """An individual opinion document from Kentucky appellate courts.

    Extends Opinion from base.py with required fields for Kentucky courts.
    """

    download_url: str
    """URL to download the opinion PDF"""

    opinion_type: str
    """Opinion type (e.g., 'DISPOSITION - MEMORANDUM OPINION')"""

    subtype: str | None = None
    """Opinion subtype (e.g., 'AFFIRMING', 'REVERSING')"""

    local_path: str | None = None
    """Local filesystem path where the PDF was downloaded (set by driver)"""


class KentuckyOpinionCluster(OpinionCluster):
    """A cluster of opinions from Kentucky appellate courts.

    This is the main output type yielded by the scraper.
    Each cluster represents an opinion with its associated documents.

    Supports both Kentucky Supreme Court (ky) and
    Court of Appeals (kyctapp).
    """

    # === Searchable fields ===
    docket_id: str  # type: ignore[assignment]
    """Case number (e.g., '2024-SC-0123' for Supreme, '2024-CA-0456' for COA)"""

    court_id: str
    """Court identifier: 'ky' (Supreme Court) or 'kyctapp' (Court of Appeals)"""

    date_filed: date
    """Publication date of the opinion"""

    # === Required fields from base ===
    case_name: str
    """Case name (e.g., 'ANTONIO CORDERIERO DOUGLAS VS COMMONWEALTH OF KENTUCKY')"""

    # === Related data ===
    opinions: list[KentuckyOpinion] = []
    """All opinion documents in this cluster"""

    # === Source tracking ===
    source_url: str | None = None
    """URL of the opinion search results page"""

    case_detail_url: str | None = None
    """URL to the case detail page on C-Track"""

    # === Kentucky-specific fields ===
    classification: str | None = None
    """Case classification (e.g., 'MATTER OF RIGHT - CRIMINAL - REGULAR CRIMINAL')"""

    case_status: str | None = None
    """Case status (e.g., 'FINAL', 'ACTIVE')"""

    status_date: str | None = None
    """Date of the current status"""

    judges_participating: str | None = None
    """Judges who participated in the opinion (from docket entry comments)"""
