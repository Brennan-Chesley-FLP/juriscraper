"""Data models for the Arizona Court of Appeals, Division Two scraper.

This site (``appeals2.az.gov/ODSPlus/``) publishes structured docket
data — parties, attorneys, filings, proceedings, decisions, mandate —
as plain HTML, *not* as PDFs. The models below mirror the on-page
structure so a single ``AzCoa2Docket`` instance carries everything
displayed on a case-detail page.

The CourtListener court ID for this court is ``arizctapp`` (shared with
Division One — distinguishable by the ``2 CA-`` docket prefix).
"""

from __future__ import annotations

from datetime import date
from typing import ClassVar

from jkent.common.data_models import ScrapedData
from pydantic import BaseModel

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
# Entry-point parameter models
# =========================================================================


class YearSearch(BaseModel):
    """Single-year filter for ``cases_by_year``.

    The site's search form accepts a four-digit year between 1990 and
    the current year. Older years return fewer results; recent years
    typically return ~700-1000 cases in a single (un-paginated) response.
    """

    year: int


class CaseId(BaseModel):
    """Direct fetch of a single case detail by its numeric ``caseID``.

    Useful for refetching a known case without going through the search
    flow (case detail pages are publicly accessible without cookies or
    captcha).
    """

    case_id: int


# =========================================================================
# Data models
# =========================================================================


class AzCoa2Attorney(ScrapedData):
    """A single attorney representing a party."""

    name: str
    firm: str | None = None
    """Firm or organisation name. ``None`` if the attorney appears
    without a firm affiliation."""
    appointment: str | None = None
    """Appointment kind: ``Appointed`` / ``Retained`` / ``Pro Bono`` /
    etc. Verbatim from the page."""


class AzCoa2Party(ScrapedData):
    """A party + the attorneys representing them."""

    name: str
    """Verbatim party name. Natural persons appear in CAPITALISED form
    (e.g. ``RAMON RODRIGUEZ``); organisations as registered."""
    role: str | None = None
    """Role on appeal: ``Appellant`` / ``Appellee`` / ``Petitioner`` /
    ``Respondent`` / etc."""
    attorneys: list[AzCoa2Attorney] = []


class AzCoa2Filing(ScrapedData):
    """One row from the Filings, Dues, and Continuances table."""

    document_type: str
    """e.g. ``Opening Brief``, ``Notice of Appeal``,
    ``Trial Court Record``."""
    document_title: str | None = None
    """Display title — sometimes verbose
    (``Appellants Opening Brief``)."""
    due_date: date | None = None
    filing_date: date | None = None
    attorney: str | None = None
    """The filer's attorney, if any. Empty for clerk filings."""
    category: str | None = None
    """``Filing`` / ``Due`` / ``Continuance``."""


class AzCoa2OralArgument(ScrapedData):
    """One row from the Calendar and Agenda Information table.

    Most cases have a single empty row in this section; cases scheduled
    for argument carry the date/time/type plus any prior request
    history.
    """

    request_due: date | None = None
    filed: date | None = None
    request_by: str | None = None
    request_result: str | None = None
    argument_date: date | None = None
    argument_time: str | None = None
    """Free text — ``2:00 p.m.`` etc."""
    argument_type: str | None = None
    """``In Court`` / ``By Telephone`` / etc."""


class AzCoa2Decision(ScrapedData):
    """One row from the Decision Information table."""

    decision_type: str | None = None
    decision_date: date | None = None
    result_type: str | None = None


class AzCoa2Proceeding(ScrapedData):
    """One row from the Proceedings (chronological master log) table."""

    proceeding_type: str
    """``Record`` / ``Briefs`` / ``All Other`` (catch-all)."""
    proceeding_date: date | None = None
    description: str
    """Free text. Judicial orders may span multiple lines preserving
    whitespace; whitespace is preserved verbatim from the source ``td``."""


class AzCoa2Docket(ScrapedData):
    """A complete Division Two case docket — main scraper output."""

    docket_number: str
    """Display form, e.g. ``2 CA-CR 2024-0280``."""

    case_id: int
    """Numeric ``caseID`` used as the URL key
    (``caseInfolast.cfm?caseID=...``). Stable across views; useful as a
    primary key."""

    court_id: str = COURT_ID

    case_type: str | None = None
    """Two-letter code: ``CR`` / ``CV`` / ``SA`` / ``CC`` / ``HC`` /
    ``JV`` / ``IC`` / ``MH``. Derived from the docket number."""

    case_year: int | None = None
    """Year component of the docket number."""

    case_name: str
    """Caption — ``STATE OF ARIZONA v. RAMON RODRIGUEZ``,
    ``IN RE THE ESTATE OF JOHN DOE``, etc."""

    department: str | None = None
    """Single-letter Court of Appeals department (``A`` / ``B``)."""

    county: str | None = None
    """Trial-court county."""

    cause_numbers: list[str] = []
    """Trial-court docket numbers — one case may consolidate several."""

    trial_judge: str | None = None
    """Free-text judge name from the case header."""

    submitted_date: date | None = None
    """``Submitted:`` date from the header — when the case was deemed
    submitted for decision."""
    at_issue_date: date | None = None
    at_issue_number: str | None = None

    # Mandate scalars
    mandate_date: date | None = None
    mandate_vacated_date: date | None = None

    # MR/PR scalars (Motion for Reconsideration / Petition for Review).
    mr_outcome: str | None = None
    mr_outcome_date: date | None = None
    pr_outcome: str | None = None
    pr_outcome_date: date | None = None

    # Nested structured data
    parties: list[AzCoa2Party] = []
    filings: list[AzCoa2Filing] = []
    oral_arguments: list[AzCoa2OralArgument] = []
    decisions: list[AzCoa2Decision] = []
    proceedings: list[AzCoa2Proceeding] = []

    source_url: str | None = None
    """Absolute URL of the case detail page this record was scraped
    from."""


# =========================================================================
# Site constants
# =========================================================================


class _AzCoa2Config:
    """Site configuration constants, kept off the public model classes."""

    BASE_URL: ClassVar[str] = "https://www.appeals2.az.gov/ODSPlus/"
    SEARCH_FORM_URL: ClassVar[str] = (
        "https://www.appeals2.az.gov/ODSPlus/caseInfo.cfm"
    )
    SEARCH_POST_URL: ClassVar[str] = (
        "https://www.appeals2.az.gov/ODSPlus/caseInfo2.cfm"
    )
    CASE_DETAIL_URL: ClassVar[str] = (
        "https://www.appeals2.az.gov/ODSPlus/caseInfolast.cfm"
    )
    CASE_TYPES: ClassVar[dict[str, str]] = CASE_TYPES
    COURT_ID: ClassVar[str] = COURT_ID
