"""Data models for the Montana Supreme Court scraper.

Only one CourtListener court id is involved: ``mont`` (Montana Supreme
Court). The site exposes cases across three UI categories (active, closed
2006+, archive 1979-2005) that all map to the same court.

Field names follow [`../../CL_MODELS.md`](../../CL_MODELS.md): the
CourtListener court-id string is ``court`` (not ``court_id``), the public
case identifier is ``docket_number``, and dates use the ``date_*`` prefix.
"""

from __future__ import annotations

from datetime import date

from jkent.common.data_models import ScrapedData

from juriscraper.state.common_models import CleanString, HarmonizedCaseName

COURT_ID: str = "mont"


class MtAttorney(ScrapedData):
    """An attorney representing a party.

    The site's party payload joins multiple attorneys into a single comma-
    separated string; the scraper splits that into individual records.
    Maps to CourtListener ``Attorney``.
    """

    name: CleanString
    """The attorney's name."""


class MtParty(ScrapedData):
    """A party in the case. Maps to CourtListener ``Party`` + ``PartyType``."""

    name: CleanString
    """The party's name."""

    role: CleanString | None = None
    """Appellate role: ``Appellant``, ``Appellee``,
    ``Real Party in Interest``, etc."""

    comment: CleanString | None = None
    """Free-text comment the API attaches to the party, if any."""

    attorneys: list[MtAttorney] = []
    """Attorneys representing this party."""


class MtDocketEntry(ScrapedData):
    """A single entry from the case's ``dockets`` list.

    Maps to CourtListener ``DocketEntry``. Document references are captured
    on the entry as a lightweight manifest (numbers + sealed flag); full
    ``MtDocument`` records are yielded separately with the archived file's
    ``local_path``.
    """

    date_filed: date | None = None
    """Filing date of the docket entry."""

    description: CleanString
    """Text content of the docket entry (``documentDescription``)."""

    document_numbers: list[str] = []
    """ctrackIds or filenet object ids referenced by this entry."""

    has_sealed_documents: bool = False
    """True when at least one referenced document is sealed/unavailable."""


class MtSealedDocument(ScrapedData):
    """A reference to an unviewable document (``Unavailable.pdf``).

    The site renders these rows with ``documentLocation == "Unavailable.pdf"``,
    ``documentId == "0"`` and ``filenetObjectId == "{0}"``. We never trigger
    a download for them; this record exists to capture the fact that the
    docket entry was sealed/redacted.
    """

    docket_number: str
    """Public case number the sealed document belongs to."""

    case_id: int | None = None
    """Montana's internal case id (null for pre-2006 archive cases)."""

    document_index: int
    """Position of this document inside its docket entry (0-based)."""

    date_filed: date | None = None
    """Filing date of the docket entry the document belongs to."""

    description: CleanString | None = None
    """Docket entry description (for context)."""

    source_entry_point: str | None = None
    """The entry point that produced this record."""


class MtDocument(ScrapedData):
    """An archived document from the case's docket.

    Maps to CourtListener ``RECAPDocument``. Yielded as a separate
    top-level record so it can be joined back to the parent ``MtDocket`` via
    ``case_id`` (or ``docket_number`` for pre-2006 cases, where ``case_id``
    is null).
    """

    docket_number: str
    """Public case number this document belongs to."""

    case_id: int | None = None
    """Montana's internal case id (null for pre-2006 archive cases)."""

    document_id: str
    """Either a numeric ctrackId (modern) or a filenet object id in curly
    braces (pre-2006)."""

    document_location: str
    """Original filename (e.g., ``531465.pdf`` or ``99-565.pdf``)."""

    download_url: str
    """The filenet endpoint URL the bytes were fetched from."""

    date_filed: date | None = None
    """Filing date of the parent docket entry."""

    description: CleanString | None = None
    """Parent docket entry description (for context)."""

    local_path: str | None = None
    """Filesystem path where the driver archived this document."""

    source_entry_point: str | None = None
    """The entry point that produced this record."""


class MtDocket(ScrapedData):
    """A complete Montana Supreme Court docket. Maps to CourtListener
    ``Docket``."""

    # === Searchable fields ===
    docket_number: str
    """Public case number (e.g., ``DA 26-0218``, ``04-164``, ``99-565``)."""

    court: str = COURT_ID
    """CourtListener court id; always ``mont`` (Montana Supreme Court)."""

    case_id: int | None = None
    """Montana's internal numeric case id. Null for pre-2006 archive cases."""

    date_filed: date | None = None
    """Date the case was filed (null on pre-2006 archive records)."""

    case_name: HarmonizedCaseName
    """Standard name of the case (the short caption)."""

    # === Case metadata ===
    case_type: CleanString | None = None
    """e.g. ``Direct Appeal - Domestic Relations``."""

    case_status: CleanString | None = None
    """Short status code returned by the API (e.g., ``PB``, ``C``)."""

    full_caption: CleanString | None = None
    """Full caption (``fullTitle``); often CRLF-delimited."""

    summary: CleanString | None = None
    """Case summary, when present (rare)."""

    citation: CleanString | None = None
    """Citation for decided cases (e.g., ``2002 MT 40N``)."""

    original_court: CleanString | None = None
    """Trial court or agency name (lower court)."""

    original_case_number: CleanString | None = None
    """Trial-court docket id."""

    trial_court_judge: CleanString | None = None
    """Presiding trial-court judge; only populated for pre-2006 archive
    cases."""

    category: str
    """Which search category yielded this case: ``active``, ``closed``,
    ``archive``."""

    # === Nested data ===
    parties: list[MtParty] = []
    """Parties to the case."""

    entries: list[MtDocketEntry] = []
    """Docket entries (the case's ``dockets`` list)."""

    source_url: str | None = None
    """The case-detail API URL used to build this record."""

    source_entry_point: str | None = None
    """The entry point that produced this record."""
