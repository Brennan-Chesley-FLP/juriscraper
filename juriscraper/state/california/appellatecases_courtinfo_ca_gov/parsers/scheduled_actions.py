"""Parser for the Scheduled Actions tab (``parse_scheduled_actions``).

Court of Appeal only -- Supreme Court case pages carry six tabs and no
``a#actionTab``. The heading reads "Future Scheduled Actions".

Despite the name, the tab is a list of **deadlines**, not of calendared
events. Its columns are ``Description | Due Date | Notes``::

    Record on appeal filed.                    10/05/2026
    Filing fee.                                            No filing fee paid.07/23/2026
    Civil case information statement filed.                07/23/2026
    Appeal dismissed per rule 8.100(c).        08/10/2026
    Something is due; see note.                08/17/2026  check status dismissal order

So the date is a ``date_due``, never a ``date_filed``: a row saying
"Appellant's opening brief." with 06/17/2026 beside it means the brief is
*owed* by then, and filing it there would assert the opposite. ``Due Date``
is blank on plenty of rows (the site puts the detail in Notes instead), so a
row with neither date is normal here.

Rows become ``CaAppScheduledAction``, kept out of ``CaAppDocket.entries``:
they have not happened, so putting them in the CourtListener ``DocketEntry``
stream would assert filings that do not exist -- and they would duplicate,
since their descriptions are the anticipated forms of entries the Register of
Actions gets later.

Verified against G067160 (4th/Div 3, six rows), B353492 (2nd, one row),
H000102 (6th, empty), and D088532 (4th/Div 1, empty) -- the column set was
identical on all of them.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from jkent.common.deferred_validation import DeferredValidation
from jkent.common.parser import JKentParser
from jkent.data_types import XPath

from juriscraper.state.california.appellatecases_courtinfo_ca_gov.models import (
    CaAppScheduledAction,
)

from ._common import clean_text, parse_date

if TYPE_CHECKING:
    from jkent.common.page_element import PageElement

#: Column header -> position, when the headers are readable. Falling back to
#: fixed indices only covers a table that has lost its ``<thead>`` entirely.
_FALLBACK_COLUMNS = {"description": 0, "due date": 1, "notes": 2}


class ScheduledActionsParser(JKentParser[CaAppScheduledAction]):
    """Parse the Future Scheduled Actions table into outstanding deadlines."""

    def __call__(
        self, page: PageElement
    ) -> list[DeferredValidation[CaAppScheduledAction]]:
        rows = page.query(
            XPath("//table//tbody//tr"), "scheduled action rows", min_count=0
        )
        if not rows:
            # The tab prints "No information found." when the case has no
            # outstanding deadlines, which is the common case: it was empty on
            # two of the four cases surveyed.
            return []

        columns = self._columns(page)

        actions: list[DeferredValidation[CaAppScheduledAction]] = []
        for row in rows:
            cells = row.query(
                XPath("td"), "scheduled action cells", min_count=0
            )
            if not cells:
                continue

            def cell(
                name: str, cells: list[PageElement] = cells
            ) -> str | None:
                index = columns.get(name)
                if index is None or index >= len(cells):
                    return None
                return cells[index].text_content()

            actions.append(
                CaAppScheduledAction.raw(
                    description=(cell("description") or "").strip(),
                    date_due=parse_date(cell("due date")),
                    notes=clean_text(cell("notes")),
                )
            )
        return actions

    @staticmethod
    def _columns(page: PageElement) -> dict[str, int]:
        """Map ``{header text: column index}``, by header rather than position.

        Same reasoning as ``BriefsParser``: this site varies its column sets
        between tabs and courts, so a fixed-index read is what silently shifts
        a date into the wrong field. When ``Due Date`` is missing from the
        headers the selector is re-queried, so header drift surfaces as a
        structural error carrying the selector and counts rather than as a
        table of entries with no dates.
        """
        columns = {
            " ".join(header.text_content().split()).lower(): i
            for i, header in enumerate(
                page.query(
                    XPath("//table//th"),
                    "scheduled action header cells",
                    min_count=0,
                )
            )
        }
        if "due date" not in columns:
            page.query(
                XPath('//table//th[normalize-space()="Due Date"]'),
                "scheduled action 'Due Date' header",
                min_count=1,
            )
            return _FALLBACK_COLUMNS
        return columns
