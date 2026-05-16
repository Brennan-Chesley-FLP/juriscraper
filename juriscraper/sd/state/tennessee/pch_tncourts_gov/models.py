"""Data models for the Tennessee Public Case History scraper.

One site, three courts, distinguished by case-number suffix:

- ``tenn``         — Tennessee Supreme Court              (suffix ``SC``)
- ``tennctapp``    — Tennessee Court of Appeals           (suffix ``COA``)
- ``tenncrimapp``  — Tennessee Court of Criminal Appeals  (suffix ``CCA``)
"""

from __future__ import annotations

from datetime import date
from typing import ClassVar

from jkent.common.data_models import ScrapedData

COURT_IDS: ClassVar[dict[str, str]] = {
    "tenn": "Tennessee Supreme Court",
    "tennctapp": "Tennessee Court of Appeals",
    "tenncrimapp": "Tennessee Court of Criminal Appeals",
}


class TnMilestone(ScrapedData):
    """A row from the Case Milestones table.

    Standard descriptions: Application Filed, Application Disposition,
    Record Filed, Appellant(s)/Appellee(s) Briefing Complete, Oral
    Argument/Submission, Decision Date, Decision Type, Disposition,
    Panel, Closed Date.
    """

    description: str
    milestone_date: date | None = None


class TnParty(ScrapedData):
    """A row from the Parties table on the case-detail page."""

    name: str
    role: str | None = None
    counsel: str | None = None


class TnRecordEntry(ScrapedData):
    """A row from the Record Information table on the case-detail page."""

    volume_type: str
    volumes: str | None = None
    record_type: str | None = None


class TnDocketEntry(ScrapedData):
    """A row from the Case History table (the docket / register of actions)."""

    date_filed: date | None = None
    event: str
    filer: str | None = None
    document_url: str | None = None
    """Postback target path for the PDF, if one is attached.

    Stored as the inner ``__doPostBack`` argument
    (e.g. ``ListView10$ctrl2$ListView12$ctrl0$LinkButton1``) — not a real
    URL. The PDF body is retrieved by re-POSTing the case-detail page with
    this value as ``__EVENTTARGET``."""
    local_path: str | None = None


class TnDocument(ScrapedData):
    """An archived PDF from a docket-history row.

    Yielded as a separate top-level record so it can be joined back to its
    parent docket via ``case_number`` and to the originating row via
    ``event_index``.
    """

    case_number: str
    """Full appeal number (e.g., 'M2013-02744-SC-R11-CD')."""

    court_id: str
    """One of ``tenn``, ``tennctapp``, ``tenncrimapp``."""

    event_index: int | None = None
    """Index of the docket-history row this document came from (0-based)."""

    event: str | None = None
    """Event description from the docket-history row."""

    document_url: str | None = None
    """The case-detail URL the PDF was downloaded from (the postback target
    is identified by ``__EVENTTARGET``, but the URL itself is the case
    detail page)."""

    local_path: str | None = None
    """Filesystem path where the driver archived this document."""


class TnDocket(ScrapedData):
    """A complete appellate case docket from pch.tncourts.gov.

    A single sequence-number search returns rows from any combination of the
    three Tennessee appellate courts; ``court_id`` is derived from the
    third dash-separated segment of ``case_number``.
    """

    # === Searchable fields ===
    case_number: str
    """Full appeal number, e.g. ``M2013-02744-SC-R11-CD``."""

    court_id: str
    """``tenn``, ``tennctapp``, or ``tenncrimapp`` — derived from the
    ``SC``/``COA``/``CCA`` segment of the case number."""

    date_filed: date | None = None
    """Application/Record-filed date from the Case Milestones table, when
    available."""

    case_name: str
    """Case style/caption, e.g. ``State of Tennessee v. Michael Crockett``."""

    # === Identifiers ===
    internal_case_id: str | None = None
    """C-Track MastCastID (numeric) — the ``id=`` URL parameter on
    ``CaseDetails.aspx``."""

    # === Case Overview fields ===
    intermediate_case_number: str | None = None
    """The ``Inter. Case No.`` field — the underlying intermediate-court
    case number when this is a Supreme Court application/review."""

    trial_court: str | None = None
    """Trial court name and division, e.g. ``Rutherford County Circuit
    Court (CIVIL)``."""

    trial_court_judge: str | None = None
    """Judge name as ``Last, First``."""

    trial_court_number: str | None = None
    """Trial-court case number, e.g. ``F70116``."""

    # === Closure ===
    date_closed: date | None = None
    """``Closed Date`` milestone, if present."""

    decision_date: date | None = None
    """``Decision Date`` milestone, if present."""

    disposition: str | None = None
    """``Disposition`` milestone value, if present."""

    decision_type: str | None = None
    """``Decision Type`` milestone value, if present."""

    panel: str | None = None
    """``Panel`` milestone value, if present."""

    # === Nested data ===
    milestones: list[TnMilestone] = []
    parties: list[TnParty] = []
    entries: list[TnDocketEntry] = []
    record_info: list[TnRecordEntry] = []

    # === Source ===
    source_url: str | None = None
    """URL of the case-detail page this docket was scraped from."""
