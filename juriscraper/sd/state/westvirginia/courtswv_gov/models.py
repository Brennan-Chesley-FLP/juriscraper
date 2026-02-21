"""Data models for West Virginia appellate courts scraper.

These models extend base model types from kent to capture
West Virginia Supreme Court of Appeals (SCA) and Intermediate Court
of Appeals (ICA) opinions.

Mapping to base.py types:
- WVOpinion -> Opinion (individual opinion document)
- WVOpinionCluster -> OpinionCluster (group of related opinions)

Supported courts (from courts.toml):
- wva: West Virginia Supreme Court (Supreme Court of Appeals)
- wvactapp: Intermediate Court of Appeals of West Virginia

The West Virginia opinions use different PDF URL patterns:
- SCA: /sites/default/pubfilesmnt/{YYYY-MM}/{case_no}%20{decision_type}.pdf
- ICA: /sites/default/pubfilesmnt/{YYYY-MM}/{case_no}_{decision_type}.pdf

Case number patterns:
- SCA: {YY}-{number} (e.g., 25-765)
- ICA: {YY}-ICA-{number} (e.g., 25-ICA-304)
"""

from __future__ import annotations

from datetime import date

from kent.common.models.base import (
    Opinion,
    OpinionCluster,
)

# Court ID mapping
# wva = Supreme Court of Appeals (SCA)
# wvactapp = Intermediate Court of Appeals (ICA)
COURT_IDS: set[str] = {"wva", "wvactapp"}

# Display names for courts
COURT_NAMES: dict[str, str] = {
    "wva": "Supreme Court of Appeals of West Virginia",
    "wvactapp": "Intermediate Court of Appeals of West Virginia",
}

# Decision type codes and their full names
DECISION_TYPES: dict[str, str] = {
    "SO": "Signed Opinion",
    "PC": "Per Curiam Opinion",
    "MD": "Memorandum Decision",
    "SEP": "Separate Opinion",
    "Order": "Order",
}

# Case type codes and their full names
CASE_TYPES: dict[str, str] = {
    "ADM": "Administrative Agency-Other",
    "CERQ": "Certified Question",
    "CIV-O": "Civil-Other",
    "CR-F": "Felony (non-Death Penalty)",
    "CR-M": "Misdemeanor",
    "CR-O": "Criminal-Other",
    "FAM": "Family",
    "J-DISC": "Judicial Discipline",
    "JUV": "Juvenile",
    "L-ADM": "Bar Admission",
    "L-DISC": "Bar Discipline",
    "MISC": "Other",
    "OJ-H": "Habeas Corpus",
    "OJ-M": "Mandamus",
    "OJ-O": "Original Jurisdiction-Other",
    "OJ-P": "Prohibition",
    "POST": "Post-Conviction",
    "PR": "Probate",
    "TAX": "Revenue (Tax)",
    "TCR": "Tort, Contract, Real Property",
    "WC": "Worker's Compensation",
}


class WVOpinion(Opinion):
    """An individual opinion document from West Virginia appellate courts.

    Extends Opinion from base.py with required fields for WV courts.
    """

    download_url: str
    """URL to the opinion PDF (required)"""

    type: str = "majority"
    """Opinion type: 'majority', 'dissent', 'concurrence', etc."""

    local_path: str | None = None
    """Local filesystem path where the PDF was downloaded (set by driver)"""


class WVOpinionCluster(OpinionCluster):
    """A cluster of opinions from West Virginia appellate courts.

    This is the main output type yielded by the scraper for opinions.
    Each cluster represents a case that may have multiple opinions
    (majority, dissents, concurrences).

    Supports Supreme Court of Appeals (wva) and Intermediate Court
    of Appeals (wvactapp).
    """

    # === Searchable fields ===
    case_number: str
    """Case number (e.g., '25-765' for SCA, '25-ICA-304' for ICA)"""

    court_id: str
    """Court identifier: 'wva' (SCA) or 'wvactapp' (ICA)"""

    date_filed: date
    """Date the opinion was filed"""

    # === Required fields ===
    case_name: str
    """Case name/caption (e.g., 'Frank Mayer v. City of Clarksburg')"""

    # === Optional fields ===
    case_type: str | None = None
    """Case type code (e.g., 'WC', 'FAM', 'POST')"""

    case_type_name: str | None = None
    """Full case type name (e.g., 'Worker's Compensation')"""

    decision_type: str | None = None
    """Decision type code (e.g., 'MD', 'SO', 'SEP')"""

    decision_type_name: str | None = None
    """Full decision type name (e.g., 'Memorandum Decision')"""

    # === Related data ===
    opinions: list[WVOpinion] = []
    """All opinions in this cluster (majority, dissents, concurrences)"""

    # === Source tracking ===
    source_url: str | None = None
    """URL of the opinions listing page"""
