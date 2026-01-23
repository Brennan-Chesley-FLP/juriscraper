"""Data models for Hawaii appellate courts scraper.

These models extend ConsumerModel types from base.py to capture
Hawaii Supreme Court and Intermediate Court of Appeals opinion data.

Mapping to base.py types:
- HawaiiOpinion -> Opinion (individual opinion document)
- HawaiiOpinionCluster -> OpinionCluster (group of related opinions)

Supported courts:
- haw: Hawaii Supreme Court (case prefixes: SCWC-, SCPW-)
- hawapp: Hawaii Intermediate Court of Appeals (case prefix: CAAP-)
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
    "haw": "Hawaii Supreme Court",
    "hawapp": "Hawaii Intermediate Court of Appeals",
}

# Case number prefixes by court
# Supreme Court: SCWC- (writs of certiorari), SCPW- (original proceedings)
# ICA: CAAP- (appeals)
CASE_PREFIX_TO_COURT = {
    "SCWC": "haw",
    "SCPW": "haw",
    "CAAP": "hawapp",
}

COURT_TO_CASE_PREFIX = {
    "haw": ["SCWC", "SCPW"],
    "hawapp": ["CAAP"],
}


class HawaiiOpinion(Opinion):
    """An individual opinion document from Hawaii appellate courts.

    Extends Opinion from base.py with required fields for Hawaii courts.
    """

    download_url: str
    """URL to the opinion PDF"""

    type: str
    """Opinion type based on suffix: 'sdo', 'mop', 'ord', 'certrej', etc."""

    local_path: str | None = None
    """Local filesystem path where the PDF was downloaded (set by driver)"""


class HawaiiOpinionCluster(OpinionCluster):
    """A cluster of opinions from Hawaii appellate courts.

    This is the main output type yielded by the scraper.
    Each cluster represents a case that may have multiple related documents
    (e.g., SDO, reconsideration order, certiorari rejection).

    Supports both Hawaii Supreme Court (haw) and
    Intermediate Court of Appeals (hawapp).
    """

    # === Searchable fields ===
    docket_id: Annotated[str, UniqueMatch()]  # type: ignore[assignment]
    """Case number (e.g., 'CAAP-23-0000347' for ICA, 'SCWC-24-0000450' for Supreme)"""

    court_id: Annotated[str, SetFilter()]
    """Court identifier: 'haw' (Supreme Court) or 'hawapp' (ICA)"""

    date_filed: Annotated[date, DateRange()]
    """Publication date of the opinion"""

    # === Required fields from base ===
    case_name: str
    """Case name (e.g., 'Fung v. Hoi')"""

    # === Related data ===
    opinions: list[HawaiiOpinion] = []
    """All opinions/orders in this cluster"""

    # === Source tracking ===
    source_url: str | None = None
    """URL of the page where this was found (RSS feed or opinions page)"""

    # === Hawaii-specific fields ===
    appealed_from: str | None = None
    """Lower court from which the case was appealed (e.g., 'Circuit Court, 1st Circuit')"""

    issued_by: str | None = None
    """Number of judges who issued the opinion (e.g., '3' for panel of 3)"""

    related_case_urls: list[str] = []
    """URLs to related documents (e.g., prior ICA SDO for a cert rejection)"""
