"""Data models for Wisconsin appellate courts scraper.

These models extend ConsumerModel types from base.py to capture
Wisconsin appellate courts opinion data.

Mapping to base.py types:
- WisconsinOpinion -> Opinion (individual opinion document)
- WisconsinOpinionCluster -> OpinionCluster (group of related opinions)

Supported courts:
- wis: Wisconsin Supreme Court
- wisctapp: Wisconsin Court of Appeals

Case number format: YYYYAPNNNNNN[-SUFFIX]
Examples:
- 2023AP002319-CR (criminal appeal)
- 2023AP001664-D (disciplinary matter)
- 2025AP001744 (civil appeal without suffix)

The Court of Appeals has four geographic districts:
- District I: Milwaukee County
- District II: Waukesha area (12 counties)
- District III: Wausau area (35 counties)
- District IV: Madison area (24 counties)
"""

from __future__ import annotations

from datetime import date

from kent.common.models.base import (
    Opinion,
    OpinionCluster,
)

# Court ID mapping
COURT_IDS: dict[str, str] = {
    "supreme": "wis",
    "appeals": "wisctapp",
}

# Court names for reference
COURT_NAMES: dict[str, str] = {
    "wis": "Wisconsin Supreme Court",
    "wisctapp": "Wisconsin Court of Appeals",
}

# District mapping for Court of Appeals (district number -> description)
DISTRICTS: dict[str, str] = {
    "1": "District I (Milwaukee)",
    "2": "District II (Waukesha)",
    "3": "District III (Wausau)",
    "4": "District IV (Madison)",
}


class WisconsinOpinion(Opinion):
    """An individual opinion document from Wisconsin appellate courts.

    Extends Opinion from base.py with required fields for Wisconsin courts.
    """

    download_url: str
    """URL to the opinion PDF"""

    local_path: str | None = None
    """Local filesystem path where the PDF was downloaded (set by driver)"""


class WisconsinOpinionCluster(OpinionCluster):
    """A cluster of opinions from Wisconsin appellate courts.

    This is the main output type yielded by the scraper.
    Each cluster represents a single case with one opinion PDF.

    Docket number format: YYYYAPNNNNNN[-SUFFIX]
    Examples:
    - 2023AP002319-CR (criminal appeal)
    - 2023AP001664-D (disciplinary matter)
    - 2025AP001744 (civil without suffix)
    """

    # === Searchable fields ===
    docket_number: str
    """Case number (e.g., '2023AP002319-CR', '2025AP001744')"""

    court_id: str
    """Court identifier: 'wis' (Supreme Court), 'wisctapp' (Court of Appeals)"""

    date_filed: date
    """Release date of the opinion"""

    # === Required fields from base ===
    case_name: str
    """Case name (e.g., 'State v. Michael Joseph Gasper')"""

    # === Related data ===
    opinions: list[WisconsinOpinion] = []
    """Opinion(s) in this cluster (typically one)"""

    # === Source tracking ===
    source_url: str | None = None
    """URL of the page where this was found"""

    # === Wisconsin-specific fields ===
    district: str | None = None
    """Court of Appeals district number (1-4), None for Supreme Court"""

    county: str | None = None
    """County of origin (for Court of Appeals cases)"""

    precedential_status: str = "Published"
    """Publication status: 'Published' or 'Unpublished'"""

    recommended_for_publication: bool = False
    """Whether the opinion is marked as 'Recommended for Publication'"""
