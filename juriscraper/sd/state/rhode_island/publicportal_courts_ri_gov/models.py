"""Data models for the Rhode Island Judiciary Public Portal scraper.

The portal is the Tyler Odyssey Public Portal product (distinct from
Tyler MyCase and from the Thomson Reuters C-Track "TR Portal"). It
serves the Supreme Court of Rhode Island, the only Rhode Island
appellate court.

See ``DESIGN.md`` for site overview, search shape, and known gaps.

Courts:
- ``ri``: Supreme Court of Rhode Island
"""

from __future__ import annotations

from datetime import date

from jkent.common.data_models import ScrapedData

# ----------------------------------------------------------------------------
# URLs and form values
# ----------------------------------------------------------------------------

PORTAL_URL = "https://publicportal.courts.ri.gov"

# Smart Search dashboard. The numeric suffix selects the search type;
# 29 = "Smart Search". Other dashboards exist (warrant, citation, etc.)
# but only Smart Search returns case dockets.
DASHBOARD_URL = f"{PORTAL_URL}/PublicPortal/Home/Dashboard/29"

# Search form action — also where the rendered results page is returned.
SEARCH_POST_URL = (
    f"{PORTAL_URL}/PublicPortal/SmartSearch/SmartSearch/SmartSearch"
)

# CourtListener court_id -> CourtLocation dropdown value used by the
# server to scope the search. The portal sends the verbatim display
# string in the form post; there is no separate numeric / GUID id.
RI_COURTS: dict[str, str] = {
    "ri": "Supreme Court Search",
}

# Display names for human-readable logging.
RI_COURT_NAMES: dict[str, str] = {
    "ri": "Supreme Court of Rhode Island",
}


# ----------------------------------------------------------------------------
# Models
# ----------------------------------------------------------------------------


class RIDocketEntry(ScrapedData):
    """A single docket entry / register-of-actions row.

    Reserved for v2 — case-detail page parsing is gated behind reCAPTCHA
    and was not verifiable during v1 recon.
    """

    date_filed: date | None = None
    description: str
    notes: str | None = None


class RIParty(ScrapedData):
    """A party in a Rhode Island appellate case (v2)."""

    name: str
    role: str | None = None
    attorneys: list[str] = []


class RIDocket(ScrapedData):
    """A docket from the Rhode Island Judiciary Public Portal.

    v1 carries only the fields available from the search-result row.
    The nested ``entries`` and ``parties`` lists are reserved for v2,
    once the case-detail page structure is confirmed against a live
    captcha-solving deploy.
    """

    case_number: str
    """Public docket number as returned by the search results."""

    court_id: str
    """CourtListener court id — currently always ``ri``."""

    case_name: str
    """Case caption / style from the search-result row."""

    date_filed: date | None = None
    """Filing date from the search-result row (``mm/dd/yyyy`` parsed)."""

    case_type: str | None = None
    """Case type label from the search-result row."""

    case_status: str | None = None
    """Case status label from the search-result row."""

    judicial_officer: str | None = None
    """Assigned judge from the search-result row, when shown."""

    source_url: str | None = None
    """Absolute URL of the case-detail page."""

    entries: list[RIDocketEntry] = []
    """Docket entries — populated in v2."""

    parties: list[RIParty] = []
    """Parties — populated in v2."""
