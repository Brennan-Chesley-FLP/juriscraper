"""Parser for the P-MACS case-search results listing.

The results page renders ``<tr class="OddRow|EvenRow">`` rows whose
first cell links to ``publicCaseMaintenance.do``. This parser pulls the
per-row fields the listing exposes (docket number, jurisdiction, filing
date, detail href); the pagination / 1000-row-cap handling stays in the
step because it reads the page-count sentinel off ``response.text``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from jkent.common.deferred_validation import DeferredValidation
from jkent.common.parser import JKentParser
from jkent.data_types import XPath

from juriscraper.state.minnesota.macsnc_courts_state_mn_us.models import (
    JURISDICTION_TO_COURT_ID,
    MnDocket,
)

from ._common import normalize_ws, parse_date

if TYPE_CHECKING:
    from jkent.common.page_element import PageElement


class SearchListingParser(JKentParser[MnDocket]):
    """Parse each result row of a ``publicCaseSearch.do`` listing page.

    Returns one ``DeferredValidation[MnDocket]`` per result row that maps
    to one of the two appellate courts. The ``raw_data`` carries the
    listing-readable fields plus two extra keys the step uses to build
    the detail fetch: ``detail_href`` and ``row_filing_date`` (ISO
    string). Rows whose jurisdiction isn't one of the appellate courts
    we model are dropped.
    """

    def __call__(
        self, page: PageElement
    ) -> list[DeferredValidation[MnDocket]]:
        rows = page.query(
            XPath(
                "//tr[contains(@class, 'OddRow') or contains(@class, 'EvenRow')]"
                "[.//a[contains(@href, 'publicCaseMaintenance.do')]]"
            ),
            "result table rows",
            min_count=0,
        )

        results: list[DeferredValidation[MnDocket]] = []
        for row in rows:
            cells = row.query(XPath("./td"), "result row cells", min_count=0)
            if len(cells) < 7:
                continue
            anchor_nodes = cells[0].query(
                XPath(".//a"), "case-number anchor", min_count=0, max_count=1
            )
            if not anchor_nodes:
                continue
            href = anchor_nodes[0].get_attribute("href")
            if not href:
                continue
            docket_number = normalize_ws(anchor_nodes[0].text_content())
            jurisdiction = normalize_ws(cells[1].text_content())
            filing_date = parse_date(normalize_ws(cells[6].text_content()))

            court = JURISDICTION_TO_COURT_ID.get(jurisdiction)
            if not court:
                # Skip rows whose jurisdiction isn't one of the two
                # appellate courts we model (e.g. Commitment Appeal Panel).
                continue

            results.append(
                MnDocket.raw(
                    docket_number=docket_number,
                    court=court,
                    jurisdiction=jurisdiction,
                    detail_href=href,
                    row_filing_date=(
                        filing_date.isoformat() if filing_date else None
                    ),
                )
            )
        return results
