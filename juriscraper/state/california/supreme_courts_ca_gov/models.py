"""Data models for the California Supreme Court briefs scraper.

``supreme.courts.ca.gov/case-information/briefs-argued-cases`` publishes the
briefs filed in every case the Supreme Court has heard oral argument in since
2010, grouped by the *oral argument session* they were argued in. One index
page lists every session (2010 → the current year); each session page lists
its cases, and under each case the PDF of every brief filed in it.

This is a different data source from
:mod:`juriscraper.state.california.appellatecases_courtinfo_ca_gov`, which
scrapes the docket (including a Briefs *tab* naming each brief and its filing
party) but links no brief files. The two join on ``docket_number`` + ``court``:
this scraper is where the brief PDFs themselves come from.
"""

from __future__ import annotations

from datetime import date
from enum import Enum

from jkent.common.data_models import ScrapedData

from juriscraper.state.common_models import CleanString, HarmonizedCaseName

BASE_URL = "https://supreme.courts.ca.gov"
BRIEFS_INDEX_URL = f"{BASE_URL}/case-information/briefs-argued-cases"

#: Earliest oral-argument session the index carries. The page states its own
#: scope: "Briefs filed in cases argued since 2010 are available for download."
MIN_YEAR = 2010

# Court ID mapping: CourtListener ID → display name.
#
# The site is the Supreme Court's, and 1,280 of the 1,284 case blocks in the
# 2010-2026 corpus carry an ``S``-prefixed Supreme Court number. The exception
# is the September 7-8 2010 session, which lists three ``C``-prefixed Third
# District cases whose briefs the court incorporated into S183411 by order --
# so a Court of Appeal number does occur, and ``court`` is derived per record
# from the number's prefix rather than assumed.
COURT_IDS: dict[str, str] = {
    "cal": "California Supreme Court",
    "calctapp_3rd": "California Court of Appeal, Third Appellate District",
}

# California appellate case-number prefix → CourtListener court id. Mirrors
# ``COURT_CONFIG`` in the sibling ``appellatecases_courtinfo_ca_gov`` scraper
# (kept local so this package stands alone); only ``S`` and ``C`` have been
# observed here, the rest are listed so a future Court of Appeal number
# resolves instead of failing.
DOCKET_PREFIX_COURTS: dict[str, str] = {
    "S": "cal",
    "A": "calctapp_1st",
    "B": "calctapp_2nd",
    "C": "calctapp_3rd",
    "D": "calctapp_4th_div1",
    "E": "calctapp_4th_div2",
    "G": "calctapp_4th_div3",
    "F": "calctapp_5th",
    "H": "calctapp_6th",
}


class CalSupremeSessionType(str, Enum):
    """What kind of oral argument session the briefs were listed under.

    Read off the session title, which names the two irregular kinds
    explicitly; a title that names neither is a regular calendar session.
    """

    REGULAR = "regular"
    """An ordinary monthly calendar session in San Francisco, Los Angeles or
    Sacramento."""

    SPECIAL = "special"
    """A session the court titled "Special Session"."""

    OUTREACH = "outreach"
    """A session the court titled "Outreach Session" -- argument held at a
    school or civic venue as a public-education program."""


class CalSupremeArgumentSession(ScrapedData):
    """One oral argument session listed on the briefs index.

    The court's own calendar of argument sessions, 2010 to the present, as the
    briefs index states it. Emitted alongside the cases so a run records which
    sessions it saw (and which it filtered out has a visible complement).
    """

    court: str
    """CourtListener court id of the court holding the session -- always
    ``"cal"``."""

    session_title: CleanString
    """Verbatim session title (e.g. ``"May 6 and 7, 2025 Oral Argument
    Cases"``)."""

    date_session_start: date
    """First day of the session, parsed from the title."""

    date_session_end: date
    """Last day of the session; equal to ``date_session_start`` for the 103 of
    191 sessions the court held on a single day."""

    session_type: CalSupremeSessionType
    """Regular, Special or Outreach -- see :class:`CalSupremeSessionType`."""

    source_url: str
    """URL of the session's own briefs page."""


class CalSupremeBrief(ScrapedData):
    """A single brief (or letter, motion, or notice) filed in a case.

    Maps to CourtListener ``RECAPDocument``, hung off the docket entry its
    ``date_filed`` and ``description`` describe. The site lists these as an
    ordered list under the case heading, oldest filing first.
    """

    document_number: int
    """1-based position in the case's list, which the court orders by filing
    date.

    Taken from the list position, not from the leading number in the PDF
    filename: 420 of 11,478 files disagree with their position because
    multi-volume exhibits are numbered ``8a``/``8b``/``8c``.
    """

    description: CleanString
    """The link text verbatim, e.g. ``"Appellant's Opening Brief on the
    Merits"`` or ``"Amicus Curiae Brief of Consumer Attorneys of
    California"``."""

    document_type: CleanString | None = None
    """The kind of document, with the filer stripped off -- ``"Opening Brief
    on the Merits"``, ``"Focus Issues Letter"``, ``"Amicus Curiae Brief"``.

    ``None`` when :data:`description` matches none of the three title
    grammars the court uses; the verbatim ``description`` always stands.
    """

    filed_by: CleanString | None = None
    """Who filed it, as the title states them -- ``"Appellant"``,
    ``"Respondents"``, ``"Real Party in Interest, The People"``, or the named
    amicus. ``None`` when the title names no filer (the pre-2011 listings
    often read just ``"Petition for Review"``)."""

    date_filed: date | None = None
    """Filing date, from the ``"Filed on <Month D, YYYY>"`` text beside the
    link. Present on all 11,478 links in the corpus; optional because a
    missing date should not fail the case."""

    url: str | None = None
    """Absolute URL of the PDF.

    ``None`` when the court listed the brief but linked no file: exactly one
    listing in the 2010-2026 corpus does that (the May 7-8 2019 session's
    "Respondent, L.A. Truck Centers, LLC, Opening Brief on the Merits"). The
    listing is kept rather than dropped -- that the court named a brief it did
    not post is itself the datum.
    """

    filename: str | None = None
    """The PDF's basename, URL-decoded; ``None`` when there is no link.

    Kept because it carries what the visible listing does not: the docket
    number (which recovers the case for a mislabelled heading) and, on
    2023-and-later filings, the court's internal event code
    (``4-115-s279242-resps-answer-pet-rev-042423.pdf``).
    """


