"""Data models for the Pennsylvania UJS Portal appellate scraper.

The Unified Judicial System web portal at
https://ujsportal.pacourts.us/CaseSearch is the public face of the three
Pennsylvania appellate courts (Supreme, Superior, Commonwealth). The site
exposes a single ASP.NET Core form whose results grid carries the case
metadata, plus a per-docket Crystal-Reports PDF "docket sheet" with the
full register-of-actions text.

Field names follow [`../../CL_MODELS.md`](../../CL_MODELS.md): the
CourtListener court-id string is ``court`` (not ``court_id``), the case
caption is ``case_name``, and dates use the ``date_*`` prefix.

The **site constants** below (search URL, form XPath, the
``AppellateCourtName`` maps, the result-row cap and split floor, the browser
headers) live here rather than in ``scraper.py`` because the sibling
``service_pacourts_us`` JSON-API scraper imports them: that API has no
date-range search, so it runs this portal's filing-date search cross-domain
to discover docket numbers. Keep them here, and keep
``ResultsGridParser``'s output keys stable — see ``CC_NOTES.md``
→ "Search Capabilities".

Models:

- ``PADocket`` — the per-row case record built from
  ``#caseSearchResultGrid``. Maps to CourtListener ``Docket``.
- ``PADocketSheetPDF`` — the archived docket-sheet PDF descriptor, emitted
  by the ``handle_docket_sheet_pdf`` step which is reached via an
  ``archive=True`` request and so receives ``local_filepath`` from the
  driver. PDF parsing into structured docket entries is explicitly
  post-hoc and lives outside this scraper.
"""

from __future__ import annotations

from datetime import date, timedelta

from jkent.common.data_models import ScrapedData
from jkent.data_types import XPath

from juriscraper.state.common_models import CleanString, HarmonizedCaseName

# =========================================================================
# Site constants
# =========================================================================

BASE_URL: str = "https://ujsportal.pacourts.us"
SEARCH_URL: str = f"{BASE_URL}/CaseSearch"

# CourtListener court IDs covered by this scraper, keyed to their display
# names. The dict is documentation for human reference; the scraper maps
# from the site's ``AppellateCourtName`` form value
# ("Supreme" / "Superior" / "Commonwealth") to the CL id directly.
COURT_IDS: dict[str, str] = {
    "pa": "Supreme Court of Pennsylvania",
    "pasuperct": "Superior Court of Pennsylvania",
    "pacommwct": "Commonwealth Court of Pennsylvania",
}

# ``AppellateCourtName`` form value <-> CourtListener ID. The site dropdown
# only offers these three values.
SITE_COURT_TO_COURT_ID: dict[str, str] = {
    "Supreme": "pa",
    "Superior": "pasuperct",
    "Commonwealth": "pacommwct",
}
COURT_ID_TO_SITE_COURT: dict[str, str] = {
    v: k for k, v in SITE_COURT_TO_COURT_ID.items()
}

# The single search form on /CaseSearch. ``find_form()`` preserves every
# hidden input (including ``__RequestVerificationToken``) and lets us
# override only the fields we care about via the ``data=`` kwarg.
SEARCH_FORM_XPATH = XPath("//form[@id='case-search-form-id']")

# Empirical row cap for the results grid. A search whose result count
# meets this cap is presumed truncated and the date range is split.
RESULT_ROW_CAP = 500

# Floor for date-range splitting. With a 1-day window we accept whatever
# row count comes back rather than continuing to split — same-day filings
# above the cap are extremely unlikely for these courts.
MIN_SPLIT_WINDOW = timedelta(days=1)

# The PDF endpoint (/Report/PacDocketSheet) returns 401 to clients with
# httpx's default User-Agent, and so does /CaseSearch itself for some
# clients. Sent on every request via ``Request.permanent`` so it cascades
# through the form-submit POST and the PDF archive GET.
BROWSER_HEADERS: dict[str, str] = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/147.0.0.0 Safari/537.36"
    ),
}


