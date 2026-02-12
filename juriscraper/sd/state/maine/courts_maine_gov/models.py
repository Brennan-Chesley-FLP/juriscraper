"""Data models for Maine appellate courts scraper.

These models extend ConsumerModel types from base.py to capture
Maine Supreme Judicial Court opinion data.

Mapping to base.py types:
- MaineOpinion -> Opinion (individual opinion document)
- MaineOpinionCluster -> OpinionCluster (group of related opinions)

Supported courts:
- me: Maine Supreme Judicial Court (Law Court)

Note: Maine does not have an intermediate appellate court.
All appeals go directly to the Supreme Judicial Court.
"""

from __future__ import annotations

from datetime import date

from kent.common.models.base import (
    Opinion,
    OpinionCluster,
)

# Court ID mapping to CourtListener IDs
COURT_IDS = {
    "me": "Supreme Judicial Court of Maine",
}


class MaineOpinion(Opinion):
    """An individual opinion document from Maine Supreme Judicial Court.

    Extends Opinion from base.py with required fields for Maine courts.
    """

    download_url: str
    """URL to the opinion PDF"""

    local_path: str | None = None
    """Local filesystem path where the PDF was downloaded (set by driver)"""


class MaineOpinionCluster(OpinionCluster):
    """A cluster of opinions from Maine Supreme Judicial Court.

    This is the main output type yielded by the scraper.
    Each cluster represents a single published opinion.

    Citation format: {Year} ME {Number} (e.g., "2026 ME 4")
    """

    # === Searchable fields ===
    docket_id: str  # type: ignore[assignment]
    """Citation number (e.g., '2026 ME 4')"""

    court_id: str
    """Court identifier: 'me' (Maine Supreme Judicial Court)"""

    date_filed: date
    """Publication date of the opinion"""

    # === Required fields from base ===
    case_name: str
    """Case name (e.g., 'State of Maine v. Daniel Gantnier')"""

    # === Related data ===
    opinions: list[MaineOpinion] = []
    """All opinions in this cluster (typically just one)"""

    # === Source tracking ===
    source_url: str | None = None
    """URL of the page where this was found"""

    # === Maine-specific fields ===
    opinion_number: int
    """The numeric opinion number within the year (e.g., 4 for '2026 ME 4')"""

    year: int
    """The year of the opinion (e.g., 2026)"""
