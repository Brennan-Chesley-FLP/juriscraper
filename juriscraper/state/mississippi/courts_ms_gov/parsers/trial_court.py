"""Parser for the Mississippi trial-court pane (``docket_type=lcinfo``).

Each trial-court ruling occupies a contiguous run of ``<td class="tccell">``
rows. The first two cells re-state the appellate docket number and the
caption; we skip those and group the rest into blocks of
``(court, case#, judge, ruling-date)``. Some cases consolidate rulings from
multiple trial courts, so the run can repeat once per ruling.

The appellate docket number and caption to skip are not on this fragment in
a labelled form, so they are passed to the constructor by the calling step
(from ``accumulated_data``).
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

from jkent.common.deferred_validation import DeferredValidation
from jkent.common.parser import JKentParser
from jkent.data_types import XPath

from juriscraper.state.mississippi.courts_ms_gov.models import (
    MsAppTrialCourt,
)

from ._common import RULING_DATE_RE, TRIAL_CASE_RE, parse_date, strip

if TYPE_CHECKING:
    from jkent.common.page_element import PageElement


class TrialCourtParser(JKentParser[MsAppTrialCourt]):
    """Parse the trial-court block(s) into ``MsAppTrialCourt`` records.

    Args:
        appellate_docket_number: the appellate docket number restated at the
            top of the pane (skipped). Optional — empty when unknown.
        case_name: the caption restated at the top of the pane (skipped).
    """

    def __init__(
        self, appellate_docket_number: str = "", case_name: str = ""
    ) -> None:
        self._appellate_no = (appellate_docket_number or "").upper()
        self._case_name = case_name or ""

    def __call__(
        self, page: PageElement
    ) -> list[DeferredValidation[MsAppTrialCourt]]:
        cells = page.query_strings(
            XPath("//td[@class='tccell']//text()"),
            "tccell texts",
            min_count=0,
        )
        cleaned = [strip(c) for c in cells if strip(c)]
        body = [
            c
            for c in cleaned
            if c.upper() != self._appellate_no and c != self._case_name
        ]

        trial_courts: list[DeferredValidation[MsAppTrialCourt]] = []
        current: dict[str, str | date | None] = {}

        def flush() -> None:
            if not current.get("court_name"):
                return
            trial_courts.append(
                MsAppTrialCourt.raw(
                    court_name=str(current["court_name"]),
                    trial_court_case_number=current.get(
                        "trial_court_case_number"
                    )
                    or None,
                    judge=current.get("judge") or None,
                    ruling_date=current.get("ruling_date") or None,
                )
            )
            current.clear()

        for line in body:
            if line.startswith("Trial Court Case #"):
                m = TRIAL_CASE_RE.match(line)
                if m:
                    current["trial_court_case_number"] = m.group(1).strip()
            elif line.startswith("The Honorable"):
                current["judge"] = line[len("The Honorable") :].strip()
            else:
                m = RULING_DATE_RE.search(line)
                if m:
                    current["ruling_date"] = parse_date(m.group(1))
                    flush()
                else:
                    # New court block — flush any pending one first.
                    if current:
                        flush()
                    current["court_name"] = line
        flush()
        return trial_courts
