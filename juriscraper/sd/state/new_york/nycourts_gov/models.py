"""Data models for New York Court of Appeals scrapers.

These models extend ScrapedData from kent to capture
New York Court of Appeals opinion and docket data.

Supported court:
- ny: New York Court of Appeals

Data sources:
- Opinions: Monthly decision pages at https://www.nycourts.gov/ctapps/Decisions/{YYYY}/{Mon}{YY}/{Month}{YY}.html
- Dockets: Court-PASS system at https://courtpass.nycourts.gov/

Opinion types (from filename suffixes):
- opn: Opinion (full opinion)
- mem: Memorandum (brief opinion)
- ent: Entry (order/entry)
"""

from __future__ import annotations

from datetime import date

from kent.common.data_models import ScrapedData

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

    local_path: str | None = None
    """Local filesystem path where the file was downloaded (set by driver)"""

    available: bool = True
    """False for sealed/not-available files"""

    temp_case_id: str | None = None
    """UUID linking this file to its parent NYCourtPassDocket for joining in the data pipeline"""

    docket_number: str | None = None
    """APL/CTQ/JCR number (e.g., 'APL-2024-00177') when reached via docket flow"""


class NYCourtPassOralArgument(ScrapedData):
    """A deferred oral-argument recording reference.

    Court-PASS serves oral-argument webcast/audio rows as a tiny ASX
    (Advanced Stream Redirector) XML stub with
    ``Content-Disposition: Attachment``, so the ASX file lands in the
    archive store even though it isn't the recording itself. The scraper
    parses the embedded ``mms://`` reference and emits this model
    capturing where the ASX stub was saved and the resolved HTTP URL of
    the actual ``.wmv`` recording, so the recording can be downloaded
    out-of-band by a separate process.
    """

    asx_url: str
    """Local filesystem path to the archived ASX redirect stub."""

    wmv_url: str
    """HTTP URL of the actual ``.wmv`` oral-argument recording."""

    filename: str
    """The original ``gvFiles`` row label (e.g. '111914-228-Oral-Argument-Webcast')."""

    temp_case_id: str | None = None
    """UUID linking this recording to its parent NYCourtPassCase / NYCourtPassDocket."""

    docket_number: str | None = None
    """APL/CTQ/JCR number when reached via docket flow."""


class NYCourtPassCase(ScrapedData):
    """Case and filing data from the Court-PASS filing detail page.

    Emitted from parse_filing_detail with all case-level information.
    Linked to NYCourtPassDocket and NYCourtPassFile via temp_case_id.
    """

    temp_case_id: str
    """UUID for joining with docket and file data in the pipeline"""

    court_id: str = "ny"
    """Court identifier"""

    case_name: str
    """Full case name from the filing detail page"""

    case_name_abbrev: str | None = None
    """Abbreviated case caption from the Public_search results grid
    (e.g. 'People v Padilla-Zuniga (Juan)'), populated when the case
    was reached via the search_pending / search_decided_after flows."""

    argument_date: date | None = None
    """Date of oral argument"""

    decision_date: date | None = None
    """Date of decision (decided cases only)"""

    issues: list[str] = []
    """Issue categories (e.g., 'Environmental Conservation--...')"""

    issue_details: list[str] = []
    """Detailed issue descriptions"""

    opinion_by: str | None = None
    """Author of the opinion (decided cases only)"""

    official_citation: str | None = None
    """Official citation (decided cases only)"""

    files: list[NYCourtPassFile] = []
    """Files from the filing detail page"""

    no_files_for_case: bool = False
    """True when the page explicitly says 'There are no files available for this case'"""

    source_url: str | None = None
    """URL of the filing detail page"""

    source_entry_point: str | None = None
    """Entry point used to find this case (e.g., 'browse')"""

    coa_site_source: str | None = None
    """Which Court-PASS surface the case was reached through:
    'search' (Public_search.aspx), 'browse' (Public_Browse.aspx), or
    'docket' (Docket.aspx).  Derived from the entry point."""

    docket_number: str | None = None
    """APL/CTQ/JCR number (e.g., 'APL-2024-00177') when reached via docket flow"""

    argument_number: str | None = None
    """Argument calendar position number for pending cases (e.g., '39').
    Shown in the Pending Cases grid on Public_search.aspx."""

    search_page: int | None = None
    """1-based page number of the result grid this case was found on
    (docket / search pending / search decided / browse). None when the case
    was reached via a direct-APL lookup rather than a grid walk."""

    search_row: int | None = None
    """0-based row index within ``search_page`` of the grid the case was
    found in. Combined with ``search_page`` this uniquely identifies the
    scrape position of this case within a given flow."""

    aria_case_info: str | None = None
    """Raw ``aria-label`` string from the grid's Select button — a single
    rendered line that typically includes the case name plus argument /
    decision / calendar dates. Useful as a tie-breaker when the filing
    detail page omits the title server-side (e.g. JCR cases)."""

    search_grid: str | None = None
    """Which Public_search.aspx subgrid this case was reached from:
    ``"pending"`` (gvPublicSearchPre) or ``"decided"`` (gvPublicSearchPost).
    None for browse / docket / direct-APL flows.  Together with the now-
    specific ``coa_site_source`` (``search_pending`` / ``search_decided``)
    this disambiguates the natural key
    ``(coa_site_source, search_page, search_row)`` — the two subgrids
    share row indices on the same response page."""


