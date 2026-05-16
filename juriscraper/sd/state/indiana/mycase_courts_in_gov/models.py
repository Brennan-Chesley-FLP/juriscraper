"""Data models for the Indiana MyCase appellate-court scraper.

Three CourtListener court ids are involved:
- ``ind``      Indiana Supreme Court (site CourtCode ``S``)
- ``indctapp`` Indiana Court of Appeals (site CourtCode ``A``)
- ``indtc``    Indiana Tax Court (site CourtCode ``T``)

The site's CaseSummary JSON returns a flat list of docket entries
(``Events``) with attached document references; this scraper splits that
into ``InDocketEntry`` rows on the docket itself plus a separate
``InDocument`` record per archived PDF (carrying ``local_path``).
"""

from __future__ import annotations

from datetime import date

from jkent.common.data_models import ScrapedData

# Map the site's per-case-result CourtCode letter to a CourtListener id.
# Site values are returned with trailing spaces (``"S  "``, ``"A  "``,
# ``"T  "``); strip before lookup.
COURT_CODE_TO_COURT_ID: dict[str, str] = {
    "S": "ind",
    "A": "indctapp",
    "T": "indtc",
}

# CourtListener id → human-readable label (mirror of the above).
COURT_IDS: dict[str, str] = {
    "ind": "Indiana Supreme Court",
    "indctapp": "Indiana Court of Appeals",
    "indtc": "Indiana Tax Court",
}

# Site CourtItemID values used in the search request body.
COURT_ITEM_ID_SUPREME: int = 96
COURT_ITEM_ID_COURT_OF_APPEALS: int = 95
COURT_ITEM_ID_TAX: int = 97
COURT_ITEM_ID_ALL_ODYSSEY: int = 92
COURT_ITEM_ID_ALL_APPELLATE: int = 94


class InAddress(ScrapedData):
    """A mailing address attached to a party or an attorney."""

    line_1: str | None = None
    line_2: str | None = None
    line_3: str | None = None
    line_4: str | None = None
    city: str | None = None
    state: str | None = None
    zip_code: str | None = None
    zip_4: str | None = None
    masked: bool = False


class InAttorney(ScrapedData):
    """An attorney representing a party in an appellate case.

    ``bar_number`` is the Indiana bar number as reported by Odyssey. The
    site renders it with a leading hash (``#2553049``); the scraper
    preserves the raw form so consumers can decide how to normalize.
    """

    name: str
    bar_number: str | None = None
    lead: bool = False
    label: str | None = None
    work_phone: str | None = None
    address: InAddress | None = None
    is_pro_se: bool = False


class InParty(ScrapedData):
    """A party in the case (Appellant, Appellee, Petitioner, …)."""

    name: str
    name_formatted: str | None = None
    role: str | None = None
    """Display label for the party's role, e.g. 'Appellant', 'Respondent'."""

    role_code: str | None = None
    """Short site code, e.g. ``PET``, ``RES``, ``APE``, ``APR``."""

    base_role: str | None = None
    """Coarse role bucket: ``PL`` (plaintiff-side) or ``DF`` (defendant-side)."""

    address: InAddress | None = None
    attorneys: list[InAttorney] = []


class InEventDocument(ScrapedData):
    """A document reference on a docket entry.

    This is the lightweight manifest row attached to ``InDocketEntry``.
    A separate ``InDocument`` is yielded for each downloaded file with
    its ``local_path``.
    """

    document_id: int
    name: str
    description: str | None = None
    date_filed: date | None = None
    page_count: int | None = None
    filename: str | None = None
    extension: str | None = None
    download_url: str | None = None


class InDocketEntry(ScrapedData):
    """A single entry in the chronological docket (Events list)."""

    event_key: str
    event_type: str
    """Site short code (e.g. ``ANOA``, ``ABRIEF``, ``AISSP``, ``APTRF``)."""

    base_event_type: str | None = None
    """Coarse bucket: ``C``, ``MOT``, ``ORD``, ``OTHER``."""

    date_filed: date | None = None
    description: str
    judge: str | None = None
    is_docketable: bool = True
    comment: str | None = None
    """Freeform note on the entry, often the order's holding."""

    secondary_date: date | None = None
    secondary_date_label: str | None = None
    """e.g. 'File Stamp', 'Date Sent'."""

    related_parties: list[str] = []
    """Names referenced by the entry (Attorney, Serve, …)."""

    documents: list[InEventDocument] = []


class InCrossReference(ScrapedData):
    """A cross-referenced cause number (e.g. trial-court Odyssey id)."""

    type: str
    """Site label, e.g. 'Original County Cause Number'."""

    key: str | None = None
    value: str


class InRelatedCase(ScrapedData):
    """A related case linked by Odyssey (typically the lower trial court)."""

    related_case_key: str
    related_case_number: str
    description: str | None = None


class InDocument(ScrapedData):
    """An archived PDF from the case docket.

    Yielded as a separate top-level record so it can be joined back to the
    parent ``InDocket`` via ``case_key`` (or ``docket_number``).
    """

    docket_number: str
    case_key: str
    document_id: int
    event_key: str
    name: str
    download_url: str
    date_filed: date | None = None
    page_count: int | None = None
    filename: str | None = None
    local_path: str | None = None
    """Filesystem path where the driver archived this document."""


class InDocket(ScrapedData):
    """A complete Indiana appellate-court docket."""

    # === Searchable fields ===
    docket_number: str
    """Public case number (e.g. ``26S-DI-00136``, ``26A-CR-00794``)."""

    court_id: str
    """One of ``ind`` / ``indctapp`` / ``indtc``."""

    case_key: str
    """Site internal numeric id (stable across searches)."""

    date_filed: date | None = None
    case_name: str

    # === Case metadata ===
    case_type: str | None = None
    """e.g. ``CR - Direct Appeals (Non Capital, Non-LWOP)``."""

    case_type_code: str | None = None
    """Short code, e.g. ``ADI`` for Attorney Discipline."""

    case_sub_type: str | None = None
    case_category: str | None = None
    """``Civil`` / ``Criminal`` / ``Family`` / ``Probate``."""

    case_category_code: str | None = None
    """``CV`` / ``CR`` / ``FAM`` / ``PR``."""

    case_status: str | None = None
    """e.g. ``Pending``, ``Closed``, ``Transfer Granted``, ``Transfer Denied``."""

    case_status_date: date | None = None
    is_active: bool | None = None
    is_public: bool | None = None

    # === Trial-court linkage ===
    trial_court_case_number: str | None = None
    """Trial-court docket id from ``Related`` (e.g. ``48C04-2406-F4-001929``)."""

    trial_court_case_key: str | None = None
    """Site internal key for the trial-court case."""

    cross_references: list[InCrossReference] = []
    related_cases: list[InRelatedCase] = []

    # === Nested data ===
    parties: list[InParty] = []
    entries: list[InDocketEntry] = []

    source_url: str | None = None
    """The CaseSummary API URL used to build this record."""
