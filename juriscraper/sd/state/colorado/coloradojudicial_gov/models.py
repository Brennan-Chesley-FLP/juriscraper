"""Data models for Colorado appellate courts scraper.

These models extend ConsumerModel types from base.py to capture
Colorado Supreme Court and Court of Appeals opinion data.

Mapping to base.py types:
- ColoradoOpinion -> Opinion (individual opinion document)
- ColoradoOpinionCluster -> OpinionCluster (group of related opinions)

Supported courts:
- colo: Colorado Supreme Court (docket prefix: SC, SA)
- coloctapp: Colorado Court of Appeals (docket prefix: CA)
"""

from __future__ import annotations

from datetime import date

from juriscraper.scraper_driver.common.models.base import (
    Opinion,
    OpinionCluster,
)

# Court ID mapping
COURT_IDS = {
    "colo": "Colorado Supreme Court",
    "coloctapp": "Colorado Court of Appeals",
}

# Docket prefixes by court
# SC = Supreme Court certiorari/appeal cases
# SA = Supreme Court original jurisdiction cases
# CA = Court of Appeals cases
DOCKET_PREFIX_TO_COURT = {
    "SC": "colo",
    "SA": "colo",
    "CA": "coloctapp",
}

COURT_TO_DOCKET_PREFIXES = {
    "colo": {"SC", "SA"},
    "coloctapp": {"CA"},
}


class ColoradoOpinion(Opinion):
    """An individual opinion document from Colorado appellate courts.

    Extends Opinion from base.py with required fields for CO courts.
    """

    download_url: str
    """URL to the opinion PDF"""

    type: str = "majority"
    """Opinion type: 'majority', 'dissent', 'concurrence', etc."""

    local_path: str | None = None
    """Local filesystem path where the PDF was downloaded (set by driver)"""


class ColoradoOpinionCluster(OpinionCluster):
    """A cluster of opinions from Colorado appellate courts.

    This is the main output type yielded by the scraper.
    Each cluster represents a case that may have multiple opinions.

    Supports both Colorado Supreme Court (colo) and
    Colorado Court of Appeals (coloctapp).

    Data sources:
    - Slip opinions: https://www.coloradojudicial.gov/supreme-court/opinions
    - Case Law Search: https://research.coloradojudicial.gov/
    """

    # === Searchable fields ===
    docket_number: str
    """Docket number (e.g., '25SC347' for Supreme Court, '24CA1951' for Appeals)"""

    court_id: str
    """Court identifier: 'colo' (Supreme Court) or 'coloctapp' (Court of Appeals)"""

    date_filed: date
    """Decision date / publication date"""

    # === Required fields from base ===
    case_name: str
    """Case name (e.g., 'Jones v. People')"""

    # === Citation information ===
    citation: str | None = None
    """Official citation (e.g., '2025 CO 63' or '2025 COA 1')"""

    neutral_citation: str | None = None
    """Neutral citation format"""

    # === Parties information ===
    parties_full: str | None = None
    """Full parties description from case law search"""

    # === Related data ===
    opinions: list[ColoradoOpinion] = []
    """All opinions in this cluster (majority, dissents, concurrences)"""

    # === Source tracking ===
    source_url: str | None = None
    """URL where this opinion was found"""

    vlex_id: str | None = None
    """vLex document ID from Case Law Search"""

    node_id: str | None = None
    """Drupal node ID from coloradojudicial.gov"""

    # === Publication status ===
    precedential_status: str = "Published"
    """Publication status: 'Published' or 'Unpublished'"""

    is_modified: bool = False
    """Whether this is a modified opinion (indicated by 'M' suffix in citation)"""
