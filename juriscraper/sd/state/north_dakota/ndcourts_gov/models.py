"""Data models for North Dakota appellate courts scraper.

These models extend ConsumerModel types from base.py to capture
North Dakota Supreme Court opinion data.

Mapping to base.py types:
- NorthDakotaOpinion -> Opinion (individual opinion document)
- NorthDakotaOpinionCluster -> OpinionCluster (group of related opinions)

Supported courts:
- nd: North Dakota Supreme Court

Note: North Dakota does not have an intermediate appellate court.
All appeals go directly to the Supreme Court.
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

# Court ID mapping to CourtListener IDs
COURT_IDS = {
    "nd": "North Dakota Supreme Court",
}


class NorthDakotaOpinion(Opinion):
    """An individual opinion document from North Dakota Supreme Court.

    Extends Opinion from base.py with required fields for North Dakota courts.
    """

    download_url: str
    """URL to the opinion PDF"""

    local_path: str | None = None
    """Local filesystem path where the PDF was downloaded (set by driver)"""


class NorthDakotaOpinionCluster(OpinionCluster):
    """A cluster of opinions from North Dakota Supreme Court.

    This is the main output type yielded by the scraper.
    Each cluster represents a single published opinion.

    Citation format: {Year} ND {Number} (e.g., "2026 ND 7")
    """

    # === Searchable fields ===
    docket_id: Annotated[str, UniqueMatch()]  # type: ignore[assignment]
    """Citation number (e.g., '2026 ND 7')"""

    court_id: Annotated[str, SetFilter()]
    """Court identifier: 'nd' (North Dakota Supreme Court)"""

    date_filed: Annotated[date, DateRange()]
    """Publication date of the opinion"""

    # === Required fields from base ===
    case_name: str
    """Case name (e.g., 'State v. Krall')"""

    # === Related data ===
    opinions: list[NorthDakotaOpinion] = []
    """All opinions in this cluster (typically just one)"""

    # === Source tracking ===
    source_url: str | None = None
    """URL of the page where this was found"""

    # === North Dakota-specific fields ===
    docket_number: str | None = None
    """Docket number (e.g., '20240233')"""

    case_type: str | None = None
    """Case type (e.g., 'Appeal - Criminal - Homicide')"""

    author_str: str | None = None
    """Author of the opinion (e.g., 'McEvers, Lisa K. Fair')"""

    internal_id: str | None = None
    """Internal database ID used in URLs (e.g., '202131')"""

    opinion_number: int | None = None
    """The numeric opinion number within the year (e.g., 7 for '2026 ND 7')"""

    year: int | None = None
    """The year of the opinion (e.g., 2026)"""
