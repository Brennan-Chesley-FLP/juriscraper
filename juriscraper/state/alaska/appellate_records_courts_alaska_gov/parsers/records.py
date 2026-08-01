"""Parser for the Record page."""

from __future__ import annotations

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


class RecordParser(JKentParser[AkRecordEntry]):
    """Parse the Record page into one ``AkRecordEntry`` per row.

    Cases with multiple source files render a heading before each
    ``cms-record-table`` — ``<h4>{label} <span
    class="cms-record-number">{number}</span></h4>``, where ``label``
    names the kind of file (``Trial Court Case``, ``ABA File Number``,
    ``AWCB Case Number``). Each row is tagged with the label and number
    from the nearest preceding heading.
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
            headings = table.query(
                XPath(
                    "./preceding::h4"
                    "[span[contains(@class, 'cms-record-number')]][1]"
                ),
                "preceding source-file heading",
                min_count=0,
                max_count=1,
            )
            source_type = None
            trial_court_case = None
            if headings:
                labels = headings[0].query_strings(
                    XPath("./text()"),
                    "source-file label",
                    min_count=0,
                )
                numbers = headings[0].query_strings(
                    XPath(
                        ".//span[contains(@class, 'cms-record-number')]/text()"
                    ),
                    "source-file number",
                    min_count=0,
                    max_count=1,
                )
                source_type = " ".join(" ".join(labels).split()) or None
                trial_court_case = (
                    numbers[0].strip()
                    if numbers and numbers[0].strip()
                    else None
                )

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
                        source_type=source_type,
                        record_type=safe_text(cells[0]) or None,
                        status=safe_text(cells[1]) or None,
                        record_date=parse_ak_date(safe_text(cells[2])),
                        filed_or_issued_by=safe_text(cells[3]) or None,
                        role=safe_text(cells[4]) or None,
                    )
                )
        return results
