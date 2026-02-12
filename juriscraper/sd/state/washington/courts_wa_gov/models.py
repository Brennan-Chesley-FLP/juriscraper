"""Data models for Washington appellate courts scraper.

These models extend ConsumerModel types from base.py to capture
opinions from Washington Supreme Court and Court of Appeals.

Mapping to base.py types:
- WashingtonOpinion -> Opinion (individual opinion document)
- WashingtonOpinionCluster -> OpinionCluster (group of related opinions)

Supported courts (from courts.toml):
- wash: Washington Supreme Court
- washctapp: Court of Appeals of Washington (all three divisions)

The Washington Court of Appeals has three divisions:
- Division I (Seattle) - covers King, Snohomish, and surrounding counties
- Division II (Tacoma) - covers Pierce, Clark, and southwestern counties
- Division III (Spokane) - covers eastern Washington counties

Opinion types on the site:
- Supreme Court published opinions
- Court of Appeals published opinions
- Court of Appeals unpublished opinions
"""

from __future__ import annotations

from datetime import date

from kent.common.models.base import (
    Opinion,
    OpinionCluster,
)

# Court ID mapping
# The site distinguishes between Supreme Court and Court of Appeals,
# and further by division for COA
COURT_IDS: set[str] = {"wash", "washctapp"}

# Court display names
COURT_NAMES: dict[str, str] = {
    "wash": "Washington Supreme Court",
    "washctapp": "Court of Appeals of Washington",
}

# Division mapping for Court of Appeals
# Roman numerals on the site map to division numbers
DIVISION_MAP: dict[str, int] = {
    "I": 1,
    "II": 2,
    "III": 3,
}


class WashingtonOpinion(Opinion):
    """An individual opinion document from Washington appellate courts.

    Extends Opinion from base.py with required fields for Washington courts.
    """

    download_url: str
    """URL to the opinion PDF (required)"""

    type: str = "majority"
    """Opinion type: 'majority', 'concurrence', 'dissent', etc."""

    local_path: str | None = None
    """Local filesystem path where the PDF was downloaded (set by driver)"""

    # Washington-specific fields
    author: str | None = None
    """Name of the opinion author (Justice/Judge)"""


class WashingtonOpinionCluster(OpinionCluster):
    """A cluster of opinions from Washington appellate courts.

    This is the main output type yielded by the scraper for opinions.
    Each cluster represents a case that may have multiple opinions
    (majority, concurrences, dissents).

    Supports Washington Supreme Court (wash) and Court of Appeals (washctapp).
    """

    # === Searchable fields ===
    docket_number: str
    """Docket number (e.g., '103,469-5' for SC, '59813-2' for COA)"""

    court_id: str
    """Court identifier: 'wash' or 'washctapp'"""

    date_filed: date
    """Date the opinion was filed"""

    # === Required fields ===
    case_name: str
    """Case name/caption (e.g., 'State v. Bennett')"""

    # === Optional fields ===
    division: int | None = None
    """Court of Appeals division (1, 2, or 3) - None for Supreme Court"""

    publication_status: str | None = None
    """'published' or 'unpublished' - only COA has unpublished opinions"""

    file_contents: str | None = None
    """Description of what the opinion file contains (e.g., 'Maj., and Con. Opinions')"""

    oral_argument_date: date | None = None
    """Date of oral argument (if available, typically on detail page)"""

    lower_court: str | None = None
    """Source of appeal (lower court name, e.g., 'Spokane County Superior Court')"""

    lower_court_docket: str | None = None
    """Lower court docket number"""

    lower_court_judge: str | None = None
    """Lower court judge name"""

    # === Related data ===
    opinions: list[WashingtonOpinion] = []
    """All opinions in this cluster (majority, dissents, concurrences)"""

    # === Source tracking ===
    source_url: str | None = None
    """URL of the opinions listing page"""

    detail_url: str | None = None
    """URL of the opinion information sheet"""
