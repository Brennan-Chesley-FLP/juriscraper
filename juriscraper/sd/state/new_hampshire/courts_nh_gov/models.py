"""Data models for New Hampshire Supreme Court scraper.

These models extend base model types from kent to capture
New Hampshire Supreme Court opinion data.

Mapping to base.py types:
- NHOpinion -> Opinion (individual opinion document)
- NHOpinionCluster -> OpinionCluster (group of related opinions)

Supported courts:
- nh: New Hampshire Supreme Court (the only appellate court in NH)

Note: New Hampshire does not have an intermediate Court of Appeals.
"""

from __future__ import annotations

from datetime import date

from kent.common.models.base import (
    Citation,
    Opinion,
    OpinionCluster,
)

# Court ID mapping to CourtListener IDs
COURT_IDS = {
    "nh": "Supreme Court of New Hampshire",
}


class NHOpinion(Opinion):
    """An individual opinion document from the NH Supreme Court.

    Extends Opinion from base.py with required fields for NH courts.
    """

    download_url: str
    """URL to the opinion PDF"""

    local_path: str | None = None
    """Local filesystem path where the PDF was downloaded (set by driver)"""


class NHCitation(Citation):
    """A citation for a New Hampshire opinion.

    Uses neutral citation format adopted January 1, 2024.
    Format: YYYY N.H. NN (e.g., '2025 N.H. 54')

    Prior to 2024, opinions were cited by case number.
    """

    # Override type to default to neutral citation
    type: int = Citation.NEUTRAL


class NHOpinionCluster(OpinionCluster):
    """A cluster of opinions from the New Hampshire Supreme Court.

    This is the main output type yielded by the scraper.
    Each cluster represents a case with its opinion PDF.

    New Hampshire adopted neutral citation format on January 1, 2024.
    Opinions prior to 2024 use case numbers for identification.
    """

    # === Searchable fields ===
    docket_number: str  # type: ignore[assignment]
    """Case number (e.g., '2025-0056')"""

    court_id: str
    """Court identifier: always 'nh' for NH Supreme Court"""

    date_filed: date
    """Publication date of the opinion"""

    # === Required fields from base ===
    case_name: str
    """Case name (e.g., 'Peregrine Interests LLC v. Todd')"""

    # === Citation fields ===
    citation_string: str | None = None
    """Neutral citation string (e.g., '2025 N.H. 54') - for 2024+ opinions"""

    opinion_number: int | None = None
    """The opinion number within the year (e.g., 54 for '2025 N.H. 54')"""

    # === Related data ===
    opinions: list[NHOpinion] = []
    """All opinions/orders in this cluster"""

    related_document_urls: list[str] = []
    """URLs to related documents referenced in the opinion"""

    # === Source tracking ===
    source_url: str | None = None
    """URL of the page where this was found"""
