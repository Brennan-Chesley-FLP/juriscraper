"""Data models for the Rhode Island Judiciary Public Portal scraper.

The portal is the Tyler Odyssey Public Portal product (distinct from
Tyler MyCase and from the Thomson Reuters C-Track "TR Portal"). It
serves the Supreme Court of Rhode Island, the only Rhode Island
appellate court.

See ``CC_NOTES.md`` for site overview, search shape, and known gaps.

Field names follow [`../../CL_MODELS.md`](../../CL_MODELS.md): the
CourtListener court-id string is ``court`` (not ``court_id``), the case
number is ``docket_number`` (with ``docket_number_raw`` for the verbatim
value), and dates use the ``date_*`` prefix.

Courts:
- ``ri``: Supreme Court of Rhode Island
"""

from __future__ import annotations

from datetime import date

from jkent.common.data_models import ScrapedData

from juriscraper.state.common_models import CleanString, HarmonizedCaseName

COURT_ID: str = "ri"

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
    COURT_ID: "Supreme Court Search",
}

# Display names for human-readable logging.
RI_COURT_NAMES: dict[str, str] = {
    COURT_ID: "Supreme Court of Rhode Island",
}


# ----------------------------------------------------------------------------
# Models
# ----------------------------------------------------------------------------


class RIDocketEntry(ScrapedData):
    """A single docket entry / register-of-actions row.

    Reserved for v2 — case-detail page parsing is gated behind reCAPTCHA
    and was not verifiable during v1 recon. Maps to CourtListener
    ``DocketEntry``.
    """

    date_filed: date | None = None
    """Filing date of the entry, when shown."""
    description: str
    """Text content of the docket entry."""
    notes: CleanString | None = None
    """Any supplementary note attached to the entry."""


class RIParty(ScrapedData):
    """A party in a Rhode Island appellate case (v2).

    Maps to CourtListener ``Party`` (+ ``PartyType`` for the role on this
    docket).
    """

    name: CleanString
    """Verbatim party name."""
    role: CleanString | None = None
    """Role on appeal (CL ``PartyType.name``)."""
    attorneys: list[str] = []
    """Representing attorneys, verbatim (CL ``Attorney``/``Role``)."""


class RIDocket(ScrapedData):
    """A docket from the Rhode Island Judiciary Public Portal.

    v1 carries only the fields available from the search-result row.
    The nested ``entries`` and ``parties`` lists are reserved for v2,
    once the case-detail page structure is confirmed against a live
    captcha-solving deploy. Maps to CourtListener ``Docket``.
    """

    docket_number: str
    """Public docket number as returned by the search results (cleaned
    enough to be usable)."""

    docket_number_raw: str | None = None
    """Verbatim docket number from the result row, no cleaning. Set only
    when it differs from ``docket_number``."""

    court: str = COURT_ID
    """CourtListener court id — currently always ``ri``."""

    case_name: HarmonizedCaseName
    """Case caption / style from the search-result row."""

    date_filed: date | None = None
    """Filing date from the search-result row (``mm/dd/yyyy`` parsed)."""

    case_type: CleanString | None = None
    """Case type label from the search-result row."""

    case_status: CleanString | None = None
    """Case status label from the search-result row."""

    judicial_officer: CleanString | None = None
    """Assigned judge from the search-result row, when shown
    (CL ``assigned_to_str``)."""

    source_url: str | None = None
    """Absolute URL of the case-detail page this row links to."""

    source_entry_point: str | None = None
    """Entry point used to reach this docket (e.g. ``dockets_by_number``)."""

    entries: list[RIDocketEntry] = []
    """Docket entries — populated in v2."""

    parties: list[RIParty] = []
    """Parties — populated in v2."""
