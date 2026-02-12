"""Data models for Oregon appellate courts scraper.

These models extend ConsumerModel types from base.py to capture
Oregon Supreme Court and Court of Appeals opinions from the
State of Oregon Law Library's CONTENTdm digital collection.

Mapping to base.py types:
- OregonOpinion -> Opinion (individual opinion document)
- OregonOpinionCluster -> OpinionCluster (group of related opinions)

Supported courts (from courts.toml):
- or: Oregon Supreme Court
- orctapp: Court of Appeals of Oregon

CONTENTdm Collection IDs:
- p17027coll3: Oregon Supreme Court Opinions
- p17027coll5: Oregon Court of Appeals Opinions
"""

from __future__ import annotations

from datetime import date

from kent.common.models.base import (
    Opinion,
    OpinionCluster,
)

# Collection ID to court ID mapping
COLLECTION_TO_COURT_ID: dict[str, str] = {
    "p17027coll3": "or",  # Oregon Supreme Court
    "p17027coll5": "orctapp",  # Court of Appeals
}

# Court ID to collection ID mapping
COURT_ID_TO_COLLECTION: dict[str, str] = {
    v: k for k, v in COLLECTION_TO_COURT_ID.items()
}

# All supported court IDs
COURT_IDS: set[str] = set(COLLECTION_TO_COURT_ID.values())

# Display names for courts
COURT_NAMES: dict[str, str] = {
    "or": "Oregon Supreme Court",
    "orctapp": "Court of Appeals of Oregon",
}

# Opinion type mapping from CONTENTdm "Type" field
# Supreme Court: opinion, petitions for review, miscellaneous dispositions
# Court of Appeals: opinion, nonprecedential opinion, awop, banc, order
OPINION_TYPE_MAP: dict[str, str] = {
    "opinion": "opinion",
    "nonprecedential opinion": "opinion",  # Nonprecedential memorandum opinion
    "awop": "awop",  # Affirmed Without Opinion
    "banc": "opinion",  # En banc opinion
    "order": "order",
    "petitions for review": "petitions",
    "miscellaneous dispositions": "miscellaneous",
    "miscellaneous dispostions": "miscellaneous",  # Typo in CONTENTdm
}


class OregonOpinion(Opinion):
    """An individual opinion document from Oregon appellate courts.

    Extends Opinion from base.py with required fields for Oregon courts.
    """

    download_url: str
    """URL to the opinion PDF (required)"""

    type: str = "majority"
    """Opinion type: 'majority', 'dissent', 'concurrence', etc."""

    local_path: str | None = None
    """Local filesystem path where the PDF was downloaded (set by driver)"""

    # Oregon-specific fields
    author: str | None = None
    """Name of the opinion author (Justice/Judge or 'Per Curiam')"""


class OregonOpinionCluster(OpinionCluster):
    """A cluster of opinions from Oregon appellate courts.

    This is the main output type yielded by the scraper for opinions.
    Each cluster represents a case with its opinion document(s).

    Supports Oregon Supreme Court (or) and Court of Appeals (orctapp).

    Data source: State of Oregon Law Library CONTENTdm digital collection
    - Supreme Court: https://cdm17027.contentdm.oclc.org/digital/collection/p17027coll3
    - Court of Appeals: https://cdm17027.contentdm.oclc.org/digital/collection/p17027coll5
    """

    # === Searchable fields ===
    case_number: str
    """Case number (e.g., 'S070647' for Supreme Court, 'A181627' for Court of Appeals)"""

    court_id: str
    """Court identifier: 'or' (Supreme Court), 'orctapp' (Court of Appeals)"""

    date_decided: date
    """Date the opinion was decided"""

    # === Required fields ===
    case_name: str
    """Official case name/caption (e.g., 'Crandall v. State of Oregon')"""

    # === Optional fields ===
    citation: str | None = None
    """Official citation (e.g., '374 Or 699' or '346 Or App 499')"""

    author: str | None = None
    """Name of the authoring judge/justice (e.g., 'Flynn')"""

    opinion_type: str | None = None
    """Type of opinion: 'opinion', 'nonprecedential opinion', 'awop', etc."""

    parties: list[str] | None = None
    """List of parties involved in the case"""

    notes: str | None = None
    """Additional notes about the case/decision"""

    additional_case_number: str | None = None
    """Additional case number (e.g., lower court case number)"""

    contentdm_id: int | None = None
    """CONTENTdm record ID for this opinion"""

    collection_id: str | None = None
    """CONTENTdm collection ID (p17027coll3 or p17027coll5)"""

    # === Related data ===
    opinions: list[OregonOpinion] = []
    """All opinions in this cluster (typically just one for Oregon)"""

    # === Source tracking ===
    source_url: str | None = None
    """URL of the CONTENTdm record page"""
