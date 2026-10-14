"""California Supreme Court briefs scraper (supreme.courts.ca.gov).

The court publishes, at ``/case-information/briefs-argued-cases``, the briefs
filed in every case it has heard oral argument in since 2010 -- "When new
cases are set for oral argument, briefs are posted here the same day." The
listing is organized by *oral argument session*: one index page links a page
per session, and each session page lists the cases argued then, with a PDF
link for every brief, letter, motion, and notice filed in the case.

Plain server-rendered HTML on a Drupal site: no JavaScript, no bot gate, no
search form. ``driver_requirements = []``.

Entry point (§4):

- ``briefs_by_argument_date(court_ids, date_range)``

Flow::

    1. briefs_by_argument_date  -> GET the briefs index
    2. parse_briefs_index (3)   -> read every session link's date span,
                                   emit CalSupremeArgumentSession for the
                                   sessions inside the window, GET each
    3. parse_session_page (2)   -> emit one CalSupremeBriefCase per case,
                                   fan out an archive request per brief PDF
    4. handle_brief_download(1) -> emit CalSupremeDownloadedBrief

The date window is applied by the scraper, not the server: the site has no
date search at all, and the only thing that makes the addressing possible is
that each index link states its session's dates in its text. Because that
filtering happens in-scraper, the window rides down the chain in
``accumulated_data`` rather than being re-read from params (JKENT_REFERENCE
§2). The entry is still named for the date it addresses -- the same shape as
Washington's ``briefs_by_hearing_date`` -- because the index is genuinely a
date index, only one the client reads.

``court_ids`` likewise filters output rather than selecting pages: the index
is not per-court. It exists because three case blocks on the September 7-8
2010 session page carry Third District numbers (briefs the court incorporated
into S183411 by order), so a run asking only for ``cal`` should not collect
them.

Data linking:
- ``CalSupremeBriefCase`` and ``CalSupremeDownloadedBrief`` share
  ``(court, docket_number, brief_url)``.
- ``docket_number`` + ``court`` also join to the sibling
  ``appellatecases_courtinfo_ca_gov`` scraper, which has the docket for the
  same case but none of the brief files.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import TYPE_CHECKING, ClassVar

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
)
from pyrate_limiter import Duration, Rate

from juriscraper.state.common.params import InferrableDateRange

from .models import (
    BRIEFS_INDEX_URL,
    COURT_IDS,
    MIN_YEAR,
    CalSupremeArgumentSession,
    CalSupremeBriefCase,
    CalSupremeDownloadedBrief,
)
from .parsers import BriefsIndexParser, SessionPageParser

if TYPE_CHECKING:
    from collections.abc import Generator

    from jkent.common.page_element import PageElement
    from jkent.data_types import ScraperYield

logger = logging.getLogger(__name__)

_Yield = (
    CalSupremeArgumentSession | CalSupremeBriefCase | CalSupremeDownloadedBrief
)


class CalSupremeBriefsScraper(BaseScraper[_Yield]):
    """Scraper for California Supreme Court briefs, by oral argument session."""

    # === Metadata ===
    court_ids: ClassVar[set[str]] = set(COURT_IDS.keys())
    court_url: ClassVar[str] = BRIEFS_INDEX_URL
    data_types: ClassVar[set[str]] = {"briefs"}
    status: ClassVar[ScraperStatus] = ScraperStatus.IN_DEVELOPMENT
    version: ClassVar[str] = "2026-09-10"
    last_verified: ClassVar[str] = "2026-09-10"
    requires_auth: ClassVar[bool] = False
    driver_requirements: ClassVar[list[DriverRequirement]] = []
    rate_limits: ClassVar[list[Rate] | None] = [Rate(2, Duration.SECOND)]

    # =========================================================================
    # Entry point
    # =========================================================================

    @entry(CalSupremeBriefCase)
    def briefs_by_argument_date(
        self, court_ids: set[str], date_range: InferrableDateRange
    ) -> Generator[Request, None, None]:
        """Fetch the briefs for every case argued in ``date_range``.

        One request: the briefs index, which lists every session held since
        2010 with its dates in the link text. ``parse_briefs_index`` picks the
        sessions whose span overlaps the window and fetches those pages.

        A session that straddles the edge of the window is fetched whole --
        the court lists its cases as one group and never says which day
        inside a multi-day session a given case was called, so there is no
        honest way to drop half of it.

        Args:
            court_ids: CourtListener court ids to keep; a subset of
                ``{"cal", "calctapp_3rd"}``. Filters the emitted cases; the
                index itself is not per-court.
            date_range: Inclusive oral-argument-date window.

        Raises:
            ValueError: If a court id is unknown.
        """
        unknown = sorted(
            court for court in court_ids if court not in COURT_IDS
        )
        if unknown:
            raise ValueError(
                f"Unknown court(s) {unknown}; expected a subset of "
                f"{sorted(COURT_IDS)}"
            )

        if date_range.end.year < MIN_YEAR:
            logger.info(
                "window ends %s, before the %d start of the briefs listing; "
                "nothing to fetch",
                date_range.end,
                MIN_YEAR,
            )
            return

        yield Request(
            request=HTTPRequestParams(
                method=HttpMethod.GET, url=BRIEFS_INDEX_URL
            ),
            step=self.parse_briefs_index,
            accumulated_data={
                "target_courts": sorted(court_ids),
                "start_date": date_range.start.isoformat(),
                "end_date": date_range.end.isoformat(),
                "entry_point": "briefs_by_argument_date",
            },
            deduplication_key=(
                f"briefs_index:{date_range.start}:{date_range.end}"
            ),
        )

    # =========================================================================
    # Index step
    # =========================================================================

    @step(priority=3)
    def parse_briefs_index(
        self, page: PageElement, accumulated_data: dict
    ) -> Generator[ScraperYield[_Yield], None, None]:
        """Select the sessions overlapping the window and fetch each one.

        Emits the ``CalSupremeArgumentSession`` for each session it fetches,
        so a run records the court's argument calendar as well as its briefs.
        """
        start = date.fromisoformat(accumulated_data["start_date"])
        end = date.fromisoformat(accumulated_data["end_date"])

        for session in BriefsIndexParser()(page):
            fields = session.raw_data
            if fields["date_session_end"] < start:
                continue
            if fields["date_session_start"] > end:
                continue

            yield ParsedData(data=session)
            yield Request(
                request=HTTPRequestParams(
                    method=HttpMethod.GET, url=fields["source_url"]
                ),
                step=self.parse_session_page,
                accumulated_data={
                    **accumulated_data,
                    "session_title": fields["session_title"],
                },
                deduplication_key=(
                    f"session_page:{_session_slug(fields['source_url'])}"
                ),
            )

    # =========================================================================
    # Session-page step
    # =========================================================================

    @step(priority=2)
    def parse_session_page(
        self,
        page: PageElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[_Yield], None, None]:
        """Emit one case per heading and one archive request per brief PDF."""
        target_courts: list[str] = accumulated_data["target_courts"]

        for parsed_case in SessionPageParser()(page):
            fields = parsed_case.raw_data
            if fields["court"] not in target_courts:
                continue

            # ``raw_data`` hands back a copy, so the page's provenance is
            # added by rebuilding the deferred record rather than by mutating
            # what the parser returned.
            yield ParsedData(
                data=CalSupremeBriefCase.raw(
                    **fields,
                    source_url=response.url,
                    source_entry_point=accumulated_data.get("entry_point"),
                )
            )

            for brief in fields["briefs"]:
                if not brief["url"]:
                    continue
                yield Request(
                    archive=True,
                    expected_type="pdf",
                    request=HTTPRequestParams(
                        method=HttpMethod.GET,
                        url=brief["url"],
                        headers={
                            "Accept": "application/pdf,*/*",
                            "Referer": response.url,
                        },
                    ),
                    step=self.handle_brief_download,
                    accumulated_data={
                        "court": fields["court"],
                        "docket_number": fields["docket_number"],
                        "document_number": brief["document_number"],
                        "description": brief["description"],
                        "date_filed": (
                            brief["date_filed"].isoformat()
                            if brief["date_filed"]
                            else None
                        ),
                        "brief_url": brief["url"],
                    },
                    deduplication_key=(
                        f"{fields['docket_number']}-{brief['filename']}"
                    ),
                )

    # =========================================================================
    # Archive download handler
    # =========================================================================

    @step()
    def handle_brief_download(
        self, local_filepath: str | None, accumulated_data: dict
    ) -> Generator[ScraperYield[_Yield], None, None]:
        """Emit a :class:`CalSupremeDownloadedBrief` for a downloaded PDF."""
        filed = accumulated_data["date_filed"]
        yield ParsedData(
            data=CalSupremeDownloadedBrief.raw(
                court=accumulated_data["court"],
                docket_number=accumulated_data["docket_number"],
                document_number=accumulated_data["document_number"],
                description=accumulated_data["description"],
                date_filed=date.fromisoformat(filed) if filed else None,
                brief_url=accumulated_data["brief_url"],
                local_path=local_filepath,
            )
        )


# =============================================================================
# Helpers
# =============================================================================


def _session_slug(url: str) -> str:
    """The session's own path segment, which names it uniquely.

    ``.../briefs-argued-cases/may-6-and-7-2025-oral-argument-cases`` ->
    ``may-6-and-7-2025-oral-argument-cases``. Used as the session page's dedup
    key so the same session dedups across runs whatever window asked for it.
    """
    return url.rstrip("/").rsplit("/", 1)[-1]
