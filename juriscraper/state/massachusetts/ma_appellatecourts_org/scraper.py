"""Massachusetts Appellate Courts scraper.

Site: https://www.ma-appellatecourts.org

Scrapes dockets and oral arguments from the Massachusetts SJC (``mass``)
and Appeals Court (``massappct``). The site is an RSI "Public Access"
(Laravel) app fronted by Cloudflare's managed challenge, so the scraper
must run under a real browser (``JS_EVAL`` + ``FF_ALIKE``). Once the
challenge is satisfied we lean on the fact that *every* case is reachable
at ``/docket/{docket_id}`` regardless of the search path.

Addressing: speculative case-number enumeration. The site exposes seven
case-type categories across the two courts, each with its own docket-number
format. A single speculative entry, :meth:`dockets_by_number`, covers all
seven; the target court + case-category + (optional) year ride in the
speculative param (:class:`MaCourtRange`) and are seeded once per category.
A speculative entry is dispatched by the driver with ONLY its speculative
param — it cannot also take a ``court_ids`` argument (see
SCRAPER_STANDARDS §4, "Multi-court speculative entries").

Per-page HTML extraction lives in the ``parsers`` package
(:class:`CaseDetailParser`, :class:`CalendarParser`); the steps keep only
navigation concerns (the per-PDF archive fan-out).

Flow:
    dockets_by_number → parse_case_detail → ParsedData(MaDocket)
                                          └→ (per PDF) handle_document_download
                                                          → ParsedData(MaDocument)
    oral_arguments_by_bulk → parse_calendar → ParsedData(MaOralArgument)

Soft-404 detection: invalid docket URLs *redirect* to ``/docket`` (the
search landing) rather than returning 404. ``actually_successful`` detects
this by checking the final response URL (§10).
"""

from __future__ import annotations

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

from juriscraper.state.common.params import CourtRange

from .models import (
    BASE_URL,
    CALENDAR_TYPES,
    CASE_TYPE_NAMES,
    COURT_APPEALS,
    COURT_SJC,
    DOCKET_URL,
    MaDocket,
    MaDocument,
    MaOralArgument,
)
from .parsers import CalendarParser, CaseDetailParser

if TYPE_CHECKING:
    from collections.abc import Generator

    from jkent.common.page_element import PageElement
    from jkent.data_types import ScraperYield

_Yield = MaDocket | MaDocument | MaOralArgument


# Per-(case-category) config: docket-number formatter + the CourtListener
# court the category belongs to. ``{n}`` is the sequence number, ``{y}`` the
# year. Categories whose format references ``{y}`` are year-partitioned.
_CATEGORY_CONFIG: dict[str, tuple[str, str]] = {
    "fc": (COURT_SJC, "SJC-{n:05d}"),
    "oe": (COURT_SJC, "OE-{n:04d}"),
    "ar": (COURT_SJC, "FAR-{n:05d}"),
    "sj": (COURT_SJC, "SJ-{y}-{n:04d}"),
    "bd": (COURT_SJC, "BD-{y}-{n:03d}"),
    "ac": (COURT_APPEALS, "{y}-P-{n:04d}"),
    "aj": (COURT_APPEALS, "{y}-J-{n:04d}"),
}

# Which calendar types belong to which court.
_CALENDAR_COURT: dict[str, str] = {
    "fc": COURT_SJC,
    "sj": COURT_SJC,
    "ac": COURT_APPEALS,
    "aj": COURT_APPEALS,
}


