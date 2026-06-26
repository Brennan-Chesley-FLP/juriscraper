"""Shared helpers for the Pennsylvania UJS Portal page parsers."""

from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING

from jkent.data_types import XPath

if TYPE_CHECKING:
    from jkent.common.page_element import PageElement


def parse_mdy(text: str | None) -> date | None:
    """Parse an ``MM/DD/YYYY`` string from the results grid.

    Returns ``None`` for missing/empty/unparseable input.
    """
    text = (text or "").strip()
    if not text:
        return None
    try:
        return datetime.strptime(text, "%m/%d/%Y").date()
    except ValueError:
        return None


def cell_text(row: PageElement, column_index: int) -> str:
    """Return trimmed text of the ``column_index``-th ``<td>`` in ``row``.

    Returns ``""`` when the cell doesn't exist (defensive — appellate
    rows have all 19 columns even when most are empty).
    """
    cells = row.query(XPath("./td"), "row cells", min_count=0)
    if column_index >= len(cells):
        return ""
    return cells[column_index].text_content().strip()
