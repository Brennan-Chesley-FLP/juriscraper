"""Data models for the New Jersey Judiciary scraper (njcourts.gov).

Supported courts:
- ``nj`` — Supreme Court of New Jersey
- ``njsuperctappdiv`` — NJ Superior Court Appellate Division

One ``NJDocket`` is emitted per ``(court_id, docket_id)`` row across all
three source pages (SCOTNJ appeals, SCAD argument schedule, SCAD briefs
from argued cases).
"""

from __future__ import annotations

from datetime import date

from jkent.common.data_models import ScrapedData

COURT_IDS: dict[str, str] = {
    "nj": "Supreme Court of New Jersey",
    "njsuperctappdiv": "New Jersey Superior Court Appellate Division",
}


class NJDocketEntry(ScrapedData):
    """A single dated event on a New Jersey appellate docket.

    On the SCOTNJ ``/courts/supreme/appeals`` page each row's right-hand
    column lists multiple events (Posted / Argued / Certification
    Granted / Opinion Filed / Amicus Motions and Briefs Due / etc.); on
    the SCAD argument-schedule page the only event is the upcoming
    sitting; on the SCAD briefs-from-argued-cases page the only event
    is ``Argued``.
    """

    date_filed: date | None = None
    description: str
    notes: str | None = None


class NJDocument(ScrapedData):
    """A document linked from a New Jersey appellate docket page.

    Captures briefs, orders, and opinions surfaced on the three source
    pages. ``local_path`` is populated by the document-archival step.
    """

    docket_id: str
    court_id: str
    document_url: str
    description: str | None = None
    date_filed: date | None = None
    local_path: str | None = None


class NJDocket(ScrapedData):
    """A New Jersey appellate court docket.

    Aggregates the data points exposed by the three public NJ Courts
    listing pages. SCOTNJ rows additionally carry ``cms_id`` (the
    six-digit internal id in the trailing parenthetical) and a
    cross-reference to the originating SCAD opinion.
    """

    docket_id: str
    """Site docket number, e.g. ``A-40-25`` (SCOTNJ), ``A-1602-24`` (SCAD)."""

    court_id: str
    """CourtListener court id: ``nj`` or ``njsuperctappdiv``."""

    case_name: str
    """Case caption."""

    date_filed: date | None = None
    """Earliest event date for the docket (e.g. Posted / Certification Granted)."""

    cms_id: str | None = None
    """SCOTNJ-only internal CMS id (six digits in the trailing parenthetical)."""

    question_presented: str | None = None
    """The issue paragraph (SCOTNJ only)."""

    appellate_docket_id: str | None = None
    """Originating SCAD docket id when SCOTNJ links to ``Read Appellate Opinion``."""

    appellate_opinion_url: str | None = None
    """Absolute URL to the originating SCAD opinion PDF (SCOTNJ rows only)."""

    argument_date: date | None = None
    """Scheduled or completed oral argument date."""

    argument_location: str | None = None
    """Courtroom / venue label for upcoming SCAD oral arguments."""

    missing_entries_reason: str | None = None
    """Why brief documents are absent: ``RECORD IMPOUNDED`` (SCAD) or
    ``Briefs are sealed`` (SCOTNJ). ``None`` when documents are public."""

    entries: list[NJDocketEntry] = []
    """All event rows for this docket."""

    documents: list[NJDocument] = []
    """All briefs / orders / opinions referenced from the docket row."""

    source_url: str | None = None
    """Absolute URL of the listing page that the row was scraped from."""
