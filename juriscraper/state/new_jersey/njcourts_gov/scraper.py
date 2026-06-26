"""New Jersey Judiciary scraper (njcourts.gov).

Scrapes appellate dockets from three public listing pages on
``https://www.njcourts.gov``:

- ``/courts/supreme/appeals`` — pending and decided Supreme Court (SCOTNJ,
  ``nj``) appeals (mixed). Filterable by event date via ``filter_by`` /
  ``start`` / ``end``; this scraper pins ``filter_by=Posted`` so the
  ``DateRange`` has a stable, repeatable meaning across runs.
- ``/courts/appellate/briefs-from-argued-cases`` — Appellate Division
  (SCAD, ``njsuperctappdiv``) cases that have been argued, filterable by
  argument date (``field_argued_dates_value``).
- ``/courts/appellate/argument-schedule`` — upcoming SCAD oral arguments.
  Snapshot only (no historical access, no date filter, no pagination).

All endpoints serve full server-rendered HTML with no JS challenge or
CSRF gate, so the scraper runs over plain HTTP (``driver_requirements =
[]``). Brief / order / opinion PDFs and SCOTNJ oral-argument MP4/MP3 are
downloaded with ``archive=True`` and emitted as ``NJDocument``.

Per-page HTML extraction lives in the ``parsers`` package
(``ListingParser`` for the two row-based listings, ``ArgumentScheduleParser``
for the snapshot); the steps keep navigation concerns (the download
fan-out and the pagination follow).

The ``missing_entries_reason`` field on ``NJDocket`` is populated when the
page indicates that documents have been withheld from public view — either
``RECORD IMPOUNDED`` (SCAD) or ``Briefs are sealed`` (SCOTNJ).

See ``CC_NOTES.md`` for the full investigation.

Entry points (§4):
    - dockets_by_posted_date(court_ids, date_range)   — SCOTNJ, by Posted date.
    - dockets_by_argument_date(court_ids, date_range) — SCAD argued cases.
    - dockets_by_bulk(court_ids)                      — SCAD upcoming-OA snapshot.

Flow:
    dockets_by_posted_date   → parse_scotnj_listing ──┐
    dockets_by_argument_date → parse_scad_argued_listing ─┼→ (per doc)
    dockets_by_bulk          → parse_argument_schedule ───┘  handle_document_download
"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar
from urllib.parse import urlencode

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
)
from pyrate_limiter import Duration, Rate

from .models import (
    BASE_URL,
    COURT_IDS,
    SCAD_ARGUED_LISTING_URL,
    SCAD_ARGUMENT_SCHEDULE_URL,
    SCOTNJ_LISTING_URL,
    NJDocket,
    NJDocument,
)
from .parsers import ArgumentScheduleParser, ListingParser, next_page_url

if TYPE_CHECKING:
    from collections.abc import Generator

    from jkent.common.page_element import PageElement
    from jkent.data_types import ScraperYield

SCOTNJ_COURT_ID = "nj"
SCAD_COURT_ID = "njsuperctappdiv"


def _media_type(url: str) -> str:
    """Map a download URL to its ``expected_type`` (``pdf`` / ``mp4`` /
    ``mp3``) from the file extension."""
    lower = url.lower()
    if lower.endswith(".mp4"):
        return "mp4"
    if lower.endswith(".mp3"):
        return "mp3"
    return "pdf"


def _accept_header(kind: str) -> str:
    """HTTP ``Accept`` header for a downloaded artefact kind."""
    if kind == "pdf":
        return "application/pdf"
    if kind == "mp3":
        return "audio/mp3"
    return f"video/{kind}"


class NJCourtsScraper(BaseScraper[NJDocket | NJDocument]):
    """Scraper for the New Jersey Judiciary's public appellate listings.

    Three entry points cover the three source pages. SCOTNJ filters by the
    ``Posted`` event date so that the ``DateRange`` parameter has a clear,
    stable meaning across runs; SCAD-argued filters on the only date
    column the page exposes (the argument date); and the SCAD
    argument-schedule snapshot has no date filter at all, so it runs as a
    bulk (dateless) entry point.
    """

    # === Metadata (§3) ===
    court_ids: ClassVar[set[str]] = set(COURT_IDS.keys())
    court_url: ClassVar[str] = BASE_URL
    data_types: ClassVar[set[str]] = {"dockets"}
    status: ClassVar[ScraperStatus] = ScraperStatus.IN_DEVELOPMENT
    version: ClassVar[str] = "2026-06-27"
    last_verified: ClassVar[str] = "2026-05-04"
    requires_auth: ClassVar[bool] = False
    driver_requirements: ClassVar[list[DriverRequirement]] = []
    rate_limits: ClassVar[list[Rate] | None] = [Rate(1, Duration.SECOND)]

    # =========================================================================
    # Entry points (§4)
    # =========================================================================

    @entry(NJDocket)
    def dockets_by_posted_date(
        self, court_ids: set[str], date_range: DateRange
    ) -> Generator[Request, None, None]:
        """SCOTNJ dockets posted in ``date_range`` (cert/leave granted etc.).

        Walks ``/courts/supreme/appeals`` filtered server-side on the
        ``Posted`` event date, following the Drupal pager to the end.
        """
        url = (
            SCOTNJ_LISTING_URL
            + "?"
            + urlencode(
                {
                    "filter_by": "Posted",
                    "start": date_range.start.isoformat(),
                    "end": date_range.end.isoformat(),
                }
            )
        )
        yield Request(
            request=HTTPRequestParams(method=HttpMethod.GET, url=url),
            continuation=self.parse_scotnj_listing,
            accumulated_data={
                "court": SCOTNJ_COURT_ID,
                "source_url": url,
                "entry_point": "dockets_by_posted_date",
            },
            deduplication_key=(
                f"scotnj_listing:{date_range.start}:{date_range.end}"
            ),
        )

    @entry(NJDocket)
    def dockets_by_argument_date(
        self, court_ids: set[str], date_range: DateRange
    ) -> Generator[Request, None, None]:
        """SCAD cases argued during ``date_range``.

        Walks ``/courts/appellate/briefs-from-argued-cases`` filtered
        server-side on the argument date.
        """
        url = (
            SCAD_ARGUED_LISTING_URL
            + "?"
            + urlencode(
                {
                    "field_argued_dates_value[min]": (
                        date_range.start.isoformat()
                    ),
                    "field_argued_dates_value[max]": (
                        date_range.end.isoformat()
                    ),
                }
            )
        )
        yield Request(
            request=HTTPRequestParams(method=HttpMethod.GET, url=url),
            continuation=self.parse_scad_argued_listing,
            accumulated_data={
                "court": SCAD_COURT_ID,
                "source_url": url,
                "entry_point": "dockets_by_argument_date",
            },
            deduplication_key=(
                f"scad_argued_listing:{date_range.start}:{date_range.end}"
            ),
        )

    @entry(NJDocket)
    def dockets_by_bulk(
        self, court_ids: set[str]
    ) -> Generator[Request, None, None]:
        """Upcoming SCAD oral arguments (snapshot, no date filter).

        The argument-schedule page only ever exposes the next ~2 weeks of
        sittings as a single non-paginated snapshot, so the addressing
        mode is bulk.
        """
        yield Request(
            request=HTTPRequestParams(
                method=HttpMethod.GET, url=SCAD_ARGUMENT_SCHEDULE_URL
            ),
            continuation=self.parse_argument_schedule,
            accumulated_data={
                "court": SCAD_COURT_ID,
                "source_url": SCAD_ARGUMENT_SCHEDULE_URL,
                "entry_point": "dockets_by_bulk",
            },
            deduplication_key="argument_schedule:snapshot",
        )

    # =========================================================================
    # Steps — paginated listings (SCOTNJ + SCAD-argued)
    # =========================================================================

    @step(priority=3)
    def parse_scotnj_listing(
        self,
        page: PageElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[NJDocket | NJDocument], None, None]:
        """Parse one page of the SCOTNJ ``/courts/supreme/appeals`` listing."""
        yield from self._parse_listing_page(
            page=page,
            response=response,
            accumulated_data=accumulated_data,
            continuation=self.parse_scotnj_listing,
            include_question=True,
        )

    @step(priority=3)
    def parse_scad_argued_listing(
        self,
        page: PageElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[NJDocket | NJDocument], None, None]:
        """Parse one page of the SCAD ``briefs-from-argued-cases`` listing."""
        yield from self._parse_listing_page(
            page=page,
            response=response,
            accumulated_data=accumulated_data,
            continuation=self.parse_scad_argued_listing,
            include_question=False,
        )

    def _parse_listing_page(
        self,
        *,
        page: PageElement,
        response: Response,
        accumulated_data: dict,
        continuation,
        include_question: bool,
    ) -> Generator[ScraperYield[NJDocket | NJDocument], None, None]:
        court: str = accumulated_data["court"]
        dockets = ListingParser(court, include_question=include_question)(page)
        for deferred in dockets:
            yield from self._emit_docket(deferred, accumulated_data)

        next_url = next_page_url(page, response.url or "")
        if next_url:
            yield Request(
                request=HTTPRequestParams(method=HttpMethod.GET, url=next_url),
                continuation=continuation,
                accumulated_data={
                    **accumulated_data,
                    "source_url": next_url,
                },
                deduplication_key=f"listing_page:{next_url}",
            )

    # =========================================================================
    # Step — argument schedule snapshot (SCAD pending OAs)
    # =========================================================================

    @step(priority=2)
    def parse_argument_schedule(
        self,
        page: PageElement,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[NJDocket | NJDocument], None, None]:
        """Parse the SCAD argument-schedule single-page snapshot."""
        court: str = accumulated_data["court"]
        dockets = ArgumentScheduleParser(court)(page)
        for deferred in dockets:
            yield from self._emit_docket(deferred, accumulated_data)

    # =========================================================================
    # Shared: emit a parsed docket + fan out its document downloads
    # =========================================================================

    def _emit_docket(
        self, deferred, accumulated_data: dict
    ) -> Generator[ScraperYield[NJDocket | NJDocument], None, None]:
        """Stamp provenance onto a parsed docket, emit it, and fan out an
        ``archive=True`` request per attached document.

        ``raw_data`` is a copy, so the provenance fields are merged into
        the deferred docket before emit; the document fan-out reads the
        already-built ``NJDocument`` records the parser attached.
        """
        raw = deferred.raw_data
        raw["source_url"] = accumulated_data.get("source_url")
        raw["source_entry_point"] = accumulated_data.get("entry_point")
        docket_number = raw["docket_number"]
        court = raw["court"]
        documents: list[NJDocument] = raw.get("documents", [])
        yield ParsedData(NJDocket.raw(**raw))

        for doc in documents:
            kind = _media_type(doc.document_url)
            yield Request(
                archive=True,
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url=doc.document_url,
                    headers={"Accept": _accept_header(kind)},
                ),
                continuation=self.handle_document_download,
                expected_type=kind,
                accumulated_data={
                    "docket_number": docket_number,
                    "court": court,
                    "description": doc.description,
                    "document_url": doc.document_url,
                },
                deduplication_key=(
                    f"{docket_number}-{doc.document_url.rsplit('/', 1)[-1]}"
                ),
            )

    # =========================================================================
    # Step — document archival (priority 0–1 reserved for downloads, §5)
    # =========================================================================

    @step()
    def handle_document_download(
        self,
        accumulated_data: dict,
        local_filepath: str | None = None,
    ) -> Generator[ScraperYield[NJDocument], None, None]:
        """Emit an ``NJDocument`` for an archived file."""
        yield ParsedData(
            NJDocument.raw(
                docket_number=accumulated_data["docket_number"],
                court=accumulated_data["court"],
                document_url=accumulated_data["document_url"],
                description=accumulated_data.get("description"),
                filepath_local=local_filepath,
            )
        )
