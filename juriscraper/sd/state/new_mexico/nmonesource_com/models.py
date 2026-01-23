"""Data models for New Mexico appellate courts scraper (NMOneSource).

These models extend ConsumerModel types from base.py to capture
New Mexico Supreme Court and Court of Appeals opinion data.

Mapping to base.py types:
- NMOpinion -> Opinion (individual opinion document)
- NMOpinionCluster -> OpinionCluster (group of related opinions)

Supported courts:
- nm: New Mexico Supreme Court (case prefix: S-1-SC-)
- nmctapp: New Mexico Court of Appeals (case prefix: A-1-CA-)

Data source: https://nmonesource.com/
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

# Court ID mapping to CourtListener IDs (from courts.toml)
COURT_IDS = {
    "nm": "New Mexico Supreme Court",
    "nmctapp": "New Mexico Court of Appeals",
}

# NMOneSource court code to CourtListener ID mapping
NMONESOURCE_COURT_TO_ID = {
    "nmsc": "nm",  # Supreme Court of New Mexico
    "nmca": "nmctapp",  # Court of Appeals of New Mexico
}

# CourtListener ID to NMOneSource court code
ID_TO_NMONESOURCE_COURT = {v: k for k, v in NMONESOURCE_COURT_TO_ID.items()}

# Case number prefixes by court
# Supreme Court: S-1-SC-XXXXX
# Court of Appeals: A-1-CA-XXXXX
CASE_PREFIX_TO_COURT = {
    "S-1-SC": "nm",
    "A-1-CA": "nmctapp",
}


class NMOpinion(Opinion):
    """An individual opinion document from New Mexico appellate courts.

    Extends Opinion from base.py with required fields for New Mexico courts.
    """

    download_url: str
    """URL to the opinion PDF"""

    type: str
    """Opinion type: 'slip' for Slip Opinions, 'unreported' for Unreported Opinions"""

    local_path: str | None = None
    """Local filesystem path where the PDF was downloaded (set by driver)"""


class NMOpinionCluster(OpinionCluster):
    """A cluster of opinions from New Mexico appellate courts.

    This is the main output type yielded by the scraper.
    Each cluster represents a case that may have one opinion document.

    Supports both New Mexico Supreme Court (nm) and
    Court of Appeals (nmctapp).
    """

    # === Searchable fields ===
    docket_id: Annotated[str, UniqueMatch()]  # type: ignore[assignment]
    """Docket number (e.g., 'S-1-SC-40434' for Supreme Court, 'A-1-CA-38594' for Court of Appeals)"""

    court_id: Annotated[str, SetFilter()]
    """Court identifier: 'nm' (Supreme Court) or 'nmctapp' (Court of Appeals)"""

    date_filed: Annotated[date, DateRange()]
    """Publication date of the opinion"""

    # === Required fields from base ===
    case_name: str
    """Case name (e.g., 'Burns v. Presbyterian Healthcare Servs.')"""

    # === Related data ===
    opinions: list[NMOpinion] = []
    """All opinions/orders in this cluster (typically just one)"""

    # === Source tracking ===
    source_url: str | None = None
    """URL of the page where this was found"""

    item_id: str | None = None
    """NMOneSource internal item ID (e.g., '537787')"""

    # === New Mexico-specific fields ===
    judges: str | None = None  # type: ignore[assignment]
    """Decision-makers (judges/justices) who participated in the decision"""

    opinion_type: str | None = None
    """Opinion type as labeled by NMOneSource: 'Slip Opinions' or 'Unreported Opinions'"""

    collection: str | None = None
    """Collection name (e.g., 'Supreme Court of New Mexico')"""