class NYCourtPassDocketEntry(ScrapedData):
    """A row from the FILINGS table on the Docket detail page."""

    filing_type: str
    """Filing type (e.g., 'Appellant Brief', 'Respondent Brief')"""

    party: str | None = None
    """Party name associated with the filing"""

    date_due: date | None = None
    """Due date for the filing"""

    date_received: date | None = None
    """Date the filing was received"""


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
    """Docket data from the Court-PASS Docket detail page.

    Contains APL number, filings table, and attorney details.
    Linked to a NYCourtPassCase via temp_case_id.
    """

    temp_case_id: str
    """UUID linking to the NYCourtPassCase"""

    docket_number: str | None = None
    """APL number (e.g., 'APL-2024-00177')"""

    court_id: str = "ny"
    """Court identifier"""

    case_name: str = ""
    """Case name as shown on the docket page (for reference)"""

    argument_date: date | None = None
    """Argument date from the docket page"""

    docket_entries: list[NYCourtPassDocketEntry] = []
    """Filing entries from the FILINGS table"""

    attorneys: list[NYCourtPassAttorney] = []
    """Attorney details"""

    search_page: int | None = None
    """1-based page number of the Docket.aspx result grid this docket was
    found on. None when reached via a direct-APL lookup (``get_docket``)."""

    search_row: int | None = None
    """0-based row index within ``search_page`` of the Docket.aspx grid."""

    aria_case_info: str | None = None
    """Raw ``aria-label`` string from the grid's Select button."""


class NYDocketFailure(ScrapedData):
    """Record of a docket whose filing-detail page could not be confirmed.

    Emitted when ``parse_docket_filing_detail`` exhausts its
    docket-number-search recovery attempts without ever loading a
    filing-detail page whose caption agrees with the docket-detail
    caption (a Court-PASS bttnDetails session-state race).

    The docket-side data (case_name, argument_date, docket_entries,
    attorneys) is reliable because it comes from the docket-detail page,
    which we verify lines up with the row that was clicked. Only the
    filing-detail-only fields (decision_date, issues, files, etc.) are
    unavailable. Downstream consumers can use this record to retry the
    case later or to surface a known gap.
    """

    temp_case_id: str
    """UUID matching what NYCourtPassDocket / NYCourtPassCase would have used."""

    docket_number: str | None = None
    """APL/CTQ/JCR number from the docket-detail page."""

    court_id: str = "ny"
    """Court identifier."""

    case_name: str = ""
    """Case caption from the docket-detail page (reliable)."""

    argument_date: date | None = None
    """Argument date from the docket-detail page."""

    docket_entries: list[NYCourtPassDocketEntry] = []
    """Filing entries from the FILINGS table on the docket-detail page."""

    attorneys: list[NYCourtPassAttorney] = []
    """Attorney details from the docket-detail page."""

    search_page: int | None = None
    """1-based page number on the Docket.aspx grid this row was found on."""

    search_row: int | None = None
    """0-based row index within ``search_page``."""

    aria_case_info: str | None = None
    """Raw ``aria-label`` string captured from the grid's Select button."""

    failure_reason: str = "filing_detail_caption_mismatch"
    """Machine-readable failure code."""

    observed_filing_caption: str | None = None
    """Caption seen on the filing-detail page (the wrong case the server
    returned). Useful when diagnosing recurring drift patterns."""

    recovery_attempts: int = 0
    """How many docket-number-search recovery walks were attempted before
    giving up (equal to MAX_FILING_DETAIL_RECOVERY at emission time)."""

    failed_docket_search: bool = False
    """True when a recovery walk's docket-number search returned no
    matching rows (the case is genuinely not findable by docket number
    on Court-PASS, or its index entry is broken).  False means the search
    found the case but the filing-detail page still wouldn't load
    consistently."""
