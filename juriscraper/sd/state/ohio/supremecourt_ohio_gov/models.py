"""Data models for Ohio appellate courts scraper.

These models extend ConsumerModel types from base.py to capture
Ohio Supreme Court and Courts of Appeals opinions.

Mapping to base.py types:
- OhioOpinion -> Opinion (individual opinion document)
- OhioOpinionCluster -> OpinionCluster (group of related opinions)

Supported courts (from courts.toml):
- ohio: Ohio Supreme Court (source=0)
- ohioctapp: Ohio Court of Appeals (all districts, source=16)
- ohctapp1-12: Individual district courts (source=1-12)

The Ohio opinion search system uses a "source" parameter:
- 0 = Supreme Court of Ohio
- 1-12 = First through Twelfth District Courts of Appeals
- 13 = Court of Claims
- 14 = Miscellaneous
- 15 = All Sources
- 16 = All District Courts
"""

from __future__ import annotations

from datetime import date
from typing import Annotated

from juriscraper.scraper_driver.common.models.base import (
    Opinion,
    OpinionCluster,
)
from juriscraper.scraper_driver.common.searchable import (
    DateRange,
    SetFilter,
    UniqueMatch,
)

# Court ID mapping from source number to CourtListener court_id
# Source 0 = Supreme Court, Sources 1-12 = District Courts of Appeals
SOURCE_TO_COURT_ID: dict[int, str] = {
    0: "ohio",  # Ohio Supreme Court
    1: "ohctapp1",  # First District Court of Appeals (Hamilton County)
    2: "ohctapp2",  # Second District Court of Appeals
    3: "ohctapp3",  # Third District Court of Appeals
    4: "ohctapp4",  # Fourth District Court of Appeals
    5: "ohctapp5",  # Fifth District Court of Appeals
    6: "ohctapp6",  # Sixth District Court of Appeals
    7: "ohctapp7",  # Seventh District Court of Appeals
    8: "ohctapp8",  # Eighth District Court of Appeals (Cuyahoga County)
    9: "ohctapp9",  # Ninth District Court of Appeals
    10: "ohctapp10",  # Tenth District Court of Appeals (Franklin County)
    11: "ohctapp11",  # Eleventh District Court of Appeals
    12: "ohctapp12",  # Twelfth District Court of Appeals
    13: "ohioctcl",  # Court of Claims
}

# Reverse mapping for URL construction
COURT_ID_TO_SOURCE: dict[str, int] = {v: k for k, v in SOURCE_TO_COURT_ID.items()}

# All supported court IDs
COURT_IDS: set[str] = set(SOURCE_TO_COURT_ID.values())

# Display names for courts
COURT_NAMES: dict[str, str] = {
    "ohio": "Ohio Supreme Court",
    "ohctapp1": "First District Court of Appeals",
    "ohctapp2": "Second District Court of Appeals",
    "ohctapp3": "Third District Court of Appeals",
    "ohctapp4": "Fourth District Court of Appeals",
    "ohctapp5": "Fifth District Court of Appeals",
    "ohctapp6": "Sixth District Court of Appeals",
    "ohctapp7": "Seventh District Court of Appeals",
    "ohctapp8": "Eighth District Court of Appeals",
    "ohctapp9": "Ninth District Court of Appeals",
    "ohctapp10": "Tenth District Court of Appeals",
    "ohctapp11": "Eleventh District Court of Appeals",
    "ohctapp12": "Twelfth District Court of Appeals",
    "ohioctcl": "Court of Claims",
}


class OhioOpinion(Opinion):
    """An individual opinion document from Ohio appellate courts.

    Extends Opinion from base.py with required fields for Ohio courts.
    """

    download_url: str
    """URL to the opinion PDF (required)"""

    type: str = "majority"
    """Opinion type: 'majority', 'dissent', 'concurrence', etc."""

    local_path: str | None = None
    """Local filesystem path where the PDF was downloaded (set by driver)"""

    # Ohio-specific fields
    author: str | None = None
    """Name of the opinion author (Justice/Judge or 'Per Curiam')"""


class OhioOpinionCluster(OpinionCluster):
    """A cluster of opinions from Ohio appellate courts.

    This is the main output type yielded by the scraper for opinions.
    Each cluster represents a case that may have multiple opinions
    (majority, dissents, concurrences).

    Supports Ohio Supreme Court (ohio) and all 12 District Courts of Appeals.
    """

    # === Searchable fields ===
    webcite: Annotated[str, UniqueMatch()]
    """WebCite citation (e.g., '2026-Ohio-148') - unique identifier"""

    court_id: Annotated[str, SetFilter()]
    """Court identifier: 'ohio', 'ohctapp1'-'ohctapp12', 'ohioctcl'"""

    date_decided: Annotated[date, DateRange()]
    """Date the opinion was decided/filed"""

    # === Required fields ===
    case_name: str
    """Case name/caption (e.g., 'State v. McAlpin')"""

    # === Optional fields ===
    case_number: str | None = None
    """Case number (e.g., '2024-0749') - may be empty for announcements"""

    author: str | None = None
    """Name of the authoring judge/justice (e.g., 'Kennedy, C.J.')"""

    topics_and_issues: str | None = None
    """Topics and issues summary from the opinion search"""

    citation: str | None = None
    """Official citation (e.g., 'Slip Opinion No. 2026-Ohio-148')"""

    county: str | None = None
    """County of origin (for Courts of Appeals cases)"""

    date_posted: date | None = None
    """Date the opinion was posted to the website"""

    # === Related data ===
    opinions: list[OhioOpinion] = []
    """All opinions in this cluster (majority, dissents, concurrences)"""

    # === Source tracking ===
    source_url: str | None = None
    """URL of the opinions listing page"""
