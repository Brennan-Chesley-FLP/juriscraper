"""Data models for North Dakota Supreme Court scraper.

These models extend the common TR Portal base models for the North
Dakota Appellate Case System served by Thomson Reuters Case
Management Systems at portal.ctrack.ndcourts.gov.

Supported courts:
- nd: North Dakota Supreme Court
"""

from __future__ import annotations

from juriscraper.state.common.tr.models import (
    TRCourtConfig,
    TRDocket,
    TRDocketEntry,
    TRDocument,
    TROralArgument,
)

COURT_CONFIG: dict[str, TRCourtConfig] = {
    "nd": {
        "name": "North Dakota Supreme Court",
        "court_guid": "68f021c4-6a44-4735-9a76-5360b2e8af13",
        "numeric_id": "1",
        "abbreviation": "North Dakota Supreme Court",
    },
}

API_BASE_URL = "https://portal-api.ctrack.ndcourts.gov"
PORTAL_URL = "https://portal.ctrack.ndcourts.gov"


class NdDocketEntry(TRDocketEntry):
    """A docket entry from the North Dakota Supreme Court."""


class NdDocket(TRDocket):
    """A docket from the North Dakota Supreme Court.

    Represents a complete case with all its metadata from the
    North Dakota Appellate Case System at portal.ctrack.ndcourts.gov.
    """

    entries: list[NdDocketEntry] = []
    """All docket entries"""


class NdOralArgument(TROralArgument):
    """An oral argument from the North Dakota Supreme Court."""


class NdDocument(TRDocument):
    """A document attached to a North Dakota Supreme Court docket entry."""

    court: str = "nd"
