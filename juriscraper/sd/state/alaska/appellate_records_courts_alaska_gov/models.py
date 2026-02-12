"""Data models for Alaska appellate courts scraper.

These models extend ConsumerModel types from base.py to capture
Alaska Supreme Court and Court of Appeals opinion data.

Mapping to base.py types:
- AlaskaOpinion -> Opinion (individual opinion document)
- AlaskaOpinionCluster -> OpinionCluster (group of related opinions)

Supported courts:
- alaska: Alaska Supreme Court
- alaskactapp: Alaska Court of Appeals
"""

from __future__ import annotations

from datetime import date

from kent.common.models.base import (
    Opinion,
    OpinionCluster,
)

# Court ID mapping
COURT_IDS = {
    "alaska": "Alaska Supreme Court",
    "alaskactapp": "Alaska Court of Appeals",
}

# Court configuration for scraping
COURT_CONFIG = {
    "alaska": {
        "name": "Alaska Supreme Court",
        "opinion_url": "https://appellate-records.courts.alaska.gov/CMSPublic/Home/Opinions?isCOA=False",
        "case_number_prefix": "S",
    },
    "alaskactapp": {
        "name": "Alaska Court of Appeals",
        "opinion_url": "https://appellate-records.courts.alaska.gov/CMSPublic/Home/Opinions?isCOA=True",
        "case_number_prefix": "A",
    },
}

# Base URL for the site
BASE_URL = "https://appellate-records.courts.alaska.gov"


class AlaskaOpinion(Opinion):
    """An individual opinion document from Alaska appellate courts.

    Extends Opinion from base.py with required fields for Alaska courts.
    """

    download_url: str
    """URL to the opinion PDF (required)"""

    type: str = "010combined"
    """Opinion type - default to COMBINED since Alaska doesn't distinguish"""

    local_path: str | None = None
    """Local filesystem path where the PDF was downloaded (set by driver)"""

    # Alaska-specific fields
    opinion_number: int | None = None
    """Opinion number (e.g., 7799)"""


class AlaskaOpinionCluster(OpinionCluster):
    """A cluster of opinions from Alaska appellate courts.

    This is the main output type yielded by the scraper for opinions.
    Each cluster represents a case from the opinion pages.

    Supports Alaska Supreme Court (alaska) and Court of Appeals (alaskactapp).
    """

    # === Searchable fields ===
    case_number: str
    """Case number (e.g., 'S19135' for Supreme Court, 'A14180' for Court of Appeals)"""

    court_id: str
    """Court identifier: 'alaska' or 'alaskactapp'"""

    date_filed: date
    """Date the opinion was filed/published (from release date on opinions page)"""

    # === Required fields ===
    case_name: str
    """Case name/title"""

    # === Alaska-specific fields ===
    opinion_number: int | None = None
    """Opinion number (e.g., 7799)"""

    pacific_reporter_citation: str | None = None
    """Pacific Reporter citation if published (e.g., '--- P.3d ---')"""

    # === Related data ===
    opinions: list[AlaskaOpinion] = []
    """All opinions in this cluster"""

    # === Source tracking ===
    source_url: str | None = None
    """URL of the opinions page where this was found"""

    case_url: str | None = None
    """URL to the case detail page"""
