"""Parser for the Docket page."""

from __future__ import annotations

from typing import TYPE_CHECKING

from jkent.common.parser import JKentParser
from jkent.data_types import XPath

from juriscraper.state.alaska.appellate_records_courts_alaska_gov.models import (
    AkDocketEntry,
)

from ._common import parse_ak_date, safe_text

if TYPE_CHECKING:
    from jkent.common.deferred_validation import DeferredValidation
    from jkent.common.page_element import PageElement


class DocketParser(JKentParser[AkDocketEntry]):
    """Parse the Docket page (By Date view) into one ``AkDocketEntry``
    per row. All rows are present in the HTML. Each row's
    ``document_url`` (when present) is surfaced so the step can archive
    the file."""

    def __call__(
        self, page: PageElement
    ) -> list[DeferredValidation[AkDocketEntry]]:
        results: list[DeferredValidation[AkDocketEntry]] = []
        rows = page.query(
            XPath(
                "//table[@id='DocketList']//tbody/tr"
                "[not(contains(@class, 'grouping'))]"
            ),
            "docket rows",
            min_count=0,
        )
        for row in rows:
            cells = row.query(XPath(".//td"), "docket cells", min_count=0)
            if len(cells) < 6:
                continue
            doc_links = row.find_links(
                XPath(".//a[contains(@class, 'documentLink')]"),
                "docket doc link",
                min_count=0,
            )
            results.append(
                AkDocketEntry.raw(
                    entry_number=safe_text(cells[0]) or None,
                    description=safe_text(cells[2]) or None,
                    status=safe_text(cells[3]) or None,
                    date_filed=parse_ak_date(safe_text(cells[4])),
                    filed_or_issued_by=safe_text(cells[5]) or None,
                    document_url=doc_links[0].url if doc_links else None,
                )
            )
        return results
