"""Data models for the Vermont Judiciary Public Portal scraper.

The portal is the Tyler Odyssey Public Portal product (the same software
behind ``rhode_island/publicportal_courts_ri_gov``, but without
reCAPTCHA and without DataDome). It serves the Supreme Court of Vermont,
the only Vermont appellate court.

See ``CC_NOTES.md`` for site overview, search shape, and the JSON-service
endpoint catalog.

Field names follow [`../../CL_MODELS.md`](../../CL_MODELS.md): the
CourtListener court-id string is ``court`` (not ``court_id``), the case
number is ``docket_number`` (not ``case_number``/``docket_id``), and dates
use the ``date_*`` prefix.

Courts:
- ``vt``: Supreme Court of Vermont
"""

from __future__ import annotations

from datetime import date

from jkent.common.data_models import ScrapedData

from juriscraper.state.common_models import CleanString, HarmonizedCaseName

# ----------------------------------------------------------------------------
# URLs and form values
# ----------------------------------------------------------------------------

COURT_ID: str = "vt"
COURT_NAME: str = "Supreme Court of Vermont"

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


class VtSearchRow(ScrapedData):
    """A single row lifted from the Smart-Search results grid.

    Not an emitted record — a carrier between the grid HTML parser and
    the JSON-service flow. The ``roa_key`` is the opaque token that
    addresses every Register-of-Actions endpoint for this case.
    """

    roa_key: str
    """Opaque key from the row ``data-url``'s ``id=`` parameter."""

    docket_number: CleanString
    """Display docket number from the case-link text (``YY-AP-NNN``)."""

    case_name: CleanString | None = None
    """Caption / style cell, when present."""

    case_type: CleanString | None = None
    """Case-type column text (e.g. ``Misdemeanor Appeal``)."""

    case_status: CleanString | None = None
    """Case-status column text (e.g. ``Active``, ``Closed``)."""

    source_url: str | None = None
    """Absolute URL of the case-detail SPA (from ``data-url``)."""


class VtAttorney(ScrapedData):
    """An attorney representing a party in a Vermont appellate case.

    Maps to CourtListener ``Attorney`` (+ ``Role`` for the role on this
    docket).
    """

    name: CleanString
    role: CleanString | None = None
    """e.g. ``Retained`` or ``Court Appointed`` from the Parties JSON."""


class VtParty(ScrapedData):
    """A party in a Vermont appellate case.

    Maps to CourtListener ``Party`` (+ ``PartyType`` for the role on this
    docket).
    """

    name: CleanString
    role: CleanString | None = None
    """Party role — ``Appellant``, ``Appellee``, ``Petitioner``, etc.
    (CL ``PartyType.name``)."""

    attorneys: list[VtAttorney] = []


class VtDocketEntry(ScrapedData):
    """A single register-of-actions entry from ``CombinedEvents``.

    Maps to CourtListener ``DocketEntry``.
    """

    date_filed: date | None = None
    """Created date of the entry (court timezone)."""

    description: CleanString
    """Event description — e.g. ``Final Decision Written Opinion``,
    ``Appellant's Brief``, ``Notice to Parties``."""

    judicial_officer: CleanString | None = None
    """Judge associated with the event, when one is named."""

    filer: CleanString | None = None
    """Brief description of who filed (party + attorney), when present."""

    has_document: bool = False
    """True if the event has at least one downloadable document attached."""


class VtDocument(ScrapedData):
    """A single downloadable document attached to a Vermont appellate case.

    Yielded as a separate ``ParsedData`` after the framework has archived
    the file to ``local_path``. Maps to CourtListener ``RECAPDocument``.
    """

    docket_number: CleanString
    """Vermont docket number (e.g. ``24-AP-121``) linking back to the
    parent ``VtDocket``."""

    court: str = COURT_ID
    """CourtListener court id — currently always ``vt``."""

    document_id: str
    """Tyler ``DocumentID`` — stable per document."""

    document_fragment_id: str
    """Tyler ``DocumentFragmentID`` — addresses the file in the viewer."""

    document_name: CleanString | None = None
    document_type: CleanString | None = None
    date_filed: date | None = None

    download_url: str | None = None
    """The final ``DownloadDocumentFile/Download`` URL."""

    local_path: str | None = None
    """Path to the archived file on disk (``filepath_local`` in CL)."""


class VtDocket(ScrapedData):
    """A Vermont Supreme Court docket assembled from the Smart-Search row
    and the Register-of-Actions JSON service.

    Maps to CourtListener ``Docket``.
    """

    docket_number: CleanString
    """Public docket number — ``YY-AP-NNN`` form."""

    court: str = COURT_ID
    """CourtListener court id — currently always ``vt``."""

    case_name: HarmonizedCaseName
    """Case caption / style."""

    date_filed: date | None = None
    """Filing date from ``CaseSummariesSlim.CaseSummaryHeader.FiledOn``."""

    case_type: CleanString | None = None
    """Case type description (e.g. ``Misdemeanor Appeal``, ``Civil Appeal``)."""

    case_status: CleanString | None = None
    """Case status description (e.g. ``Active``, ``Closed``)."""

    disposition: CleanString | None = None
    """Most recent disposition description, when present."""

    date_terminated: date | None = None
    """Date of the most recent disposition, when present (CL
    ``date_terminated``)."""

    citation: CleanString | None = None
    """Vermont opinion citation when one has been assigned (e.g.
    ``2025 VT 14``)."""

    entries: list[VtDocketEntry] = []
    parties: list[VtParty] = []
    documents: list[VtDocument] = []
    """Slim references to documents available on the case. The actual
    archived files are emitted as separate ``VtDocument`` ``ParsedData``
    records once the download chase completes."""

    source_url: str | None = None
    """Absolute URL of the case-detail SPA."""

    source_entry_point: str | None = None
    """Entry point used to reach this docket (e.g. ``dockets_by_number``)."""
