"""Parser for the Briefs tab (``parse_briefs``)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from jkent.common.deferred_validation import DeferredValidation
from jkent.common.parser import JKentParser
from jkent.data_types import XPath

from juriscraper.state.california.appellatecases_courtinfo_ca_gov.models import (
    CaAppBrief,
)

from ._common import clean_text, parse_date

if TYPE_CHECKING:
    from jkent.common.page_element import PageElement


class BriefsParser(JKentParser[CaAppBrief]):
    """Parse each row of the Briefs table.

    Columns: brief type/description, date filed, party & attorney (often
    empty), notes. Identical structure for Supreme Court and Court of
    Appeal.
    """

    def __call__(
        self, page: PageElement
    ) -> list[DeferredValidation[CaAppBrief]]:
        rows = page.query(
            XPath("//table//tbody//tr"), "brief rows", min_count=0
        )
        briefs: list[DeferredValidation[CaAppBrief]] = []
        for row in rows:
            cells = row.query(XPath("td"), "brief cells", min_count=0)
            if len(cells) < 2:
                continue
            briefs.append(
                CaAppBrief.raw(
                    brief_type=cells[0].text_content().strip(),
                    date_filed=parse_date(cells[1].text_content()),
                    party_attorney=(
                        clean_text(cells[2].text_content())
                        if len(cells) > 2
                        else None
                    ),
                    notes=(
                        clean_text(cells[3].text_content())
                        if len(cells) > 3
                        else None
                    ),
                )
            )
        return briefs
