"""Data models for Michigan appellate courts scraper.

These models extend ConsumerModel types from base.py to capture
Michigan Supreme Court and Court of Appeals opinion data.

Mapping to base.py types:
- MichiganOpinion -> Opinion (individual opinion document)
- MichiganOpinionCluster -> OpinionCluster (group of related opinions)

Supported courts:
- mich: Michigan Supreme Court
- michctapp: Michigan Court of Appeals
"""

from __future__ import annotations

from datetime import date

from kent.common.models.base import (
    Opinion,
    OpinionCluster,
)

# Court ID mapping to CourtListener IDs
COURT_IDS = {
    "mich": "Michigan Supreme Court",
    "michctapp": "Michigan Court of Appeals",
}


class MichiganOpinion(Opinion):
    """An individual opinion document from Michigan appellate courts.

    Extends Opinion from base.py with required fields for Michigan courts.
    """

    download_url: str
    """URL to the opinion PDF"""

    local_path: str | None = None
    """Local filesystem path where the PDF was downloaded (set by driver)"""


class MichiganOpinionCluster(OpinionCluster):
    """A cluster of opinions from Michigan appellate courts.

    This is the main output type yielded by the scraper.
    Each cluster represents a case with its opinion document.

    Supports both Michigan Supreme Court (mich) and
    Court of Appeals (michctapp).
    """

    # === Searchable fields ===
    docket_number: str  # type: ignore[assignment]
    """Docket number (e.g., '167745' for Supreme Court, '366123' for COA)"""

    court_id: str
    """Court identifier: 'mich' (Supreme Court) or 'michctapp' (Court of Appeals)"""

    date_filed: date
    """Publication date of the opinion from the ZIP file release date"""

    # === Required fields from base ===
    case_name: str
    """Case name (e.g., 'People v Carson')"""

    # === Related data ===
    opinions: list[MichiganOpinion] = []
    """All opinions in this cluster (typically just one per case)"""

    # === Source tracking ===
    source_url: str | None = None
    """URL of the ZIP file where this was found"""

    # === Michigan-specific fields ===
    precedential_status: str = "Unknown"
    """'Published', 'Unpublished', or 'Unknown'"""

    pdf_filename: str | None = None
    """Original filename from the ZIP file (e.g., '167745_74_01.pdf')"""
