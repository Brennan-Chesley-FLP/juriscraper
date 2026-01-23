"""Data models for Utah appellate courts scraper.

These models extend ConsumerModel types from base.py to capture
Utah Supreme Court and Court of Appeals opinions.

Mapping to base.py types:
- UtahOpinion -> Opinion (individual opinion document)
- UtahOpinionCluster -> OpinionCluster (group of related opinions)

Supported courts (from courts.toml):
- utah: Utah Supreme Court
- utahctapp: Utah Court of Appeals

URL Patterns:
- Current year Supreme Court: https://legacy.utcourts.gov/opinions/supopin/
- Current year Court of Appeals: https://legacy.utcourts.gov/opinions/appopin/
- PDFs: {base_url}/{filename}.pdf

Citation formats:
- Supreme Court: YYYY UT NN (e.g., "2026 UT 1")
- Court of Appeals: YYYY UT App NN (e.g., "2026 UT App 5")

Case number format: YYYYMMDD-CA or YYYYMMDD (e.g., "20220502-CA")
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

# Court type to URL path mapping
COURT_TYPE_TO_PATH: dict[str, str] = {
    "utah": "supopin",  # Supreme Court
    "utahctapp": "appopin",  # Court of Appeals
}

# Reverse mapping
PATH_TO_COURT_ID: dict[str, str] = {v: k for k, v in COURT_TYPE_TO_PATH.items()}

# All supported court IDs
COURT_IDS: set[str] = {"utah", "utahctapp"}

# Display names for courts
COURT_NAMES: dict[str, str] = {
    "utah": "Utah Supreme Court",
    "utahctapp": "Utah Court of Appeals",
}

# Base URL for opinions
BASE_URL = "https://legacy.utcourts.gov/opinions"


class UtahOpinion(Opinion):
    """An individual opinion document from Utah appellate courts.

    Extends Opinion from base.py with required fields for Utah courts.
    """

    download_url: str
    """URL to the opinion PDF (required)"""

    type: str = "majority"
    """Opinion type: 'majority', 'dissent', 'concurrence', etc."""

    local_path: str | None = None
    """Local filesystem path where the PDF was downloaded (set by driver)"""


class UtahOpinionCluster(OpinionCluster):
    """A cluster of opinions from Utah appellate courts.

    This is the main output type yielded by the scraper for opinions.
    Each cluster represents a case with its opinion PDF.

    Supports Utah Supreme Court (utah) and Court of Appeals (utahctapp).
    """

    # === Searchable fields ===
    citation: Annotated[str, UniqueMatch()]
    """Official citation (e.g., '2026 UT 1' or '2026 UT App 5') - unique identifier"""

    court_id: Annotated[str, SetFilter()]
    """Court identifier: 'utah' or 'utahctapp'"""

    date_filed: Annotated[date, DateRange()]
    """Date the opinion was filed"""

    # === Required fields ===
    case_name: str
    """Case name/caption (e.g., 'State v. Macbeth')"""

    case_number: str
    """Case number (e.g., '20230512-CA')"""

    # === Optional fields ===
    year: int | None = None
    """Year of the opinion"""

    # === Related data ===
    opinions: list[UtahOpinion] = []
    """All opinions in this cluster (usually just one majority opinion)"""

    # === Source tracking ===
    source_url: str | None = None
    """URL of the opinions listing page"""
