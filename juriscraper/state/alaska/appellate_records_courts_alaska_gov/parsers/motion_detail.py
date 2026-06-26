"""Parser for a single motion-detail page."""

from __future__ import annotations

from typing import TYPE_CHECKING

from jkent.common.parser import JKentParser
from jkent.data_types import XPath

from juriscraper.state.alaska.appellate_records_courts_alaska_gov.models import (
    AkMotion,
)

from ._common import collect_glyphicon_labels, safe_text

if TYPE_CHECKING:
    from jkent.common.deferred_validation import DeferredValidation
    from jkent.common.page_element import PageElement


class MotionDetailParser(JKentParser[AkMotion]):
    """Parse a motion-detail page into an ``AkMotion`` fragment.

    Emits only the detail-page fields (extension metadata, checkbox
    flags, oppositions, orders); the step merges this onto the motion
    already captured from the motions list. Order rows surface a
    ``document_url`` so the step can archive any order documents.
    """

    def __call__(
        self, page: PageElement
    ) -> list[DeferredValidation[AkMotion]]:
        dd_map = self._dd_map(page)
        d: dict = {
            "response_due_date": dd_map.get("Response Due Date") or None,
            "extension_number": dd_map.get("Extension Number") or None,
            "total_extensions": (
                dd_map.get("Total Number of Extensions") or None
            ),
            "days_requested": dd_map.get("Days Requested") or None,
            # The site labels prior extensions "Previous Days Extended".
            "days_extended": (
                dd_map.get("Previous Days Extended")
                or dd_map.get("Days Extended")
                or None
            ),
            # ...and the projected total "Total Extension if Granted".
            "total_days_extended": (
                dd_map.get("Total Extension if Granted")
                or dd_map.get("Total Days Extended")
                or None
            ),
            "current_due_date": dd_map.get("Current Due Date") or None,
            "requested_due_date": dd_map.get("Requested Due Date") or None,
            "flags": [
                {"motion_flag": label, "motion_value": value}
                for label, value in collect_glyphicon_labels(page).items()
            ],
            "oppositions": self._parse_oppositions(page),
            "orders": self._parse_orders(page),
        }
        return [AkMotion.raw(**d)]

    @staticmethod
    def _dd_map(page: PageElement) -> dict[str, str]:
        dd_map: dict[str, str] = {}
        for dt in page.query(XPath("//dt"), "detail dts", min_count=0):
            label = safe_text(dt).rstrip(":").strip()
            dd_els = dt.query(
                XPath("./following-sibling::dd[1]"), "detail dd", min_count=0
            )
            if dd_els:
                dd_map[label] = safe_text(dd_els[0])
        return dd_map

    @staticmethod
    def _parse_oppositions(page: PageElement) -> list[dict]:
        rows = page.query(
            XPath(
                "//h4[contains(text(), 'Oppositions')]"
                "/following-sibling::div[1]//table//tbody/tr"
            ),
            "opposition rows",
            min_count=0,
        )
        out: list[dict] = []
        for row in rows:
            cells = row.query(XPath(".//td"), "opposition cells", min_count=0)
            if cells:
                out.append({"text": " | ".join(safe_text(c) for c in cells)})
        return out

    @staticmethod
    def _parse_orders(page: PageElement) -> list[dict]:
        rows = page.query(
            XPath(
                "//h4[contains(text(), 'Orders')]"
                "/following-sibling::div[1]//table//tbody/tr"
            ),
            "order rows",
            min_count=0,
        )
        out: list[dict] = []
        for row in rows:
            cells = row.query(XPath(".//td"), "order cells", min_count=0)
            if len(cells) < 4:
                continue
            doc_links = row.find_links(
                XPath(".//a[contains(@class, 'glyphicon-file')]"),
                "order doc",
                min_count=0,
            )
            out.append(
                {
                    "entry_number": safe_text(cells[0]) or None,
                    "ruling": safe_text(cells[2]) or None,
                    "distribution_date": safe_text(cells[3]) or None,
                    "new_due_date": (
                        safe_text(cells[4]) if len(cells) > 4 else None
                    ),
                    "document_url": doc_links[0].url if doc_links else None,
                }
            )
        return out
