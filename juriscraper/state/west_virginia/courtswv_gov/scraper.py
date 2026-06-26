"""West Virginia Courts (courtswv.gov) Scraper.

Scrapes dockets and order lists from the Supreme Court of Appeals of
West Virginia (``wva``) and the Intermediate Court of Appeals of West
Virginia (``wvactapp``) at https://www.courtswv.gov.

Both courts are served from a Drupal site behind two near-identical
listing pages:

- ``/appellate-courts/supreme-court-of-appeals/current-docket``
- ``/appellate-courts/intermediate-court-of-appeals/current-docket``

The listings render server-side as HTML tables (a ``bootstrap-table``
plugin then takes over for client-side pagination, but every row is in
the initial HTML). Filters are exposed as GET query parameters:
``combine`` (free text), the year filter, and the argument-type
filter. Plain HTTP — no JS challenge, captcha, or session required.

Per-page HTML extraction lives in the ``parsers`` package
(``ListingParser`` / ``CaseDetailParser``); the steps keep navigation
concerns (per-row fan-out, archive downloads).

Entry points (§4):
    - dockets_by_argument_date(court_ids, date_range) — fetch each
      court's listing for the year(s) covering the range, post-filter
      rows by docket date, follow in-window case rows into
      ``parse_case_detail`` and schedule order-list PDFs.
    - docket_by_number(court_id, docket_number)       — use
      ``combine={docket_number}`` to find the case slug, then follow the
      resulting row(s) into ``parse_case_detail``.

Per-case flow:
    parse_listing → parse_case_detail → ParsedData(WVDocket)
                                     └→ (per brief) archive Request
                                            → handle_brief_download
                                                → ParsedData(WVBrief)
Per-order-list flow:
    parse_listing → archive Request → handle_orderlist_download
                                         → ParsedData(WVOrderListPDF)
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING, ClassVar

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
    COURT_ICA,
    COURT_SCA,
    WVBrief,
    WVDocket,
    WVOrderListPDF,
)
from .parsers import CaseDetailParser, ListingParser
from .parsers._common import date_from_iso, row_matches_query

if TYPE_CHECKING:
    from collections.abc import Generator

    from jkent.common.page_element import PageElement
    from jkent.data_types import ScraperYield


BASE_URL = "https://www.courtswv.gov"
SCA_LISTING_URL = (
    f"{BASE_URL}/appellate-courts/supreme-court-of-appeals/current-docket"
)
ICA_LISTING_URL = (
    f"{BASE_URL}/appellate-courts/intermediate-court-of-appeals/current-docket"
)


@dataclass(frozen=True)
class _CourtConfig:
    """Per-court bundle of values that differ between SCA and ICA."""

    court: str
    listing_url: str
    field_prefix: str  # 'sca' or 'ica' — used to build CSS / xpath fragments
    year_param: str  # the listing form's year filter name
    arg_type_param: str  # the listing form's argument-type filter name


SCA_CONFIG = _CourtConfig(
    court=COURT_SCA,
    listing_url=SCA_LISTING_URL,
    field_prefix="sca",
    year_param="field_sca_docket_year_value",
    arg_type_param="field_sca_docket_argument_type_value",
)

ICA_CONFIG = _CourtConfig(
    court=COURT_ICA,
    listing_url=ICA_LISTING_URL,
    field_prefix="ica",
    year_param="field_ica_docket_entry_year_value",
    arg_type_param="field_ica_docket_argument_type_value",
)

_CONFIG_BY_COURT: dict[str, _CourtConfig] = {
    SCA_CONFIG.court: SCA_CONFIG,
    ICA_CONFIG.court: ICA_CONFIG,
}


class WestVirginiaCourtsScraper(
    BaseScraper[WVDocket | WVBrief | WVOrderListPDF]
):
    """Scraper for the WV Supreme Court of Appeals and Intermediate
    Court of Appeals dockets.

    Both courts ride on the same Drupal Views infrastructure with
    parallel field naming, so a single ``parse_case_detail`` services
    both. Per-court differences (URLs, field prefix, form param names)
    are captured in ``_CourtConfig`` instances looked up via
    ``accumulated_data["court"]``.
    """

    # === Metadata ===
    court_ids: ClassVar[set[str]] = {COURT_SCA, COURT_ICA}
    court_url: ClassVar[str] = BASE_URL
    data_types: ClassVar[set[str]] = {"dockets"}
    status: ClassVar[ScraperStatus] = ScraperStatus.IN_DEVELOPMENT
    version: ClassVar[str] = "2026-05-05"
    last_verified: ClassVar[str] = "2026-05-05"
    requires_auth: ClassVar[bool] = False
    driver_requirements: ClassVar[list[DriverRequirement]] = []
    rate_limits: ClassVar[list[Rate] | None] = [Rate(2, Duration.SECOND)]

    # =========================================================================
    # Entry points (§4)
    # =========================================================================

    @entry(WVDocket)
    def dockets_by_argument_date(
        self, court_ids: set[str], date_range: DateRange
    ) -> Generator[Request, None, None]:
        """Fetch dockets whose argument/docket date falls in ``date_range``.

        The listing's year filter operates on the row's docket date (when
        the case sits / the order list issues), so we constrain each
        court's response to the relevant year(s) and post-filter inside
        that window. One request per (court, year) keeps each response
        small.
        """
        for court in sorted(court_ids):
            cfg = _CONFIG_BY_COURT.get(court)
            if cfg is None:
                continue
            for year in range(date_range.start.year, date_range.end.year + 1):
                yield Request(
                    request=HTTPRequestParams(
                        method=HttpMethod.GET,
                        url=cfg.listing_url,
                        params={
                            cfg.year_param: str(year),
                            cfg.arg_type_param: "All",
                            "combine": "",
                        },
                    ),
                    continuation=self.parse_listing,
                    accumulated_data={
                        "court": cfg.court,
                        "field_prefix": cfg.field_prefix,
                        "listing_url": cfg.listing_url,
                        "date_gte": date_range.start.isoformat(),
                        "date_lte": date_range.end.isoformat(),
                        "filter_mode": "date_range",
                        "entry_point": "dockets_by_argument_date",
                    },
                    deduplication_key=SkipDeduplicationCheck(),
                )

    @entry(WVDocket)
    def docket_by_number(
        self, court_id: str, docket_number: str
    ) -> Generator[Request, None, None]:
        """Fetch a single docket by docket number from one court.

        Uses the listing's ``combine`` free-text filter to locate the case
        slug, then follows the matching row into ``parse_case_detail``.
        """
        cfg = _CONFIG_BY_COURT.get(court_id)
        if cfg is None:
            return
        yield Request(
            request=HTTPRequestParams(
                method=HttpMethod.GET,
                url=cfg.listing_url,
                params={
                    cfg.year_param: "All",
                    cfg.arg_type_param: "All",
                    "combine": docket_number,
                },
            ),
            continuation=self.parse_listing,
            accumulated_data={
                "court": cfg.court,
                "field_prefix": cfg.field_prefix,
                "listing_url": cfg.listing_url,
                "filter_mode": "docket_number",
                "docket_number_query": docket_number,
                "entry_point": "docket_by_number",
            },
            deduplication_key=f"docket_by_number:{cfg.court}:{docket_number}",
        )

    # =========================================================================
    # Step: parse the listing table (priority 4 — shallowest)
    # =========================================================================

    @step(priority=4)
    def parse_listing(
        self,
        page: PageElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[WVDocket | WVOrderListPDF], None, None]:
        """Walk the docket listing's ``<tbody>`` rows.

        Two row shapes are emitted:

        - **Case row**: yields a follow-up Request to
          ``parse_case_detail``.
        - **Order-list row** (empty case-no, PDF link): yields an archive
          Request; the ``WVOrderListPDF`` is emitted from
          ``handle_orderlist_download`` once the file is on disk.
        """
        court = accumulated_data["court"]
        field_prefix = accumulated_data["field_prefix"]
        entry_point = accumulated_data.get("entry_point")
        date_gte = date_from_iso(accumulated_data.get("date_gte"))
        date_lte = date_from_iso(accumulated_data.get("date_lte"))
        docket_number_query = (
            accumulated_data.get("docket_number_query") or ""
        ).strip()

        rows = ListingParser(field_prefix, response.url)(page)

        for row_data in rows:
            row_date = row_data["docket_date"]
            if (
                date_gte is not None
                and date_lte is not None
                and (
                    row_date is None or not (date_gte <= row_date <= date_lte)
                )
            ):
                continue

            if row_data["is_order_list"]:
                if row_date is None or not row_data["pdf_url"]:
                    continue
                yield Request(
                    archive=True,
                    request=HTTPRequestParams(
                        method=HttpMethod.GET, url=row_data["pdf_url"]
                    ),
                    continuation=self.handle_orderlist_download,
                    expected_type="pdf",
                    accumulated_data={
                        "court": court,
                        "release_date": row_date.isoformat(),
                        "download_url": row_data["pdf_url"],
                        "label": row_data["case_name"] or "ORDER LIST",
                        "source_url": response.url,
                        "entry_point": entry_point,
                    },
                    deduplication_key=(
                        f"orderlist {court} {row_data['pdf_url']}"
                    ),
                )
                continue

            detail_url = row_data["detail_url"]
            if not detail_url:
                continue

            # In docket-number mode, only follow rows whose case-no
            # matches the user's query. The `combine` filter is fuzzy
            # and may also match other columns.
            if accumulated_data.get(
                "filter_mode"
            ) == "docket_number" and not row_matches_query(
                row_data["case_no_text"], docket_number_query
            ):
                continue

            yield Request(
                request=HTTPRequestParams(
                    method=HttpMethod.GET, url=detail_url
                ),
                continuation=self.parse_case_detail,
                accumulated_data={
                    "court": court,
                    "field_prefix": field_prefix,
                    "listing_docket_date": (
                        row_date.isoformat() if row_date else None
                    ),
                    "listing_case_no": row_data["case_no_text"],
                    "listing_youtube_url": row_data["youtube_url"],
                    "entry_point": entry_point,
                },
                deduplication_key=f"case_detail:{detail_url}",
            )

    # =========================================================================
    # Step: parse the case-detail page (priority 3)
    # =========================================================================

    @step(priority=3)
    def parse_case_detail(
        self,
        page: PageElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[WVDocket | WVBrief], None, None]:
        """Parse one Drupal case-detail page into a ``WVDocket``."""
        court = accumulated_data["court"]
        field_prefix = accumulated_data["field_prefix"]
        entry_point = accumulated_data.get("entry_point")

        parser = CaseDetailParser(field_prefix)
        deferred = parser(page)
        if not deferred:
            # Calendar / month-aggregator page with no case-no block.
            return

        raw = deferred[0].raw_data

        # Fall back to listing-supplied values where the detail page is
        # missing them.
        if not (raw.get("case_name") or "").strip() and accumulated_data.get(
            "listing_case_no"
        ):
            raw["case_name"] = accumulated_data["listing_case_no"]
        if raw.get("date_argued") is None:
            raw["date_argued"] = date_from_iso(
                accumulated_data.get("listing_docket_date")
            )
        if not raw.get("youtube_url"):
            raw["youtube_url"] = accumulated_data.get("listing_youtube_url")

        raw["court"] = court
        raw["source_url"] = response.url
        raw["source_entry_point"] = entry_point

        primary_docket_number = raw["docket_number"]
        consolidated = raw.get("consolidated_docket_numbers") or []

        yield ParsedData(WVDocket.raw(**raw))

        for brief in parser.extract_briefs(
            page,
            primary_docket_number=primary_docket_number,
            consolidated_numbers=consolidated,
            base_url=response.url,
        ):
            yield Request(
                archive=True,
                request=HTTPRequestParams(
                    method=HttpMethod.GET, url=brief["download_url"]
                ),
                continuation=self.handle_brief_download,
                expected_type="pdf",
                accumulated_data={
                    "docket_number": brief["docket_number"],
                    "court": court,
                    "description": brief["description"],
                    "download_url": brief["download_url"],
                    "entry_point": entry_point,
                },
                deduplication_key=(f"brief {court} {brief['download_url']}"),
            )

    # =========================================================================
    # Step: archive callbacks (downloads — priority 1)
    # =========================================================================

    @step(priority=1)
    def handle_brief_download(
        self,
        accumulated_data: dict,
        local_filepath: str | None = None,
    ) -> Generator[ScraperYield[WVBrief], None, None]:
        """Emit a top-level ``WVBrief`` carrying the archived PDF path."""
        yield ParsedData(
            data=WVBrief(
                docket_number=accumulated_data["docket_number"],
                court=accumulated_data["court"],
                description=accumulated_data.get("description"),
                download_url=accumulated_data["download_url"],
                local_path=local_filepath,
                source_entry_point=accumulated_data.get("entry_point"),
            )
        )

    @step(priority=1)
    def handle_orderlist_download(
        self,
        accumulated_data: dict,
        local_filepath: str | None = None,
    ) -> Generator[ScraperYield[WVOrderListPDF], None, None]:
        """Emit a ``WVOrderListPDF`` for an archived order-list PDF."""
        yield ParsedData(
            data=WVOrderListPDF(
                court=accumulated_data["court"],
                release_date=date.fromisoformat(
                    accumulated_data["release_date"]
                ),
                download_url=accumulated_data["download_url"],
                label=accumulated_data.get("label"),
                source_url=accumulated_data.get("source_url"),
                local_path=local_filepath,
                source_entry_point=accumulated_data.get("entry_point"),
            )
        )
