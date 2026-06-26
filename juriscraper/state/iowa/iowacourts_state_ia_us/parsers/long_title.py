"""Parser for the Iowa Long Title tab (``AViewLongTitle``).

The formal caption sits inside a ``<font face="Courier New">`` block in the
row following the header. Empty cases render an empty ``<br>``.
:class:`LongTitleParser` returns the whitespace-collapsed caption string,
or ``None`` when the page has no caption.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from jkent.data_types import XPath

from ._common import clean_text

if TYPE_CHECKING:
    from jkent.common.page_element import PageElement


class LongTitleParser:
    """Extract the formal caption (``case_name_full``)."""

    def __call__(self, page: PageElement) -> str | None:
        long_title_parts = page.query_strings(
            XPath("//font[contains(@face, 'Courier')]//text()"),
            "long-title text",
            min_count=0,
        )
        cleaned = clean_text(" ".join(long_title_parts))
        return cleaned or None
