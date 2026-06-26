"""Parser for the Washington DW Courts case-detail (case-summary) page.

The case-detail page lists every docket event in a Tabulator table. The
server embeds the rows as an inline JavaScript ``data = [...]`` array; the
scraper step parses that array off ``response.text`` (primary). When the
inline array is absent (e.g. the site moves to AJAX loading),
:class:`CaseDetailDomParser` extracts the visible ``.tabulator-row``
elements from the rendered DOM instead (fallback) — staying on the public
``PageElement`` API (§9).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from jkent.common.parser import JKentParser
from jkent.data_types import XPath

from juriscraper.state.washington.dw_courts_wa_gov.models import (
    DWWADocketEntry,
)

from ._common import parse_dw_date

if TYPE_CHECKING:
    from jkent.common.deferred_validation import DeferredValidation
    from jkent.common.page_element import PageElement


class CaseDetailDomParser(JKentParser[DWWADocketEntry]):
    """Extract docket entries from the rendered Tabulator DOM (fallback)."""

    def __call__(
        self, page: PageElement
    ) -> list[DeferredValidation[DWWADocketEntry]]:
        out: list[DeferredValidation[DWWADocketEntry]] = []
        rows = page.query(
            XPath("//div[contains(@class, 'tabulator-row')]"),
            "tabulator rows",
            min_count=0,
        )
        for row in rows:
            cells = row.query(
                XPath(".//div[contains(@class, 'tabulator-cell')]"),
                "tabulator cells",
                min_count=0,
            )
            if len(cells) >= 3:
                out.append(
                    DWWADocketEntry.raw(
                        date_filed=parse_dw_date(
                            cells[0].text_content().strip()
                        ),
                        description=cells[1].text_content().strip(),
                        action=cells[2].text_content().strip(),
                    )
                )
        return out
