"""North Carolina Appellate Courts docket scraper.

Scrapes dockets for the Supreme Court of North Carolina (``nc``) and
the North Carolina Court of Appeals (``ncctapp``). Plain-HTTP, server-
rendered HTML on both endpoints (no JS / captcha / cookies); HTML
extraction lives in the ``parsers`` package (§9), the steps keep only
navigation (the search-result link follow, per-case fan-out, pagination,
archive downloads).

Entry points (§4):
    - docket_by_number(court_id, docket_number) — single-case lookup by
      visible docket number (e.g. ``26-310``, ``P26-334``, ``15P26``).
    - dockets_by_filing_date(court_ids, date_range) — surface every case
      with at least one e-filing in the window.

Per-case flow::

    docket_by_number
        │
        ▼
    parse_docket_search_result       (dockets.php?...&submit=Search)
        │  ── follows the link
        ▼
    parse_docket_sheet               (dockets.php?...&pdf=1) ── yields NCAppealsDocket
        │  ── fans out per case
        ▼
    parse_case_filings               (search-results.php?sDocketSearch=…)
        ├─ archive Request → handle_document_download → NCAppealsDocument
        └─ (sealed) ParsedData(NCAppealsDocument)

    dockets_by_filing_date
        │
        ▼
    parse_filings_listing            (search-results.php?start_date=…)
        │  ── one Request per unique case + pagination Request(s)
        ▼
    parse_docket_sheet               (as above)

The "PDF" docket sheet at ``dockets.php?…&pdf=1`` is actually styled
HTML, despite the parameter name — see ``CC_NOTES.md``.

Soft-404: a docket-number miss returns HTTP 200 but signals "0 case" in
the result page body. We detect that in ``actually_successful`` (§10) so
the framework treats the miss as a failure rather than a valid empty
page.
"""

from __future__ import annotations

import re
from datetime import date, timedelta
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
    XPath,
)
from pyrate_limiter import Duration, Rate

from juriscraper.state.common.params import InferrableDateRange

from .models import (
    COURT_COA,
    COURT_SC,
    COURT_URL,
    DOCKETS_BASE,
    SEARCH_RESULTS_URL,
    SITE_COURT_ID,
    NCAppealsDocket,
    NCAppealsDocument,
)
from .parsers import (
    CaseFilingsParser,
    DocketListingParser,
    DocketSheetParser,
    pagination_offsets,
)
from .parsers._common import current_istart, normalize_url

if TYPE_CHECKING:
    from collections.abc import Generator

    from jkent.common.page_element import PageElement
    from jkent.data_types import ScraperYield


# ─── Regexes for routing visible docket numbers to the right court ────
# COA appeals of right and petitions: ``26-310``, ``P26-334``,
# ``25-1111``; ``258A22-2`` is *not* matched here (that's SC).
_COA_DOCKET_RE = re.compile(r"^P?\d{1,2}-\d+(?:-\d+)?$")
# SC: digits, letters, two-digit year, optional ``-N`` suffix
# (e.g. ``15P26``, ``1A26``, ``1PA26``, ``258A22-2``).
_SC_DOCKET_RE = re.compile(r"^\d+[A-Z]+\d{2}(?:-\d+)?$")


def _iter_date_windows(
    start: date, end: date, days: int
) -> Generator[tuple[date, date], None, None]:
    """Yield inclusive ``(start, end)`` sub-windows of at most ``days`` each.

    ``search-results.php`` paginates 50 cases at a time and its offset-based
    paging degrades into 504 gateway timeouts once the offset climbs past a
    few hundred rows (see ``parse_filings_listing``). Splitting a wide
    ``date_range`` into narrow windows keeps every search within its first
    few (reliable) pages. Windows tile the range with no gap or overlap.
    """
    step = timedelta(days=days)
    cursor = start
    while cursor <= end:
        window_end = min(cursor + step - timedelta(days=1), end)
        yield cursor, window_end
        cursor = window_end + timedelta(days=1)


