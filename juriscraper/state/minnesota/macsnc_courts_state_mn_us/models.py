"""Data models for the Minnesota P-MACS appellate scraper.

Covers the Minnesota Supreme Court (``minn``) and Court of Appeals
(``minnctapp``), both served from the P-MACS C-Track install at
``macsnc.courts.state.mn.us/ctrack/``.

Field names track CourtListener (see ``../../CL_MODELS.md``):
``docket_number`` (not ``case_number``), ``court`` (a CourtListener
court-id string, not ``court_id``), and ``date_*`` for dates.
"""

from __future__ import annotations

from datetime import date

from jkent.common.data_models import ScrapedData

from juriscraper.state.common_models import CleanString, HarmonizedCaseName

# CourtListener court IDs the P-MACS site exposes via its
# ``jurisdictionID`` filter, mapped to their display names. Documentation
# only — the scraper resolves the court from the per-row / per-page
# jurisdiction text rather than from this mapping.
COURT_IDS: dict[str, str] = {
    "minn": "Supreme Court of Minnesota",
    "minnctapp": "Court of Appeals of Minnesota",
}

# Map the jurisdiction text shown on results / case pages to a
# CourtListener id. Rows whose jurisdiction isn't in this map are
# filtered out at scraping time.
JURISDICTION_TO_COURT_ID: dict[str, str] = {
    "Court of Appeals": "minnctapp",
    "Supreme Court": "minn",
}


class MnDocument(ScrapedData):
    """A downloadable document attached to a docket entry.

    Maps onto CourtListener ``RECAPDocument``. The P-MACS docket entry
    detail page exposes one or more ``/ctrack/document.do?document={hash}``
    anchors; each becomes one of these records. The actual file is fetched
    by an ``archive=True`` Request whose deduplication key embeds the
    docket number, ``deID``, and document hash."""

    label: str
    """Anchor text of the document link (e.g. ``Order - Other``).
    The remote ``Content-Disposition`` filename is typically
    ``{label}.pdf``."""

    document_url: str
    """Absolute URL of the ``document.do`` endpoint that serves the
    file."""

    doc_entry_id: str | None = None
    """The ``deID`` of the parent docket entry — captured directly on
    the document record so consumers can join back to the entry
    without traversing the docket's nested ``entries`` list."""


class MnDocketEntry(ScrapedData):
    """A row from the Docket Information table on a case page.

    Maps onto CourtListener ``DocketEntry``."""

    date_filed: date | None = None
    """Filing date displayed in the row."""

    description: str | None = None
    """Document description text (the anchor text in the first column)."""

    docket_entry_type: str | None = None
    """Docket Entry Type column (e.g. ``Order``, ``Motion``, ``Notice``)."""

    filing_type: str | None = None
    """Filing Type column (e.g. ``Other``, ``Case Filing``)."""

    status: str | None = None
    """Status column (e.g. ``Final``)."""

    jurisdiction: str | None = None
    """Jurisdiction column text (e.g. ``Court of Appeals``)."""

    doc_entry_id: str | None = None
    """Numeric ``deID`` parameter from the entry's anchor href."""

    entry_url: str | None = None
    """Absolute URL of the docket-entry detail page; the scraper
    follows this to enumerate attached documents."""

    documents: list[MnDocument] = []
    """Documents attached to this entry, populated after the
    docket-entry detail page is fetched. Empty for sealed / metadata-
    only entries."""

    # === Entry-specific fields harvested from the docketEntry.do
    # detail page. These reflect the entry-section of the page (cells
    # whose labels use ``class="Label"`` in upper case — the
    # ``class="label"`` lower-case rows at the top of the page repeat
    # the parent case info and are skipped). ===

    entry_status: str | None = None
    """Per-entry workflow status (e.g. ``Final``, ``Pending``).
    Distinct from the parent case's ``status``."""

    thread_to: str | None = None
    """Description of the parent docket entry this entry threads to,
    when set."""

    method_of_receipt: str | None = None
    """``Method of Receipt`` select value (Mail / Electronic / Fax /
    Hand Delivered / Overnight Service)."""

    method_of_service: str | None = None
    """``Method of Service`` select value."""

    method_of_payment: str | None = None
    """``Method of Payment`` select value, on entries that record a
    filing fee."""

    indicate_service: str | None = None
    """``Indicate Service`` radio choice — ``Service Complete`` /
    ``No Service`` / ``Partial Service``."""

    filing_fee: str | None = None
    """``Filing Fee`` radio choice — ``Not Paid`` / ``Motion to
    Waive`` / ``Collected`` / ``Waived``."""

    postmark_date: date | None = None
    """``Postmark Date (if by mail)`` value."""

    filing_date_time: str | None = None
    """``Filing Date`` value with the per-entry timestamp (the parent
    ``date_filed`` is the date-only version)."""

    docket_entry_date_time: str | None = None
    """``Docket Entry Date`` value with timestamp."""

    filed_by: list[str] = []
    """Selected option text(s) from the ``Filed By`` multi-select
    (party names, e.g. ``Williams, Dale Allen, Sr.; Appellant: o/b/o
    Pro Se``)."""

    signed_by: list[str] = []
    """Selected option text(s) from ``Signed By`` on Order entries —
    one or more judge names, or ``Per Curiam``."""

    other_signatures: str | None = None
    """``Other Signatures`` free text."""

    disposition_type: str | None = None
    """Order entries: ``Order Disposition Type`` select value (Other /
    Deny / Grant / Grant/Deny / Granted and Stayed)."""

    disposition_details: str | None = None
    """Order entries: ``Disposition Details`` free text."""

    reporters: str | None = None
    """Transcript entries: ``Reporter(s)`` free text."""

    date_of_hearings: str | None = None
    """Transcript entries: ``Date of Hearing(s)`` free text."""

    comments: str | None = None
    """``Comments`` free text, on entries that have a comments field."""

    other_deficiencies: str | None = None
    """``Other Deficiencies`` free text, on Notice entries."""

    details: dict[str, str] = {}
    """Catch-all map of every Label / value pair harvested from the
    entry-detail page. Includes the typed fields above (so consumers
    have one bag-of-strings to grep) plus any additional fields that
    the typed schema doesn't model yet — useful for entry types we
    haven't seen during design."""


