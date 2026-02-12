"""Data models for Arizona appellate courts scraper.

These models extend ConsumerModel types from base.py to capture
Arizona Supreme Court and Court of Appeals opinion data.

Mapping to base.py types:
- ArizOpinion -> Opinion (individual opinion document)
- ArizOpinionCluster -> OpinionCluster (group of related opinions)

Supported courts:
- ariz: Arizona Supreme Court
- arizctapp: Arizona Court of Appeals (Division 1 and Division 2)

Data sources:
- Supreme Court & COA Div 1: https://www.azcourts.gov/opinions
- COA Division 2: https://www.appeals2.az.gov/ODSPlus/recentOpinionsHTML.cfm
"""

from __future__ import annotations

from datetime import date

from kent.common.models.base import (
    Opinion,
    OpinionCluster,
)

# Court ID mapping
COURT_IDS = {
    "ariz": "Arizona Supreme Court",
    "arizctapp": "Arizona Court of Appeals",
}

# Docket prefixes by court
# Note: Court of Appeals uses both 1 CA-XX and 2 CA-XX for Div 1 and Div 2
DOCKET_PREFIX_TO_COURT = {
    "CR-": "ariz",  # Supreme Court Criminal
    "CV-": "ariz",  # Supreme Court Civil
    "1 CA-": "arizctapp",  # Court of Appeals Division 1
    "2 CA-": "arizctapp",  # Court of Appeals Division 2
}

# Court code to court ID mapping for the opinion search
COURT_CODE_TO_COURT_ID = {
    "999": "ariz",  # All courts (but URL shows AZ Supreme Court)
    "998": "arizctapp",  # Court of Appeals Division 1
}


class ArizJudge:
    """A judge involved in an Arizona opinion.

    Attributes:
        name: Judge's name
        involvement: Type of involvement (Author, Concur, Dissent, etc.)
    """

    def __init__(self, name: str, involvement: str):
        self.name = name
        self.involvement = involvement


class ArizOpinion(Opinion):
    """An individual opinion document from Arizona appellate courts.

    Extends Opinion from base.py with required fields for AZ courts.
    """

    download_url: str  # Required - URL to PDF
    """URL to the opinion PDF"""

    type: str  # Required - opinion type
    """Opinion type: 'majority', 'memorandum', 'decision_order', etc."""

    local_path: str | None = None
    """Local filesystem path where the PDF was downloaded (set by driver)"""


class ArizOpinionCluster(OpinionCluster):
    """A cluster of opinions from Arizona appellate courts.

    This is the main output type yielded by the scraper.
    Each cluster represents a case with its opinion(s).

    Supports Arizona Supreme Court (ariz) and
    Arizona Court of Appeals (arizctapp).
    """

    # === Searchable fields ===
    docket_id: str  # type: ignore[assignment]
    """Docket number (e.g., 'CR-24-0064-PR' for Supreme Court, '1 CA-CV 23-0123' for COA)"""

    court_id: str  # Required, searchable
    """Court identifier: 'ariz' (Supreme Court) or 'arizctapp' (Court of Appeals)"""

    date_filed: date  # Required, searchable
    """Filing date of the opinion"""

    # === Required fields from base ===
    case_name: str  # Required
    """Case name (e.g., 'STATE OF ARIZONA v HON.GORDON/OWEN')"""

    # === Related data ===
    opinions: list[ArizOpinion] = []
    """All opinions in this cluster"""

    # === Arizona-specific fields ===
    decision_type: str | None = None
    """Decision type: OPINION, MEMORANDUM, DECISION ORDER"""

    judges: str | None = None
    """Judges involved with their roles (e.g., 'Montgomery, Author; Timmer, Concur')"""

    constitutionality_summary: str | None = None
    """Summary of constitutional analysis (for constitutionality decisions)"""

    # === Source tracking ===
    source_url: str | None = None
    """URL of the page where this was found"""

    publication_year: int | None = None
    """Year of publication"""
