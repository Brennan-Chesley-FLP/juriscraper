"""Base data models for TR Portal (Thomson Reuters C-Track) scrapers.

These models provide the common structure for dockets, docket entries,
parties, and oral arguments scraped from TR Portal deployments.
State-specific scrapers can use these directly or extend them with
additional fields.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import TypedDict

from jkent.common.data_models import ScrapedData


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


class TRDocketEntryActor(ScrapedData):
    """An actor (party or attorney) associated with a docket entry filing.

    Pulled from the ``submittedBy`` list on each docket entry.
    """

    display_name: str
    """Display name of the actor (e.g., 'Doe, John')."""

    sort_name: str | None = None
    """Name used for sorting (e.g., 'DOE JOHN')."""


class TRDocketEntry(ScrapedData):
    """A docket entry from a TR Portal court system.

    Represents a single filing/document in a case's docket. Field names
    mirror the ``docketEntryHeader`` keys from the API where reasonable.
    """

    docket_entry_uuid: str | None = None
    """UUID for the docket entry itself."""

    date_filed: date | None = None
    """Date the document was filed (date portion of ``filedDate``)."""

    datetime_filed: datetime | None = None
    """Full timestamp the document was filed (from ``filedDate``)."""

    date_submitted: datetime | None = None
    """Timestamp the document was submitted (from ``submittedDate``).

    Distinct from filed date: submission is when the filer transmitted
    the document; filed date is when the court accepted it.
    """

    document_type: str | None = None
    """Entry type string (e.g., 'Filing'), from ``docketEntryType``."""

    document_type_id: int | None = None
    """Numeric ID of the entry type, from ``docketEntryTypeID``."""

    document_subtype: str | None = None
    """Entry subtype string, from ``docketEntrySubType``."""

    document_subtype_id: int | None = None
    """Numeric ID of the entry subtype, from ``docketEntrySubTypeID``."""

    entry_name: str | None = None
    """Display name of the entry, from ``docketEntryName``."""

    entry_status: str | None = None
    """Status string (e.g., 'Filed'), from ``docketEntryStatus``."""

    entry_status_id: int | None = None
    """Numeric ID of the entry status, from ``docketEntryStatusID``."""

    description: str | None = None
    """Free-form description, from ``docketEntryDescription``."""

    outcome_status: str | None = None
    """Outcome string (e.g., 'Granted'), from ``outcomeStatus``.

    Only populated for entries involving a judicial determination.
    """

    outcome_status_id: int | None = None
    """Numeric ID of the outcome status, from ``outcomeStatusID``."""

    official: bool | None = None
    """Whether the entry is an official court action, from ``official``."""

    document_count: int | None = None
    """Number of documents attached, from ``documentCount``."""

    secured_document: bool | None = None
    """Whether attached documents are secured, from ``securedDocument``."""

    security_1: bool | None = None
    """Granular security flag, from ``security1``."""

    security_2: bool | None = None
    """Granular security flag, from ``security2``."""

    security_3: bool | None = None
    """Granular security flag, from ``security3``."""

    security_4: bool | None = None
    """Granular security flag, from ``security4``."""

    security_5: bool | None = None
    """Granular security flag, from ``security5``."""

    composite_security: bool | None = None
    """Composite security flag, from ``compositeSecurity``."""

    submitted_by: list[TRDocketEntryActor] = []
    """Actors who submitted this entry, from ``submittedBy``."""

    document_url: str | None = None
    """URL to a single attached document, when known.

    Most TR scrapers emit attachments as separate TRDocument records.
    This field is kept for legacy callers; new code should use the
    documents flow instead.
    """


class TRRepresentative(ScrapedData):
    """An attorney (or other legal representative) of a party.

    Pulled from each party's ``legalRepresentations`` list.
    """

    case_party_uuid: str | None = None
    """UUID of the party this representative represents."""

    name: str
    """Display name (from ``attorneyPartyHeader.partyActorInstance.displayName``)."""

    sort_name: str | None = None
    """Sort name (from ``attorneyPartyHeader.partyActorInstance.sortName``)."""

    primary_flag: bool | None = None
    """Whether this is the party's primary representative."""


class TRParty(ScrapedData):
    """A party in a case from a TR Portal court system.

    Mirrors the fields available in the ``partyHeader`` block plus the
    party-level flags returned alongside it.
    """

    case_party_uuid: str | None = None
    """UUID for this party in this case, from ``casePartyUUID``."""

    name: str
    """Party display name (from ``partyHeader.partyActorInstance.displayName``)."""

    sort_name: str | None = None
    """Sort name (from ``partyHeader.partyActorInstance.sortName``)."""

    party_type: str | None = None
    """Top-level party type, from ``partyType`` (e.g., 'Party')."""

    party_type_id: int | None = None
    """Numeric ID of the party type, from ``partyTypeID``."""

    party_subtype: str | None = None
    """Party subtype / role, from ``partySubType`` (e.g., 'Appellant')."""

    party_subtype_id: int | None = None
    """Numeric ID of the party subtype, from ``partySubTypeID``."""

    status: str | None = None
    """Party status string, from ``partyStatus``."""

    status_id: int | None = None
    """Numeric ID of the party status, from ``partyStatusID``."""

    pro_se_flag: bool | None = None
    """Whether this party is self-represented, from ``proSeFlag``."""

    order_by: int | None = None
    """Display ordering hint, from ``orderBy``."""

    party_number: int | None = None
    """Party number within the case, from ``partyNumber``."""

    involvement_type_id: int | None = None
    """Numeric ID of the involvement type, from ``involvementTypeID``."""

    non_public_flag: bool | None = None
    """Whether the party record is non-public, from ``nonPublicFlag``."""

    representatives: list[TRRepresentative] = []
    """Legal representatives for this party."""


