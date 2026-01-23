"""Data models for Kansas appellate courts scraper.

These models extend ConsumerModel types from base.py to capture
Kansas Supreme Court and Court of Appeals opinion data.

Mapping to base.py types:
- KansasOpinion -> Opinion (individual opinion document)
- KansasOpinionCluster -> OpinionCluster (group of related opinions)

Supported courts:
- kan: Kansas Supreme Court
- kanctapp: Kansas Court of Appeals
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
    "kan": "Kansas Supreme Court",
    "kanctapp": "Kansas Court of Appeals",
}

# Reverse mapping from site court names to court IDs
COURT_NAME_TO_ID = {
    "Supreme Court": "kan",
    "Court of Appeals": "kanctapp",
}


class KansasOpinion(Opinion):
    """An individual opinion document from Kansas appellate courts.

    Extends Opinion from base.py with required fields for Kansas courts.
    """

    download_url: str
    """URL to the opinion PDF"""

    local_path: str | None = None
    """Local filesystem path where the PDF was downloaded (set by driver)"""


class KansasOpinionCluster(OpinionCluster):
    """A cluster of opinions from Kansas appellate courts.

    This is the main output type yielded by the scraper.
    Each cluster represents a case decision from either the
    Kansas Supreme Court or Court of Appeals.

    Supports both Kansas Supreme Court (kan) and
    Court of Appeals (kanctapp).
    """

    # === Searchable fields ===
    docket_id: Annotated[str, UniqueMatch()]  # type: ignore[assignment]
    """Case number (e.g., '126317' for Supreme Court, '128733' for Court of Appeals)"""

    court_id: Annotated[str, SetFilter()]
    """Court identifier: 'kan' (Supreme Court) or 'kanctapp' (Court of Appeals)"""

    date_filed: Annotated[date, DateRange()]
    """Release date of the opinion"""

    # === Required fields from base ===
    case_name: str
    """Case name (e.g., 'State v. Hardwick')"""

    # === Related data ===
    opinions: list[KansasOpinion] = []
    """All opinions/orders in this cluster"""

    # === Source tracking ===
    source_url: str | None = None
    """URL of the search page where this was found"""

    # === Kansas-specific fields ===
    precedential_status: str = "Unknown"
    """Publication status: 'Published', 'Unpublished', or 'Unknown'"""
