"""Data models for Maryland appellate courts scraper.

These models extend ConsumerModel types from base.py to capture
Maryland appellate court opinion data.

Mapping to base.py types:
- MarylandOpinion -> Opinion (individual opinion document)
- MarylandOpinionCluster -> OpinionCluster (group of related opinions)

Supported courts:
- md: Supreme Court of Maryland (formerly Court of Appeals of Maryland)
- mdctspecapp: Appellate Court of Maryland (formerly Court of Special Appeals)

Note: The courts were renamed effective December 14, 2022:
- Court of Appeals of Maryland -> Supreme Court of Maryland
- Court of Special Appeals of Maryland -> Appellate Court of Maryland
"""

from __future__ import annotations

from datetime import date

from kent.common.models.base import (
    Opinion,
    OpinionCluster,
)

# Court ID mapping to CourtListener IDs
# PDF URL path prefix -> court_id
COURT_IDS = {
    "coa": "md",  # Supreme Court (formerly Court of Appeals)
    "cosa": "mdctspecapp",  # Appellate Court (formerly Court of Special Appeals)
}

# Reverse mapping for filtering
COURT_ID_TO_PATH = {
    "md": "coa",
    "mdctspecapp": "cosa",
}


class MarylandOpinion(Opinion):
    """An individual opinion document from Maryland appellate courts.

    Extends Opinion from base.py with required fields for Maryland courts.
    """

    download_url: str
    """URL to the opinion PDF"""

    local_path: str | None = None
    """Local filesystem path where the PDF was downloaded (set by driver)"""


class MarylandOpinionCluster(OpinionCluster):
    """A cluster of opinions from Maryland appellate courts.

    This is the main output type yielded by the scraper.
    Each cluster represents a single published opinion.

    Docket number format: {case_number}/{term_year} (e.g., "3/25", "1991/23")
    """

    # === Searchable fields ===
    docket_id: str  # type: ignore[assignment]
    """Docket number (e.g., '3/25', '1991/23')"""

    court_id: str
    """Court identifier: 'md' (Supreme) or 'mdctspecapp' (Appellate)"""

    date_filed: date
    """Publication date of the opinion"""

    # === Required fields from base ===
    case_name: str
    """Case name (e.g., 'May. & City Cncl. Of Baltimore v. Varghese')"""

    # === Related data ===
    opinions: list[MarylandOpinion] = []
    """All opinions in this cluster (typically just one)"""

    # === Source tracking ===
    source_url: str | None = None
    """URL of the page where this was found"""

    # === Maryland-specific fields ===
    judge: str | None = None
    """Name of the authoring judge/justice"""

    citation: str | None = None
    """Official citation (e.g., 'slip.op.' or volume/page)"""

    year: int
    """The term year of the opinion (e.g., 2025)"""
