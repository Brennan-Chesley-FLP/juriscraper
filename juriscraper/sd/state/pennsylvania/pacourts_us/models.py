"""Data models for Pennsylvania appellate courts scraper.

These models extend ConsumerModel types from base.py to capture
Pennsylvania Supreme Court, Superior Court, and Commonwealth Court
opinion data from the RSS feeds at pacourts.us.

Mapping to base.py types:
- PennsylvaniaOpinion -> Opinion (individual opinion document)
- PennsylvaniaOpinionCluster -> OpinionCluster (group of related opinions)

Supported courts:
- pa: Supreme Court of Pennsylvania
- pasuperct: Superior Court of Pennsylvania
- pacommwct: Commonwealth Court of Pennsylvania
"""

from __future__ import annotations

from datetime import date
from typing import Annotated, ClassVar

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
COURT_IDS: set[str] = {
    "pa",         # Supreme Court of Pennsylvania
    "pasuperct",  # Superior Court of Pennsylvania
    "pacommwct",  # Commonwealth Court of Pennsylvania
}

COURT_NAMES: dict[str, str] = {
    "pa": "Supreme Court of Pennsylvania",
    "pasuperct": "Superior Court of Pennsylvania",
    "pacommwct": "Commonwealth Court of Pennsylvania",
}

# Mapping from RSS feed court name to court_id
RSS_COURT_TO_COURT_ID: dict[str, str] = {
    "Supreme": "pa",
    "Superior": "pasuperct",
    "Commonwealth": "pacommwct",
}

# Mapping from court_id to RSS feed court name (for URL construction)
COURT_ID_TO_RSS_COURT: dict[str, str] = {
    "pa": "Supreme",
    "pasuperct": "Superior",
    "pacommwct": "Commonwealth",
}


class PennsylvaniaOpinion(Opinion):
    """An individual opinion document from Pennsylvania appellate courts.

    Extends Opinion from base.py with required fields for Pennsylvania courts.
    """

    download_url: str
    """URL to the opinion PDF"""

    type: str = "majority"
    """Opinion type based on dc:creator and title (majority, concurrence, dissent, per_curiam)"""

    local_path: str | None = None
    """Local filesystem path where the PDF was downloaded (set by driver)"""

    author_str: str | None = None
    """Author/judge name from dc:creator field"""


class PennsylvaniaOpinionCluster(OpinionCluster):
    """A cluster of opinions from Pennsylvania appellate courts.

    This is the main output type yielded by the scraper.
    Each cluster represents a case that may have multiple related documents
    (e.g., majority opinion, dissent, concurrence).

    Supports all three Pennsylvania appellate courts:
    - Supreme Court (pa)
    - Superior Court (pasuperct)
    - Commonwealth Court (pacommwct)
    """

    # === Searchable fields ===
    docket_number: Annotated[str, UniqueMatch()]
    """Case docket number (e.g., '95 MAP 2024', '876 WDA 2024', '918 C.D. 2024')"""

    court_id: Annotated[str, SetFilter()]
    """Court identifier: 'pa' (Supreme), 'pasuperct' (Superior), 'pacommwct' (Commonwealth)"""

    date_filed: Annotated[date, DateRange()]
    """Publication date of the opinion (from RSS pubDate)"""

    # === Required fields from base ===
    case_name: str
    """Case name extracted from RSS title (e.g., 'Commonwealth v. Fitzpatrick')"""

    # === Related data ===
    opinions: list[PennsylvaniaOpinion] = []
    """All opinions/orders in this cluster"""

    # === Source tracking ===
    source_url: str | None = None
    """URL of the RSS feed where this was found"""

    guid: str | None = None
    """RSS GUID (usually the PDF URL) for deduplication"""

    # === Pennsylvania-specific fields ===
    posting_type: str | None = None
    """Type of posting (e.g., 'Majority Opinion', 'Per Curiam Order', 'Dissenting Opinion')"""

    raw_title: str | None = None
    """Original RSS title for debugging/reference"""

    # Opinion type constants for parsing
    OPINION_TYPE_MAJORITY: ClassVar[str] = "majority"
    OPINION_TYPE_CONCURRENCE: ClassVar[str] = "concurrence"
    OPINION_TYPE_DISSENT: ClassVar[str] = "dissent"
    OPINION_TYPE_PER_CURIAM: ClassVar[str] = "per_curiam"
    OPINION_TYPE_ORDER: ClassVar[str] = "order"
    OPINION_TYPE_UNKNOWN: ClassVar[str] = "unknown"
