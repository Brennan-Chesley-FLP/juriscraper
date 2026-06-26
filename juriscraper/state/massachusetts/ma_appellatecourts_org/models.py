"""Data models for the Massachusetts Appellate Courts scraper.

The site at https://www.ma-appellatecourts.org covers two CourtListener
courts:

- ``mass``       — Supreme Judicial Court of Massachusetts
- ``massappct``  — Massachusetts Appeals Court

Each case-type category on the site (SJC Full Court, SJC Single Justice,
SJC Original Entry, SJC DAR/FAR Applications, SJC Bar Docket, Appeals
Court Panel, Appeals Court Single Justice) has its own docket-number
format but shares a common case-detail page layout, so a single
``MaDocket`` model captures every variant.

Field names follow [`../../CL_MODELS.md`](../../CL_MODELS.md): the
CourtListener court-id string is ``court`` (not ``court_id``), the docket
number is ``docket_number`` (not ``docket_id``), and dates use the
``date_*`` prefix. ``CleanString``/``HarmonizedCaseName`` come from
``juriscraper.state.common_models``.
"""

from __future__ import annotations

from datetime import date

from jkent.common.data_models import ScrapedData

from juriscraper.state.common_models import CleanString, HarmonizedCaseName

# CourtListener court IDs.
COURT_SJC = "mass"
COURT_APPEALS = "massappct"

COURT_IDS: dict[str, str] = {
    COURT_SJC: "Supreme Judicial Court of Massachusetts",
    COURT_APPEALS: "Massachusetts Appeals Court",
}

# Site internal ``doc_doctp`` value → display name. The first column of
# each entry is what the site uses on the search form's Case Type
# dropdown; we mirror them so the scraper can be configured by category.
CASE_TYPE_NAMES: dict[str, str] = {
    "fc": "SJC Full Court Cases",
    "sj": "SJC Single Justice Cases",
    "oe": "SJC Original Entry Cases",
    "ar": "SJC DAR and FAR Applications",
    "bd": "SJC Bar Docket Cases",
    "ac": "Appeals Court Panel Cases",
    "aj": "Appeals Court Single Justice Cases",
}

# Calendar URL fragments. Each calendar page lists oral arguments
# scheduled for the *current month only*.
CALENDAR_TYPES: dict[str, str] = {
    "fc": "SJC Full Court Sitting List",
    "sj": "SJC Single Justice Sitting List",
    "ac": "Appeals Court Panel Sitting List",
    "aj": "Appeals Court Single Justice Sitting List",
}

# Site constants.
BASE_URL: str = "https://www.ma-appellatecourts.org"
DOCKET_URL: str = f"{BASE_URL}/docket"


class MaAttorney(ScrapedData):
    """A single attorney appearance on a party.

    Attorneys are listed under each party on the case-detail page. A
    "- Withdrawn" suffix on the name surface indicates the attorney has
    withdrawn from the case. Maps to CourtListener ``Attorney`` (+
    ``Role`` for the per-docket linkage)."""

    name: CleanString
    """Full attorney name as displayed (without the trailing role)."""

    title: CleanString | None = None
    """Honorific or role suffix, e.g. ``Esquire``, ``A.D.A.``."""

    withdrawn: bool = False
    """True if the surface text included the ``- Withdrawn`` marker."""

    attorney_url: str | None = None
    """Absolute URL to the attorney's profile page (``/attorney/{id}``)."""

    attorney_id: str | None = None
    """Site-internal numeric attorney ID, parsed from ``attorney_url``."""


class MaParty(ScrapedData):
    """A party (or other interested participant) in the case.

    Maps to CourtListener ``Party`` (+ ``PartyType`` for the role on this
    docket)."""

    name: CleanString
    """The party's name as displayed."""

    role: CleanString | None = None
    """Role text, e.g. ``Plaintiff/Appellant``, ``Pro Se Defendant``,
    ``Other interested party`` (CL ``PartyType.name``)."""

    brief_status: CleanString | None = None
    """Free-text brief-status indicator (e.g. ``Blue brief filed``)."""

    enlargement_summary: CleanString | None = None
    """Optional summary of motion enlargements (e.g. ``2 Enls, 79 Days``)."""

    attorneys: list[MaAttorney] = []
    """Attorneys representing the party."""


