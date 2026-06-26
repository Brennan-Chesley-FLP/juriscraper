"""Parser for the AppellaDockets Attorney Index page.

Each name cell looks like ``ABNEY, DAVID <SMALL ...>[AZ-9001]</small>`` (or
``[OH]`` / ``[CA]`` for out-of-state counsel). We pull the jurisdiction and
any digits out of the bracket and strip the bracket from the name. Returns
one ``AzAppAttorneyCase`` per data row; the step stamps ``court``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from jkent.common.deferred_validation import DeferredValidation
from jkent.common.parser import JKentParser
from jkent.data_types import XPath

from juriscraper.state.arizona.apps_azcourts_gov.models import (
    AzAppAttorneyCase,
)

from ._common import (
    BAR_BRACKET_RE,
    extract_row_pdf_link,
    iter_pdf_rows,
    safe_text,
)

if TYPE_CHECKING:
    from jkent.common.page_element import PageElement


class AttorneyIndexParser(JKentParser[AzAppAttorneyCase]):
    """Parse the Attorney Index, splitting bar number from name."""

    def __call__(
        self, page: PageElement
    ) -> list[DeferredValidation[AzAppAttorneyCase]]:
        results: list[DeferredValidation[AzAppAttorneyCase]] = []
        for row in iter_pdf_rows(page):
            extracted = extract_row_pdf_link(row)
            if extracted is None:
                continue
            docket_number, pdf_url = extracted
            cells = row.query(XPath(".//td"), "row cells", min_count=3)
            if len(cells) < 3:
                continue

            full_text = safe_text(cells[0])
            bar_match = BAR_BRACKET_RE.search(full_text)
            bar_number = bar_match.group("num") if bar_match else None
            bar_jurisdiction = (
                bar_match.group("juris").upper() if bar_match else None
            )
            attorney_name = (
                BAR_BRACKET_RE.sub("", full_text).strip().rstrip(",")
            ).strip()
            if not attorney_name:
                continue

            results.append(
                AzAppAttorneyCase.raw(
                    attorney_name=attorney_name,
                    bar_number=bar_number,
                    bar_jurisdiction=bar_jurisdiction,
                    docket_number=docket_number,
                    case_pdf_url=pdf_url,
                    case_title=safe_text(cells[2]),
                )
            )
        return results