# =========================================================================
# Data models
# =========================================================================


class PADocket(ScrapedData):
    """A row from the UJS Portal case-search results grid.

    One ``PADocket`` is emitted per matching docket on either the
    docket-number lookup or the appellate date-range walk. Most fields
    come straight from the corresponding ``<td>`` in the row; the trial-
    court columns (``county``, ``otn``, etc.) are present in the grid
    schema but mostly blank for appellate cases and are kept as optional
    fields so the same model fits future trial-court use.

    Maps to CourtListener ``Docket``.
    """

    court: str
    """CourtListener court ID — ``pa`` / ``pasuperct`` / ``pacommwct``."""

    docket_number: str
    """Docket number as printed on the site, e.g. ``44 WM 2026``.
    Format is ``<seq> <type> <year>`` where the type prefix encodes
    court + district + case-type and the sequence resets yearly."""

    case_name: HarmonizedCaseName
    """Case caption from the grid (the site's word for case name)."""

    case_status: CleanString | None = None
    """Case status (``Active``, ``Closed``, etc.) from the grid."""

    date_filed: date | None = None
    """Filing date parsed from the ``Filing Date`` column (MM/DD/YYYY)."""

    court_type: CleanString | None = None
    """Site-side ``Court Type`` cell — should be ``Appellate`` for our
    targets but kept as a free-text field in case the value drifts."""

    primary_participants: CleanString | None = None
    """``Primary Participant(s)`` cell as raw text — usually empty for
    appellate cases."""

    county: CleanString | None = None
    """``County`` cell — usually empty for appellate cases."""

    court_office: CleanString | None = None
    """``Court Office`` cell — usually empty for appellate cases."""

    otn: CleanString | None = None
    """Offense Tracking Number — appellate cases rarely have one."""

    complaint_number: CleanString | None = None
    """``Complaint #`` cell — appellate cases rarely have one."""

    incident_number: CleanString | None = None
    """``Incident #`` cell — appellate cases rarely have one."""

    next_event_type: CleanString | None = None
    """Upcoming-event type from the ``Event Type`` column, when present."""

    next_event_status: CleanString | None = None
    """Upcoming-event status from the ``Event Status`` column."""

    next_event_date: date | None = None
    """Upcoming-event date parsed from the ``Event Date`` column."""

    next_event_location: CleanString | None = None
    """Upcoming-event location from the ``Event Location`` column."""

    docket_sheet_url: str | None = None
    """Absolute URL of the Crystal-Reports docket-sheet PDF
    (``/Report/PacDocketSheet?docketNumber=…&dnh=…``). The ``dnh`` hash
    is captured verbatim from the row HTML and is required to fetch the
    PDF."""

    source_url: str | None = None
    """URL of the search results page that surfaced this row."""

    source_entry_point: str | None = None
    """Entry point used to reach this docket (``dockets_by_filing_date``
    or ``docket_by_number``)."""


class PADocketSheetPDF(ScrapedData):
    """The archived docket-sheet PDF for a Pennsylvania appellate case.

    This model is intentionally named with the ``PDF`` suffix to mark it
    as the unparsed-binary artifact: the PDF contains the full register
    of actions, parties, attorneys, and dispositions, but extraction of
    those structured records is performed post-hoc by a downstream PDF
    parser, not by this scraper.

    Emitted by ``handle_docket_sheet_pdf`` which is the continuation of
    an ``archive=True`` request — the kent driver writes the PDF to disk
    and injects the resulting path as ``local_filepath``.
    """

    court: str
    """CourtListener court ID — copied from the parent ``PADocket``."""

    docket_number: str
    """Docket number this PDF corresponds to (e.g. ``44 WM 2026``)."""

    document_url: str
    """The ``/Report/PacDocketSheet?…`` URL that was archived."""

    local_path: str | None = None
    """Local filesystem path where the kent driver wrote the PDF.
    Populated by the driver via the ``local_filepath`` step argument; may
    be ``None`` if the archive failed."""
