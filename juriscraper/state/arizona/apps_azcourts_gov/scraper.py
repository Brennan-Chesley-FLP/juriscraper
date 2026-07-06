"""Arizona appellate-courts scraper (Supreme + Court of Appeals Div. 1).

Scrapes active case-list pages and three index pages (Lower Court, Party,
Attorney) from the AppellaDockets system at apps.azcourts.gov. Both supported
courts (``ariz`` and ``arizctapp``) sit on the same backend and share the
same HTML row format; each entry takes ``court_ids`` and fans out to the
matching site URLs per court. Plain HTTP — server-rendered static HTML, no
bot protection.

Closed-case docket PDFs are deleted from the public site 15 days after the
case closes — see CC_NOTES.md.

Per-page HTML extraction lives in the ``parsers`` package; the steps keep
navigation concerns (per-court/case-type fan-out, the ``_update`` cutoff
early-stop, and PDF archive requests).

Entry points (§4):
    - dockets_by_updated_date(court_ids, date_range)  — walk ``_update`` pages
      (sorted by Last Updated DESC) per court, emit rows inside the window.
    - dockets_by_bulk(court_ids)                       — walk every case-type
      page per court end-to-end.
    - lower_court_cases_by_bulk(court_ids)             — Lower Court Index.
    - party_cases_by_bulk(court_ids)                   — Party Index.
    - attorney_cases_by_bulk(court_ids)                — Attorney Index.
"""

from __future__ import annotations

from datetime import datetime, time
from typing import TYPE_CHECKING, ClassVar

from jkent.common.decorators import entry, step
from jkent.common.exceptions import ScraperAssumptionException
from jkent.data_types import (
    BaseScraper,
    DriverRequirement,
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
    BASE_URL,
    COURTS,
    AzAppAttorneyCase,
    AzAppDocket,
    AzAppDocument,
    AzAppLowerCourtCase,
    AzAppPartyCase,
)
from .parsers import (
    AttorneyIndexParser,
    CaseListParser,
    LowerCourtIndexParser,
    PartyIndexParser,
)

if TYPE_CHECKING:
    from collections.abc import Generator

    from jkent.common.page_element import PageElement
    from jkent.data_types import ScraperYield

_Yield = (
    AzAppDocket
    | AzAppDocument
    | AzAppLowerCourtCase
    | AzAppPartyCase
    | AzAppAttorneyCase
)


def _site_id(court_id: str) -> str:
    """Resolve a courts-db ``court_id`` to its AppellaDockets site code."""
    return COURTS[court_id]["site_id"]


def _case_list_url(court_id: str, case_type: str, *, by_update: bool) -> str:
    """Build a case-type list URL.

    The ``_update`` variant is sorted by Last Updated descending; the
    canonical variant is sorted by case number ascending.
    """
    site = _site_id(court_id)
    suffix = "_update" if by_update else ""
    return f"{BASE_URL}stage_{site}_{case_type}{suffix}.htm"


def _index_url(court_id: str, kind: str) -> str:
    """Build an index page URL (``lower_court`` / ``party`` / ``attorney``)."""
    site = _site_id(court_id)
    paths = {
        "lower_court": f"000_{site}_LOWERCOURT_INDEX.HTM",
        "party": f"000_{site}_party_index.HTM",
        "attorney": f"000_{site}_ATTY_INDEX.HTM",
    }
    return BASE_URL + paths[kind]


