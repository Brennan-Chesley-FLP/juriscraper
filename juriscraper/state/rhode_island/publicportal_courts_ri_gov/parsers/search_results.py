"""Parser for a Rhode Island Public Portal Smart Search results page.

The Tyler Odyssey Public Portal renders search results in a kendo grid
wrapping a ``<table>`` whose rows carry the case fields as ``<td>``
cells. The first cell typically holds an ``<a>`` whose ``href`` is the
case-detail URL (``/PublicPortal/Case/CaseDetail?caseId=…``).

:class:`SearchResultsParser` extracts one :class:`RIDocket` per matching
row. The result page is reCAPTCHA-gated and could not be observed live
during recon, so the XPaths follow the typical Tyler Odyssey layout —
see ``CC_NOTES.md`` "Known Gaps". The parser intentionally tolerates an
empty result set (``min_count=0``): a speculative miss yields no rows.

``court``, ``source_url`` (absolutised), and ``source_entry_point`` are
stamped by the calling step.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from jkent.common.parser import JKentParser
from jkent.data_types import XPath

from juriscraper.state.rhode_island.publicportal_courts_ri_gov.models import (
    RIDocket,
)

from ._common import clean, find_date_in_texts, pick_cell, safe_text

if TYPE_CHECKING:
    from jkent.common.deferred_validation import DeferredValidation
    from jkent.common.page_element import PageElement


# Result rows carry a link to the case-detail page. The href shape varies
# slightly across Tyler builds, so match any of the known forms.
_CASE_LINK_PRED = (
    "contains(@href, 'CaseDetail') or contains(@href, 'caseId=') "
    "or contains(@href, 'CaseID=')"
)


class SearchResultsParser(JKentParser[RIDocket]):
    """Parse the Smart Search results table into ``RIDocket`` records.

    Returns one ``RIDocket`` per result row (empty list for a no-match
    page). Each record carries the relative case-detail href in
    ``source_url``; the calling step absolutises it against the response
    URL and stamps ``court`` / ``source_entry_point``.
    """

    def __call__(
        self, page: PageElement
    ) -> list[DeferredValidation[RIDocket]]:
        rows = page.query(
            XPath(f"//table//tr[.//a[{_CASE_LINK_PRED}]]"),
            "search result rows",
            min_count=0,
        )
        out: list[DeferredValidation[RIDocket]] = []
        for row in rows:
            record = self._parse_row(row)
            if record is not None:
                out.append(record)
        return out

    @staticmethod
    def _parse_row(row: PageElement) -> DeferredValidation[RIDocket] | None:
        """Parse one result row into a deferred ``RIDocket`` (or ``None``).

        Returns ``None`` for a row missing the case link or the docket
        number (a layout glitch / header row).
        """
        link_els = row.query(
            XPath(f".//a[{_CASE_LINK_PRED}]"),
            "case detail link",
            min_count=0,
            max_count=1,
        )
        if not link_els:
            return None
        href = link_els[0].get_attribute("href") or ""
        docket_number = safe_text(link_els[0])
        if not docket_number:
            return None

        cells = row.query(XPath(".//td"), "row cells", min_count=0)
        cell_texts = [safe_text(c) for c in cells]
        case_name = cell_texts[1] if len(cell_texts) > 1 else docket_number

        return RIDocket.raw(
            docket_number=docket_number,
            case_name=case_name or docket_number,
            date_filed=find_date_in_texts(cell_texts),
            case_type=pick_cell(
                cell_texts, contains_any=["Appeal", "Petition", "Writ"]
            ),
            case_status=pick_cell(
                cell_texts,
                contains_any=["Pending", "Closed", "Disposed", "Active"],
            ),
            # Relative href; the step absolutises against the response URL.
            source_url=clean(href),
        )
