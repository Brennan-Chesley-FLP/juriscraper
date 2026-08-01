"""Parser for the Motions and Orders list page."""

from __future__ import annotations

from typing import TYPE_CHECKING

from jkent.common.parser import JKentParser
from jkent.data_types import XPath

from juriscraper.state.alaska.appellate_records_courts_alaska_gov.models import (
    AkMotion,
)

from ._common import parse_ak_date, safe_text, text_lines

if TYPE_CHECKING:
    from jkent.common.deferred_validation import DeferredValidation
    from jkent.common.page_element import PageElement


class MotionsParser(JKentParser[AkMotion]):
    """Parse the Motions and Orders table into one ``AkMotion`` per row.

    ``detail_url`` (the ``Dkt#`` cell link to the motion-detail page) and
    ``document_url`` are surfaced so the step can chain into details and
    archive documents.
    """

    def __call__(
        self, page: PageElement
    ) -> list[DeferredValidation[AkMotion]]:
        results: list[DeferredValidation[AkMotion]] = []
        rows = page.query(
            XPath("//table[contains(@class, 'cms-motion-table')]//tbody/tr"),
            "motion rows",
            min_count=0,
        )
        for row in rows:
            cells = row.query(XPath(".//td"), "motion cells", min_count=0)
            if len(cells) < 6:
                continue
            detail_links = cells[0].find_links(
                XPath(".//a"), "motion detail link", min_count=0
            )
            doc_links = row.find_links(
                XPath(".//a[contains(@class, 'glyphicon-file')]"),
                "motion doc link",
                min_count=0,
            )
            results.append(
                AkMotion.raw(
                    entry_number=(
                        " ".join(text_lines(cells[0], "motion dkt#")) or None
                    ),
                    motion_type=safe_text(cells[2]) or None,
                    filed_or_issued_by=safe_text(cells[3]) or None,
                    motion_date=parse_ak_date(safe_text(cells[4])),
                    status=safe_text(cells[5]) or None,
                    document_url=doc_links[0].url if doc_links else None,
                    detail_url=(detail_links[0].url if detail_links else None),
                )
            )
        return results
