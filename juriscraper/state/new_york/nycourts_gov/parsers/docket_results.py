"""Parser for the Court-PASS docket-results grid (``parse_docket_results``)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from jkent.common.deferred_validation import DeferredValidation
from jkent.common.parser import JKentParser
from jkent.data_types import XPath

from juriscraper.state.new_york.nycourts_gov.models import NYCourtPassDocket

from ._common import _parse_date_mdy

if TYPE_CHECKING:
    from jkent.common.page_element import PageElement


class DocketResultsParser(JKentParser[NYCourtPassDocket]):
    """Parse each row of the ``gvResults`` docket search grid.

    Returns one ``DeferredValidation[NYCourtPassDocket]`` per data row,
    carrying the fields that survive into NYCourtPassDocket:
    ``case_short_name``, ``argument_date``, plus ``search_row`` (the 0-based
    row index within this page of search results).

    The Select button's ``aria-label`` is deliberately not read: it restates
    the two cells above it and nothing more, and Court-PASS double-escapes it,
    so carrying it meant carrying the site's entities as well. Dropped
    2026-08-16 after the data audit.
    """

    def __call__(
        self, page: PageElement
    ) -> list[DeferredValidation[NYCourtPassDocket]]:
        data_rows = page.query(
            XPath(
                "//table[contains(@id, 'gvResults')]"
                "//tr[.//input[contains(@id, 'btnSelect')]]"
            ),
            "docket data rows",
            min_count=0,
        )
        results: list[DeferredValidation[NYCourtPassDocket]] = []
        for i, row in enumerate(data_rows):
            cells = row.query(XPath("td"), "row cells", min_count=0)
            if len(cells) < 3:
                continue
            case_title = " ".join(cells[1].text_content().split())
            argument_date_str = cells[2].text_content().strip()
            results.append(
                NYCourtPassDocket.raw(
                    case_short_name=case_title or None,
                    argument_date=_parse_date_mdy(argument_date_str),
                    search_row=i,
                )
            )
        return results
