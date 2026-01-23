"""Data models for Minnesota appellate courts scraper.

These models extend ConsumerModel types from base.py to capture
Minnesota appellate court opinion data.

Mapping to base.py types:
- MNOpinion -> Opinion (individual opinion document)
- MNOpinionCluster -> OpinionCluster (group of related opinions)

Supported courts:
- minn: Supreme Court of Minnesota
- minnctapp: Court of Appeals of Minnesota

Opinion types:
- Supreme Court: Standard opinions (binding precedent)
- Court of Appeals: Precedential (binding) and Nonprecedential (persuasive only)
"""

from __future__ import annotations

from datetime import date
from enum import Enum
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


class MNCourt(str, Enum):
    """Minnesota appellate court identifiers."""

    SUPREME_COURT = "minn"
    COURT_OF_APPEALS = "minnctapp"


class PrecedentialStatus(str, Enum):
    """Precedential status for Minnesota opinions."""

    PRECEDENTIAL = "Precedential"  # Binding (Supreme Court + CoA precedential)
    NONPRECEDENTIAL = "Nonprecedential"  # Persuasive only (CoA unpublished)


# Court ID mapping to CourtListener IDs
COURT_IDS = {
    "minn": "Supreme Court of Minnesota",
    "minnctapp": "Court of Appeals of Minnesota",
}


class MNOpinion(Opinion):
    """An individual opinion document from Minnesota appellate courts.

    Extends Opinion from base.py with required fields for Minnesota courts.
    """

    download_url: str
    """URL to the opinion PDF"""

    local_path: str | None = None
    """Local filesystem path where the PDF was downloaded (set by driver)"""


class MNOpinionCluster(OpinionCluster):
    """A cluster of opinions from Minnesota appellate courts.

    This is the main output type yielded by the scraper.
    Each cluster represents a single opinion release.

    Docket number format: A{YY}-{NNNN} (e.g., 'A25-0268')
    where A = Appeal, YY = year, NNNN = sequence number
    """

    # === Searchable fields ===
    docket_id: Annotated[str, UniqueMatch()]  # type: ignore[assignment]
    """Docket number (e.g., 'A25-0268')"""

    court_id: Annotated[str, SetFilter()]
    """Court identifier: 'minn' or 'minnctapp'"""

    date_filed: Annotated[date, DateRange()]
    """Release date of the opinion"""

    # === Required fields from base ===
    case_name: str
    """Case name (e.g., 'State of Minnesota vs. Jim Duramax Whitcomb')"""

    # === Related data ===
    opinions: list[MNOpinion] = []
    """All opinions in this cluster (typically just one)"""

    # === Source tracking ===
    source_url: str | None = None
    """URL of the page where this was found"""

    # === Minnesota-specific fields ===
    precedential_status: PrecedentialStatus
    """Whether this opinion is precedential (binding) or nonprecedential"""

    author: str | None = None
    """Author of the opinion (judge/justice name)"""

    lower_court: str | None = None
    """Lower court from which the appeal originated"""

    lower_court_judge: str | None = None
    """Judge in the lower court"""

    disposition: str | None = None
    """Case disposition (e.g., 'Affirmed', 'Reversed', 'Reversed and remanded')"""

    summary: str | None = None
    """Summary/syllabus of the opinion (if available)"""