class MaDocketEntry(ScrapedData):
    """A row from the DOCKET ENTRIES table on the case-detail page.

    Maps to CourtListener ``DocketEntry``."""

    date_filed: date | None = None
    """Date of the entry (``MM/DD/YYYY`` on the page)."""

    paper_number: CleanString | None = None
    """Paper number, e.g. ``#5``. Empty for clerk notations."""

    description: str
    """Free-text description of the entry."""


class MaScheduledHearing(ScrapedData):
    """A row from the FUTURE CALENDAR block on a case-detail page.

    Distinct from ``MaOralArgument`` (which is a top-level record yielded
    from the calendar pages); this one is embedded inside ``MaDocket``
    when the case is scheduled. Maps loosely to a future ``DocketEntry``.
    """

    scheduled_for: CleanString | None = None
    """Date + time text exactly as displayed (e.g. ``Monday, May 4th 2026, 9:00 AM``)."""

    presiding: CleanString | None = None
    """Presiding panel string."""

    location: CleanString | None = None
    """Courthouse / room (e.g. ``John Adams Courthouse, Rm 1``)."""


class MaDocument(ScrapedData):
    """A downloadable document (PDF) referenced from a case-detail page.

    Yielded as a separate top-level record so it can be archived
    independently. The ``docket_number`` field joins back to the parent
    ``MaDocket``. Maps to CourtListener ``RECAPDocument``.
    """

    docket_number: str
    """The case's docket number (e.g. ``SJC-13231``)."""

    court: str
    """CourtListener court id: ``mass`` or ``massappct``."""

    description: CleanString | None = None
    """Label as displayed (e.g. ``Appellant Smith Brief``)."""

    document_url: str
    """Absolute URL the PDF was downloaded from."""

    local_path: str | None = None
    """Filesystem path the driver archived the file to."""


