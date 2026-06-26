"""Parser for the Iowa case Summary tab (``AViewCase``).

The Summary page carries the case header scalars: short title (caption),
case type, status, trial-court judge, appellate judges, originating trial
court case id / county, and the reporter cite. These don't form a complete
``IowaDocket`` on their own — the docket is assembled across four tabs — so
:class:`CaseSummaryParser` returns a plain dict of the extracted fields,
which the step merges into ``accumulated_data``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from jkent.data_types import XPath

from ._common import clean_text

if TYPE_CHECKING:
    from jkent.common.page_element import PageElement


class CaseSummaryParser:
    """Extract the header scalars from the Summary tab into a dict."""

    def __call__(self, page: PageElement) -> dict:
        return {
            "case_name": self._case_name(page),
            **self._primary_cells(page),
            "appellate_judges": self._appellate_judges(page),
            **self._trial_court(page),
            "citation": self._citation(page),
        }

    @staticmethod
    def _case_name(page: PageElement) -> str:
        short_title_cells = page.query_strings(
            XPath(
                "//b[normalize-space()='Summary']/following::text()"
                "[contains(., 'Short Title:')][1]"
            ),
            "short title text",
            min_count=0,
            max_count=1,
        )
        if not short_title_cells:
            return ""
        raw = clean_text(short_title_cells[0])
        return raw.split(":", 1)[-1].strip()

    @staticmethod
    def _primary_cells(page: PageElement) -> dict:
        # The four primary cells (Docket No., Case Type, Status, Trial
        # Court Judge) sit in the row immediately after the header row.
        # Iterate <td> elements (not their text nodes) so empty cells keep
        # their position.
        primary_tds = page.query(
            XPath(
                "//tr[td/b/u[normalize-space()='Docket No.']]"
                "/following-sibling::tr[1]/td"
            ),
            "summary primary cells",
            min_count=0,
        )
        primary_text = [clean_text(td.text_content()) for td in primary_tds]
        case_type = primary_text[1] if len(primary_text) > 1 else None
        status = primary_text[2] if len(primary_text) > 2 else None
        assigned_to_str = primary_text[3] if len(primary_text) > 3 else None
        return {
            "case_type": case_type or None,
            "status": status or None,
            "assigned_to_str": assigned_to_str or None,
        }

    @staticmethod
    def _appellate_judges(page: PageElement) -> list[str]:
        judges_cells = page.query_strings(
            XPath(
                "//tr[td/b/u[normalize-space()='Appellate Judges/Justices']]"
                "/following-sibling::tr[1]/td/text()"
            ),
            "appellate judge cells",
            min_count=0,
        )
        appellate_judges: list[str] = []
        for raw in judges_cells:
            cleaned = clean_text(raw).strip('"')
            if cleaned and "No Judges Listed" not in cleaned:
                appellate_judges.append(cleaned)
        return appellate_judges

    @staticmethod
    def _trial_court(page: PageElement) -> dict:
        tc_cells = page.query_strings(
            XPath(
                "//tr[td/b/u[normalize-space()='Trial Court Case ID']]"
                "/following-sibling::tr[1]/td/text()"
            ),
            "trial court info cells",
            min_count=0,
        )
        tc_clean = [clean_text(c) for c in tc_cells if clean_text(c)]
        trial_court_case_id: str | None = None
        trial_court_county: str | None = None
        if tc_clean and "No Trial Court Cases Listed" not in tc_clean[0]:
            trial_court_case_id = tc_clean[0]
            if len(tc_clean) > 1:
                trial_court_county = tc_clean[1]
        return {
            "trial_court_case_id": trial_court_case_id,
            "trial_court_county": trial_court_county,
        }

    @staticmethod
    def _citation(page: PageElement) -> str | None:
        cite_cells = page.query_strings(
            XPath(
                "//tr[td/b/u[normalize-space()='Cite']]"
                "/following-sibling::tr[1]/td/text()"
            ),
            "cite cells",
            min_count=0,
        )
        for raw in cite_cells:
            cleaned = clean_text(raw).strip('"')
            if cleaned and "No Cite Listed" not in cleaned:
                return cleaned
        return None
