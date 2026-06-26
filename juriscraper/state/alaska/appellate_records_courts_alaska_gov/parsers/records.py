"""Parser for the Record page."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from jkent.common.parser import JKentParser
from jkent.data_types import XPath

from juriscraper.state.alaska.appellate_records_courts_alaska_gov.models import (
    AkRecordEntry,
)

from ._common import parse_ak_date, safe_text

if TYPE_CHECKING:
    from jkent.common.deferred_validation import DeferredValidation
    from jkent.common.page_element import PageElement

_TRIAL_COURT_RE = re.compile(r"Trial Court Case\s+(\S+)")


class RecordParser(JKentParser[AkRecordEntry]):
    """Parse the Record page into one ``AkRecordEntry`` per row.

    Cases with multiple trial-court source files render an
    ``<h4>Trial Court Case <number></h4>`` heading before each
    ``cms-record-table``; each row is tagged with the trial-court case
    resolved from the nearest preceding heading.
    """

    def __call__(
        self, page: PageElement
    ) -> list[DeferredValidation[AkRecordEntry]]:
        results: list[DeferredValidation[AkRecordEntry]] = []
        tables = page.query(
            XPath("//table[contains(@class, 'cms-record-table')]"),
            "record tables",
            min_count=0,
        )
        for table in tables:
            tc_h4s = table.query(
                XPath(
                    "./preceding::h4[contains(text(), 'Trial Court Case')][1]"
                ),
                "preceding trial-court heading",
                min_count=0,
                max_count=1,
            )
            trial_court_case = None
            if tc_h4s:
                match = _TRIAL_COURT_RE.search(safe_text(tc_h4s[0]))
                if match:
                    trial_court_case = match.group(1).strip()

            rows = table.query(
                XPath(".//tbody/tr"), "record rows", min_count=0
            )
            for row in rows:
                cells = row.query(XPath(".//td"), "record cells", min_count=0)
                if len(cells) < 5:
                    continue
                results.append(
                    AkRecordEntry.raw(
                        trial_court_case=trial_court_case,
                        record_type=safe_text(cells[0]) or None,
                        status=safe_text(cells[1]) or None,
                        record_date=parse_ak_date(safe_text(cells[2])),
                        filed_or_issued_by=safe_text(cells[3]) or None,
                        role=safe_text(cells[4]) or None,
                    )
                )
        return results
