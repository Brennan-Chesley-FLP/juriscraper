"""Data models for New York Court of Appeals scrapers.

These models extend ScrapedData from jkent to capture
New York Court of Appeals opinion and docket data.

Supported court:
- ny: New York Court of Appeals

Data sources:
- Dockets: Court-PASS system at https://courtpass.nycourts.gov/

"""

from __future__ import annotations

from datetime import date

from jkent.common.data_models import ScrapedData

from juriscraper.state.common_models import CleanString, HarmonizedCaseName

from .vocabularies import (
    FilingDocType,
    FilingRole,
    FilingType,
    IssueCategory,
    IssueSubcategory,
    PartyRole,
)

# Court ID mapping
COURT_IDS = {
    "ny": "New York Court of Appeals",
}


# =========================================================================
# Court-PASS Models (courtpass.nycourts.gov)
# =========================================================================


class NYCourtPassFile(ScrapedData):
    """A file from Court-PASS filing detail page."""

    file_name: str
    """Filename as shown on the filing detail page"""

    file_index: int | None = None
    """0-based position of this file in the files table on the page"""

    document_number: int | None = None
    """1-based document number for the file, numbered from the bottom of
    the gvFiles table up. The bottom-most row is document_number=1 and the
    top-most row is document_number=len(files). Mirrors the convention used
    when attaching documents to dockets in the downstream pipeline."""

    local_path: str | None = None
    """Local filesystem path where the file was downloaded (set by driver).

    Set **only** on the ``NYCourtPassFile`` emitted as its own result by
    ``handle_file_download``, never on the copy nested in
    ``NYCourtPassDocket.files``: the download is a separate request, and the
    docket is already emitted by the time it lands. The nested copy is the one
    that covers sealed files, which are never fetched and so have no path at
    all.

    Downstream, the merge joins the docket's files to the emitted ones on
    ``(docket_number, file_index)`` to pick this up. Every other field on the
    two is identical -- the emitted record is rebuilt from the same reconciled
    row -- so the join carries the path and nothing else."""

    available: bool = True
    """False for sealed/not-available files"""

    file_type: str | None = None
    """File extension the page states for this document ('pdf', 'asx').

    Read off the ``gvFiles`` download button, which labels itself ``Download
    PDF`` / ``Video`` / ``Not Available`` and repeats the file name with its
    extension in ``aria-label``. The Court states this outright, so the type is
    data rather than something to sniff from the bytes -- and it is known
    *before* the download, which is what lets it be passed as the request's
    ``expected_type``.

    None when the page named no extension. Sealed rows do carry one (``.txt``,
    ``.docx``, ``.rtf``), so this is set for them too; it describes a file the
    scrape will never hold."""

    docket_number: str | None = None
    """APL/CTQ/JCR number (e.g., 'APL-2024-00177') when reached via docket flow"""

    # --- file-name convention (see filename_convention.py) -----------------
    # Court-PASS file names follow the Court's published convention,
    # ``title of action-role-name-doctype[-volN].pdf``
    # (https://www.nycourts.gov/ctapps/techspecs.htm). These carry what that
    # name encodes; each is None when the filer departed from the convention.

    doc_role: FilingRole | None = None
    """Party role from the file name. None when the name states no role this
    vocabulary recognizes."""

    doc_party: str | None = None
    """Party-name segment from the file name (e.g. 'ConcernedCitizens')."""

    doc_type: FilingDocType | None = None
    """Document type from the file name. The '_'-prefixed members are court
    output rather than a filing, and '_combined' is one PDF covering two
    filings. None when the trailing token was unrecognizable, which is roughly
    6% of names -- filings that predate the Court's convention, document kinds
    this vocabulary has no member for, and misspellings."""

    volume: int | None = None
    """Volume number for multi-volume records/appendices ('-Rec-vol3')."""

    part: int | None = None
    """Part number, when a volume is itself split ('-Rec-vol1 part2')."""

    document_group: int | None = None
    """Which logical document this file belongs to within the docket. Volumes
    and parts of one record share a ``document_group``; every group maps to
    exactly one ``docket_entry_index``."""

    # --- resolved link to the FILINGS table --------------------------------

    docket_entry_id: str | None = None
    """``docket_entry_id`` of the ``docket_entries`` row this file belongs to.
    With the parent's ``docket_number`` this is the composite key
    ``(docket_number, docket_entry_id)``, and it is the join key to prefer:
    unlike ``docket_entry_index`` it survives rows being inserted above this
    one. Volumes of one record all point at the same entry. Always set: court
    output gets a synthesized entry like any other document the FILINGS table
    omits, so nothing is reachable only through ``files``."""

    docket_entry_index: int | None = None
    """``entry_index`` of the ``docket_entries`` row this file belongs to.

    Positional, and therefore **only valid within a single scrape** — the
    FILINGS table inserts new rows at the top, not the bottom (every one of the
    7 observed row additions was an insertion above existing rows), so this
    shifts between runs. Use ``docket_entry_id`` to join across scrapes.
    Resolved by ``reconcile_files_and_entries``, which synthesizes an entry
    for any document the FILINGS table omitted, so every file has one."""

    link_status: str | None = None
    """How this file reached its entry: 'matched' (a real FILINGS row),
    'inferred' (an entry synthesized from this file name because no FILINGS row
    listed it), or 'court_generated' (likewise synthesized, but the document is
    the court's own output -- a decision, transcript or webcast -- rather than
    something a party filed). 'unlinked' would mean a file escaped every path
    and indicates a bug."""

    match_confidence: str | None = None
    """For ``link_status='matched'``, how the link was established: 'exact'
    (document type, role, and party name all agree), 'strong' (type agrees
    plus one of role/party), or 'weak' (matched on compatible type and
    elimination within the docket). None for inferred and court-generated
    files, which were not matched against anything."""

    date_received: date | None = None
    """``date_received`` inherited from the linked docket entry. Only the
    FILINGS table carries filing dates; ``gvFiles`` has none."""

    date_due: date | None = None
    """``date_due`` inherited from the linked docket entry."""


