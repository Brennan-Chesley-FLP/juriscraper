"""Data models for Montana appellate courts scraper.

These models extend ConsumerModel types from base.py to capture
Montana Supreme Court opinion and order data.

Mapping to base.py types:
- MontanaOpinion -> Opinion (individual opinion document)
- MontanaOpinionCluster -> OpinionCluster (group of related opinions/orders)

Supported courts:
- mont: Montana Supreme Court

Note: Montana does not have an intermediate appellate court.
All appeals go directly to the Supreme Court.

Case number format: {PREFIX} {YY}-{NNNN}
  - DA: Direct Appeal
  - OP: Original Proceeding
  - PR: Professional Responsibility/Attorney Discipline
  - AF: Administrative Filing
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
    "mont": "Montana Supreme Court",
}


class MontanaOpinion(Opinion):
    """An individual opinion or order document from Montana Supreme Court.

    Extends Opinion from base.py with required fields for Montana courts.
    """

    download_url: str
    """URL to the document PDF"""

    local_path: str | None = None
    """Local filesystem path where the PDF was downloaded (set by driver)"""

    doc_id: str | None = None
    """Document ID from juddocumentservice.mt.gov"""


class MontanaOpinionCluster(OpinionCluster):
    """A cluster of opinions/orders from Montana Supreme Court.

    This is the main output type yielded by the scraper.
    Each cluster represents a single case's order or opinion from the daily
    orders page.
    """

    # === Searchable fields ===
    docket_id: Annotated[str, UniqueMatch()]  # type: ignore[assignment]
    """Case number (e.g., 'DA 25-0142')"""

    court_id: Annotated[str, SetFilter()]
    """Court identifier: 'mont' (Montana Supreme Court)"""

    date_filed: Annotated[date, DateRange()]
    """Filing date of the order/opinion"""

    # === Required fields from base ===
    case_name: str
    """Case name/title (e.g., 'State of Montana v. John Doe')"""

    # === Related data ===
    opinions: list[MontanaOpinion] = []
    """All opinions/orders in this cluster"""

    # === Source tracking ===
    source_url: str | None = None
    """URL of the page where this was found"""

    case_info_url: str | None = None
    """URL to the case information page"""

    # === Montana-specific fields ===
    document_description: str | None = None
    """Description of the document from the daily orders table"""

    case_type: str | None = None
    """Type of case (Direct Appeal, Original Proceeding, etc.)"""
