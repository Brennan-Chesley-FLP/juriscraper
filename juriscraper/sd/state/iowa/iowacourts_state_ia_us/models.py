"""Data models for the Iowa Appellate Courts scraper.

Two CourtListener court ids share the same docket number space:

- ``iowa`` — Supreme Court of Iowa
- ``iowactapp`` — Court of Appeals of Iowa

Every appeal is initially docketed at the Supreme Court. Cases the court
chooses to transfer carry a ``TRANSFERRED TO COURT OF APPEALS`` docket
event; we use that event to assign ``court_id`` at assemble time.
"""

from __future__ import annotations

from datetime import date

from jkent.common.data_models import ScrapedData

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
    """One row of the case's Register of Actions (Docket tab)."""

    date_filed: date | None = None
    """`Date of Filing` cell. ``MM/DD/YYYY`` on the page."""

    date_served: date | None = None
    """`Date Served` cell, when set."""

    event: str
    """`Event` cell (e.g., ``OPINION: AFFIRMED``, ``NOTICE OF APPEAL (CERT)``)."""

    filed_by: str | None = None
    """`Filed By` cell — party, attorney, judge, or clerk role."""

    due_date: date | None = None
    """`Due Date` cell, when set."""

    notes: str | None = None
    """Free-text comment from the optional ``Comments:`` follow-on row."""

    event_id: str | None = None
    """Site-internal event id parsed from the row's ``<!-- Event ID #N -->`` comment."""


class IowaParty(ScrapedData):
    """A row from the Parties tab.

    The same table holds both human parties (``APPELLANT``, ``APPELLEE``,
    ``DEFENDANT``…) and attorneys/firms (``ATTORNEY FOR APPELLANT``,
    ``APPELLATE DEFENDER``…). The role string is the only signal of which
    is which.
    """

    name: str
    """Display name as shown on the page (UPPERCASE on the live site)."""

    role: str
    """Appellate role label, e.g., ``APPELLANT`` / ``ATTORNEY FOR APPELLANT``."""

    status: str | None = None
    """Membership status: ``ACTIVE``, ``WITHDRAWN``, ``INACTIVE``."""

    site_id: str | None = None
    """Internal site id from the ``AViewAttorney?<id>`` link, if present.
    Lets the same attorney/party be reconciled across cases."""


class IowaDocket(ScrapedData):
    """A complete Iowa appellate case docket."""

    # === Identifying / searchable fields ===
    docket_id: str
    """Public docket number, ``YY-NNNN`` (e.g., ``25-2200``)."""

    court_id: str = DEFAULT_COURT_ID
    """``iowa`` (Supreme) or ``iowactapp`` (Court of Appeals); see
    :data:`COA_TRANSFER_SIGNAL` for how this is decided."""

    date_filed: date | None = None
    """Date of the earliest docket entry — typically the
    ``NOTICE OF APPEAL`` filing."""

    case_name: str
    """Short title from the Summary header (e.g., ``State v. Robinson``)."""

    case_name_full: str | None = None
    """Long title from the Long Title tab (e.g., ``STATE OF IOWA,
    Plaintiff-Appellee, vs. SHERRELL QUINTRAD ROBINSON, Defendant-Appellant``).
    Many older cases have an empty Long Title and this stays ``None``."""

    # === Case metadata ===
    case_type: str | None = None
    """``CRIMINAL CASE``, ``CIVIL CASE``, ``JUVENILE CASE``, etc."""

    status: str | None = None
    """Latest status string (``NOTICE OF APPEAL FILED``, ``SUBMITTED``,
    ``OPINION FILED``, ``DISPOSED``, …)."""

    citation: str | None = None
    """Reporter cite when the case has been assigned one; else ``None``.
    The Summary page renders ``"No Cite Listed"`` when absent."""

    appellate_judges: list[str] = []
    """Judges/justices listed on the Summary page (panel members or assigned
    writer). Empty when the page renders ``"No Judges Listed"``."""

    # === Trial court linkage ===
    trial_court_case_id: str | None = None
    """Originating district-court case number (e.g., ``FECR391937``)."""

    trial_court_county: str | None = None
    """Originating county (UPPERCASE, e.g., ``POLK``)."""

    trial_court_judge: str | None = None
    """Trial-court judge name from the Summary page."""

    # === Nested data ===
    entries: list[IowaDocketEntry] = []
    parties: list[IowaParty] = []

    source_url: str | None = None
    """The Summary tab URL the record was assembled from."""