class MaCourtRange(CourtRange):
    """``CourtRange`` carrying the MA case-category (and optional year).

    A single CourtListener court id (``mass``) spans five distinct
    docket-number spaces (Full Court / Original Entry / DAR-FAR /
    Single Justice / Bar Docket) and ``massappct`` spans two (Panel /
    Single Justice). Per SCRAPER_STANDARDS §4, the discriminator rides on
    the speculative param: ``case_category`` selects the number format and
    ``year`` partitions the year-based formats. ``from_int`` (driver
    advancement) preserves both because it copies via ``model_copy``.
    """

    case_category: str
    """Site case-type code: ``fc`` / ``oe`` / ``ar`` / ``sj`` / ``bd`` /
    ``ac`` / ``aj``. Selects the docket-number format and the court."""

    year: int | None = None
    """Calendar year, for the year-partitioned categories (``sj``, ``bd``,
    ``ac``, ``aj``). Unused for the continuous categories."""

    def docket_id(self) -> str:
        """Format the site docket id for this range's current ``min``."""
        _court, fmt = _CATEGORY_CONFIG[self.case_category]
        if self.year is None:
            return fmt.format(n=self.min)
        return fmt.format(n=self.min, y=self.year)


class MassachusettsAppellateScraper(BaseScraper[_Yield]):
    """Scraper for the Massachusetts SJC and Appeals Court.

    All seven case-type categories share the same case-detail page
    layout, so a single ``parse_case_detail`` step services every
    speculative seed.
    """

    # === Metadata ===
    court_ids: ClassVar[set[str]] = {COURT_SJC, COURT_APPEALS}
    court_url: ClassVar[str] = BASE_URL
    data_types: ClassVar[set[str]] = {"dockets", "oral_arguments"}
    status: ClassVar[ScraperStatus] = ScraperStatus.IN_DEVELOPMENT
    version: ClassVar[str] = "2026-06-27"
    last_verified: ClassVar[str] = "2026-05-03"
    requires_auth: ClassVar[bool] = False
    rate_limits: ClassVar[list[Rate] | None] = [Rate(2, Duration.SECOND)]

    # Cloudflare managed challenge gates everything, so we need a real
    # browser.
    driver_requirements: ClassVar[list[DriverRequirement]] = [
        DriverRequirement.JS_EVAL,
        DriverRequirement.FF_ALIKE,
        DriverRequirement.CFCAP_HANDLER,
    ]

    # =========================================================================
    # Entry points (§4)
    # =========================================================================

    @entry(MaDocket)
    def dockets_by_number(self, docket_number: MaCourtRange) -> Request:
        """Speculatively fetch one docket by case number for one category.

        ``docket_number.case_category`` selects the court and the
        docket-number format; the driver probes ascending ``min`` and
        advances until ``gap`` consecutive misses. Seed once per category
        (and per year for the year-partitioned categories), e.g.::

            seed_params = [
                {"dockets_by_number": {"docket_number":
                    {"court_id": "mass", "case_category": "fc",
                     "min": 13927, "soft_max": 13927, "gap": 25}}},
                {"dockets_by_number": {"docket_number":
                    {"court_id": "massappct", "case_category": "ac",
                     "year": 2025, "min": 1489, "soft_max": 1489,
                     "gap": 50}}},
                # ... one per category; year-partitioned ones once per year.
            ]
        """
        court, _fmt = _CATEGORY_CONFIG[docket_number.case_category]
        docket_id = docket_number.docket_id()
        return Request(
            request=HTTPRequestParams(
                method=HttpMethod.GET,
                url=f"{DOCKET_URL}/{docket_id}",
                headers={"Accept": "text/html"},
            ),
            continuation=self.parse_case_detail,
            accumulated_data={
                "docket_number": docket_id,
                "court": court,
                "case_category": CASE_TYPE_NAMES.get(
                    docket_number.case_category
                ),
                "entry_point": "dockets_by_number",
            },
            deduplication_key=f"parse_case_detail:{docket_id}",
        )

    @entry(MaOralArgument)
    def oral_arguments_by_bulk(
        self, court_ids: set[str]
    ) -> Generator[Request, None, None]:
        """Scrape the current-month oral-argument calendars.

        The calendar pages (``/calendar/{fc,sj,ac,aj}``) only ever show the
        *current month* and have no date picker, so the addressing mode is
        bulk. One request per calendar type whose court is in ``court_ids``.
        """
        for calendar_type, court in _CALENDAR_COURT.items():
            if court not in court_ids:
                continue
            yield Request(
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url=f"{BASE_URL}/calendar/{calendar_type}",
                    headers={"Accept": "text/html"},
                ),
                continuation=self.parse_calendar,
                accumulated_data={
                    "calendar_type": calendar_type,
                    "court": court,
                    "calendar_name": CALENDAR_TYPES.get(calendar_type),
                    "entry_point": "oral_arguments_by_bulk",
                },
                deduplication_key=f"parse_calendar:{calendar_type}",
            )

    # =========================================================================
    # Soft-404 detection (§10)
    # =========================================================================

    def actually_successful(self, response: Response) -> bool:
        """Return False for speculative misses on case-detail GETs.

        The site redirects unknown docket IDs back to ``/docket`` (the
        search landing) rather than 404'ing. Detect this by checking
        whether the final response URL still includes a docket id in its
        path. Calendar URLs always succeed and so are passed through.
        """
        url = response.url or ""
        if "/docket/" not in url:
            # Either a calendar URL (always OK) or the redirect to the
            # bare /docket landing — i.e. a miss.
            return "/calendar/" in url
        return True

    # =========================================================================
    # Step: parse a case-detail page (§5: deepest non-download step)
    # =========================================================================

    @step(priority=2)
    def parse_case_detail(
        self,
        page: PageElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[MaDocket | MaDocument], None, None]:
        """Parse a ``/docket/{id}`` page into a ``MaDocket`` and fan out
        an ``archive=True`` request for each PDF in the DOCUMENTS block.

        ``CaseDetailParser`` owns the page extraction; this step stamps the
        fields not present on the page (``docket_number``, ``court``,
        ``case_category``, ``source_url``, ``source_entry_point``).
        """
        docket_number = accumulated_data["docket_number"]
        court = accumulated_data["court"]

        parser = CaseDetailParser()
        raw = parser(page)[0].raw_data
        raw["docket_number"] = docket_number
        raw["court"] = court
        raw["case_category"] = accumulated_data.get("case_category")
        raw["source_url"] = response.url
        raw["source_entry_point"] = accumulated_data.get("entry_point")
        if not raw.get("case_name"):
            raw["case_name"] = docket_number

        yield ParsedData(MaDocket.raw(**raw))

        for url in raw.get("document_urls", []):
            description = parser.document_label_for_url(page, url)
            filename = url.rsplit("/", 1)[-1]
            yield Request(
                archive=True,
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url=url,
                    headers={"Accept": "application/pdf"},
                ),
                continuation=self.handle_document_download,
                expected_type="pdf",
                accumulated_data={
                    "docket_number": docket_number,
                    "court": court,
                    "description": description,
                    "document_url": url,
                },
                deduplication_key=f"{docket_number}-{filename}",
            )

    @step()
    def handle_document_download(
        self,
        accumulated_data: dict,
        local_filepath: str | None = None,
    ) -> Generator[ScraperYield[MaDocument], None, None]:
        """Emit an ``MaDocument`` for an archived PDF."""
        yield ParsedData(
            data=MaDocument(
                docket_number=accumulated_data["docket_number"],
                court=accumulated_data["court"],
                description=accumulated_data.get("description"),
                document_url=accumulated_data["document_url"],
                local_path=local_filepath,
            )
        )

    # =========================================================================
    # Step: parse a calendar page
    # =========================================================================

    @step(priority=2)
    def parse_calendar(
        self,
        page: PageElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[MaOralArgument], None, None]:
        """Parse one calendar page into ``MaOralArgument`` rows.

        ``CalendarParser`` owns the extraction; this step stamps ``court``,
        ``calendar_type``, ``source_url``, and ``source_entry_point``.
        """
        calendar_type = accumulated_data["calendar_type"]
        court = accumulated_data["court"]

        for session in CalendarParser()(page):
            raw = session.raw_data
            raw["court"] = court
            raw["calendar_type"] = calendar_type
            raw["source_url"] = response.url
            raw["source_entry_point"] = accumulated_data.get("entry_point")
            yield ParsedData(MaOralArgument.raw(**raw))
