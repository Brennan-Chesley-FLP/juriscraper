"""Data models for Virginia appellate courts scraper.

These models extend base model types from kent to capture
Supreme Court of Virginia and Court of Appeals of Virginia opinions.

Mapping to base.py types:
- VaOpinion -> Opinion (individual opinion document)
- VaOpinionCluster -> OpinionCluster (group of related opinions)

Supported courts (from courts.toml):
- va: Supreme Court of Virginia
- vactapp: Court of Appeals of Virginia

Opinion types:
- Supreme Court: Published opinions and orders (since June 9, 1995)
- Court of Appeals: Published opinions (since May 2, 1995)
- Court of Appeals: Unpublished opinions (since March 5, 2002)

URL patterns::

  - Supreme Court opinions: https://www.vacourts.gov/scndex
    (redirects to https://webdev.vacourts.gov/dynamic/scndex.htm)
  - Court of Appeals published: https://www.vacourts.gov/wpcap
    (redirects to https://webdev.vacourts.gov/dynamic/wpcap.htm)
  - Court of Appeals unpublished: https://www.vacourts.gov/wpcau
    (redirects to https://webdev.vacourts.gov/dynamic/wpcau.htm)

PDF URL patterns::

  - Supreme Court: https://www.vacourts.gov/opinions/opnscvwp/1{case_number}.pdf
    (6-digit case number prefixed with 1, e.g., 1240736.pdf for case 240736)
  - Court of Appeals: https://www.vacourts.gov/opinions/opncavwp/{case_number}.pdf
    (7-digit case number, e.g., 0350251.pdf)
"""

from __future__ import annotations

from datetime import date

from kent.common.models.base import (
    Opinion,
    OpinionCluster,
)

# Court IDs from courts.toml
COURT_IDS: set[str] = {"va", "vactapp"}

# Display names for courts
COURT_NAMES: dict[str, str] = {
    "va": "Supreme Court of Virginia",
    "vactapp": "Court of Appeals of Virginia",
}

# Opinion page URLs
OPINION_URLS: dict[str, str] = {
    "va": "https://www.vacourts.gov/scndex",
    "vactapp_published": "https://www.vacourts.gov/wpcap",
    "vactapp_unpublished": "https://www.vacourts.gov/wpcau",
}


class VaOpinion(Opinion):
    """An individual opinion document from Virginia appellate courts.

    Extends Opinion from base.py with required fields for Virginia courts.
    """

    download_url: str
    """URL to the opinion PDF (required)"""

    type: str = "majority"
    """Opinion type: 'majority', 'dissent', 'concurrence', etc."""

    local_path: str | None = None
    """Local filesystem path where the PDF was downloaded (set by driver)"""


class VaOpinionCluster(OpinionCluster):
    """A cluster of opinions from Virginia appellate courts.

    This is the main output type yielded by the scraper for opinions.
    Each cluster represents a case with one or more opinion documents.

    Supports Supreme Court of Virginia (va) and Court of Appeals of Virginia (vactapp).
    """

    # === Searchable fields ===
    docket_number: str
    """Case/record number (e.g., '240736' for Supreme Court, '0350251' for Court of Appeals)"""

    court_id: str
    """Court identifier: 'va' or 'vactapp'"""

    date_filed: date | None = None
    """Date the opinion was filed/decided"""

    # === Required fields ===
    case_name: str
    """Case name/style (e.g., 'Appian Corporation v. Pegasystems')"""

    # === Optional fields ===
    precedential_status: str | None = None
    """'published' or 'unpublished' - only applicable for Court of Appeals"""

    summary: str | None = None
    """Brief summary/disposition of the opinion"""

    # === Related data ===
    opinions: list[VaOpinion] = []
    """All opinions in this cluster"""

    # === Source tracking ===
    source_url: str | None = None
    """URL of the opinions listing page"""
