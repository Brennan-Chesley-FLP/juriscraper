"""Kentucky Appellate Courts Scraper.

Scrapes docket data from the Kentucky Court of Justice C-Track Public
Access portal at https://appellatepublic.kycourts.net.

This is the older Thomson Reuters "C-Track Public Access" product
(distinct from "TR Portal" handled by ``common/tr/``). Endpoints live
under ``/api/api/v1/`` on the same host as the Vue.js frontend, and
pagination uses ``x-ctrack-paging-*`` HTTP headers rather than query
parameters.

Supported courts:
- Kentucky Supreme Court (``ky``) — case numbers ``YYYY-SC-####``
- Kentucky Court of Appeals (``kyctapp``) — case numbers ``YYYY-CA-####``

Flow:
  1. Entry: ``get_dockets`` paginates ``/cases/search`` for each
     (court, year) using a case-number prefix; speculative entries
     ``fetch_sc_docket`` / ``fetch_ca_docket`` probe a single case.
  2. ``parse_search_results`` walks the search response and yields
     a case-detail request per ``caseID`` (deduplicated).
  3. ``parse_case_detail`` builds the bare ``KyDocket`` and chains into
     ``parse_docket_entries``.
  4. ``parse_docket_entries`` -> ``parse_parties`` -> ``parse_trial_courts``
     fill in nested fields. The completed ``KyDocket`` is yielded at
     the end of ``parse_trial_courts``, which also fans out one
     documents-list request per docket entry that has documents.
  5. ``parse_documents_list`` yields an archive request per file;
     ``parse_document_download`` emits ``KyDocument`` records.
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING, ClassVar
from urllib.parse import urlencode

from jkent.common.decorators import entry, step
from jkent.common.param_models import YearlySpeculativeRange
from jkent.data_types import (
    BaseScraper,
    HttpMethod,
    HTTPRequestParams,
    ParsedData,
    Request,
    Response,
    ScraperStatus,
    SkipDeduplicationCheck,
)
from pyrate_limiter import Duration, Rate

from .models import (
    API_BASE_URL,
    COURT_CASE_PREFIX,
    PORTAL_URL,
    SITE_COURT_TO_ID,
    KyDocket,
    KyDocketEntry,
    KyDocument,
)

if TYPE_CHECKING:
    from collections.abc import Generator

    from jkent.data_types import ScraperYield


# Headers required on every API call. ``x-ctrack-excludeselflinks`` is
# mandatory: without it the search endpoint silently returns an empty
# resultItems array.
_API_HEADERS: dict[str, str] = {
    "Accept": "application/json",
    "x-ctrack-excludeselflinks": "true",
}

# Pagination tuning. The server caps total enumerable results per query
# at 10,000 (returned in ``x-ctrack-paging-resultslimit``) but each
# (year, court) prefix returns at most ~3500 results, so a single
# search per year is always safe.
_PAGE_SIZE: int = 200

# Earliest year of available records (defensive floor for date-range
# enumeration). The portal carries data back to at least 1990.
_OLDEST_YEAR: int = 1990


def _parse_iso_date(date_str: str | None) -> date | None:
    """Parse an ISO 8601 datetime string from C-Track to a ``date``.

    The API returns values like ``2026-01-07T05:00:00.000+0000``.
    """
    if not date_str:
        return None
    try:
        return date.fromisoformat(date_str[:10])
    except (TypeError, ValueError):
        return None


def _build_search_url(prefix: str) -> str:
    """Build the case-number search URL for a Starts-With prefix match."""
    params = {
        "queryString": "true",
        "searchFields[0].searchType": "Starts With",
        "searchFields[0].operation": "=",
        "searchFields[0].values[0]": prefix,
        "searchFields[0].indexFieldName": "caseNumber",
    }
    return f"{API_BASE_URL}/cases/search?{urlencode(params)}"


def _paging_headers(start_index: int, max_results: int) -> dict[str, str]:
    """Build headers carrying C-Track paging instructions for one page.

    ``start_index`` is 1-based. Asking for the total count is cheap and
    only useful on the first page, so we always set it.
    """
    return {
        **_API_HEADERS,
        "x-ctrack-paging-startindex": str(start_index),
        "x-ctrack-paging-maxresults": str(max_results),
        "x-ctrack-paging-calculatetotalcount": "true",
    }


class KentuckyAppellateScraper(BaseScraper[KyDocket | KyDocument]):
    """Scraper for Kentucky Supreme Court and Court of Appeals dockets.

    Default entry yields all dockets for the current year on each
    target court. Speculative entries enable per-case probing.
    """

    # === Metadata ===
    court_ids: ClassVar[set[str]] = {"ky", "kyctapp"}
    court_url: ClassVar[str] = PORTAL_URL
    data_types: ClassVar[set[str]] = {"dockets"}
    status: ClassVar[ScraperStatus] = ScraperStatus.IN_DEVELOPMENT
    version: ClassVar[str] = "2026-05-03"
    requires_auth: ClassVar[bool] = False

    rate_limits: ClassVar[list[Rate] | None] = [Rate(4, Duration.SECOND)]

    # =========================================================================
    # Param helpers
    # =========================================================================

    def _get_target_courts(self) -> set[str]:
        """Return the set of court_ids to scrape, honoring any param filter."""
        if self._params is None:
            return set(self.court_ids)
        try:
            proxy = self._params.KyDocket
            searchable = proxy.get_searchable_fields()
            field = searchable.get("court_id")
            if field and field.is_set():
                return field.values & set(self.court_ids)
        except AttributeError:
            pass
        return set(self.court_ids)

    def _get_year_range(self) -> tuple[int, int]:
        """Resolve (start_year, end_year) inclusive for a bulk crawl.

        Reads ``KyDocket.date_filed`` from params. If unset, defaults
        to the current calendar year only — there is no date-based
        docket search, so we partition by year via the case-number
        prefix and a wide default would be expensive.
        """
        today = date.today()
        start_year = today.year
        end_year = today.year

        if self._params is None:
            return start_year, end_year
        try:
            proxy = self._params.KyDocket
            searchable = proxy.get_searchable_fields()
            field = searchable.get("date_filed")
        except AttributeError:
            return start_year, end_year

        if field and field.is_set():
            if field.gte is not None:
                start_year = max(_OLDEST_YEAR, field.gte.year)
            if field.lte is not None:
                end_year = field.lte.year
        return start_year, end_year

    def _get_case_number_filter(self) -> str | None:
        """Return an exact case-number value from params, if set."""
        if self._params is None:
            return None
        try:
            proxy = self._params.KyDocket
            field = proxy.get_searchable_fields().get("case_number")
            if field and field.is_set():
                return field.value
        except AttributeError:
            pass
        return None

    # =========================================================================
    # Soft-404 detection (speculative probing)
    # =========================================================================

    def fails_successfully(self, response: Response) -> bool:
        """Return False for empty search results (speculation miss).

        The search endpoint returns HTTP 200 with an empty
        ``resultItems`` array for a case number that does not exist.
        Only treat the search endpoint specially; other endpoints
        return real 404s for missing IDs.
        """
        if "/cases/search" not in response.url:
            return True
        # Empty resultItems is the miss signal. Use a substring check
        # so we don't pay the cost of JSON parsing on every response.
        text = response.text or ""
        return '"resultItems":[]' not in text.replace(" ", "")

    # =========================================================================
    # Entry points
    # =========================================================================

    @entry(KyDocket)
    def get_dockets(self) -> Generator[Request, None, None]:
        """Bulk crawl by case-number prefix per (court, year).

        For each target court and each year in the requested range,
        issues a paginated search of ``YYYY-{SC|CA}``. If
        ``KyDocket.case_number`` is set, treats it as an exact case
        number and falls through to a single search instead.
        """
        case_number_filter = self._get_case_number_filter()
        if case_number_filter:
            yield from self._yield_search_request(
                prefix=case_number_filter,
                start_index=1,
                court_id=self._court_id_from_case_number(case_number_filter),
                year=self._year_from_case_number(case_number_filter),
            )
            return

        target_courts = self._get_target_courts()
        start_year, end_year = self._get_year_range()
        if start_year > end_year:
            return

        for year in range(start_year, end_year + 1):
            for court_id in sorted(target_courts):
                court_prefix = COURT_CASE_PREFIX[court_id]
                yield from self._yield_search_request(
                    prefix=f"{year}-{court_prefix}",
                    start_index=1,
                    court_id=court_id,
                    year=year,
                )

    @entry(KyDocket)
    def fetch_sc_docket(self, rid: YearlySpeculativeRange) -> Request:
        """Speculative single-case fetcher for the Kentucky Supreme Court.

        Builds case number ``{year}-SC-{seq:04d}`` and looks up the
        caseID via the search endpoint. The driver enumerates ``rid.min``
        across the seed range and advances on success until ``gap``
        consecutive misses.
        """
        return self._make_speculative_request("ky", rid.year, rid.min)

    @entry(KyDocket)
    def fetch_ca_docket(self, rid: YearlySpeculativeRange) -> Request:
        """Speculative single-case fetcher for the Kentucky Court of Appeals.

        Builds case number ``{year}-CA-{seq:04d}``.
        """
        return self._make_speculative_request("kyctapp", rid.year, rid.min)

    # =========================================================================
    # Search request builders
    # =========================================================================

    def _yield_search_request(
        self,
        prefix: str,
        start_index: int,
        court_id: str,
        year: int,
    ) -> Generator[Request, None, None]:
        """Yield one page of a prefix search."""
        url = _build_search_url(prefix)
        # Pagination requests must always run; otherwise the URL-only
        # dedup key would swallow page 2+ as duplicates of page 1.
        dedup: object
        if start_index == 1:
            dedup = f"search:{prefix}"
        else:
            dedup = SkipDeduplicationCheck()

        yield Request(
            request=HTTPRequestParams(
                method=HttpMethod.GET,
                url=url,
                headers=_paging_headers(start_index, _PAGE_SIZE),
            ),
            continuation=self.parse_search_results,
            accumulated_data={
                "search_prefix": prefix,
                "start_index": start_index,
                "court_id_hint": court_id,
                "year_hint": year,
            },
            deduplication_key=dedup,
        )

    def _make_speculative_request(
        self, court_id: str, year: int, seq: int
    ) -> Request:
        """Build a search request for one specific case number."""
        prefix = COURT_CASE_PREFIX[court_id]
        case_number = f"{year}-{prefix}-{seq:04d}"
        url = _build_search_url(case_number)
        return Request(
            request=HTTPRequestParams(
                method=HttpMethod.GET,
                url=url,
                headers=_paging_headers(1, 5),
            ),
            continuation=self.parse_search_results,
            accumulated_data={
                "search_prefix": case_number,
                "start_index": 1,
                "court_id_hint": court_id,
                "year_hint": year,
                "exact_match": case_number,
            },
            deduplication_key=case_number,
        )

    @staticmethod
    def _court_id_from_case_number(case_number: str) -> str | None:
        for cid, prefix in COURT_CASE_PREFIX.items():
            if f"-{prefix}-" in case_number.upper():
                return cid
        return None

    @staticmethod
    def _year_from_case_number(case_number: str) -> int | None:
        head = case_number.split("-", 1)[0]
        return int(head) if head.isdigit() and len(head) == 4 else None

    # =========================================================================
    # Step 1: parse search results, fan out into per-case fetches
    # =========================================================================

    @step()
    def parse_search_results(
        self,
        json_content: dict,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[KyDocket | KyDocument], None, None]:
        """Walk one page of search results and chain into case detail."""
        prefix = accumulated_data["search_prefix"]
        start_index = accumulated_data["start_index"]
        court_id_hint = accumulated_data.get("court_id_hint")
        exact_match = accumulated_data.get("exact_match")

        results = json_content.get("resultItems") or []
        for item in results:
            row = item.get("rowMap") or {}
            case_id = row.get("caseID") or item.get("id")
            case_number = row.get("caseNumber")
            if not case_id or not case_number:
                continue

            # For speculative probes, only follow the exact match —
            # search returns adjacent / partial matches we don't want.
            if exact_match and case_number != exact_match:
                continue

            yield Request(
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url=f"{API_BASE_URL}/cases/{case_id}",
                    headers=_API_HEADERS,
                ),
                continuation=self.parse_case_detail,
                accumulated_data={
                    "case_id": case_id,
                    "court_id_hint": court_id_hint,
                },
                deduplication_key=case_id,
            )

        # Pagination: drive off response headers when present, otherwise
        # off the resultItems length to be defensive against any header
        # stripping on the way through proxies.
        headers = response.headers or {}
        more_results = (
            headers.get("x-ctrack-paging-moreresults") or ""
        ).lower()
        result_count = headers.get("x-ctrack-paging-resultcount")

        if exact_match:
            # Speculative entry: never paginate.
            return

        try:
            received = int(result_count) if result_count else len(results)
        except ValueError:
            received = len(results)

        has_more = (
            more_results == "true" if more_results else received >= _PAGE_SIZE
        )
        if has_more and received > 0:
            yield from self._yield_search_request(
                prefix=prefix,
                start_index=start_index + received,
                court_id=court_id_hint or "",
                year=accumulated_data.get("year_hint") or 0,
            )

    # =========================================================================
    # Step 2: case detail
    # =========================================================================

    @step()
    def parse_case_detail(
        self,
        json_content: dict,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[KyDocket | KyDocument], None, None]:
        """Build the bare KyDocket from /cases/{caseID} and chain to entries."""
        case_id = accumulated_data["case_id"]

        case_number = json_content.get("caseNumber") or ""
        site_court = json_content.get("court") or ""
        court_id = SITE_COURT_TO_ID.get(site_court) or accumulated_data.get(
            "court_id_hint"
        )
        if not court_id:
            return

        docket = KyDocket(
            case_id=case_id,
            case_number=case_number,
            court_id=court_id,
            date_filed=_parse_iso_date(json_content.get("filedDate")),
            case_name=json_content.get("shortTitle") or case_number,
            case_type=json_content.get("caseType"),
            case_classification=json_content.get("caseClassification"),
            case_status=json_content.get("caseStatus"),
            status_date=_parse_iso_date(json_content.get("caseStatusDate")),
            closed=bool(json_content.get("closed")),
            court_level=json_content.get("courtLevel"),
            case_category=json_content.get("caseCategory"),
            full_title=json_content.get("fullTitle"),
            entries=[],
            parties=[],
            trial_courts=[],
            source_url=f"{PORTAL_URL}/case/{case_id}",
        )

        yield Request(
            request=HTTPRequestParams(
                method=HttpMethod.GET,
                url=f"{API_BASE_URL}/cases/{case_id}/docketentries",
                headers=_API_HEADERS,
            ),
            continuation=self.parse_docket_entries,
            accumulated_data={"docket_data": docket.model_dump(mode="json")},
        )

    # =========================================================================
    # Step 3: docket entries
    # =========================================================================

    @step()
    def parse_docket_entries(
        self,
        json_content: list,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[KyDocket | KyDocument], None, None]:
        """Parse the docket-entries array and chain to parties."""
        docket = KyDocket.model_validate(accumulated_data["docket_data"])

        entries: list[KyDocketEntry] = []
        for raw in json_content or []:
            entry_id = raw.get("docketEntryID")
            if not entry_id:
                continue
            custom = raw.get("customFields") or {}
            entries.append(
                KyDocketEntry(
                    docket_entry_id=entry_id,
                    date_filed=_parse_iso_date(raw.get("filedDate")),
                    entry_type=raw.get("docketEntryType"),
                    entry_subtype=raw.get("docketEntrySubtype"),
                    description=raw.get("docketEntryDescription"),
                    submitted_by=_normalize_submitted_by(
                        raw.get("submittedBy")
                    ),
                    comments=custom.get("Comments"),
                    is_opinion=bool(raw.get("opinion")),
                    has_documents=bool(raw.get("hasDocuments")),
                )
            )
        docket.entries = entries

        yield Request(
            request=HTTPRequestParams(
                method=HttpMethod.GET,
                url=f"{API_BASE_URL}/cases/{docket.case_id}/parties",
                headers=_API_HEADERS,
            ),
            continuation=self.parse_parties,
            accumulated_data={"docket_data": docket.model_dump(mode="json")},
        )

    # =========================================================================
    # Step 4: parties
    # =========================================================================

    @step()
    def parse_parties(
        self,
        json_content: list,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[KyDocket | KyDocument], None, None]:
        """Parse the parties array and chain to lower courts."""
        docket = KyDocket.model_validate(accumulated_data["docket_data"])

        parties: list[dict] = []
        for raw in json_content or []:
            name_obj = raw.get("partyName") or {}
            address = raw.get("address") or {}
            attorneys: list[dict] = []
            for att in raw.get("attorneys") or []:
                att_name = att.get("attorneyName") or {}
                att_addr = att.get("address") or {}
                attorneys.append(
                    {
                        "name": att_name.get("displayName"),
                        "role": att_name.get("role"),
                        "address": _format_address(att_addr),
                        "bar_number": att.get("barNumber"),
                    }
                )
            parties.append(
                {
                    "name": name_obj.get("displayName"),
                    "role": name_obj.get("role"),
                    "status": raw.get("partyStatus"),
                    "pro_se": bool(raw.get("proSe")),
                    "address": _format_address(address),
                    "attorneys": attorneys,
                }
            )
        docket.parties = parties

        yield Request(
            request=HTTPRequestParams(
                method=HttpMethod.GET,
                url=f"{API_BASE_URL}/cases/{docket.case_id}/lowercourts",
                headers=_API_HEADERS,
            ),
            continuation=self.parse_trial_courts,
            accumulated_data={"docket_data": docket.model_dump(mode="json")},
        )

    # =========================================================================
    # Step 5: trial / lower courts (and emit + fan out documents)
    # =========================================================================

    @step()
    def parse_trial_courts(
        self,
        json_content: list,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[KyDocket | KyDocument], None, None]:
        """Parse lower-court info, emit the docket, and fan out documents."""
        docket = KyDocket.model_validate(accumulated_data["docket_data"])

        trial_courts: list[dict] = []
        for raw in json_content or []:
            trial_courts.append(
                {
                    "name": raw.get("lowerCourtName"),
                    "case_number": raw.get("lowerCourtCaseNumber"),
                    "case_title": raw.get("lowerCourtCaseTitle"),
                }
            )
        docket.trial_courts = trial_courts

        yield ParsedData(data=docket)

        # Fan out one documents-list request per docket entry that has
        # documents. The list endpoint returns one record per file with
        # the documentID we need for the download URL.
        for de in docket.entries:
            if not de.has_documents:
                continue
            params = {
                "filter": (
                    f"parentCategory=docketentries,parentID={de.docket_entry_id}"
                ),
            }
            url = f"{API_BASE_URL}/publicaccessdocuments?{urlencode(params)}"
            yield Request(
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url=url,
                    headers=_API_HEADERS,
                ),
                continuation=self.parse_documents_list,
                accumulated_data={
                    "case_id": docket.case_id,
                    "case_number": docket.case_number,
                    "court_id": docket.court_id,
                    "docket_entry_id": de.docket_entry_id,
                },
                deduplication_key=f"docs:{de.docket_entry_id}",
            )

    # =========================================================================
    # Step 6: documents list -> per-file archive request
    # =========================================================================

    @step()
    def parse_documents_list(
        self,
        json_content: list,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[KyDocument], None, None]:
        """For each document on a docket entry, yield an archive request."""
        for raw in json_content or []:
            document_id = raw.get("documentID")
            if not document_id:
                continue
            download_url = f"{PORTAL_URL}/documents/{document_id}/download"
            mime = raw.get("mimeType") or ""
            expected_type = "pdf" if "pdf" in mime.lower() else "pdf"

            yield Request(
                archive=True,
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url=download_url,
                ),
                continuation=self.parse_document_download,
                expected_type=expected_type,
                accumulated_data={
                    **accumulated_data,
                    "document_id": document_id,
                    "dms_document_id": raw.get("dmsDocumentID"),
                    "document_name": raw.get("documentName"),
                    "document_description": raw.get("documentDescription"),
                    "parent_type": raw.get("parentType"),
                    "parent_subtype": raw.get("parentSubtype"),
                    "parent_date": raw.get("parentDate"),
                    "mime_type": raw.get("mimeType"),
                    "download_url": download_url,
                },
                deduplication_key=document_id,
            )

    # =========================================================================
    # Step 7: document download -> emit KyDocument
    # =========================================================================

    @step()
    def parse_document_download(
        self,
        local_filepath: str | None,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[KyDocument], None, None]:
        """Emit a KyDocument record for an archived file."""
        yield ParsedData(
            data=KyDocument(
                case_id=accumulated_data["case_id"],
                case_number=accumulated_data["case_number"],
                court_id=accumulated_data["court_id"],
                docket_entry_id=accumulated_data.get("docket_entry_id"),
                document_id=accumulated_data["document_id"],
                dms_document_id=accumulated_data.get("dms_document_id"),
                document_name=accumulated_data.get("document_name"),
                document_description=accumulated_data.get(
                    "document_description"
                ),
                parent_type=accumulated_data.get("parent_type"),
                parent_subtype=accumulated_data.get("parent_subtype"),
                parent_date=_parse_iso_date(
                    accumulated_data.get("parent_date")
                ),
                mime_type=accumulated_data.get("mime_type"),
                download_url=accumulated_data.get("download_url"),
                local_path=local_filepath,
            )
        )


def _normalize_submitted_by(value: object) -> str | None:
    """Coerce a docket entry's submittedBy to a string.

    The API sometimes returns a string and sometimes a list of party
    objects (each with ``displayName``). Flatten to a comma-separated
    display name list when needed.
    """
    if value is None or isinstance(value, str):
        return value or None
    if isinstance(value, list):
        names: list[str] = []
        for item in value:
            if isinstance(item, dict):
                name = item.get("displayName") or item.get("sortName")
                if name:
                    names.append(name)
            elif isinstance(item, str) and item:
                names.append(item)
        return ", ".join(names) if names else None
    return None


def _format_address(address: dict | None) -> str | None:
    """Flatten a C-Track address dict into a single string."""
    if not address:
        return None
    parts = [
        address.get("line1"),
        address.get("line2"),
        address.get("line3"),
        address.get("line4"),
    ]
    city = address.get("city")
    state = address.get("state")
    postal = address.get("postalCode")
    locality = ", ".join(p for p in (city, state) if p)
    if locality and postal:
        locality = f"{locality} {postal}"
    elif postal and not locality:
        locality = postal
    parts.append(locality or None)
    cleaned = [p.strip() for p in parts if p and p.strip()]
    return ", ".join(cleaned) if cleaned else None
