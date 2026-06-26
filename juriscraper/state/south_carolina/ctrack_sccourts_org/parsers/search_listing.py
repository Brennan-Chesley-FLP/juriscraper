"""Parser for the SC C-Track case-search results listing."""

from __future__ import annotations

from typing import TYPE_CHECKING

from jkent.common.deferred_validation import DeferredValidation
from jkent.common.parser import JKentParser
from jkent.data_types import XPath

from juriscraper.state.south_carolina.ctrack_sccourts_org.models import (
    SCAppDocket,
)

from ._common import COURT_NAME_TO_COURT, CSIID_RE, normalize_whitespace

if TYPE_CHECKING:
    from jkent.common.page_element import PageElement


class SearchListingParser(JKentParser[SCAppDocket]):
    """Parse each result row of a ``caseSearch.do`` listing page.

    Returns one ``DeferredValidation[SCAppDocket]`` per result row,
    carrying only the fields readable from the row — ``court``,
    ``docket_number``, and ``site_case_id`` (the C-Track ``csIID``).
    The step turns each into a case-detail fetch; the full record is
    built by :class:`CaseDetailParser`.
    """

    def __call__(
        self, page: PageElement
    ) -> list[DeferredValidation[SCAppDocket]]:
        # Only match leaf <tr> rows that have a case link as a *child* of
        # one of their TDs — keeps ancestor table rows (which inherit
        # descendant matches) out of the list.
        rows = page.query(
            XPath("//tr[./td/a[contains(@href, 'csIID=')]]"),
            "result rows",
            min_count=0,
        )

        results: list[DeferredValidation[SCAppDocket]] = []
        for row in rows:
            cells = row.query(XPath(".//td"), "result cells", min_count=0)
            if len(cells) < 8:
                continue

            court = COURT_NAME_TO_COURT.get(
                normalize_whitespace(cells[0].text_content())
            )
            if court is None:
                # Unknown court label — skip rather than emit a record
                # with a guessed court.
                continue

            links = cells[1].query(
                XPath(".//a[contains(@href, 'csIID=')]"),
                "case link",
                min_count=0,
                max_count=1,
            )
            if not links:
                continue
            href = links[0].get_attribute("href") or ""
            csiid_match = CSIID_RE.search(href)
            if not csiid_match:
                continue

            results.append(
                SCAppDocket.raw(
                    court=court,
                    docket_number=normalize_whitespace(
                        links[0].text_content()
                    ),
                    site_case_id=csiid_match.group(1),
                )
            )
        return results
