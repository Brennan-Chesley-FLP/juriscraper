"""Data models for the Nevada appellate courts scraper.

These models extend the common TR Portal base models for Nevada's
Supreme Court and Court of Appeals, served by the Thomson Reuters
C-Track Appellate Case Information System (ACIS) at acis.nvcourts.gov.

Supported courts:
- nev: Nevada Supreme Court
- nevapp: Nevada Court of Appeals
"""

from __future__ import annotations

from juriscraper.state.common.tr.models import (
    TRCourtConfig,
    TRDocket,
    TRDocketEntry,
    TRDocument,
    TROralArgument,
)

# Court configuration.
# numeric_id matches the caseHeader.courtID / event.courtID values the API
# returns ("1" = Supreme Court, "2" = Court of Appeals); abbreviation matches
# the courtAbbreviation field on the case-search and events feeds.
COURT_CONFIG: dict[str, TRCourtConfig] = {
    "nev": {
        "name": "Nevada Supreme Court",
        "court_guid": "dc01122c-a19d-4eb7-bfe9-5b96e93c26fd",
        "numeric_id": "1",
        "abbreviation": "Supreme Court",
    },
    "nevapp": {
        "name": "Nevada Court of Appeals",
        "court_guid": "74764f58-a87f-4ec5-8233-7a1255e410b3",
        "numeric_id": "2",
        "abbreviation": "Court of Appeals",
    },
}

# API configuration
API_BASE_URL = "https://acis-api.nvcourts.gov"
PORTAL_URL = "https://acis.nvcourts.gov"


class NevDocketEntry(TRDocketEntry):
    """A docket entry from a Nevada appellate court."""


class NevDocket(TRDocket):
    """A docket from a Nevada appellate court.

    Represents a complete case with all its metadata from the
    C-Track ACIS portal at acis.nvcourts.gov.
    """

    entries: list[NevDocketEntry] = []
    """All docket entries"""


class NevOralArgument(TROralArgument):
    """An oral argument from a Nevada appellate court."""


class NevDocument(TRDocument):
    """A document attached to a Nevada appellate court docket entry."""
