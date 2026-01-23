"""Data models for Vermont appellate courts scraper.

These models extend ConsumerModel types from base.py to capture
Vermont Supreme Court opinion data.

Mapping to base.py types:
- VermontOpinion -> Opinion (individual opinion document)
- VermontOpinionCluster -> OpinionCluster (group of related opinions)

Supported courts:
- vt: Vermont Supreme Court

Note: Vermont does not have an intermediate appellate court.
All appeals go directly to the Supreme Court.
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
    "vt": "Supreme Court of Vermont",
}


class VermontOpinion(Opinion):
    """An individual opinion document from Vermont Supreme Court.

    Extends Opinion from base.py with required fields for Vermont courts.
    """

    download_url: str
    """URL to the opinion PDF"""

    local_path: str | None = None
    """Local filesystem path where the PDF was downloaded (set by driver)"""


class VermontOpinionCluster(OpinionCluster):
    """A cluster of opinions from Vermont Supreme Court.

    This is the main output type yielded by the scraper.
    Each cluster represents a single opinion (published or unpublished).

    Docket format: YY-AP-NNN (e.g., "25-AP-314")
    """

    # === Searchable fields ===
    docket_id: Annotated[str, UniqueMatch()]  # type: ignore[assignment]
    """Docket number (e.g., '25-AP-314')"""

    court_id: Annotated[str, SetFilter()]
    """Court identifier: 'vt' (Vermont Supreme Court)"""

    date_filed: Annotated[date, DateRange()]
    """Publication date of the opinion"""

    # === Required fields from base ===
    case_name: str
    """Case name (e.g., 'State v. Anna Sylvester')"""

    # === Related data ===
    opinions: list[VermontOpinion] = []
    """All opinions in this cluster (typically just one)"""

    # === Source tracking ===
    source_url: str | None = None
    """URL of the page where this was found"""

    # === Vermont-specific fields ===
    media_id: int
    """The internal media ID from the document URL (e.g., 19786 from /media/19786)"""
