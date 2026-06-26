"""Parser for the DC C-Track case-search results listing."""

from __future__ import annotations

from typing import TYPE_CHECKING

from jkent.common.deferred_validation import DeferredValidation
from jkent.common.parser import JKentParser
from jkent.data_types import XPath

from juriscraper.state.district_of_columbia.efile_dcappeals_gov.models import (  # noqa: E501
    DCAppDocket,
)

from ._common import CSIID_RE, normalize_whitespace

if TYPE_CHECKING:
    from jkent.common.page_element import PageElement


class SearchListingParser(JKentParser[DCAppDocket]):
    """Parse each result row of a ``caseSearch.do`` listing page.

    Returns one ``DeferredValidation[DCAppDocket]`` per result row,
    carrying ``docket_number`` and ``site_case_id`` (the C-Track
    ``csIID``). The step turns each into a case-detail fetch; the full
    record is built by :class:`CaseDetailParser`.
    """

    def __call__(
        self, page: PageElement
    ) -> list[DeferredValidation[DCAppDocket]]:
        # Match leaf <tr> rows where one of the TDs has a child anchor
        # whose href carries csIID — keeps ancestor table rows out.
        rows = page.query(
            XPath("//tr[./td/a[contains(@href, 'csIID=')]]"),
            "result rows",
            min_count=0,
        )

        results: list[DeferredValidation[DCAppDocket]] = []
        for row in rows:
            cells = row.query(XPath(".//td"), "result cells", min_count=0)
            if len(cells) < 7:
                continue
            links = cells[0].query(
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
                DCAppDocket.raw(
                    court="dc",
                    docket_number=normalize_whitespace(
                        links[0].text_content()
                    ),
                    site_case_id=csiid_match.group(1),
                )
            )
        return results
