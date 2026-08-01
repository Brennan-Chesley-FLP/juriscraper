"""Parser for the Participants & Attorneys page."""

from __future__ import annotations

from typing import TYPE_CHECKING

from jkent.common.parser import JKentParser
from jkent.data_types import XPath

from juriscraper.state.alaska.appellate_records_courts_alaska_gov.models import (
    AkParty,
)

from ._common import parse_attorney, safe_text

if TYPE_CHECKING:
    from jkent.common.deferred_validation import DeferredValidation
    from jkent.common.page_element import PageElement


class PartiesParser(JKentParser[AkParty]):
    """Parse the participants table into one ``AkParty`` per row.

    A participant's attorneys are rendered as separate ``<address>``
    blocks in the fourth cell. When nobody is on record the cell instead
    holds a bare span saying ``Unassigned`` or ``Self-represented
    litigant``.
    """

    def __call__(self, page: PageElement) -> list[DeferredValidation[AkParty]]:
        results: list[DeferredValidation[AkParty]] = []
        rows = page.query(
            XPath("//table[contains(@class, 'cms-party-table')]//tbody/tr"),
            "party rows",
            min_count=0,
        )
        for row in rows:
            cells = row.query(XPath(".//td"), "party cells", min_count=0)
            if len(cells) < 4:
                continue
            addr_els = cells[3].query(
                XPath(".//address"), "attorney address", min_count=0
            )
            status = cells[3].query_strings(
                XPath("./span/text()"),
                "representation status",
                min_count=0,
                max_count=1,
            )
            results.append(
                AkParty.raw(
                    name=safe_text(cells[0]),
                    role=safe_text(cells[1]) or None,
                    side=safe_text(cells[2]) or None,
                    attorneys=[parse_attorney(a) for a in addr_els],
                    representation_status=(
                        status[0].strip()
                        if status and status[0].strip()
                        else None
                    ),
                )
            )
        return results
