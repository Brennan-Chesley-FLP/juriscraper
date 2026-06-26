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

from datetime import date

from jkent.common.data_models import ScrapedData

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
