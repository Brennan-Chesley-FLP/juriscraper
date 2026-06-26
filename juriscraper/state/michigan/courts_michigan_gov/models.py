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


class MichDocket(ScrapedData):
    """A Michigan appellate-court docket — the main scraper output.

    One record per ``(court, docket_number)`` combination. Maps to
    CourtListener ``Docket``. Fields that are only present in the
    captcha-gated case-detail JSON (parties, attorneys,
    register-of-actions entries, judges) are not populated by the
    listing-driven flow; see ``CC_NOTES.md`` for context.
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
