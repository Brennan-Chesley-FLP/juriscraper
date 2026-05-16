"""Data models for the Vermont Judiciary Public Portal scraper.

The portal is the Tyler Odyssey Public Portal product (the same software
behind ``rhode_island/publicportal_courts_ri_gov``, but without
reCAPTCHA and without DataDome). It serves the Supreme Court of Vermont,
the only Vermont appellate court.

See ``DESIGN.md`` for site overview, search shape, and the JSON-service
endpoint catalog.

Courts:
- ``vt``: Supreme Court of Vermont
"""

from __future__ import annotations

from datetime import date

from jkent.common.data_models import ScrapedData

# ----------------------------------------------------------------------------
# URLs and form values
# ----------------------------------------------------------------------------

PORTAL_URL = "https://portal.vtcourts.gov"

# Smart Search dashboard. The numeric suffix selects the search type;
# 29 = "Smart Search". Other dashboards exist (payments, etc.) but only
# Smart Search returns case dockets.
DASHBOARD_URL = f"{PORTAL_URL}/Portal/Home/Dashboard/29"

# Form action — also where the empty WorkspaceMode redirect lands.
SEARCH_POST_URL = f"{PORTAL_URL}/Portal/SmartSearch/SmartSearch/SmartSearch"

# AJAX-fetched grid of search results. The session cookie set by the
# POST scopes which results this returns.
SEARCH_RESULTS_URL = f"{PORTAL_URL}/Portal/SmartSearch/SmartSearchResults"

# Register-of-Actions JSON service base. The opaque ``key`` carried by
# each search-row's ``data-url`` addresses every case-detail endpoint.
ROA_SERVICE_BASE = f"{PORTAL_URL}/app/RegisterOfActionsService"

# Document download chain — first hop is a 302; under FOLLOW_REDIRECTS
# we land on the DocumentViewer/Index HTML page that contains the
# actual download link.
DOC_DISPLAY_URL = f"{PORTAL_URL}/Portal/DocumentViewer/DisplayDoc"


# CourtListener court_id -> Tyler ``CourtLocation`` dropdown value used
# by the server to scope the search. The portal sends the verbatim
# display string in the form post; there is no separate numeric / GUID
# id.
VT_COURTS: dict[str, str] = {
    "vt": "Vermont Supreme Court",
}

# Display names for human-readable logging.
VT_COURT_NAMES: dict[str, str] = {
    "vt": "Supreme Court of Vermont",
}


# ----------------------------------------------------------------------------
# Models
# ----------------------------------------------------------------------------


class VtAttorney(ScrapedData):
    """An attorney representing a party in a Vermont appellate case."""

    name: str
    role: str | None = None
    """e.g. ``Retained`` or ``Court Appointed`` from the Parties JSON."""


class VtParty(ScrapedData):
    """A party in a Vermont appellate case."""

    name: str
    role: str | None = None
    """Party role — ``Appellant``, ``Appellee``, ``Petitioner``, etc."""

    attorneys: list[VtAttorney] = []


class VtDocketEntry(ScrapedData):
    """A single register-of-actions entry from ``CombinedEvents``."""

    date_filed: date | None = None
    description: str
    """Event description — e.g. ``Final Decision Written Opinion``,
    ``Appellant's Brief``, ``Notice to Parties``."""

    judicial_officer: str | None = None
    """Judge associated with the event, when one is named."""

    filer: str | None = None
    """Brief description of who filed (party + attorney), when present."""

    has_document: bool = False
    """True if the event has at least one downloadable document attached."""


class VtDocument(ScrapedData):
    """A single downloadable document attached to a Vermont appellate case.

    Yielded as a separate ``ParsedData`` after the framework has archived
    the file to ``local_path``.
    """

    docket_id: str
    """Vermont docket number (e.g. ``24-AP-121``)."""

    court_id: str

    document_id: str
    """Tyler ``DocumentID`` — stable per document."""

    document_fragment_id: str
    """Tyler ``DocumentFragmentID`` — addresses the file in the viewer."""

    document_name: str | None = None
    document_type: str | None = None
    date_filed: date | None = None

    download_url: str | None = None
    """The final ``DownloadDocumentFile/Download`` URL."""

    local_path: str | None = None
    """Path to the archived file on disk."""


class VtDocket(ScrapedData):
    """A Vermont Supreme Court docket assembled from the Smart-Search row
    and the Register-of-Actions JSON service.
    """

    docket_id: str
    """Public docket number — ``YY-AP-NNN`` form."""

    court_id: str
    """CourtListener court id — currently always ``vt``."""

    case_name: str
    """Case caption / style."""

    date_filed: date | None = None
    """Filing date from ``CaseSummariesSlim.CaseSummaryHeader.FiledOn``."""

    case_type: str | None = None
    """Case type description (e.g. ``Misdemeanor Appeal``, ``Civil Appeal``)."""

    case_status: str | None = None
    """Case status description (e.g. ``Active``, ``Closed``)."""

    disposition: str | None = None
    """Most recent disposition description, when present."""

    disposition_date: date | None = None

    citation: str | None = None
    """Vermont opinion citation when one has been assigned (e.g. ``2025 VT 14``)."""

    entries: list[VtDocketEntry] = []
    parties: list[VtParty] = []
    documents: list[VtDocument] = []
    """Slim references to documents available on the case. The actual
    archived files are emitted as separate ``VtDocument`` ``ParsedData``
    records once the download chase completes."""

    source_url: str | None = None
    """Absolute URL of the case-detail SPA."""
