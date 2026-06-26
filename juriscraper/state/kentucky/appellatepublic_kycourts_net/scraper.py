"""Kentucky Appellate Courts Scraper.

Scrapes docket data from the Kentucky Court of Justice C-Track Public
Access portal at https://appellatepublic.kycourts.net.

This is the JSON-API "C-Track Public Access" product — distinct from both
the newer "TR Portal" (``juriscraper.state.common.tr``) and the older
HTML-form C-Track (``juriscraper.state.common.ctrack``). Endpoints live
under ``/api/api/v1/`` on the same host as the Vue.js frontend, return
plain JSON, and paginate via ``x-ctrack-paging-*`` HTTP headers rather
than query parameters. Because everything is JSON (no HTML parsing), there
is no ``parsers/`` package (SCRAPER_STANDARDS §3.5); extraction lives in
the steps and small module-level helpers.

Supported courts:
- Kentucky Supreme Court (``ky``) — case numbers ``YYYY-SC-####``
- Kentucky Court of Appeals (``kyctapp``) — case numbers ``YYYY-CA-####``

Entry points (§4):
    - dockets_by_filing_date(court_ids, date_range) — there is no
      date-based docket search, but case numbers are year-partitioned, so
      the date range drives a per-(court, year) case-number prefix search.
    - dockets_by_number(docket_number: KyCourtYearRange) — speculative
      single-case probe; the target court + year ride in the param.
    - docket_by_number(court_id, docket_number) — direct lookup of one
      already-known case number.

Flow:
  search → parse_search_results  (paginates; one detail fetch per caseID)
    → parse_case_detail          (/cases/{caseID}; builds bare KyDocket)
      → parse_docket_entries     (/cases/{caseID}/docketentries)
        → parse_parties          (/cases/{caseID}/parties)
          → parse_trial_courts   (/cases/{caseID}/lowercourts; emits the
                                   KyDocket + fans out documents)
            → parse_documents_list (/publicaccessdocuments per entry)
              → parse_document_download (archive; emits KyDocument)
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING, ClassVar
from urllib.parse import urlencode

from jkent.common.decorators import entry, step
from jkent.common.param_models import DateRange, YearlySpeculativeRange
from jkent.data_types import (
    BaseScraper,
    DriverRequirement,
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
    KyAttorney,
    KyDocket,
    KyDocketEntry,
    KyDocument,
    KyParty,
    KyTrialCourt,
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

# Pagination tuning. The server caps total enumerable results per query at
# 10,000 (returned in ``x-ctrack-paging-resultslimit``) but each
# (year, court) prefix returns at most ~3500 results, so a single search
# per year is always safe.
_PAGE_SIZE: int = 200

# Earliest year of available records (defensive floor for the year loop).
# The portal carries data back to at least 1990.
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

    ``start_index`` is 1-based. Asking for the total count is cheap and only
    useful on the first page, so we always set it.
    """
    return {
        **_API_HEADERS,
        "x-ctrack-paging-startindex": str(start_index),
        "x-ctrack-paging-maxresults": str(max_results),
        "x-ctrack-paging-calculatetotalcount": "true",
    }


