"""Parser for the Docket Entries table of a CourtConnect docket report."""

from __future__ import annotations

from typing import TYPE_CHECKING

from jkent.common.deferred_validation import DeferredValidation
from jkent.common.parser import JKentParser
from jkent.data_types import XPath

from juriscraper.state.delaware.courtconnect_courts_delaware_gov.models import (
    DeCourtConnectDocketEntry,
)

from ._common import (
    cell_lines,
    clean_text,
    parse_date,
    parse_time,
)

if TYPE_CHECKING:
    from jkent.common.page_element import PageElement

#: The docket table, identified by its last column header.
_DOCKET_TABLE = XPath('//table[.//th[normalize-space()="Monetary"]]')

#: Cells in an entry's summary row (Filing Date, Description, Name, Monetary).
_SUMMARY_ROW_CELLS = 4

#: The label the continuation row carries in its first cell.
_ENTRY_LABEL = "entry:"


class DocketEntriesParser(JKentParser[DeCourtConnectDocketEntry]):
    """Parse the Docket Entries table into one record per entry.

    Each entry spans three physical rows -- a four-cell summary row, a two-cell
    "Entry:" row holding the full text, and a one-cell spacer -- and, as in the
    parties table, the site leaves the summary row's ``<tr>`` unclosed so all
    three parse as siblings. The summary row opens an entry; an "Entry:" row
    attaches its text to the entry most recently opened.

    An entry without an "Entry:" row is normal (the first entry of some cases
    has none), as is a case whose whole table is replaced by "No docket entries
    found." -- both yield fewer records rather than an error.
    """

    def __call__(
        self, page: PageElement
    ) -> list[DeferredValidation[DeCourtConnectDocketEntry]]:
        tables = page.query(
            _DOCKET_TABLE, "docket entries table", min_count=0, max_count=1
        )
        if not tables:
            return []

        entries: list[DeferredValidation[DeCourtConnectDocketEntry]] = []
        pending: dict | None = None
        for row in tables[0].query(
            XPath("./tr | ./tbody/tr"), "docket entry rows", min_count=1
        ):
            cells = row.query(XPath("./td"), "docket entry cells", min_count=0)
            if len(cells) >= _SUMMARY_ROW_CELLS:
                if pending is not None:
                    entries.append(DeCourtConnectDocketEntry.raw(**pending))
                pending = self._summary_row(cells, len(entries))
            elif (
                len(cells) == 2
                and pending is not None
                and (clean_text(cells[0].text_content()) or "").lower()
                == _ENTRY_LABEL
            ):
                pending["entry_text"] = self._entry_text(cells[1])
        if pending is not None:
            entries.append(DeCourtConnectDocketEntry.raw(**pending))
        return entries

    @staticmethod
    def _summary_row(cells: list[PageElement], index: int) -> dict:
        """Read the four-cell row that opens an entry.

        The first cell holds the date and time separated by a ``<br>``; read
        whole it reads "30-SEP-202511:37 AM", so the lines are taken
        individually.
        """
        lines = cell_lines(cells[0])
        return {
            "date_filed": parse_date(lines[0] if lines else None),
            "time_filed": parse_time(lines[1] if len(lines) > 1 else None),
            "description": clean_text(cells[1].text_content()),
            "name": clean_text(cells[2].text_content()),
            "monetary": clean_text(cells[3].text_content()),
            "sequence_number": index,
            # Seeded so every record carries the key: an entry whose "Entry:"
            # row is absent is common, and a raw_data whose shape depends on
            # that would make each consumer probe for the key.
            "entry_text": None,
        }

    @staticmethod
    def _entry_text(cell: PageElement) -> str | None:
        """Read the "Entry:" cell, keeping its line structure.

        The text is pre-formatted by the court -- numbered lists, a trailing
        "DATE DOCKETED:" line, tab-aligned judgment amounts -- so the newlines
        are content. Trailing whitespace is stripped per line (the site pads
        lines out with long runs of spaces) but the breaks are kept.
        """
        text = cell.text_content()
        lines = [
            line.rstrip() for line in text.replace("\xa0", " ").split("\n")
        ]
        joined = "\n".join(lines).strip()
        return joined or None
