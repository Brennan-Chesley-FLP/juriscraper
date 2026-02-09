"""Data models for Nebraska appellate courts scraper.

These models extend ConsumerModel types from base.py to capture
Nebraska Supreme Court and Court of Appeals opinion data.

Mapping to base.py types:
- NebraskaOpinion -> Opinion (individual opinion document)
- NebraskaOpinionCluster -> OpinionCluster (group of related opinions)

Supported courts:
- neb: Nebraska Supreme Court (case prefix: S-)
- nebctapp: Nebraska Court of Appeals (case prefix: A-)
"""

from __future__ import annotations

from datetime import date

from juriscraper.scraper_driver.common.models.base import (
    Opinion,
    OpinionCluster,
)

# Court ID mapping to CourtListener IDs
COURT_IDS = {
    "neb": "Nebraska Supreme Court",
    "nebctapp": "Nebraska Court of Appeals",
}

# Volume prefix to court mapping
# Supreme Court: "Neb." (e.g., "320 Neb.")
# Court of Appeals: "Neb. App." (e.g., "34 Neb. App.")
VOLUME_PREFIX_TO_COURT = {
    "Neb.": "neb",
    "Neb. App.": "nebctapp",
}

COURT_TO_VOLUME_PREFIX = {
    "neb": "Neb.",
    "nebctapp": "Neb. App.",
}

# Case number prefixes by court
# Supreme Court: S-YY-NNN (e.g., S-24-295)
# Court of Appeals: A-YY-NNN (e.g., A-24-927)
CASE_PREFIX_TO_COURT = {
    "S": "neb",
    "A": "nebctapp",
}

COURT_TO_CASE_PREFIX = {
    "neb": "S",
    "nebctapp": "A",
}


class NebraskaOpinion(Opinion):
    """An individual opinion document from Nebraska appellate courts.

    Extends Opinion from base.py with required fields for Nebraska courts.
    """

    download_url: str
    """URL to the opinion PDF"""

    doc_id: str
    """Document ID from the online library (e.g., 'N00012924PUB')"""

    local_path: str | None = None
    """Local filesystem path where the PDF was downloaded (set by driver)"""


class NebraskaOpinionCluster(OpinionCluster):
    """A cluster of opinions from Nebraska appellate courts.

    This is the main output type yielded by the scraper.
    Each cluster represents a single opinion from the Nebraska
    Appellate Courts Online Library.

    Supports both Nebraska Supreme Court (neb) and
    Court of Appeals (nebctapp).
    """

    # === Searchable fields ===
    docket_id: str  # type: ignore[assignment]
    """Case number (e.g., 'S-24-295' for Supreme Court, 'A-24-927' for Appeals)"""

    court_id: str
    """Court identifier: 'neb' (Supreme Court) or 'nebctapp' (Court of Appeals)"""

    date_filed: date
    """Publication date of the opinion"""

    # === Required fields from base ===
    case_name: str
    """Case name (e.g., 'State v. Cartwright')"""

    # === Citation info ===
    citation: str
    """Official citation (e.g., '320 Neb. 619')"""

    volume_number: int
    """Volume number from citation (e.g., 320)"""

    page_number: int
    """Starting page number from citation (e.g., 619)"""

    # === Related data ===
    opinions: list[NebraskaOpinion] = []
    """All opinions in this cluster (typically just one)"""

    # === Source tracking ===
    source_url: str | None = None
    """URL of the volume list page where this was found"""

    # === Nebraska-specific fields ===
    status: str = "Advance"
    """Publication status: 'Advance' for recent, 'Published' for finalized"""

    volume_doc_id: str | None = None
    """Document ID for the volume (e.g., 'N00012940PUB')"""