class NYCourtPassDocketEntry(ScrapedData):
    """A row from the FILINGS table on the Docket detail page.

    Or, when ``inferred_from_file`` is set, a document found in ``gvFiles``
    that the FILINGS table never listed — synthesized by
    ``reconcile_files_and_entries`` so that every file on the docket hangs off
    exactly one entry, including the court's own decisions, transcripts and
    webcasts. See ``filename_convention.py``.
    """

    filing_type: str
    """Filing type. Verbatim from the FILINGS table (e.g. 'Appellant Brief')
    for real rows; composed from the file name (e.g. 'Appellant Motion for
    Leave to Appeal') when ``inferred_from_file``."""

    party: str | None = None
    """Party name associated with the filing, without the FILINGS table's
    trailing ``(A)`` / ``(R)`` side marker — that is a role, and it is carried
    on ``party_side``.

    For a real row this is the Court's own wording (``'122 East 42nd Street,
    LLC'``). For an ``inferred_from_file`` entry the source is the file name's
    party segment, which is a squashed short form (``'122East42ndStreet'``,
    ``'1995CAM'``, ``'Scharf'``); it is aligned back onto the wording the
    FILINGS table or the ATTORNEY DETAILS section uses for the same party
    where that can be done unambiguously, so the two kinds of entry read
    alike. ``party_match`` says whether that happened, and the unaligned
    segment remains on ``NYCourtPassFile.doc_party``."""

    party_side: PartyRole | None = None
    """Which side the FILINGS table put this filing's party on, from the ``(A)``
    / ``(R)`` marker it appends to the party name. Only ever ``APPELLANT`` or
    ``RESPONDENT`` — the table states no other side — and always None for an
    ``inferred_from_file`` entry, whose file name carries a filing role
    (``entry_role``) rather than a party's posture.

    Narrower than the ``NYCourtPassAttorney.party_role`` for the same party,
    which is the full ``Party Role`` line and distinguishes an amicus, an
    intervenor and a defendant below. The two never disagreed across the 6,579
    rows where both were stated."""

    party_match: str | None = None
    """How an ``inferred_from_file`` entry's ``party`` was aligned onto a name
    the docket states: 'exact', 'containment', 'initialism', 'subsequence' or
    'overlap', weakest last — see ``align_party_name``. None means no alignment
    took place: a real FILINGS row (which needs none), or a file-name segment
    that matched nothing on the docket unambiguously, in which case ``party``
    is still the raw segment. 94.6% of inferred entries with a party align, the
    great majority at 'exact' or 'containment'.

    The tier is about how the *name* was reached, not how sure we are the entry
    is that party's — a 'containment' match on a distinctive full name is
    firmer evidence than an 'exact' match on a two-letter token."""

    date_due: date | None = None
    """Due date for the filing. Always None when ``inferred_from_file``:
    ``gvFiles`` carries no dates."""

    date_received: date | None = None
    """Date the filing was received. Always None when ``inferred_from_file``."""

    docket_entry_id: str | None = None
    """Stable identifier for this entry, unique within the docket and intended
    to survive across scrapes. Set by ``reconcile_files_and_entries``; the
    parser leaves it None because it is assigned once the whole table is known.

    Two namespaces, distinguished by prefix, because the two kinds of entry have
    nothing in common to key on:

    * ``e:<filing_type>:<party>:<ordinal>`` for a real FILINGS row. Neither date
      is included — ``date_received`` fills in and ``date_due`` gets adjourned,
      so either would retire the id on a routine update.
    * ``d:<role>:<party>:<doctype>:<ordinal>`` for an entry synthesized from a
      document. Keyed on the group triple rather than a file name, so losing one
      volume of a record does not re-key the rest. Court output has no role or
      party, so it uses ``d:court:<title>:<doctype>:<ordinal>`` — the title
      (``123ent25``, ``51opn21``) is what separates two decisions on one
      docket.

    ``ordinal`` is a 1-based occurrence counter that only does work for repeated
    keys (124 duplicate ``(filing_type, party)`` groups across 14647 rows, 65 of
    them identical in all four columns and so genuinely indistinguishable).

    The id is *not* immortal: a clerk correcting ``filing_type`` or ``party``
    re-keys the entry, which reads downstream as a delete plus insert rather
    than an update. Observed 3 times across ~1180 docket-transitions."""

    entry_index: int | None = None
    """0-based position of this entry in the parent docket's ``docket_entries``.

    Real FILINGS rows come first in table order, then inferred entries. Useful
    for reproducing page order, but **positional and not stable between
    scrapes** — Court-PASS inserts new FILINGS rows at the top, so a row's index
    changes when anything is filed above it. Join on ``docket_entry_id``
    instead."""

    raw_filing_type: str | None = None
    """The FILINGS-table filing-type string exactly as the page rendered it.
    None when ``inferred_from_file`` — no table row existed to quote."""

    entry_filing_type: FilingType | None = None
    """The FILINGS-table filing type, classified. None when no table row named
    this filing -- an entry reconstructed from a document -- and also None when
    the table named a type this vocabulary does not cover;
    ``filing_type_recognized`` tells those two apart."""

    entry_role: FilingRole | None = None
    """Party role for this filing, from ``FILING_TYPE_MAP`` or from the file
    name for inferred entries. None when the filing type implies no role."""

    entry_doctype: FilingDocType | None = None
    """Document type for this filing. None when the filing type carries no
    document (e.g. an SCJC determination) or when it could not be classified —
    see ``filing_type_recognized`` to tell those apart."""

    filing_type_recognized: bool = False
    """True when this entry's filing type resolved: present in
    ``FILING_TYPE_MAP`` for a real row, or yielding a doctype from the file
    name for an inferred one.

    Read it together with ``inferred_from_file``, because False means two
    different things. ``filing_type_recognized=False AND
    inferred_from_file=False`` is the **vocabulary-drift signal** — Court-PASS
    put a filing kind in the FILINGS table that ``FILING_TYPE_MAP`` predates
    (currently zero across the historical corpus; such an entry still matches
    files, just without role/doctype constraints). ``False`` on an inferred
    entry merely means the file name's document-type token was unreadable,
    which is common (~6% of names) and not drift."""

    inferred_from_file: bool = False
    """True when this entry was synthesized from a file name rather than read
    from the FILINGS table. Expected for filings the table structurally omits
    (motion papers, Appellate Division material, compendia, addenda —
    ``NOT_ON_FILINGS_TABLE``) and for the court's own output (decisions,
    transcripts, webcasts), which is never a filing at all; outside those two
    sets it means the table dropped something it usually lists. Join to
    ``NYCourtPassFile.link_status`` to tell a filer document ('inferred') from
    court output ('court_generated')."""

    file_indexes: list[int] = []
    """``file_index`` of every file belonging to this entry — zero or more.
    A synthesized entry always has at least one, since a file is what created
    it.
    Empty means the FILINGS table listed a filing with no document on the
    site (routine for pending cases). More than one means a multi-volume
    record or a document split into parts. Join to ``NYCourtPassFile`` on
    ``(docket_number, file_index)`` to reach ``available``."""


