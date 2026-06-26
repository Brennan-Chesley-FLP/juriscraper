"""Missouri Case.net appellate docket scraper.

Scrapes dockets from Missouri's Case.net public-access portal at
``https://www.courts.mo.gov/casenet/`` for the Supreme Court of Missouri
plus the three Court of Appeals districts (Eastern, Southern, Western).

The portal is behind Cloudflare's managed challenge. Search results and
case-detail tabs are JSON APIs underneath, even though the user-facing
search form is server-rendered HTML — once Cloudflare's cookie is set
on the Playwright context, all data flows through JSON endpoints:

- ``searchResult.do`` — DataTables-style results listing
- ``cases/newHeaderData.do`` — case header
- ``cases/party.do`` — parties + attorneys
- ``cases/docketEntriesSearch.do`` — docket entries + document refs

Because every data path is a JSON endpoint (no XPath / HTML parsing),
this scraper follows the JSON-API shape (no ``parsers/`` package);
extraction lives in small static builders on the scraper.

The site search uses a fixed 7-day filing-date window. The
``dockets_by_filing_date`` entry point splits the seeded date range into
7-day chunks, fans out (4 courts × N chunks) search requests, and walks
each search hit through the case-detail JSON endpoints.

Entry points (§4):
    - dockets_by_filing_date(court_ids, date_range) — chunked date scan.
    - docket_by_number(court_id, docket_number)     — direct case lookup.

Flow per case::

    warmup_session (GET filingDateSearch.do) — clears Cloudflare
      └─ for each (court, 7-day window):
         parse_search_results (POST searchResult.do, length=1000)
            └─ for each hit:
               parse_case_header (POST cases/newHeaderData.do)
                  └─ parse_case_parties (POST cases/party.do)
                     └─ parse_case_docket (POST cases/docketEntriesSearch.do)
                        ├─ emit MoDocket (with parties + entries + doc refs)
                        └─ for each non-confidential document:
                           handle_document_download (archive=True GET /fv/c/...)
                              └─ emit MoDocument with filepath_local
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING, ClassVar
from urllib.parse import quote, urlencode

from jkent.common.decorators import entry, step
from jkent.common.param_models import DateRange
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
    CL_COURT_TO_COUNTY,
    CL_COURT_TO_SITE,
    COURT_IDS,
    SITE_COURT_TO_CL,
    MoAttorney,
    MoDocket,
    MoDocketEntry,
    MoDocument,
    MoParty,
    MoTrialCourtInfo,
)

if TYPE_CHECKING:
    from collections.abc import Generator

    from jkent.data_types import ScraperYield


BASE_URL = "https://www.courts.mo.gov"
SEARCH_FORM_URL = f"{BASE_URL}/casenet/filingDateSearch.do"
SEARCH_RESULTS_URL = f"{BASE_URL}/casenet/searchResult.do"
CASE_HEADER_URL = f"{BASE_URL}/casenet/cases/newHeaderData.do"
CASE_PARTY_URL = f"{BASE_URL}/casenet/cases/party.do"
CASE_DOCKET_URL = f"{BASE_URL}/casenet/cases/docketEntriesSearch.do"
CASE_PAGE_URL_TEMPLATE = (
    f"{BASE_URL}/casenet/cases/newHeader.do"
    "?inputVO.caseNumber={docket_number}&inputVO.courtId={court_id}"
)

# 7 days inclusive (server uses Start..Start+6 inclusive).
SEARCH_CHUNK_DAYS = 7

# DataTables column descriptors mirror the order the in-page DataTable
# sends. The server only inspects ``start``/``length``/``draw`` for our
# purposes but we send the full structure to match the legitimate XHR.
_DT_COLUMNS = [
    {
        "data": 0,
        "name": "",
        "searchable": True,
        "orderable": True,
        "search": {"value": "", "regex": False},
    },
    {
        "data": "initFiling",
        "name": "",
        "searchable": True,
        "orderable": True,
        "search": {"value": "", "regex": False},
    },
    {
        "data": "caseNumber",
        "name": "",
        "searchable": True,
        "orderable": True,
        "search": {"value": "", "regex": False},
    },
    {
        "data": "caseStyle",
        "name": "",
        "searchable": True,
        "orderable": True,
        "search": {"value": "", "regex": False},
    },
    {
        "data": "caseType",
        "name": "",
        "searchable": True,
        "orderable": True,
        "search": {"value": "", "regex": False},
    },
    {
        "data": "countyDesc",
        "name": "",
        "searchable": True,
        "orderable": True,
        "search": {"value": "", "regex": False},
    },
]


def _parse_mdy(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.strptime(value.strip(), "%m/%d/%Y").date()
    except ValueError:
        return None


def _format_mdy(d: date) -> str:
    return d.strftime("%m/%d/%Y")


def _build_search_url(court_cl_id: str, start: date) -> str:
    params = {
        "countyCode": CL_COURT_TO_COUNTY[court_cl_id],
        "newSearch": "Y",
        "courtCode": CL_COURT_TO_SITE[court_cl_id],
        "startDate": _format_mdy(start),
        "caseStatus": "A",
        "caseType": "All",
        "locationCode": "",
    }
    return f"{SEARCH_RESULTS_URL}?{urlencode(params)}"


def _build_search_body(start: int = 0, length: int = 1000) -> str:
    return json.dumps(
        {
            "draw": 1,
            "columns": _DT_COLUMNS,
            "order": [{"column": 0, "dir": "asc"}],
            "start": start,
            "length": length,
            "search": {"value": "", "regex": False},
        }
    )


def _build_form_body(**fields: str) -> str:
    return urlencode(fields)


_Yield = MoDocket | MoDocument


class MissouriCaseNetScraper(BaseScraper[_Yield]):
    """Scraper for the four Missouri appellate courts on Case.net.

    Covers the Supreme Court and the Eastern, Southern, and Western
    Districts of the Court of Appeals. The site is Cloudflare-gated and
    served via a mix of HTML and JSON endpoints; we drive everything
    through Playwright (for the JS challenge) but the data path is
    JSON-API-only after the initial warmup.
    """

    court_ids: ClassVar[set[str]] = set(COURT_IDS.keys())
    court_url: ClassVar[str] = SEARCH_FORM_URL
    data_types: ClassVar[set[str]] = {"dockets"}
    status: ClassVar[ScraperStatus] = ScraperStatus.IN_DEVELOPMENT
    version: ClassVar[str] = "2026-05-04"
    last_verified: ClassVar[str] = "2026-05-04"
    requires_auth: ClassVar[bool] = False
    driver_requirements: ClassVar[list[DriverRequirement]] = [
        DriverRequirement.JS_EVAL,
        DriverRequirement.FF_ALIKE,
    ]

    rate_limits: ClassVar[list[Rate] | None] = [Rate(2, Duration.SECOND)]

    # =========================================================================
    # HTTP handling
    # =========================================================================

    def actually_successful(self, response: Response) -> bool:
        """Treat the Cloudflare interstitial as a non-success.

        A cold client gets a 200 with the "Just a moment…" challenge body
        instead of the form/JSON; the Playwright driver clears it, but if
        the challenge body slips through we don't want to treat it as a
        valid (empty) page.
        """
        if response.status_code != 200:
            return response.status_code < 400
        body = (response.text or "")[:4096].lower()
        return "just a moment" not in body and "challenge-platform" not in body

    # =========================================================================
    # Search-parameter helpers
    # =========================================================================

    @staticmethod
    def _iter_chunks(
        date_gte: date, date_lte: date
    ) -> Generator[date, None, None]:
        """Yield the first day of each 7-day window covering [gte, lte]."""
        cur = date_gte
        while cur <= date_lte:
            yield cur
            cur = cur + timedelta(days=SEARCH_CHUNK_DAYS)

    # =========================================================================
    # Entry points
    # =========================================================================

    @entry(MoDocket)
    def dockets_by_filing_date(
        self, court_ids: set[str], date_range: DateRange
    ) -> Generator[Request, None, None]:
        """Enumerate dockets filed within ``date_range`` for ``court_ids``.

        The site enforces a 7-day filing-date window per query, so the
        scraper splits ``date_range`` into 7-day chunks and submits one
        search per (court, chunk) — fanning out up to 4 × N requests. The
        requested ``court_ids`` ride down the chain so unrelated courts in
        the configured set aren't searched.
        """
        targets = sorted(court_ids & set(CL_COURT_TO_SITE))
        if not targets or date_range.start > date_range.end:
            return
        yield self._build_warmup_request(
            after=self._dispatch_search_chunks,
            extra={
                "date_gte": date_range.start.isoformat(),
                "date_lte": date_range.end.isoformat(),
                "target_courts": targets,
            },
        )

    @entry(MoDocket)
    def docket_by_number(
        self, court_id: str, docket_number: str
    ) -> Generator[Request, None, None]:
        """Look up a specific case by docket number + CourtListener court id.

        Bypasses the search step. ``court_id`` must be one of the
        scraper's ``court_ids`` (e.g. "mo", "moctapped").
        """
        if court_id not in CL_COURT_TO_SITE:
            raise ValueError(
                f"Unknown court_id {court_id!r}; "
                f"expected one of {sorted(CL_COURT_TO_SITE)}"
            )
        yield self._build_warmup_request(
            after=self._dispatch_single_case,
            extra={
                "single_docket_number": docket_number.upper(),
                "single_court_id": court_id,
            },
        )

    # =========================================================================
    # Warmup → fan-out
    # =========================================================================

    def _build_warmup_request(
        self,
        after: str,
        extra: dict,
    ) -> Request:
        """One initial GET to the search form.

        Lets the Playwright driver clear Cloudflare's managed challenge
        and obtain the bot-protection cookie. The continuation then
        dispatches the actual data-fetching POSTs as ``nonnavigating``
        requests inside the same browser context.
        """
        return Request(
            request=HTTPRequestParams(
                method=HttpMethod.GET,
                url=SEARCH_FORM_URL,
            ),
            continuation=after,
            accumulated_data=extra,
            deduplication_key=SkipDeduplicationCheck(),
        )

    @step(priority=6)
    def _dispatch_search_chunks(
        self,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[_Yield], None, None]:
        """Fan out (courts) × N (7-day windows) search POSTs."""
        date_gte = date.fromisoformat(accumulated_data["date_gte"])
        date_lte = date.fromisoformat(accumulated_data["date_lte"])

        for court_cl_id in accumulated_data["target_courts"]:
            for chunk_start in self._iter_chunks(date_gte, date_lte):
                yield self._build_search_request(court_cl_id, chunk_start)

    @step(priority=6)
    def _dispatch_single_case(
        self,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[_Yield], None, None]:
        """Direct lookup path used by ``docket_by_number``."""
        yield self._build_case_header_request(
            docket_number=accumulated_data["single_docket_number"],
            court_cl_id=accumulated_data["single_court_id"],
        )

    # =========================================================================
    # Search request + parser
    # =========================================================================

    def _build_search_request(
        self, court_cl_id: str, chunk_start: date
    ) -> Request:
        return Request(
            request=HTTPRequestParams(
                method=HttpMethod.POST,
                url=_build_search_url(court_cl_id, chunk_start),
                data=_build_search_body(),
                headers={
                    "Content-Type": "application/json;charset=UTF-8",
                    "Accept": "application/json, text/javascript, */*; q=0.01",
                    "X-Requested-With": "XMLHttpRequest",
                },
            ),
            continuation=self.parse_search_results,
            nonnavigating=True,
            accumulated_data={
                "court_id": court_cl_id,
                "chunk_start": chunk_start.isoformat(),
            },
            deduplication_key=SkipDeduplicationCheck(),
        )

    @step(priority=5)
    def parse_search_results(
        self,
        json_content: dict,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[_Yield], None, None]:
        """Walk one search response; emit a header-fetch per hit.

        ``length=1000`` is well above any realistic 7-day appellate
        volume, so we don't paginate here — the response carries every
        case for the (court, week) pair in a single payload.
        """
        court_cl_id: str = accumulated_data["court_id"]
        rows = json_content.get("data") or []

        for row in rows:
            docket_number = row.get("caseNumber") or ""
            site_court_id = (
                row.get("dbSource") or CL_COURT_TO_SITE[court_cl_id]
            )
            if not docket_number:
                continue
            # The hit's dbSource sometimes differs from the court being
            # searched (e.g. cases that originated in another district).
            # Trust the hit and re-route accordingly when recognised.
            resolved_court_cl_id = SITE_COURT_TO_CL.get(
                site_court_id, court_cl_id
            )
            yield self._build_case_header_request(
                docket_number=docket_number,
                court_cl_id=resolved_court_cl_id,
                site_court_id=site_court_id,
            )

    # =========================================================================
    # Case header → parties → docket entries
    # =========================================================================

    def _build_case_header_request(
        self,
        docket_number: str,
        court_cl_id: str,
        site_court_id: str | None = None,
    ) -> Request:
        site_court_id = site_court_id or CL_COURT_TO_SITE[court_cl_id]
        return Request(
            request=HTTPRequestParams(
                method=HttpMethod.POST,
                url=CASE_HEADER_URL,
                data=_build_form_body(
                    caseNumber=docket_number,
                    courtId=site_court_id,
                    isTicket="",
                    locnCode="",
                    isCriminal="",
                    diposed="",
                    pleaAndPayInd="",
                ),
                headers={
                    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                    "Accept": "application/json, text/javascript, */*; q=0.01",
                    "X-Requested-With": "XMLHttpRequest",
                },
            ),
            continuation=self.parse_case_header,
            nonnavigating=True,
            accumulated_data={
                "docket_number": docket_number,
                "court_id": court_cl_id,
                "site_court_id": site_court_id,
            },
            # Dedup on the docket number so overlapping windows (or a
            # re-run with a wider range) don't re-fetch case detail.
            deduplication_key=f"case_detail:{docket_number}",
        )

    @step(priority=4)
    def parse_case_header(
        self,
        json_content: dict,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[_Yield], None, None]:
        """Stash header fields and chain into the parties endpoint."""
        if not json_content or not json_content.get("caseNumber"):
            # Soft-404 — the API returns a near-empty body for unknown cases.
            return

        accumulated_data["header"] = json_content
        # The short courtCode used in document URLs comes off the header.
        accumulated_data["doc_court_code"] = (
            json_content.get("courtCode") or ""
        )

        docket_number: str = accumulated_data["docket_number"]
        site_court_id: str = accumulated_data["site_court_id"]

        yield Request(
            request=HTTPRequestParams(
                method=HttpMethod.POST,
                url=CASE_PARTY_URL,
                data=_build_form_body(
                    caseNumber=docket_number,
                    courtId=site_court_id,
                    isTicket="",
                ),
                headers={
                    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                    "Accept": "application/json, text/javascript, */*; q=0.01",
                    "X-Requested-With": "XMLHttpRequest",
                },
            ),
            continuation=self.parse_case_parties,
            nonnavigating=True,
            accumulated_data=accumulated_data,
        )

    @step(priority=3)
    def parse_case_parties(
        self,
        json_content: dict,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[_Yield], None, None]:
        """Stash parties+attorneys and chain into the docket-entries endpoint."""
        accumulated_data["parties_payload"] = json_content or {}

        docket_number: str = accumulated_data["docket_number"]
        site_court_id: str = accumulated_data["site_court_id"]

        url = f"{CASE_DOCKET_URL}?displayOption=A&sortOption=D&hasChange=false"
        yield Request(
            request=HTTPRequestParams(
                method=HttpMethod.POST,
                url=url,
                data=_build_form_body(
                    caseNumber=docket_number,
                    courtId=site_court_id,
                    isTicket="",
                    tabName="Docket",
                ),
                headers={
                    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                    "Accept": "application/json, text/javascript, */*; q=0.01",
                    "X-Requested-With": "XMLHttpRequest",
                },
            ),
            continuation=self.parse_case_docket,
            nonnavigating=True,
            accumulated_data=accumulated_data,
        )

    @step(priority=2)
    def parse_case_docket(
        self,
        json_content: dict,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[_Yield], None, None]:
        """Assemble the full ``MoDocket`` and schedule document downloads."""
        header = accumulated_data.get("header") or {}
        parties_payload = accumulated_data.get("parties_payload") or {}
        docket_payload = json_content or {}

        court_cl_id: str = accumulated_data["court_id"]
        site_court_id: str = accumulated_data["site_court_id"]
        docket_number: str = accumulated_data["docket_number"]
        doc_court_code: str = accumulated_data.get("doc_court_code") or ""

        parties = self._build_parties(parties_payload)
        entries, documents = self._build_entries_and_documents(
            docket_payload,
            doc_court_code=doc_court_code,
            docket_number=docket_number,
        )
        trial_courts = self._build_trial_court_refs(header)

        docket = MoDocket.raw(
            docket_number=docket_number,
            court=court_cl_id,
            site_court_id=site_court_id,
            case_name=(header.get("caseDesc") or "").strip(),
            date_filed=_parse_mdy(header.get("filingDate")),
            case_type=header.get("caseType"),
            case_type_code=header.get("caseTypeCode"),
            location=header.get("location"),
            disposition=(
                (header.get("caseDispositionDetail") or {}).get(
                    "dispositionDescription"
                )
            ),
            disposed=bool(header.get("disposed")),
            dismissed=(header.get("dismissed") or "").upper() == "T",
            appellate_origin=(
                (header.get("appellateOriginNo") or {}).get("caseValue")
            ),
            related_appellate_docket=(
                (header.get("appellateCaseNo") or {}).get("caseValue")
            ),
            related_appellate_court=SITE_COURT_TO_CL.get(
                (header.get("appellateCaseNo") or {}).get("courtId") or ""
            ),
            trial_courts=trial_courts,
            parties=parties,
            entries=entries,
            documents=documents,
            source_url=CASE_PAGE_URL_TEMPLATE.format(
                docket_number=docket_number, court_id=site_court_id
            ),
            source_entry_point="dockets_by_filing_date",
        )

        yield ParsedData(data=docket)

        for doc in documents:
            yield Request(
                archive=True,
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url=doc.download_url,
                ),
                continuation=self.handle_document_download,
                expected_type="pdf",
                nonnavigating=True,
                accumulated_data={
                    "docket_number": docket_number,
                    "court_id": court_cl_id,
                    "document": doc.model_dump(mode="json"),
                },
                # File-download keys avoid colons (used in filenames).
                deduplication_key=(
                    f"{docket_number}-{doc.docket_sequence}-"
                    f"{doc.document_id}.{doc.document_extension.lower()}"
                ),
            )

    @step(priority=0)
    def handle_document_download(
        self,
        local_filepath: str | None,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[_Yield], None, None]:
        """Wrap the archived PDF as an ``MoDocument`` with ``filepath_local``."""
        if not local_filepath:
            return
        doc = MoDocument(**accumulated_data["document"])
        doc.filepath_local = local_filepath
        yield ParsedData(data=doc)

    # =========================================================================
    # Builders
    # =========================================================================

    @staticmethod
    def _build_parties(payload: dict) -> list[MoParty]:
        parties: list[MoParty] = []
        for entry_dict in payload.get("partyDetailsList") or []:
            if entry_dict.get("partyType") != "party":
                continue
            attorneys: list[MoAttorney] = []
            for atty in entry_dict.get("attorneyList") or []:
                attorneys.append(
                    MoAttorney(
                        name=(atty.get("formattedPartyName") or "").strip(),
                        role=atty.get("desc"),
                        role_code=atty.get("descCode"),
                        address=atty.get("formattedPartyAddress") or None,
                        phone=atty.get("formattedTelePhone") or None,
                        date_start=_parse_mdy(atty.get("startDate")),
                    )
                )
            parties.append(
                MoParty(
                    name=(entry_dict.get("formattedPartyName") or "").strip(),
                    role=entry_dict.get("desc"),
                    role_code=entry_dict.get("descCode"),
                    address=entry_dict.get("formattedPartyAddress") or None,
                    phone=entry_dict.get("formattedTelePhone") or None,
                    date_start=_parse_mdy(entry_dict.get("startDate")),
                    attorneys=attorneys,
                )
            )
        return parties

    @staticmethod
    def _build_trial_court_refs(header: dict) -> list[MoTrialCourtInfo]:
        refs: list[MoTrialCourtInfo] = []
        for ref in header.get("circuitCaseNo") or []:
            case_value = ref.get("caseValue")
            if not case_value:
                continue
            refs.append(
                MoTrialCourtInfo(
                    docket_number=case_value,
                    court_id=ref.get("courtId"),
                )
            )
        origin = (header.get("appellateOriginNo") or {}).get("caseValue")
        if origin and not any(r.label == origin for r in refs):
            refs.append(MoTrialCourtInfo(docket_number=origin, label=origin))
        return refs

    @classmethod
    def _build_entries_and_documents(
        cls,
        payload: dict,
        doc_court_code: str,
        docket_number: str,
    ) -> tuple[list[MoDocketEntry], list[MoDocument]]:
        entries: list[MoDocketEntry] = []
        documents: list[MoDocument] = []
        rows = payload.get("docketTabModelList") or []
        # Site returns newest-first; reverse so entries[] is oldest-first
        # to match the on-screen Docket Entries tab default reading order.
        for row in reversed(rows):
            entries.append(
                MoDocketEntry(
                    date_filed=_parse_mdy(row.get("filingDate")),
                    description=(row.get("docketDesc") or "").strip(),
                    text=row.get("docketText") or None,
                    sequence_number=row.get("sequenceNumber"),
                    docket_code=row.get("docketCode"),
                    filing_party_name=(row.get("filingPartyFullName") or None),
                    filing_party_role=row.get("eventDesc"),
                    behalf_of_parties=(
                        row.get("behalfOfPartiesNames") or None
                    ),
                    confidential=bool(row.get("confidential")),
                )
            )
            if not row.get("canSeeCaseDocuments"):
                continue
            seq = row.get("sequenceNumber")
            seen: set[int] = set()
            for doc in row.get("document") or []:
                documents.extend(
                    cls._collect_document_tree(
                        doc,
                        doc_court_code=doc_court_code,
                        docket_seq=seq,
                        parent_id=None,
                        seen=seen,
                    )
                )
        return entries, documents

    @classmethod
    def _collect_document_tree(
        cls,
        doc: dict,
        doc_court_code: str,
        docket_seq: int | None,
        parent_id: int | None,
        seen: set[int],
    ) -> Generator[MoDocument, None, None]:
        """Walk a docket entry's documents + nested ``documentModels``.

        Case.net wraps supplementary attachments (e.g. the underlying
        Court of Appeals opinion that came in with an Application for
        Transfer) under a ``documentModels`` array on the parent doc —
        and the parent itself is repeated as ``documentModels[0]`` with
        the same id before the actual sub-attachments. We flatten the
        tree into ``MoDocument`` records, dedupe by id within a docket
        entry, and carry ``parent_document_id`` to preserve the wrapper
        relationship.
        """
        document_id = (
            doc.get("documentId") or doc.get("cebdmsdId") or doc.get("docId")
        )
        title = (
            doc.get("documentTitle") or doc.get("cebdmsdDesc") or ""
        ).strip()
        ext = doc.get("documentExtension") or doc.get("cebdmsdExt") or "PDF"
        next_parent = parent_id
        if document_id and title and int(document_id) not in seen:
            seen.add(int(document_id))
            yield MoDocument(
                download_url=(
                    f"{BASE_URL}/fv/c/{quote(title)}.{ext}"
                    f"?courtCode={doc_court_code}&di={document_id}"
                ),
                document_id=int(document_id),
                document_title=title,
                document_extension=ext,
                docket_sequence=docket_seq,
                parent_document_id=parent_id,
            )
            next_parent = int(document_id)
        for child in doc.get("documentModels") or []:
            yield from cls._collect_document_tree(
                child,
                doc_court_code=doc_court_code,
                docket_seq=docket_seq,
                parent_id=next_parent,
                seen=seen,
            )