class MaDocket(ScrapedData):
    """A complete appellate-court docket from ma-appellatecourts.org.

    Maps to CourtListener ``Docket`` (+ its per-court side tables)."""

    # ── Searchable / required ──────────────────────────────────────────
    docket_number: str
    """Site docket number, e.g. ``SJC-13231``, ``2025-P-1256``,
    ``SJ-2025-0518``, ``FAR-30715``, ``OE-0157``, ``BD-2025-004``."""

    court: str
    """CourtListener court id: ``mass`` (SJC) or ``massappct`` (Appeals
    Court)."""

    case_name: HarmonizedCaseName
    """Caption as displayed on the detail page."""

    date_filed: date | None = None
    """Mapped from the ``Entry Date`` field in the case header."""

    # ── Category / classification ──────────────────────────────────────
    case_category: CleanString | None = None
    """Site case-type category — one of ``CASE_TYPE_NAMES`` values
    (e.g. ``SJC Full Court Cases``)."""

    case_type: CleanString | None = None
    """Civil / Criminal classification from the case header."""

    nature: CleanString | None = None
    """Nature-of-case text (e.g. ``Equity``, ``Murder1 appeal``)."""

    appellant: CleanString | None = None
    """Which side is the appellant (``Plaintiff``, ``Defendant``, ...)."""

    applicant: CleanString | None = None
    """For DAR/FAR applications: which side filed the application."""

    is_impounded: bool = False
    """True if the page advertises impounded material/PID."""

    # ── Status / dates ─────────────────────────────────────────────────
    case_status: CleanString | None = None
    """Case-status text (e.g. ``Decided, Rescript issued``, ``FAR denied``)."""

    date_status: date | None = None
    """Date associated with ``case_status``."""

    brief_status: CleanString | None = None
    """Header brief-status text."""

    brief_due: CleanString | None = None
    """Header brief-due text (often a date string, sometimes free text)."""

    date_argued: date | None = None
    """Argument date (``Argued Date`` / ``Arg/Submitted``)."""

    date_decision: date | None = None
    """Decision date."""

    date_response: date | None = None
    """For DAR/FAR applications: date the response is due."""

    # ── Panel / quorum ─────────────────────────────────────────────────
    panel_str: CleanString | None = None
    """Appeals Court panel string (when applicable; CL ``panel_str``)."""

    quorum: CleanString | None = None
    """SJC quorum string (when applicable)."""

    # ── Cross-references between case-type categories ──────────────────
    citation: CleanString | None = None
    """Reporter citation (e.g. ``492 Mass. 604``)."""

    sjc_number: CleanString | None = None
    """SJC docket number, when this case is the related Appeals Court
    or DAR/FAR application."""

    appeals_court_number: CleanString | None = None
    """Appeals Court number, when this case is the related SJC matter."""

    sj_number: CleanString | None = None
    """Single Justice number, when this case has a related SJ filing."""

    far_number: CleanString | None = None
    """FAR number, when this case has a related FAR application."""

    full_court_number: CleanString | None = None
    """Full Court number, when this case is an OE or DAR/FAR with one."""

    route_to_sjc: CleanString | None = None
    """How the case reached the SJC (e.g. ``Direct Entry: Murder 1``)."""

    # ── Lower court (CL OriginatingCourtInformation) ───────────────────
    appeal_from_str: CleanString | None = None
    """Lower court name (e.g. ``Worcester Superior Court``); CL
    ``appeal_from_str``."""

    lower_court_number: CleanString | None = None
    """Trial court / agency case number (CL lower-court ``docket_number``)."""

    lower_court_judge: CleanString | None = None
    """Lower court judge name (CL lower-court ``assigned_to_str``)."""

    date_lower_court_entry: date | None = None
    """Date the lower court rendered its judgment / decision."""

    # ── Free-text and aggregates ───────────────────────────────────────
    additional_information: CleanString | None = None
    """Free-text ADDITIONAL INFORMATION block, when present."""

    parties: list[MaParty] = []
    """Parties (and their attorneys)."""

    entries: list[MaDocketEntry] = []
    """Rows from the DOCKET ENTRIES table."""

    scheduled_hearings: list[MaScheduledHearing] = []
    """FUTURE CALENDAR rows, when the case is scheduled."""

    document_urls: list[str] = []
    """URLs of the PDFs listed in the DOCUMENTS block. Each is also
    yielded as a separate ``MaDocument`` for archiving."""

    source_url: str | None = None
    """The case-detail URL the data was fetched from."""

    source_entry_point: str | None = None
    """Entry point used to reach this docket (e.g. ``dockets_by_number``)."""


class MaOralArgumentCase(ScrapedData):
    """A single case scheduled within an oral-argument session."""

    docket_number: str
    """Docket number link as listed on the calendar page."""

    case_name: HarmonizedCaseName
    """Caption as listed on the calendar page (may be ``IMPOUNDED CASE``)."""


class MaOralArgument(ScrapedData):
    """An oral-argument session from a calendar page.

    Calendar pages (``/calendar/{fc,sj,ac,aj}``) list the *current
    month's* sittings only. Each session aggregates one or more
    scheduled cases under a single date, time, panel, and location.
    """

    court: str
    """``mass`` for SJC calendars (fc, sj), ``massappct`` for Appeals
    Court calendars (ac, aj)."""

    calendar_type: str
    """``fc``, ``sj``, ``ac``, or ``aj``."""

    date_argued: date | None = None
    """Date of the sitting (parsed from the heading)."""

    session_time: CleanString | None = None
    """Time-of-day text (e.g. ``9:00 AM``)."""

    location: CleanString | None = None
    """Courthouse / room string."""

    presiding: CleanString | None = None
    """Presiding panel / quorum string."""

    cases: list[MaOralArgumentCase] = []
    """Cases scheduled in this session."""

    source_url: str | None = None
    """The calendar URL the data was fetched from."""

    source_entry_point: str | None = None
    """Entry point used to reach this session (``oral_arguments_by_bulk``)."""
