"""Parser for the Iowa Docket / Register of Actions tab (``AViewDocket``).

Each event sits in a ``<tr>`` whose first comment is ``<!-- Event ID #N -->``;
an optional follow-on ``<tr>`` holds the ``Comments:`` text. Cell order is
``[date_filed, date_served, event, filed_by, due_date]``.
:class:`DocketEntriesParser` returns one :class:`IowaDocketEntry` per event
row.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from jkent.common.deferred_validation import DeferredValidation
from jkent.common.parser import JKentParser
from jkent.data_types import XPath

from juriscraper.state.iowa.iowacourts_state_ia_us.models import (
    IowaDocketEntry,
)

from ._common import clean_text, parse_date

if TYPE_CHECKING:
    from jkent.common.page_element import PageElement


class DocketEntriesParser(JKentParser[IowaDocketEntry]):
    """Walk the Register of Actions, one ``IowaDocketEntry`` per event."""

    def __call__(
        self, page: PageElement
    ) -> list[DeferredValidation[IowaDocketEntry]]:
        event_rows = page.query(
            XPath("//tr[comment()[contains(., 'Event ID #')]]"),
            "docket event rows",
            min_count=0,
        )

        entries: list[DeferredValidation[IowaDocketEntry]] = []
        for row in event_rows:
            # <td> in row order; preserves empty cells (Date Served and
            # Due Date are frequently blank).
            tds = row.query(XPath("./td"), "event row cells", min_count=0)
            cells = [clean_text(td.text_content()) for td in tds]
            if not cells or len(cells) < 3:
                continue

            # Pull the event id from the leading <!-- Event ID #N --> comment
            # by searching the row's raw HTML — XPath string-coercion of a
            # comment node is unreliable across lxml versions.
            event_id: str | None = None
            m = re.search(r"Event ID #(\d+)", row.inner_html())
            if m:
                event_id = m.group(1)

            event_text = cells[2] if len(cells) > 2 else ""
            filed_by = cells[3] if len(cells) > 3 else None

            # Comments row is the next sibling <tr> when present.
            notes: str | None = None
            comment_texts = row.query_strings(
                XPath(
                    "following-sibling::tr[1]"
                    "[.//i[normalize-space()='Comments:']]//td//text()"
                ),
                "comments cell text",
                min_count=0,
            )
            if comment_texts:
                blob = clean_text(" ".join(comment_texts))
                blob = re.sub(r"^Comments:\s*", "", blob)
                notes = blob or None

            entries.append(
                IowaDocketEntry.raw(
                    date_filed=parse_date(cells[0]),
                    date_served=parse_date(cells[1])
                    if len(cells) > 1
                    else None,
                    event=event_text,
                    filed_by=filed_by or None,
                    due_date=parse_date(cells[4]) if len(cells) > 4 else None,
                    notes=notes,
                    event_id=event_id,
                )
            )
        return entries
