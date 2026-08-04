"""Georgia Court of Appeals Docket Scraper.

Scrapes the public docket-search and opinion-search pages at
https://www.gaappeals.gov/. Both UIs submit GET requests to plain PHP
scripts under ``/wp-content/themes/benjamin/docket/``; everything is
server-rendered HTML with no auth, cookies, or bot protection.

This is an **HTML** scraper: per-page extraction lives in the ``parsers``
package (``CaseDetailParser``, ``OpinionSearchParser``; §9), and the steps keep
only navigation (the per-row fan-out and the PDF downloads).

Entry points (§4):

- ``opinions_by_decision_date(court_ids, date_range)`` — date-range opinion
  search. Catches **decided** cases only and yields both a docket-detail fetch
  and an opinion-PDF download per row. The detail page links the same PDF, so
  both entry points reach documents; they share the ``opinion-<case_number>``
  dedup key and download it once.
- ``dockets_by_number(docket_number)`` — speculative per-(year, letter) probe
  against the case-detail page. The Georgia case-number space partitions by
  case-type letter (A/D/E/I/O) within each year, so the speculative param
  (``GaCoaCaseNumberRange``) carries the ``letter`` discriminator and is seeded
  once per (year, letter) bucket. A speculative entry is dispatched with ONLY
  its speculative param (SCRAPER_STANDARDS §4), so the court/letter ride inside
  the param rather than as separate arguments.

Flow:

    opinions_by_decision_date → parse_opinion_search ┬→ parse_case_detail
                                                     └→ handle_opinion_download
    dockets_by_number ──────────────────────────────→ parse_case_detail

    parse_case_detail ┬→ ParsedData(GaCoaDocket)
                      ├→ ParsedData(GaCoaDocketUnavailable)   (soft-404)
                      └→ handle_opinion_download → ParsedData(GaCoaOpinion)
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, ClassVar
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
)
from pyrate_limiter import Duration, Rate

from juriscraper.state.common.params import (
    InferrableDateRange,
    YearlySpeculativeRange,
)

from .models import (
    COURT_ID,
    DETAIL_URL,
    OPINION_SEARCH_URL,
    SITE_BASE,
    GaCoaDocket,
    GaCoaDocketUnavailable,
    GaCoaOpinion,
)
from .parsers import CaseDetailParser, OpinionSearchParser
from .parsers._common import extract_filing_id, parse_iso_date

if TYPE_CHECKING:
    from collections.abc import Generator

    from jkent.common.page_element import PageElement
    from jkent.data_types import ScraperYield


# Letters the case-number space partitions by (one bucket per appeal type).
CASE_TYPE_LETTERS: tuple[str, ...] = ("A", "D", "E", "I", "O")

# The PHP detail page returns HTTP 200 even for invalid case numbers; the only
# reliable marker is an empty heading ``<h2>Case Number: </h2>``.
_SOFT_404_PATTERN = re.compile(r"<h2>\s*Case Number:\s*</h2>", re.IGNORECASE)

_Yield = GaCoaDocket | GaCoaOpinion | GaCoaDocketUnavailable


class GaCoaCaseNumberRange(YearlySpeculativeRange):
    """A year-partitioned speculative range tagged with its case-type letter.

    The Georgia case number ``A{YY}{LETTER}{NNNN}`` packs three axes — year,
    letter, and sequence — but Kent's speculation walks a single integer axis
    per seed. The ``year`` (from ``YearlySpeculativeRange``) and the ``letter``
    here pin the bucket; ``min`` walks the four-digit sequence. ``from_int``
    copies via ``model_copy`` so ``year`` and ``letter`` survive driver
    advancement. Seed once per (year, letter) bucket.
    """

    letter: str
    """Case-type letter — one of ``CASE_TYPE_LETTERS``."""


class GeorgiaCourtOfAppealsScraper(BaseScraper[_Yield]):
    """Scraper for the Georgia Court of Appeals docket and opinion search.

    Speaks the site's PHP HTML endpoints directly over plain HTTP. Emits three
    record types:

    - ``GaCoaDocket`` — one per case, with nested entries / attorneys /
      trial-court info.
    - ``GaCoaOpinion`` — one per archived opinion/order PDF (only available
      via the opinion-search path).
    - ``GaCoaDocketUnavailable`` — one per case number whose detail page came
      back as the site's soft-404 (chiefly speculative misses).
    """

    # === Metadata (§3) ===
    court_ids: ClassVar[set[str]] = {COURT_ID}
    court_url: ClassVar[str] = f"{SITE_BASE}/docket-search/"
    data_types: ClassVar[set[str]] = {"dockets"}
    status: ClassVar[ScraperStatus] = ScraperStatus.IN_DEVELOPMENT
    version: ClassVar[str] = "2026-06-27"
    last_verified: ClassVar[str] = "2026-05-02"
    requires_auth: ClassVar[bool] = False
    driver_requirements: ClassVar[list[DriverRequirement]] = []
    rate_limits: ClassVar[list[Rate] | None] = [Rate(3, Duration.SECOND)]

    # =========================================================================
    # HTTP status handling (§10)
    # =========================================================================

    def actually_successful(self, response: Response) -> bool:
        """Return ``False`` for the soft-404 the detail page emits.

        The PHP detail page returns HTTP 200 even for invalid case numbers;
        the only reliable marker is an empty heading ``<h2>Case Number: </h2>``.
        Only applies to the detail page; other responses pass through.
        """
        if response.url and "results_one_record.php" not in response.url:
            return True
        text = response.text or ""
        return not _SOFT_404_PATTERN.search(text)

    # =========================================================================
    # Entry points (§4)
    # =========================================================================

    @entry(GaCoaDocket)
    def opinions_by_decision_date(
        self, court_ids: set[str], date_range: InferrableDateRange
    ) -> Generator[Request, None, None]:
        """Date-range opinion search; yields decided cases in the window.

        ``court_ids`` is accepted for the §4 signature but this scraper covers
        exactly one court (``gactapp``).
        """
        yield Request(
            request=HTTPRequestParams(
                method=HttpMethod.GET,
                url=OPINION_SEARCH_URL,
                params={
                    "OPstartDate": date_range.start.strftime("%m/%d/%Y"),
                    "OPendDate": date_range.end.strftime("%m/%d/%Y"),
                },
            ),
            continuation=self.parse_opinion_search,
            accumulated_data={
                "date_start": date_range.start.isoformat(),
                "date_end": date_range.end.isoformat(),
                "entry_point": "opinions_by_decision_date",
            },
            deduplication_key=(
                f"opinion_search:{date_range.start.isoformat()}:"
                f"{date_range.end.isoformat()}"
            ),
        )

    @entry(GaCoaDocket)
    def dockets_by_number(
        self, docket_number: GaCoaCaseNumberRange
    ) -> Request:
        """Speculative ``A{YY}{LETTER}{NNNN}`` lookup for one (year, letter) bucket.

        ``docket_number.year`` + ``docket_number.letter`` pin the bucket; the
        driver probes ``min`` ascending. Seed once per (year, letter), e.g.::

            seed_params = [
                {"dockets_by_number": {"docket_number":
                    {"year": 2026, "letter": "A", "min": 1, "soft_max": 1, "gap": 15}}},
                # ... one per (year, letter) in CASE_TYPE_LETTERS.
            ]
        """
        case_number = (
            f"A{docket_number.year % 100:02d}"
            f"{docket_number.letter}{docket_number.min:04d}"
        )
        return Request(
            request=HTTPRequestParams(
                method=HttpMethod.GET,
                url=DETAIL_URL,
                params={"docr_case_num": case_number},
            ),
            continuation=self.parse_case_detail,
            accumulated_data={
                "docket_number": case_number,
                "entry_point": "dockets_by_number",
            },
            deduplication_key=f"case_detail:{case_number}",
        )

    # =========================================================================
    # Step 1: opinion-search results
    # =========================================================================

    @step(priority=3)
    def parse_opinion_search(
        self,
        page: PageElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[GaCoaDocket | GaCoaOpinion], None, None]:
        """Parse the opinion-search results table.

        For each row, yield (a) a detail fetch deduped on the case number and
        (b) an archive request for the opinion PDF. The judgment date and
        ruling from the row are forwarded into the detail step via
        ``accumulated_data``.
        """
        entry_point = accumulated_data.get("entry_point")
        for row in OpinionSearchParser()(page):
            judgment_iso = (
                row.date_judgment.isoformat() if row.date_judgment else None
            )

            # 1) docket detail fetch — the search page already gives us the
            # judgment metadata, so we forward it along.
            yield Request(
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url=DETAIL_URL,
                    params={"docr_case_num": row.docket_number},
                ),
                continuation=self.parse_case_detail,
                accumulated_data={
                    "docket_number": row.docket_number,
                    "preview_case_name": row.case_name,
                    "date_judgment": judgment_iso,
                    "judgment_ruling": row.judgment_ruling,
                    "entry_point": entry_point,
                },
                deduplication_key=f"case_detail:{row.docket_number}",
            )

            # 2) opinion PDF archive (independent record).
            if row.pdf_url:
                absolute_pdf_url = urljoin(response.url, row.pdf_url)
                yield Request(
                    archive=True,
                    request=HTTPRequestParams(
                        method=HttpMethod.GET, url=absolute_pdf_url
                    ),
                    continuation=self.handle_opinion_download,
                    expected_type="pdf",
                    accumulated_data={
                        "docket_number": row.docket_number,
                        "date_judgment": judgment_iso,
                        "judgment_ruling": row.judgment_ruling,
                        "filing_id": extract_filing_id(absolute_pdf_url),
                        "entry_point": entry_point,
                    },
                    deduplication_key=f"opinion-{row.docket_number}",
                )

    # =========================================================================
    # Step 2: case detail
    # =========================================================================

    @step(priority=2)
    def parse_case_detail(
        self,
        page: PageElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[_Yield], None, None]:
        """Parse the per-case detail HTML into a GaCoaDocket.

        ``CaseDetailParser`` owns the page extraction; the step stamps the
        fields not present on the page (``court``, provenance) and supplies
        fallbacks for the docket number / case name / judgment metadata from
        ``accumulated_data``.

        A decided case links its opinion/order PDF from the ``Opinion/Order``
        row, so the step also fans out an archive request for it — that is the
        only way the speculative entry point reaches documents. The
        ``opinion-<case_number>`` dedup key is shared with
        ``parse_opinion_search``, so a case reached both ways downloads once.

        The soft-404 check comes first: the driver consults
        ``actually_successful`` only to stop speculation, so a soft-404 body
        still reaches this step. Its skeleton of empty tables has nothing to
        parse (and, being invalid HTML, lxml re-nests it into rows that look
        like real ones), so it yields a ``GaCoaDocketUnavailable`` recording
        the searched number rather than an empty docket.
        """
        if not self.actually_successful(response):
            searched = (accumulated_data.get("docket_number") or "").strip()
            searched = searched.upper()
            yield ParsedData(
                GaCoaDocketUnavailable(
                    docket_number=searched,
                    court=COURT_ID,
                    case_type=searched[3:4] or None,
                    source_url=response.url,
                    source_entry_point=accumulated_data.get("entry_point"),
                )
            )
            return

        raw = CaseDetailParser()(page)[0].raw_data

        docket_number = (
            raw.get("docket_number")
            or (accumulated_data.get("docket_number") or "").strip().upper()
        )
        raw["docket_number"] = docket_number
        if not raw.get("case_name"):
            raw["case_name"] = (
                accumulated_data.get("preview_case_name") or docket_number
            )
        raw["court"] = COURT_ID
        # The detail page carries the disposition once the case is decided;
        # the opinion-search row is the fallback for anything it omits.
        raw["date_judgment"] = raw.get("date_judgment") or parse_iso_date(
            accumulated_data.get("date_judgment")
        )
        raw["judgment_ruling"] = raw.get(
            "judgment_ruling"
        ) or accumulated_data.get("judgment_ruling")
        raw["source_url"] = response.url
        raw["source_entry_point"] = accumulated_data.get("entry_point")
        yield ParsedData(GaCoaDocket.raw(**raw))

        opinion_url = raw.get("opinion_url")
        if opinion_url:
            date_judgment = raw.get("date_judgment")
            yield Request(
                archive=True,
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url=urljoin(response.url, opinion_url),
                ),
                continuation=self.handle_opinion_download,
                expected_type="pdf",
                accumulated_data={
                    "docket_number": docket_number,
                    "date_judgment": (
                        date_judgment.isoformat() if date_judgment else None
                    ),
                    "judgment_ruling": raw.get("judgment_ruling"),
                    "filing_id": raw.get("opinion_filing_id"),
                    "entry_point": accumulated_data.get("entry_point"),
                },
                deduplication_key=f"opinion-{docket_number}",
            )

    # =========================================================================
    # Step 3: opinion download completion
    # =========================================================================

    @step(priority=0)
    def handle_opinion_download(
        self,
        local_filepath: str | None,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[GaCoaOpinion], None, None]:
        """Emit a GaCoaOpinion record once an opinion PDF has been archived."""
        yield ParsedData(
            GaCoaOpinion.raw(
                docket_number=accumulated_data["docket_number"],
                download_url=response.url,
                filing_id=accumulated_data.get("filing_id"),
                date_judgment=parse_iso_date(
                    accumulated_data.get("date_judgment")
                ),
                judgment_ruling=accumulated_data.get("judgment_ruling"),
                local_path=local_filepath,
                source_entry_point=accumulated_data.get("entry_point"),
            )
        )
