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

Entry point:

- ``@entry(WaBriefCase) get_briefs(date_range, court)``

Flow:

1. ``get_briefs`` emits one GET per year in ``date_range`` (clamped to
   2006, the earliest year the site carries).
2. ``parse_briefs_page`` walks the year page in document order, builds a
   :class:`WaBriefCase` per (hearing_date, docket_number, case_name)
   whose ``hearing_date`` falls inside ``date_range``, and yields one
   ``archive=True`` request per brief PDF.
3. ``handle_brief_download`` emits a :class:`WaDownloadedBrief` carrying
   the local file path.

Notes:

- Div III does not carry briefs before 2008.  The site renders a
  ``"No Court Briefs were found with Scheduled Hearing Dates in YYYY."``
  page for missing years; :meth:`parse_briefs_page` detects that and
  exits cleanly with no yields.
- The briefs pages are generated server-side and the HTML is mildly
  malformed (``<a name>`` tags wrap block elements).  We rely on lxml's
  document-order iteration to associate hearing dates, cases, and briefs
  rather than trusting XPath sibling relationships.
"""

from __future__ import annotations

import re
from datetime import date
from typing import TYPE_CHECKING, ClassVar
from urllib.parse import urljoin

from jkent.common.decorators import entry, step
from jkent.common.page_element import PageElement
from jkent.common.param_models import DateRange
from jkent.data_types import (
    ArchiveResponse,
    BaseScraper,
    HttpMethod,
    HTTPRequestParams,
    ParsedData,
    Request,
    Response,
    ScraperStatus,
)
from pyrate_limiter import Duration, Rate

from .models import (
    BRIEFS_COURTS,
    WaBrief,
    WaBriefCase,
    WaDownloadedBrief,
)

if TYPE_CHECKING:
    from collections.abc import Generator

    from jkent.data_types import ScraperYield

# =============================================================================
# URLs and constants
# =============================================================================

BASE_URL = "https://www.courts.wa.gov"
BRIEFS_INDEX_URL = f"{BASE_URL}/appellate_trial_courts/coaBriefs/index.cfm"

# The briefs site's earliest year.  Div III doesn't actually carry briefs
# until 2008, but the site still serves a clean "no results" page for
# 2006/2007 — we let parse_briefs_page detect and skip those.
MIN_YEAR = 2006

# Anchor name format for a hearing-date section, e.g. "a20260115".
_HEARING_ANCHOR_RE = re.compile(r"^a(\d{4})(\d{2})(\d{2})$")

# Case LI text format: "<docket> - <case name>" where docket is e.g.
# "104,170-5" (Supreme Court) or "84401-6" (Court of Appeals).
_CASE_TEXT_RE = re.compile(r"^\s*([\d,]+-\d+)\s*-\s*(.+?)\s*$", re.DOTALL)

# Empty-year signal rendered by the site (Div III early years, etc.).
_EMPTY_YEAR_TEXT = "No Court Briefs were found with Scheduled Hearing Dates"

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

    court_ids: ClassVar[set[str]] = set(BRIEFS_COURTS.keys())
    court_url: ClassVar[str] = f"{BASE_URL}/appellate_trial_courts/coaBriefs/"
    data_types: ClassVar[set[str]] = {"briefs"}
    status: ClassVar[ScraperStatus] = ScraperStatus.IN_DEVELOPMENT
    version: ClassVar[str] = "2026-04-15"
    requires_auth: ClassVar[bool] = False

    rate_limits: ClassVar[list[Rate] | None] = [Rate(2, Duration.SECOND)]

    # =========================================================================
    # Entry point
    # =========================================================================

    @entry(WaBriefCase)
    def get_briefs(
        self, date_range: DateRange, court: str
    ) -> Generator[Request, None, None]:
        """Fetch all briefs scheduled for hearings in ``date_range``.

        Dispatches one GET per year that overlaps the range (the site
        paginates by year), clamping to :data:`MIN_YEAR` on the low end.
        Each year page is parsed to emit :class:`WaBriefCase`s whose
        ``hearing_date`` actually falls inside the requested range.

        Args:
            date_range: Inclusive hearing-date window.
            court: CourtListener court id.  One of
                ``"wash"``, ``"washctappdiv1"``, ``"washctappdiv2"``,
                ``"washctappdiv3"``.

        Raises:
            ValueError: If ``court`` is unknown.
        """
        if court not in BRIEFS_COURTS:
            raise ValueError(
                f"Unknown court {court!r}; expected one of "
                f"{sorted(BRIEFS_COURTS)}"
            )

        briefs_court_id, _display = BRIEFS_COURTS[court]

        start_year = max(date_range.start.year, MIN_YEAR)
        end_year = date_range.end.year
        if end_year < start_year:
            return

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
                    "court_id": court,
                    "year": year,
                    "start_date": date_range.start.isoformat(),
                    "end_date": date_range.end.isoformat(),
                },
            )

    # =========================================================================
    # Year-page parser
    # =========================================================================

    @step()
    def parse_briefs_page(
        self,
        page: PageElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[_Yield], None, None]:
        """Parse one year page into :class:`WaBriefCase`s + archive requests.

        Walks the ``td.mainPage`` container in lxml document order,
        tracking the current hearing-date anchor and the current case LI
        and attaching brief PDFs to that case as they appear.
        """
        court_id: str = accumulated_data["court_id"]
        start = date.fromisoformat(accumulated_data["start_date"])
        end = date.fromisoformat(accumulated_data["end_date"])

        # Empty-year guard — Div III before 2008 + any future gaps.
        empty_markers = page.query_xpath(
            f"//*[contains(text(), {_EMPTY_YEAR_TEXT!r})]",
            "no-briefs-found marker",
            min_count=0,
            max_count=1,
        )
        if empty_markers:
            return

        # Drop to the raw lxml tree inside td.mainPage so we can iterate
        # the subtree in document order — the server-rendered HTML wraps
        # <a name> around block elements, so sibling XPath lies.
        main_pes = page.query_xpath(
            "//td[@class='mainPage']",
            "main page container",
            min_count=0,
            max_count=1,
        )
        if not main_pes:
            return
        main_lxml = main_pes[0]._element._element  # type: ignore[attr-defined]

        for case in _walk_year_page(main_lxml):
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
                data=WaBriefCase(
                    court_id=court_id,
                    hearing_date=hearing_date,
                    docket_number=case["docket"],
                    case_name=case["case_name"],
                    briefs=briefs,
                    source_url=response.url,
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
                        "court_id": court_id,
                        "docket_number": case["docket"],
                        "hearing_date": hearing_date.isoformat(),
                        "brief_title": b.title,
                        "brief_url": b.url,
                    },
                )

    # =========================================================================
    # Archive download handler
    # =========================================================================

    @step()
    def handle_brief_download(
        self,
        response: ArchiveResponse,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[_Yield], None, None]:
        """Emit a :class:`WaDownloadedBrief` for a downloaded PDF."""
        yield ParsedData(
            data=WaDownloadedBrief(
                court_id=accumulated_data["court_id"],
                docket_number=accumulated_data["docket_number"],
                hearing_date=date.fromisoformat(
                    accumulated_data["hearing_date"]
                ),
                brief_title=accumulated_data["brief_title"],
                brief_url=accumulated_data["brief_url"],
                local_path=response.file_url or None,
            )
        )


# =============================================================================
# Year-page traversal
# =============================================================================


def _walk_year_page(main_lxml) -> list[dict]:  # noqa: ANN001 — lxml element
    """Walk a year page's ``<td class="mainPage">`` subtree and group
    briefs by ``(hearing_date, docket_number, case_name)``.

    Returns a list of dicts with keys ``hearing_date`` (``date``),
    ``docket`` (``str``), ``case_name`` (``str``), and ``briefs``
    (``list[{"title": str, "url": str}]``).
    """
    cases: list[dict] = []
    cur_hearing_date: date | None = None
    cur_case: dict | None = None

    for el in main_lxml.iter():
        tag = el.tag

        # Hearing-date anchor
        if tag == "a":
            name = el.get("name") or ""
            m = _HEARING_ANCHOR_RE.match(name)
            if m:
                cur_hearing_date = date(
                    int(m.group(1)), int(m.group(2)), int(m.group(3))
                )
                cur_case = None
                continue

        # LI: either case header or brief entry
        if tag == "li":
            brief = _brief_from_li(el)
            if brief is not None:
                if cur_case is not None:
                    cur_case["briefs"].append(brief)
                continue

            parsed = _case_from_li(el)
            if parsed is not None and cur_hearing_date is not None:
                docket, case_name = parsed
                cur_case = {
                    "hearing_date": cur_hearing_date,
                    "docket": docket,
                    "case_name": case_name,
                    "briefs": [],
                }
                cases.append(cur_case)

    return cases


def _case_from_li(li) -> tuple[str, str] | None:  # noqa: ANN001 — lxml element
    """Return ``(docket_number, case_name)`` if this LI is a case header.

    A case header LI has no descendant ``<a>`` tags and its text matches
    ``"<docket> - <case name>"``.
    """
    if li.findall(".//a"):
        return None
    text = (li.text_content() or "").strip()
    text = re.sub(r"\s+", " ", text)
    m = _CASE_TEXT_RE.match(text)
    if not m:
        return None
    return m.group(1).strip(), m.group(2).strip()


def _brief_from_li(li) -> dict | None:  # noqa: ANN001 — lxml element
    """Return ``{"title", "url"}`` if this LI contains a brief PDF link."""
    for a in li.findall("./a"):
        href = a.get("href") or ""
        if ".pdf" in href.lower():
            title = re.sub(r"\s+", " ", (a.text_content() or "").strip())
            return {"title": title, "url": href}
    return None


Site = WashingtonBriefsScraper
