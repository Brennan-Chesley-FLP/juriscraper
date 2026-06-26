"""Parser for the Briefs list page."""

from __future__ import annotations

from typing import TYPE_CHECKING

from jkent.common.parser import JKentParser
from jkent.data_types import XPath

from juriscraper.state.alaska.appellate_records_courts_alaska_gov.models import (
    AkBrief,
)

from ._common import parse_ak_date, safe_text

if TYPE_CHECKING:
    from jkent.common.deferred_validation import DeferredValidation
    from jkent.common.page_element import PageElement


class BriefsParser(JKentParser[AkBrief]):
    """Parse the Briefs table into one ``AkBrief`` per row.

    ``history_url`` (the ``Dkt#`` cell link to the brief-history page)
    and ``document_url`` are surfaced so the step can chain into the
    history and archive documents.
    """

    def __call__(self, page: PageElement) -> list[DeferredValidation[AkBrief]]:
        results: list[DeferredValidation[AkBrief]] = []
        rows = page.query(
            XPath("//table[contains(@class, 'cms-brief-table')]//tbody/tr"),
            "brief rows",
            min_count=0,
        )
        for row in rows:
            cells = row.query(XPath(".//td"), "brief cells", min_count=0)
            if len(cells) < 6:
                continue
            history_links = cells[0].find_links(
                XPath(".//a"), "brief history link", min_count=0
            )
            doc_links = row.find_links(
                XPath(".//a[contains(@class, 'glyphicon-file')]"),
                "brief doc",
                min_count=0,
            )
            results.append(
                AkBrief.raw(
                    entry_number=safe_text(cells[0]) or None,
                    brief_type=safe_text(cells[2]) or None,
                    party=safe_text(cells[3]) or None,
                    status=safe_text(cells[4]) or None,
                    brief_date=parse_ak_date(safe_text(cells[5])),
                    document_url=doc_links[0].url if doc_links else None,
                    history_url=(
                        history_links[0].url if history_links else None
                    ),
                )
            )
        return results
