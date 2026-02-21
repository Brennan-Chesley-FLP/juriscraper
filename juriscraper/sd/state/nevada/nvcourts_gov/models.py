"""Data models for Nevada appellate courts scraper.

These models extend base model types from kent to capture
Nevada Supreme Court and Court of Appeals opinion data.

Mapping to base.py types:
- NevadaOpinion -> Opinion (individual opinion document)
- NevadaOpinionCluster -> OpinionCluster (group of related opinions)

Supported courts:
- nev: Nevada Supreme Court
- nevapp: Nevada Court of Appeals
"""

from __future__ import annotations

from datetime import date

from kent.common.models.base import (
    Opinion,
    OpinionCluster,
)

# Court ID mapping to CourtListener IDs
COURT_IDS = {
    "nev": "Nevada Supreme Court",
    "nevapp": "Nevada Court of Appeals",
}

# Base URLs
BASE_URL = "https://nvcourts.gov"
ADVANCE_OPINIONS_URL = f"{BASE_URL}/supreme/decisions/advance_opinions"
UNPUBLISHED_ORDERS_URL = f"{BASE_URL}/supreme/decisions/unpublished_orders"


class NevadaOpinion(Opinion):
    """An individual opinion document from Nevada appellate courts.

    Extends Opinion from base.py with required fields for Nevada courts.
    """

    download_url: str
    """URL to the opinion PDF"""

    type: str = "unknown"
    """Opinion type (e.g., 'advance_opinion', 'unpublished_order')"""

    local_path: str | None = None
    """Local filesystem path where the PDF was downloaded (set by driver)"""

    advance_number: int | None = None
    """Advance opinion number (for published opinions only)"""


class NevadaOpinionCluster(OpinionCluster):
    """A cluster of opinions from Nevada appellate courts.

    This is the main output type yielded by the scraper.
    Each cluster represents a case with one or more opinions/orders.

    Supports both Nevada Supreme Court (nev) and Court of Appeals (nevapp).
    Note: Nevada uses a deflective model where the Supreme Court receives
    all appeals and assigns approximately 1/3 to the Court of Appeals.
    """

    # === Searchable fields ===
    docket_number: str
    """Case number (5-digit number, e.g., '88998')"""

    court_id: str
    """Court identifier: 'nev' (Supreme Court) or 'nevapp' (Court of Appeals)"""

    date_filed: date
    """Publication date of the opinion"""

    # === Required fields from base ===
    case_name: str
    """Case title (e.g., 'AJAY (AJAY) VS. STATE (CRIMINAL)')"""

    # === Related data ===
    opinions: list[NevadaOpinion] = []
    """All opinions/orders in this cluster"""

    # === Source tracking ===
    source_url: str | None = None
    """URL of the page where this was found"""

    # === Nevada-specific fields ===
    advance_number: int | None = None
    """Advance opinion number (for published opinions)"""

    precedential_status: str = "Unknown"
    """Publication status: 'Published', 'Unpublished', or 'Unknown'"""
