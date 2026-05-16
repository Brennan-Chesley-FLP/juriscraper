"""Data models for Oregon appellate courts scraper.

These models extend the common TR Portal base models for Oregon's
Supreme Court and Court of Appeals.

Supported courts:
- or: Oregon Supreme Court
- orctapp: Oregon Court of Appeals
"""

from __future__ import annotations

from juriscraper.sd.state.common.tr.models import (
    TRCourtConfig,
    TRDocket,
    TRDocketEntry,
    TRDocument,
    TROralArgument,
)

# Court configuration
COURT_CONFIG: dict[str, TRCourtConfig] = {
    "or": {
        "name": "Oregon Supreme Court",
        "court_guid": "f28c1f7b-0af7-4462-b253-bd5371f86443",
        "numeric_id": "2",
        "abbreviation": "Oregon Supreme Court",
    },
    "orctapp": {
        "name": "Oregon Court of Appeals",
        "court_guid": "3d764b2a-2faa-4613-aac6-7da3b06325f4",
        "numeric_id": "1",
        "abbreviation": "Oregon Court of Appeals",
    },
}

# API configuration
API_BASE_URL = "https://trportal-api.courts.oregon.gov"
PORTAL_URL = "https://trportal.courts.oregon.gov"


class OreDocketEntry(TRDocketEntry):
    """A docket entry from Oregon appellate courts."""


class OreDocket(TRDocket):
    """A docket from Oregon appellate courts.

    Represents a complete case with all its metadata from the
    TR Portal at trportal.courts.oregon.gov.
    """

    entries: list[OreDocketEntry] = []
    """All docket entries"""


class OreOralArgument(TROralArgument):
    """An oral argument from Oregon appellate courts."""


class OreDocument(TRDocument):
    """A document attached to an Oregon appellate court docket entry.

    Note: many Oregon appellate documents are paywalled, so anonymous
    archive requests for those will fail and the resulting record will
    have ``local_path=None``.
    """
