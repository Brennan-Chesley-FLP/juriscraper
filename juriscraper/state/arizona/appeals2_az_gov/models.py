"""Data models for the Arizona Court of Appeals, Division Two scraper.

This site (``appeals2.az.gov/ODSPlus/``) publishes structured docket
data — parties, attorneys, filings, proceedings, decisions, mandate —
as plain HTML, *not* as PDFs. The models below mirror the on-page
structure so a single ``AzCoa2Docket`` instance carries everything
displayed on a case-detail page.

The CourtListener court ID for this court is ``arizctapp`` (shared with
Division One — distinguishable by the ``2 CA-`` docket prefix).

Field names follow [`../../CL_MODELS.md`](../../CL_MODELS.md): the
CourtListener court-id string is ``court`` (not ``court_id``), and dates
use the ``date_*`` prefix.
"""

from __future__ import annotations

from datetime import date
from typing import ClassVar

from jkent.common.data_models import ScrapedData

from juriscraper.state.common_models import CleanString, HarmonizedCaseName

COURT_ID: str = "arizctapp"
COURT_NAME: str = "Arizona Court of Appeals, Division Two"


# Case-type code → human description, from the search form.
CASE_TYPES: dict[str, str] = {
    "CR": "Criminal",
    "CV": "Civil",
    "SA": "Special Action",
    "CC": "Corporation Commission",
    "HC": "Habeas Corpus",
    "JV": "Juvenile",
    "IC": "Industrial Commission",
    "MH": "Mental Health",
}


# =========================================================================
# Data models
# =========================================================================


class AzCoa2Attorney(ScrapedData):
    """A single attorney representing a party.

    Maps to CourtListener ``Attorney`` (+ ``AttorneyOrganization`` for
    the firm)."""

    name: CleanString
    firm: CleanString | None = None
    """Firm or organisation name. ``None`` if the attorney appears
    without a firm affiliation."""
    appointment: CleanString | None = None
    """Appointment kind: ``Appointed`` / ``Retained`` / ``Pro Bono`` /
    etc. Verbatim from the page."""


class AzCoa2Party(ScrapedData):
    """A party + the attorneys representing them.

    Maps to CourtListener ``Party`` (+ ``PartyType`` for the role on
    this docket)."""

    name: CleanString
    """Verbatim party name. Natural persons appear in CAPITALISED form
    (e.g. ``RAMON RODRIGUEZ``); organisations as registered."""
    role: CleanString | None = None
    """Role on appeal: ``Appellant`` / ``Appellee`` / ``Petitioner`` /
    ``Respondent`` / etc. (CL ``PartyType.name``)."""
    attorneys: list[AzCoa2Attorney] = []


class AzCoa2Filing(ScrapedData):
    """One row from the Filings, Dues, and Continuances table.

    Maps loosely to CourtListener ``DocketEntry``."""

    document_type: CleanString
    """e.g. ``Opening Brief``, ``Notice of Appeal``,
    ``Trial Court Record``."""
    document_title: CleanString | None = None
    """Display title — sometimes verbose
    (``Appellants Opening Brief``)."""
    date_due: date | None = None
    date_filed: date | None = None
    attorney: CleanString | None = None
    """The filer's attorney, if any. Empty for clerk filings."""
    category: CleanString | None = None
    """``Filing`` / ``Due`` / ``Continuance``."""


class AzCoa2OralArgument(ScrapedData):
    """One row from the Calendar and Agenda Information table.

    Most cases have a single empty row in this section; cases scheduled
    for argument carry the date/time/type plus any prior request
    history.
    """

    date_request_due: date | None = None
    date_filed: date | None = None
    request_by: CleanString | None = None
    request_result: CleanString | None = None
    date_argument: date | None = None
    argument_time: CleanString | None = None
    """Free text — ``2:00 p.m.`` etc."""
    argument_type: CleanString | None = None
    """``In Court`` / ``By Telephone`` / etc."""


class AzCoa2Decision(ScrapedData):
    """One row from the Decision Information table."""

    decision_type: CleanString | None = None
    date_decision: date | None = None
    result_type: CleanString | None = None


