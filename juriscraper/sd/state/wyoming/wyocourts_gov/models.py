"""Data models for Wyoming appellate courts scraper.

These models extend ConsumerModel types from base.py to capture
Wyoming Supreme Court opinions.

Mapping to base.py types:
- WyomingOpinion -> Opinion (individual opinion document)
- WyomingOpinionCluster -> OpinionCluster (group of related opinions)

Supported courts (from courts.toml):
- wyo: Wyoming Supreme Court

Wyoming uses:
- Opinion ID format: YYYY WY # (e.g., "2026 WY 11")
- Docket number format: S-YY-NNNN (e.g., "S-25-0114")
"""

from __future__ import annotations

from datetime import date

from kent.common.models.base import (
    Opinion,
    OpinionCluster,
)

# Court ID mapping for Wyoming
COURT_IDS: set[str] = {"wyo"}


class WyomingOpinion(Opinion):
    """An individual opinion document from Wyoming Supreme Court.

    Extends Opinion from base.py with required fields for Wyoming courts.
    """

    download_url: str
    """URL to the opinion PDF (required)"""

    type: str = "majority"
    """Opinion type: 'majority', 'dissent', 'concurrence', etc."""

    local_path: str | None = None
    """Local filesystem path where the PDF was downloaded (set by driver)"""


class WyomingOpinionCluster(OpinionCluster):
    """A cluster of opinions from Wyoming Supreme Court.

    This is the main output type yielded by the scraper for opinions.
    Each cluster represents a case that may have multiple opinions
    (majority, dissents, concurrences).
    """

    # === Searchable fields ===
    opinion_id: str
    """Opinion ID citation (e.g., '2026 WY 11') - unique identifier"""

    court_id: str = "wyo"
    """Court identifier: 'wyo' for Wyoming Supreme Court"""

    date_filed: date
    """Date the opinion was published/decided"""

    # === Required fields ===
    case_name: str
    """Case name/caption combining appellant and appellee"""

    docket_number: str
    """Docket number (e.g., 'S-25-0114')"""

    # === Optional fields ===
    appellant: str | None = None
    """Appellant name"""

    appellee: str | None = None
    """Appellee name"""

    # === Related data ===
    opinions: list[WyomingOpinion] = []
    """All opinions in this cluster (majority, dissents, concurrences)"""

    # === Source tracking ===
    source_url: str | None = None
    """URL of the opinions listing page"""