class MnOrcaInfo(ScrapedData):
    """Originating Court / Agency information.

    Maps loosely onto CourtListener ``OriginatingCourtInformation``.
    Sourced from the ``ORCA Info`` link in the case-page sidebar
    (``publicLowerCourtSummary.jsp``). Captures the originating
    court / agency, the lower-court case identifiers, related case
    numbers, and the trial-court decisionmaker(s)."""

    appeal_from_str: str | None = None
    """``Appeal From:`` field (e.g. ``District Court``). Raw string —
    CL ``OriginatingCourtInformation`` / ``Docket.appeal_from_str``."""

    court_agency: str | None = None
    """``Court/Agency:`` field (e.g. ``Commitment Appeal Panel - CAP``,
    or a Minnesota district / county court name)."""

    other: str | None = None
    """``Other:`` free-text field."""

    orig_case_number: str | None = None
    """``Orig. Case Number:`` (the trial-court case number; CL
    ``OriginatingCourtInformation.docket_number``)."""

    orig_case_title: str | None = None
    """``Orig. Case Title:``."""

    related_case_numbers: list[str] = []
    """``Related Case Number(s):`` — typically a single value but
    occasionally multiple (split on commas)."""

    decisionmakers: list[str] = []
    """Trial-court judges / decisionmakers listed under
    ``Decisionmaker(s)``."""

    source_url: str | None = None
    """Absolute URL of the ORCA page."""


class MnParty(ScrapedData):
    """A row from the Party Information table on a case page.

    Maps onto CourtListener ``Party`` (+ ``PartyType`` for the role)
    and ``Attorney`` for the represented counsel."""

    macs_id: str | None = None
    """Internal MACS participant id."""

    role: str | None = None
    """Appellate Role column (e.g. ``Appellant``, ``Respondent``;
    CL ``PartyType.name``)."""

    name: str
    """Party display name."""

    attorneys: list[str] = []
    """Attorney names listed in the Attorney(s) column. ``<br>`` is the
    in-cell separator on the source page; we split on it and trim."""


class MnDocket(ScrapedData):
    """A Minnesota appellate docket scraped from P-MACS.

    Maps onto CourtListener ``Docket``."""

    # === Identity ===
    docket_number: str
    """P-MACS appellate case number, including the year-prefixed hyphen
    (e.g. ``A26-0748``). CL ``docket_number``."""

    court: str
    """CourtListener court id derived from the page's jurisdiction
    label (one of ``COURT_IDS``). CL ``Docket.court``."""

    # === Caption ===
    case_name: HarmonizedCaseName
    """Short title (or full title when short title is blank)."""

    short_title: CleanString | None = None
    full_title: CleanString | None = None
    summary: CleanString | None = None
    citation: CleanString | None = None

    # === Dates ===
    date_filed: date | None = None
    """Filing date as displayed on the case page."""

    # === Classification / status ===
    classification: CleanString | None = None
    """Classification column joined with ``-`` (group/type/subtype)."""
    status: CleanString | None = None
    jurisdiction: CleanString | None = None
    """Raw jurisdiction text as displayed (preserved alongside the
    mapped ``court``)."""
    orca: CleanString | None = None
    """ORCA (origin / hearing context) field."""
    hearing_type: CleanString | None = None

    # === Nested data ===
    parties: list[MnParty] = []
    entries: list[MnDocketEntry] = []
    orca_info: MnOrcaInfo | None = None
    """Originating Court / Agency info, fetched from the ``ORCA Info``
    page linked on the case sidebar."""

    # === Source tracking ===
    source_url: str | None = None
    """Absolute URL of the case-detail page this record was scraped
    from."""
    source_entry_point: str | None = None
    """Entry point used to reach this docket (e.g. ``dockets_by_filing_date``)."""
    cs_name_id: str | None = None
    """C-Track ``csNameID`` parameter (URL key component)."""
    cs_instance_id: str | None = None
    """C-Track ``csInstanceID`` parameter (URL key component)."""


# =========================================================================
# Site constants
# =========================================================================

BASE_URL: str = "https://macsnc.courts.state.mn.us"
LOGIN_URL: str = f"{BASE_URL}/ctrack/publicLogin.do"
SEARCH_URL: str = f"{BASE_URL}/ctrack/search/publicCaseSearch.do"
CASE_DETAIL_PATH: str = "/ctrack/view/publicCaseMaintenance.do"
ORCA_PATH: str = "/ctrack/view/publicLowerCourtSummary.jsp"

# Server-side display cap on the search results page.
RESULTS_CAP: int = 1000
PAGE_SIZE: int = 50
