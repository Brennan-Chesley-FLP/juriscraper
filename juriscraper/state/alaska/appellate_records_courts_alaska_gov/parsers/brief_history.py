"""Parser for a single brief-history page."""

from __future__ import annotations

from typing import TYPE_CHECKING

from jkent.common.parser import JKentParser
from jkent.data_types import XPath

from juriscraper.state.alaska.appellate_records_courts_alaska_gov.models import (
    AkBrief,
)

from ._common import safe_text

if TYPE_CHECKING:
    from jkent.common.deferred_validation import DeferredValidation
    from jkent.common.page_element import PageElement


class BriefHistoryParser(JKentParser[AkBrief]):
    """Parse a brief-history page into an ``AkBrief`` fragment.

    Emits ``filing_party``, a refined ``brief_type``, and the history
    rows; the step merges this onto the brief captured from the briefs
    list. History rows surface a ``document_url`` for archiving.
    """

    def __call__(self, page: PageElement) -> list[DeferredValidation[AkBrief]]:
        d: dict = {}
        for dt in page.query(XPath("//dt"), "brief dts", min_count=0):
            label = safe_text(dt).rstrip(":")
            dd_els = dt.query(
                XPath("./following-sibling::dd[1]"), "brief dd", min_count=0
            )
            if not dd_els:
                continue
            val = safe_text(dd_els[0])
            if "Brief Type" in label and val:
                d["brief_type"] = val
            elif "Filing Party" in label:
                d["filing_party"] = val or None

        d["history"] = self._parse_history(page)
        return [AkBrief.raw(**d)]

    @staticmethod
    def _parse_history(page: PageElement) -> list[dict]:
        rows = page.query(
            XPath("//table[contains(@class, 'cms-brief-table')]//tbody/tr"),
            "brief history rows",
            min_count=0,
        )
        out: list[dict] = []
        for row in rows:
            cells = row.query(XPath(".//td"), "history cells", min_count=0)
            if len(cells) < 5:
                continue
            doc_links = row.find_links(
                XPath(".//a[contains(@class, 'glyphicon-file')]"),
                "history doc",
                min_count=0,
            )
            out.append(
                {
                    "entry_number": safe_text(cells[0]) or None,
                    "type": safe_text(cells[2]) or None,
                    "date_filed_or_issued": safe_text(cells[3]) or None,
                    "date_due_or_status": safe_text(cells[4]) or None,
                    "document_url": doc_links[0].url if doc_links else None,
                }
            )
        return out
