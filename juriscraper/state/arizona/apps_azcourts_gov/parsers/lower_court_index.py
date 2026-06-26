"""Parser for the AppellaDockets Lower Court Index page.

The index is segmented by lower-court name. Each segment begins with a
heading row carrying the court name and an ``<a name="...">`` anchor; the
rows that follow belong to that segment until the next heading. ASC's index
also has category-marker rows (pure-digit anchors: ``150`` "Appellate
Court", ``200`` "Superior Court", ``500`` "Other") which are skipped so data
rows are attributed to the specific court, not the generic parent.

Returns one ``AzAppLowerCourtCase`` per data row; the step stamps ``court``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from jkent.common.deferred_validation import DeferredValidation
from jkent.common.parser import JKentParser
from jkent.data_types import XPath

from juriscraper.state.arizona.apps_azcourts_gov.models import (
    AzAppLowerCourtCase,
)

from ._common import extract_row_pdf_link, safe_text

if TYPE_CHECKING:
    from jkent.common.page_element import PageElement


class LowerCourtIndexParser(JKentParser[AzAppLowerCourtCase]):
    """Parse the Lower Court Index, tracking section headings."""

    def __call__(
        self, page: PageElement
    ) -> list[DeferredValidation[AzAppLowerCourtCase]]:
        all_rows = page.query(XPath("//tr"), "rows", min_count=1)

        current_court_name: str | None = None
        current_court_anchor: str | None = None

        results: list[DeferredValidation[AzAppLowerCourtCase]] = []
        for row in all_rows:
            heading = self._extract_heading(row)
            if heading is not None:
                current_court_name, current_court_anchor = heading
                continue

            extracted = extract_row_pdf_link(row)
            if extracted is None:
                continue
            our_docket, pdf_url = extracted
            cells = row.query(XPath(".//td"), "row cells", min_count=3)
            if len(cells) < 3:
                continue
            if not current_court_name:
                # No heading yet; skip until we see one. The page should
                # always emit a heading before its rows.
                continue

            results.append(
                AzAppLowerCourtCase.raw(
                    lower_court_case_number=safe_text(cells[0]),
                    lower_court_name=current_court_name,
                    lower_court_anchor=current_court_anchor,
                    our_docket_number=our_docket,
                    our_case_pdf_url=pdf_url,
                    case_title=safe_text(cells[2]),
                )
            )
        return results

    @staticmethod
    def _extract_heading(row: PageElement) -> tuple[str, str] | None:
        """If this row is a specific-court heading, return ``(name, anchor)``.

        Heading rows look like::

            <TR>
              <TD ...><b>COURT OF APPEALS, DIVISION ONE</b></TD>
              <TD ...><b><a name="1 CA">1 CA</a></b></TD>
              ...
            </TR>

        Category-marker rows whose anchors are pure digits (``150``/``200``/
        ``500``) are not real courts and return ``None``.
        """
        anchors = row.query(
            XPath(".//a[@name]"), "heading anchors", min_count=0
        )
        named = [a for a in anchors if (a.get_attribute("name") or "").strip()]
        if not named:
            return None
        anchor_name = (named[0].get_attribute("name") or "").strip()
        if not anchor_name or anchor_name.isdigit():
            # Category marker (e.g. "150", "200", "500"); not a real court.
            return None
        bold_texts: list[str] = []
        for b in row.query(XPath(".//b"), "bold spans", min_count=0):
            text = b.text_content().strip()
            if text and text != anchor_name:
                bold_texts.append(text)
        if not bold_texts:
            return None
        return bold_texts[0], anchor_name