class CalSupremeBriefCase(ScrapedData):
    """A case's brief listing under one oral argument session.

    Maps to CourtListener ``Docket``. This is *not* a full docket -- the
    briefs page states only the case number, the caption, an occasional note,
    and the briefs. Filing dates, parties, and disposition for the same case
    come from ``appellatecases_courtinfo_ca_gov``, which joins on
    ``docket_number`` + ``court``.

    A case continued to a later calendar is listed again under the new
    session, with the briefs filed since appended: 52 of the corpus's 1,227
    distinct case numbers appear under more than one session, and 49 of those
    have a different brief set each time. So the record is one *listing*, not
    one case -- ``(court, docket_number, source_url)`` identifies it.
    """

    court: str
    """CourtListener court id, derived from the case-number prefix."""

    docket_number: str
    """Case number, e.g. ``"S280572"``."""

    case_name: HarmonizedCaseName | None = None
    """Caption as the heading states it, e.g. ``"PEOPLE v. MENO"``. ``None``
    on the one heading in the corpus that states no case at all."""

    heading_raw: CleanString
    """The case heading verbatim, number and caption together.

    Kept because the heading is the site's weakest field: one September 2019
    heading reads ``"NO CASE ASSIGNED"`` over what the filenames show to be a
    duplicate listing of S198132, and 2010-2012 headings vary the separator
    between number and caption (``-``, ``--``, or nothing at all).
    """

    date_argued: date | None = None
    """The date this case was argued -- set only for a single-day session.

    ``None`` for the 88 of 191 multi-day sessions: the page groups every case
    under the session as a whole and never says which day a given case was
    called, so any single date would be a guess. The session span is always
    available in ``date_session_start``/``date_session_end``, and the
    per-case day is in the session's oral argument calendar PDF (see
    CC_NOTES).
    """

    date_session_start: date
    """First day of the session this listing appeared under."""

    date_session_end: date
    """Last day of that session; equal to ``date_session_start`` when the
    session ran one day."""

    session_title: CleanString
    """Verbatim title of the session page."""

    session_type: CalSupremeSessionType
    """Regular, Special or Outreach."""

    notes: CleanString | None = None
    """The court's parenthetical note(s) under the heading, verbatim.

    A case may carry more than one -- 8 in the corpus do, stating both a
    consolidation and a pro tempore assignment -- in which case they are
    joined with a space in the order the page states them.

    A note says one of a handful of things: which Court of Appeal justice sat pro
    tempore, which justices did not participate, that the case is
    consolidated with another, that it was retitled or deferred, or that it
    will "be called and continued to a future oral argument calendar" (which
    is why a case reappears under a later session).
    """

    consolidated_with: list[str] = []
    """Case numbers named in :data:`notes` as consolidated with this one."""

    briefs: list[CalSupremeBrief] = []
    """Every brief the court listed for this case at this session, in the
    order listed (oldest filing first)."""

    source_url: str
    """URL of the session page that listed this case."""

    source_entry_point: str | None = None
    """Entry point that reached this listing."""


class CalSupremeDownloadedBrief(ScrapedData):
    """Archive record for a downloaded brief PDF.

    Emitted separately from :class:`CalSupremeBriefCase` so the file joins
    back to its case on ``(court, docket_number, brief_url)``. Maps to
    CourtListener ``RECAPDocument``.

    One record per (case, file), not per listing: a case listed under two
    sessions shares the same URLs, and the download is deduplicated on
    ``(docket_number, filename)`` so the file is fetched once.
    """

    court: str
    """CourtListener court id, matching :data:`CalSupremeBriefCase.court`."""

    docket_number: str
    """Case number, matching :data:`CalSupremeBriefCase.docket_number`."""

    document_number: int
    """Position in the case's brief list at the session that yielded it."""

    description: CleanString
    """The brief's link text, matching :data:`CalSupremeBrief.description`."""

    date_filed: date | None = None
    """The brief's filing date."""

    brief_url: str
    """URL the file was downloaded from."""

    local_path: str | None = None
    """Path the archive handler wrote the file to; ``None`` if the download
    was skipped."""
