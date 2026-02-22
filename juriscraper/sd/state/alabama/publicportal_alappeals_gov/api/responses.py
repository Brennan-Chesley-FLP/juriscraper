"""Pydantic models for Alabama Appellate Courts API responses.

These models validate the structure of JSON API responses from the
Alabama appellate courts public portal API.

IMPORTANT: These models use extra="forbid" to detect when the API
starts returning new fields. If validation fails due to unexpected
fields, update the models to include the new fields.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

# =============================================================================
# Common Models (shared across multiple endpoints)
# =============================================================================


class PageInfo(BaseModel):
    """Pagination information included in paginated responses."""

    model_config = ConfigDict(extra="forbid")

    size: int
    totalElements: int
    totalPages: int
    number: int


# =============================================================================
# Publications API Models (parse_publications_list)
# =============================================================================


class PublicationItem(BaseModel):
    """Individual case/opinion within a publication.

    Note: The list endpoint only returns caseNumber. Additional fields
    like title, decision, documents would come from a detail endpoint.
    """

    model_config = ConfigDict(extra="forbid")

    caseNumber: str


class Publication(BaseModel):
    """A publication (release list) containing multiple items."""

    model_config = ConfigDict(extra="forbid")

    publicationUUID: str
    courtID: str
    courtAbbreviation: str
    publicationNumber: str
    publicationName: str
    publicationDate: str
    publicationItems: list[PublicationItem] = []


class PublicationsEmbedded(BaseModel):
    """Embedded results for publications endpoint."""

    model_config = ConfigDict(extra="forbid")

    results: list[Publication] = []


class PublicationsListResponse(BaseModel):
    """Response from the publications endpoint.

    Endpoint: /courts/cms/publications
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    embedded: PublicationsEmbedded | None = Field(
        default=None, alias="_embedded"
    )
    page: PageInfo | None = None


# =============================================================================
# Events API Models (parse_events_list)
# =============================================================================


class Event(BaseModel):
    """A calendar event (oral argument session)."""

    model_config = ConfigDict(extra="forbid")

    eventUUID: str
    eventName: str | None = None
    eventStatusTypeID: str | None = None
    suppressCalendarAssignmentFlag: bool | None = None
    courtID: str | None = None
    courtAbbreviation: str | None = None
    courtSessionType: str | None = None
    panelFlag: bool | None = None
    startDate: str
    location: str | None = None


class EventsEmbedded(BaseModel):
    """Embedded results for events endpoint."""

    model_config = ConfigDict(extra="forbid")

    results: list[Event] = []


class EventsListResponse(BaseModel):
    """Response from the events endpoint.

    Endpoint: /courts/cms/events
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    embedded: EventsEmbedded | None = Field(default=None, alias="_embedded")
    page: PageInfo | None = None


# =============================================================================
# Event Hearings API Models (parse_event_hearings)
# =============================================================================


class HearingCaseHeader(BaseModel):
    """Case header within a hearing."""

    model_config = ConfigDict(extra="forbid")

    caseInstanceUUID: str
    caseNumber: str
    caseTitle: str | None = None
    courtID: str | None = None


class HearingEvent(BaseModel):
    """Event reference within a hearing."""

    model_config = ConfigDict(extra="forbid")

    panelFlag: bool | None = None


class Hearing(BaseModel):
    """A hearing (case scheduled for an oral argument session)."""

    model_config = ConfigDict(extra="forbid")

    startDate: str | None = None
    hearingType: str | None = None
    hearingStatus: str | None = None
    orderBy: int | None = None
    event: HearingEvent | None = None
    caseHeader: HearingCaseHeader


class HearingsEmbedded(BaseModel):
    """Embedded results for hearings endpoint."""

    model_config = ConfigDict(extra="forbid")

    results: list[Hearing] = []


class EventHearingsResponse(BaseModel):
    """Response from the event hearings endpoint.

    Endpoint: /courts/{court-guid}/cms/events/{event-uuid}/hearings
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    embedded: HearingsEmbedded | None = Field(default=None, alias="_embedded")
    page: PageInfo | None = None