class TROriginatingCase(ScrapedData):
    """A lower-court case from which a TR Portal appellate case originated.

    Pulled from each entry of ``caseHeader.originatingCourtCases``.
    """

    court_name: str | None = None
    """Originating court name, from ``originatingCourtName``."""

    case_number: str | None = None
    """Case number in the originating court, from ``originatingCaseNumber``."""


class TRTicklerDueFrom(ScrapedData):
    """A party a tickler deadline runs from.

    Pulled from each entry of a tickler's ``dueFroms`` list.
    """

    sort_name: str | None = None
    """Sort name of the responsible party, from
    ``partyActorInstance.sortName``."""


class TRTickler(ScrapedData):
    """A tickler (upcoming case deadline) from a TR Portal court system.

    Ticklers track a case's scheduled deadlines — the briefing schedule,
    record/transcript due dates, corrections due, etc. Pulled from the
    per-case ``/ticklers`` endpoint (the portal's "Ticklers" tab).

    Not every C-Track deployment populates ticklers; some expose the
    endpoint but return no rows.
    """

    due_date: date | None = None
    """Date the item is due (date portion of ``dueDate``)."""

    tickler_type: str | None = None
    """Deadline type string (e.g., 'Appellant Brief Due'), from
    ``ticklerType``."""

    tickler_type_id: int | None = None
    """Numeric ID of the tickler type, from ``ticklerTypeID``."""

    tickler_status: str | None = None
    """Status string (e.g., 'Open', 'Satisfied'), from ``ticklerStatus``."""

    tickler_status_id: int | None = None
    """Numeric ID of the tickler status, from ``ticklerStatusID``."""

    due_froms: list[TRTicklerDueFrom] = []
    """Parties the deadline runs from, from ``dueFroms``."""

    docket_entry_uuid: str | None = None
    """UUID of the docket entry that triggered this deadline, from
    ``docketEntryHeader.docketEntryUUID`` (when the API includes it)."""


class TRDocket(ScrapedData):
    """A docket from a TR Portal court system.

    Represents a complete case with all its metadata including
    parties and docket entries.
    """

    # === Searchable fields ===
    case_instance_uuid: str
    """Case instance UUID - the unique identifier for the case"""

    docket_number: str
    """Docket / case number (e.g., 'S072851', 'A190411'). Maps to
    CourtListener ``Docket.docket_number``; the API value is already clean
    so no separate ``docket_number_raw`` is carried."""

    court: str
    """CourtListener court ID (e.g., 'or', 'orctapp', 'ala'). Maps to
    ``Docket.court``; one of the scraper's ``court_ids``."""

    date_filed: date | None = None
    """Date the case was filed (date portion of ``filedDate``)."""

    datetime_filed: datetime | None = None
    """Full timestamp the case was filed (from ``filedDate``)."""

    # === Required fields ===
    case_name: str
    """Case name. Prefers ``caseHeader.caseCaption``, falls back to
    ``caseHeader.caseTitle``. Suitable for display."""

    case_name_full: str | None = None
    """Raw ``caseHeader.caseTitle`` — the long-form case title."""

    case_caption: str | None = None
    """Raw ``caseHeader.caseCaption`` — the courthouse-displayed caption."""

    # === Case metadata ===
    case_classification: str | None = None
    """Case classification (e.g., 'Appeal - Civil - Other'), from
    ``caseClassification``."""

    classification_id: int | None = None
    """Numeric ID of the case classification, from ``caseClassificationID``."""

    class_group_type: str | None = None
    """Case class group type string, from ``caseClassGroupType``."""

    class_group_type_id: int | None = None
    """Numeric ID of the class group type, from ``caseClassGroupTypeID``."""

    court_abbreviation: str | None = None
    """Court abbreviation as returned by the API (e.g., '1DCA'), from
    ``caseHeader.courtAbbreviation``."""

    location: str | None = None
    """Location name within the court, from ``caseHeader.location``."""

    location_id: int | None = None
    """Numeric ID of the location, from ``caseHeader.locationID``."""

    case_group_flag: bool | None = None
    """Whether the case is part of a case group, from ``caseGroupFlag``."""

    panel_flag: bool | None = None
    """Whether a panel has been assigned, from ``panelFlag``."""

    originating_cases: list[TROriginatingCase] = []
    """All lower-court cases this case originated from."""

    # === Case status ===
    status: str | None = None
    """Current case status"""

    # === Parties ===
    parties: list[TRParty] = []
    """Parties in the case, each with its attorneys."""

    # === Document history ===
    entries: list[TRDocketEntry] = []
    """All docket entries"""

    # === Oral arguments ===
    oral_arguments: list[dict] = []
    """Scheduled oral arguments for this case"""

    # === Ticklers (deadlines) ===
    ticklers: list[TRTickler] = []
    """Scheduled case deadlines (briefing schedule, record/transcript due
    dates, etc.), from the per-case ticklers endpoint. Only populated for
    courts whose scraper sets ``TR_FETCH_TICKLERS`` and that expose data."""

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

    docket_number: str
    """Docket / case number this document belongs to."""

    court: str
    """CourtListener court ID (e.g., 'nd', 'or', 'wyo')."""

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
    docket_number: str
    """Docket / case number"""

    court: str
    """CourtListener court ID"""

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
