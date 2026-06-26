"""Data models for Wyoming Supreme Court scraper.

These models extend the common TR Portal base models for Wyoming's
Supreme Court served by the Appellate C-Track Electronic Filing
Portal (CTEF) at ctefiling.wyocourts.gov.

Supported courts:
- wyo: Wyoming Supreme Court
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
    "wyo": {
        "name": "Wyoming Supreme Court",
        "court_guid": "cd2875bd-3280-4b05-ac69-030ce5faac20",
        "numeric_id": "1",
        "abbreviation": "Wyoming",
    },
}

API_BASE_URL = "https://ctefiling-api.wyocourts.gov"
PORTAL_URL = "https://ctefiling.wyocourts.gov"


class WyoDocketEntry(TRDocketEntry):
    """A docket entry from the Wyoming Supreme Court."""


class WyoDocket(TRDocket):
    """A docket from the Wyoming Supreme Court.

    Represents a complete case with all its metadata from the
    Appellate C-Track Electronic Filing Portal at
    ctefiling.wyocourts.gov.
    """

    entries: list[WyoDocketEntry] = []
    """All docket entries"""


class WyoOralArgument(TROralArgument):
    """An oral argument from the Wyoming Supreme Court."""


class WyoDocument(TRDocument):
    """A document attached to a Wyoming Supreme Court docket entry."""

    court: str = "wyo"
