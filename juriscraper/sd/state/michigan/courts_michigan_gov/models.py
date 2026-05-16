"""Data models for the Michigan appellate courts scraper.

Supported courts:
- ``michctapp`` — Michigan Court of Appeals (case # is a bare integer)
- ``mich``     — Michigan Supreme Court    (case # is a bare integer)

The Michigan Court of Claims uses a separate ``YY-NNNNNN-XX`` numbering
scheme and is treated as a trial-level court; it is intentionally out of
scope for this scraper.
"""

from __future__ import annotations

from datetime import date

from jkent.common.data_models import ScrapedData

COURT_IDS: dict[str, str] = {
    "michctapp": "Michigan Court of Appeals",
    "mich": "Michigan Supreme Court",
}


# Site-side appellate-court name as it appears in the
# ``aAppellateCourt=`` query parameter (case-sensitive, space-separated).
SITE_COURT_NAME: dict[str, str] = {
    "michctapp": "Court Of Appeals",
    "mich": "Supreme Court",
}


class MichTrialCourtRef(ScrapedData):
    """A reference to the trial court / agency that the appeal originates from.

    A single appellate matter may have multiple lower-court rows when the
    appeal was consolidated; the listing API returns these as a flat list
    of trial-court display names.
    """

    name: str
    """Trial court display name (e.g. ``KALAMAZOO CIRCUIT COURT``)."""


class MichDocket(ScrapedData):
    """A Michigan appellate-court docket.

    One record per ``(court_id, docket_id)`` combination. Fields that are
    only present in the captcha-gated case-detail JSON (parties,
    attorneys, register-of-actions entries, judges) are not populated by
    the listing-driven flow; see ``DESIGN.md`` for context.
    """

    # === Searchable fields ===
    docket_id: str
    """Site case number (e.g. ``380502`` for COA, ``170011`` for MSC)."""

    court_id: str
    """CourtListener court id: ``michctapp`` or ``mich``."""

    date_filed: date | None = None
    """Filing date of the appellate matter."""

    case_name: str
    """Case caption / title from the listing API."""

    # === Status & metadata ===
    case_status: str | None = None
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

    coc_case_number: str | None = None
    """COC case number (``YY-NNNNNN-XX``) when linked to a Court of Claims matter."""

    # === Originating courts ===
    trial_courts: list[MichTrialCourtRef] = []
    """Trial-court / agency rows (the originating courts of the appeal)."""

    # === Source ===
    source_url: str | None = None
    """Absolute URL of the case detail page."""