class AzCoa2Proceeding(ScrapedData):
    """One row from the Proceedings (chronological master log) table.

    Maps loosely to CourtListener ``DocketEntry``."""

    proceeding_type: CleanString
    """``Record`` / ``Briefs`` / ``All Other`` (catch-all)."""
    date_proceeding: date | None = None
    description: str
    """Free text. Judicial orders may span multiple lines preserving
    whitespace; whitespace is preserved verbatim from the source ``td``."""


class AzCoa2Docket(ScrapedData):
    """A complete Division Two case docket — main scraper output.

    Maps to CourtListener ``Docket`` (+ its per-court side tables)."""

    docket_number: str
    """Display form, e.g. ``2 CA-CR 2024-0280``."""

    case_id: int
    """Numeric ``caseID`` used as the URL key
    (``caseInfolast.cfm?caseID=...``). Stable across views; useful as a
    primary key."""

    court: str = COURT_ID
    """CourtListener court ID (``arizctapp``)."""

    case_type: CleanString | None = None
    """Two-letter code: ``CR`` / ``CV`` / ``SA`` / ``CC`` / ``HC`` /
    ``JV`` / ``IC`` / ``MH``. Derived from the docket number."""

    case_year: int | None = None
    """Year component of the docket number."""

    case_subtype: CleanString | None = None
    """Trailing proceeding-type code on the docket number, when present:
    ``PR`` (petition for review), ``FC`` (family court), ``S``, etc.
    e.g. the ``PR`` in ``2 CA-CR 2026-0130-PR``. Derived from the docket
    number; ``None`` for plain dockets like ``2 CA-CC 2026-0002``."""

    case_name: HarmonizedCaseName
    """Caption — ``STATE OF ARIZONA v. RAMON RODRIGUEZ``,
    ``IN RE THE ESTATE OF JOHN DOE``, etc."""

    department: CleanString | None = None
    """Single-letter Court of Appeals department (``A`` / ``B``)."""

    county: CleanString | None = None
    """Trial-court county."""

    cause_numbers: list[str] = []
    """Trial-court docket numbers — one case may consolidate several."""

    assigned_to_str: CleanString | None = None
    """Free-text trial judge name from the case header (CL
    ``assigned_to_str``)."""

    date_submitted: date | None = None
    """``Submitted:`` date from the header — when the case was deemed
    submitted for decision."""
    date_at_issue: date | None = None
    at_issue_number: CleanString | None = None

    # Mandate scalars
    date_mandate: date | None = None
    date_mandate_vacated: date | None = None

    # MR/PR scalars (Motion for Reconsideration / Petition for Review).
    mr_outcome: CleanString | None = None
    date_mr_outcome: date | None = None
    pr_outcome: CleanString | None = None
    date_pr_outcome: date | None = None

    # Nested structured data
    parties: list[AzCoa2Party] = []
    filings: list[AzCoa2Filing] = []
    oral_arguments: list[AzCoa2OralArgument] = []
    decisions: list[AzCoa2Decision] = []
    proceedings: list[AzCoa2Proceeding] = []

    source_url: str | None = None
    """Absolute URL of the case detail page this record was scraped
    from."""

    source_entry_point: str | None = None
    """Entry point used to reach this docket (e.g.
    ``dockets_by_bulk``)."""


# =========================================================================
# Site constants
# =========================================================================

BASE_URL: str = "https://www.appeals2.az.gov/ODSPlus/"
SEARCH_FORM_URL: str = "https://www.appeals2.az.gov/ODSPlus/caseInfo.cfm"
SEARCH_POST_URL: str = "https://www.appeals2.az.gov/ODSPlus/caseInfo2.cfm"
CASE_DETAIL_URL: str = "https://www.appeals2.az.gov/ODSPlus/caseInfolast.cfm"


class _AzCoa2Config:
    """Site configuration constants, kept off the public model classes."""

    BASE_URL: ClassVar[str] = BASE_URL
    SEARCH_FORM_URL: ClassVar[str] = SEARCH_FORM_URL
    SEARCH_POST_URL: ClassVar[str] = SEARCH_POST_URL
    CASE_DETAIL_URL: ClassVar[str] = CASE_DETAIL_URL
    CASE_TYPES: ClassVar[dict[str, str]] = CASE_TYPES
    COURT_ID: ClassVar[str] = COURT_ID
