"""Data models for the Michigan appellate courts scraper.

Site: https://www.courts.michigan.gov/case-search/

Supported courts:
- ``michctapp`` — Michigan Court of Appeals (case # is a bare integer)
- ``mich``     — Michigan Supreme Court    (case # is a bare integer)

The Michigan Court of Claims uses a separate ``YY-NNNNNN-XX`` numbering
scheme and is treated as a trial-level court; it is intentionally out of
scope for this scraper (it is not in ``courts-db``).

Field names follow [`../../CL_MODELS.md`](../../CL_MODELS.md): the
CourtListener court-id string is ``court`` (not ``court_id``), the docket
number is ``docket_number`` (not ``docket_id``/``case_number``), and dates
use the ``date_*`` prefix. Free-text name fields use ``CleanString`` /
``HarmonizedCaseName`` from ``juriscraper.state.common_models``.
"""

from __future__ import annotations

from datetime import date
from typing import ClassVar

from jkent.common.data_models import ScrapedData

from juriscraper.state.common_models import CleanString, HarmonizedCaseName

# CourtListener court id → site display name (as it appears in the
# ``aAppellateCourt=`` listing query parameter, case-sensitive).
COURT_IDS: dict[str, str] = {
    "michctapp": "Michigan Court of Appeals",
    "mich": "Michigan Supreme Court",
}

# CourtListener court id → the value the site searches by in the
# ``aAppellateCourt=`` query parameter.
SITE_COURT_NAME: dict[str, str] = {
    "michctapp": "Court Of Appeals",
    "mich": "Supreme Court",
}


# =========================================================================
# Data models
# =========================================================================


class MichTrialCourtRef(ScrapedData):
    """A reference to the trial court / agency the appeal originates from.

    A single appellate matter may carry multiple lower-court rows when the
    appeal was consolidated; the listing API returns these as a flat list
    of trial-court display names. Maps loosely to CourtListener
    ``OriginatingCourtInformation`` / ``TrialCourtData``.
    """

    name: CleanString
    """Trial court display name (e.g. ``KALAMAZOO CIRCUIT COURT``)."""


class MichAttorney(ScrapedData):
    """An attorney of record on a party (from the case-detail JSON).

    Maps loosely to CourtListener ``Attorney``. ``appoint_type`` is the
    site's appointment role (e.g. ``Prosecutor``, ``Retained``); ``p_number``
    is the Michigan attorney "P-number" bar id.
    """

    name: CleanString
    p_number: int | None = None
    appoint_type: CleanString | None = None


class MichParty(ScrapedData):
    """A party to the appeal (from the case-detail JSON).

    Maps to CourtListener ``Party``. ``connections`` is the site's role
    string (e.g. ``Plaintiff - Appellee``); attorneys of record are nested.
    """

    name: HarmonizedCaseName
    number: int | None = None
    connections: CleanString | None = None
    """Role string, e.g. ``Plaintiff - Appellee``."""
    self_represented: bool | None = None
    prisoner_id: CleanString | None = None
    attorneys: list[MichAttorney] = []


class MichDocument(ScrapedData):
    """A document linked to a docket entry (opinion/order/brief PDF).

    Maps to CourtListener ``RECAPDocument``-ish. The public case-detail JSON
    exposes documents under docket entries; ``url`` is the site-relative or
    absolute link when present.
    """

    description: CleanString | None = None
    url: CleanString | None = None
    document_type: CleanString | None = None


class MichDocketEntry(ScrapedData):
    """A register-of-actions entry (from the case-detail ``dockets`` list).

    Maps to CourtListener ``DocketEntry``. Future-dated events are ordinary
    docket entries (they are not modeled as a separate scheduled-hearing
    type). ``documents`` carries any linked filings for the entry.
    """

    event_number: int | None = None
    date_event: date | None = None
    event_description: CleanString | None = None
    event_abbreviation: CleanString | None = None
    event_type: CleanString | None = None
    docket_type: CleanString | None = None
    date_service: date | None = None
    filing_attorney: CleanString | None = None
    fee_code: CleanString | None = None
    is_open: bool | None = None
    documents: list[MichDocument] = []


class MichJudgment(ScrapedData):
    """A trial-court judgment being appealed (from ``judgments``).

    Maps to CourtListener ``OriginatingCourtInformation`` detail: the trial
    court, its case number, and the judge whose ruling is on appeal.
    """

    case_type: CleanString | None = None
    trial_court_name: CleanString | None = None
    trial_court_case_number: CleanString | None = None
    trial_court_judge_name: CleanString | None = None


