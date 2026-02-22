"""Pydantic models for Alabama Appellate Courts JSON API responses.

These models define the expected structure of API responses for post-hoc
validation. They are used by the diagnostic validation system to identify
when API responses have changed from their expected structure.

Models are organized by API endpoint:
- Publications: parse_publications_list
- Events: parse_events_list
- Event Hearings: parse_event_hearings
- Dockets Search: parse_dockets_search
- Case Detail: parse_case_detail
- Case Parties: parse_case_parties
- Docket Entries: parse_docket_entries
"""

from .responses import (
    CaseDetailResponse,
    CasePartiesResponse,
    DocketEntriesResponse,
    DocketsSearchResponse,
    EventHearingsResponse,
    EventsListResponse,
    PublicationsListResponse,
)

__all__ = [
    "PublicationsListResponse",
    "EventsListResponse",
    "EventHearingsResponse",
    "DocketsSearchResponse",
    "CaseDetailResponse",
    "CasePartiesResponse",
    "DocketEntriesResponse",
]
