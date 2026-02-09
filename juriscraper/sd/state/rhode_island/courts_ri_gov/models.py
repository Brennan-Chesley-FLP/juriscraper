"""Data models for Rhode Island appellate courts scraper.

These models extend ConsumerModel types from base.py to capture
Rhode Island Supreme Court opinion data.

Mapping to base.py types:
- RhodeIslandOpinion -> Opinion (individual opinion document)
- RhodeIslandOpinionCluster -> OpinionCluster (group of related opinions)

Supported courts:
- ri: Supreme Court of Rhode Island

Note: Rhode Island does not have an intermediate appellate court.
All appeals go directly to the Supreme Court.
"""

from __future__ import annotations

from datetime import date

from juriscraper.scraper_driver.common.models.base import (
    Opinion,
    OpinionCluster,
)

# Court ID mapping to CourtListener IDs
COURT_IDS = {
    "ri": "Supreme Court of Rhode Island",
}


class RhodeIslandOpinion(Opinion):
    """An individual opinion document from Rhode Island Supreme Court.

    Extends Opinion from base.py with required fields for Rhode Island courts.
    """

    download_url: str
    """URL to the opinion PDF"""

    local_path: str | None = None
    """Local filesystem path where the PDF was downloaded (set by driver)"""


class RhodeIslandOpinionCluster(OpinionCluster):
    """A cluster of opinions from Rhode Island Supreme Court.

    This is the main output type yielded by the scraper.
    Each cluster represents a single published opinion.

    Case number format examples:
    - "2025-0021-Appeal."
    - "2024-0269-Appeal."
    - "2023-0082-M.P."
    - "2024-0038-C.A."
    """

    # === Searchable fields ===
    docket_number: str
    """Case number (e.g., '2025-0021-Appeal.')"""

    court_id: str
    """Court identifier: 'ri' (Supreme Court of Rhode Island)"""

    date_filed: date
    """Publication date of the opinion"""

    # === Required fields from base ===
    case_name: str
    """Case name (e.g., 'Clifton Peasley v. City of Providence')"""

    # === Related data ===
    opinions: list[RhodeIslandOpinion] = []
    """All opinions in this cluster (typically just one)"""

    # === Source tracking ===
    source_url: str | None = None
    """URL of the page where this was found"""

    # === Rhode Island-specific fields ===
    summary: str | None = None
    """Brief summary of the opinion from the search results"""

    year: int
    """The year of the opinion publication"""
