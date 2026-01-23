"""Data models for Idaho appellate courts scraper.

These models extend ConsumerModel types from base.py to capture
Idaho Supreme Court and Court of Appeals opinion data.

Mapping to base.py types:
- IdahoOpinion -> Opinion (individual opinion document)
- IdahoOpinionCluster -> OpinionCluster (group of related opinions)

Supported courts:
- idaho: Idaho Supreme Court
- idahoctapp: Idaho Court of Appeals

Opinion categories scraped:
- Supreme Court Civil Opinions (/appeals-court/isc_civil)
- Supreme Court Criminal Opinions (/appeals-court/isc_criminal)
- Court of Appeals Civil Opinions (/appeals-court/coa_civil)
- Court of Appeals Criminal & PC Opinions (/appeals-court/coa_criminal)
- Court of Appeals Unpublished Opinions (/appeals-court/coaunpublished)
- Court of Appeals Unpublished Per Curiam Opinions (/appeals-court/Unpublished-Per-Curiam)
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
    "idaho": "Idaho Supreme Court",
    "idahoctapp": "Idaho Court of Appeals",
}

# Opinion page categories
# Each tuple: (url_path, court_id, case_type, is_published)
OPINION_PAGES = [
    ("isc_civil", "idaho", "civil", True),
    ("isc_criminal", "idaho", "criminal", True),
    ("coa_civil", "idahoctapp", "civil", True),
    ("coa_criminal", "idahoctapp", "criminal", True),
    ("coaunpublished", "idahoctapp", "unpublished", False),
    ("Unpublished-Per-Curiam", "idahoctapp", "per_curiam", False),
]

# Map opinion page category to court_id
PAGE_TO_COURT: dict[str, str] = {
    "isc_civil": "idaho",
    "isc_criminal": "idaho",
    "coa_civil": "idahoctapp",
    "coa_criminal": "idahoctapp",
    "coaunpublished": "idahoctapp",
    "Unpublished-Per-Curiam": "idahoctapp",
}


class IdahoOpinion(Opinion):
    """An individual opinion document from Idaho appellate courts.

    Extends Opinion from base.py with required fields for Idaho courts.
    """

    download_url: str
    """URL to the opinion PDF (e.g., https://isc.idaho.gov/opinions/52012.pdf)"""

    local_path: str | None = None
    """Local filesystem path where the PDF was downloaded (set by driver)"""

    has_summary: bool = False
    """Whether a summary PDF exists for this opinion"""

    summary_url: str | None = None
    """URL to the summary PDF if available (e.g., https://isc.idaho.gov/opinions/52012summ.pdf)"""


class IdahoOpinionCluster(OpinionCluster):
    """A cluster of opinions from Idaho appellate courts.

    This is the main output type yielded by the scraper.
    Each cluster represents a case with its opinion PDF and optional summary.

    Supports both Idaho Supreme Court (idaho) and
    Court of Appeals (idahoctapp).
    """

    # === Searchable fields ===
    docket_id: Annotated[str, UniqueMatch()]  # type: ignore[assignment]
    """Docket number (e.g., '52012', '51532')"""

    court_id: Annotated[str, SetFilter()]
    """Court identifier: 'idaho' (Supreme Court) or 'idahoctapp' (Court of Appeals)"""

    date_filed: Annotated[date, DateRange()]
    """Release/publication date of the opinion"""

    # === Required fields from base ===
    case_name: str
    """Case name (e.g., 'Medical Recovery Services, LLC v. Wood')"""

    # === Related data ===
    opinions: list[IdahoOpinion] = []
    """All opinions in this cluster (typically just one)"""

    # === Source tracking ===
    source_url: str | None = None
    """URL of the page where this was found (opinion listing page)"""

    # === Idaho-specific fields ===
    case_type: str | None = None
    """Type of case: 'civil', 'criminal', 'unpublished', 'per_curiam'"""

    notes: str | None = None
    """Subject matter notes from the opinion listing (e.g., 'Standing; Local Land Use Planning Act')"""

    precedential_status: str = "Published"
    """Publication status: 'Published' or 'Unpublished'"""
