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
    """Local filesystem path where the file was downloaded (set by driver)"""

    available: bool = True
    """False for sealed/not-available files"""

    docket_number: str | None = None
    """APL/CTQ/JCR number (e.g., 'APL-2024-00177') when reached via docket flow"""

    # --- file-name convention (see filename_convention.py) -----------------
    # Court-PASS file names follow the Court's published convention,
    # ``title of action-role-name-doctype[-volN].pdf``
    # (https://www.nycourts.gov/ctapps/techspecs.htm). These carry what that
    # name encodes; each is None when the filer departed from the convention.

    doc_role: str | None = None
    """Party role from the file name, normalized ('appellant', 'respondent',
    'amicus', 'appellant-respondent', ...)."""

    doc_party: str | None = None
    """Party-name segment from the file name (e.g. 'ConcernedCitizens')."""

    doc_type: str | None = None
    """Canonical document type from the file name ('brf', 'replybrf', 'rec',
    'appdx', 'amicbrf', 'ssmltrbrf', 'motforlv', ...). Values prefixed '_'
    are court-generated rather than filed: '_decision', '_transcript',
    '_webcast', and '_combined' for one PDF covering two filings."""

    volume: int | None = None
    """Volume number for multi-volume records/appendices ('-Rec-vol3')."""

    part: int | None = None
    """Part number, when a volume is itself split ('-Rec-vol1 part2')."""

    document_group: int | None = None
    """Which logical document this file belongs to within the docket. Volumes
    and parts of one record share a ``document_group``; every group maps to
    exactly one ``docket_entry_index``. None for court-generated files."""

    # --- resolved link to the FILINGS table --------------------------------

    docket_entry_index: int | None = None
    """``entry_index`` of the ``docket_entries`` row this file belongs to.
    With the parent's ``docket_number`` this is the composite key
    ``(docket_number, docket_entry_index)`` -> ``(docket_number,
    entry_index)``. Volumes of one record all point at the same entry.
    Resolved by ``reconcile_files_and_entries``, which synthesizes an entry
    for any document the FILINGS table omitted, so every filer-submitted file
    has one. None only for court-generated files (decision, transcript,
    webcast), which are not filings."""

    link_status: str | None = None
    """How this file reached its entry: 'matched' (a real FILINGS row),
    'inferred' (an entry synthesized from this file name because no FILINGS
    row listed it), or 'court_generated' (no entry -- the court's own output).
    'unlinked' would mean a filer file escaped both paths and indicates a bug."""

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
    ``reconcile_files_and_entries`` so that every filer-submitted file hangs
    off exactly one entry. See ``filename_convention.py``.
    """

    filing_type: str
    """Filing type. Verbatim from the FILINGS table (e.g. 'Appellant Brief')
    for real rows; composed from the file name (e.g. 'Appellant Motion for
    Leave to Appeal') when ``inferred_from_file``."""

    party: str | None = None
    """Party name associated with the filing. From the FILINGS table, or from
    the file name's party segment when ``inferred_from_file``."""

    date_due: date | None = None
    """Due date for the filing. Always None when ``inferred_from_file``:
    ``gvFiles`` carries no dates."""

    date_received: date | None = None
    """Date the filing was received. Always None when ``inferred_from_file``."""

    entry_index: int | None = None
    """0-based position of this entry in the parent docket's
    ``docket_entries``. Real FILINGS rows keep their table order and come
    first; inferred entries are appended after them, so these values are
    stable. With the parent's ``docket_number`` this forms the composite key
    ``NYCourtPassFile.docket_entry_index`` joins against."""

    raw_filing_type: str | None = None
    """The FILINGS-table filing-type string exactly as the page rendered it.
    None when ``inferred_from_file`` — no table row existed to quote."""

    entry_role: str | None = None
    """Normalized party role for this filing ('appellant', 'respondent',
    'amicus', ...), from ``FILING_TYPE_MAP`` or from the file name for
    inferred entries. None when the filing type implies no role."""

    entry_doctype: str | None = None
    """Canonical document type for this filing ('brf', 'replybrf', 'rec',
    'motforlv', ...). None when the filing type carries no document (e.g.
    'SCJC Determination') or when it could not be classified — see
    ``filing_type_recognized`` to tell those apart."""

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
    which is common (~8% of names) and not drift."""

    inferred_from_file: bool = False
    """True when this entry was synthesized from a file name rather than read
    from the FILINGS table. Expected for filings the table structurally omits
    (motion papers, Appellate Division material, compendia, addenda —
    ``NOT_ON_FILINGS_TABLE``); outside that set it means the table dropped
    something it usually lists."""

    file_indexes: list[int] = []
    """``file_index`` of every file belonging to this entry — zero or more.
    Empty means the FILINGS table listed a filing with no document on the
    site (routine for pending cases). More than one means a multi-volume
    record or a document split into parts. Join to ``NYCourtPassFile`` on
    ``(docket_number, file_index)`` to reach ``available``."""


class NYCourtPassAttorney(ScrapedData):
    """Attorney info from the ATTORNEY DETAILS section of the Docket page."""

    party_name: str
    """Name of the party this attorney represents"""

    party_role: str
    """Party's role (e.g., 'Appellant', 'Respondent', 'Amicus Curiae')"""

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

    issues: list[CleanString] = []
    """Issue categories (e.g., 'Environmental Conservation--...')"""

    issue_details: list[CleanString] = []
    """Detailed issue descriptions"""

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
    """0-based row index within ``search_page`` of the Docket.aspx grid."""

    aria_case_info: str | None = None
    """Raw ``aria-label`` string from the grid's Select button."""
