"""Parser for an OSCN ``Results.aspx`` date-range search page.

The search page is a single HTML table of every appellate case filed in
the requested window. This parser pulls each result row's case-detail
link, case number, and filed date out of the table; the step owns the
navigation (per-case fan-out and the 500-row cap resume logic).

The result page yields navigation targets, not finished records, so this
parser is not a :class:`JKentParser` (which returns
``DeferredValidation`` records) — it returns plain
:class:`SearchResultRow` descriptors the step consumes.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING
from urllib.parse import urljoin

from jkent.data_types import XPath

from ._common import normalize_ws, parse_date

if TYPE_CHECKING:
    from jkent.common.page_element import PageElement

# OSCN caps Results.aspx output at 500 rows regardless of the date range;
# when this marker appears we resume scanning from the latest date shown.
RESULTS_CAP_MARKER = "limited to 500"


@dataclass(frozen=True)
class SearchResultRow:
    """One row of an OSCN ``Results.aspx`` table."""

    docket_number: str
    """Case number text from the ``result_casenumber`` link."""
    detail_url: str
    """Absolute URL of the case-detail page."""
    date_filed: date | None
    """Filed date from the ``result_datefiled`` cell, if parseable."""


class SearchResultsParser:
    """Extract result rows from a ``Results.aspx`` table."""

    def __call__(
        self, page: PageElement, base_url: str
    ) -> list[SearchResultRow]:
        result_rows = page.query(
            XPath("//tr[contains(@class, 'resultTableRow')]"),
            "search result rows",
            min_count=0,
        )
        rows: list[SearchResultRow] = []
        seen: set[str] = set()
        for row in result_rows:
            link_nodes = row.query(
                XPath(".//td[contains(@class, 'result_casenumber')]/a"),
                "case-number anchor",
                min_count=0,
                max_count=1,
            )
            if not link_nodes:
                continue
            href = link_nodes[0].get_attribute("href")
            if not href:
                continue
            absolute = urljoin(base_url, href)
            if absolute in seen:
                continue
            seen.add(absolute)

            date_nodes = row.query(
                XPath(".//td[contains(@class, 'result_datefiled')]"),
                "date filed cell",
                min_count=0,
                max_count=1,
            )
            docket_number = normalize_ws(link_nodes[0].text_content())
            row_date = (
                parse_date(date_nodes[0].text_content())
                if date_nodes
                else None
            )
            rows.append(
                SearchResultRow(
                    docket_number=docket_number,
                    detail_url=absolute,
                    date_filed=row_date,
                )
            )
        return rows

    @staticmethod
    def cap_hit(text: str | None) -> bool:
        """True when the page reports the 500-row server cap."""
        return RESULTS_CAP_MARKER in (text or "")
