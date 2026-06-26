"""Data models for the Iowa Appellate Courts scraper.

Two CourtListener court ids share the same docket number space:

- ``iowa`` — Supreme Court of Iowa
- ``iowactapp`` — Court of Appeals of Iowa

Every appeal is initially docketed at the Supreme Court. Cases the court
chooses to transfer carry a ``TRANSFERRED TO COURT OF APPEALS`` docket
event; we use that event to assign ``court`` at assemble time.

Field names follow [`../../CL_MODELS.md`](../../CL_MODELS.md): the
CourtListener court-id string is ``court`` (not ``court_id``), the public
docket number is ``docket_number`` (not ``docket_id``), and dates use the
``date_*`` prefix. ``CleanString``/``HarmonizedCaseName`` come from
``juriscraper.state.common_models``.
"""

from __future__ import annotations

from datetime import date

from jkent.common.data_models import ScrapedData

from juriscraper.state.common_models import CleanString, HarmonizedCaseName

# Courts covered. Display names mirror courts_db; the keys are the
# CourtListener court ids the scraper emits.
COURT_IDS: dict[str, str] = {
    "iowa": "Supreme Court of Iowa",
    "iowactapp": "Court of Appeals of Iowa",
}

# Default ("not yet transferred") court. Cases sit at the Supreme Court
# until the Supreme Court decides to push them down.
DEFAULT_COURT_ID = "iowa"

# Substring that, when found in any docket entry's event text, signals
# that the case has moved to the Court of Appeals.
COA_TRANSFER_SIGNAL = "TRANSFERRED TO COURT OF APPEALS"

# Endpoints (paths under the base URL).
BASE_URL = "https://www.iowacourts.state.ia.us"
ADV_SEARCH_URL = f"{BASE_URL}/ESAWebApp/AViewSearchResultsAdv"
CASE_SUMMARY_URL = f"{BASE_URL}/ESAWebApp/AViewCase"
CASE_LONG_TITLE_URL = f"{BASE_URL}/ESAWebApp/AViewLongTitle"
CASE_DOCKET_URL = f"{BASE_URL}/ESAWebApp/AViewDocket"
CASE_PARTIES_URL = f"{BASE_URL}/ESAWebApp/AViewParties"


class IowaDocketEntry(ScrapedData):
    """One row of the case's Register of Actions (Docket tab).

    Maps loosely to CourtListener ``DocketEntry``."""

    date_filed: date | None = None
    """`Date of Filing` cell. ``MM/DD/YYYY`` on the page."""

    date_served: date | None = None
    """`Date Served` cell, when set."""

    event: CleanString
    """`Event` cell (e.g., ``OPINION: AFFIRMED``, ``NOTICE OF APPEAL (CERT)``)."""

    filed_by: CleanString | None = None
    """`Filed By` cell — party, attorney, judge, or clerk role."""

    due_date: date | None = None
    """`Due Date` cell, when set."""

    notes: CleanString | None = None
    """Free-text comment from the optional ``Comments:`` follow-on row."""

    event_id: str | None = None
    """Site-internal event id parsed from the row's ``<!-- Event ID #N -->`` comment."""


class IowaParty(ScrapedData):
    """A row from the Parties tab.

    The same table holds both human parties (``APPELLANT``, ``APPELLEE``,
    ``DEFENDANT``…) and attorneys/firms (``ATTORNEY FOR APPELLANT``,
    ``APPELLATE DEFENDER``…). The role string is the only signal of which
    is which. Maps to CourtListener ``Party`` (+ ``PartyType`` for the
    role on this docket); attorney rows map to ``Attorney`` + ``Role``."""

    name: CleanString
    """Display name as shown on the page (UPPERCASE on the live site)."""

    role: CleanString
    """Appellate role label, e.g., ``APPELLANT`` / ``ATTORNEY FOR APPELLANT``."""

    status: CleanString | None = None
    """Membership status: ``ACTIVE``, ``WITHDRAWN``, ``INACTIVE``."""

    site_id: str | None = None
    """Internal site id from the ``AViewAttorney?<id>`` link, if present.
    Lets the same attorney/party be reconciled across cases."""


class IowaDocket(ScrapedData):
    """A complete Iowa appellate case docket.

    Maps to CourtListener ``Docket`` (+ its per-court side tables)."""

    # === Identifying / searchable fields ===
    docket_number: str
    """Public docket number, ``YY-NNNN`` (e.g., ``25-2200``)."""

    court: str = DEFAULT_COURT_ID
    """``iowa`` (Supreme) or ``iowactapp`` (Court of Appeals); see
    :data:`COA_TRANSFER_SIGNAL` for how this is decided."""

    date_filed: date | None = None
    """Date of the earliest docket entry — typically the
    ``NOTICE OF APPEAL`` filing."""

    case_name: HarmonizedCaseName
    """Short title from the Summary header (e.g., ``State v. Robinson``)."""

    case_name_full: CleanString | None = None
    """Long title from the Long Title tab (e.g., ``STATE OF IOWA,
    Plaintiff-Appellee, vs. SHERRELL QUINTRAD ROBINSON, Defendant-Appellant``).
    Many older cases have an empty Long Title and this stays ``None``."""

    # === Case metadata ===
    case_type: CleanString | None = None
    """``CRIMINAL CASE``, ``CIVIL CASE``, ``JUVENILE CASE``, etc."""

    status: CleanString | None = None
    """Latest status string (``NOTICE OF APPEAL FILED``, ``SUBMITTED``,
    ``OPINION FILED``, ``DISPOSED``, …)."""

    citation: CleanString | None = None
    """Reporter cite when the case has been assigned one; else ``None``.
    The Summary page renders ``"No Cite Listed"`` when absent."""

    appellate_judges: list[str] = []
    """Judges/justices listed on the Summary page (panel members or assigned
    writer). Empty when the page renders ``"No Judges Listed"``."""

    # === Trial court linkage ===
    trial_court_case_id: CleanString | None = None
    """Originating district-court case number (e.g., ``FECR391937``)."""

    trial_court_county: CleanString | None = None
    """Originating county (UPPERCASE, e.g., ``POLK``)."""

    assigned_to_str: CleanString | None = None
    """Trial-court judge name from the Summary page (CL ``assigned_to_str``)."""

    # === Nested data ===
    entries: list[IowaDocketEntry] = []
    parties: list[IowaParty] = []

    source_url: str | None = None
    """The Summary tab URL the record was assembled from."""

    source_entry_point: str | None = None
    """Entry point used to reach this docket (e.g. ``dockets_by_filing_date``)."""
