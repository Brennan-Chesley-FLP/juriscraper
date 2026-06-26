"""Parser for the NYSCEF case-search results grid.

URL: ``https://iapps.courts.state.ny.us/nyscef/CaseSearchResults``

The results table (``table.NewSearchResults``) lists one case per data row:
case number (a link carrying the ``docketId``) + received date, eFiling
status, short caption, and court + case type. A case-number search returns
one row; a date search returns many (paginated).

This parser returns one partial :class:`NYSCEFCase` per row carrying the
fields visible in the grid. The calling step adds the parties, originating
court, and documents from the later pages before emitting, and reads the
``iapps_internal_docket_id`` to navigate to the case-detail page. Empty
results (no table) are valid and yield an empty list.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from jkent.common.deferred_validation import DeferredValidation
from jkent.common.parser import JKentParser
from jkent.data_types import XPath

from juriscraper.state.new_york.iapps_courts_state_ny_us.models import (
    COURT_NAME_TO_ID,
    NYSCEFCase,
)

from ._common import extract_query_param, parse_date_mdy

if TYPE_CHECKING:
    from jkent.common.page_element import PageElement


class SearchResultsParser(JKentParser[NYSCEFCase]):
    """Parse the ``NewSearchResults`` table into partial ``NYSCEFCase`` rows."""

    def __call__(
        self, page: PageElement
    ) -> list[DeferredValidation[NYSCEFCase]]:
        rows = page.query(
            XPath(
                "//table[contains(@class, 'NewSearchResults')]"
                "//tr[position()>1]"
            ),
            "search result rows",
            min_count=0,
        )
        results: list[DeferredValidation[NYSCEFCase]] = []
        for row in rows:
            cells = row.query(XPath(".//td"), "row cells", min_count=0)
            if len(cells) < 4:
                continue

            # Cell 0: case # (link carrying docketId) + received date.
            case_links = cells[0].query(
                XPath(".//a"), "case link", min_count=0, max_count=1
            )
            if not case_links:
                continue
            link_href = case_links[0].get_attribute("href")
            case_number = case_links[0].text_content().strip()

            cell0_text = cells[0].text_content().strip()
            date_received = parse_date_mdy(
                cell0_text.replace(case_number, "").strip()
            )

            # Cell 1: eFiling / case status.
            efiling_status = cells[1].text_content().strip() or None

            # Cell 2: short caption.
            case_name_short = cells[2].text_content().strip() or None

            # Cell 3: court name + case type (newline-separated).
            cell3_texts = [
                t.strip()
                for t in cells[3].text_content().strip().split("\n")
                if t.strip()
            ]
            court_name_raw = cell3_texts[0] if cell3_texts else ""
            case_type = cell3_texts[1] if len(cell3_texts) > 1 else None

            docket_id = extract_query_param(link_href, "docketId")

            results.append(
                NYSCEFCase.raw(
                    docket_number=case_number,
                    court=COURT_NAME_TO_ID.get(court_name_raw, court_name_raw),
                    court_name_raw=court_name_raw or None,
                    iapps_internal_docket_id=docket_id,
                    case_name_short=case_name_short,
                    case_type=case_type,
                    efiling_status=efiling_status,
                    date_received=date_received,
                )
            )
        return results