def _normalize_submitted_by(value: object) -> str | None:
    """Coerce a docket entry's submittedBy to a string.

    The API sometimes returns a string and sometimes a list of party
    objects (each with ``displayName``). Flatten to a comma-separated
    display-name list when needed.
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


class KyCourtYearRange(YearlySpeculativeRange):
    """A year-partitioned speculative range tagged with its CL court id.

    Kentucky case numbers are partitioned by both court and year
    (``YYYY-{SC,CA}-####``). A speculative entry is dispatched with **only**
    its speculative param (SCRAPER_STANDARDS §4, "Multi-court speculative
    entries"), so the target court rides here alongside the year. Seed one
    template per (court, year); ``from_int`` advances ``min`` while
    preserving ``court_id`` and ``year`` via ``model_copy``.

    Example seed (one Supreme Court year + one Court of Appeals year)::

        seed_params = [
            {"dockets_by_number": {"docket_number":
                {"court_id": "ky", "year": 2026, "min": 1,
                 "soft_max": 1, "gap": 15}}},
            {"dockets_by_number": {"docket_number":
                {"court_id": "kyctapp", "year": 2026, "min": 1,
                 "soft_max": 1, "gap": 15}}},
        ]
    """

    court_id: str
    """CourtListener court id this range probes (``ky`` or ``kyctapp``)."""

    def case_number(self) -> str:
        """Build the public case number for the current probe position."""
        prefix = COURT_CASE_PREFIX[self.court_id]
        return f"{self.year}-{prefix}-{self.min:04d}"


class KentuckyAppellateScraper(BaseScraper[KyDocket | KyDocument]):
    """Scraper for Kentucky Supreme Court and Court of Appeals dockets.

    Speaks the ``/api/api/v1`` C-Track JSON API directly (plain HTTP).
    Yields:

    - ``KyDocket`` — one per case, with nested entries / parties /
      trial-courts.
    - ``KyDocument`` — one per archived file; joins back to the parent
      docket via ``case_id`` / ``docket_number``.
    """

    # === Metadata ===
    court_ids: ClassVar[set[str]] = {"ky", "kyctapp"}
    court_url: ClassVar[str] = PORTAL_URL
    data_types: ClassVar[set[str]] = {"dockets"}
    status: ClassVar[ScraperStatus] = ScraperStatus.IN_DEVELOPMENT
    version: ClassVar[str] = "2026-06-27"
    last_verified: ClassVar[str] = "2026-05-03"
    requires_auth: ClassVar[bool] = False
    driver_requirements: ClassVar[list[DriverRequirement]] = []
    rate_limits: ClassVar[list[Rate] | None] = [Rate(4, Duration.SECOND)]

    # =========================================================================
    # Soft-404 detection (speculative probing)
    # =========================================================================

    def actually_successful(self, response: Response) -> bool:
        """Return False for empty search results (a speculation miss).

        The search endpoint returns HTTP 200 with an empty ``resultItems``
        array for a case number that does not exist. Only treat the search
        endpoint specially; other endpoints return real 404s for missing
        IDs.
        """
        if "/cases/search" not in response.url:
            return True
        # Empty resultItems is the miss signal. Use a substring check so we
        # don't pay the cost of JSON parsing on every response.
        text = response.text or ""
        return '"resultItems":[]' not in text.replace(" ", "")

    # =========================================================================
    # Entry points (§4)
    # =========================================================================

    @entry(KyDocket)
    def dockets_by_filing_date(
        self, court_ids: set[str], date_range: DateRange
    ) -> Generator[Request, None, None]:
        """Crawl every case filed in ``date_range`` for each target court.

        There is no date-based docket search, but Kentucky case numbers are
        year-partitioned (``YYYY-{SC|CA}-####``), so the date range is
        widened to whole years and a paginated case-number prefix search is
        issued per (court, year). ``court_ids`` is seeded by the driver and
        intersected with the courts this scraper supports.
        """
        target_courts = court_ids & self.court_ids
        start_year = max(_OLDEST_YEAR, date_range.start.year)
        end_year = min(date.today().year, date_range.end.year)
        if start_year > end_year:
            return

        for year in range(start_year, end_year + 1):
            for court_id in sorted(target_courts):
                court_prefix = COURT_CASE_PREFIX[court_id]
                yield from self._yield_search_request(
                    prefix=f"{year}-{court_prefix}",
                    start_index=1,
                    court_id=court_id,
                    entry_point="dockets_by_filing_date",
                )

    @entry(KyDocket)
    def dockets_by_number(self, docket_number: KyCourtYearRange) -> Request:
        """Speculatively fetch one case by case number for one (court, year).

        ``docket_number.court_id`` selects the court and ``docket_number.year``
        the partition; the driver probes ``{year}-{SC|CA}-{n:04d}`` for
        ascending ``n`` and advances until ``gap`` consecutive misses. Seed
        once per (court, year) — see :class:`KyCourtYearRange`.
        """
        return self._make_speculative_request(
            docket_number.court_id,
            docket_number.case_number(),
            entry_point="dockets_by_number",
        )

    @entry(KyDocket)
    def docket_by_number(self, court_id: str, docket_number: str) -> Request:
        """Direct lookup of one already-known case number.

        Looks up the caseID via the search endpoint, then walks the case
        detail. ``court_id`` is the CourtListener id of the court the case
        belongs to.
        """
        return self._make_speculative_request(
            court_id, docket_number, entry_point="docket_by_number"
        )

    # =========================================================================
    # Search request builders
    # =========================================================================

    def _yield_search_request(
        self,
        prefix: str,
        start_index: int,
        court_id: str,
        entry_point: str,
    ) -> Generator[Request, None, None]:
        """Yield one page of a prefix search."""
        url = _build_search_url(prefix)
        # Pagination requests must always run; otherwise the URL-only dedup
        # key would swallow page 2+ as duplicates of page 1.
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
                "entry_point": entry_point,
            },
            deduplication_key=dedup,
        )

    def _make_speculative_request(
        self, court_id: str, case_number: str, entry_point: str
    ) -> Request:
        """Build a search request for one specific case number."""
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
                "exact_match": case_number,
                "entry_point": entry_point,
            },
            deduplication_key=f"search:{case_number}",
        )

    # =========================================================================
    # Step 1: parse search results, fan out into per-case fetches
    # =========================================================================

    @step(priority=6)
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
        entry_point = accumulated_data.get("entry_point")

        results = json_content.get("resultItems") or []
        for item in results:
            row = item.get("rowMap") or {}
            case_id = row.get("caseID") or item.get("id")
            case_number = row.get("caseNumber")
            if not case_id or not case_number:
                continue

            # For exact lookups / speculative probes, only follow the exact
            # match — search returns adjacent / partial matches we skip.
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
                    "source_entry_point": entry_point,
                },
                deduplication_key=f"case_detail:{case_id}",
            )

        # Pagination: drive off response headers when present, otherwise off
        # the resultItems length to be defensive against header stripping on
        # the way through proxies.
        headers = response.headers or {}
        more_results = (
            headers.get("x-ctrack-paging-moreresults") or ""
        ).lower()
        result_count = headers.get("x-ctrack-paging-resultcount")

        if exact_match:
            # Exact lookup / speculative entry: never paginate.
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
                entry_point=entry_point or "dockets_by_filing_date",
            )

    # =========================================================================
    # Step 2: case detail
    # =========================================================================

    @step(priority=5)
    def parse_case_detail(
        self,
        json_content: dict,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[KyDocket | KyDocument], None, None]:
        """Build the bare KyDocket from /cases/{caseID} and chain to entries."""
        case_id = accumulated_data["case_id"]

        case_number = json_content.get("caseNumber") or ""
        site_court = json_content.get("court") or ""
        court = SITE_COURT_TO_ID.get(site_court) or accumulated_data.get(
            "court_id_hint"
        )
        if not court:
            return

        docket = KyDocket(
            case_id=case_id,
            docket_number=case_number,
            docket_number_raw=case_number,
            court=court,
            date_filed=_parse_iso_date(json_content.get("filedDate")),
            case_name=json_content.get("shortTitle") or case_number,
            case_name_full=json_content.get("fullTitle"),
            case_type=json_content.get("caseType"),
            case_classification=json_content.get("caseClassification"),
            case_status=json_content.get("caseStatus"),
            date_status=_parse_iso_date(json_content.get("caseStatusDate")),
            closed=bool(json_content.get("closed")),
            court_level=json_content.get("courtLevel"),
            case_category=json_content.get("caseCategory"),
            entries=[],
            parties=[],
            trial_courts=[],
            source_url=f"{PORTAL_URL}/case/{case_id}",
            source_entry_point=accumulated_data.get("source_entry_point"),
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

    @step(priority=4)
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

    @step(priority=3)
    def parse_parties(
        self,
        json_content: list,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[KyDocket | KyDocument], None, None]:
        """Parse the parties array and chain to lower courts."""
        docket = KyDocket.model_validate(accumulated_data["docket_data"])

        parties: list[KyParty] = []
        for raw in json_content or []:
            name_obj = raw.get("partyName") or {}
            address = raw.get("address") or {}
            attorneys: list[KyAttorney] = []
            for att in raw.get("attorneys") or []:
                att_name = att.get("attorneyName") or {}
                att_addr = att.get("address") or {}
                attorneys.append(
                    KyAttorney(
                        name=att_name.get("displayName"),
                        role=att_name.get("role"),
                        address=_format_address(att_addr),
                        bar_number=att.get("barNumber"),
                    )
                )
            parties.append(
                KyParty(
                    name=name_obj.get("displayName"),
                    role=name_obj.get("role"),
                    status=raw.get("partyStatus"),
                    pro_se=bool(raw.get("proSe")),
                    address=_format_address(address),
                    attorneys=attorneys,
                )
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

    @step(priority=2)
    def parse_trial_courts(
        self,
        json_content: list,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[KyDocket | KyDocument], None, None]:
        """Parse lower-court info, emit the docket, and fan out documents."""
        docket = KyDocket.model_validate(accumulated_data["docket_data"])

        trial_courts: list[KyTrialCourt] = []
        for raw in json_content or []:
            trial_courts.append(
                KyTrialCourt(
                    name=raw.get("lowerCourtName"),
                    docket_number=raw.get("lowerCourtCaseNumber"),
                    case_title=raw.get("lowerCourtCaseTitle"),
                )
            )
        docket.trial_courts = trial_courts

        yield ParsedData(data=docket)

        # Fan out one documents-list request per docket entry that has
        # documents. The list endpoint returns one record per file with the
        # documentID we need for the download URL.
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
                    "docket_number": docket.docket_number,
                    "court": docket.court,
                    "docket_entry_id": de.docket_entry_id,
                },
                deduplication_key=f"documents_list:{de.docket_entry_id}",
            )

    # =========================================================================
    # Step 6: documents list -> per-file archive request
    # =========================================================================

    @step(priority=2)
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

            yield Request(
                archive=True,
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url=download_url,
                ),
                continuation=self.parse_document_download,
                expected_type="pdf",
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
                # Used in the archived filename, so avoid colons.
                deduplication_key=(
                    f"{accumulated_data['docket_number']}-{document_id}"
                ),
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
            data=KyDocument.raw(
                case_id=accumulated_data["case_id"],
                docket_number=accumulated_data["docket_number"],
                court=accumulated_data["court"],
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
                filepath_local=local_filepath,
            )
        )
