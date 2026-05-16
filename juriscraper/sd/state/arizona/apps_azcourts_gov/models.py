"""Data models for the Arizona appellate-courts scraper.

Covers two courts on the same AppellaDockets backend at
``apps.azcourts.gov/aacc/appella/``:

- ``ariz``: Arizona Supreme Court (site code ``ASC``)
- ``arizctapp``: Arizona Court of Appeals (site code ``1CA``;
  Division One only — Division Two uses a different CMS)

The scraper publishes five top-level types:

- ``AzAppDocket``: one record per active appellate case (metadata only —
  the docket sheet itself is a PDF).
- ``AzAppDocument``: one record per archived PDF.
- ``AzAppLowerCourtCase``: one row from the Lower Court Index — a mapping
  from a lower-court case to the appellate case.
- ``AzAppPartyCase``: one row from the Party Index — a mapping from a
  party name to a case.
- ``AzAppAttorneyCase``: one row from the Attorney Index — a mapping
  from an attorney (with bar number / jurisdiction) to a case.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import ClassVar

from jkent.common.data_models import ScrapedData
from pydantic import BaseModel

# =========================================================================
# Per-court configuration
# =========================================================================
#
# CourtListener court_id → site config. ``site_id`` is the token
# AppellaDockets uses in URLs (``ASC`` vs ``1CA``). ``case_types`` maps
# the 1-2 letter case-type code to a human-readable description.

COURTS: dict[str, dict] = {
    "ariz": {
        "display_name": "Arizona Supreme Court",
        "site_id": "ASC",
        "case_types": {
            "CR": "Active Criminal cases",
            "CV": "Active Civil cases",
            "HC": "Active Habeas Corpus cases",
            "M": "Active Miscellaneous Special Action cases",
            "R": "Active Rule 28 Petition cases",
            "SB": "Active State Bar cases",
            "WC": "Active Water Case cases",
        },
    },
    "arizctapp": {
        # courts-db treats both Court of Appeals divisions as one ID.
        # This scraper only covers Division One — Division Two uses a
        # separate publicaccess CMS and is not yet wired up.
        "display_name": "Arizona Court of Appeals, Division One",
        "site_id": "1CA",
        "case_types": {
            "CC": "Active Corporation Commission cases",
            "CR": "Active Criminal cases",
            "CV": "Active Civil cases",
            "HC": "Active Habeas Corpus cases",
            "IC": "Active Industrial Commission cases",
            "JV": "Active Juvenile cases",
            "MH": "Active Mental Health cases",
            "SA": "Active Special Action cases",
            "TX": "Active Tax Appeal cases",
            "UB": "Active Unemployment Board cases",
        },
    },
}


SUPPORTED_COURT_IDS: frozenset[str] = frozenset(COURTS)


# =========================================================================
# Entry-point parameter models
# =========================================================================


class CourtParam(BaseModel):
    """Pick which appellate court to scrape.

    ``court_id`` must be a key of ``COURTS`` (currently ``ariz`` or
    ``arizctapp``).
    """

    court_id: str


class CourtCutoff(BaseModel):
    """Court-id + ``Last Updated`` cutoff for the incremental entry.

    The scraper walks the ``Last Updated``-sorted case-list pages top-down
    for ``court_id`` and stops once it sees a row at-or-before ``cutoff``.
    """

    court_id: str
    cutoff: date


# =========================================================================
# Data models
# =========================================================================


class AzAppDocket(ScrapedData):
    """An active Arizona appellate case (Supreme or Court of Appeals).

    The docket sheet itself is a PDF (see ``AzAppDocument``); this record
    only carries the metadata that appears on the case-list page.
    """

    docket_number: str
    """Display form, e.g. ``CR-26-0127-PR`` for ASC, or
    ``1 CA-CR 26-0210`` for COA1."""

    court_id: str
    """CourtListener court ID — one of ``COURTS``."""

    case_type: str
    """One of the keys of ``COURTS[court_id]['case_types']``
    (``CR``, ``CV``, etc.)."""

    case_name: str
    """Short caption from the case-list table."""

    last_updated: datetime | None = None
    """Last time the docket PDF was regenerated, from the hidden timestamp
    cell on ``stage_<COURT>_<TYPE>_update.htm``. Naive local time
    (Arizona, MST/UTC-7 year-round)."""

    pdf_url: str
    """Absolute URL to the docket-sheet PDF."""

    source_url: str | None = None
    """The case-type list page this row was scraped from."""


class AzAppDocument(ScrapedData):
    """A PDF archived from the Arizona appellate-courts site."""

    docket_number: str
    """The display-form docket number this PDF belongs to."""
    court_id: str
    document_url: str
    """Absolute URL the PDF was fetched from."""
    local_path: str | None = None
    """Filesystem path of the archived PDF, set by the kent driver."""
    source: str | None = None
    """Origin of the request: ``case_list``, ``lower_court_index``,
    ``party_index``, or ``attorney_index``."""


class AzAppLowerCourtCase(ScrapedData):
    """A row from the Lower Court Index — one lower-court case mapped to
    an Arizona appellate case."""

    court_id: str
    """The appellate court whose index this row came from."""

    lower_court_case_number: str
    """The lower court's docket number, verbatim (e.g.
    ``1 CA-CR 21-0231`` (when ASC reviews a CoA case),
    ``CR2019-001234``, ``S0700CR202300456``, etc.)."""

    lower_court_name: str
    """Section heading the row appeared under (e.g.
    ``COURT OF APPEALS, DIVISION ONE``,
    ``MARICOPA COUNTY SUPERIOR COURT``)."""

    lower_court_anchor: str | None = None
    """The HTML anchor name for the section (e.g. ``1 CA``, ``MAR``).
    Useful as a stable lower-court key when the display name varies."""

    our_docket_number: str
    """The appellate docket number this lower-court case was appealed
    to (display form)."""

    our_case_pdf_url: str
    """Absolute URL to the appellate docket PDF."""

    case_title: str


class AzAppPartyCase(ScrapedData):
    """A row from the Party Index — one party name mapped to a case."""

    court_id: str
    party_name: str
    """Verbatim from the index, including any company suffixes (``LLC``,
    ``LTD``, etc.). The index uses ``LAST, FIRST`` for natural persons
    and the legal name for organisations."""
    docket_number: str
    case_pdf_url: str
    case_title: str


class AzAppAttorneyCase(ScrapedData):
    """A row from the Attorney Index — one attorney mapped to a case."""

    court_id: str
    attorney_name: str
    """``LAST, FIRST`` form, with the trailing ``[<JURIS>-<NUM>]``
    bracket stripped."""

    bar_number: str | None = None
    """Digits from the bracket. ``None`` for attorneys whose bracket
    carries only a jurisdiction code with no number — most often
    out-of-state counsel admitted pro hac vice."""

    bar_jurisdiction: str | None = None
    """Two-letter jurisdiction code from the bracket (``AZ``, ``CA``,
    ``DC``, ``OH``, ...). ``None`` only if the bracket was malformed."""

    docket_number: str
    case_pdf_url: str
    case_title: str


# =========================================================================
# Site constants
# =========================================================================


class _AzAppConfig:
    """Site configuration constants, kept off the public model classes."""

    BASE_URL: ClassVar[str] = "https://apps.azcourts.gov/aacc/appella/"
    COURTS: ClassVar[dict[str, dict]] = COURTS
