"""Parser for the Briefs tab (``parse_briefs``)."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from jkent.common.deferred_validation import DeferredValidation
from jkent.common.parser import JKentParser
from jkent.data_types import XPath

from juriscraper.state.california.appellatecases_courtinfo_ca_gov.models import (
    CaAppBrief,
)

from ._common import clean_text, parse_date

if TYPE_CHECKING:
    from jkent.common.page_element import PageElement

# A ``Party:`` / ``Attorney:`` / ``Atty:`` credit label in the Notes cell.
# Tolerates the ``Atty::`` typo and requires the colon, so prose mentioning
# "the State Attorney General" or "Party of the first part" is not a label.
_NOTES_LABEL = re.compile(r"\b(Party|Atty|Attorney)\s*:+\s*", re.IGNORECASE)


class BriefsParser(JKentParser[CaAppBrief]):
    """Parse each row of the Briefs table.

    The column layout differs by court: the Supreme Court table is
    ``Brief | Date Filed | Party and Attorney | Notes``, while the Court of
    Appeal table inserts a ``Due Date`` column after ``Brief``. Cells are
    therefore mapped by header text, not fixed index — a fixed-index read
    against the CoA layout shifted the filing date into the party/attorney
    cell and dropped the Notes column entirely.

    ``Due Date`` holds the deadline for a brief that has not arrived yet; the
    site clears it on filing, so it is populated precisely on the rows whose
    ``Date Filed`` is blank (1,101 of 137,337 rows across the Third
    District). Without it those rows look like missing data rather than
    pending briefs.
    """

    def __call__(
        self, page: PageElement
    ) -> list[DeferredValidation[CaAppBrief]]:
        rows = page.query(
            XPath("//table//tbody//tr"), "brief rows", min_count=0
        )
        if not rows:
            return []
        headers = page.query(
            XPath("//table//th"), "brief header cells", min_count=2
        )
        col = {
            " ".join(h.text_content().split()).lower(): i
            for i, h in enumerate(headers)
        }
        if "date filed" not in col:
            # Header drift — re-query so the structural error carries the
            # selector and counts instead of silently mis-mapping columns.
            page.query(
                XPath('//table//th[normalize-space()="Date Filed"]'),
                "brief 'Date Filed' header",
                min_count=1,
            )

        def cell(
            cells: list[PageElement], name: str, default_idx: int | None = None
        ) -> str | None:
            idx = col.get(name, default_idx)
            if idx is None or idx >= len(cells):
                return None
            return cells[idx].text_content()

        def cell_element(
            cells: list[PageElement], name: str
        ) -> PageElement | None:
            idx = col.get(name)
            if idx is None or idx >= len(cells):
                return None
            return cells[idx]

        briefs: list[DeferredValidation[CaAppBrief]] = []
        for row in rows:
            cells = row.query(XPath("td"), "brief cells", min_count=0)
            if len(cells) < 2:
                continue
            credits, prose = self._parse_notes(cell_element(cells, "notes"))
            briefs.append(
                CaAppBrief.raw(
                    brief_type=(cell(cells, "brief", 0) or "").strip(),
                    date_filed=parse_date(cell(cells, "date filed")),
                    date_due=parse_date(cell(cells, "due date")),
                    filed_by=self._parse_filed_by(
                        cell_element(cells, "party and attorney")
                    ),
                    notes_filed_by=credits,
                    notes=clean_text("\n".join(prose)),
                )
            )
        return briefs

    @staticmethod
    def _cell_lines(cell: PageElement | None) -> list[str]:
        """Read a cell as the list of lines its ``<br>`` tags separate.

        ``text_content()`` drops ``<br>`` entirely, gluing adjacent lines into
        one run ("The PeopleAttorney: Eric L. Christoffersen"). Collecting the
        text nodes individually keeps the boundaries.
        """
        if cell is None:
            return []
        return [
            line
            for text in cell.query_strings(
                XPath(".//text()"), "cell lines", min_count=0
            )
            if (line := " ".join(text.split()))
        ]

    @classmethod
    def _parse_filed_by(cls, cell: PageElement | None) -> list[dict]:
        """Split the "Party and Attorney" cell into one dict per party.

        Reading the cell as ``<br>``-separated lines is what makes the
        multi-party cells representable: a single cell can name several
        parties, each with one or more attorneys.

        Grammar, one line at a time: ``"Attorney: <name>"`` adds an attorney
        to the party opened most recently, a bare ``"Pro Per"`` flags that
        party as self-represented, and any other ``"<Role>: <Name>"`` line
        opens a new party.
        """
        parties: list[dict] = []
        for line in cls._cell_lines(cell):
            if line.startswith("Attorney:"):
                if parties:
                    parties[-1]["attorneys"].append(
                        line.split(":", 1)[1].strip()
                    )
                continue
            if line == "Pro Per":
                if parties:
                    parties[-1]["pro_per"] = True
                continue
            role, sep, name = line.partition(":")
            parties.append(
                {
                    "name": (name if sep else line).strip(),
                    "role": role.strip() if sep else None,
                    "attorneys": [],
                    "pro_per": False,
                }
            )
        return parties

    @classmethod
    def _parse_notes(
        cls, cell: PageElement | None
    ) -> tuple[list[dict], list[str]]:
        """Split the Notes cell into credit records and leftover prose.

        Older cases repeat the filing credit here as ``Party:`` /
        ``Attorney:`` (or ``Atty:``) labels. Unlike the party cell those
        labels are *not* reliably one per line — a row can read
        ``Attorney: Tilner, Mitchell C. Party: Fire Insurance Exchange`` with
        no ``<br>`` between them — so each line is scanned for labels rather
        than matched by prefix. Text before the first label on a line, and any
        line with no label at all, is prose.

        The cell lists every ``Party:`` first and every ``Attorney:`` after,
        paired by position: C025527 credits four parties and repeats
        ``Somach, Stuart L.`` four times. So the two runs are collected
        separately and zipped, rather than attorneys being attached to the
        most recent party the way the party cell works. When the counts don't
        line up, one party (92% of rows) takes every attorney, and any
        attorney left without a party becomes a ``party``-less record instead
        of being dropped.
        """
        parties: list[str] = []
        attorneys: list[str] = []
        prose: list[str] = []

        for line in cls._cell_lines(cell):
            labels = list(_NOTES_LABEL.finditer(line))
            if not labels:
                prose.append(line)
                continue
            if leading := line[: labels[0].start()].strip():
                prose.append(leading)
            for i, match in enumerate(labels):
                end = (
                    labels[i + 1].start() if i + 1 < len(labels) else len(line)
                )
                if not (value := line[match.end() : end].strip()):
                    continue
                if match.group(1).lower() == "party":
                    parties.append(value)
                else:
                    attorneys.append(value)

        if not parties and not attorneys:
            return [], prose
        if len(parties) <= 1:
            # The overwhelmingly common shape: one party takes every
            # attorney, or attorneys with no party at all.
            return [
                {
                    "party": parties[0] if parties else None,
                    "attorneys": attorneys,
                }
            ], prose

        credits = [
            {"party": party, "attorneys": attorneys[i : i + 1]}
            for i, party in enumerate(parties)
        ]
        if extra := attorneys[len(parties) :]:
            credits.append({"party": None, "attorneys": extra})
        return credits, prose
