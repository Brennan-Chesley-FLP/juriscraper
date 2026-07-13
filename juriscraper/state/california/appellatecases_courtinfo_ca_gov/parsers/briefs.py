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

    The column layout differs by court: the Supreme Court table is
    ``Brief | Date Filed | Party and Attorney | Notes``, while the Court of
    Appeal table inserts a ``Due Date`` column after ``Brief``. Cells are
    therefore mapped by header text, not fixed index — a fixed-index read
    against the CoA layout shifted the filing date into ``party_attorney``
    and dropped the Notes column entirely.
    """

    def __call__(
        self, page: PageElement
    ) -> list[DeferredValidation[CaAppBrief]]:
        rows = page.query(
            XPath("//table//tbody//tr"), "brief rows", min_count=0
        )
        if not rows:
            return []
        headers = page.query(
            XPath("//table//th"), "brief header cells", min_count=2
        )
        col = {
            " ".join(h.text_content().split()).lower(): i
            for i, h in enumerate(headers)
        }
        if "date filed" not in col:
            # Header drift — re-query so the structural error carries the
            # selector and counts instead of silently mis-mapping columns.
            page.query(
                XPath('//table//th[normalize-space()="Date Filed"]'),
                "brief 'Date Filed' header",
                min_count=1,
            )

        def cell(
            cells: list[PageElement], name: str, default_idx: int | None = None
        ) -> str | None:
            idx = col.get(name, default_idx)
            if idx is None or idx >= len(cells):
                return None
            return cells[idx].text_content()

        briefs: list[DeferredValidation[CaAppBrief]] = []
        for row in rows:
            cells = row.query(XPath("td"), "brief cells", min_count=0)
            if len(cells) < 2:
                continue
            briefs.append(
                CaAppBrief.raw(
                    brief_type=(cell(cells, "brief", 0) or "").strip(),
                    date_filed=parse_date(cell(cells, "date filed")),
                    party_attorney=clean_text(
                        cell(cells, "party and attorney")
                    ),
                    notes=clean_text(cell(cells, "notes")),
                )
            )
        return briefs
