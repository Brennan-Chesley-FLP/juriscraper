"""Data models for Mississippi appellate courts scraper.

These models extend ConsumerModel types from base.py to capture
Mississippi appellate court opinion data.

Mapping to base.py types:
- MississippiOpinion -> Opinion (individual opinion document)
- MississippiOpinionCluster -> OpinionCluster (group of related opinions)

Supported courts:
- miss: Mississippi Supreme Court
- missctapp: Mississippi Court of Appeals

Case number format: {YYYY}-{TYPE}-{NUMBER}-{COURT}
Example: 2024-KA-01001-SCT (Criminal appeal to Supreme Court)

Case type codes:
- CA: Civil Appeal
- KA: Criminal Appeal (Felony)
- SA: Supreme Court Assignment / Special Assignment
- CT: Certiorari
- FC: Federal Court (Certified Question)
- WC: Workers' Compensation

Court suffixes:
- SCT: Supreme Court
- COA: Court of Appeals
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
    "miss": "Mississippi Supreme Court",
    "missctapp": "Court of Appeals of Mississippi",
}

# Map court suffix in case number to court_id
COURT_SUFFIX_MAP = {
    "SCT": "miss",
    "COA": "missctapp",
}


class MississippiOpinion(Opinion):
    """An individual opinion document from Mississippi appellate courts.

    Extends Opinion from base.py with required fields for Mississippi courts.
    """

    download_url: str
    """URL to the opinion PDF"""

    local_path: str | None = None
    """Local filesystem path where the PDF was downloaded (set by driver)"""

    opinion_id: str | None = None
    """Internal opinion ID (e.g., 'CO189869')"""


class MississippiOpinionCluster(OpinionCluster):
    """A cluster of opinions from Mississippi appellate courts.

    This is the main output type yielded by the scraper.
    Each cluster represents a single hand down list entry.

    Case number format: {YYYY}-{TYPE}-{NUMBER}-{COURT}
    Example: 2024-KA-01001-SCT
    """

    # === Searchable fields ===
    docket_number: Annotated[str, UniqueMatch()]  # type: ignore[assignment]
    """Case number (e.g., '2024-KA-01001-SCT')"""

    court_id: Annotated[str, SetFilter()]
    """Court identifier: 'miss' (Supreme Court) or 'missctapp' (Court of Appeals)"""

    date_filed: Annotated[date, DateRange()]
    """Hand down date of the opinion"""

    # === Required fields from base ===
    case_name: str
    """Case name (e.g., 'Tavion Pegues v. State of Mississippi')"""

    # === Related data ===
    opinions: list[MississippiOpinion] = []
    """All opinions in this cluster"""

    # === Source tracking ===
    source_url: str | None = None
    """URL of the hand down list page where this was found"""

    # === Mississippi-specific fields ===
    author: str | None = None
    """Opinion author (e.g., 'Coleman, Josiah Dennis, P.J.')"""

    lower_court: str | None = None
    """Lower court name (e.g., 'Oktibbeha Circuit Court')"""

    lower_court_case_number: str | None = None
    """Lower court case number (e.g., '53CI1:23-cr-00051-K-1')"""

    lower_court_ruling_date: date | None = None
    """Date of ruling from lower court"""

    lower_court_judge: str | None = None
    """Judge from lower court"""

    disposition: str | None = None  # type: ignore[assignment]
    """Disposition (e.g., 'Affirmed', 'Reversed')"""

    votes: str | None = None
    """Vote breakdown (e.g., 'Randolph, C.J., King, P.J., ... Concur.')"""

    is_en_banc: bool = False
    """Whether this was an en banc decision"""

    is_published: bool = True
    """Whether the opinion is published (marked with X on hand down list)"""
