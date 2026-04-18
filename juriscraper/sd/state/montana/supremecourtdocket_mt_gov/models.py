"""Data models for the Montana Supreme Court scraper.

Only one CourtListener court id is involved: `mont` (Montana Supreme Court).
The site exposes cases across three UI categories (active, closed 2006+,
archive 1979-2005) that all map to the same court.
"""

from __future__ import annotations

from datetime import date

from jkent.common.data_models import ScrapedData


class MtAttorney(ScrapedData):
    """An attorney representing a party.

    The site's party payload joins multiple attorneys into a single comma-
    separated string; the scraper splits that into individual records.
    """

    name: str


class MtParty(ScrapedData):
    """A party in the case."""

    name: str
    role: str | None = None
    """Appellate role: 'Appellant', 'Appellee', 'Real Party in Interest', etc."""

    comment: str | None = None
    attorneys: list[MtAttorney] = []


class MtDocketEntry(ScrapedData):
    """A single entry from the case's `dockets` list.

    Document references are captured on the entry as a lightweight manifest
    (numbers + sealed flag). Full MtDocument records are yielded separately
    with the archived file's `local_path`.
    """

    date_filed: date | None = None
    description: str
    document_numbers: list[str] = []
    """ctrackIds or filenet object ids referenced by this entry."""

    has_sealed_documents: bool = False


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

    description: str | None = None
    """Docket entry description (for context)."""


class MtDocument(ScrapedData):
    """An archived document from the case's docket.

    Yielded as a separate top-level record so it can be joined back to the
    parent MtDocket via ``case_id`` (or ``docket_number`` for pre-2006
    cases, where ``case_id`` is null).
    """

    docket_number: str
    case_id: int | None = None

    document_id: str
    """Either a numeric ctrackId (modern) or a filenet object id in curly
    braces (pre-2006)."""

    document_location: str
    """Original filename (e.g., '531465.pdf' or '99-565.pdf')."""

    download_url: str

    date_filed: date | None = None
    description: str | None = None

    local_path: str | None = None
    """Filesystem path where the driver archived this document."""


class MtDocket(ScrapedData):
    """A complete Montana Supreme Court docket."""

    # === Searchable fields ===
    docket_number: str
    """Public case number (e.g., 'DA 26-0218', '04-164', '99-565')."""

    court_id: str = "mont"
    """Always 'mont' (Montana Supreme Court)."""

    case_id: int | None = None
    """Montana's internal numeric case id. Null for pre-2006 archive cases."""

    date_filed: date | None = None
    case_name: str

    # === Case metadata ===
    case_type: str | None = None
    case_status: str | None = None
    """Short status code returned by the API (e.g., 'PB', 'C')."""

    full_caption: str | None = None
    summary: str | None = None
    citation: str | None = None

    original_court: str | None = None
    """Trial court or agency name."""

    original_case_number: str | None = None
    """Trial-court docket id."""

    trial_court_judge: str | None = None
    """Only populated for pre-2006 archive cases."""

    category: str
    """Which search category yielded this case: 'active', 'closed', 'archive'."""

    # === Nested data ===
    parties: list[MtParty] = []
    entries: list[MtDocketEntry] = []

    source_url: str | None = None
    """The case-detail API URL used to build this record."""
