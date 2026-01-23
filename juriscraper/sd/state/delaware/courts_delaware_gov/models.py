"""Data models for Delaware courts scraper.

These models extend ConsumerModel types from base.py to capture
Delaware court opinion data.

Mapping to base.py types:
- DelOpinion -> Opinion (individual opinion document)
- DelOpinionCluster -> OpinionCluster (group of related opinions)

Supported courts:
- del: Delaware Supreme Court
- delch: Delaware Court of Chancery
- delsuperct: Superior Court of Delaware
- delctcompl: Delaware Court of Common Pleas
- delfamct: Delaware Family Court
- deljustpct: Delaware Justice of the Peace Courts
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

# Court ID mapping from site court names to CourtListener IDs
COURT_ID_MAP: dict[str, str] = {
    "Supreme Court": "del",
    "Supreme Court (Court of Chancery)": "del",
    "Supreme Court (Superior Court)": "del",
    "Supreme Court (Family Court)": "del",
    "Supreme Court (Court of Common Pleas)": "del",
    "Supreme Court (Justice Of The Peace Court)": "del",
    "Court of Chancery": "delch",
    "Superior Court": "delsuperct",
    "Court of Common Pleas": "delctcompl",
    "Family Court": "delfamct",
    "Justice Of The Peace Court": "deljustpct",
}

# Reverse mapping for display
COURT_NAMES: dict[str, str] = {
    "del": "Delaware Supreme Court",
    "delch": "Delaware Court of Chancery",
    "delsuperct": "Superior Court of Delaware",
    "delctcompl": "Delaware Court of Common Pleas",
    "delfamct": "Delaware Family Court",
    "deljustpct": "Delaware Justice of the Peace Courts",
}

# Court URL filter values (as used in the dropdown)
COURT_URL_FILTER_MAP: dict[str, str] = {
    "del": "Supreme Court",
    "delch": "Court of Chancery",
    "delsuperct": "Superior Court",
    "delctcompl": "Court of Common Pleas",
    "delfamct": "Family Court",
    "deljustpct": "Justice Of The Peace Court",
}


def get_court_id(site_court_name: str) -> str | None:
    """Map site court name to CourtListener court_id.

    Args:
        site_court_name: Court name as it appears on the Delaware courts site

    Returns:
        CourtListener court ID or None if not found
    """
    return COURT_ID_MAP.get(site_court_name)


class DelOpinion(Opinion):
    """An individual opinion document from Delaware courts.

    Extends Opinion from base.py with required fields for DE courts.
    """

    download_url: str
    """URL to the opinion PDF (e.g., /Opinions/Download.aspx?id=390230)"""

    opinion_id: int
    """Internal opinion ID from Delaware courts system"""

    local_path: str | None = None
    """Local filesystem path where the PDF was downloaded (set by driver)"""


class DelOpinionCluster(OpinionCluster):
    """A cluster of opinions from Delaware courts.

    This is the main output type yielded by the scraper.
    Delaware typically has one opinion per cluster, but we use the
    cluster model for consistency with other scrapers.
    """

    # === Searchable fields ===
    docket_number: Annotated[str, UniqueMatch()]
    """Docket/file number (e.g., 'C.A. No. 2024-1022-BWD', '340, 2024')"""

    court_id: Annotated[str, SetFilter()]
    """Court identifier from CourtListener (e.g., 'del', 'delch', 'delsuperct')"""

    date_filed: Annotated[date, DateRange()]
    """Date the opinion was filed/published"""

    # === Required fields from base ===
    case_name: str
    """Case caption (e.g., 'Moelis & Company v. West Palm Beach Firefighters')"""

    # === Related data ===
    opinions: list[DelOpinion] = []
    """All opinions in this cluster (typically just one for Delaware)"""

    # === Delaware-specific fields ===
    case_type: str | None = None
    """Case type: 'Civil' or 'Criminal'"""

    judicial_officer: str | None = None
    """Name of the judicial officer (e.g., 'Traynor J.', 'McCormick, C.')"""

    description: str | None = None
    """Opinion description/type (e.g., 'Opinion', 'Memorandum Opinion', 'Order')"""

    originating_court: str | None = None
    """For Supreme Court appeals, the lower court (e.g., 'Court of Chancery')"""

    # === Source tracking ===
    source_url: str | None = None
    """URL of the opinions page where this was found"""
