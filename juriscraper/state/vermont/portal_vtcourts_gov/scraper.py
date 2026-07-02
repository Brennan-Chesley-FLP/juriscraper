"""Vermont Judiciary Public Portal scraper.

Scrapes appellate dockets from the Supreme Court of Vermont via the
Tyler Odyssey Public Portal at
``https://portal.vtcourts.gov/Portal/Home/Dashboard/29``.

Unlike the sibling ``rhode_island/publicportal_courts_ri_gov``, the
Vermont deploy has neither reCAPTCHA nor DataDome, so this scraper runs
under the default HTTP driver. Per-case detail comes from a JSON OData
service (``/app/RegisterOfActionsService/``); the search-results grid and
the document-viewer landing page are HTML, parsed in the ``parsers``
package. The JSON steps keep their extraction inline (JKentParser /
PageElement are HTML-only; see SCRAPER_STANDARDS §3.5).

Entry points (§4):
    - dockets_by_number(docket_number)  — speculative ``YY-AP-NNN`` lookup
      at the Vermont Supreme Court (the only Vermont appellate court).

Flow per case::

    entry → submit_search_form     GET dashboard (primes session cookie);
                                    POST SmartSearch via form.submit()
          → fetch_results_grid     GET SmartSearchResults
          → parse_search_results   parse grid (SearchResultsParser), lift the
                                    ROA service key; request CaseSummariesSlim
          → parse_case_summary     fold JSON header into accumulated_data;
                                    request CombinedEvents
          → parse_combined_events  build VtDocketEntry list, gather doc
                                    descriptors; request Parties
          → parse_parties          build VtParty list; yield VtDocket; for each
                                    document, fan out a download chain
          → fetch_document_download  GET DisplayDoc (302) → DocumentViewer Index
                                    page; lift the Download href; archive the PDF
          → handle_document_download  yield VtDocument ParsedData
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar
from urllib.parse import urljoin

from jkent.common.decorators import entry, step
from jkent.data_types import (
    BaseScraper,
    DriverRequirement,
    HttpMethod,
    HTTPRequestParams,
    ParsedData,
    Request,
    Response,
    ScraperStatus,
    XPath,
)
from pyrate_limiter import Duration, Rate

from juriscraper.state.common.params import YearlySpeculativeRange

from .models import (
    COURT_ID,
    DASHBOARD_URL,
    DOC_DISPLAY_URL,
    PORTAL_URL,
    ROA_SERVICE_BASE,
    SEARCH_RESULTS_URL,
    VT_COURTS,
    VtAttorney,
    VtDocket,
    VtDocketEntry,
    VtDocument,
    VtParty,
)
from .parsers import SearchResultsParser, extract_download_href
from .parsers._common import parse_iso_date, parse_us_date

if TYPE_CHECKING:
    from collections.abc import Generator

    from jkent.common.page_element import PageElement
    from jkent.data_types import ScraperYield


# XPath for the Smart Search form. The form has id ``frmSS`` on this
# Tyler build.
SEARCH_FORM_XPATH = XPath("//form[@id='frmSS']")

# ``Accept`` header for JSON service requests — the OData service
# negotiates by Accept.
JSON_HEADERS = {"Accept": "application/json, text/plain, */*"}

# Page size for the events endpoint. The largest case observed during
# recon (24-AP-121) had 75 events; 200 leaves a comfortable margin
# without paginating. v1 will not paginate.
EVENTS_PAGE_SIZE = 200


_Yield = VtDocket | VtDocument


class VermontPortalScraper(BaseScraper[_Yield]):
    """Scraper for the Supreme Court of Vermont via the Tyler Odyssey
    Public Portal.

    Speculative single-case lookups by ``YY-AP-NNN`` docket number, one
    ``@entry`` since Vermont has only one appellate court (``vt``).
    """

    # === Metadata (§3) ===
    court_ids: ClassVar[set[str]] = set(VT_COURTS.keys())
    court_url: ClassVar[str] = DASHBOARD_URL
    data_types: ClassVar[set[str]] = {"dockets"}
    status: ClassVar[ScraperStatus] = ScraperStatus.IN_DEVELOPMENT
    version: ClassVar[str] = "2026-06-27"
    last_verified: ClassVar[str] = "2026-05-05"
    requires_auth: ClassVar[bool] = False

    # FOLLOW_REDIRECTS is needed for two reasons:
    # - the search form POST returns 302 → /Portal/Home/WorkspaceMode;
    # - the document DisplayDoc URL returns 302 → DocumentViewer/Index.
    driver_requirements: ClassVar[list[DriverRequirement]] = [
        DriverRequirement.FOLLOW_REDIRECTS,
    ]

    rate_limits: ClassVar[list[Rate] | None] = [Rate(2, Duration.SECOND)]

    # =========================================================================
    # Entry point — speculative by docket number, Supreme Court only (§4).
    # =========================================================================

    @entry(VtDocket)
    def dockets_by_number(
        self, docket_number: YearlySpeculativeRange
    ) -> Generator[Request, None, None]:
        """Speculative ``YY-AP-NNN`` lookup at the Vermont Supreme Court.

        Vermont is single-court, so this speculative entry carries no
        ``court_ids`` argument (the driver dispatches a speculative entry
        with only its speculative param — see SCRAPER_STANDARDS §4); the
        court is always ``vt``.

        Docket numbers are year-partitioned; we format ``:03d`` since the
        SmartSearch box accepts both ``26-AP-1`` and ``26-AP-001`` and the
        latter matches the convention published on the judiciary website.
        Operators seed one ``YearlySpeculativeRange`` template per year.
        """
        docket_id = (
            f"{docket_number.year % 100:02d}-AP-{docket_number.min:03d}"
        )
        yield Request(
            request=HTTPRequestParams(
                method=HttpMethod.GET,
                url=DASHBOARD_URL,
            ),
            continuation=self.submit_search_form,
            accumulated_data={
                "court_id": COURT_ID,
                "docket_number": docket_id,
                "year": docket_number.year,
            },
            deduplication_key=f"dockets_by_number:{docket_id}",
        )

    # =========================================================================
    # Step: fill and submit the search form.
    # =========================================================================

    @step(priority=8)
    def submit_search_form(
        self,
        page: PageElement,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[_Yield], None, None]:
        """Submit the smart-search form scoped to the Supreme Court.

        ``find_form().submit()`` preserves all hidden defaults (the
        ``Settings.Captcha*`` flags and the dozen ``caseCriteria.*``
        booleans) so we only have to override the two fields that
        actually matter.
        """
        court_location = VT_COURTS[accumulated_data["court_id"]]
        docket_id = accumulated_data["docket_number"]

        form = page.find_form(SEARCH_FORM_XPATH, "smart search form")
        yield form.submit(
            data={
                "caseCriteria.SearchCriteria": docket_id,
                "caseCriteria.CourtLocation": court_location,
            },
            continuation=self.fetch_results_grid,
            accumulated_data=accumulated_data,
        )

    # =========================================================================
    # Step: fetch the AJAX-rendered results grid.
    # =========================================================================

    @step(priority=7)
    def fetch_results_grid(
        self,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[_Yield], None, None]:
        """Pull the results grid in a separate GET.

        The form POST returns ``302 → /Portal/Home/WorkspaceMode``,
        which is just the empty workspace shell. The actual grid is
        AJAX-rendered by JS in the workspace, hitting the
        ``SmartSearchResults`` endpoint. The session cookie set by the
        POST scopes which results this returns.
        """
        yield Request(
            request=HTTPRequestParams(
                method=HttpMethod.GET,
                url=SEARCH_RESULTS_URL,
                params={"_": "1"},
            ),
            continuation=self.parse_search_results,
            accumulated_data=accumulated_data,
        )

    # =========================================================================
    # Step: parse the grid; lift the JSON-service key.
    # =========================================================================

    @step(priority=6)
    def parse_search_results(
        self,
        page: PageElement,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[_Yield], None, None]:
        """Find the case row, extract the Register-of-Actions ``key``,
        and request ``CaseSummariesSlim``.

        Soft-404: a non-existent docket renders as
        ``<p>No cases match your search</p>`` with no result table at
        all, so the parser returns an empty list. Returning without a
        ParsedData yield lets the speculation driver advance the gap
        counter for this seed.
        """
        rows = SearchResultsParser()(page)
        if not rows:
            # Speculative miss.
            return

        # The smart-search box is record-number-aware; for our exact
        # ``YY-AP-NNN`` query it returns at most one matching row.
        row = rows[0].raw_data

        accumulated_data.update(
            {
                "roa_key": row["roa_key"],
                "case_name": row.get("case_name") or row["docket_number"],
                "case_type_from_grid": row.get("case_type"),
                "case_status_from_grid": row.get("case_status"),
                "source_url": row.get("source_url"),
            }
        )

        yield Request(
            request=HTTPRequestParams(
                method=HttpMethod.GET,
                url=f"{ROA_SERVICE_BASE}/CaseSummariesSlim",
                params={"key": row["roa_key"], "mode": "portalembed"},
                headers=JSON_HEADERS,
            ),
            nonnavigating=True,
            continuation=self.parse_case_summary,
            accumulated_data=accumulated_data,
        )

    # =========================================================================
    # Step: parse case summary JSON; request CombinedEvents.
    # =========================================================================

    @step(priority=5)
    def parse_case_summary(
        self,
        json_content: dict,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[_Yield], None, None]:
        """Lift case-header fields and IDs needed for document URLs."""
        header = json_content.get("CaseSummaryHeader") or {}
        case_info = json_content.get("CaseInformation") or {}
        case_id_int = json_content.get("CaseId")
        node_id = header.get("NodeId")

        # Filing date + caption from the JSON service take precedence
        # over the grid's truncated values.
        accumulated_data["case_name"] = header.get(
            "Style"
        ) or accumulated_data.get("case_name")
        accumulated_data["filed_on"] = header.get("FiledOn")
        accumulated_data["case_id_int"] = case_id_int
        accumulated_data["node_id"] = node_id

        case_type = (case_info.get("CaseType") or {}).get("Description")
        accumulated_data["case_type"] = case_type or accumulated_data.get(
            "case_type_from_grid"
        )

        statuses = case_info.get("CaseStatuses") or []
        if statuses:
            status_desc = (statuses[0].get("CaseStatusId") or {}).get(
                "Description"
            )
            accumulated_data["case_status"] = (
                status_desc or accumulated_data.get("case_status_from_grid")
            )
        else:
            accumulated_data["case_status"] = accumulated_data.get(
                "case_status_from_grid"
            )

        # Disposition (most recent) — DispositionInformation may be
        # absent on cases that have not been decided yet.
        disp_info = json_content.get("DispositionInformation") or {}
        dispositions = disp_info.get("Dispositions") or []
        if dispositions:
            most_recent = dispositions[-1]
            accumulated_data["disposition"] = (
                most_recent.get("DispositionTypeId") or {}
            ).get("Description")
            accumulated_data["disposition_date"] = most_recent.get(
                "DispositionDate"
            )

        roa_key = accumulated_data["roa_key"]
        yield Request(
            request=HTTPRequestParams(
                method=HttpMethod.GET,
                url=f"{ROA_SERVICE_BASE}/CombinedEvents('{roa_key}')",
                params={
                    "mode": "portalembed",
                    "$top": str(EVENTS_PAGE_SIZE),
                    "$skip": "0",
                },
                headers=JSON_HEADERS,
            ),
            nonnavigating=True,
            continuation=self.parse_combined_events,
            accumulated_data=accumulated_data,
        )

    # =========================================================================
    # Step: parse events; collect documents; request Parties.
    # =========================================================================

    @step(priority=4)
    def parse_combined_events(
        self,
        json_content: dict,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[_Yield], None, None]:
        """Build the entry list and a documents-to-fetch list."""
        entries: list[VtDocketEntry] = []
        documents: list[dict[str, Any]] = []

        for event_wrapper in json_content.get("Events") or []:
            ev = event_wrapper.get("Event") or {}
            type_id = ev.get("TypeId") or {}
            description = type_id.get("Description") or ""
            if not description:
                continue
            date_filed = parse_us_date(event_wrapper.get("SortEventDate"))

            judicial_officer = _extract_judicial_officer(event_wrapper, ev)
            filer = _extract_filer(ev)

            doc_count = event_wrapper.get("DocumentCount") or 0
            entries.append(
                VtDocketEntry(
                    date_filed=date_filed,
                    description=description,
                    judicial_officer=judicial_officer,
                    filer=filer,
                    has_document=bool(doc_count),
                )
            )

            documents.extend(_extract_documents(ev, date_filed))

        accumulated_data["entries"] = [
            e.model_dump(mode="json") for e in entries
        ]
        accumulated_data["documents_to_fetch"] = documents

        roa_key = accumulated_data["roa_key"]
        yield Request(
            request=HTTPRequestParams(
                method=HttpMethod.GET,
                url=f"{ROA_SERVICE_BASE}/Parties('{roa_key}')",
                params={
                    "mode": "portalembed",
                    "$top": "50",
                    "$skip": "0",
                },
                headers=JSON_HEADERS,
            ),
            nonnavigating=True,
            continuation=self.parse_parties,
            accumulated_data=accumulated_data,
        )

    # =========================================================================
    # Step: parse parties; yield the assembled docket; fan out doc downloads.
    # =========================================================================

    @step(priority=3)
    def parse_parties(
        self,
        json_content: dict,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[_Yield], None, None]:
        """Final assembly: emit ``VtDocket``; queue document downloads."""
        parties: list[VtParty] = []
        for p in json_content.get("Parties") or []:
            parties.append(
                VtParty(
                    name=p.get("FormattedName") or "",
                    role=p.get("ConnectionType"),
                    attorneys=[
                        VtAttorney(
                            name=a.get("FormattedName") or "",
                            role=a.get("Appointment"),
                        )
                        for a in (p.get("CasePartyAttorneys") or [])
                        if a.get("FormattedName")
                    ],
                )
            )

        entries = [
            VtDocketEntry.model_validate(e)
            for e in accumulated_data.get("entries") or []
        ]

        document_descriptors = accumulated_data.get("documents_to_fetch") or []
        # Slim doc references on the docket itself — the archived
        # files come back as separate ParsedData records below.
        slim_documents = [
            VtDocument(
                docket_number=accumulated_data["docket_number"],
                court=accumulated_data["court_id"],
                document_id=d["document_id"],
                document_fragment_id=d["document_fragment_id"],
                document_name=d.get("document_name"),
                document_type=d.get("document_type"),
                date_filed=parse_iso_date(d.get("date_filed")),
            )
            for d in document_descriptors
        ]

        docket = VtDocket.raw(
            docket_number=accumulated_data["docket_number"],
            court=accumulated_data["court_id"],
            case_name=accumulated_data.get("case_name")
            or accumulated_data["docket_number"],
            date_filed=parse_us_date(accumulated_data.get("filed_on")),
            case_type=accumulated_data.get("case_type"),
            case_status=accumulated_data.get("case_status"),
            disposition=accumulated_data.get("disposition"),
            date_terminated=parse_us_date(
                accumulated_data.get("disposition_date")
            ),
            entries=entries,
            parties=parties,
            documents=slim_documents,
            source_url=accumulated_data.get("source_url"),
            source_entry_point="dockets_by_number",
        )
        yield ParsedData(docket)

        for d in document_descriptors:
            yield self._build_document_request(d, accumulated_data)

    # =========================================================================
    # Step: chase document download link.
    # =========================================================================

    @step(priority=2)
    def fetch_document_download(
        self,
        page: PageElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[_Yield], None, None]:
        """Lift the ``Download Document`` href and archive the PDF.

        FOLLOW_REDIRECTS turns the initial ``DisplayDoc`` 302 into a
        landing on ``DocumentViewer/Index``; if the case has restricted
        access (rare for Supreme Court) the page renders without a
        Download link, in which case we silently skip.
        """
        href = extract_download_href(page)
        if not href:
            return

        download_url = urljoin(response.url or PORTAL_URL, href)
        accumulated_data["download_url"] = download_url

        yield Request(
            archive=True,
            request=HTTPRequestParams(
                method=HttpMethod.GET,
                url=download_url,
            ),
            continuation=self.handle_document_download,
            expected_type="pdf",
            accumulated_data=accumulated_data,
        )

    # =========================================================================
    # Step: emit the archived document record.
    # =========================================================================

    @step(priority=2)
    def handle_document_download(
        self,
        local_filepath: str | None,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[_Yield], None, None]:
        """Yield a ``VtDocument`` referencing the archived PDF."""
        yield ParsedData(
            VtDocument.raw(
                docket_number=accumulated_data["docket_number"],
                court=accumulated_data["court_id"],
                document_id=accumulated_data["document_id"],
                document_fragment_id=accumulated_data["document_fragment_id"],
                document_name=accumulated_data.get("document_name"),
                document_type=accumulated_data.get("document_type"),
                date_filed=parse_iso_date(
                    accumulated_data.get("doc_date_filed")
                ),
                download_url=accumulated_data.get("download_url")
                or response.url,
                local_path=local_filepath,
            )
        )

    # =========================================================================
    # Internal helpers
    # =========================================================================

    def _build_document_request(
        self, doc: dict[str, Any], parent: dict
    ) -> Request:
        """Build the ``DisplayDoc`` request that starts a document chase."""
        return Request(
            request=HTTPRequestParams(
                method=HttpMethod.GET,
                url=DOC_DISPLAY_URL,
                params={
                    "documentID": doc["document_fragment_id"],
                    "caseNum": parent["docket_number"],
                    "locationId": str(parent.get("node_id") or ""),
                    "caseId": str(parent.get("case_id_int") or ""),
                    "docTypeId": doc.get("document_type_code") or "",
                    "isVersionId": "false",
                    "docType": doc.get("document_type") or "",
                    "docName": doc.get("document_name") or "",
                    "eventName": doc.get("event_name") or "",
                },
            ),
            continuation=self.fetch_document_download,
            accumulated_data={
                "court_id": parent["court_id"],
                "docket_number": parent["docket_number"],
                "document_id": doc["document_id"],
                "document_fragment_id": doc["document_fragment_id"],
                "document_name": doc.get("document_name"),
                "document_type": doc.get("document_type"),
                "doc_date_filed": doc.get("date_filed"),
            },
            deduplication_key=(
                f"{parent['docket_number']}-{doc['document_id']}"
            ),
        )


# =============================================================================
# Module-level JSON helpers (the JSON endpoints are HTML-free; no parser)
# =============================================================================


def _extract_judicial_officer(event_wrapper: dict, ev: dict) -> str | None:
    """Best-effort judge extraction.

    Tyler stores judges in several places depending on the event type
    (entry-order events vs. hearings vs. orders). We try the obvious
    fields and fall back to None.
    """
    judge_id = ev.get("JudgeId")
    if isinstance(judge_id, dict):
        name = judge_id.get("FormattedName") or judge_id.get("Description")
        if name:
            return name
    elif isinstance(judge_id, str) and judge_id:
        return judge_id
    # Sometimes the judge is listed under the wrapper-level "Judge"
    # field on hearing events.
    for key in ("Judge", "JudicialOfficer"):
        v = event_wrapper.get(key)
        if isinstance(v, str) and v:
            return v
        if isinstance(v, dict):
            name = v.get("FormattedName") or v.get("Description")
            if name:
                return name
    return None


def _extract_filer(ev: dict) -> str | None:
    """Format the first filer party-name on an event, if any.

    The ``Partys`` array on each event lists everyone associated with
    the event; the filer rows have ``ActKey == "F"``. We pick the
    first one for the entry summary.
    """
    for p in ev.get("Partys") or []:
        if p.get("ActKey") == "F":
            name = p.get("FormattedName")
            conn = p.get("ConnectionType")
            if name and conn:
                return f"{conn}: {name}"
            return name or conn
    return None


def _extract_documents(ev: dict, date_filed: Any) -> list[dict[str, Any]]:
    """Walk an event's ``Documents`` list and pull a flat descriptor."""
    out: list[dict[str, Any]] = []
    event_name = (ev.get("TypeId") or {}).get("Description")
    iso_date = date_filed.isoformat() if date_filed else None

    for doc in ev.get("Documents") or []:
        doc_id = doc.get("DocumentID")
        if not doc_id:
            continue
        type_id = doc.get("DocumentTypeID") or {}
        document_type = type_id.get("Description")
        document_type_code = type_id.get("CodeID")

        # Prefer the current version's fragment; fall back to the
        # singular DocumentVersion.
        fragment_id = _pluck_fragment_id(doc.get("DocumentVersions"))
        if not fragment_id:
            fragment_id = _pluck_fragment_id(
                [doc.get("DocumentVersion")]
                if doc.get("DocumentVersion")
                else []
            )
        if not fragment_id:
            continue

        out.append(
            {
                "document_id": str(doc_id),
                "document_fragment_id": str(fragment_id),
                "document_name": doc.get("DocumentName"),
                "document_type": document_type,
                "document_type_code": document_type_code,
                "event_name": event_name,
                "date_filed": iso_date,
            }
        )
    return out


def _pluck_fragment_id(versions: Any) -> str | None:
    """Return the first ``DocumentFragmentID`` seen in the version tree."""
    if not versions:
        return None
    for version in versions:
        if not version:
            continue
        for fragment in version.get("DocumentFragments") or []:
            fid = fragment.get("DocumentFragmentID")
            if fid:
                return str(fid)
            # Some payloads carry the fragment id only on the viewer
            # intent under URI.
            for intent in fragment.get("DocumentViewerIntents") or []:
                uri = intent.get("URI")
                if uri:
                    return str(uri)
    return None
