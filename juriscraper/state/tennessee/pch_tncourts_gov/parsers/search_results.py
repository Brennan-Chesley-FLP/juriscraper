"""Parser for the Tennessee PCH ``SearchResults.aspx`` listing page.

Returns one partial ``DeferredValidation[TnDocket]`` per result row,
carrying ``docket_number``, ``case_name``, ``court``, and the C-Track
``internal_case_id``. The step turns each into a case-detail fetch; the
full record is built by :class:`CaseDetailParser`.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from jkent.common.parser import JKentParser
from jkent.data_types import XPath

from juriscraper.state.tennessee.pch_tncourts_gov.models import TnDocket

from ._common import court_from_docket_number, safe_text

if TYPE_CHECKING:
    from jkent.common.deferred_validation import DeferredValidation
    from jkent.common.page_element import PageElement


# Each row is a ``<tr onclick="redirectToCase('<id>', 'Number', 'False')">``.
REDIRECT_TO_CASE_RE = re.compile(
    r"redirectToCase\('(\d+)',\s*'([^']+)',\s*'([^']+)'\)"
)


class SearchResultsParser(JKentParser[TnDocket]):
    """Parse each result row of a ``SearchResults.aspx`` page.

    Each result row is a ``<tr onclick="redirectToCase('<id>', 'Number',
    'False')">`` containing two cells (case number, style). Rows whose
    court suffix is unrecognized are dropped. The ``internal_case_id`` on
    each returned partial record is the C-Track ``MastCastID`` the step
    uses to build the ``CaseDetails.aspx`` fetch.
    """

    def __call__(
        self, page: PageElement
    ) -> list[DeferredValidation[TnDocket]]:
        rows = page.query(
            XPath(
                "//table[@id='grdSearchResult']"
                "//tr[contains(@onclick, 'redirectToCase')]"
            ),
            "result rows",
            min_count=0,
        )

        results: list[DeferredValidation[TnDocket]] = []
        for row in rows:
            onclick = row.get_attribute("onclick") or ""
            match = REDIRECT_TO_CASE_RE.search(onclick)
            if not match:
                continue
            mast_id = match.group(1)

            cells = row.query(XPath(".//td"), "result cells", min_count=0)
            if len(cells) < 2:
                continue
            docket_number = safe_text(cells[0])
            case_name = safe_text(cells[1])

            court = court_from_docket_number(docket_number)
            if court is None:
                # Skip rows we don't recognize (unknown court suffix).
                continue

            results.append(
                TnDocket.raw(
                    docket_number=docket_number,
                    court=court,
                    case_name=case_name or docket_number,
                    internal_case_id=mast_id,
                )
            )
        return results
