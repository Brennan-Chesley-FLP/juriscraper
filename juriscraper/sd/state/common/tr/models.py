"""Base data models for TR Portal (Thomson Reuters C-Track) scrapers.

These models provide the common structure for dockets, docket entries,
and oral arguments scraped from TR Portal deployments. State-specific
scrapers can use these directly or extend them with additional fields.
"""

from __future__ import annotations

from datetime import date
from typing import TypedDict

from kent.common.data_models import ScrapedData


class TRCourtConfig(TypedDict):
    """Configuration for a court in a TR Portal deployment.

    Fields:
        name: Human-readable court name
        court_guid: UUID identifying the court in the API
        numeric_id: Numeric/string court identifier from the API
            (the externalIdentifier / courtID field)
        abbreviation: Court abbreviation as returned by the API
            (the courtAbbreviation field)
    """

    name: str
    court_guid: str
    numeric_id: str
    abbreviation: str


class TRDocketEntry(ScrapedData):
    """A docket entry from a TR Portal court system.

    Represents a single filing/document in a case's docket.
    """

    date_filed: date | None = None
    """Date the document was filed"""

    document_type: str | None = None
    """Document type (e.g., 'Filing', 'Initiating Document')"""

    document_subtype: str | None = None
    """Document subtype (more specific classification)"""

    description: str | None = None
    """Document description"""

    document_url: str | None = None
    """URL to the document (if available)"""

    document_uuid: str | None = None
    """UUID for the document"""


class TRDocket(ScrapedData):
    """A docket from a TR Portal court system.

    Represents a complete case with all its metadata including
    parties and docket entries.
    """

    # === Searchable fields ===
    case_instance_uuid: str
    """Case instance UUID - the unique identifier for the case"""

    case_number: str
    """Case number (e.g., 'S072851', 'A190411')"""

    court_id: str
    """Court identifier (e.g., 'or', 'orctapp', 'ala')"""

    date_filed: date | None = None
    """Date the case was filed"""

    # === Required fields ===
    case_name: str
    """Case name/style"""

    # === Case metadata ===
    case_classification: str | None = None
    """Case classification/type"""

    originating_court: str | None = None
    """Originating/lower court name"""

    originating_court_number: str | None = None
    """Originating court case number"""

    # === Case status ===
    status: str | None = None
    """Current case status"""

    # === Parties ===
    parties: list[dict] = []
    """List of parties with their roles, attorneys, and status"""

    # === Document history ===
    entries: list[TRDocketEntry] = []
    """All docket entries"""

    # === Oral arguments ===
    oral_arguments: list[dict] = []
    """Scheduled oral arguments for this case"""

    # === Source tracking ===
    source_url: str | None = None
    """URL of the case detail page"""

    # === API metadata ===
    court_guid: str | None = None
    """Court GUID used in API calls"""


class TRDocument(ScrapedData):
    """A document attached to a docket entry on a TR Portal court.

    Yielded as a separate top-level record so it can be joined back to
    the parent TRDocket via ``case_instance_uuid``, and to the specific
    docket entry via ``docket_entry_uuid``.
    """

    case_number: str
    """Case number this document belongs to."""

    court_id: str
    """Court identifier (e.g., 'nd', 'or', 'wyo')."""

    case_instance_uuid: str
    """Case instance UUID — joins back to the parent TRDocket."""

    docket_entry_uuid: str | None = None
    """UUID of the parent docket entry (when known)."""

    document_link_uuid: str
    """The TR Portal documentLinkUUID identifying the physical file."""

    document_name: str | None = None
    document_type: str | None = None

    content_type: str | None = None
    """MIME type from documentInfo.contentType (e.g., 'application/pdf')."""

    file_extension: str | None = None
    page_count: int | None = None
    file_size: int | None = None

    download_url: str | None = None
    local_path: str | None = None
    """Filesystem path where the driver archived this document."""


class TROralArgument(ScrapedData):
    """An oral argument from a TR Portal court system."""

    # === Searchable fields ===
    case_number: str
    """Case number"""

    court_id: str
    """Court identifier"""

    date_argued: date
    """Date the oral argument is/was scheduled"""

    # === Required fields ===
    case_name: str
    """Case name"""

    # === Source tracking ===
    source_url: str | None = None
    """URL of the case detail page"""

    # === Calendar metadata ===
    calendar_uuid: str | None = None
    """UUID for the calendar entry"""

    case_instance_uuid: str | None = None
    """UUID for the case instance"""
