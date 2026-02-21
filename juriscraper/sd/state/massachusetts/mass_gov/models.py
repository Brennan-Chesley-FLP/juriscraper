"""Data models for Massachusetts appellate courts scraper.

These models extend base model types from kent to capture
Massachusetts Supreme Judicial Court and Appeals Court opinion data.

Mapping to base.py types:
- MassOpinion -> Opinion (individual opinion document)
- MassOpinionCluster -> OpinionCluster (group of related opinions)

Supported courts:
- mass: Massachusetts Supreme Judicial Court (SJC)
- massappct: Massachusetts Appeals Court

Data sources:
- Published opinions: https://www.mass.gov/info-details/new-opinions
- Summary dispositions: https://128archive.com/

Docket number formats:
- SJC: SJC-{NNNNN} (e.g., SJC-13767)
- Appeals Court: {YY}-P-{NNNN} (e.g., 24-P-1364)
"""

from __future__ import annotations

from datetime import date

from kent.common.models.base import (
    Opinion,
    OpinionCluster,
)

# Court ID mapping to CourtListener IDs
COURT_IDS = {
    "mass": "Massachusetts Supreme Judicial Court",
    "massappct": "Massachusetts Appeals Court",
}


class MassOpinion(Opinion):
    """An individual opinion document from Massachusetts appellate courts.

    Extends Opinion from base.py with required fields for Massachusetts courts.
    """

    download_url: str
    """URL to the opinion PDF"""

    local_path: str | None = None
    """Local filesystem path where the PDF was downloaded (set by driver)"""


class MassOpinionCluster(OpinionCluster):
    """A cluster of opinions from Massachusetts appellate courts.

    This is the main output type yielded by the scraper.
    Each cluster represents a single published opinion or summary disposition.

    SJC docket format: SJC-{NNNNN} (e.g., "SJC-13767")
    Appeals Court docket format: {YY}-P-{NNNN} (e.g., "24-P-1364")
    """

    # === Searchable fields ===
    docket_id: str  # type: ignore[assignment]
    """Docket number (e.g., 'SJC-13767' or '24-P-1364')"""

    court_id: str
    """Court identifier: 'mass' (SJC) or 'massappct' (Appeals Court)"""

    date_filed: date
    """Publication date of the opinion"""

    # === Required fields from base ===
    case_name: str
    """Case name (e.g., 'Commonwealth v. Lewis')"""

    # === Related data ===
    opinions: list[MassOpinion] = []
    """All opinions in this cluster (typically just one)"""

    # === Source tracking ===
    source_url: str | None = None
    """URL of the page where this was found"""

    # === Massachusetts-specific fields ===
    is_summary_disposition: bool = False
    """True if this is a Rule 23.0 summary disposition (not binding precedent)"""
