"""Arkansas Appellate Courts Scraper.

Scrapes docket data from the Arkansas Supreme Court (``ark``) and the
Arkansas Court of Appeals (``arkctapp``) via the public JSON API at
``caseinfo.arcourts.gov/opad``. The site is a Next.js frontend over a
plain REST backend; no HTML parsing is required.

Entry point:

- ``dockets_by_filing_date(court_ids, date_range)`` — fans out one search
  per requested court (``ark`` → Supreme Court, ``arkctapp`` → Court of
  Appeals).

Flow per case:

1. ``parse_search_results``   — paginates the search response and
                                 dispatches one detail request per case.
2. ``parse_case_detail``      — builds the ``ArDocket`` from the detail
                                 payload and schedules a presigned-URL
                                 fetch for every document on the case's
                                 docket entries.
3. ``fetch_document_url``     — reads ``{"url": ...}`` and schedules an
                                 ``archive=True`` request to S3.
4. ``archive_document``       — emits the ``ArDocument`` once the file is
                                 on disk.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import TYPE_CHECKING, Any, ClassVar

from jkent.common.decorators import entry, step
from jkent.common.param_models import DateRange
from jkent.data_types import (
    BaseScraper,
    HttpMethod,
    HTTPRequestParams,
    ParsedData,
    Request,
    Response,
    ScraperStatus,
)
from pyrate_limiter import Duration, Rate

from juriscraper.state.common.params import InferrableDateRange

from .models import (
    COURT_ID_TO_NAME,
    COURT_NAME_TO_ID,
    ArDocket,
    ArDocketEntry,
    ArDocument,
    ArMilestone,
    ArParty,
)

if TYPE_CHECKING:
    from collections.abc import Generator

    from jkent.data_types import ScraperYield


BASE_URL = "https://caseinfo.arcourts.gov/opad"
SEARCH_URL = f"{BASE_URL}/api/cases/search"
CASE_DETAIL_URL = f"{BASE_URL}/api/cases"
DOCUMENT_URL = f"{BASE_URL}/api/documents"

# pageSize=500 works; 1000 returns HTTP 500. 500 keeps page count low for
# the largest single-year court (~1500 results / year for CoA).
PAGE_SIZE = 500


class ArkansasAppellateScraper(BaseScraper[ArDocket | ArDocument]):
    """Scraper for Arkansas Supreme Court and Court of Appeals.

    Speaks the ``/opad`` JSON API directly. Yields:

    - ``ArDocket`` — one per case, with nested entries / parties /
      milestones.
    - ``ArDocument`` — one per archived file, carrying its own docket
      metadata. Joinable back to the parent docket via ``docket_number``.
    """

    court_ids: ClassVar[set[str]] = {"ark", "arkctapp"}
    court_url: ClassVar[str] = BASE_URL
    data_types: ClassVar[set[str]] = {"dockets"}
    status: ClassVar[ScraperStatus] = ScraperStatus.IN_DEVELOPMENT
    version: ClassVar[str] = "2026-05-02"
    requires_auth: ClassVar[bool] = False
    rate_limits: ClassVar[list[Rate] | None] = [Rate(3, Duration.SECOND)]

    # =========================================================================
    # Entry points
    # =========================================================================

    @entry(ArDocket)
    def dockets_by_filing_date(
        self, court_ids: set[str], date_range: InferrableDateRange
    ) -> Generator[Request, None, None]:
        """Fetch dockets filed in ``date_range`` for each requested court.

        ``court_ids`` is a set of CourtListener court ids (``ark``,
        ``arkctapp``); each is dispatched to its caseinfo search path.
        Unknown ids are rejected so a typo fails loudly rather than
        silently scraping nothing.
        """
        unknown = [cid for cid in court_ids if cid not in COURT_ID_TO_NAME]
        if unknown:
            raise ValueError(
                f"Unknown Arkansas court id(s): {unknown}. "
                f"Supported: {sorted(COURT_ID_TO_NAME)}."
            )
        for court_id in court_ids:
            yield self._build_search_request(
                COURT_ID_TO_NAME[court_id], date_range, page=1
            )

    # =========================================================================
    # Step 1: search results + pagination
    # =========================================================================

    @step()
    def parse_search_results(
        self,
        json_content: dict,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[ArDocket], None, None]:
        """Dispatch a detail fetch per hit and request the next page."""
        court_name = accumulated_data["court_name"]

        for hit in json_content.get("items") or []:
            docket_number = hit.get("caseId")
            if not docket_number:
                continue
            yield Request(
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url=f"{CASE_DETAIL_URL}/{docket_number}",
                ),
                continuation=self.parse_case_detail,
                accumulated_data={"court_name": court_name},
                deduplication_key=f"ar-case-{docket_number}",
            )

        paging = json_content.get("paging") or {}
        current_page = int(paging.get("pageNumber", 1))
        total_pages = int(paging.get("totalPages", 0))
        if current_page < total_pages:
            date_range = DateRange(
                start=date.fromisoformat(accumulated_data["date_start"]),
                end=date.fromisoformat(accumulated_data["date_end"]),
            )
            yield self._build_search_request(
                court_name, date_range, page=current_page + 1
            )

    # =========================================================================
    # Step 2: case detail
    # =========================================================================

    @step()
    def parse_case_detail(
        self,
        json_content: dict,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[ArDocket | ArDocument], None, None]:
        """Build an ``ArDocket`` and schedule document downloads."""
        docket_number = json_content["caseId"]
        court_name = (
            json_content.get("courtName") or accumulated_data["court_name"]
        )
        court_id = COURT_NAME_TO_ID.get(court_name, "")

        entries = self._parse_dockets(json_content.get("caseDockets") or [])
        parties = self._parse_parties(
            json_content.get("caseParticipants") or []
        )
        milestones = self._parse_milestones(
            json_content.get("caseMilestones") or []
        )

        docket = ArDocket(
            docket_number=docket_number,
            court_id=court_id,
            date_filed=_parse_iso_date(json_content.get("caseFilingDate")),
            case_name=json_content.get("caseDesc") or docket_number,
            case_title=json_content.get("caseTitle"),
            case_type=json_content.get("caseType"),
            trial_desc=json_content.get("caseTrialDesc"),
            status=json_content.get("statusDesc"),
            court_name=court_name,
            court_location=json_content.get("courtLocation"),
            sealed_flag=json_content.get("caseSealed"),
            security_level=json_content.get("caseSecurity"),
            entries=entries,
            parties=parties,
            milestones=milestones,
            raw_events=json_content.get("caseEvents") or [],
            raw_offenses=json_content.get("caseOffenses") or [],
            raw_sentences=json_content.get("caseSentences") or [],
            source_url=response.url,
        )
        yield ParsedData(data=docket)

        # Schedule a presigned-URL fetch for every referenced document.
        # Each document's metadata rides on accumulated_data and lands on
        # the emitted ArDocument; it joins back to this docket via
        # docket_number, so nothing needs to be stored on the ArDocket.
        seen: set[str] = set()
        for d in json_content.get("caseDockets") or []:
            docket_seq_no = d.get("docketSeqNo")
            docket_entry_desc = d.get("docketDesc")
            docket_entry_filed = _parse_iso_date(d.get("docketFilingDate"))
            for doc in d.get("docketDocuments") or []:
                file_id = doc.get("documentFileId")
                if not file_id or file_id in seen:
                    continue
                seen.add(file_id)
                upload_date = _parse_iso_date(doc.get("documentUploadDate"))
                yield Request(
                    request=HTTPRequestParams(
                        method=HttpMethod.GET,
                        url=f"{DOCUMENT_URL}/{file_id}",
                    ),
                    continuation=self.fetch_document_url,
                    accumulated_data={
                        "docket_number": docket_number,
                        "court_id": court_id,
                        "document_file_id": file_id,
                        "document_name": doc.get("documentName"),
                        "description": doc.get("documentDesc"),
                        "docket_seq_no": docket_seq_no,
                        "docket_entry_description": docket_entry_desc,
                        "docket_entry_date_filed": (
                            docket_entry_filed.isoformat()
                            if docket_entry_filed
                            else None
                        ),
                        "upload_date": (
                            upload_date.isoformat() if upload_date else None
                        ),
                    },
                    deduplication_key=f"ar-doc-{file_id}",
                )

    # =========================================================================
    # Step 3: presigned URL fetch
    # =========================================================================

    @step()
    def fetch_document_url(
        self,
        json_content: dict,
        accumulated_data: dict,
    ) -> Generator[Request, None, None]:
        """Read the presigned S3 URL and schedule the archive download."""
        download_url = json_content.get("url")
        if not download_url:
            return
        accumulated_data["download_url"] = download_url
        yield Request(
            archive=True,
            request=HTTPRequestParams(method=HttpMethod.GET, url=download_url),
            continuation=self.archive_document,
            expected_type="pdf",
            bypass_rate_limit=True,  # AWS S# signed links with expiration
            accumulated_data=accumulated_data,
            # Presigned URLs expire ~10 minutes after issuance, so dedup
            # against the underlying file id rather than the URL.
            deduplication_key=(
                f"ar-doc-archive-{accumulated_data['document_file_id']}"
            ),
        )

    # =========================================================================
    # Step 4: archived file → ArDocument
    # =========================================================================

    @step()
    def archive_document(
        self,
        local_filepath: str | None,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[ArDocument], None, None]:
        """Emit an ``ArDocument`` record for an archived file."""
        upload_raw = accumulated_data.get("upload_date")
        entry_filed_raw = accumulated_data.get("docket_entry_date_filed")
        yield ParsedData(
            data=ArDocument.raw(
                docket_number=accumulated_data["docket_number"],
                court_id=accumulated_data["court_id"],
                document_file_id=accumulated_data["document_file_id"],
                document_name=accumulated_data.get("document_name"),
                description=accumulated_data.get("description"),
                docket_seq_no=accumulated_data.get("docket_seq_no"),
                docket_entry_description=accumulated_data.get(
                    "docket_entry_description"
                ),
                docket_entry_date_filed=(
                    date.fromisoformat(entry_filed_raw)
                    if entry_filed_raw
                    else None
                ),
                upload_date=(
                    date.fromisoformat(upload_raw) if upload_raw else None
                ),
                download_url=accumulated_data["download_url"],
                local_path=local_filepath,
            )
        )

    # =========================================================================
    # Search-request builder
    # =========================================================================

    def _build_search_request(
        self, court_name: str, date_range: DateRange, *, page: int
    ) -> Request:
        body = self._build_search_body(court_name, date_range, page)
        return Request(
            request=HTTPRequestParams(
                method=HttpMethod.POST,
                url=SEARCH_URL,
                headers={"Content-Type": "application/json"},
                json=body,
            ),
            continuation=self.parse_search_results,
            accumulated_data={
                "court_name": court_name,
                "date_start": date_range.start.isoformat(),
                "date_end": date_range.end.isoformat(),
                "page": page,
            },
            # Pagination requests must always execute even when the URL is
            # identical (POST body changes between pages).
            deduplication_key=f"{court_name}.{date_range.start}.{date_range.end}-{page}",
        )

    @staticmethod
    def _build_search_body(
        court_name: str, date_range: DateRange, page: int
    ) -> dict[str, Any]:
        # Day boundaries in UTC, anchored to Central Time (UTC-5/-6) so
        # the result set matches the site's UI.
        start_iso = (
            datetime.combine(date_range.start, datetime.min.time())
            .replace(tzinfo=timezone.utc)
            .strftime("%Y-%m-%dT05:00:00.000Z")
        )
        end_iso = (
            datetime.combine(date_range.end, datetime.min.time())
            .replace(tzinfo=timezone.utc)
            .strftime("%Y-%m-%dT04:59:59.999Z")
        )
        return {
            "caseSearchRequest": {
                "searchCriteria": {
                    "filterBy": [
                        [
                            {
                                "fieldName": "CourtName",
                                "operator": "EQUALS",
                                "fieldValue": court_name,
                            }
                        ]
                    ],
                    "paging": {"pageSize": PAGE_SIZE, "pageNumber": page},
                },
                "startDate": start_iso,
                "endDate": end_iso,
                "caseType": "",
                "docketDesc": "",
            }
        }

    # =========================================================================
    # Detail-payload parsing
    # =========================================================================

    @staticmethod
    def _parse_dockets(raw: list[dict]) -> list[ArDocketEntry]:
        entries: list[ArDocketEntry] = []
        raw_sorted = sorted(
            raw,
            key=lambda e: (
                e.get("docketSeqNo", None) is None,
                e.get("docketSeqNo"),
            ),
        )
        for d in raw_sorted:
            entries.append(
                {
                    "docket_seq_no": d.get("docketSeqNo"),
                    "docket_type": d.get("docketType"),
                    "description": d.get("docketDesc"),
                    "text": d.get("docketText"),
                    "date_filed": _parse_iso_date(d.get("docketFilingDate")),
                    "entity_id": d.get("entityId"),
                    "entity_name": d.get("entityName"),
                }
            )
        return entries

    @staticmethod
    def _parse_parties(raw: list[dict]) -> list[ArParty]:
        parties: list[ArParty] = []
        for p in raw:
            name = (p.get("name") or "").strip()
            role = (p.get("partyType") or "").strip()
            if not name or not role:
                continue
            aliases_raw = p.get("aliases") or ""
            aliases = [a.strip() for a in aliases_raw.split(",") if a.strip()]
            parties.append(
                ArParty(
                    seq_no=p.get("seqNo"),
                    name=name,
                    role=role,
                    entity_id=p.get("entityId"),
                    aliases=aliases,
                )
            )
        return parties

    @staticmethod
    def _parse_milestones(raw: list[dict]) -> list[ArMilestone]:
        return [
            ArMilestone.raw(
                milestone_code=m.get("milestoneCode"),
                description=m.get("milestoneDesc"),
                seq_no=m.get("milestoneSeqNo"),
                order_seq_no=m.get("milestoneOseqNo"),
                due_date=_parse_iso_date(m.get("dueDate")),
                changed_due_date=_parse_iso_date(m.get("changedDueDate")),
                filing_date=_parse_iso_date(m.get("filingDate")),
            )
            for m in raw
        ]


def _parse_iso_date(value: str | None) -> date | None:
    """Parse an ISO timestamp like ``2026-04-30T16:53:46.000Z`` to a date.

    The API also emits malformed historical timestamps (e.g. year ``0200``
    or ``1099``) for some pre-digital records. Those parse cleanly as
    ``datetime`` objects but are obviously wrong; we still surface them as
    ``date`` because suppressing them would silently lose the field, and
    consumers can detect the sentinel year if they care.
    """
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except ValueError:
        return None
