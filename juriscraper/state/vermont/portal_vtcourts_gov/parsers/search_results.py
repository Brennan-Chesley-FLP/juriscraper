"""Parser for the Vermont Public Portal Smart-Search results grid.

``/Portal/SmartSearch/SmartSearchResults`` renders an HTML grid; each
matching case is a row with a ``<a class="caseLink">`` carrying the
Register-of-Actions ``data-url``. :class:`SearchResultsParser` lifts the
opaque ROA ``key`` plus the visible header columns into one
:class:`VtSearchRow` per row.

For our exact ``YY-AP-NNN`` query the grid returns at most one matching
row; a non-existent docket renders ``<p>No cases match your search</p>``
with no result table, which yields an empty list (a speculative miss).
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from urllib.parse import urljoin

from jkent.common.parser import JKentParser
from jkent.data_types import XPath

from juriscraper.state.vermont.portal_vtcourts_gov.models import (
    PORTAL_URL,
    VtSearchRow,
)

from ._common import extract_roa_key

if TYPE_CHECKING:
    from jkent.common.deferred_validation import DeferredValidation
    from jkent.common.page_element import PageElement


class SearchResultsParser(JKentParser[VtSearchRow]):
    """Extract case rows from the Smart-Search results grid."""

    def __call__(
        self, page: PageElement
    ) -> list[DeferredValidation[VtSearchRow]]:
        rows = page.query(
            XPath("//table//tr[.//a[contains(@class, 'caseLink')]]"),
            "search result rows",
            min_count=0,
        )
        out: list[DeferredValidation[VtSearchRow]] = []
        for row in rows:
            case_links = row.query(
                XPath(".//a[contains(@class, 'caseLink')]"),
                "case link",
                min_count=1,
                max_count=1,
            )
            case_link = case_links[0]
            data_url = case_link.get_attribute("data-url") or ""
            roa_key = extract_roa_key(data_url)
            if not roa_key:
                continue

            docket_number = (case_link.text_content() or "").strip()

            cells = row.query(XPath(".//td"), "row cells", min_count=0)
            cell_texts = [(c.text_content() or "").strip() for c in cells]
            # Column order: Case Number, Style/Defendant, (hidden FileDate),
            # Type, Status, Location, Date of Birth, (hidden Party Type).
            style = cell_texts[1] if len(cell_texts) > 1 else docket_number
            case_type = cell_texts[2] if len(cell_texts) > 2 else None
            case_status = cell_texts[3] if len(cell_texts) > 3 else None

            source_url = urljoin(PORTAL_URL, data_url) if data_url else None

            out.append(
                VtSearchRow.raw(
                    roa_key=roa_key,
                    docket_number=docket_number,
                    case_name=style or docket_number,
                    case_type=case_type,
                    case_status=case_status,
                    source_url=source_url,
                )
            )
        return out
