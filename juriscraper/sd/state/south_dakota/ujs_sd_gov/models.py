"""Data models for South Dakota Supreme Court scraper.

These models extend ConsumerModel types from base.py to capture
South Dakota Supreme Court opinions.

Mapping to base.py types:
- SouthDakotaOpinion -> Opinion (individual opinion document)
- SouthDakotaOpinionCluster -> OpinionCluster (group of related opinions)

Supported courts (from courts.toml):
- sd: South Dakota Supreme Court

South Dakota does NOT have an intermediate Court of Appeals. All appeals
from circuit courts go directly to the Supreme Court.

Citation format: {YEAR} S.D. {NUMBER}
Examples:
- 2026 S.D. 2
- 2025 S.D. 74
"""

from __future__ import annotations

import re
from datetime import date

from juriscraper.scraper_driver.common.models.base import (
    Opinion,
    OpinionCluster,
)

# Court ID - South Dakota only has one appellate court
COURT_ID = "sd"

# Court display name
COURT_NAME = "South Dakota Supreme Court"

# Pattern for extracting citation from title
# Matches: "CASE NAME, YYYY S.D. NN" -> extracts year and number
CITATION_PATTERN = re.compile(r",?\s*(\d{4})\s+S\.?D\.?\s+(\d+)\s*$")

# Pattern for extracting case number from PDF URL
# Example: /media/wb0plwaw/31017.pdf -> 31017
CASE_NUMBER_PATTERN = re.compile(r"/(\d+(?:-\d+)*)\.pdf$")


def parse_citation(title: str) -> tuple[str | None, str | None, int | None]:
    """Parse case name and citation from a title string.

    Args:
        title: Full title like "ESTATE OF WEBB, 2026 S.D. 2"

    Returns:
        Tuple of (case_name, citation, opinion_number)
        Example: ("ESTATE OF WEBB", "2026 S.D. 2", 2)
    """
    match = CITATION_PATTERN.search(title)
    if match:
        year = match.group(1)
        number = match.group(2)
        citation = f"{year} S.D. {number}"
        case_name = title[: match.start()].strip().rstrip(",")
        return case_name, citation, int(number)
    return title.strip(), None, None


def extract_case_number_from_url(url: str) -> str | None:
    """Extract case number from PDF URL.

    Args:
        url: PDF URL like "/media/wb0plwaw/31017.pdf"

    Returns:
        Case number like "31017" or "30811-30812" for consolidated cases
    """
    match = CASE_NUMBER_PATTERN.search(url)
    if match:
        return match.group(1)
    return None


class SouthDakotaOpinion(Opinion):
    """An individual opinion document from South Dakota Supreme Court.

    Extends Opinion from base.py with required fields for South Dakota.
    """

    download_url: str
    """URL to the opinion PDF (required)"""

    type: str = "majority"
    """Opinion type: 'majority', 'dissent', 'concurrence', etc."""

    local_path: str | None = None
    """Local filesystem path where the PDF was downloaded (set by driver)"""


class SouthDakotaOpinionCluster(OpinionCluster):
    """A cluster of opinions from South Dakota Supreme Court.

    This is the main output type yielded by the scraper for opinions.
    Each cluster represents a case decision.

    Citation format: {YEAR} S.D. {NUMBER}
    """

    # === Searchable fields ===
    citation: str
    """South Dakota citation (e.g., '2026 S.D. 2') - unique identifier"""

    court_id: str = COURT_ID
    """Court identifier: always 'sd' for South Dakota Supreme Court"""

    date_filed: date
    """Date the opinion was filed/decided"""

    # === Required fields ===
    case_name: str
    """Case name/caption (e.g., 'ESTATE OF WEBB')"""

    # === Optional fields ===
    case_number: str | None = None
    """Internal case number from the court (e.g., '31017')"""

    opinion_number: int | None = None
    """Sequential opinion number for the year (e.g., 2 for '2026 S.D. 2')"""

    # === Related data ===
    opinions: list[SouthDakotaOpinion] = []
    """All opinions in this cluster (typically just one for SD)"""

    # === Source tracking ===
    source_url: str | None = None
    """URL of the opinions listing page"""
