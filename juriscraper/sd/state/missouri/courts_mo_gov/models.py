"""Data models for Missouri appellate courts scraper.

These models extend base model types from kent to capture
Missouri appellate courts opinion data.

Mapping to base.py types:
- MissouriOpinion -> Opinion (individual opinion document)
- MissouriOpinionCluster -> OpinionCluster (group of related opinions)

Supported courts:
- mo: Supreme Court of Missouri
- moctapped: Missouri Court of Appeals, Eastern District
- moctappsd: Missouri Court of Appeals, Southern District
- moctappwd: Missouri Court of Appeals, Western District

Case number format: {PREFIX}{NUMBER}
- SC = Supreme Court
- ED = Eastern District
- SD = Southern District
- WD = Western District
"""

from __future__ import annotations

from datetime import date

from kent.common.models.base import (
    Opinion,
    OpinionCluster,
)

# Court ID mapping from case number prefix to CourtListener court_id
COURT_PREFIX_TO_ID: dict[str, str] = {
    "SC": "mo",  # Supreme Court of Missouri
    "ED": "moctapped",  # Missouri Court of Appeals, Eastern District
    "SD": "moctappsd",  # Missouri Court of Appeals, Southern District
    "WD": "moctappwd",  # Missouri Court of Appeals, Western District
}

# Court names for reference
COURT_NAMES: dict[str, str] = {
    "mo": "Supreme Court of Missouri",
    "moctapped": "Missouri Court of Appeals, Eastern District",
    "moctappsd": "Missouri Court of Appeals, Southern District",
    "moctappwd": "Missouri Court of Appeals, Western District",
}


def get_court_id_from_docket(docket_number: str) -> str | None:
    """Extract court_id from docket number prefix.

    Args:
        docket_number: Case number like 'SC101157', 'ED113623', etc.

    Returns:
        CourtListener court_id or None if prefix not recognized
    """
    for prefix, court_id in COURT_PREFIX_TO_ID.items():
        if docket_number.startswith(prefix):
            return court_id
    return None


class MissouriOpinion(Opinion):
    """An individual opinion document from Missouri appellate courts.

    Extends Opinion from base.py with required fields for Missouri courts.
    """

    download_url: str
    """URL to the opinion PDF"""

    local_path: str | None = None
    """Local filesystem path where the PDF was downloaded (set by driver)"""

    is_summary: bool = False
    """Whether this is an Overview/Summary document rather than full opinion"""


class MissouriOpinionCluster(OpinionCluster):
    """A cluster of opinions from Missouri appellate courts.

    This is the main output type yielded by the scraper.
    Each cluster represents a single case which may have:
    - One main opinion PDF
    - An optional Overview/Summary PDF

    Docket number format: {PREFIX}{NUMBER}
    Examples: SC101157, ED113623, SD38757, WD87719
    """

    # === Searchable fields ===
    docket_id: str  # type: ignore[assignment]
    """Case number (e.g., 'SC101157', 'ED113623')"""

    court_id: str
    """Court identifier: 'mo', 'moctapped', 'moctappsd', 'moctappwd'"""

    date_filed: date
    """Publication date of the opinion"""

    # === Required fields from base ===
    case_name: str
    """Case name (e.g., 'State of Missouri v. John Doe')"""

    # === Related data ===
    opinions: list[MissouriOpinion] = []
    """All opinions in this cluster (main opinion + optional summary)"""

    # === Source tracking ===
    source_url: str | None = None
    """URL of the page where this was found"""

    # === Missouri-specific fields ===
    author: str | None = None
    """Author of the opinion (judge name and title)"""

    vote: str | None = None
    """Vote breakdown and disposition (e.g., 'AFFIRMED. All concur.')"""

    disposition: str | None = None
    """Case disposition extracted from vote (e.g., 'AFFIRMED')"""

    precedential_status: str = "Published"
    """Publication status - Missouri appellate opinions are published"""
