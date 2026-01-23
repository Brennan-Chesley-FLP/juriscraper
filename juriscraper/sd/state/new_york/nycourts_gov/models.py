"""Data models for New York Court of Appeals scraper.

These models extend ConsumerModel types from base.py to capture
New York Court of Appeals opinion data.

Mapping to base.py types:
- NYOpinion -> Opinion (individual opinion document)
- NYOpinionCluster -> OpinionCluster (group of related opinions for a case)

Supported court:
- ny: New York Court of Appeals

Data source:
- Monthly decision pages at https://www.nycourts.gov/ctapps/Decisions/{YYYY}/{Mon}{YY}/{Month}{YY}.html
- Each decision day has a Decision List PDF and individual opinion PDFs

Opinion types (from filename suffixes):
- opn: Opinion (full opinion)
- mem: Memorandum (brief opinion)
- ent: Entry (order/entry)
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
    "ny": "New York Court of Appeals",
}

# Opinion type suffixes found in PDF filenames
OPINION_TYPES = {
    "opn": "Opinion",
    "mem": "Memorandum",
    "ent": "Entry",
}


def normalize_opinion_type(filename: str) -> str:
    """Extract opinion type from PDF filename.

    Args:
        filename: PDF filename like '112opn26-Decision.pdf' or '102mem25-Decision.pdf'

    Returns:
        Opinion type string (e.g., 'opn', 'mem', 'ent') or 'unknown'
    """
    filename_lower = filename.lower()
    for suffix in OPINION_TYPES:
        if suffix in filename_lower:
            return suffix
    return "unknown"


class NYOpinion(Opinion):
    """An individual opinion document from New York Court of Appeals.

    Extends Opinion from base.py with required fields for NY courts.
    """

    download_url: str
    """URL to the opinion PDF"""

    type: str
    """Opinion type based on filename suffix: 'opn', 'mem', 'ent', etc."""

    local_path: str | None = None
    """Local filesystem path where the PDF was downloaded (set by driver)"""


class NYOpinionCluster(OpinionCluster):
    """A cluster of opinions from New York Court of Appeals.

    This is the main output type yielded by the scraper.
    Each cluster represents a single opinion number (e.g., 'No. 112')
    from a decision day.

    The New York Court of Appeals is the highest court in New York State.
    """

    # === Searchable fields ===
    docket_id: Annotated[str, UniqueMatch()]  # type: ignore[assignment]
    """Opinion number (e.g., 'No. 112' or '112')"""

    court_id: Annotated[str, SetFilter()]
    """Court identifier: 'ny' (Court of Appeals)"""

    date_filed: Annotated[date, DateRange()]
    """Decision date"""

    # === Required fields from base ===
    case_name: str
    """Case name (e.g., 'The Matter of The Coalition for Fairness in Soho and Noho v. City of New York')"""

    # === Related data ===
    opinions: list[NYOpinion] = []
    """All opinions/orders in this cluster (typically one per case)"""

    # === Source tracking ===
    source_url: str | None = None
    """URL of the monthly decisions page where this was found"""

    # === NY-specific fields ===
    slip_op_number: str | None = None
    """Slip opinion number if available (e.g., '2026 NY Slip Op 00201')"""
