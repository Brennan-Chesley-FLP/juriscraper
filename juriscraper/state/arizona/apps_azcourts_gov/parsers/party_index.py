"""Parser for the AppellaDockets Party Index page.

Flat rows; letter-section headers are ignored. Returns one
``AzAppPartyCase`` per data row; the step stamps ``court``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from jkent.common.deferred_validation import DeferredValidation
from jkent.common.parser import JKentParser
from jkent.data_types import XPath

from juriscraper.state.arizona.apps_azcourts_gov.models import AzAppPartyCase

from ._common import extract_row_pdf_link, iter_pdf_rows, safe_text

if TYPE_CHECKING:
    from jkent.common.page_element import PageElement


class PartyIndexParser(JKentParser[AzAppPartyCase]):
    """Parse the Party Index into one ``AzAppPartyCase`` per row."""

    def __call__(
        self, page: PageElement
    ) -> list[DeferredValidation[AzAppPartyCase]]:
        results: list[DeferredValidation[AzAppPartyCase]] = []
        for row in iter_pdf_rows(page):
            extracted = extract_row_pdf_link(row)
            if extracted is None:
                continue
            docket_number, pdf_url = extracted
            cells = row.query(XPath(".//td"), "row cells", min_count=3)
            if len(cells) < 3:
                continue
            party_name = safe_text(cells[0])
            if not party_name:
                continue
            results.append(
                AzAppPartyCase.raw(
                    party_name=party_name,
                    docket_number=docket_number,
                    case_pdf_url=pdf_url,
                    case_title=safe_text(cells[2]),
                )
            )
        return results
