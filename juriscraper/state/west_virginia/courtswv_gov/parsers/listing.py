"""Parser for a West Virginia courtswv.gov docket-listing page.

The "Current Docket" page renders a Drupal View into an HTML ``<table>``;
all rows are present in the initial HTML (a ``bootstrap-table`` plugin only
paginates client-side). :class:`ListingParser` walks the ``<tbody>`` rows
and returns one structured dict per row describing what it points at — a
case-detail link, an order-list PDF, or neither.

Unlike :class:`CaseDetailParser`, this parser does not build a model record:
listing rows are navigation affordances (the step decides whether to follow
a detail link or schedule a PDF archive download), so it returns plain row
dicts rather than ``DeferredValidation`` instances.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from urllib.parse import urljoin

from jkent.data_types import XPath

from ._common import parse_listing_date

if TYPE_CHECKING:
    from datetime import date

    from jkent.common.page_element import PageElement


class ListingParser:
    """Extract navigation rows from a courtswv.gov docket listing.

    ``__call__`` returns a list of row dicts, each with::

        {
            "docket_date": date | None,
            "case_no_text": str,
            "case_name": str,
            "detail_url": str | None,
            "pdf_url": str | None,
            "youtube_url": str | None,
            "is_order_list": bool,
        }

    ``base_url`` resolves the row's relative hrefs to absolute URLs.
    """

    def __init__(self, field_prefix: str, base_url: str | None) -> None:
        self.field_prefix = field_prefix
        self.base_url = base_url

    def __call__(self, page: PageElement) -> list[dict]:
        rows = page.query(
            XPath("//table[contains(@class,'views-view-table')]/tbody/tr"),
            "listing rows",
            min_count=0,
        )
        out: list[dict] = []
        for row in rows:
            row_data = self._extract_row(row)
            if row_data is not None:
                out.append(row_data)
        return out

    def _extract_row(self, row: PageElement) -> dict | None:
        """Extract docket-date / case-no / case-name from one ``<tr>``.

        Returns ``None`` when the row doesn't carry a usable date
        (defensive against the rare non-data row).
        """
        prefix = self.field_prefix

        date_cells = row.query_strings(
            XPath(
                f".//td[contains(@class,'views-field-field-{prefix}-docket-date')]/text()"
            ),
            "row date",
            min_count=0,
        )
        raw_date = " ".join(t.strip() for t in date_cells if t.strip())
        docket_date: date | None = parse_listing_date(raw_date)

        # Case-no cell may contain an <a> wrapping the docket number, or be
        # blank for an order-list row.
        case_no_link_hrefs = row.query_strings(
            XPath(
                f".//td[contains(@class,'views-field-field-{prefix}-docket-case-no')]"
                f"//a[1]/@href"
            ),
            "case-no href",
            min_count=0,
            max_count=1,
        )
        case_no_link_text = row.query_strings(
            XPath(
                f".//td[contains(@class,'views-field-field-{prefix}-docket-case-no')]"
                f"//a[1]//text()"
            ),
            "case-no link text",
            min_count=0,
        )
        case_no_text_nodes = row.query_strings(
            XPath(
                f".//td[contains(@class,'views-field-field-{prefix}-docket-case-no')]//text()"
            ),
            "case-no text",
            min_count=0,
        )
        case_no_full = " ".join(
            t.strip() for t in case_no_text_nodes if t.strip()
        )

        # Third column ("nothing"): contains either an order-list PDF link
        # or a YouTube webcast link wrapping the case name.
        name_cell_hrefs = row.query_strings(
            XPath(".//td[contains(@class,'views-field-nothing')]//a/@href"),
            "name-cell hrefs",
            min_count=0,
        )
        name_cell_text_nodes = row.query_strings(
            XPath(".//td[contains(@class,'views-field-nothing')]//text()"),
            "name-cell text",
            min_count=0,
        )
        case_name_full = " ".join(
            t.strip() for t in name_cell_text_nodes if t.strip()
        )

        base = self.base_url
        pdf_url: str | None = None
        youtube_url: str | None = None
        detail_url: str | None = None

        if case_no_link_hrefs:
            detail_url = urljoin(base or "", case_no_link_hrefs[0])

        for href in name_cell_hrefs:
            if (
                href.lower().endswith(".pdf")
                or "/pubfilesmnt/" in href.lower()
            ):
                pdf_url = urljoin(base or "", href)
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
