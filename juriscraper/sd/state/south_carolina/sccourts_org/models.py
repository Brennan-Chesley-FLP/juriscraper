"""Data models for South Carolina appellate courts scraper.

These models extend ConsumerModel types from base.py to capture
South Carolina Supreme Court and Court of Appeals opinions.

Mapping to base.py types:
- SCOpinion -> Opinion (individual opinion document)
- SCOpinionCluster -> OpinionCluster (group of related opinions)

Supported courts (from courts.toml):
- sc: Supreme Court of South Carolina
- scctapp: Court of Appeals of South Carolina

The South Carolina opinion pages organize opinions by:
- Court (Supreme Court or Court of Appeals)
- Month/Year
- Published vs Unpublished status

Opinion URL patterns:
- Supreme Court: https://www.sccourts.org/media/opinions/HTMLFiles/SC/{opinion_number}.pdf
- Court of Appeals: https://www.sccourts.org/media/opinions/HTMLFiles/COA/{opinion_number}.pdf
"""

from __future__ import annotations

from datetime import date

from kent.common.models.base import (
    Opinion,
    OpinionCluster,
)

# Court ID mapping
COURT_IDS: set[str] = {"sc", "scctapp"}

# Court display names
COURT_NAMES: dict[str, str] = {
    "sc": "Supreme Court of South Carolina",
    "scctapp": "Court of Appeals of South Carolina",
}

# URL path segment for each court
COURT_URL_SEGMENT: dict[str, str] = {
    "sc": "supreme-court",
    "scctapp": "court-of-appeals",
}

# PDF path segment for each court
COURT_PDF_SEGMENT: dict[str, str] = {
    "sc": "SC",
    "scctapp": "COA",
}


class SCOpinion(Opinion):
    """An individual opinion document from South Carolina appellate courts.

    Extends Opinion from base.py with required fields for South Carolina courts.
    """

    download_url: str
    """URL to the opinion PDF (required)"""

    type: str = "majority"
    """Opinion type: 'majority', 'dissent', 'concurrence', etc."""

    local_path: str | None = None
    """Local filesystem path where the PDF was downloaded (set by driver)"""


class SCOpinionCluster(OpinionCluster):
    """A cluster of opinions from South Carolina appellate courts.

    This is the main output type yielded by the scraper for opinions.
    Each cluster represents a case that may have multiple opinions.

    Supports Supreme Court (sc) and Court of Appeals (scctapp).
    """

    # === Searchable fields ===
    opinion_number: str
    """Opinion number (e.g., '28309' for SC, '6128' for COA) - unique identifier"""

    court_id: str
    """Court identifier: 'sc' or 'scctapp'"""

    date_filed: date
    """Date the opinion was filed/published"""

    # === Required fields ===
    case_name: str
    """Case name/caption (e.g., 'Spring Valley Interests, LLC v. The Best for Last, LLC')"""

    # === Optional fields ===
    published: bool = True
    """Whether this is a published (precedential) opinion"""

    # === Related data ===
    opinions: list[SCOpinion] = []
    """All opinions in this cluster (majority, dissents, concurrences)"""

    # === Source tracking ===
    source_url: str | None = None
    """URL of the opinions listing page"""
