"""Data models for North Carolina appellate courts scraper.

These models extend base model types from kent to capture
North Carolina Supreme Court and Court of Appeals opinion data.

Mapping to base.py types:
- NCOpinion -> Opinion (individual opinion document)
- NCOpinionCluster -> OpinionCluster (group of related opinions for a case on a given date)

Supported courts:
- nc: North Carolina Supreme Court (docket format: NNP[A]YY)
- ncctapp: North Carolina Court of Appeals (docket format: COA[YY]-NNNN)
"""

from __future__ import annotations

from datetime import date

from kent.common.models.base import (
    Opinion,
    OpinionCluster,
)

# Court ID mapping to CourtListener IDs
COURT_IDS = {
    "nc": "North Carolina Supreme Court",
    "ncctapp": "North Carolina Court of Appeals",
}

# URL court parameter values
# ?c=sc or c=1 for Supreme Court
# ?c=coa or c=2 for Court of Appeals
URL_COURT_PARAMS = {
    "nc": {"c": "sc", "c_num": "1"},
    "ncctapp": {"c": "coa", "c_num": "2"},
}

# Case number patterns by court
# Supreme Court: NNP[A]YY (e.g., 123P24, 123PA24)
# Court of Appeals: COAYY-NNNN (e.g., COA25-263, COA24-443)
COURT_TO_CASE_PREFIX = {
    "nc": ["P", "PA"],  # Petition patterns
    "ncctapp": ["COA"],
}


class NCOpinion(Opinion):
    """An individual opinion document from North Carolina appellate courts.

    Extends Opinion from base.py with required fields for NC courts.
    """

    download_url: str
    """URL to the opinion PDF (e.g., https://appellate.nccourts.org/opinions/?c=2&pdf=44963)"""

    type: str = "010combined"
    """Opinion type - NC doesn't distinguish types in the listing, default to combined"""

    local_path: str | None = None
    """Local filesystem path where the PDF was downloaded (set by driver)"""


class NCOpinionCluster(OpinionCluster):
    """A cluster of opinions from North Carolina appellate courts.

    This is the main output type yielded by the scraper.
    Each cluster represents a case decision filed on a specific date.
    The slip opinions page groups opinions by filing date.

    Supports both North Carolina Supreme Court (nc) and
    Court of Appeals (ncctapp).
    """

    # === Searchable fields ===
    docket_id: str  # type: ignore[assignment]
    """Case number (e.g., 'COA25-263' for COA, '123P24' for Supreme)"""

    court_id: str
    """Court identifier: 'nc' (Supreme Court) or 'ncctapp' (Court of Appeals)"""

    date_filed: date
    """Filing date of the opinion"""

    # === Required fields from base ===
    case_name: str
    """Case name (e.g., 'Eagles v. Integon Indem. Corp.')"""

    # === Related data ===
    opinions: list[NCOpinion] = []
    """All opinions/documents in this cluster (typically just one)"""

    # === Source tracking ===
    source_url: str | None = None
    """URL of the slip opinions page where this was found"""

    # === NC-specific fields ===
    author_str: str | None = None
    """Author of the opinion (e.g., 'Judge Valerie Zachary', 'Per Curiam')"""

    headnotes: str | None = None
    """Subject headnotes/topics (e.g., 'receivership; venue; standing')"""

    precedential_status: str = "Unknown"
    """Publication status: 'Published' or 'Unpublished' (NC uses Rule 30e for unpublished)"""

    mandate_date: date | None = None
    """Date the mandate will/did issue"""
