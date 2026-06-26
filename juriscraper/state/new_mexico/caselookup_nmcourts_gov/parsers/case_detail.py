"""Parser for a New Mexico Case Lookup case-detail page.

One case-number search result renders the full register of actions in plain
HTML tables: a case-summary row, parties, hearings, register-of-actions
activity, and judge-assignment history. :class:`CaseDetailParser` extracts
every section into a single :class:`NmDocket`.

The page does not reliably carry the CourtListener court id, the source URL,
or the entry point — the calling step stamps those onto the returned
``raw_data`` before emitting (see ``scraper.py``). Each section renders as its
own ``<table>`` whose first ``<tr>`` is a single-cell heading row carrying the
section title (``Case Detail``, ``Parties to this Case``, …); we locate that
table by title and walk every row after the heading.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from jkent.common.parser import JKentParser
from jkent.data_types import XPath

from juriscraper.state.new_mexico.caselookup_nmcourts_gov.models import (
    NmDocket,
    NmDocketEntry,
    NmJudgeAssignment,
    NmParty,
)

from ._common import clean, parse_us_date, xpath_string

if TYPE_CHECKING:
    from jkent.common.deferred_validation import DeferredValidation
    from jkent.common.page_element import PageElement


class CaseDetailParser(JKentParser[NmDocket]):
    """Parse every section of a New Mexico case-detail page.

    Returns a single-element list with one ``NmDocket`` carrying the
    case-summary scalars and the nested party / entry / judge-assignment
    records. ``docket_number`` falls back to the case-summary cell here;
    ``court``, ``source_url``, and ``source_entry_point`` are stamped by the
    calling step.
    """

    def __call__(
        self, page: PageElement
    ) -> list[DeferredValidation[NmDocket]]:
        case_name = self._extract_case_name(page)
        docket_number, current_judge, date_filed, court_name = (
            self._extract_case_summary(page)
        )

        docket = NmDocket.raw(
            docket_number=docket_number or "",
            date_filed=date_filed,
            case_name=case_name or docket_number or "",
            current_judge=current_judge,
            court_name=court_name,
            entries=(
                self._extract_hearings(page)
                + self._extract_register_of_actions(page)
            ),
            parties=self._extract_parties(page),
            judge_assignments=self._extract_judge_assignments(page),
        )
        return [docket]

    # =====================================================================
    # Case summary
    # =====================================================================

    def _extract_case_name(self, page: PageElement) -> str | None:
        """Pull the case caption from the page heading."""
        headings = page.query(
            XPath("//h2//span[1]"),
            "case name heading",
            min_count=0,
            max_count=1,
        )
        if headings:
            return clean(headings[0].text_content())
        # Fall back to the bare h2 text.
        h2s = page.query(
            XPath("//h2"), "case name h2", min_count=0, max_count=1
        )
        if h2s:
            return clean(h2s[0].text_content())
        return None

    def _extract_case_summary(
        self, page: PageElement
    ) -> tuple[str | None, str | None, object, str | None]:
        """Parse the four-cell row beneath the ``Case Detail`` heading.

        Returns ``(docket_number, current_judge, date_filed, court_name)``.
        """
        rows = self._rows_under_section(page, "Case Detail")
        # Skip the column-header row; the data row sits below it.
        for row in rows:
            cells = row.query(
                XPath(".//td"), "case-summary cells", min_count=0
            )
            if len(cells) < 4:
                continue
            texts = [clean(c.text_content()) for c in cells]
            # The header row has labels; data row has actual values.
            if any(texts) and "Case Number" in texts[0]:
                continue
            return (
                texts[0] or None,
                texts[1] or None,
                parse_us_date(texts[2]),
                texts[3] or None,
            )
        return None, None, None, None

    # =====================================================================
    # Parties
    # =====================================================================

    def _extract_parties(self, page: PageElement) -> list[NmParty]:
        """Parse the ``Parties to this Case`` table."""
        out: list[NmParty] = []
        for row in self._rows_under_section(page, "Parties to this Case"):
            cells = row.query(XPath(".//td"), "party cells", min_count=0)
            if len(cells) < 4:
                continue
            texts = [clean(c.text_content()) for c in cells]
            if texts[0] == "Party Type":  # column-header row
                continue
            if not texts[0] and not texts[3]:
                continue
            out.append(
                NmParty(
                    party_type=texts[0] or "",
                    party_description=texts[1] or None,
                    party_number=texts[2] or None,
                    name=texts[3] or "",
                )
            )
        return out

    # =====================================================================
    # Hearings (folded into entries)
    # =====================================================================

    def _extract_hearings(self, page: PageElement) -> list[NmDocketEntry]:
        """Parse the ``Hearings for this Case`` table.

        Hearings are folded into ``entries`` with ``entry_kind='hearing'``
        per the project convention that future-calendar / scheduled-hearing
        items are docket-entries, not a parallel data type.
        """
        out: list[NmDocketEntry] = []
        for row in self._rows_under_section(page, "Hearings for this Case"):
            cells = row.query(XPath(".//td"), "hearing cells", min_count=0)
            if len(cells) < 6:
                continue
            texts = [clean(c.text_content()) for c in cells]
            if texts[0] == "Hearing Date":
                continue
            if not texts[0] and not texts[2]:
                continue
            out.append(
                NmDocketEntry(
                    entry_kind="hearing",
                    date_filed=parse_us_date(texts[0]),
                    description=texts[2] or "",
                    hearing_time=texts[1] or None,
                    hearing_judge=texts[3] or None,
                    court=texts[4] or None,
                    court_room=texts[5] or None,
                )
            )
        return out

    # =====================================================================
    # Register of actions (folded into entries)
    # =====================================================================

    def _extract_register_of_actions(
        self, page: PageElement
    ) -> list[NmDocketEntry]:
        """Parse the ``Register of Actions Activity`` table.

        Some rows are 2-cell sub-rows carrying free-text supplemental content
        (motion title, brief title, attorney name) — those are appended to
        the preceding event's ``notes`` rather than being modelled as their
        own entry.
        """
        out: list[NmDocketEntry] = []
        for row in self._rows_under_section(
            page, "Register of Actions Activity"
        ):
            cells = row.query(XPath(".//td"), "action cells", min_count=0)
            if not cells:
                continue
            texts = [clean(c.text_content()) for c in cells]

            # Column-header row is exactly the labels.
            if texts[0] == "Event Date":
                continue

            # Sub-row: typically 2 cells, the second carrying notes.
            if len(cells) <= 2:
                note_text = next((t for t in texts if t), "")
                if out and note_text:
                    out[-1] = _append_notes(out[-1], note_text)
                continue

            # Standard 6-column event row.
            if len(cells) < 6:
                continue
            out.append(
                NmDocketEntry(
                    entry_kind="action",
                    date_filed=parse_us_date(texts[0]),
                    description=texts[1] or "",
                    event_result=texts[2] or None,
                    party_type=texts[3] or None,
                    party_number=texts[4] or None,
                    amount=texts[5] or None,
                )
            )
        return out

    # =====================================================================
    # Judge assignment history
    # =====================================================================

    def _extract_judge_assignments(
        self, page: PageElement
    ) -> list[NmJudgeAssignment]:
        """Parse the ``Judge Assignment History`` table."""
        out: list[NmJudgeAssignment] = []
        for row in self._rows_under_section(page, "Judge Assignment History"):
            cells = row.query(
                XPath(".//td"), "judge-assignment cells", min_count=0
            )
            if len(cells) < 4:
                continue
            texts = [clean(c.text_content()) for c in cells]
            if texts[0] == "Assignment Date":
                continue
            if not any(texts):
                continue
            out.append(
                NmJudgeAssignment(
                    assignment_date=parse_us_date(texts[0]),
                    judge_name=texts[1] or None,
                    sequence_number=texts[2] or None,
                    assignment_event_description=texts[3] or None,
                )
            )
        return out

    # =====================================================================
    # Helpers
    # =====================================================================

    def _rows_under_section(
        self, page: PageElement, section_title: str
    ) -> list[PageElement]:
        """Return all data rows in the table whose first cell matches.

        The case-detail page renders each section as its own ``<table>``
        whose first ``<tr>`` is a single-cell heading row carrying the
        section title (``Case Detail``, ``Parties to this Case``, etc.).
        Locate that table, then return every row *after* the heading.
        """
        return page.query(
            XPath(
                f"//table[.//tr[1]/td[normalize-space(.)="
                f"{xpath_string(section_title)}]]"
                f"//tr[position() > 1]"
            ),
            f"{section_title} rows",
            min_count=0,
        )


def _append_notes(entry: NmDocketEntry, extra: str) -> NmDocketEntry:
    """Return a copy of ``entry`` with ``extra`` folded into ``notes``."""
    if not extra:
        return entry
    notes = f"{entry.notes} | {extra}" if entry.notes else extra
    return entry.model_copy(update={"notes": notes})