# =============================================================================
# Dockets Search API Models (parse_dockets_search)
# =============================================================================


class SearchOriginatingCourtCase(BaseModel):
    """Lower court case information in search results."""

    model_config = ConfigDict(extra="forbid")

    originatingCourtName: str | None = None
    originatingCaseNumber: str | None = None


class SearchCaseHeader(BaseModel):
    """Case header in search results."""

    model_config = ConfigDict(extra="forbid")

    caseInstanceUUID: str
    caseNumber: str | None = None
    caseTitle: str | None = None
    courtID: int
    courtAbbreviation: str | None = None
    filedDate: str | None = None
    caseClassification: str | None = None
    caseClassificationID: str | None = None
    closedFlag: bool | None = None
    originatingCourtCases: list[SearchOriginatingCourtCase] = []


class SearchResult(BaseModel):
    """A single case in search results."""

    model_config = ConfigDict(extra="forbid")

    caseHeader: SearchCaseHeader


class SearchEmbedded(BaseModel):
    """Embedded results for dockets search endpoint."""

    model_config = ConfigDict(extra="forbid")

    results: list[SearchResult] = []


class DocketsSearchResponse(BaseModel):
    """Response from the dockets search endpoint.

    Endpoint: /courts/cms/cases
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    embedded: SearchEmbedded | None = Field(default=None, alias="_embedded")
    page: PageInfo | None = None


# =============================================================================
# Case Detail API Models (parse_case_detail)
# =============================================================================


class OriginatingCourtCase(BaseModel):
    """Lower court case information."""

    model_config = ConfigDict(extra="forbid")

    originatingCourtName: str | None = None
    originatingCaseNumber: str | None = None


class DetailCaseHeader(BaseModel):
    """Case header in detail response."""

    model_config = ConfigDict(extra="forbid")

    caseInstanceUUID: str
    caseNumber: str
    caseTitle: str | None = None
    caseCaption: str | None = None
    courtID: int | None = None
    filedDate: str | None = None
    caseClassification: str | None = None
    caseClassificationID: str | None = None
    caseClassGroupType: str | None = None
    caseClassGroupTypeID: str | None = None
    caseGroupFlag: bool | None = None
    caseGroupPublicFlag: bool | None = None
    closedFlag: bool | None = None
    location: str | None = None
    locationID: str | None = None
    panelFlag: bool | None = None
    originatingCourtCases: list[OriginatingCourtCase] = []


class CaseDetailResponse(BaseModel):
    """Response from the case detail endpoint.

    Endpoint: /courts/{court-guid}/cms/cases/{case-uuid}
    """

    model_config = ConfigDict(extra="forbid")

    caseHeader: DetailCaseHeader


# =============================================================================
# Case Parties API Models (parse_case_parties)
# =============================================================================


class PartyActorInstance(BaseModel):
    """Person or entity actor instance."""

    model_config = ConfigDict(extra="forbid")

    displayName: str
    sortName: str | None = None


class PartyHeader(BaseModel):
    """Party header containing party details."""

    model_config = ConfigDict(extra="forbid")

    casePartyUUID: str | None = None
    partyType: str | None = None
    partyTypeID: str | None = None
    partySubType: str | None = None
    partySubTypeID: str | None = None
    partyStatus: str | None = None
    partyStatusID: str | None = None
    partyActorInstance: PartyActorInstance | None = None


class AttorneyPartyHeader(BaseModel):
    """Attorney party header."""

    model_config = ConfigDict(extra="forbid")

    casePartyUUID: str | None = None
    partyActorInstance: PartyActorInstance | None = None


class LegalOrganizationPartyHeader(BaseModel):
    """Legal organization party header (e.g., law firms, AG office)."""

    model_config = ConfigDict(extra="forbid")

    casePartyUUID: str | None = None
    partyActorInstance: PartyActorInstance | None = None


class LegalRepresentation(BaseModel):
    """Attorney representation for a party."""

    model_config = ConfigDict(extra="forbid")

    attorneyPartyHeader: AttorneyPartyHeader | None = None
    legalOrganizationPartyHeader: LegalOrganizationPartyHeader | None = None
    primaryFlag: bool | None = None


class PartyCaseHeader(BaseModel):
    """Empty case header in party results."""

    model_config = ConfigDict(extra="forbid")


class Party(BaseModel):
    """A party in a case."""

    model_config = ConfigDict(extra="forbid")

    partyHeader: PartyHeader
    proSeFlag: bool | None = None
    orderBy: int | None = None
    partyNumber: int | None = None
    legalRepresentations: list[LegalRepresentation] = []
    involvementTypeID: str | None = None
    caseHeader: PartyCaseHeader | None = None


class PartiesEmbedded(BaseModel):
    """Embedded results for parties endpoint."""

    model_config = ConfigDict(extra="forbid")

    results: list[Party] = []


class CasePartiesResponse(BaseModel):
    """Response from the case parties endpoint.

    Endpoint: /courts/{court-guid}/cms/cases/{case-uuid}/parties
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    embedded: PartiesEmbedded | None = Field(default=None, alias="_embedded")
    page: PageInfo | None = None


