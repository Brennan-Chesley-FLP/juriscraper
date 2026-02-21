"""Data models for Illinois appellate courts scraper.

These models extend base model types from kent to capture
Illinois Supreme Court and Appellate Court opinion data.

Mapping to base.py types:
- IllinoisOpinion -> Opinion (individual opinion document)
- IllinoisOpinionCluster -> OpinionCluster (group of related opinions)

Supported courts:
- ill: Illinois Supreme Court
- illappct: Appellate Court of Illinois (all 5 districts)

Citation formats:
- Supreme Court: YYYY IL XXXXXX (e.g., "2025 IL 131564")
- Appellate Court: YYYY IL App (Xd) XXXXXX (e.g., "2026 IL App (1st) 240123")
- Rule 23 orders add "-U" suffix: "2026 IL App (1st) 241387-U"

RSS Feeds:
- Supreme Court: https://www.illinoiscourts.gov/views/courts/rss/opinions-supreme.aspx
- Appellate Court: https://www.illinoiscourts.gov/views/courts/rss/opinions-appellate.aspx
"""

from __future__ import annotations

from datetime import date

from kent.common.models.base import (
    Opinion,
    OpinionCluster,
)

# Court ID mapping to CourtListener IDs
COURT_IDS = {
    "ill": "Illinois Supreme Court",
    "illappct": "Appellate Court of Illinois",
}

# Mapping from RSS court names to CourtListener court IDs
COURT_NAME_TO_ID: dict[str, str] = {
    "Supreme Court": "ill",
    "First District Appellate Court": "illappct",
    "Second District Appellate Court": "illappct",
    "Third District Appellate Court": "illappct",
    "Fourth District Appellate Court": "illappct",
    "Fifth District Appellate Court": "illappct",
    "Workers' Compensation Commission Division": "illappct",
}

# Mapping from court name in RSS to district number
COURT_NAME_TO_DISTRICT: dict[str, str | None] = {
    "Supreme Court": None,
    "First District Appellate Court": "1st",
    "Second District Appellate Court": "2d",
    "Third District Appellate Court": "3d",
    "Fourth District Appellate Court": "4th",
    "Fifth District Appellate Court": "5th",
    "Workers' Compensation Commission Division": "WC",
}


class IllinoisOpinion(Opinion):
    """An individual opinion document from Illinois appellate courts.

    Extends Opinion from base.py with required fields for Illinois courts.
    """

    download_url: str
    """URL to the opinion PDF"""

    type: str
    """Opinion type: 'Opinion' or 'Rule 23'"""

    local_path: str | None = None
    """Local filesystem path where the PDF was downloaded (set by driver)"""


class IllinoisOpinionCluster(OpinionCluster):
    """A cluster of opinions from Illinois appellate courts.

    This is the main output type yielded by the scraper.
    Each cluster represents a case that may have the main opinion
    plus optional summary/notes documents.

    Supports both Illinois Supreme Court (ill) and
    Appellate Court of Illinois (illappct).
    """

    # === Searchable fields ===
    docket_id: str  # type: ignore[assignment]
    """Citation number (e.g., '2025 IL 131564' or '2026 IL App (1st) 240123')"""

    court_id: str
    """Court identifier: 'ill' (Supreme Court) or 'illappct' (Appellate Court)"""

    date_filed: date
    """Publication date of the opinion"""

    # === Required fields from base ===
    case_name: str
    """Case name (e.g., 'People v. Seymore')"""

    # === Related data ===
    opinions: list[IllinoisOpinion] = []
    """All opinions/orders in this cluster"""

    # === Source tracking ===
    source_url: str | None = None
    """URL of the RSS feed where this was found"""

    # === Illinois-specific fields ===
    opinion_type: str | None = None
    """Type of decision: 'Opinion' or 'Rule 23'"""

    docket_status: str | None = None
    """Status of the opinion: 'Slip', 'Released', or 'Final'"""

    district: str | None = None
    """Appellate district (1st, 2d, 3d, 4th, 5th) or None for Supreme Court"""

    summary_url: str | None = None
    """URL to case summary PDF if available"""

    guid: str | None = None
    """Unique identifier from RSS feed"""