class NYCourtPassIssue(ScrapedData):
    """One issue the Court assigned to a case, from the case-details section.

    The Court writes an issue as a category and a subcategory joined by a
    double dash -- ``Judgments--Confession of Judgment`` -- and describes most
    of them in a paragraph of detail. A case usually has one but may have
    several.
    """

    category_raw: CleanString
    """The issue exactly as Court-PASS stated it, category and subcategory
    together."""

    category: IssueCategory | None = None
    """The issue's category. None when the Court stated one this vocabulary
    does not cover, which ``recognized`` reports."""

    subcategory: IssueSubcategory | None = None
    """The issue's subcategory. None when the Court stated a bare category,
    which it does for roughly 13% of issues, and also None when the
    subcategory is one this vocabulary does not cover."""

    detail: CleanString | None = None
    """The Court's description of the issue. None on the roughly 4% of issues
    it states without one."""

    recognized: bool = False
    """False when the Court stated a category or subcategory these
    vocabularies do not cover, which is the signal to add a member."""


class NYCourtPassAttorney(ScrapedData):
    """Attorney info from the ATTORNEY DETAILS section of the Docket page."""

    party_name: str
    """Name of the party this attorney represents"""

    party_role: PartyRole | None = None
    """The party's role, classified. None when the page stated nothing, and
    also None when it stated a role ``PartyRole`` does not cover -- compare
    with ``party_role_raw``, which is always intact, to tell those apart. A
    nonempty ``party_role_raw`` beside a None here is the signal to add a
    member."""

    party_role_raw: str = ""
    """The ``Party Role`` line exactly as the page stated it (e.g.
    'Appellant', 'Respondent', 'Amicus Curiae'), with whitespace collapsed."""

    firm: str | None = None
    """Law firm name"""

    attorney_name: str | None = None
    """Attorney's name"""

    address: str | None = None
    """Attorney's address"""

    phone: str | None = None
    """Attorney's phone number"""