# =============================================================================
# Docket Entries API Models (parse_docket_entries)
# =============================================================================


class DocketEntryHeader(BaseModel):
    """Header information for a docket entry."""

    model_config = ConfigDict(extra="forbid")

    docketEntryUUID: str | None = None
    docketEntryType: str | None = None
    docketEntryTypeID: str | None = None
    docketEntrySubType: str | None = None
    docketEntrySubTypeID: str | None = None
    docketEntryName: str | None = None
    docketEntryDescription: str | None = None
    docketEntryStatus: str | None = None
    docketEntryStatusID: str | None = None
    filedDate: str | None = None
    submittedDate: str | None = None
    official: bool | None = None
    securedDocument: bool | None = None
    security1: bool | None = None
    security2: bool | None = None
    security3: bool | None = None
    security4: bool | None = None
    security5: bool | None = None
    compositeSecurity: bool | None = None
    documentCount: int | None = None
    outcomeStatus: str | None = None
    outcomeStatusID: str | None = None


class SubmittedByPartyActorInstance(BaseModel):
    """Actor instance for submittedBy party."""

    model_config = ConfigDict(extra="forbid")

    sortName: str | None = None
    displayName: str | None = None


class SubmittedByParty(BaseModel):
    """Party info in submittedBy."""

    model_config = ConfigDict(extra="forbid")

    partyActorInstance: SubmittedByPartyActorInstance | None = None


class SubmittedByAttorney(BaseModel):
    """Attorney info in submittedBy."""

    model_config = ConfigDict(extra="forbid")

    partyActorInstance: SubmittedByPartyActorInstance | None = None


class SubmittedByEntry(BaseModel):
    """Entry in the submittedBy array."""

    model_config = ConfigDict(extra="forbid")

    party: SubmittedByParty | None = None
    attorney: SubmittedByAttorney | None = None


class DocketEntry(BaseModel):
    """A single docket entry."""

    model_config = ConfigDict(extra="forbid")

    docketEntryHeader: DocketEntryHeader
    submittedBy: list[SubmittedByEntry] = []
    otherSubmitter: str | None = None


class DocketEntriesEmbedded(BaseModel):
    """Embedded results for docket entries endpoint."""

    model_config = ConfigDict(extra="forbid")

    results: list[DocketEntry] = []


class DocketEntriesResponse(BaseModel):
    """Response from the docket entries endpoint.

    Endpoint: /courts/{court-guid}/cms/cases/{case-uuid}/docketentries
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    embedded: DocketEntriesEmbedded | None = Field(
        default=None, alias="_embedded"
    )
    page: PageInfo | None = None