class ArizonaAppellateScraper(BaseScraper[_Yield]):
    """Scraper for the Arizona Supreme Court and Court of Appeals (Div. 1).

    See ``CC_NOTES.md`` in this directory for site analysis. Each entry
    point takes ``court_ids`` (a subset of ``ariz`` / ``arizctapp``).
    """

    # === Metadata ===
    court_ids: ClassVar[set[str]] = set(COURTS)
    court_url: ClassVar[str] = "https://www.azcourts.gov/appellatecourtcases/"
    data_types: ClassVar[set[str]] = {"dockets"}
    status: ClassVar[ScraperStatus] = ScraperStatus.IN_DEVELOPMENT
    version: ClassVar[str] = "2026-06-26"
    last_verified: ClassVar[str] = "2026-05-02"
    requires_auth: ClassVar[bool] = False
    driver_requirements: ClassVar[list[DriverRequirement]] = []
    rate_limits: ClassVar[list[Rate] | None] = [Rate(2, Duration.SECOND)]

    # =========================================================================
    # Helpers
    # =========================================================================

    @staticmethod
    def _known_courts(court_ids: set[str]) -> list[str]:
        """Return the requested courts this scraper actually supports.

        Raises if none of the requested ids are known, so a misconfigured
        run fails loudly rather than scraping nothing.
        """
        known = [c for c in sorted(court_ids) if c in COURTS]
        if not known:
            raise ScraperAssumptionException(
                f"none of court_ids {sorted(court_ids)!r} are supported; "
                f"known: {sorted(COURTS)!r}"
            )
        return known

    def _pdf_archive_request(
        self,
        *,
        pdf_url: str,
        docket_number: str,
        court: str,
        source: str,
        date_last_updated: datetime | None = None,
    ) -> Request:
        """Build an archive request for a docket PDF.

        Keyed by ``court`` + PDF basename so the same PDF referenced from
        multiple indices (case-list / lower-court / party / attorney) is
        fetched only once, and so the two courts can't collide on a shared
        basename.

        When ``date_last_updated`` is known (the case-list flow — the index
        pages don't carry it), its ``YYYY-MM-DD`` is spliced into the key
        just before the ``.pdf`` suffix, e.g. ``ariz-ASC_CR260127.pdf`` →
        ``ariz-ASC_CR260127.2026-07-03.pdf``. This makes each revision of a
        docket sheet archive as a distinct object (the docket PDF is
        regenerated in place under the same URL, so without the stamp a
        newer version would dedup against the stale copy).
        """
        filename = pdf_url.replace("\\", "/").rsplit("/", 1)[-1]
        if date_last_updated is not None:
            stem, dot, ext = filename.rpartition(".")
            stamp = date_last_updated.strftime("%Y-%m-%d")
            filename = (
                f"{stem}.{stamp}{dot}{ext}" if dot else f"{filename}.{stamp}"
            )
        return Request(
            archive=True,
            request=HTTPRequestParams(method=HttpMethod.GET, url=pdf_url),
            continuation=self.handle_pdf_archive,
            expected_type="pdf",
            accumulated_data={
                "court": court,
                "docket_number": docket_number,
                "document_url": pdf_url,
                "source": source,
            },
            deduplication_key=f"{court}-{filename}",
        )

    # =========================================================================
    # Entry points (§4)
    # =========================================================================

    @entry(AzAppDocket)
    def dockets_by_updated_date(
        self, court_ids: set[str], date_range: InferrableDateRange
    ) -> Generator[Request, None, None]:
        """Walk each court's ``_update`` pages (Last Updated DESC) and emit
        every active docket whose Last Updated falls within ``date_range``.

        Short-circuits each page once it sees a row older than
        ``date_range.start`` (rows are newest-first).
        """
        start_dt = datetime.combine(date_range.start, time.min).isoformat()
        end_dt = datetime.combine(date_range.end, time.max).isoformat()
        for court in self._known_courts(court_ids):
            for case_type in COURTS[court]["case_types"]:
                yield Request(
                    request=HTTPRequestParams(
                        method=HttpMethod.GET,
                        url=_case_list_url(court, case_type, by_update=True),
                        headers={"Accept": "text/html"},
                    ),
                    continuation=self.parse_case_list_update,
                    accumulated_data={
                        "court": court,
                        "case_type": case_type,
                        "start_dt": start_dt,
                        "end_dt": end_dt,
                    },
                    deduplication_key=f"case_list_update:{court}:{case_type}",
                )

    @entry(AzAppDocket)
    def dockets_by_bulk(
        self, court_ids: set[str]
    ) -> Generator[Request, None, None]:
        """Walk every case-type page for each court end-to-end.

        Use this for an initial backfill or a full snapshot; for incremental
        nightly runs, prefer :meth:`dockets_by_updated_date`.
        """
        for court in self._known_courts(court_ids):
            for case_type in COURTS[court]["case_types"]:
                yield Request(
                    request=HTTPRequestParams(
                        method=HttpMethod.GET,
                        url=_case_list_url(court, case_type, by_update=False),
                        headers={"Accept": "text/html"},
                    ),
                    continuation=self.parse_case_list_full,
                    accumulated_data={"court": court, "case_type": case_type},
                    deduplication_key=f"case_list_full:{court}:{case_type}",
                )

    @entry(AzAppLowerCourtCase)
    def lower_court_cases_by_bulk(
        self, court_ids: set[str]
    ) -> Generator[Request, None, None]:
        """Fetch and parse the Lower Court Index for each court."""
        for court in self._known_courts(court_ids):
            yield Request(
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url=_index_url(court, "lower_court"),
                    headers={"Accept": "text/html"},
                ),
                continuation=self.parse_lower_court_index,
                accumulated_data={"court": court},
                deduplication_key=f"lower_court_index:{court}",
            )

    @entry(AzAppPartyCase)
    def party_cases_by_bulk(
        self, court_ids: set[str]
    ) -> Generator[Request, None, None]:
        """Fetch and parse the Party Index for each court."""
        for court in self._known_courts(court_ids):
            yield Request(
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url=_index_url(court, "party"),
                    headers={"Accept": "text/html"},
                ),
                continuation=self.parse_party_index,
                accumulated_data={"court": court},
                deduplication_key=f"party_index:{court}",
            )

    @entry(AzAppAttorneyCase)
    def attorney_cases_by_bulk(
        self, court_ids: set[str]
    ) -> Generator[Request, None, None]:
        """Fetch and parse the Attorney Index for each court."""
        for court in self._known_courts(court_ids):
            yield Request(
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url=_index_url(court, "attorney"),
                    headers={"Accept": "text/html"},
                ),
                continuation=self.parse_attorney_index,
                accumulated_data={"court": court},
                deduplication_key=f"attorney_index:{court}",
            )

    # =========================================================================
    # Step: parse case-type list pages
    # =========================================================================

    @step(priority=2)
    def parse_case_list_update(
        self,
        page: PageElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[_Yield], None, None]:
        """Parse a ``_update`` page top-down, stopping past the window.

        Rows are sorted by Last Updated DESC. Rows newer than ``end_dt`` are
        skipped; the walk breaks at the first row older than ``start_dt``.
        Rows with no timestamp are emitted but don't stop the walk.
        """
        court = accumulated_data["court"]
        case_type = accumulated_data["case_type"]
        start_dt = datetime.fromisoformat(accumulated_data["start_dt"])
        end_dt = datetime.fromisoformat(accumulated_data["end_dt"])

        for docket in CaseListParser()(page):
            ts = docket.raw_data.get("date_last_updated")
            if ts is not None:
                if ts > end_dt:
                    continue
                if ts < start_dt:
                    # Sorted DESC — everything after this is older.
                    break
            yield from self._emit_docket(
                docket,
                court=court,
                case_type=case_type,
                source_url=response.url,
            )

    @step(priority=2)
    def parse_case_list_full(
        self,
        page: PageElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[_Yield], None, None]:
        """Parse a ``stage_<COURT>_<TYPE>.htm`` page in full."""
        court = accumulated_data["court"]
        case_type = accumulated_data["case_type"]
        for docket in CaseListParser()(page):
            yield from self._emit_docket(
                docket,
                court=court,
                case_type=case_type,
                source_url=response.url,
            )

    def _emit_docket(
        self,
        docket,
        *,
        court: str,
        case_type: str,
        source_url: str,
    ) -> Generator[ScraperYield[_Yield], None, None]:
        """Stamp court/case_type/source_url, emit the docket + its PDF.

        ``raw_data`` is a copy, so re-wrap with the merged fields rather
        than mutating the parser's deferred value in place.
        """
        raw = docket.raw_data
        raw["court"] = court
        raw["case_type"] = case_type
        raw["source_url"] = source_url
        yield ParsedData(AzAppDocket.raw(**raw))
        yield self._pdf_archive_request(
            pdf_url=raw["pdf_url"],
            docket_number=raw["docket_number"],
            court=court,
            source="case_list",
            date_last_updated=raw.get("date_last_updated"),
        )

    # =========================================================================
    # Step: parse index pages
    # =========================================================================

    @step(priority=2)
    def parse_lower_court_index(
        self,
        page: PageElement,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[_Yield], None, None]:
        """Emit one ``AzAppLowerCourtCase`` per index row + archive its PDF."""
        court = accumulated_data["court"]
        for rec in LowerCourtIndexParser()(page):
            raw = rec.raw_data
            raw["court"] = court
            yield ParsedData(AzAppLowerCourtCase.raw(**raw))
            yield self._pdf_archive_request(
                pdf_url=raw["our_case_pdf_url"],
                docket_number=raw["our_docket_number"],
                court=court,
                source="lower_court_index",
            )

    @step(priority=2)
    def parse_party_index(
        self,
        page: PageElement,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[_Yield], None, None]:
        """Emit one ``AzAppPartyCase`` per index row + archive its PDF."""
        court = accumulated_data["court"]
        for rec in PartyIndexParser()(page):
            raw = rec.raw_data
            raw["court"] = court
            yield ParsedData(AzAppPartyCase.raw(**raw))
            yield self._pdf_archive_request(
                pdf_url=raw["case_pdf_url"],
                docket_number=raw["docket_number"],
                court=court,
                source="party_index",
            )

    @step(priority=2)
    def parse_attorney_index(
        self,
        page: PageElement,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[_Yield], None, None]:
        """Emit one ``AzAppAttorneyCase`` per index row + archive its PDF."""
        court = accumulated_data["court"]
        for rec in AttorneyIndexParser()(page):
            raw = rec.raw_data
            raw["court"] = court
            yield ParsedData(AzAppAttorneyCase.raw(**raw))
            yield self._pdf_archive_request(
                pdf_url=raw["case_pdf_url"],
                docket_number=raw["docket_number"],
                court=court,
                source="attorney_index",
            )

    # =========================================================================
    # Step: archive a PDF
    # =========================================================================

    @step()
    def handle_pdf_archive(
        self,
        local_filepath: str | None,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[_Yield], None, None]:
        """Emit an ``AzAppDocument`` record for an archived PDF."""
        yield ParsedData(
            data=AzAppDocument(
                court=accumulated_data["court"],
                docket_number=accumulated_data["docket_number"],
                document_url=accumulated_data["document_url"],
                local_path=local_filepath,
                source=accumulated_data.get("source"),
            )
        )
