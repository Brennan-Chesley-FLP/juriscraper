"""Data models for the New Jersey Judiciary scraper (njcourts.gov).

The NJ Courts site (``njcourts.gov``) publishes appellate docket data as
plain server-rendered HTML across three public listing pages — the
Supreme Court appeals list, the Appellate Division argument schedule, and
the Appellate Division briefs-from-argued-cases list. The models below
mirror that on-page structure: one :class:`NJDocket` per case row, with
nested event (:class:`NJDocketEntry`) and document (:class:`NJDocument`)
records.

Supported courts:

- ``nj`` — Supreme Court of New Jersey (SCOTNJ).
- ``njsuperctappdiv`` — NJ Superior Court Appellate Division (SCAD).

Field names follow [`../../CL_MODELS.md`](../../CL_MODELS.md): the
CourtListener court-id string is ``court`` (not ``court_id``), the docket
identifier is ``docket_number`` (not ``case_number``), and dates use the
``date_*`` prefix.
"""

from __future__ import annotations

from datetime import date

from jkent.common.data_models import ScrapedData

from juriscraper.state.common_models import CleanString, HarmonizedCaseName

COURT_IDS: dict[str, str] = {
    "nj": "Supreme Court of New Jersey",
    "njsuperctappdiv": "New Jersey Superior Court Appellate Division",
}


class NJDocketEntry(ScrapedData):
    """A single dated event on a New Jersey appellate docket.

    Maps to CourtListener ``DocketEntry``. On the SCOTNJ
    ``/courts/supreme/appeals`` page each row's right-hand column lists
    multiple events (Posted / Argued / Certification Granted / Opinion
    Filed / Amicus Motions and Briefs Due / etc.); on the SCAD
    argument-schedule page the only event is the upcoming sitting; on the
    SCAD briefs-from-argued-cases page the only event is ``Argued``.
    """

    description: CleanString
    """Event name, e.g. ``Posted``, ``Argued``, ``Opinion Filed``."""
    date_filed: date | None = None
    """The event date, when the right-hand value parses as a date."""
    notes: CleanString | None = None
    """The right-hand value when it is not a date (e.g. an argument
    location), preserved verbatim."""


class NJDocument(ScrapedData):
    """A document linked from a New Jersey appellate docket page.

    Maps to CourtListener ``RECAPDocument``. Captures briefs, orders,
    opinions, and oral-argument media surfaced on the three source pages.
    ``filepath_local`` is populated by the document-archival step.
    """

    docket_number: str
    """The docket number of the parent :class:`NJDocket` (join key)."""
    court: str
    """CourtListener court id: ``nj`` or ``njsuperctappdiv``."""
    document_url: str
    """Absolute URL the document was downloaded from."""
    description: CleanString | None = None
    """Short link/label text (e.g. ``Brief``, ``Oral Argument Video``)."""
    date_filed: date | None = None
    """Filed date, when known from the parent row."""
    filepath_local: str | None = None
    """Local path of the archived file, set by ``handle_document_download``."""


class NJDocket(ScrapedData):
    """A New Jersey appellate court docket — the main scraper output.

    Maps to CourtListener ``Docket`` (+ its per-court side tables).
    Aggregates the data points exposed by the three public NJ Courts
    listing pages. SCOTNJ rows additionally carry ``cms_id`` (the
    six-digit internal id in the trailing parenthetical) and a
    cross-reference to the originating SCAD opinion.
    """

    docket_number: str
    """Site docket number, e.g. ``A-40-25`` (SCOTNJ), ``A-1602-24`` (SCAD)."""

    court: str
    """CourtListener court id: ``nj`` or ``njsuperctappdiv``."""

    case_name: HarmonizedCaseName
    """Case caption."""

    date_filed: date | None = None
    """Earliest event date for the docket (e.g. Posted / Certification
    Granted)."""

    cms_id: CleanString | None = None
    """SCOTNJ-only internal CMS id (six digits in the trailing
    parenthetical)."""

    question_presented: CleanString | None = None
    """The issue paragraph (SCOTNJ only)."""

    appellate_docket_number: CleanString | None = None
    """Originating SCAD docket number when SCOTNJ links to ``Read
    Appellate Opinion`` (CL ``OriginatingCourtInformation.docket_number``)."""

    appellate_opinion_url: CleanString | None = None
    """Absolute URL to the originating SCAD opinion PDF (SCOTNJ rows only)."""

    date_argued: date | None = None
    """Scheduled or completed oral-argument date (CL ``Docket.date_argued``)."""

    argument_location: CleanString | None = None
    """Courtroom / venue label for upcoming SCAD oral arguments."""

    missing_entries_reason: CleanString | None = None
    """Why brief documents are absent: ``RECORD IMPOUNDED`` (SCAD) or
    ``Briefs are sealed`` (SCOTNJ). ``None`` when documents are public."""

    entries: list[NJDocketEntry] = []
    """All event rows for this docket."""

    documents: list[NJDocument] = []
    """All briefs / orders / opinions referenced from the docket row."""

    source_url: str | None = None
    """Absolute URL of the listing page that the row was scraped from."""

    source_entry_point: str | None = None
    """Entry point used to reach this docket (e.g.
    ``dockets_by_posted_date``)."""


# =========================================================================
# Site constants
# =========================================================================

BASE_URL: str = "https://www.njcourts.gov"
SCOTNJ_LISTING_URL: str = f"{BASE_URL}/courts/supreme/appeals"
SCAD_ARGUMENT_SCHEDULE_URL: str = (
    f"{BASE_URL}/courts/appellate/argument-schedule"
)
SCAD_ARGUED_LISTING_URL: str = (
    f"{BASE_URL}/courts/appellate/briefs-from-argued-cases"
)
