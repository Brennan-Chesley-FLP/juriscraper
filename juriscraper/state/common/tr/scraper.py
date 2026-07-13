"""Base mixin for TR Portal (Thomson Reuters C-Track) scrapers.

Provides common infrastructure for scraping the TR Portal API:
- Date parsing and formatting
- Court configuration lookups
- Docket scraping flow (search -> detail -> parties -> entries)
- Events/oral arguments flow (events -> hearings)
- Publications/opinions flow (list -> detail)

State-specific scrapers inherit from this mixin and BaseScraper,
define their own @entry/@step methods, and delegate to the mixin's
generator methods via ``yield from``.

Required class variables on the subclass:
    TR_API_BASE_URL: API base URL (e.g., "https://trportal-api.courts.oregon.gov")
    TR_PORTAL_URL: Portal base URL (e.g., "https://trportal.courts.oregon.gov")
    TR_COURT_CONFIG: dict mapping court_id -> TRCourtConfig

Required class variables for model creation:
    DOCKET_CLASS: type  -- the docket ScrapedData subclass
    DOCKET_ENTRY_CLASS: type  -- the docket entry ScrapedData subclass
    DOCUMENT_CLASS: type  -- the document ScrapedData subclass
    ORAL_ARGUMENT_CLASS: type  -- the oral argument ScrapedData subclass

Expected step method names on the subclass (referenced by continuations):
    parse_dockets_search, parse_case_detail, parse_case_parties,
    parse_docket_entries, parse_documents_list, parse_document_download,
    parse_events_list, parse_event_hearings,
    parse_publications_list, parse_publication_detail

Subclasses that set ``TR_FETCH_TICKLERS = True`` must additionally define a
``parse_ticklers_list`` step (see North Dakota / Oregon / Wyoming).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING, ClassVar
from urllib.parse import urlencode

from jkent.data_types import (
    HttpMethod,
    HTTPRequestParams,
    ParsedData,
    Request,
)

from .models import (
    TRCourtConfig,
    TRDocketEntryActor,
    TROriginatingCase,
    TRParty,
    TRRepresentative,
    TRTickler,
    TRTicklerDueFrom,
)

# File extension -> kent expected_type hint
_TR_EXPECTED_TYPE_MAP: dict[str, str] = {
    "pdf": "pdf",
    "mp3": "audio",
    "wav": "audio",
    "mp4": "video",
    "wma": "audio",
    "m4a": "audio",
}

if TYPE_CHECKING:
    from collections.abc import Generator


class TRPortalMixin:
    """Mixin providing common TR Portal scraping logic.

    Subclasses must also inherit from BaseScraper and provide
    the required class variables and step method names.
    """

    # === Configuration (set by subclass) ===
    TR_API_BASE_URL: ClassVar[str]
    TR_PORTAL_URL: ClassVar[str]
    TR_COURT_CONFIG: ClassVar[dict[str, TRCourtConfig]]

    # === Model classes (set by subclass) ===
    DOCKET_CLASS: ClassVar[type]
    DOCKET_ENTRY_CLASS: ClassVar[type]
    DOCUMENT_CLASS: ClassVar[type]
    ORAL_ARGUMENT_CLASS: ClassVar[type]

    # === Dockets API limits ===
    DOCKETS_MAX_RESULTS: ClassVar[int] = 10000
    DOCKETS_PAGE_SIZE: ClassVar[int] = 50
    DOCUMENTS_PAGE_SIZE: ClassVar[int] = 100
    TICKLERS_PAGE_SIZE: ClassVar[int] = 100

    # === Document access gating ===
    # The docketentrydocumentsaccess listing reports each document's
    # ``userDocumentState`` — the current (anonymous) client's access verdict.
    # These are global C-Track platform constants (hard-coded identically in
    # every deployment's Angular bundle; verified byte-for-byte on the North
    # Dakota and Oregon portals):
    #
    #   VIEWABLE     b64d1d1e-f926-4c87-ab6b-df5c96d3b186  free, fetchable
    #   PURCHASABLE  dc195201-c792-4883-ab2a-5730dc357ca2  paywalled
    #   IN_CART      e069220c-7377-4b6a-8664-15f29da6808a  paywalled (in cart)
    #   UNAVAILABLE  ea5979e2-9949-4819-819b-72f9ef7f7106  not public
    #
    # Only VIEWABLE documents can be fetched anonymously; every other state
    # 302-redirects to a purchase/login wall (e.g. Alabama's docket PDFs are
    # UNAVAILABLE, Oregon's are paywalled). We skip the download for those and
    # record metadata only. Default-deny: only allow-listed states are fetched,
    # so a deployment we haven't inspected stays quiet instead of hammering the
    # wall. Extend the set if a new fetchable state ever appears.
    TR_DOWNLOADABLE_DOCUMENT_STATES: ClassVar[frozenset[str]] = frozenset(
        {"b64d1d1e-f926-4c87-ab6b-df5c96d3b186"}  # VIEWABLE
    )

    # === Ticklers ===
    # Whether to fetch the per-case ticklers (deadlines) endpoint after
    # docket entries. Off by default: some C-Track deployments (e.g.
    # Nevada, Alabama) expose the endpoint but never populate it, so
    # fetching would just cost an empty request per case. Enable on the
    # subclass (North Dakota / Oregon / Wyoming) where it carries data.
    TR_FETCH_TICKLERS: ClassVar[bool] = False

    # =========================================================================
    # Date helpers
    # =========================================================================

    def _tr_parse_date(self, date_str: str) -> date | None:
        """Parse ISO 8601 date string from TR Portal API.

        The API returns dates like: 2023-11-09T14:15:00.000+00:00

        Returns:
            Parsed date object, or None if parsing fails.
        """
        if not date_str:
            return None
        try:
            return datetime.fromisoformat(date_str[:10]).date()
        except (ValueError, IndexError):
            return None

    def _tr_parse_datetime(self, date_str: str) -> datetime | None:
        """Parse a full ISO 8601 timestamp from the TR Portal API.

        Returns:
            Parsed datetime object, or None if parsing fails.
        """
        if not date_str:
            return None
        try:
            return datetime.fromisoformat(date_str)
        except ValueError:
            return None

    def _tr_format_api_datetime(
        self, d: date, end_of_day: bool = False
    ) -> str:
        """Format a date for the TR Portal API.

        Args:
            d: The date to format.
            end_of_day: If True, use 23:59:59.900, otherwise 00:00:00.001.

        Returns:
            ISO 8601 formatted datetime string with timezone.
        """
        if end_of_day:
            return f"{d.isoformat()}T23:59:59.900-06:00"
        return f"{d.isoformat()}T00:00:00.001-06:00"

    # =========================================================================
    # Court configuration lookups
    # =========================================================================

    def _tr_get_court_guid(self, court_id: str) -> str | None:
        """Get court GUID from our court_id string."""
        config = self.TR_COURT_CONFIG.get(court_id)
        return config["court_guid"] if config else None

    def _tr_get_court_id_from_guid(self, court_guid: str) -> str | None:
        """Map court GUID to our court_id string."""
        for court_id, config in self.TR_COURT_CONFIG.items():
            if config["court_guid"] == court_guid:
                return court_id
        return None

    def _tr_get_court_id_from_abbreviation(self, abbr: str) -> str | None:
        """Map court abbreviation (from API) to our court_id string."""
        for court_id, config in self.TR_COURT_CONFIG.items():
            if config["abbreviation"] == abbr:
                return court_id
        return None

    def _tr_get_court_id_from_numeric(
        self, numeric_id: int | str
    ) -> str | None:
        """Map numeric court ID (from API) to our court_id string."""
        numeric_str = str(numeric_id)
        for court_id, config in self.TR_COURT_CONFIG.items():
            if config["numeric_id"] == numeric_str:
                return court_id
        return None

    def _tr_get_court_guid_from_numeric(
        self, numeric_id: int | str
    ) -> str | None:
        """Map numeric court ID to court GUID."""
        court_id = self._tr_get_court_id_from_numeric(numeric_id)
        return self._tr_get_court_guid(court_id) if court_id else None

    def _tr_get_target_courts(self, court_ids: set[str] | None) -> set[str]:
        """Get the set of court IDs to scrape, filtered by any user filter.

        Args:
            court_ids: Set of court_id values from search params, or None.

        Returns:
            Set of valid court_id strings.
        """
        if court_ids:
            valid = court_ids & set(self.TR_COURT_CONFIG.keys())
            if valid:
                return valid
        return set(self.TR_COURT_CONFIG.keys())

    # =========================================================================
    # Dockets: request builders
    # =========================================================================

    def _tr_yield_dockets_search_request(
        self, start_date: date, end_date: date, target_courts: set[str]
    ) -> Generator[Request, None, None]:
        """Yield a search request for dockets in the given date range.

        The continuation targets ``self.parse_dockets_search``. The
        ``cms/cases`` endpoint searches all courts by filed date, so the
        court allow-list rides in ``accumulated_data["target_courts"]``
        (seeded by the entry from its ``court_ids`` argument) and the step
        drops detail requests for any other court.
        """
        api_url = f"{self.TR_API_BASE_URL}/courts/cms/cases"
        params = {
            "caseHeader.filedDateFrom": self._tr_format_api_datetime(
                start_date, end_of_day=False
            ),
            "caseHeader.filedDateTo": self._tr_format_api_datetime(
                end_date, end_of_day=True
            ),
            "page": "0",
            "size": str(self.DOCKETS_PAGE_SIZE),
            "sort": "caseHeader.filedDate,asc",
        }
        url = f"{api_url}?{urlencode(params)}"

        yield Request(
            request=HTTPRequestParams(
                method=HttpMethod.GET,
                url=url,
                headers={"Accept": "application/json"},
            ),
            continuation=self.parse_dockets_search,
            accumulated_data={
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
                "is_first_page": True,
                "target_courts": sorted(target_courts),
            },
            deduplication_key=(
                f"dockets_search:{start_date.isoformat()}:"
                f"{end_date.isoformat()}:0"
            ),
        )

    def _tr_split_date_range(
        self, start_date: date, end_date: date, target_courts: set[str]
    ) -> Generator[Request, None, None]:
        """Split a date range in half and yield searches for both halves.

        Used when the API returns 10,000+ results for a date range.
        """
        days_diff = (end_date - start_date).days
        if days_diff <= 0:
            yield from self._tr_yield_dockets_search_request(
                start_date, end_date, target_courts
            )
            return

        mid_date = start_date + timedelta(days=days_diff // 2)
        yield from self._tr_yield_dockets_search_request(
            start_date, mid_date, target_courts
        )
        yield from self._tr_yield_dockets_search_request(
            mid_date + timedelta(days=1), end_date, target_courts
        )

    # =========================================================================
    # Dockets: step implementations
    # =========================================================================

    def _tr_handle_dockets_search(
        self,
        json_content: dict,
        accumulated_data: dict,
    ) -> Generator:
        """Core logic for parse_dockets_search step.

        Handles pagination and the 10,000 result limit by splitting
        date ranges. Yields Request objects for case detail.
        """
        start_date = date.fromisoformat(accumulated_data["start_date"])
        end_date = date.fromisoformat(accumulated_data["end_date"])
        is_first_page = accumulated_data.get("is_first_page", False)
        target_courts = set(accumulated_data.get("target_courts", []))

        page_info = json_content.get("page", {})
        current_page = page_info.get("number", 0)
        total_pages = page_info.get("totalPages", 1)
        total_elements = page_info.get("totalElements", 0)

        # Check 10,000 limit on first page
        if is_first_page and total_elements >= self.DOCKETS_MAX_RESULTS:
            yield from self._tr_split_date_range(
                start_date, end_date, target_courts
            )
            return

        embedded = json_content.get("_embedded", {})
        results = embedded.get("results", [])

        for result in results:
            case_header = result.get("caseHeader", {})
            case_instance_uuid = case_header.get("caseInstanceUUID")
            court_id_num = case_header.get("courtID")

            if not case_instance_uuid or court_id_num is None:
                continue

            court_id = self._tr_get_court_id_from_numeric(court_id_num)
            if not court_id or (
                target_courts and court_id not in target_courts
            ):
                continue

            court_guid = self._tr_get_court_guid(court_id)
            if not court_guid:
                continue

            detail_url = (
                f"{self.TR_API_BASE_URL}/courts/{court_guid}"
                f"/cms/cases/{case_instance_uuid}"
            )

            yield Request(
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url=detail_url,
                    headers={"Accept": "application/json"},
                ),
                continuation=self.parse_case_detail,
                accumulated_data={
                    "case_instance_uuid": case_instance_uuid,
                    "court_guid": court_guid,
                },
                deduplication_key=f"case_detail:{case_instance_uuid}",
            )

        # Paginate
        if current_page + 1 < total_pages:
            api_url = f"{self.TR_API_BASE_URL}/courts/cms/cases"
            params = {
                "caseHeader.filedDateFrom": self._tr_format_api_datetime(
                    start_date, end_of_day=False
                ),
                "caseHeader.filedDateTo": self._tr_format_api_datetime(
                    end_date, end_of_day=True
                ),
                "page": str(current_page + 1),
                "size": str(self.DOCKETS_PAGE_SIZE),
                "sort": "caseHeader.filedDate,asc",
            }
            url = f"{api_url}?{urlencode(params)}"

            yield Request(
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url=url,
                    headers={"Accept": "application/json"},
                ),
                continuation=self.parse_dockets_search,
                accumulated_data={
                    "start_date": start_date.isoformat(),
                    "end_date": end_date.isoformat(),
                    "is_first_page": False,
                    "target_courts": sorted(target_courts),
                },
                deduplication_key=(
                    f"dockets_search:{start_date.isoformat()}:"
                    f"{end_date.isoformat()}:{current_page + 1}"
                ),
            )

    def _tr_handle_case_detail(
        self,
        json_content: dict,
        accumulated_data: dict,
    ) -> Generator:
        """Core logic for parse_case_detail step.

        Parses case header, creates a docket model, and yields a
        request for case parties.
        """
        case_instance_uuid = accumulated_data["case_instance_uuid"]
        court_guid = accumulated_data["court_guid"]

        case_header = json_content.get("caseHeader", {}) or {}

        case_number = case_header.get("caseNumber", "")
        case_title = case_header.get("caseTitle", "")
        case_caption = case_header.get("caseCaption", "")
        filed_date_str = case_header.get("filedDate", "")
        closed_flag = case_header.get("closedFlag", False)

        originating_cases = [
            TROriginatingCase(
                court_name=oc.get("originatingCourtName"),
                case_number=oc.get("originatingCaseNumber"),
            )
            for oc in case_header.get("originatingCourtCases", []) or []
        ]

        court_id = self._tr_get_court_id_from_guid(court_guid)
        if not court_id:
            return

        case_name = case_caption if case_caption else case_title

        source_url = (
            f"{self.TR_PORTAL_URL}/portal/court/{court_guid}"
            f"/case/{case_instance_uuid}"
        )

        docket = self.DOCKET_CLASS(
            case_instance_uuid=case_instance_uuid,
            docket_number=case_number,
            court=court_id,
            date_filed=self._tr_parse_date(filed_date_str),
            datetime_filed=self._tr_parse_datetime(filed_date_str),
            case_name=case_name,
            case_name_full=case_title or None,
            case_caption=case_caption or None,
            case_classification=case_header.get("caseClassification"),
            classification_id=case_header.get("caseClassificationID"),
            class_group_type=case_header.get("caseClassGroupType") or None,
            class_group_type_id=case_header.get("caseClassGroupTypeID"),
            court_abbreviation=case_header.get("courtAbbreviation") or None,
            location=case_header.get("location") or None,
            location_id=case_header.get("locationID"),
            case_group_flag=case_header.get("caseGroupFlag"),
            panel_flag=case_header.get("panelFlag"),
            originating_cases=originating_cases,
            status="Closed" if closed_flag else "Open",
            court_guid=court_guid,
            source_url=source_url,
            parties=[],
            entries=[],
            oral_arguments=[],
        )

        parties_url = (
            f"{self.TR_API_BASE_URL}/courts/{court_guid}"
            f"/cms/cases/{case_instance_uuid}/parties"
            "?sort=orderBy,asc&sort=partyNumber,asc&size=100"
        )

        yield Request(
            request=HTTPRequestParams(
                method=HttpMethod.GET,
                url=parties_url,
                headers={"Accept": "application/json"},
            ),
            continuation=self.parse_case_parties,
            accumulated_data={
                "docket_data": docket.model_dump(mode="json"),
            },
            deduplication_key=f"case_parties:{case_instance_uuid}",
        )

    def _tr_handle_case_parties(
        self,
        json_content: dict,
        accumulated_data: dict,
    ) -> Generator:
        """Core logic for parse_case_parties step.

        Parses parties and yields a request for docket entries.
        """
        docket = self.DOCKET_CLASS.model_validate(
            accumulated_data["docket_data"]
        )

        embedded = json_content.get("_embedded", {})
        results = embedded.get("results", [])

        parties: list[TRParty] = []
        for party_data in results:
            party_header = party_data.get("partyHeader", {}) or {}
            actor = party_header.get("partyActorInstance", {}) or {}

            case_party_uuid = party_header.get("casePartyUUID")

            representatives: list[TRRepresentative] = []
            for rep in party_data.get("legalRepresentations", []) or []:
                attorney_header = rep.get("attorneyPartyHeader", {}) or {}
                rep_actor = attorney_header.get("partyActorInstance", {}) or {}
                attorney_name = rep_actor.get("displayName")
                if not attorney_name:
                    continue
                representatives.append(
                    TRRepresentative(
                        case_party_uuid=case_party_uuid,
                        name=attorney_name,
                        sort_name=rep_actor.get("sortName"),
                        primary_flag=rep.get("primaryFlag"),
                    )
                )

            parties.append(
                TRParty(
                    case_party_uuid=case_party_uuid,
                    name=actor.get("displayName", ""),
                    sort_name=actor.get("sortName"),
                    party_type=party_header.get("partyType"),
                    party_type_id=party_header.get("partyTypeID"),
                    party_subtype=party_header.get("partySubType"),
                    party_subtype_id=party_header.get("partySubTypeID"),
                    status=party_header.get("partyStatus"),
                    status_id=party_header.get("partyStatusID"),
                    pro_se_flag=party_data.get("proSeFlag"),
                    order_by=party_data.get("orderBy"),
                    party_number=party_data.get("partyNumber"),
                    involvement_type_id=party_data.get("involvementTypeID"),
                    non_public_flag=party_data.get("nonPublicFlag"),
                    representatives=representatives,
                )
            )

        docket.parties = parties

        entries_url = (
            f"{self.TR_API_BASE_URL}/courts/{docket.court_guid}"
            f"/cms/cases/{docket.case_instance_uuid}/docketentries"
            f"?page=0&size={self.DOCKETS_PAGE_SIZE}"
            "&sort=docketEntryHeader.filedDate,asc"
        )

        yield Request(
            request=HTTPRequestParams(
                method=HttpMethod.GET,
                url=entries_url,
                headers={"Accept": "application/json"},
            ),
            continuation=self.parse_docket_entries,
            accumulated_data={
                "docket_data": docket.model_dump(mode="json"),
            },
            deduplication_key=(
                f"docket_entries:{docket.case_instance_uuid}:0"
            ),
        )

    def _tr_handle_docket_entries(
        self,
        json_content: dict,
        accumulated_data: dict,
    ) -> Generator:
        """Core logic for parse_docket_entries step.

        Parses entries, handles pagination, and yields the final docket.
        """
        docket = self.DOCKET_CLASS.model_validate(
            accumulated_data["docket_data"]
        )

        embedded = json_content.get("_embedded", {})
        results = embedded.get("results", [])

        page_info = json_content.get("page", {})
        current_page = page_info.get("number", 0)
        total_pages = page_info.get("totalPages", 1)

        entries = list(docket.entries)

        for entry_data in results:
            header = entry_data.get("docketEntryHeader", {}) or {}
            filed_date_str = header.get("filedDate", "")
            submitted_date_str = header.get("submittedDate", "")

            submitted_by: list[TRDocketEntryActor] = []
            for actor in entry_data.get("submittedBy", []) or []:
                actor_info = actor.get("partyActorInstance", {}) or {}
                display_name = actor_info.get("displayName")
                if not display_name:
                    continue
                submitted_by.append(
                    TRDocketEntryActor(
                        display_name=display_name,
                        sort_name=actor_info.get("sortName"),
                    )
                )

            entry = self.DOCKET_ENTRY_CLASS(
                docket_entry_uuid=header.get("docketEntryUUID"),
                date_filed=self._tr_parse_date(filed_date_str),
                datetime_filed=self._tr_parse_datetime(filed_date_str),
                date_submitted=self._tr_parse_datetime(submitted_date_str),
                document_type=header.get("docketEntryType") or None,
                document_type_id=header.get("docketEntryTypeID"),
                document_subtype=header.get("docketEntrySubType") or None,
                document_subtype_id=header.get("docketEntrySubTypeID"),
                entry_name=header.get("docketEntryName") or None,
                entry_status=header.get("docketEntryStatus") or None,
                entry_status_id=header.get("docketEntryStatusID"),
                description=header.get("docketEntryDescription") or None,
                outcome_status=header.get("outcomeStatus") or None,
                outcome_status_id=header.get("outcomeStatusID"),
                official=header.get("official"),
                document_count=header.get("documentCount"),
                secured_document=header.get("securedDocument"),
                security_1=header.get("security1"),
                security_2=header.get("security2"),
                security_3=header.get("security3"),
                security_4=header.get("security4"),
                security_5=header.get("security5"),
                composite_security=header.get("compositeSecurity"),
                submitted_by=submitted_by,
            )
            entries.append(entry)

        docket.entries = entries

        if current_page + 1 < total_pages:
            entries_url = (
                f"{self.TR_API_BASE_URL}/courts/{docket.court_guid}"
                f"/cms/cases/{docket.case_instance_uuid}/docketentries"
                f"?page={current_page + 1}&size={self.DOCKETS_PAGE_SIZE}"
                "&sort=docketEntryHeader.filedDate,asc"
            )

            yield Request(
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url=entries_url,
                    headers={"Accept": "application/json"},
                ),
                continuation=self.parse_docket_entries,
                accumulated_data={
                    "docket_data": docket.model_dump(mode="json"),
                },
                deduplication_key=(
                    f"docket_entries:{docket.case_instance_uuid}:"
                    f"{current_page + 1}"
                ),
            )
        elif self.TR_FETCH_TICKLERS:
            yield from self._tr_yield_ticklers_request(docket=docket, page=0)
        else:
            yield from self._tr_yield_documents_request(docket=docket, page=0)

    # =========================================================================
    # Ticklers (deadlines): request builder
    # =========================================================================

    def _tr_yield_ticklers_request(
        self, docket, page: int
    ) -> Generator[Request, None, None]:
        """Yield a ticklers (deadlines) request for the given case.

        The continuation targets ``self.parse_ticklers_list``. Only used
        when the subclass sets ``TR_FETCH_TICKLERS``; the chain runs after
        docket entries and, once the last tickler page is parsed, hands off
        to the documents fetch.
        """
        api_url = (
            f"{self.TR_API_BASE_URL}/courts/{docket.court_guid}"
            f"/cms/cases/{docket.case_instance_uuid}/ticklers"
        )
        params = {
            "page": str(page),
            "size": str(self.TICKLERS_PAGE_SIZE),
            "sort": "dueDate,asc",
        }
        url = f"{api_url}?{urlencode(params)}"

        yield Request(
            request=HTTPRequestParams(
                method=HttpMethod.GET,
                url=url,
                headers={"Accept": "application/json"},
            ),
            continuation=self.parse_ticklers_list,
            accumulated_data={
                "docket_data": docket.model_dump(mode="json"),
            },
            deduplication_key=(
                f"ticklers_list:{docket.case_instance_uuid}:{page}"
            ),
        )

    # =========================================================================
    # Ticklers (deadlines): step implementation
    # =========================================================================

    def _tr_handle_ticklers_list(
        self,
        json_content: dict,
        accumulated_data: dict,
    ) -> Generator:
        """Core logic for parse_ticklers_list step.

        Parses tickler (deadline) rows, handles pagination, and once the
        last page is consumed chains into the documents fetch.
        """
        docket = self.DOCKET_CLASS.model_validate(
            accumulated_data["docket_data"]
        )

        embedded = json_content.get("_embedded", {}) or {}
        results = embedded.get("results", []) or []

        page_info = json_content.get("page", {}) or {}
        current_page = page_info.get("number", 0)
        total_pages = page_info.get("totalPages", 1)

        ticklers = list(docket.ticklers)
        for result in results:
            due_froms: list[TRTicklerDueFrom] = []
            for due_from in result.get("dueFroms", []) or []:
                actor = due_from.get("partyActorInstance", {}) or {}
                due_froms.append(
                    TRTicklerDueFrom(sort_name=actor.get("sortName"))
                )

            entry_header = result.get("docketEntryHeader", {}) or {}

            ticklers.append(
                TRTickler(
                    due_date=self._tr_parse_date(result.get("dueDate", "")),
                    tickler_type=result.get("ticklerType") or None,
                    tickler_type_id=result.get("ticklerTypeID"),
                    tickler_status=result.get("ticklerStatus") or None,
                    tickler_status_id=result.get("ticklerStatusID"),
                    due_froms=due_froms,
                    docket_entry_uuid=entry_header.get("docketEntryUUID"),
                )
            )

        docket.ticklers = ticklers

        if current_page + 1 < total_pages:
            yield from self._tr_yield_ticklers_request(
                docket=docket, page=current_page + 1
            )
        else:
            yield from self._tr_yield_documents_request(docket=docket, page=0)

    # =========================================================================
    # Documents: request builders
    # =========================================================================

    def _tr_yield_documents_request(
        self, docket, page: int
    ) -> Generator[Request, None, None]:
        """Yield a docketentrydocumentsaccess request for the given case.

        The continuation targets ``self.parse_documents_list``. The
        access endpoint is preferred over ``/docketentrydocuments``
        because it includes ``docketEntryUUID`` (linking each document
        back to its parent docket entry) and ``documentInfo`` metadata.
        """
        api_url = (
            f"{self.TR_API_BASE_URL}/courts/cms/docketentrydocumentsaccess"
        )
        params = {
            "caseHeader.caseInstanceUUID": docket.case_instance_uuid,
            "page": str(page),
            "size": str(self.DOCUMENTS_PAGE_SIZE),
        }
        url = f"{api_url}?{urlencode(params)}"

        yield Request(
            request=HTTPRequestParams(
                method=HttpMethod.GET,
                url=url,
                headers={"Accept": "application/json"},
            ),
            continuation=self.parse_documents_list,
            accumulated_data={
                "docket_data": docket.model_dump(mode="json"),
            },
            deduplication_key=(
                f"documents_list:{docket.case_instance_uuid}:{page}"
            ),
        )

    # =========================================================================
    # Documents: step implementations
    # =========================================================================

    def _tr_handle_documents_list(
        self,
        json_content: dict,
        accumulated_data: dict,
    ) -> Generator:
        """Core logic for parse_documents_list step.

        Pages through the documents-access listing for a case. For each
        document, yields an archive request whose continuation is
        ``self.parse_document_download``. On the last page also yields
        the final docket.
        """
        docket = self.DOCKET_CLASS.model_validate(
            accumulated_data["docket_data"]
        )

        embedded = json_content.get("_embedded", {}) or {}
        results = embedded.get("results", []) or []

        page_info = json_content.get("page", {}) or {}
        current_page = page_info.get("number", 0)
        total_pages = page_info.get("totalPages", 1)

        for result in results:
            doc_uuid = result.get("documentLinkUUID")
            if not doc_uuid:
                continue

            doc_info = result.get("documentInfo") or {}
            file_ext = doc_info.get("fileExtension")
            expected_type = _TR_EXPECTED_TYPE_MAP.get(
                (file_ext or "").lower(), "pdf"
            )

            download_url = (
                f"{self.TR_API_BASE_URL}/courts/{docket.court_guid}"
                f"/cms/case/{docket.case_instance_uuid}"
                f"/docketentrydocuments/{doc_uuid}"
            )

            meta = {
                "docket_number": docket.docket_number,
                "court": docket.court,
                "case_instance_uuid": docket.case_instance_uuid,
                "docket_entry_uuid": result.get("docketEntryUUID"),
                "document_link_uuid": doc_uuid,
                "document_name": result.get("documentName"),
                "document_type": doc_info.get("documentType"),
                "content_type": doc_info.get("contentType"),
                "file_extension": file_ext,
                "page_count": doc_info.get("pageCount"),
                "file_size": doc_info.get("fileSize"),
                "download_url": download_url,
            }

            # Only fetch documents the portal reports as accessible; any
            # other state 302-redirects to a purchase/login wall. Skip the
            # download but still emit the document metadata (no local file).
            if (
                result.get("userDocumentState")
                not in self.TR_DOWNLOADABLE_DOCUMENT_STATES
            ):
                yield ParsedData(data=self._tr_build_document(meta, None))
                continue

            yield Request(
                archive=True,
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url=download_url,
                ),
                continuation=self.parse_document_download,
                expected_type=expected_type,
                accumulated_data=meta,
                deduplication_key=f"{docket.docket_number}-{doc_uuid}",
            )

        if current_page + 1 < total_pages:
            yield from self._tr_yield_documents_request(
                docket=docket, page=current_page + 1
            )
        else:
            yield ParsedData(data=docket)

    def _tr_handle_document_download(
        self,
        local_filepath: str | None,
        accumulated_data: dict,
    ) -> Generator:
        """Core logic for parse_document_download step.

        Emits a TR-portal document record carrying ``local_path`` from
        the archive driver.
        """
        yield ParsedData(
            data=self._tr_build_document(accumulated_data, local_filepath)
        )

    def _tr_build_document(self, meta: dict, local_path: str | None):
        """Build a document record from listing metadata + an optional path.

        Shared by the documents-list step (which records metadata for
        non-fetchable documents with no ``local_path``) and the download
        step (which supplies the archived file path).
        """
        return self.DOCUMENT_CLASS(
            docket_number=meta["docket_number"],
            court=meta["court"],
            case_instance_uuid=meta["case_instance_uuid"],
            docket_entry_uuid=meta.get("docket_entry_uuid"),
            document_link_uuid=meta["document_link_uuid"],
            document_name=meta.get("document_name"),
            document_type=meta.get("document_type"),
            content_type=meta.get("content_type"),
            file_extension=meta.get("file_extension"),
            page_count=meta.get("page_count"),
            file_size=meta.get("file_size"),
            download_url=meta.get("download_url"),
            local_path=local_path,
        )

    # =========================================================================
    # Events / Oral Arguments: request builders
    # =========================================================================

    def _tr_yield_events_request(
        self,
        date_gte: date,
        date_lte: date,
        target_courts: set[str],
    ) -> Generator[Request, None, None]:
        """Yield an events search request.

        The continuation targets ``self.parse_events_list``. ``target_courts``
        rides in ``accumulated_data`` so the step (and its pagination) can
        filter the all-courts events feed without re-reading entry args.
        """
        api_url = f"{self.TR_API_BASE_URL}/courts/cms/events"
        params = {
            "startDateFrom": self._tr_format_api_datetime(
                date_gte, end_of_day=False
            ),
            "startDateTo": self._tr_format_api_datetime(
                date_lte, end_of_day=True
            ),
            "page": "0",
            "size": "100",
            "sort": "startDate,desc",
        }
        url = f"{api_url}?{urlencode(params)}"

        yield Request(
            request=HTTPRequestParams(
                method=HttpMethod.GET,
                url=url,
                headers={"Accept": "application/json"},
            ),
            continuation=self.parse_events_list,
            accumulated_data={
                "start_date": date_gte.isoformat(),
                "end_date": date_lte.isoformat(),
                "target_courts": sorted(target_courts),
            },
            deduplication_key=(
                f"events_list:{date_gte.isoformat()}:{date_lte.isoformat()}:0"
            ),
        )

    # =========================================================================
    # Events / Oral Arguments: step implementations
    # =========================================================================

    def _tr_handle_events_list(
        self,
        json_content: dict,
        accumulated_data: dict,
    ) -> Generator:
        """Core logic for parse_events_list step.

        Filters events by court and date range, then yields requests
        for event hearings. The court allow-list rides in
        ``accumulated_data["target_courts"]`` (seeded by the entry from
        its ``court_ids`` argument).
        """
        start_date = date.fromisoformat(accumulated_data["start_date"])
        end_date = date.fromisoformat(accumulated_data["end_date"])
        target_courts = set(accumulated_data.get("target_courts", []))

        page_info = json_content.get("page", {})
        current_page = page_info.get("number", 0)
        total_pages = page_info.get("totalPages", 1)

        results = json_content.get("_embedded", {}).get("results", [])
        for event in results:
            event_uuid = event.get("eventUUID")
            court_abbr = event.get("courtAbbreviation", "")
            event_start_date_str = event.get("startDate")
            location = event.get("location", "")

            if not event_uuid:
                continue

            court_id = self._tr_get_court_id_from_abbreviation(court_abbr)
            if not court_id or court_id not in target_courts:
                continue

            event_date = self._tr_parse_date(event_start_date_str)
            if not event_date:
                continue

            if event_date < start_date or event_date > end_date:
                continue

            court_guid = self._tr_get_court_guid(court_id)
            if not court_guid:
                continue

            hearings_url = (
                f"{self.TR_API_BASE_URL}/courts/{court_guid}"
                f"/cms/events/{event_uuid}/hearings"
                "?page=0&size=100&sort=orderBy,asc"
            )

            yield Request(
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url=hearings_url,
                    headers={"Accept": "application/json"},
                ),
                continuation=self.parse_event_hearings,
                accumulated_data={
                    "court_id": court_id,
                    "court_guid": court_guid,
                    "event_uuid": event_uuid,
                    "event_date": event_date.isoformat(),
                    "location": location,
                },
                deduplication_key=f"event_hearings:{event_uuid}",
            )

        # Paginate
        if current_page + 1 < total_pages:
            api_url = f"{self.TR_API_BASE_URL}/courts/cms/events"
            params = {
                "startDateFrom": self._tr_format_api_datetime(
                    start_date, end_of_day=False
                ),
                "startDateTo": self._tr_format_api_datetime(
                    end_date, end_of_day=True
                ),
                "page": str(current_page + 1),
                "size": "100",
                "sort": "startDate,desc",
            }
            url = f"{api_url}?{urlencode(params)}"

            yield Request(
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url=url,
                    headers={"Accept": "application/json"},
                ),
                continuation=self.parse_events_list,
                accumulated_data={
                    "start_date": start_date.isoformat(),
                    "end_date": end_date.isoformat(),
                    "target_courts": sorted(target_courts),
                },
                deduplication_key=(
                    f"events_list:{start_date.isoformat()}:"
                    f"{end_date.isoformat()}:{current_page + 1}"
                ),
            )

    def _tr_handle_event_hearings(
        self,
        json_content: dict,
        accumulated_data: dict,
    ) -> Generator:
        """Core logic for parse_event_hearings step.

        Parses hearings and yields oral argument objects.
        """
        court_id = accumulated_data["court_id"]
        court_guid = accumulated_data["court_guid"]
        event_uuid = accumulated_data["event_uuid"]
        event_date = date.fromisoformat(accumulated_data["event_date"])

        results = json_content.get("_embedded", {}).get("results", [])

        for hearing in results:
            case_header = hearing.get("caseHeader", {})
            case_instance_uuid = case_header.get("caseInstanceUUID")
            case_number = case_header.get("caseNumber", "")
            case_title = case_header.get("caseTitle", "")
            hearing_start = hearing.get("startDate")

            if not case_number or not case_instance_uuid:
                continue

            date_argued = self._tr_parse_date(hearing_start)
            if not date_argued:
                date_argued = event_date

            source_url = (
                f"{self.TR_PORTAL_URL}/portal/court/{court_guid}"
                f"/case/{case_instance_uuid}"
            )

            oral_arg = self.ORAL_ARGUMENT_CLASS(
                docket_number=case_number,
                court=court_id,
                date_argued=date_argued,
                case_name=case_title,
                source_url=source_url,
                calendar_uuid=event_uuid,
                case_instance_uuid=case_instance_uuid,
            )

            yield ParsedData(data=oral_arg)

    # =========================================================================
    # Publications: request builders
    # =========================================================================

    def _tr_yield_publications_request(
        self,
        date_gte: date | None,
        date_lte: date | None,
        target_courts: set[str],
    ) -> Generator[Request, None, None]:
        """Yield publication list requests for target courts.

        The continuation targets ``self.parse_publications_list``.
        """
        for court_id in sorted(target_courts):
            config = self.TR_COURT_CONFIG.get(court_id)
            if not config:
                continue
            court_guid = config["court_guid"]

            api_url = f"{self.TR_API_BASE_URL}/courts/cms/publications"
            params = {
                "courtID": court_guid,
                "page": "0",
                "size": "25",
                "sort": "publicationDate,desc",
            }
            url = f"{api_url}?{urlencode(params)}"

            yield Request(
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url=url,
                    headers={"Accept": "application/json"},
                ),
                continuation=self.parse_publications_list,
                accumulated_data={
                    "court_id": court_id,
                    "court_guid": court_guid,
                    "date_gte": date_gte.isoformat() if date_gte else None,
                    "date_lte": date_lte.isoformat() if date_lte else None,
                },
                deduplication_key=f"publications_list:{court_id}:0",
            )

    # =========================================================================
    # Publications: step implementations
    # =========================================================================

    def _tr_handle_publications_list(
        self,
        json_content: dict,
        accumulated_data: dict,
    ) -> Generator:
        """Core logic for parse_publications_list step.

        Parses the publication list, filters by date range, and yields
        requests for publication details.
        """
        court_id: str = accumulated_data.get("court_id", "")
        court_guid: str = accumulated_data.get("court_guid", "")

        date_gte_str = accumulated_data.get("date_gte")
        date_lte_str = accumulated_data.get("date_lte")
        date_gte = date.fromisoformat(date_gte_str) if date_gte_str else None
        date_lte = date.fromisoformat(date_lte_str) if date_lte_str else None

        embedded = json_content.get("_embedded", {})
        results = embedded.get("results", [])

        if not results:
            return

        page_info = json_content.get("page", {})
        current_page = page_info.get("number", 0)
        total_pages = page_info.get("totalPages", 1)

        should_paginate = False
        earliest_date_seen = None

        for publication in results:
            publication_uuid = publication.get("publicationUUID")
            pub_date_str = publication.get(
                "publicationDate",
                publication.get("scheduledDate", ""),
            )
            pub_date = self._tr_parse_date(pub_date_str)

            if not pub_date or not publication_uuid:
                continue

            if earliest_date_seen is None or pub_date < earliest_date_seen:
                earliest_date_seen = pub_date

            if date_lte and pub_date > date_lte:
                continue

            if date_gte and pub_date < date_gte:
                break

            if date_gte is None or pub_date >= date_gte:
                should_paginate = True

            detail_url = (
                f"{self.TR_API_BASE_URL}/courts/{court_guid}"
                f"/cms/publication/{publication_uuid}"
            )

            yield Request(
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url=detail_url,
                    headers={"Accept": "application/json"},
                ),
                continuation=self.parse_publication_detail,
                accumulated_data={
                    "court_id": court_id,
                    "court_guid": court_guid,
                },
                deduplication_key=(f"publication_detail:{publication_uuid}"),
            )

        # Pagination
        if (
            should_paginate
            and current_page + 1 < total_pages
            and (
                date_gte is None
                or (earliest_date_seen and earliest_date_seen >= date_gte)
            )
        ):
            api_url = f"{self.TR_API_BASE_URL}/courts/cms/publications"
            params = {
                "courtID": court_guid,
                "page": str(current_page + 1),
                "size": "25",
                "sort": "publicationDate,desc",
            }
            url = f"{api_url}?{urlencode(params)}"

            yield Request(
                nonnavigating=True,
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url=url,
                    headers={"Accept": "application/json"},
                ),
                continuation=self.parse_publications_list,
                accumulated_data={
                    "court_id": court_id,
                    "court_guid": court_guid,
                    "date_gte": date_gte_str,
                    "date_lte": date_lte_str,
                },
                deduplication_key=(
                    f"publications_list:{court_id}:{current_page + 1}"
                ),
            )
