"""Data models for Indiana appellate courts scraper.

These models extend ConsumerModel types from base.py to capture
Indiana appellate court opinion data from the decisions portal.

Mapping to base.py types:
- IndianaOpinion -> Opinion (individual opinion document)
- IndianaOpinionCluster -> OpinionCluster (group of related opinions)

Supported courts:
- ind: Indiana Supreme Court (courtId: 9510)
- indctapp: Indiana Court of Appeals (courtId: 9530)
- indtc: Indiana Tax Court (courtId: 9550)
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

# Court ID mapping: CourtListener ID -> API Court ID
COURT_ID_MAP: dict[str, int] = {
    "ind": 9510,  # Indiana Supreme Court
    "indctapp": 9530,  # Indiana Court of Appeals
    "indtc": 9550,  # Indiana Tax Court
}

# Reverse mapping: API Court ID -> CourtListener ID
API_COURT_ID_TO_CL: dict[int, str] = {v: k for k, v in COURT_ID_MAP.items()}

# API Court ID to court display name
COURT_DISPLAY_NAMES: dict[int, str] = {
    9510: "Supreme Court",
    9530: "Court of Appeals",
    9550: "Tax Court",
}

# CourtListener ID to full court name
COURT_FULL_NAMES: dict[str, str] = {
    "ind": "Indiana Supreme Court",
    "indctapp": "Indiana Court of Appeals",
    "indtc": "Indiana Tax Court",
}


class IndianaOpinion(Opinion):
    """An individual opinion document from Indiana appellate courts.

    Extends Opinion from base.py with required fields for Indiana courts.
    """

    download_url: str
    """URL to the opinion PDF"""

    type: str = "010combined"
    """Opinion type - defaults to combined since Indiana doesn't distinguish"""

    local_path: str | None = None
    """Local filesystem path where the PDF was downloaded (set by driver)"""


class IndianaOpinionCluster(OpinionCluster):
    """A cluster of opinions from Indiana appellate courts.

    This is the main output type yielded by the scraper.
    Each cluster represents a case decision.

    Supports Indiana Supreme Court (ind), Court of Appeals (indctapp),
    and Tax Court (indtc).
    """

    # === Searchable fields ===
    docket_id: Annotated[str, UniqueMatch()]  # type: ignore[assignment]
    """Appellate case number (e.g., '25A-CR-00675' for Appeals, '25S-CR-00303' for Supreme)"""

    court_id: Annotated[str, SetFilter()]
    """Court identifier: 'ind' (Supreme), 'indctapp' (Appeals), or 'indtc' (Tax)"""

    date_filed: Annotated[date, DateRange()]
    """Publication date of the opinion"""

    # === Required fields from base ===
    case_name: str
    """Case name/style (e.g., 'Devon Makel Jones v. State of Indiana')"""

    # === Related data ===
    opinions: list[IndianaOpinion] = []
    """All opinions in this cluster (typically just one PDF)"""

    # === Source tracking ===
    source_url: str | None = None
    """URL of the API endpoint where this was retrieved"""

    # === Indiana-specific fields ===
    trial_court_case_number: str | None = None
    """Trial court case number (e.g., '48C04-2312-F1-003574')"""

    trial_court_name: str | None = None
    """Name of the trial court (e.g., 'Madison Circuit Court 4')"""

    case_category: str | None = None
    """Case category: Criminal, Civil, Juvenile, Tax, etc."""

    disposition: str | None = None
    """Case disposition (e.g., 'Affirmed', 'Reversed', 'Remanded')"""

    authoring_judge: str | None = None
    """Name of the judge who authored the opinion"""

    concurring_judges: list[str] = []
    """List of judges who concur"""

    dissenting_judges: list[str] = []
    """List of judges who dissent"""

    is_memorandum: bool = False
    """Whether this is a memorandum decision (non-precedential)"""

    county: str | None = None
    """County of origin for the case"""
