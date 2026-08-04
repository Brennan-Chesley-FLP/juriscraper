"""Parser for a Georgia Court of Appeals case-detail page.

One ``results_one_record.php?docr_case_num=<N>`` page renders the case as a
sequence of ``<h3>``-headed HTML tables. :class:`CaseDetailParser` extracts
every section into a single :class:`GaCoaDocket`. The page does *not* carry the
``court`` id or the source URL — the step stamps those onto the returned
``raw_data`` before emitting (see ``scraper.py``).

Section markup, as observed across a 396-page corpus (``ga/coa`` run db):

- Every row is exactly two cells. The **label cell is sometimes ``<th>`` and
  sometimes ``<td>``** — the ``Opinion/Order`` row of the COA block and every
  row of the filings block use ``<td>`` for both cells — so rows are read
  positionally (first cell = label, second = value), never by tag.
- Most sections are ``<h3>`` *followed by* their table, but the filings
  section's ``<h3>`` sits **inside** its table (invalid HTML, kept as-is by
  lxml), and the attorney / court-initiated sections spread their rows over
  **several** sibling tables. ``_section_rows_xpath`` covers all three shapes.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from jkent.common.deferred_validation import DeferredValidation
from jkent.common.parser import JKentParser
from jkent.data_types import XPath

from juriscraper.state.georgia.gaappeals_gov.models import (
    CASE_TYPE_DESCRIPTIONS,
    GaCoaAttorney,
    GaCoaDocket,
    GaCoaDocketEntry,
    GaCoaSupremeCourtInfo,
    GaCoaTrialCourtInfo,
)

from ._common import (
    PLACEHOLDER_VALUES,
    clean,
    extract_filing_id,
    none_unless_meaningful,
    parse_judgment,
    parse_long_date,
)

if TYPE_CHECKING:
    from jkent.common.page_element import PageElement

# Labels whose value is the Supreme Court case number, lowercased.
_SC_CASE_NUMBER_LABELS = {
    "case number",
    "sc case number",
    "certiorari number",
}


def _section_rows_xpath(heading: str) -> str:
    """Every ``<tr>`` belonging to the ``<h3>heading</h3>`` section.

    Two shapes are unioned because the site uses both:

    1. ``ancestor::table[1]`` — the heading is nested *inside* its own table
       ("Filings, Motions, and Court Actions").
    2. sibling tables whose nearest preceding ``<h3>`` sibling is this heading,
       excluding tables that carry a heading of their own (that would be case
       1 leaking into the *previous* section). This picks up **all** of a
       section's tables, not just the first — the attorney block always uses
       two, and "Court Initiated Actions" uses one table per action.
    """
    return (
        f"//h3[normalize-space()='{heading}']/ancestor::table[1]//tr"
        f" | //table[preceding-sibling::h3[1][normalize-space()='{heading}']]"
        "[not(.//h3)]//tr"
    )


class CaseDetailParser(JKentParser[GaCoaDocket]):
    """Parse every section of a Georgia CoA case-detail page.

    Returns a single-element list with one ``GaCoaDocket`` carrying the
    header scalars and the nested entry/attorney/trial-court/supreme-court
    records. ``court``, ``source_url``, and ``source_entry_point`` are stamped
    by the calling step.
    """

    def __call__(
        self, page: PageElement
    ) -> list[DeferredValidation[GaCoaDocket]]:
        coa = self._section_pairs(page, "Court of Appeals Information")
        trial = self._section_pairs(page, "Trial Court Information")

        # The detail page lists case number at the top of the COA block.
        docket_number = (self._text(coa, "Case Number") or "").strip().upper()
        case_name = self._text(coa, "Style") or docket_number
        case_type = docket_number[3:4] if len(docket_number) >= 4 else None

        # 'DISMISSED (July 7, 2026)' — ruling and disposition date in one cell.
        judgment_ruling, date_judgment = parse_judgment(
            self._text(coa, "COA Judgment/Ruling")
        )
        opinion_url = self._link(coa, "Opinion/Order")

        docket = GaCoaDocket.raw(
            docket_number=docket_number,
            date_filed=parse_long_date(self._text(coa, "Docket/Notice Date")),
            case_name=case_name,
            case_type=case_type,
            case_type_description=(
                CASE_TYPE_DESCRIPTIONS.get(case_type) if case_type else None
            ),
            case_status=self._text(coa, "Status"),
            date_remittitur=parse_long_date(
                self._text(coa, "Remittitur Date")
            ),
            term=self._text(coa, "Term"),
            supreme_court_transfer=none_unless_meaningful(
                self._text(coa, "Supreme Court Transfer")
            ),
            calendar_date=none_unless_meaningful(
                self._text(coa, "Calendar Date")
            ),
            date_judgment=date_judgment,
            judgment_ruling=judgment_ruling,
            opinion_url=opinion_url,
            opinion_filing_id=(
                extract_filing_id(opinion_url) if opinion_url else None
            ),
            entries=self._parse_entries(page),
            attorneys=self._parse_attorneys(page),
            trial_court=self._build_trial_court(trial),
            supreme_court=self._build_supreme_court(page),
        )
        return [docket]

    # =====================================================================
    # Row access
    # =====================================================================

    @staticmethod
    def _section_pairs(
        page: PageElement, heading: str
    ) -> list[tuple[str, PageElement]]:
        """Label → value-cell pairs for one section, in document order.

        Duplicate labels are **kept** (the trial-court block repeats
        ``Case Number`` once per companion case), so callers pick with
        :meth:`_text` / :meth:`_texts` rather than dict lookup. Rows that are
        not two cells wide are skipped as spacers; a *wider* row raises, since
        that means the site added a column.
        """
        rows = page.query(
            XPath(_section_rows_xpath(heading)),
            f"{heading} rows",
            min_count=0,
        )
        pairs: list[tuple[str, PageElement]] = []
        for row in rows:
            cells = row.query(
                XPath("./th|./td"),
                f"{heading} row cells",
                min_count=0,
                max_count=2,
            )
            if len(cells) != 2:
                continue
            label = clean(cells[0].text_content())
            if label is None:
                continue
            pairs.append((label, cells[1]))
        return pairs

    @staticmethod
    def _texts(pairs: list[tuple[str, PageElement]], label: str) -> list[str]:
        """Every value carrying ``label``, cleaned, in document order."""
        return [
            clean(cell.text_content()) or ""
            for row_label, cell in pairs
            if row_label == label
        ]

    @classmethod
    def _text(
        cls, pairs: list[tuple[str, PageElement]], label: str
    ) -> str | None:
        """The first value carrying ``label``, or ``None`` if absent."""
        values = cls._texts(pairs, label)
        return values[0] if values else None

    @staticmethod
    def _link(pairs: list[tuple[str, PageElement]], label: str) -> str | None:
        """The ``href`` of the single link in the ``label`` row, if any."""
        for row_label, cell in pairs:
            if row_label != label:
                continue
            links = cell.query(
                XPath(".//a[@href]"), f"{label} link", min_count=0, max_count=1
            )
            if links:
                return links[0].get_attribute("href")
        return None

    # =====================================================================
    # Section helpers
    # =====================================================================

    @classmethod
    def _parse_entries(cls, page: PageElement) -> list[GaCoaDocketEntry]:
        """Parse the "Filings" and "Court Initiated Actions" tables.

        Both sections render as ``<kind> Date`` / ``<kind>`` row pairs, where
        the kind is ``Filing``, ``Motion``, or ``Court Action`` — a single
        filings table interleaves all three (a motion row is typically
        followed by the court action ruling on it). The kind is read off the
        label rather than matched against a fixed list, so a kind the site
        adds later is captured instead of silently dropped.
        """
        entries: list[GaCoaDocketEntry] = []
        for heading, court_initiated in (
            ("Filings, Motions, and Court Actions", False),
            ("Court Initiated Actions", True),
        ):
            # Date row precedes its description row; hold it per kind so the
            # interleaved Motion/Court Action pairs don't cross-contaminate.
            pending: dict[str, object] = {}
            for label, cell in cls._section_pairs(page, heading):
                value = clean(cell.text_content())
                if label.lower() in PLACEHOLDER_VALUES:
                    # The ``None / None`` placeholder row for empty sections.
                    continue
                if label.endswith(" Date"):
                    pending[label[: -len(" Date")]] = parse_long_date(value)
                    continue
                if not value or value.lower() in PLACEHOLDER_VALUES:
                    continue
                entries.append(
                    GaCoaDocketEntry(
                        date_filed=pending.pop(label, None),  # type: ignore[arg-type]
                        description=value,
                        entry_type=label,
                        court_initiated=(
                            court_initiated or label == "Court Action"
                        ),
                    )
                )
        return entries

    @classmethod
    def _parse_attorneys(cls, page: PageElement) -> list[GaCoaAttorney]:
        """Parse the back-to-back attorney tables under ``Attorney Information``.

        Each row carries a side label (Appellant/Appellee/...) and a name. The
        side is repeated per attorney, so one side may span several rows.
        """
        attorneys: list[GaCoaAttorney] = []
        for side, cell in cls._section_pairs(page, "Attorney Information"):
            name = clean(cell.text_content())
            if not name or name.lower() in PLACEHOLDER_VALUES:
                continue
            attorneys.append(GaCoaAttorney(name=name, side=side))
        return attorneys

    @classmethod
    def _build_trial_court(
        cls, pairs: list[tuple[str, PageElement]]
    ) -> GaCoaTrialCourtInfo | None:
        if not pairs:
            return None
        case_numbers = [
            number
            for number in cls._texts(pairs, "Case Number")
            if number and number.lower() not in PLACEHOLDER_VALUES
        ]
        info = GaCoaTrialCourtInfo(
            case_number=case_numbers[0] if case_numbers else None,
            additional_case_numbers=case_numbers[1:],
            clerk=none_unless_meaningful(cls._text(pairs, "Clerk")),
            judge=none_unless_meaningful(cls._text(pairs, "Judge")),
            county=none_unless_meaningful(cls._text(pairs, "County")),
            court=none_unless_meaningful(cls._text(pairs, "Court")),
            date_appealed_order=parse_long_date(
                cls._text(pairs, "Appealed Order")
            ),
            date_notice_of_appeal=parse_long_date(
                cls._text(pairs, "Notice of Appeal")
            ),
        )
        if all(
            getattr(info, f) is None
            for f in (
                "case_number",
                "clerk",
                "judge",
                "county",
                "court",
                "date_appealed_order",
                "date_notice_of_appeal",
            )
        ):
            return None
        return info

    @classmethod
    def _build_supreme_court(
        cls, page: PageElement
    ) -> GaCoaSupremeCourtInfo | None:
        """Parse the "Supreme Court Information" section if non-empty."""
        raw_rows: list[dict[str, str]] = []
        sc_case_number: str | None = None
        transfer_date = None
        for label, cell in cls._section_pairs(
            page, "Supreme Court Information"
        ):
            value = clean(cell.text_content())
            if label.lower() in PLACEHOLDER_VALUES:
                continue
            if not value or value.lower() in PLACEHOLDER_VALUES:
                continue
            raw_rows.append({"label": label, "value": value})
            if label.lower() in _SC_CASE_NUMBER_LABELS:
                sc_case_number = value
            elif "transfer" in label.lower() and "date" in label.lower():
                transfer_date = parse_long_date(value)
        if not raw_rows:
            return None
        return GaCoaSupremeCourtInfo(
            sc_case_number=sc_case_number,
            transfer_date=transfer_date,
            rows=raw_rows,
        )