class MichDocket(ScrapedData):
    """A Michigan appellate-court docket — the main scraper output.

    One record per ``(court, docket_number)`` combination. Maps to
    CourtListener ``Docket``. The listing-driven flow fills the summary
    fields; the browser-captured case-detail JSON (promoted from the
    invisible-hCaptcha-gated ``get*casedetaildata`` XHR) fills the detail
    collections (parties, docket entries, judges, judgments). See
    ``CC_NOTES.md``.
    """

    # === Identity ===
    docket_number: str
    """Site case number (e.g. ``380502`` for COA, ``170011`` for MSC),
    used as the docket number. Bare integer for both appellate courts."""

    court: str
    """CourtListener court id: ``michctapp`` or ``mich``."""

    case_name: HarmonizedCaseName
    """Case caption / title from the listing API."""

    date_filed: date | None = None
    """Filing date of the appellate matter."""

    # === Status & metadata ===
    case_status: CleanString | None = None
    """Status string (e.g. ``Open``, ``Case Concluded; File Open``)."""

    has_opinions: bool | None = None
    """Whether the case has any associated opinion documents."""

    has_orders: bool | None = None
    """Whether the case has any associated order documents."""

    # === Cross-court references ===
    coa_case_number: int | None = None
    """COA case number when this docket is also linked to one."""

    msc_case_number: int | None = None
    """MSC case number when this docket is also linked to one."""

    coc_case_number: CleanString | None = None
    """Court of Claims case number (``YY-NNNNNN-XX``) when linked to a
    Court of Claims matter."""

    # === Originating courts ===
    trial_courts: list[MichTrialCourtRef] = []
    """Trial-court / agency rows (the originating courts of the appeal).
    Maps to CourtListener ``OriginatingCourtInformation``."""

    # === Provenance ===
    source_url: str | None = None
    """Absolute URL of the case detail page this record was scraped
    from."""

    source_entry_point: str | None = None
    """Entry point used to reach this docket (e.g.
    ``dockets_by_filing_date``)."""

    # === Case detail (from the captcha-gated get*casedetaildata JSON) ===
    # All default empty/None so a listing-only record validates unchanged;
    # the detail step promotes the gated XHR and fills these in.
    date_last_updated: date | None = None
    """When the site last updated the case (``caseLastUpdated``)."""

    case_types: list[CleanString] = []
    """Site case-type codes (e.g. ``CSC-1``)."""

    parties: list[MichParty] = []
    """Parties to the appeal, with nested attorneys of record."""

    docket_entries: list[MichDocketEntry] = []
    """Register-of-actions entries (CL ``DocketEntry``)."""

    judges: list[CleanString] = []
    """Judge names associated with the case."""

    judgments: list[MichJudgment] = []
    """Trial-court judgments under appeal (originating-court detail)."""

    related_coa_case_numbers: list[int] = []
    """Related Court of Appeals case numbers."""

    related_msc_case_numbers: list[int] = []
    """Related Supreme Court case numbers."""

    has_detail: bool = False
    """True when the case-detail JSON was successfully promoted and parsed."""


# =========================================================================
# Site constants
# =========================================================================

SITE_BASE: str = "https://www.courts.michigan.gov"
LISTING_PATH: str = "/case-search/"
LISTING_URL: str = f"{SITE_BASE}{LISTING_PATH}"
SINGLE_CASE_API: str = f"{SITE_BASE}/api/CaseSearch/AdvancedSearchCaseDetails"

# Maximum pageSize honoured by the listing API. Anything larger is
# silently clamped to 10 (the default).
MAX_PAGE_SIZE: int = 100


class _MichConfig:
    """Site configuration constants, kept off the public model classes."""

    SITE_BASE: ClassVar[str] = SITE_BASE
    LISTING_PATH: ClassVar[str] = LISTING_PATH
    LISTING_URL: ClassVar[str] = LISTING_URL
    SINGLE_CASE_API: ClassVar[str] = SINGLE_CASE_API
    MAX_PAGE_SIZE: ClassVar[int] = MAX_PAGE_SIZE
    COURT_IDS: ClassVar[dict[str, str]] = COURT_IDS
    SITE_COURT_NAME: ClassVar[dict[str, str]] = SITE_COURT_NAME
