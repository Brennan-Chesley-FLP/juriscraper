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
filter.

Entry points (one set per court):

- ``get_{court}_dockets_by_date(date_range)`` — fetches the listing,
  post-filters rows by docket date, and follows each in-window row
  into ``parse_case_detail`` (case rows) or yields a
  ``WVOrderListPDF`` directly (order-list rows).
- ``fetch_{court}_docket_by_number(docket_number)`` — uses
  ``combine={docket_number}`` to find the case slug, then follows the
  resulting row(s) into ``parse_case_detail``.

Per-case flow:

  parse_case_detail
        │
        ├── ParsedData(WVDocket)
        └── for each brief link:
               archive Request → handle_brief_download
                                     │
                                     ▼
                                ParsedData(WVBrief)
        (briefs are top-level only; join back to WVDocket on
        ``docket_number``)

Per-order-list flow (initiated in ``parse_listing``):

  archive Request → handle_orderlist_download
                          │
                          ▼
                    ParsedData(WVOrderListPDF)  (release_date + local_path)
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import TYPE_CHECKING, ClassVar
from urllib.parse import urljoin

from jkent.common.decorators import entry, step
from jkent.common.page_element import PageElement
from jkent.common.param_models import DateRange
from jkent.data_types import (
    BaseScraper,
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

if TYPE_CHECKING:
    from collections.abc import Generator

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

    court_id: str
    listing_url: str
    field_prefix: str  # 'sca' or 'ica' — used to build CSS / xpath fragments
    year_param: str  # the listing form's year filter name
    arg_type_param: str  # the listing form's argument-type filter name


SCA_CONFIG = _CourtConfig(
    court_id=COURT_SCA,
    listing_url=SCA_LISTING_URL,
    field_prefix="sca",
    year_param="field_sca_docket_year_value",
    arg_type_param="field_sca_docket_argument_type_value",
)

ICA_CONFIG = _CourtConfig(
    court_id=COURT_ICA,
    listing_url=ICA_LISTING_URL,
    field_prefix="ica",
    year_param="field_ica_docket_entry_year_value",
    arg_type_param="field_ica_docket_argument_type_value",
)


# Split consolidated case-no strings on either separator: " & " or " and ".
_CONSOLIDATED_SPLIT_RE = re.compile(r"\s*(?:&|and)\s*", re.IGNORECASE)

_CLERK_BRIEFS_RE = re.compile(
    r"briefs?[\s\S]{0,40}?(?:on file|filed)[\s\S]{0,40}?clerk",
    re.IGNORECASE,
)

_LISTING_DATE_RE = re.compile(r"\b(\d{2}/\d{2}/\d{4})\b")


class WestVirginiaCourtsScraper(
    BaseScraper[WVDocket | WVBrief | WVOrderListPDF]
):
    """Scraper for the WV Supreme Court of Appeals and Intermediate
    Court of Appeals dockets.

    Both courts ride on the same Drupal Views infrastructure with
    parallel field naming, so a single ``parse_case_detail`` services
    both. Per-court differences (URLs, field prefix, form param names)
    are captured in ``_CourtConfig`` instances looked up via
    ``accumulated_data["court_id"]``.
    """

    # === Metadata ===
    court_ids: ClassVar[set[str]] = {COURT_SCA, COURT_ICA}
    court_url: ClassVar[str] = BASE_URL
    data_types: ClassVar[set[str]] = {"dockets"}
    status: ClassVar[ScraperStatus] = ScraperStatus.IN_DEVELOPMENT
    version: ClassVar[str] = "2026-05-05"
    requires_auth: ClassVar[bool] = False
    rate_limits: ClassVar[list[Rate] | None] = [Rate(2, Duration.SECOND)]

    # =========================================================================
    # Entry points — Supreme Court of Appeals
    # =========================================================================

    @entry(WVDocket)
    def get_sca_dockets_by_date(
        self, date_range: DateRange
    ) -> Generator[Request, None, None]:
        """Fetch SCA dockets whose docket date falls in ``date_range``."""
        yield from self._listing_request_for_date_range(SCA_CONFIG, date_range)

    @entry(WVDocket)
    def fetch_sca_docket_by_number(
        self, docket_number: str
    ) -> Generator[Request, None, None]:
        """Fetch a single SCA docket by docket number."""
        yield self._listing_request_for_docket_number(
            SCA_CONFIG, docket_number
        )

    # =========================================================================
    # Entry points — Intermediate Court of Appeals
    # =========================================================================

    @entry(WVDocket)
    def get_ica_dockets_by_date(
        self, date_range: DateRange
    ) -> Generator[Request, None, None]:
        """Fetch ICA dockets whose docket date falls in ``date_range``."""
        yield from self._listing_request_for_date_range(ICA_CONFIG, date_range)

    @entry(WVDocket)
    def fetch_ica_docket_by_number(
        self, docket_number: str
    ) -> Generator[Request, None, None]:
        """Fetch a single ICA docket by docket number."""
        yield self._listing_request_for_docket_number(
            ICA_CONFIG, docket_number
        )

    # =========================================================================
    # Listing request helpers
    # =========================================================================

    def _listing_request_for_date_range(
        self, cfg: _CourtConfig, date_range: DateRange
    ) -> Generator[Request, None, None]:
        """Issue one listing GET per year covered by ``date_range``.

        The listing's year filter operates on the row's docket date, so
        we constrain the response to just the relevant year(s) and
        post-filter inside that window. For multi-year ranges (rare in
        practice) we issue one request per year so the response stays
        small.
        """
        years = list(range(date_range.start.year, date_range.end.year + 1))
        for year in years:
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
                    "court_id": cfg.court_id,
                    "field_prefix": cfg.field_prefix,
                    "date_gte": date_range.start.isoformat(),
                    "date_lte": date_range.end.isoformat(),
                    "filter_mode": "date_range",
                },
                deduplication_key=SkipDeduplicationCheck(),
            )

    def _listing_request_for_docket_number(
        self, cfg: _CourtConfig, docket_number: str
    ) -> Request:
        return Request(
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
                "court_id": cfg.court_id,
                "field_prefix": cfg.field_prefix,
                "filter_mode": "docket_number",
                "docket_number_query": docket_number,
            },
            deduplication_key=f"wv-listing-{cfg.court_id}-{docket_number}",
        )

    # =========================================================================
    # Step 1: parse the listing table
    # =========================================================================

    @step()
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
        - **Order-list row** (empty case-no, PDF link in third column):
          yields an archive Request for the PDF; the
          ``WVOrderListPDF`` itself is emitted from
          ``handle_orderlist_download`` once the file is on disk.
        """
        court_id = accumulated_data["court_id"]
        field_prefix = accumulated_data["field_prefix"]
        date_gte_raw = accumulated_data.get("date_gte")
        date_lte_raw = accumulated_data.get("date_lte")
        date_gte = date.fromisoformat(date_gte_raw) if date_gte_raw else None
        date_lte = date.fromisoformat(date_lte_raw) if date_lte_raw else None
        docket_number_query = (
            accumulated_data.get("docket_number_query") or ""
        ).strip()

        rows = page.query_xpath(
            "//table[contains(@class,'views-view-table')]/tbody/tr",
            "listing rows",
            min_count=0,
        )

        for row in rows:
            row_data = _extract_listing_row(row, field_prefix, response.url)
            if row_data is None:
                continue

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
                        "court_id": court_id,
                        "release_date": row_date.isoformat(),
                        "download_url": row_data["pdf_url"],
                        "label": row_data["case_name"] or "ORDER LIST",
                        "source_url": response.url,
                    },
                    deduplication_key=f"wv-orderlist-{court_id}-{row_data['pdf_url']}",
                )
                continue

            detail_url = row_data["detail_url"]
            if not detail_url:
                continue

            # In docket-number mode, only follow rows whose case-no
            # matches the user's query. The `combine` filter is fuzzy
            # and may also match other columns.
            if accumulated_data.get("filter_mode") == "docket_number" and (
                not _row_matches_query(
                    row_data["case_no_text"], docket_number_query
                )
            ):
                continue

            yield Request(
                request=HTTPRequestParams(
                    method=HttpMethod.GET, url=detail_url
                ),
                continuation=self.parse_case_detail,
                accumulated_data={
                    "court_id": court_id,
                    "field_prefix": field_prefix,
                    "listing_docket_date": (
                        row_date.isoformat() if row_date else None
                    ),
                    "listing_case_no": row_data["case_no_text"],
                    "listing_youtube_url": row_data["youtube_url"],
                },
                deduplication_key=detail_url,
            )

    # =========================================================================
    # Step 2: parse the case-detail page
    # =========================================================================

    @step()
    def parse_case_detail(
        self,
        page: PageElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[WVDocket | WVBrief], None, None]:
        """Parse one Drupal case-detail page into a ``WVDocket``."""
        court_id = accumulated_data["court_id"]
        field_prefix = accumulated_data["field_prefix"]

        case_no_text = (
            _drupal_field_text(page, field_prefix, "case-no")
            or accumulated_data.get("listing_case_no")
            or ""
        ).strip()
        if not case_no_text:
            # Some ICA listing rows link to month-aggregator pages with
            # no case-no field. Skip them — they're not single cases.
            return

        consolidated = _split_docket_numbers(case_no_text)
        primary_docket_number = (
            consolidated[0] if consolidated else case_no_text
        )

        case_name = (
            _drupal_field_text(page, field_prefix, "case-name") or case_no_text
        )

        docket_date = _parse_detail_date(page, field_prefix) or _date_from_iso(
            accumulated_data.get("listing_docket_date")
        )

        docket_time = _drupal_field_text(page, field_prefix, "time")
        argument_type = _drupal_field_text(page, field_prefix, "argument-type")

        youtube_url = _drupal_field_link(
            page, field_prefix, "youtube-link"
        ) or accumulated_data.get("listing_youtube_url")

        note_text = _drupal_field_text(page, field_prefix, "note")
        clerk_has_briefs = bool(
            note_text and _CLERK_BRIEFS_RE.search(note_text)
        )

        docket = WVDocket(
            docket_number=primary_docket_number,
            court_id=court_id,
            consolidated_docket_numbers=consolidated,
            case_name=case_name,
            docket_date=docket_date,
            docket_time=docket_time,
            argument_type=argument_type,
            youtube_url=youtube_url,
            clerk_has_briefs=clerk_has_briefs,
            note=note_text,
            source_url=response.url,
        )
        yield ParsedData(data=docket)

        for brief in _extract_briefs(
            page,
            field_prefix=field_prefix,
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
                    "court_id": court_id,
                    "description": brief["description"],
                    "download_url": brief["download_url"],
                },
                deduplication_key=(
                    f"wv-brief-{court_id}-{brief['download_url']}"
                ),
            )

    # =========================================================================
    # Step 3: archive callbacks
    # =========================================================================

    @step()
    def handle_brief_download(
        self,
        accumulated_data: dict,
        local_filepath: str | None = None,
    ) -> Generator[ScraperYield[WVBrief], None, None]:
        """Emit a top-level ``WVBrief`` carrying the archived PDF path."""
        yield ParsedData(
            data=WVBrief(
                docket_number=accumulated_data["docket_number"],
                court_id=accumulated_data["court_id"],
                description=accumulated_data.get("description") or "",
                download_url=accumulated_data["download_url"],
                local_path=local_filepath,
            )
        )

    @step()
    def handle_orderlist_download(
        self,
        accumulated_data: dict,
        local_filepath: str | None = None,
    ) -> Generator[ScraperYield[WVOrderListPDF], None, None]:
        """Emit a ``WVOrderListPDF`` for an archived order-list PDF."""
        yield ParsedData(
            data=WVOrderListPDF(
                court_id=accumulated_data["court_id"],
                release_date=date.fromisoformat(
                    accumulated_data["release_date"]
                ),
                download_url=accumulated_data["download_url"],
                label=accumulated_data.get("label"),
                source_url=accumulated_data.get("source_url"),
                local_path=local_filepath,
            )
        )


# =============================================================================
# Module-level parsing helpers
# =============================================================================


def _extract_listing_row(
    row: PageElement, field_prefix: str, base_url: str | None
) -> dict | None:
    """Extract docket-date / case-no / case-name from one ``<tr>``.

    Returns ``None`` when the row doesn't carry a usable date (defensive
    against the rare cases where the listing renders a non-data row).
    """
    date_cells = row.query_xpath_strings(
        f".//td[contains(@class,'views-field-field-{field_prefix}-docket-date')]/text()",
        "row date",
        min_count=0,
    )
    raw_date = " ".join(t.strip() for t in date_cells if t.strip())
    docket_date = _parse_listing_date(raw_date)

    # Case-no cell may contain an <a> wrapping the docket number, or be
    # blank for an order-list row.
    case_no_link_hrefs = row.query_xpath_strings(
        f".//td[contains(@class,'views-field-field-{field_prefix}-docket-case-no')]"
        f"//a[1]/@href",
        "case-no href",
        min_count=0,
        max_count=1,
    )
    case_no_link_text = row.query_xpath_strings(
        f".//td[contains(@class,'views-field-field-{field_prefix}-docket-case-no')]"
        f"//a[1]//text()",
        "case-no link text",
        min_count=0,
    )
    case_no_text_nodes = row.query_xpath_strings(
        f".//td[contains(@class,'views-field-field-{field_prefix}-docket-case-no')]//text()",
        "case-no text",
        min_count=0,
    )
    case_no_full = " ".join(t.strip() for t in case_no_text_nodes if t.strip())

    # Third column ("nothing"): contains either an order-list PDF link
    # or a YouTube webcast link wrapping the case name.
    name_cell_hrefs = row.query_xpath_strings(
        ".//td[contains(@class,'views-field-nothing')]//a/@href",
        "name-cell hrefs",
        min_count=0,
    )
    name_cell_text_nodes = row.query_xpath_strings(
        ".//td[contains(@class,'views-field-nothing')]//text()",
        "name-cell text",
        min_count=0,
    )
    case_name_full = " ".join(
        t.strip() for t in name_cell_text_nodes if t.strip()
    )

    pdf_url = None
    youtube_url = None
    detail_url = None

    if case_no_link_hrefs:
        detail_url = urljoin(base_url or BASE_URL, case_no_link_hrefs[0])

    for href in name_cell_hrefs:
        if href.lower().endswith(".pdf") or "/pubfilesmnt/" in href.lower():
            pdf_url = urljoin(base_url or BASE_URL, href)
        elif "youtube.com" in href or "youtu.be" in href:
            youtube_url = href

    is_order_list = (
        not case_no_full
        and bool(pdf_url)
        and "ORDER LIST" in case_name_full.upper()
    )

    return {
        "docket_date": docket_date,
        "case_no_text": case_no_full,
        "case_no_link_text": " ".join(
            t.strip() for t in case_no_link_text if t.strip()
        ),
        "case_name": case_name_full,
        "detail_url": detail_url,
        "pdf_url": pdf_url,
        "youtube_url": youtube_url,
        "is_order_list": is_order_list,
    }


def _row_matches_query(case_no_text: str, query: str) -> bool:
    """Check whether the listing row's case-no contains the requested
    docket number.

    ``combine=`` searches multiple columns, so we re-verify here that
    the row really does match the user's docket-number query before
    following its detail link. Comparison is case-insensitive and
    matches against any component of a consolidated case-no string.
    """
    if not query:
        return True
    components = _split_docket_numbers(case_no_text)
    needle = query.lower().strip()
    for component in components:
        if component.lower() == needle:
            return True
    # Fall back to substring match (handles formatting drift like
    # "25-ICA-280" vs "25-ica-280").
    return needle in case_no_text.lower()


def _split_docket_numbers(case_no_text: str) -> list[str]:
    """Split a possibly-consolidated case-no string into components."""
    if not case_no_text:
        return []
    parts = [
        p.strip()
        for p in _CONSOLIDATED_SPLIT_RE.split(case_no_text)
        if p.strip()
    ]
    return parts


def _parse_listing_date(raw: str) -> date | None:
    """Parse the ``MM/DD/YYYY`` date in a listing row."""
    if not raw:
        return None
    match = _LISTING_DATE_RE.search(raw)
    if not match:
        return None
    try:
        return datetime.strptime(match.group(1), "%m/%d/%Y").date()
    except ValueError:
        return None


def _date_from_iso(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _drupal_field_text(
    page: PageElement, field_prefix: str, suffix: str
) -> str | None:
    """Extract the rendered text from a Drupal field block.

    Drupal renders a field with class
    ``field--name-field-{prefix}-docket-{suffix}``. The value lives
    inside ``.field__item`` (sometimes nested with ``<p>`` /
    ``<strong>`` tags). We collect every text node under that block,
    join with spaces, and trim.
    """
    text_nodes = page.query_xpath_strings(
        f"//div[contains(@class,'field--name-field-{field_prefix}-docket-{suffix}')]"
        f"//div[contains(@class,'field__item')]//text()",
        f"{field_prefix}-{suffix} text",
        min_count=0,
    )
    text = " ".join(t.strip() for t in text_nodes if t.strip())
    return text or None


def _drupal_field_link(
    page: PageElement, field_prefix: str, suffix: str
) -> str | None:
    """Extract the first ``<a href>`` from a Drupal field block."""
    hrefs = page.query_xpath_strings(
        f"//div[contains(@class,'field--name-field-{field_prefix}-docket-{suffix}')]"
        f"//a/@href",
        f"{field_prefix}-{suffix} href",
        min_count=0,
        max_count=1,
    )
    if not hrefs:
        return None
    return hrefs[0]


def _parse_detail_date(page: PageElement, field_prefix: str) -> date | None:
    """Pull the ISO date attribute from the docket-date ``<time>``."""
    iso_values = page.query_xpath_strings(
        f"//div[contains(@class,'field--name-field-{field_prefix}-docket-date')]"
        f"//time/@datetime",
        f"{field_prefix}-docket-date datetime",
        min_count=0,
        max_count=1,
    )
    if iso_values:
        try:
            return datetime.fromisoformat(
                iso_values[0].replace("Z", "+00:00")
            ).date()
        except ValueError:
            pass
    # Fall back to the rendered text (e.g. "Wednesday, April 22, 2026").
    rendered = _drupal_field_text(page, field_prefix, "date")
    if rendered:
        for fmt in ("%A, %B %d, %Y", "%B %d, %Y"):
            try:
                return datetime.strptime(rendered, fmt).date()
            except ValueError:
                continue
    return None


def _extract_briefs(
    page: PageElement,
    *,
    field_prefix: str,
    primary_docket_number: str,
    consolidated_numbers: list[str],
    base_url: str | None,
) -> list[dict]:
    """Pull brief / order references from the case-detail page.

    Returns a list of plain dicts (``docket_number``, ``description``,
    ``download_url``) suitable for plumbing into archive Requests via
    ``accumulated_data``. The brief field is absent entirely for
    clerk-only cases; missing block → ``[]``.
    """
    items = page.query_xpath(
        f"//div[contains(@class,'field--name-field-{field_prefix}-docket-briefs')]"
        f"//div[contains(@class,'field__item')]",
        "brief items",
        min_count=0,
    )
    briefs: list[dict] = []
    for item in items:
        hrefs = item.query_xpath_strings(
            ".//a/@href", "brief href", min_count=0, max_count=1
        )
        if not hrefs:
            continue
        url = urljoin(base_url or BASE_URL, hrefs[0])
        label_parts = item.query_xpath_strings(
            ".//a//text()", "brief label", min_count=0
        )
        description = " ".join(p.strip() for p in label_parts if p.strip())

        component = _component_for_brief(
            description, consolidated_numbers, primary_docket_number
        )
        briefs.append(
            {
                "docket_number": component,
                "description": description or "",
                "download_url": url,
            }
        )
    return briefs


def _component_for_brief(
    description: str,
    consolidated_numbers: list[str],
    primary_docket_number: str,
) -> str:
    """Pick which docket number a brief belongs to in a consolidated case.

    The site labels component briefs with their docket-number prefix
    (``"23-753 Petitioner's Brief"``). When the description starts with
    a known component, we assign the brief to that component. Otherwise
    we fall back to the primary docket number.
    """
    if not description or len(consolidated_numbers) <= 1:
        return primary_docket_number
    for component in consolidated_numbers:
        if description.lower().startswith(component.lower()):
            return component
    return primary_docket_number
