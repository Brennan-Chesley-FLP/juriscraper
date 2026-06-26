"""Parser for a Georgia Court of Appeals case-detail page.

One ``results_one_record.php?docr_case_num=<N>`` page renders the case as a
sequence of ``<h3>``-headed HTML tables. :class:`CaseDetailParser` extracts
every section into a single :class:`GaCoaDocket`. The page does *not* carry the
``court`` id, the source URL, or the opinion-row judgment metadata — the step
stamps those onto the returned ``raw_data`` before emitting (see ``scraper.py``).
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
    none_unless_meaningful,
    parse_long_date,
)

if TYPE_CHECKING:
    from jkent.common.page_element import PageElement


class CaseDetailParser(JKentParser[GaCoaDocket]):
    """Parse every section of a Georgia CoA case-detail page.

    Returns a single-element list with one ``GaCoaDocket`` carrying the
    header scalars and the nested entry/attorney/trial-court/supreme-court
    records. ``court``, ``source_url``, ``source_entry_point``, and the
    opinion-row judgment metadata are stamped by the calling step.
    """

    def __call__(
        self, page: PageElement
    ) -> list[DeferredValidation[GaCoaDocket]]:
        coa = self._parse_kv_table(page, "Court of Appeals Information")
        trial = self._parse_kv_table(page, "Trial Court Information")

        # The detail page lists case number at the top of the COA block.
        docket_number = (coa.get("Case Number") or "").strip().upper()
        case_name = coa.get("Style") or docket_number
        case_type = docket_number[3:4] if len(docket_number) >= 4 else None

        docket = GaCoaDocket.raw(
            docket_number=docket_number,
            date_filed=parse_long_date(coa.get("Docket/Notice Date")),
            case_name=case_name,
            case_type=case_type,
            case_type_description=(
                CASE_TYPE_DESCRIPTIONS.get(case_type) if case_type else None
            ),
            case_status=coa.get("Status"),
            date_remittitur=parse_long_date(coa.get("Remittitur Date")),
            term=coa.get("Term"),
            supreme_court_transfer=none_unless_meaningful(
                coa.get("Supreme Court Transfer")
            ),
            calendar_date=none_unless_meaningful(coa.get("Calendar Date")),
            entries=self._parse_entries(page),
            attorneys=self._parse_attorneys(page),
            trial_court=self._build_trial_court(trial),
            supreme_court=self._build_supreme_court(page),
        )
        return [docket]

    # =====================================================================
    # Section helpers
    # =====================================================================

    @staticmethod
    def _parse_kv_table(page: PageElement, heading: str) -> dict[str, str]:
        """Extract a header→value mapping from the table after ``<h3>heading</h3>``.

        The detail page renders each section as an ``<h3>`` followed by a
        ``<table>`` of ``<tr><th>label</th><td>value</td></tr>`` rows.
        Returns ``{}`` if the section is absent.
        """
        rows = page.query(
            XPath(
                f"//h3[normalize-space()='{heading}']"
                "/following-sibling::table[1]//tr"
            ),
            f"{heading} rows",
            min_count=0,
        )
        out: dict[str, str] = {}
        for row in rows:
            ths = row.query(XPath(".//th"), "row th", min_count=0, max_count=1)
            tds = row.query(XPath(".//td"), "row td", min_count=0, max_count=1)
            if not ths or not tds:
                continue
            label = clean(ths[0].text_content())
            value = clean(tds[0].text_content())
            if label is None:
                continue
            out[label] = value or ""
        return out

    @staticmethod
    def _parse_entries(page: PageElement) -> list[GaCoaDocketEntry]:
        """Parse the "Filings" and "Court Initiated Actions" tables.

        Both render as alternating ``Filing Date`` / ``Filing`` row pairs
        (header in the first ``<td>``, value in the second). The parser pairs
        them up so each entry carries one date and one description.

        Quirk: the ``<h3>`` heading for both sections lives **inside** the
        table element (invalid but accepted by browsers), so the rows are
        selected via ``ancestor::table[1]`` from the heading rather than
        ``following-sibling::table``.
        """
        entries: list[GaCoaDocketEntry] = []
        for heading, court_initiated in (
            ("Filings, Motions, and Court Actions", False),
            ("Court Initiated Actions", True),
        ):
            rows = page.query(
                XPath(
                    f"//h3[normalize-space()='{heading}']"
                    "/ancestor::table[1]//tr"
                ),
                f"{heading} rows",
                min_count=0,
            )
            pending_date = None
            for row in rows:
                cells = row.query(XPath(".//td"), "row cells", min_count=0)
                if len(cells) < 2:
                    continue
                label = clean(cells[0].text_content())
                value = clean(cells[1].text_content())
                if label is None:
                    continue
                if label == "Filing Date":
                    pending_date = parse_long_date(value)
                elif label == "Filing":
                    description = value
                    if (
                        description
                        and description.lower() not in PLACEHOLDER_VALUES
                    ):
                        entries.append(
                            GaCoaDocketEntry(
                                date_filed=pending_date,
                                description=description,
                                court_initiated=court_initiated,
                            )
                        )
                    pending_date = None
                elif label.lower() in PLACEHOLDER_VALUES:
                    # The ``None / None`` placeholder row for empty sections.
                    continue
        return entries

    @staticmethod
    def _parse_attorneys(page: PageElement) -> list[GaCoaAttorney]:
        """Parse the back-to-back attorney tables under ``Attorney Information``.

        Each row carries a ``<th>`` side label (Appellant/Appellee/...) and a
        ``<td>`` name. Two tables are emitted (one per side) but we union them.
        """
        rows = page.query(
            XPath(
                "//h3[normalize-space()='Attorney Information']"
                "/following-sibling::table[position()<=2]//tr"
            ),
            "attorney rows",
            min_count=0,
        )
        attorneys: list[GaCoaAttorney] = []
        for row in rows:
            ths = row.query(XPath(".//th"), "row th", min_count=0, max_count=1)
            tds = row.query(XPath(".//td"), "row td", min_count=0, max_count=1)
            if not ths or not tds:
                continue
            side = clean(ths[0].text_content())
            name = clean(tds[0].text_content())
            if not name or name.lower() in PLACEHOLDER_VALUES:
                continue
            attorneys.append(GaCoaAttorney(name=name, side=side))
        return attorneys

    @staticmethod
    def _build_trial_court(
        rows: dict[str, str],
    ) -> GaCoaTrialCourtInfo | None:
        if not rows:
            return None
        case_number = clean(rows.get("Case Number"))
        if case_number and case_number.lower() in PLACEHOLDER_VALUES:
            case_number = None
        info = GaCoaTrialCourtInfo(
            case_number=case_number,
            clerk=none_unless_meaningful(rows.get("Clerk")),
            judge=none_unless_meaningful(rows.get("Judge")),
            county=none_unless_meaningful(rows.get("County")),
            court=none_unless_meaningful(rows.get("Court")),
            date_appealed_order=parse_long_date(rows.get("Appealed Order")),
            date_notice_of_appeal=parse_long_date(
                rows.get("Notice of Appeal")
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

    @staticmethod
    def _build_supreme_court(
        page: PageElement,
    ) -> GaCoaSupremeCourtInfo | None:
        """Parse the "Supreme Court Information" section if non-empty."""
        rows = page.query(
            XPath(
                "//h3[normalize-space()='Supreme Court Information']"
                "/following-sibling::table[1]//tr"
            ),
            "supreme court rows",
            min_count=0,
        )
        raw_rows: list[dict[str, str]] = []
        sc_case_number: str | None = None
        transfer_date = None
        for row in rows:
            cells = row.query(XPath(".//td|.//th"), "row cells", min_count=0)
            if len(cells) < 2:
                continue
            label = clean(cells[0].text_content())
            value = clean(cells[1].text_content())
            if not label or label.lower() in PLACEHOLDER_VALUES:
                continue
            if not value or value.lower() in PLACEHOLDER_VALUES:
                continue
            raw_rows.append({"label": label, "value": value})
            if label.lower() in {"case number", "sc case number"}:
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
