"""Data models for Florida appellate courts scraper.

These models extend base model types from kent to capture
Florida Supreme Court and District Courts of Appeal data.

Mapping to base.py types:
- FloridaOpinion -> Opinion (individual opinion document)
- FloridaOpinionCluster -> OpinionCluster (group of related opinions)

Supported courts:
- fla: Florida Supreme Court
- fladistctapp1: First District Court of Appeal
- fladistctapp2: Second District Court of Appeal
- fladistctapp3: Third District Court of Appeal
- fladistctapp4: Fourth District Court of Appeal
- fladistctapp5: Fifth District Court of Appeal
- fladistctapp6: Sixth District Court of Appeal
"""

from __future__ import annotations

from datetime import date
from typing import TypedDict

from kent.common.models.base import (
    Opinion,
    OpinionCluster,
)

# Court ID mapping (CourtListener IDs)
COURT_IDS = {
    "fla": "Florida Supreme Court",
    "fladistctapp1": "First District Court of Appeal",
    "fladistctapp2": "Second District Court of Appeal",
    "fladistctapp3": "Third District Court of Appeal",
    "fladistctapp4": "Fourth District Court of Appeal",
    "fladistctapp5": "Fifth District Court of Appeal",
    "fladistctapp6": "Sixth District Court of Appeal",
}


class CourtConfigEntry(TypedDict):
    """Type definition for court configuration entries."""

    name: str
    siteaccess: str
    opinions_url: str


# Court configuration for scraping
# siteaccess values are used in the API calls to flcourts-media.flcourts.gov
COURT_CONFIG: dict[str, CourtConfigEntry] = {
    "fla": {
        "name": "Florida Supreme Court",
        "siteaccess": "supreme2",
        "opinions_url": "https://supremecourt.flcourts.gov/Opinions/Most-Recent-Opinions",
    },
    "fladistctapp1": {
        "name": "First District Court of Appeal",
        "siteaccess": "1dca",
        "opinions_url": "https://1dca.flcourts.gov/opinions",
    },
    "fladistctapp2": {
        "name": "Second District Court of Appeal",
        "siteaccess": "2dca",
        "opinions_url": "https://2dca.flcourts.gov/opinions",
    },
    "fladistctapp3": {
        "name": "Third District Court of Appeal",
        "siteaccess": "3dca",
        "opinions_url": "https://3dca.flcourts.gov/opinions",
    },
    "fladistctapp4": {
        "name": "Fourth District Court of Appeal",
        "siteaccess": "4dca",
        "opinions_url": "https://4dca.flcourts.gov/opinions",
    },
    "fladistctapp5": {
        "name": "Fifth District Court of Appeal",
        "siteaccess": "5dca",
        "opinions_url": "https://5dca.flcourts.gov/opinions",
    },
    "fladistctapp6": {
        "name": "Sixth District Court of Appeal",
        "siteaccess": "6dca",
        "opinions_url": "https://6dca.flcourts.gov/opinions",
    },
}

# API configuration
API_CONFIG = {
    "search_endpoint": "https://flcourts-media.flcourts.gov/_search/opinions",
    "content_download_base": "https://flcourts-media.flcourts.gov/content/download",
}


class FloridaOpinion(Opinion):
    """An individual opinion document from Florida appellate courts.

    Extends Opinion from base.py with required fields for FL courts.
    """

    download_url: str
    """URL to the opinion PDF (required)"""

    type: str = "010combined"
    """Opinion type: uses base Opinion constants"""

    local_path: str | None = None
    """Local filesystem path where the PDF was downloaded (set by driver)"""

    # Florida-specific fields
    content_id: str | None = None
    """Content ID from flcourts-media (the download ID in the URL)"""


class FloridaOpinionCluster(OpinionCluster):
    """A cluster of opinions from Florida appellate courts.

    This is the main output type yielded by the scraper for opinions.
    Each cluster represents a case that may have multiple opinions.

    Supports Florida Supreme Court (fla) and all six District Courts
    of Appeal (fladistctapp1-6).
    """

    # === Searchable fields ===
    case_number: str
    """Case number (e.g., 'SC24-123' or '1D24-1234')"""

    court_id: str
    """Court identifier: 'fla' or 'fladistctapp1' through 'fladistctapp6'"""

    date_filed: date
    """Date the opinion was filed/released"""

    # === Required fields ===
    case_name: str
    """Case name (e.g., 'State v. Smith')"""

    # === Florida-specific fields ===
    note: str | None = None
    """Note field from the opinions table (e.g., 'Revised Opinion')"""

    oral_argument_url: str | None = None
    """URL to oral argument video (if available)"""

    # === Related data ===
    opinions: list[FloridaOpinion] = []
    """All opinions in this cluster"""

    # === Source tracking ===
    source_url: str | None = None
    """URL of the opinions listing page"""
