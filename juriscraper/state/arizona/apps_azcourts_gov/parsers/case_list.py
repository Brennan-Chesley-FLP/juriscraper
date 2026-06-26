"""Parser for an AppellaDockets case-type list page (``stage_<SITE>_<TYPE>``).

Returns one ``AzAppDocket`` per PDF row, **in document order** (the
``_update`` variant is sorted by Last Updated descending, which the step
relies on for its cutoff early-stop). ``court``, ``case_type``, and
``source_url`` are not on the page — the step stamps them before emitting.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from jkent.common.deferred_validation import DeferredValidation
from jkent.common.parser import JKentParser
from jkent.data_types import XPath

from juriscraper.state.arizona.apps_azcourts_gov.models import AzAppDocket

from ._common import (
    extract_row_pdf_link,
    extract_row_timestamp_and_path,
    iter_pdf_rows,
    safe_text,
)

if TYPE_CHECKING:
    from jkent.common.page_element import PageElement


class CaseListParser(JKentParser[AzAppDocket]):
    """Parse a case-type list page into one ``AzAppDocket`` per PDF row."""

    def __call__(
        self, page: PageElement
    ) -> list[DeferredValidation[AzAppDocket]]:
        results: list[DeferredValidation[AzAppDocket]] = []
        for row in iter_pdf_rows(page):
            extracted = extract_row_pdf_link(row)
            if extracted is None:
                continue
            docket_number, pdf_url = extracted
            ts, _ = extract_row_timestamp_and_path(row)
            cells = row.query(XPath(".//td"), "row cells", min_count=1)
            case_name = safe_text(cells[1]) if len(cells) > 1 else ""
            results.append(
                AzAppDocket.raw(
                    docket_number=docket_number,
                    case_name=case_name,
                    date_last_updated=ts,
                    pdf_url=pdf_url,
                )
            )
        return results
