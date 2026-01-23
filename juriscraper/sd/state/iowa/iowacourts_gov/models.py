"""Data models for Iowa appellate courts scraper.

These models extend ConsumerModel types from base.py to capture
Iowa Supreme Court and Court of Appeals opinion data.

Mapping to base.py types:
- IowaOpinion -> Opinion (individual opinion document)
- IowaOpinionCluster -> OpinionCluster (group of related opinions)

Supported courts:
- iowa: Iowa Supreme Court
- iowactapp: Iowa Court of Appeals
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
    "iowa": "Iowa Supreme Court",
    "iowactapp": "Iowa Court of Appeals",
}

# URL patterns by court
COURT_URLS = {
    "iowa": "https://www.iowacourts.gov/iowa-courts/supreme-court/supreme-court-opinions/",
    "iowactapp": "https://www.iowacourts.gov/iowa-courts/court-of-appeals/court-of-appeals-court-opinions/",
}

# PDF embed type by court
COURT_OPINION_TYPE = {
    "iowa": "SupremeCourtOpinion",
    "iowactapp": "CourtAppealsOpinion",
}


class IowaOpinion(Opinion):
    """An individual opinion document from Iowa appellate courts.

    Extends Opinion from base.py with required fields for Iowa courts.
    """

    download_url: str
    """URL to the opinion PDF"""

    type: str = "opinion"
    """Opinion type: 'opinion', 'order', etc."""

    local_path: str | None = None
    """Local filesystem path where the PDF was downloaded (set by driver)"""


class IowaOpinionCluster(OpinionCluster):
    """A cluster of opinions from Iowa appellate courts.

    This is the main output type yielded by the scraper.
    Each cluster represents a case that may have multiple related documents
    (e.g., Supreme Court opinion, Court of Appeals opinion, briefs).

    Supports both Iowa Supreme Court (iowa) and
    Court of Appeals (iowactapp).
    """

    # === Searchable fields ===
    docket_id: Annotated[str, UniqueMatch()]  # type: ignore[assignment]
    """Case number (e.g., '23-1794' for Supreme Court, '24-0249' for Court of Appeals)"""

    court_id: Annotated[str, SetFilter()]
    """Court identifier: 'iowa' (Supreme Court) or 'iowactapp' (Court of Appeals)"""

    date_filed: Annotated[date, DateRange()]
    """Publication date of the opinion"""

    # === Required fields from base ===
    case_name: str
    """Case name (e.g., 'State of Iowa v. John Walter Spooner')"""

    # === Related data ===
    opinions: list[IowaOpinion] = []
    """All opinions in this cluster"""

    # === Source tracking ===
    source_url: str | None = None
    """URL of the page where this was found"""

    # === Iowa-specific fields ===
    county: str | None = None
    """County where the case originated (e.g., 'Polk')"""

    trial_court_case_number: str | None = None
    """Trial court case number (e.g., 'LACL155126')"""

    summary: str | None = None
    """Case summary/abstract from the case detail page"""

    internal_id: int | None = None
    """Internal case ID used in URLs (e.g., 22626 from /courtcases/22626/)"""
