"""Parser for a Massachusetts Appellate Courts calendar page.

The calendar pages (``/calendar/{fc,sj,ac,aj}``) list the *current
month's* oral-argument sittings. :class:`CalendarParser` groups the page
into one :class:`MaOralArgument` per (date, presiding panel) and returns
one ``DeferredValidation`` per session. ``court``, ``calendar_type``,
``source_url``, and ``source_entry_point`` are stamped by the calling
step.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from jkent.common.parser import JKentParser
from jkent.data_types import XPath

from juriscraper.state.massachusetts.ma_appellatecourts_org.models import (
    MaOralArgument,
    MaOralArgumentCase,
)

from ._common import clean, parse_session_when

if TYPE_CHECKING:
    from jkent.common.deferred_validation import DeferredValidation
    from jkent.common.page_element import PageElement


class CalendarParser(JKentParser[MaOralArgument]):
    """Parse one calendar page into one ``MaOralArgument`` per session.

    The page renders the date heading once (``calendar-results-date``)
    and then one or more presiding-panel blocks
    (``calendar-results-presiding`` plus the cases listed under the same
    panel inside the surrounding ``calendar-results-indent`` wrapper).
    Each presiding panel becomes one ``MaOralArgument``.
    """

    def __call__(
        self, page: PageElement
    ) -> list[DeferredValidation[MaOralArgument]]:
        sessions: list[DeferredValidation[MaOralArgument]] = []

        date_blocks = page.query(
            XPath("//div[contains(@class,'calendar-results-date')]"),
            "calendar date headers",
            min_count=0,
        )
        for date_block in date_blocks:
            date_text_lines = [
                t.strip()
                for t in date_block.query_strings(
                    XPath(".//text()"), "date lines", min_count=0
                )
                if t.strip()
            ]
            when = date_text_lines[0] if date_text_lines else ""
            location = date_text_lines[1] if len(date_text_lines) > 1 else None
            date_argued, session_time = parse_session_when(when)

            # Each presiding-panel block follows the date header inside
            # the same ``calendar-results-indent`` wrapper.
            presiding_blocks = date_block.query(
                XPath(
                    "./following-sibling::div"
                    "[contains(@class,'calendar-results-indent')]"
                    "[1]/div[contains(., 'Presiding')]"
                ),
                "presiding blocks",
                min_count=0,
            )
            for pres in presiding_blocks:
                presiding = clean(
                    next(
                        (
                            line[len("Presiding:") :].strip()
                            for line in (
                                t.strip()
                                for t in pres.query_strings(
                                    XPath(".//text()"),
                                    "presiding text",
                                    min_count=0,
                                )
                            )
                            if line.lower().startswith("presiding:")
                        ),
                        "",
                    )
                )

                cases = self._extract_cases(pres)

                sessions.append(
                    MaOralArgument.raw(
                        date_argued=date_argued,
                        session_time=session_time,
                        location=location,
                        presiding=presiding or None,
                        cases=cases,
                    )
                )

        return sessions

    @staticmethod
    def _extract_cases(pres: PageElement) -> list[MaOralArgumentCase]:
        """Pull the scheduled cases under one presiding-panel block."""
        cases: list[MaOralArgumentCase] = []
        case_blocks = pres.query(
            XPath(".//div[contains(@class,'calendar-results-case-block')]"),
            "case blocks",
            min_count=0,
        )
        for case_block in case_blocks:
            docket_links = case_block.query_strings(
                XPath(".//a[contains(@class,'docket-number-link')]/text()"),
                "docket id",
                min_count=0,
                max_count=1,
            )
            name_lines = case_block.query_strings(
                XPath(".//div[contains(@class,'col text-left')]//text()"),
                "case name",
                min_count=0,
            )
            docket_number = clean(docket_links[0]) if docket_links else None
            case_name = clean(" ".join(name_lines)) or ""
            if docket_number:
                cases.append(
                    MaOralArgumentCase(
                        docket_number=docket_number,
                        case_name=case_name,
                    )
                )
        return cases
