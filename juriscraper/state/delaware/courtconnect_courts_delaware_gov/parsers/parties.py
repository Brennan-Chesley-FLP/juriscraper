"""Parser for the Case Parties table of a CourtConnect docket report."""

from __future__ import annotations

from typing import TYPE_CHECKING

from jkent.common.deferred_validation import DeferredValidation
from jkent.common.parser import JKentParser
from jkent.data_types import XPath

from juriscraper.state.delaware.courtconnect_courts_delaware_gov.models import (
    DeCourtConnectParty,
)

from ._common import (
    cell_lines,
    clean_optional,
    clean_text,
    parse_date,
    parse_int,
)

if TYPE_CHECKING:
    from jkent.common.page_element import PageElement

#: The parties table, identified by its first column header. There is exactly
#: one such table on a docket report.
_PARTIES_TABLE = XPath('//table[.//th[normalize-space()="Seq #"]]')

#: Number of cells in a party's main row (Seq #, Assoc, Party End Date, Type,
#: ID, Name) and in its Address/Aliases continuation row.
_MAIN_ROW_CELLS = 6
_DETAIL_ROW_CELLS = 4


class PartiesParser(JKentParser[DeCourtConnectParty]):
    """Parse the Case Parties table into one record per party row.

    Each party occupies three physical rows: a six-cell main row, a four-cell
    Address/Aliases row, and a one-cell spacer. The site never closes the main
    row's ``<tr>``, so the three arrive as *siblings* rather than nested --
    which is why the detail row is matched by cell count and folded into the
    party opened by the preceding main row, instead of being looked for inside
    it.
    """

    def __call__(
        self, page: PageElement
    ) -> list[DeferredValidation[DeCourtConnectParty]]:
        tables = page.query(
            _PARTIES_TABLE, "case parties table", min_count=0, max_count=1
        )
        if not tables:
            # A case with no parties renders no table at all.
            return []

        parties: list[DeferredValidation[DeCourtConnectParty]] = []
        pending: dict | None = None
        for row in tables[0].query(
            XPath("./tr | ./tbody/tr"), "party rows", min_count=1
        ):
            cells = row.query(XPath("./td"), "party cells", min_count=0)
            if len(cells) >= _MAIN_ROW_CELLS:
                if pending is not None:
                    parties.append(DeCourtConnectParty.raw(**pending))
                pending = self._main_row(cells)
            elif len(cells) == _DETAIL_ROW_CELLS and pending is not None:
                pending.update(self._detail_row(cells))
        if pending is not None:
            parties.append(DeCourtConnectParty.raw(**pending))
        return parties

    @staticmethod
    def _main_row(cells: list[PageElement]) -> dict:
        """Read the six-cell row that opens a party."""
        return {
            "sequence_number": parse_int(cells[0].text_content()),
            "associated_sequence_number": parse_int(cells[1].text_content()),
            "date_terminated": parse_date(cells[2].text_content()),
            "party_type": clean_text(cells[3].text_content()),
            "id_code": clean_text(cells[4].text_content()),
            "name": clean_text(cells[5].text_content()),
        }

    @staticmethod
    def _detail_row(cells: list[PageElement]) -> dict:
        """Read the four-cell Address/Aliases continuation row.

        The address is a ``<br>``-separated block, so its lines are collected
        individually and rejoined with newlines; ``text_content()`` would glue
        "DONALD L. GOUGE JR LLC" to "800 N. KING STREET".
        """
        address_lines = [
            line for line in cell_lines(cells[1]) if clean_optional(line)
        ]
        alias_lines = [
            line for line in cell_lines(cells[3]) if clean_optional(line)
        ]
        return {
            "contact_raw": "\n".join(address_lines) or None,
            "aliases": alias_lines,
        }
