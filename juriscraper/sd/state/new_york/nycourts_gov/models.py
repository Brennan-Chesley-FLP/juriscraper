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

# Opinion type suffixes found in PDF filenames
OPINION_TYPES = {
    "opn": "Opinion",
    "mem": "Memorandum",
    "ent": "Entry",
}


def normalize_opinion_type(filename: str) -> str:
    """Extract opinion type from PDF filename.

    Args:
        filename: PDF filename like '112opn26-Decision.pdf' or '102mem25-Decision.pdf'

    Returns:
        Opinion type string (e.g., 'opn', 'mem', 'ent') or 'unknown'
    """
    filename_lower = filename.lower()
    for suffix in OPINION_TYPES:
        if suffix in filename_lower:
            return suffix
    return "unknown"


class NYOpinion(ScrapedData):
    """An individual opinion document from New York Court of Appeals."""

    download_url: str
    """URL to the opinion PDF"""

    type: str
    """Opinion type based on filename suffix: 'opn', 'mem', 'ent', etc."""

    local_path: str | None = None
    """Local filesystem path where the PDF was downloaded (set by driver)"""


class NYOpinionCluster(ScrapedData):
    """A cluster of opinions from New York Court of Appeals.

    This is the main output type yielded by the scraper.
    Each cluster represents a single opinion number (e.g., 'No. 112')
    from a decision day.

    The New York Court of Appeals is the highest court in New York State.
    """

    # === Searchable fields ===
    docket_id: str
    """Opinion number (e.g., 'No. 112' or '112')"""

    court_id: str
    """Court identifier: 'ny' (Court of Appeals)"""

    date_filed: date
    """Decision date"""

    # === Required fields ===
    case_name: str
    """Case name"""

    # === Related data ===
    opinions: list[NYOpinion] = []
    """All opinions/orders in this cluster (typically one per case)"""

    # === Source tracking ===
    source_url: str | None = None
    """URL of the monthly decisions page where this was found"""

    # === NY-specific fields ===
    precedential_status: str | None = None
    """Precedential status (e.g., 'Published')"""

    slip_op_number: str | None = None
    """Slip opinion number if available (e.g., '2026 NY Slip Op 00201')"""


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


class RefreshDocketsParams(ScrapedData):
    """Parameters for the ``refresh_dockets`` entry point."""

    seen_dockets: set[str]
    """Docket numbers already scraped (e.g., {'APL-2024-00177', ...})"""

    still_live: date
    """Cutoff date: dockets decided before this are considered stale"""


class NYCourtDocketAlreadyScraped(ScrapedData):
    """Confirmation that a previously-scraped docket is still on Court-PASS.

    Emitted by ``refresh_dockets`` when the docket number was already seen
    and its decision date predates the ``still_live`` cutoff.
    """

    docket_number: str
    """APL number (e.g., 'APL-2024-00177')"""


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
