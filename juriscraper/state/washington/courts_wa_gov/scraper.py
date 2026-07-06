"""Washington Appellate Briefs scraper (www.courts.wa.gov).

Scrapes briefs organized by scheduled hearing date from the public
``/appellate_trial_courts/coaBriefs/`` pages.  Each year page lists every
hearing date for that year plus the cases and briefs scheduled on it.

Supported courts (each has its own ``courtId=`` URL parameter):

======================================== ============================
CourtListener id                         Briefs ``courtId``
======================================== ============================
``wash``                                 ``A08`` — Supreme Court
``washctappdiv1``                        ``A01`` — CoA Division I
``washctappdiv2``                        ``A02`` — CoA Division II
``washctappdiv3``                        ``A03`` — CoA Division III
======================================== ============================

Entry point (§4):

- ``briefs_by_hearing_date(court_ids, date_range)``

Flow:

1. ``briefs_by_hearing_date`` emits one GET per (court, year) overlapping
   ``date_range`` (the site paginates by year), clamped to :data:`MIN_YEAR`.
2. ``parse_briefs_page`` runs :class:`BriefsPageParser` over the year page,
   keeps only cases whose ``hearing_date`` falls inside ``date_range``,
   emits a :class:`WaBriefCase`, and yields one ``archive=True`` request
   per brief PDF.
3. ``handle_brief_download`` emits a :class:`WaDownloadedBrief` carrying
   the local file path.

Notes:

- Div III does not carry briefs before 2008.  The site renders a
  ``"No Court Briefs were found with Scheduled Hearing Dates in YYYY."``
  page for missing years; :class:`BriefsPageParser` detects that and
  returns no cases.
- The briefs pages are server-rendered with mildly malformed HTML
  (``<a name>`` wraps block elements).  ``BriefsPageParser`` recovers
  document order off ``td.mainPage``'s ``inner_html()`` rather than
  trusting XPath sibling relationships (see §9 — no ``._element`` access).
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING, ClassVar
from urllib.parse import urljoin

from jkent.common.decorators import entry, step
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
    BRIEFS_COURTS,
    WaBrief,
    WaBriefCase,
    WaDownloadedBrief,
)
from .parsers import BriefsPageParser
from .parsers._common import collapse_ws

if TYPE_CHECKING:
    from collections.abc import Generator

    from jkent.common.page_element import PageElement
    from jkent.data_types import ScraperYield

# =============================================================================
# URLs and constants
# =============================================================================

BASE_URL = "https://www.courts.wa.gov"
BRIEFS_INDEX_URL = f"{BASE_URL}/appellate_trial_courts/coaBriefs/index.cfm"

# The briefs site's earliest year.  Div III doesn't actually carry briefs
# until 2008, but the site still serves a clean "no results" page for
# 2006/2007 — we let BriefsPageParser detect and skip those.
MIN_YEAR = 2006

# The site serves a short error page to clients without a UA; be a browser.
_BROWSER_HEADERS: dict[str, str] = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15"
    ),
    "Accept": "text/html,application/xhtml+xml",
}


_Yield = WaBriefCase | WaDownloadedBrief


# =============================================================================
# Scraper
# =============================================================================


class WashingtonBriefsScraper(BaseScraper[_Yield]):
    """Scraper for Washington Supreme Court and Court of Appeals briefs
    listed by scheduled hearing date."""

    # === Metadata ===
    court_ids: ClassVar[set[str]] = set(BRIEFS_COURTS.keys())
    court_url: ClassVar[str] = f"{BASE_URL}/appellate_trial_courts/coaBriefs/"
    data_types: ClassVar[set[str]] = {"briefs"}
    status: ClassVar[ScraperStatus] = ScraperStatus.IN_DEVELOPMENT
    version: ClassVar[str] = "2026-06-27"
    last_verified: ClassVar[str] = "2026-04-15"
    requires_auth: ClassVar[bool] = False
    driver_requirements: ClassVar[list] = []
    rate_limits: ClassVar[list[Rate] | None] = [Rate(2, Duration.SECOND)]

    # =========================================================================
    # Entry point
    # =========================================================================

    @entry(WaBriefCase)
    def briefs_by_hearing_date(
        self, court_ids: set[str], date_range: InferrableDateRange
    ) -> Generator[Request, None, None]:
        """Fetch all briefs scheduled for hearings in ``date_range``.

        The site exposes briefs server-side by *scheduled hearing date*
        and paginates by year, one ``courtId`` per court. For each
        requested court and each year overlapping ``date_range`` (clamped
        to :data:`MIN_YEAR`), one GET is dispatched; the year page is
        parsed and only cases whose ``hearing_date`` falls inside the
        requested range are emitted.

        Args:
            court_ids: CourtListener court ids to scrape; a subset of
                ``"wash"``, ``"washctappdiv1"``, ``"washctappdiv2"``,
                ``"washctappdiv3"``.
            date_range: Inclusive hearing-date window.

        Raises:
            ValueError: If a court id is unknown.
        """
        unknown = sorted(c for c in court_ids if c not in BRIEFS_COURTS)
        if unknown:
            raise ValueError(
                f"Unknown court(s) {unknown}; expected a subset of "
                f"{sorted(BRIEFS_COURTS)}"
            )

        start_year = max(date_range.start.year, MIN_YEAR)
        end_year = date_range.end.year
        if end_year < start_year:
            return

        for court in sorted(court_ids):
            briefs_court_id, _display = BRIEFS_COURTS[court]
            for year in range(start_year, end_year + 1):
                url = (
                    f"{BRIEFS_INDEX_URL}"
                    f"?fa=coabriefs.briefsByHearingDate"
                    f"&courtId={briefs_court_id}"
                    f"&year={year}"
                )
                yield Request(
                    request=HTTPRequestParams(
                        method=HttpMethod.GET,
                        url=url,
                        headers=_BROWSER_HEADERS,
                    ),
                    continuation=self.parse_briefs_page,
                    accumulated_data={
                        "court": court,
                        "year": year,
                        "start_date": date_range.start.isoformat(),
                        "end_date": date_range.end.isoformat(),
                        "entry_point": "briefs_by_hearing_date",
                    },
                    deduplication_key=f"briefs_page:{court}:{year}",
                )

    # =========================================================================
    # Year-page parser step
    # =========================================================================

    @step(priority=2)
    def parse_briefs_page(
        self,
        page: PageElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[_Yield], None, None]:
        """Parse one year page into :class:`WaBriefCase`s + archive requests.

        ``BriefsPageParser`` owns the document-order extraction; the step
        applies the hearing-date window, resolves brief URLs against the
        page URL, and fans out the PDF downloads.
        """
        court_id: str = accumulated_data["court"]
        start = date.fromisoformat(accumulated_data["start_date"])
        end = date.fromisoformat(accumulated_data["end_date"])

        for case in BriefsPageParser().walk_groups(page):
            hearing_date = case["hearing_date"]
            if not (start <= hearing_date <= end):
                continue

            briefs = [
                WaBrief(
                    title=b["title"],
                    url=urljoin(response.url, b["url"]),
                )
                for b in case["briefs"]
            ]

            yield ParsedData(
                data=WaBriefCase.raw(
                    court=court_id,
                    hearing_date=hearing_date,
                    docket_number=case["docket"],
                    case_name=case["case_name"],
                    briefs=briefs,
                    source_url=response.url,
                    source_entry_point=accumulated_data.get("entry_point"),
                )
            )

            for b in briefs:
                yield Request(
                    archive=True,
                    expected_type="pdf",
                    request=HTTPRequestParams(
                        method=HttpMethod.GET,
                        url=b.url,
                        headers={
                            **_BROWSER_HEADERS,
                            "Accept": "application/pdf, */*",
                            "Referer": response.url,
                        },
                    ),
                    continuation=self.handle_brief_download,
                    accumulated_data={
                        "court": court_id,
                        "docket_number": case["docket"],
                        "hearing_date": hearing_date.isoformat(),
                        "brief_title": b.title,
                        "brief_url": b.url,
                    },
                    deduplication_key=_brief_dedup_key(
                        court_id, case["docket"], hearing_date, b.url
                    ),
                )

    # =========================================================================
    # Archive download handler
    # =========================================================================

    @step()
    def handle_brief_download(
        self,
        local_filepath: str | None,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[_Yield], None, None]:
        """Emit a :class:`WaDownloadedBrief` for a downloaded PDF."""
        yield ParsedData(
            data=WaDownloadedBrief.raw(
                court=accumulated_data["court"],
                docket_number=accumulated_data["docket_number"],
                hearing_date=date.fromisoformat(
                    accumulated_data["hearing_date"]
                ),
                brief_title=accumulated_data["brief_title"],
                brief_url=accumulated_data["brief_url"],
                local_path=local_filepath,
            )
        )


# =============================================================================
# Helpers
# =============================================================================


def _brief_dedup_key(
    court: str, docket: str, hearing_date: date, url: str
) -> str:
    """Build a colon-free, filename-safe dedup key for a brief PDF.

    Brief filenames on the site are not unique across cases, so the key
    folds in the court, docket, hearing date, and the PDF's basename.
    """
    basename = url.rsplit("/", 1)[-1].split("?", 1)[0] or "brief.pdf"
    safe_docket = collapse_ws(docket).replace(" ", "").replace(",", "")
    return f"{court}-{safe_docket}-{hearing_date.isoformat()}-{basename}"
