"""Data models for Arkansas appellate courts opinions scraper.

These models extend ConsumerModel types from base.py to capture
Arkansas Supreme Court and Court of Appeals opinion data from
the Lexum/Norma platform at https://opinions.arcourts.gov/

Mapping to base.py types:
- ArkOpinion -> Opinion (individual opinion document)
- ArkOpinionCluster -> OpinionCluster (group of related opinions)

Supported courts:
- ark: Arkansas Supreme Court
- arkctapp: Arkansas Court of Appeals

Citation formats:
- Supreme Court: "{year} Ark. {number}" (e.g., "2026 Ark. 4")
- Court of Appeals: "{year} Ark. App. {number}" (e.g., "2026 Ark. App. 40")
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
    SpeculativeID,
    UniqueMatch,
)

# Court ID mapping
COURT_IDS = {
    "ark": "Arkansas Supreme Court",
    "arkctapp": "Arkansas Court of Appeals",
}

# Court configuration for scraping
# URL path segments for each court
COURT_CONFIG: dict[str, dict[str, str]] = {
    "ark": {
        "name": "Arkansas Supreme Court",
        "url_path": "supremecourt",
        "citation_prefix": "Ark.",
    },
    "arkctapp": {
        "name": "Arkansas Court of Appeals",
        "url_path": "courtofappeals",
        "citation_prefix": "Ark. App.",
    },
}

# Base URL configuration
BASE_URL = "https://opinions.arcourts.gov"
BASE_PATH = "/ark"


class ArkOpinion(Opinion):
    """An individual opinion document from Arkansas appellate courts.

    Extends Opinion from base.py with required fields for Arkansas courts.
    """

    download_url: str
    """URL to the opinion PDF (required)"""

    type: str = "majority"
    """Opinion type: 'majority', 'dissent', 'concurrence', etc."""

    local_path: str | None = None
    """Local filesystem path where the PDF was downloaded (set by driver)"""


class ArkOpinionCluster(OpinionCluster):
    """A cluster of opinions from Arkansas appellate courts.

    This is the main output type yielded by the scraper for opinions.
    Each cluster represents a case from the opinions database.

    Supports Arkansas Supreme Court (ark) and Court of Appeals (arkctapp).
    """

    # === Searchable fields ===
    item_id: Annotated[int, SpeculativeID()]
    """Unique item ID from Lexum database (used for speculative scraping)"""

    court_id: Annotated[str, SetFilter()]
    """Court identifier: 'ark' or 'arkctapp'"""

    date_filed: Annotated[date, DateRange()]
    """Date the opinion was filed/published"""

    # === Required fields ===
    case_name: str
    """Case name/title"""

    # === Citation fields ===
    neutral_citation: str | None = None
    """Neutral citation (e.g., '2026 Ark. 4' or '2026 Ark. App. 40')"""

    docket_number: str | None = None
    """Docket/case number (e.g., 'CR-24-603')"""

    # === Arkansas-specific fields ===
    opinion_type: str | None = None
    """Opinion type from site (e.g., 'Supreme Court - Majority')"""

    term: str | None = None
    """Court term (e.g., '2026 Spring Term')"""

    # === Related data ===
    opinions: list[ArkOpinion] = []
    """All opinions in this cluster (usually just one PDF)"""

    # === Source tracking ===
    source_url: str | None = None
    """URL of the opinion item page"""
