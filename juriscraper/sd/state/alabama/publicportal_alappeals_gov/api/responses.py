"""Pydantic models for Alabama Appellate Courts API responses.

These models validate the structure of JSON API responses from the
Alabama appellate courts public portal API.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

# =============================================================================
# Common Models (shared across multiple endpoints)
# =============================================================================


class PageInfo(BaseModel):
    """Pagination information included in paginated responses."""

    model_config = ConfigDict(extra="allow")

    size: int
    totalElements: int
    totalPages: int
    number: int


class Link(BaseModel):
    """HAL-style link."""

    model_config = ConfigDict(extra="allow")

    href: str


class Links(BaseModel):
    """HAL-style links collection."""

    model_config = ConfigDict(extra="allow")

    self: Link | None = None
    first: Link | None = None
    last: Link | None = None
    next: Link | None = None
    prev: Link | None = None


# =============================================================================
# Publications API Models (parse_publications_list)
# =============================================================================


class PublicationDocument(BaseModel):
    """Document attached to a publication item."""

    model_config = ConfigDict(extra="allow")

    documentLinkUUID: str
    documentName: str | None = None
    documentType: str | None = None


class PublicationItem(BaseModel):
    """Individual case/opinion within a publication."""

    model_config = ConfigDict(extra="allow")

    publicationItemUUID: str | None = None
    caseInstanceUUID: str
    caseNumber: str
    groupName: str | None = None
    title: str
    decision: str | None = None
    documents: list[PublicationDocument] = []


class Publication(BaseModel):
    """A publication (release list) containing multiple items."""

    model_config = ConfigDict(extra="allow")

    publicationUUID: str
    courtID: str | None = None
    courtAbbreviation: str | None = None
    publicationNumber: str | None = None
    scheduledDate: str
    publicationItems: list[PublicationItem] = []


class PublicationsEmbedded(BaseModel):
    """Embedded results for publications endpoint."""

    model_config = ConfigDict(extra="allow")

    results: list[Publication] = []


class PublicationsListResponse(BaseModel):
    """Response from the publications endpoint.

    Endpoint: /courts/cms/publications
    """

    model_config = ConfigDict(extra="allow")

    _embedded: PublicationsEmbedded | None = None
    _links: Links | None = None
    page: PageInfo | None = None


# =============================================================================
# Events API Models (parse_events_list)
# =============================================================================


class Event(BaseModel):
    """A calendar event (oral argument session)."""

    model_config = ConfigDict(extra="allow")

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

    model_config = ConfigDict(extra="allow")

    results: list[Event] = []


class EventsListResponse(BaseModel):
    """Response from the events endpoint.

    Endpoint: /courts/cms/events
    """

    model_config = ConfigDict(extra="allow")

    _embedded: EventsEmbedded | None = None
    _links: Links | None = None
    page: PageInfo | None = None


# =============================================================================
# Event Hearings API Models (parse_event_hearings)
# =============================================================================


class HearingCaseHeader(BaseModel):
    """Case header within a hearing."""

    model_config = ConfigDict(extra="allow")

    caseInstanceUUID: str
    caseNumber: str
    caseTitle: str | None = None
    courtID: str | None = None


class HearingEvent(BaseModel):
    """Event reference within a hearing."""

    model_config = ConfigDict(extra="allow")

    panelFlag: bool | None = None


class Hearing(BaseModel):
    """A hearing (case scheduled for an oral argument session)."""

    model_config = ConfigDict(extra="allow")

    startDate: str | None = None
    hearingType: str | None = None
    hearingStatus: str | None = None
    orderBy: int | None = None
    event: HearingEvent | None = None
    caseHeader: HearingCaseHeader


class HearingsEmbedded(BaseModel):
    """Embedded results for hearings endpoint."""

    model_config = ConfigDict(extra="allow")

    results: list[Hearing] = []


class EventHearingsResponse(BaseModel):
    """Response from the event hearings endpoint.

    Endpoint: /courts/{court-guid}/cms/events/{event-uuid}/hearings
    """

    model_config = ConfigDict(extra="allow")

    _embedded: HearingsEmbedded | None = None
    _links: Links | None = None
    page: PageInfo | None = None


# =============================================================================
# Dockets Search API Models (parse_dockets_search)
# =============================================================================


class SearchCaseHeader(BaseModel):
    """Case header in search results."""

    model_config = ConfigDict(extra="allow")

    caseInstanceUUID: str
    caseNumber: str | None = None
    caseTitle: str | None = None
    caseCaption: str | None = None
    courtID: int
    courtAbbreviation: str | None = None
    filedDate: str | None = None
    caseClassification: str | None = None
    closedFlag: bool | None = None


class SearchResult(BaseModel):
    """A single case in search results."""

    model_config = ConfigDict(extra="allow")

    caseHeader: SearchCaseHeader


class SearchEmbedded(BaseModel):
    """Embedded results for dockets search endpoint."""

    model_config = ConfigDict(extra="allow")

    results: list[SearchResult] = []


class DocketsSearchResponse(BaseModel):
    """Response from the dockets search endpoint.

    Endpoint: /courts/cms/cases
    """

    model_config = ConfigDict(extra="allow")

    _embedded: SearchEmbedded | None = None
    _links: Links | None = None
    page: PageInfo | None = None


# =============================================================================
# Case Detail API Models (parse_case_detail)
# =============================================================================


class OriginatingCourtCase(BaseModel):
    """Lower court case information."""

    model_config = ConfigDict(extra="allow")

    originatingCourtName: str | None = None
    originatingCaseNumber: str | None = None


class DetailCaseHeader(BaseModel):
    """Case header in detail response."""

    model_config = ConfigDict(extra="allow")

    caseInstanceUUID: str
    caseNumber: str
    caseTitle: str | None = None
    caseCaption: str | None = None
    courtID: int | None = None
    courtAbbreviation: str | None = None
    filedDate: str | None = None
    caseClassification: str | None = None
    closedFlag: bool | None = None
    originatingCourtCases: list[OriginatingCourtCase] = []


class CaseDetailResponse(BaseModel):
    """Response from the case detail endpoint.

    Endpoint: /courts/{court-guid}/cms/cases/{case-uuid}
    """

    model_config = ConfigDict(extra="allow")

    caseHeader: DetailCaseHeader


# =============================================================================
# Case Parties API Models (parse_case_parties)
# =============================================================================


class Actor(BaseModel):
    """Person or entity actor."""

    model_config = ConfigDict(extra="allow")

    displayName: str
    sortName: str | None = None


class LegalRepresentation(BaseModel):
    """Attorney representation for a party."""

    model_config = ConfigDict(extra="allow")

    legalRepresentationUUID: str | None = None
    primaryFlag: bool | None = None
    actor: Actor | None = None


class Party(BaseModel):
    """A party in a case."""

    model_config = ConfigDict(extra="allow")

    casePartyUUID: str | None = None
    partyType: str | None = None
    partySubType: str | None = None
    partyStatus: str | None = None
    proSeFlag: bool | None = None
    actor: Actor | None = None
    legalRepresentations: list[LegalRepresentation] = []
    orderBy: int | None = None
    partyNumber: int | None = None


class PartiesEmbedded(BaseModel):
    """Embedded results for parties endpoint."""

    model_config = ConfigDict(extra="allow")

    results: list[Party] = []


class CasePartiesResponse(BaseModel):
    """Response from the case parties endpoint.

    Endpoint: /courts/{court-guid}/cms/cases/{case-uuid}/parties
    """

    model_config = ConfigDict(extra="allow")

    _embedded: PartiesEmbedded | None = None
    _links: Links | None = None
    page: PageInfo | None = None


# =============================================================================
# Docket Entries API Models (parse_docket_entries)
# =============================================================================


class DocketEntryHeader(BaseModel):
    """Header information for a docket entry."""

    model_config = ConfigDict(extra="allow")

    docketEntryUUID: str | None = None
    docketEntryType: str | None = None
    docketEntrySubType: str | None = None
    filedDate: str | None = None
    description: str | None = None
    documentCount: int | None = None


class DocketEntry(BaseModel):
    """A single docket entry."""

    model_config = ConfigDict(extra="allow")

    docketEntryHeader: DocketEntryHeader
    documentCount: int | None = None


class DocketEntriesEmbedded(BaseModel):
    """Embedded results for docket entries endpoint."""

    model_config = ConfigDict(extra="allow")

    results: list[DocketEntry] = []


class DocketEntriesResponse(BaseModel):
    """Response from the docket entries endpoint.

    Endpoint: /courts/{court-guid}/cms/cases/{case-uuid}/docketentries
    """

    model_config = ConfigDict(extra="allow")

    _embedded: DocketEntriesEmbedded | None = None
    _links: Links | None = None
    page: PageInfo | None = None
