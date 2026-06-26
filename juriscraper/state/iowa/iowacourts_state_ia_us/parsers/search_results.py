"""Parser for an Iowa advanced-search results page.

The search posts to ``AViewSearchResultsAdv`` and renders a single result
table. Each case appears once as a clickable docket-number anchor
(``<a href="javascript:mySubmit('YY-NNNN')">YY-NNNN</a>``); the other
rows for the same case repeat the empty cells without an anchor.
:class:`SearchResultsParser` returns the de-duplicated list of ``YY-NNNN``
docket numbers found on the page — the step turns each into a case-detail
fetch.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from jkent.data_types import XPath

from ._common import clean_text

if TYPE_CHECKING:
    from jkent.common.page_element import PageElement

# Docket numbers are exactly ``YY-NNNN``.
DOCKET_RE = re.compile(r"^\d{2}-\d{4}$")

# Soft-404 signal: real cases render an EDMS span; non-existent cases
# render an HTML comment ``<!-- !EDMS -->`` (note the leading bang).
SOFT_404_RE = re.compile(r"<!--\s*!EDMS\s*-->")


class SearchResultsParser:
    """Extract the unique ``YY-NNNN`` docket numbers from a results page."""

    def __call__(self, page: PageElement) -> list[str]:
        anchors = page.query(
            XPath("//a[starts-with(@href, 'javascript:mySubmit')]"),
            "search-result docket links",
            min_count=0,
        )
        seen: set[str] = set()
        out: list[str] = []
        for anchor in anchors:
            text = clean_text(anchor.text_content())
            if not DOCKET_RE.match(text) or text in seen:
                continue
            seen.add(text)
            out.append(text)
        return out
