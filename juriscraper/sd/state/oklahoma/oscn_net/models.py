"""Data models for Oklahoma appellate courts scraper.

These models extend ConsumerModel types from base.py to capture
opinions from Oklahoma appellate courts via OSCN (Oklahoma State Courts Network).

Supported courts (from courts.toml):
- okla: Supreme Court of Oklahoma
- oklacrimapp: Court of Criminal Appeals of Oklahoma
- oklacivapp: Court of Civil Appeals of Oklahoma

The OSCN system uses different database codes (ftdb):
- STOKCSSC: Oklahoma Supreme Court Cases
- STOKCSCR: Oklahoma Court of Criminal Appeals Cases
- STOKCSCV: Oklahoma Court of Civil Appeals Cases

Citation formats:
- Supreme Court: YYYY OK N (e.g., 2026 OK 1)
- Criminal Appeals: YYYY OK CR N (e.g., 2026 OK CR 1)
- Civil Appeals: YYYY OK CIV APP N (e.g., 2026 OK CIV APP 1)
"""

from __future__ import annotations

from datetime import date

from juriscraper.scraper_driver.common.models.base import (
    Opinion,
    OpinionCluster,
)

# Database code to court_id mapping
FTDB_TO_COURT_ID: dict[str, str] = {
    "STOKCSSC": "okla",  # Supreme Court of Oklahoma
    "STOKCSCR": "oklacrimapp",  # Court of Criminal Appeals
    "STOKCSCV": "oklacivapp",  # Court of Civil Appeals
}

# Reverse mapping
COURT_ID_TO_FTDB: dict[str, str] = {v: k for k, v in FTDB_TO_COURT_ID.items()}

# All supported court IDs
COURT_IDS: set[str] = set(FTDB_TO_COURT_ID.values())

# Court display names
COURT_NAMES: dict[str, str] = {
    "okla": "Supreme Court of Oklahoma",
    "oklacrimapp": "Court of Criminal Appeals of Oklahoma",
    "oklacivapp": "Court of Civil Appeals of Oklahoma",
}


class OklahomaOpinion(Opinion):
    """An individual opinion document from Oklahoma appellate courts.

    Extends Opinion from base.py with fields for Oklahoma courts.
    The OSCN system provides opinions as HTML pages, not PDFs.
    """

    download_url: str
    """URL to the opinion page (DeliverDocument.asp?CiteID=...)"""

    type: str = "majority"
    """Opinion type: 'majority', 'dissent', 'concurrence', etc."""

    local_path: str | None = None
    """Local filesystem path where the HTML was saved (set by driver)"""

    # Oklahoma-specific fields
    author: str | None = None
    """Name of the opinion author (Justice/Judge)"""


class OklahomaOpinionCluster(OpinionCluster):
    """A cluster of opinions from Oklahoma appellate courts.

    This is the main output type yielded by the scraper for opinions.
    Each cluster represents a case with its official Oklahoma citation.

    Supports:
    - Supreme Court of Oklahoma (okla)
    - Court of Criminal Appeals of Oklahoma (oklacrimapp)
    - Court of Civil Appeals of Oklahoma (oklacivapp)
    """

    # === Searchable fields ===
    cite_id: str
    """OSCN CiteID - unique identifier for the opinion"""

    court_id: str
    """Court identifier: 'okla', 'oklacrimapp', 'oklacivapp'"""

    date_filed: date | None = None
    """Date the opinion was filed/decided"""

    # === Required fields ===
    case_name: str
    """Case name/caption (e.g., 'TOBACCO SETTLEMENT ENDOWMENT TRUST FUND v. STITT')"""

    citation: str
    """Official Oklahoma citation (e.g., '2026 OK 1', '2026 OK CR 1')"""

    # === Optional fields ===
    docket_number: str | None = None
    """Docket/case number"""

    # === Related data ===
    opinions: list[OklahomaOpinion] = []
    """All opinions in this cluster (majority, dissents, concurrences)"""

    # === Source tracking ===
    source_url: str | None = None
    """URL of the opinions listing page"""