def _route_court(docket_number: str) -> str | None:
    """Best-effort CL court id guess from a visible docket number.

    Used only as a fallback when ``court_id`` isn't supplied; returns
    ``None`` if the format isn't recognised.
    """
    text = docket_number.strip().upper()
    if _COA_DOCKET_RE.match(text):
        return COURT_COA
    if _SC_DOCKET_RE.match(text):
        return COURT_SC
    return None


class NorthCarolinaAppellateScraper(
    BaseScraper[NCAppealsDocket | NCAppealsDocument]
):
    """Scraper for NC Supreme Court and Court of Appeals dockets.

    Both courts share the same docket-sheet layout, served from
    ``appellate.nccourts.org/dockets.php?…&pdf=1`` (which is HTML, not
    PDF — see CC_NOTES.md).
    """

    # === Metadata (§3) ===
    court_ids: ClassVar[set[str]] = {COURT_SC, COURT_COA}
    court_url: ClassVar[str] = COURT_URL
    data_types: ClassVar[set[str]] = {"dockets"}
    status: ClassVar[ScraperStatus] = ScraperStatus.IN_DEVELOPMENT
    version: ClassVar[str] = "2026-06-27"
    last_verified: ClassVar[str] = "2026-05-04"
    requires_auth: ClassVar[bool] = False
    driver_requirements: ClassVar[list[DriverRequirement]] = []
    rate_limits: ClassVar[list[Rate] | None] = [Rate(1, Duration.SECOND)]

    # ``search-results.php`` 504s on deep offset pagination (offsets ≥ ~200
    # were unreliable in testing; offsets ≤ 150 never failed). A date-range
    # entry is split into windows of this many days so each search stays in
    # its first few pages. At ~40 filings/day this keeps the offset near 100.
    filing_window_days: ClassVar[int] = 3

    # =========================================================================
    # Entry points (§4)
    # =========================================================================

    @entry(NCAppealsDocket)
    def docket_by_number(
        self, court_id: str, docket_number: str
    ) -> Generator[Request, None, None]:
        """Look up one case by its visible docket number.

        The court is selected from ``court_id`` (``nc`` → ``court=1``,
        ``ncctapp`` → ``court=2``); when an unknown id is supplied we
        fall back to routing by the docket-number format.
        """
        court = court_id if court_id in SITE_COURT_ID else None
        if court is None:
            court = _route_court(docket_number) or COURT_COA
        site_court = SITE_COURT_ID[court]
        yield Request(
            request=HTTPRequestParams(
                method=HttpMethod.GET,
                url=DOCKETS_BASE,
                params={
                    "court": str(site_court),
                    "docket": docket_number,
                    "title": "",
                    "submit": "Search",
                },
            ),
            continuation=self.parse_docket_search_result,
            accumulated_data={
                "docket_number": docket_number,
                "court": court,
                "entry_point": "docket_by_number",
            },
            deduplication_key=f"docket_by_number:{docket_number}",
        )

    @entry(NCAppealsDocket)
    def dockets_by_filing_date(
        self, court_ids: set[str], date_range: InferrableDateRange
    ) -> Generator[Request, None, None]:
        """Walk the e-filing library for every case touched in the date
        range.

        ``search-results.php`` filters on document filing date — i.e.
        the result is "every case with any e-filing between
        ``start_date`` and ``end_date``", not "every case opened in
        that window".

        ``bSearchTypeAnd=0`` is required: with the default ``=1`` the
        site silently ignores the date params and returns the whole
        corpus.

        The range is split into ``filing_window_days``-day windows (one
        seed search each) to keep offset pagination shallow — deep pages
        504 (see ``parse_filings_listing``).
        """
        for window_start, window_end in _iter_date_windows(
            date_range.start, date_range.end, self.filing_window_days
        ):
            start = window_start.isoformat()
            end = window_end.isoformat()
            yield Request(
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url=SEARCH_RESULTS_URL,
                    params=self._listing_params(start, end, 0),
                ),
                continuation=self.parse_filings_listing,
                accumulated_data={
                    "start_date": start,
                    "end_date": end,
                    "target_courts": sorted(court_ids),
                    "entry_point": "dockets_by_filing_date",
                },
                deduplication_key=f"filings_listing:{start}:{end}:0",
            )

    @staticmethod
    def _listing_params(start: str, end: str, istart: int) -> dict[str, str]:
        """Build the search-results.php query params for a listing page."""
        return {
            "atty_first": "",
            "atty_last": "",
            "sDocketSearch": "",
            "short_title": "",
            "party": "",
            "start_date": start,
            "end_date": end,
            "type": "",
            "court_name": "",
            "bSearchTypeAnd": "0",
            "exact": "0",
            "iStart": str(istart),
        }

    # =========================================================================
    # HTTP success handling (§10)
    # =========================================================================

    def actually_successful(self, response: Response) -> bool:
        """Treat a docket-number lookup that returned 0 cases as a miss.

        ``dockets.php?…&submit=Search`` always returns HTTP 200; a miss
        is signalled only by the result-page text. Every other 200
        response (date-range listings with no rows, the rich docket-sheet
        detail page, etc.) is a genuine success.
        """
        if response.status_code != 200:
            return response.status_code < 400
        url = response.url or ""
        if "/dockets.php" not in url or "submit=Search" not in url:
            return True
        text = response.text or ""
        return "Your search returned a total of" in text and ">0 case" in text

    # =========================================================================
    # Steps (§5)
    # =========================================================================

    @step(priority=4)
    def parse_docket_search_result(
        self,
        page: PageElement,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[NCAppealsDocket], None, None]:
        """Follow the docket-sheet link from a 1-result search page."""
        # The result page renders: ``<a href="…&pdf=1…">{caption}</a> -
        # <strong>{docket}</strong>``. There's exactly one such link on a
        # successful single-docket lookup.
        hrefs = page.query_strings(
            XPath("//a[contains(@href, 'pdf=1')]/@href"),
            "docket sheet link",
            min_count=1,
            max_count=1,
        )
        source_url = normalize_url(hrefs[0])
        accumulated_data["source_url"] = source_url
        yield Request(
            request=HTTPRequestParams(method=HttpMethod.GET, url=source_url),
            continuation=self.parse_docket_sheet,
            accumulated_data=accumulated_data,
            deduplication_key=f"docket_sheet:{accumulated_data['docket_number']}",
        )

    @step(priority=4)
    def parse_filings_listing(
        self,
        page: PageElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[NCAppealsDocket], None, None]:
        """Walk one page of the filings listing.

        Yields one per-case Request for every unique case on the page,
        plus follow-up pagination Requests for each remaining ``iStart``
        offset listed in the page's selector dropdown.
        """
        for case in DocketListingParser().cases(page, COURT_SC, COURT_COA):
            yield Request(
                request=HTTPRequestParams(
                    method=HttpMethod.GET, url=case.sheet_url
                ),
                continuation=self.parse_docket_sheet,
                accumulated_data={
                    "docket_number": case.docket_number,
                    "court": case.court,
                    "case_name_hint": case.case_name,
                    "source_url": case.sheet_url,
                    "entry_point": accumulated_data.get("entry_point"),
                },
                deduplication_key=f"docket_sheet:{case.docket_number}",
            )

        # Follow-up pages from the iStart selector. Every page lists the
        # full offset set in its dropdown, so we key each follow-up on its
        # (window, offset) to fetch it exactly once — without this dedup
        # each of N pages would re-enqueue all higher offsets (O(N²)),
        # hammering the very deep pages that 504.
        start_date = accumulated_data["start_date"]
        end_date = accumulated_data["end_date"]
        current_offset = current_istart(response.url)
        for offset in pagination_offsets(page):
            if offset <= current_offset:
                continue
            yield Request(
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url=SEARCH_RESULTS_URL,
                    params=self._listing_params(start_date, end_date, offset),
                ),
                continuation=self.parse_filings_listing,
                accumulated_data=accumulated_data,
                deduplication_key=f"filings_listing:{start_date}:{end_date}:{offset}",
            )

    @step(priority=3)
    def parse_docket_sheet(
        self,
        page: PageElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[
        ScraperYield[NCAppealsDocket | NCAppealsDocument], None, None
    ]:
        """Parse the rich docket-sheet HTML into ``NCAppealsDocket``,
        then fan out to the per-case filings page so the e-filed
        documents are also harvested as ``NCAppealsDocument`` rows.

        ``DocketSheetParser`` owns the page extraction; the step stamps
        the fields not present on the page (``docket_number``, ``court``,
        ``source_url``, ``source_entry_point``) and supplies the
        case-name fallback when the page has no long title.
        """
        raw = DocketSheetParser()(page)[0].raw_data
        docket_number = accumulated_data["docket_number"]
        raw["docket_number"] = docket_number
        raw["court"] = accumulated_data["court"]
        raw["source_url"] = accumulated_data.get("source_url") or response.url
        raw["source_entry_point"] = accumulated_data.get("entry_point")
        if not raw.get("case_name"):
            raw["case_name"] = (
                accumulated_data.get("case_name_hint") or docket_number
            )
        docket = NCAppealsDocket.raw(**raw)
        yield ParsedData(docket)

        # Fan out to the per-case filings page to harvest documents.
        yield Request(
            request=HTTPRequestParams(
                method=HttpMethod.GET,
                url=SEARCH_RESULTS_URL,
                params={
                    "sDocketSearch": docket_number,
                    "exact": "1",
                    "iStart": "0",
                },
            ),
            continuation=self.parse_case_filings,
            accumulated_data={
                "docket_number": docket_number,
                "court": accumulated_data["court"],
            },
            deduplication_key=f"case_filings:{docket_number}",
        )

    @step(priority=2)
    def parse_case_filings(
        self,
        page: PageElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[NCAppealsDocument], None, None]:
        """Walk one page of a case's e-filings list.

        Downloadable PDFs are archived (``archive=True``); the download
        handler emits the final ``NCAppealsDocument`` with the local
        path. Sealed filings (no download URL) are yielded directly so
        downstream joins see the slot.
        """
        docket_number = accumulated_data["docket_number"]
        court = accumulated_data["court"]

        for doc in CaseFilingsParser().documents(page, docket_number, court):
            if doc.document_url:
                yield Request(
                    archive=True,
                    request=HTTPRequestParams(
                        method=HttpMethod.GET, url=doc.document_url
                    ),
                    continuation=self.handle_document_download,
                    expected_type="pdf",
                    accumulated_data={"document": doc.model_dump(mode="json")},
                    deduplication_key=(
                        f"{docket_number}-{doc.document_id}.pdf"
                        if doc.document_id
                        else None
                    ),
                )
            else:
                # Sealed filing — no PDF to fetch, but still record it.
                yield ParsedData(doc)

        # Pagination — the per-case page uses the same ``iStart`` selector
        # as the date-listing page. Most cases have well under 50 filings,
        # so this branch rarely fires. Keyed per (docket, offset) so a page
        # is fetched once even though every page lists the full offset set.
        current_offset = current_istart(response.url)
        for offset in pagination_offsets(page):
            if offset <= current_offset:
                continue
            yield Request(
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url=SEARCH_RESULTS_URL,
                    params={
                        "sDocketSearch": docket_number,
                        "exact": "1",
                        "iStart": str(offset),
                    },
                ),
                continuation=self.parse_case_filings,
                accumulated_data=accumulated_data,
                deduplication_key=f"case_filings:{docket_number}:{offset}",
            )

    @step(priority=1)
    def handle_document_download(
        self,
        accumulated_data: dict,
        local_filepath: str | None = None,
    ) -> Generator[ScraperYield[NCAppealsDocument], None, None]:
        """Emit an ``NCAppealsDocument`` once the PDF has been archived."""
        payload = dict(accumulated_data["document"])
        payload["local_path"] = local_filepath
        yield ParsedData(NCAppealsDocument.model_validate(payload))