class NYCourtPassDocket(ScrapedData):
    """Docket + filing detail data from Court-PASS.

    Built by merging the docket-detail page (APL number, filings table,
    attorneys, case title) with the filing-detail page reached via
    bttnDetails (decision date, issues, citations, file list).
    Linked to NYCourtPassFile rows via ``docket_number``.
    """

    docket_number: str | None = None
    """APL number (e.g., 'APL-2024-00177')"""

    court: str = "ny"
    """CourtListener court ID (``ny``)."""

    case_name: HarmonizedCaseName
    """Full case name from the docket-detail / filing-detail page."""

    case_short_name: str | None = None
    """Abbreviated case caption from the Docket.aspx grid row
    (e.g. 'People v Padilla-Zuniga (Juan)'). Captured during grid walks
    (``dockets_by_bulk``); None for direct-APL lookups."""

    argument_date: date | None = None
    """Argument date from the docket page"""

    decision_date: date | None = None
    """Date of decision (decided cases only)"""

    issues: list[NYCourtPassIssue] = []
    """The issues the Court assigned to this case, classified, each paired with
    the detail the Court published for it."""

    official_citation: str | None = None
    """Official citation (decided cases only)"""

    lower_court_citation: str | None = None
    """'Reported Below' citation for the appealed decision
    (e.g., '102 AD3d 543'); None when not reported."""

    no_files_for_case: bool = False
    """True when the filing-detail page explicitly says 'There are no
    files available for this case'."""

    docket_entries: list[NYCourtPassDocketEntry] = []
    """Filing entries from the FILINGS table"""

    attorneys: list[NYCourtPassAttorney] = []
    """Attorney details"""

    files: list[NYCourtPassFile] = []
    """Files listed on the filing-detail page (gvFiles). Each file's
    binary is emitted separately via ``handle_file_download``."""

    source_url: str | None = None
    """URL of the filing-detail page."""

    source_entry_point: str | None = None
    """Entry point used to reach this docket (e.g., 'dockets_by_bulk')."""

    search_page: int | None = None
    """1-based page number of the Docket.aspx result grid this docket was
    found on. None when reached via a direct-APL lookup (``docket_by_number``)."""

    search_row: int | None = None
    """0-based row index within ``search_page`` of the Docket.aspx grid.

    The grid's Select button also carries an ``aria-label`` restating the case
    name and argument date. It was captured as ``aria_case_info`` until
    2026-08-16, when the data audit found it stated nothing beyond
    ``case_short_name`` and ``argument_date`` -- both read from the grid's own
    cells -- while carrying the site's double-escaped HTML entities into the
    data on 2,057 of 5,088 dockets. Dropped rather than repaired."""
