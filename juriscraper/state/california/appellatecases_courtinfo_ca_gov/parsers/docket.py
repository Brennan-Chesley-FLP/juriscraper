"""Parser for the Docket / Register of Actions tab (``parse_docket``)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from jkent.common.deferred_validation import DeferredValidation
from jkent.common.parser import JKentParser
from jkent.data_types import XPath

from juriscraper.state.california.appellatecases_courtinfo_ca_gov.models import (
    CaAppDocketEntry,
)

from ._common import clean_text, parse_date

if TYPE_CHECKING:
    from jkent.common.page_element import PageElement


class DocketEntriesParser(JKentParser[CaAppDocketEntry]):
    """Parse each row of the Register of Actions table.

    Returns one ``CaAppDocketEntry`` per row (Date, Description, optional
    Notes). Identical structure for Supreme Court and Court of Appeal.
    """

    def __call__(
        self, page: PageElement
    ) -> list[DeferredValidation[CaAppDocketEntry]]:
        rows = page.query(
            XPath("//table//tbody//tr"), "docket entry rows", min_count=0
        )
        entries: list[DeferredValidation[CaAppDocketEntry]] = []
        for row in rows:
            cells = row.query(XPath("td"), "row cells", min_count=0)
            if len(cells) < 2:
                continue
            entries.append(
                CaAppDocketEntry.raw(
                    date_filed=parse_date(cells[0].text_content()),
                    description=cells[1].text_content().strip(),
                    notes=(
                        clean_text(cells[2].text_content())
                        if len(cells) > 2
                        else None
                    ),
                )
            )
        return entries
