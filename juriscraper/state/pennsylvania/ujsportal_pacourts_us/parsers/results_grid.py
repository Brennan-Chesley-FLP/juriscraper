"""Parser for the Pennsylvania UJS Portal case-search results grid.

A search POST to ``/CaseSearch`` returns the same page with the results
rendered inline in ``#caseSearchResultGrid``. :class:`ResultsGridParser`
turns each data row into a :class:`PADocket`. The page does not carry the
target ``court``, the absolute docket-sheet URL, or the source URL — the
calling step resolves the relative docket-sheet href against the response
URL and stamps ``court`` / ``source_url`` / ``source_entry_point`` onto
each ``raw_data`` before emitting (see ``scraper.py``).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from jkent.common.deferred_validation import DeferredValidation
from jkent.common.parser import JKentParser
from jkent.data_types import XPath

from juriscraper.state.pennsylvania.ujsportal_pacourts_us.models import (
    PADocket,
)

from ._common import cell_text, parse_mdy

if TYPE_CHECKING:
    from jkent.common.page_element import PageElement

RESULTS_TABLE_ID = "caseSearchResultGrid"


class ResultsGridParser(JKentParser[PADocket]):
    """Parse every data row of the case-search results grid.

    Returns one :class:`PADocket` (deferred) per result row. The
    ``docket_sheet_url`` field holds the **relative** ``/Report/...`` href
    as found in the row; the step joins it to the response URL. ``court``,
    ``source_url``, and ``source_entry_point`` are stamped by the step.
    """

    # Column indices in #caseSearchResultGrid (0-based, includes the two
    # leading display:none sort-marker cells). Matches the headers list:
    # "Docket Number", "", "Docket Number", "Court Type", "Case Caption",
    # "Case Status", "Filing Date", "Primary Participant(s)",
    # "Date Of Birth(s)", "County", "Court Office", "OTN", "Complaint #",
    # "Incident #", "Event Type?", "Event Status", "Event Date",
    # "Event Location", "" (icons col).
    _COL_DOCKET_NUMBER: ClassVar[int] = 2
    _COL_COURT_TYPE: ClassVar[int] = 3
    _COL_CASE_CAPTION: ClassVar[int] = 4
    _COL_CASE_STATUS: ClassVar[int] = 5
    _COL_FILING_DATE: ClassVar[int] = 6
    _COL_PRIMARY_PARTICIPANTS: ClassVar[int] = 7
    _COL_COUNTY: ClassVar[int] = 9
    _COL_COURT_OFFICE: ClassVar[int] = 10
    _COL_OTN: ClassVar[int] = 11
    _COL_COMPLAINT_NUMBER: ClassVar[int] = 12
    _COL_INCIDENT_NUMBER: ClassVar[int] = 13
    _COL_EVENT_TYPE: ClassVar[int] = 14
    _COL_EVENT_STATUS: ClassVar[int] = 15
    _COL_EVENT_DATE: ClassVar[int] = 16
    _COL_EVENT_LOCATION: ClassVar[int] = 17

    def __call__(
        self, page: PageElement
    ) -> list[DeferredValidation[PADocket]]:
        rows = page.query(
            XPath(f"//table[@id='{RESULTS_TABLE_ID}']/tbody/tr"),
            "case-search result rows",
            min_count=0,
        )
        out: list[DeferredValidation[PADocket]] = []
        for row in rows:
            docket = self._row_to_docket(row)
            if docket is not None:
                out.append(docket)
        return out

    def _row_to_docket(
        self, row: PageElement
    ) -> DeferredValidation[PADocket] | None:
        """Build a deferred ``PADocket`` from a single result-grid row.

        Returns ``None`` if the docket-number cell is empty (the row is
        malformed). The ``docket_sheet_url`` is the relative href; the
        step joins it to the response URL.
        """
        docket_number = cell_text(row, self._COL_DOCKET_NUMBER)
        if not docket_number:
            return None

        # Pull the docket-sheet PDF link out of the icon cell. Each row
        # has two copies of the link (one for the desktop layout, one
        # nested in the hamburger panel for the small-screen carousel) —
        # we want exactly one.
        sheet_hrefs = row.query_strings(
            XPath(
                "(.//a[contains(@href, '/Report/PacDocketSheet')])[1]/@href"
            ),
            "docket sheet href",
            min_count=0,
            max_count=1,
        )
        docket_sheet_url = sheet_hrefs[0] if sheet_hrefs else None

        return PADocket.raw(
            docket_number=docket_number,
            case_name=cell_text(row, self._COL_CASE_CAPTION),
            case_status=cell_text(row, self._COL_CASE_STATUS) or None,
            date_filed=parse_mdy(cell_text(row, self._COL_FILING_DATE)),
            court_type=cell_text(row, self._COL_COURT_TYPE) or None,
            primary_participants=(
                cell_text(row, self._COL_PRIMARY_PARTICIPANTS) or None
            ),
            county=cell_text(row, self._COL_COUNTY) or None,
            court_office=cell_text(row, self._COL_COURT_OFFICE) or None,
            otn=cell_text(row, self._COL_OTN) or None,
            complaint_number=(
                cell_text(row, self._COL_COMPLAINT_NUMBER) or None
            ),
            incident_number=(
                cell_text(row, self._COL_INCIDENT_NUMBER) or None
            ),
            next_event_type=cell_text(row, self._COL_EVENT_TYPE) or None,
            next_event_status=cell_text(row, self._COL_EVENT_STATUS) or None,
            next_event_date=parse_mdy(cell_text(row, self._COL_EVENT_DATE)),
            next_event_location=(
                cell_text(row, self._COL_EVENT_LOCATION) or None
            ),
            docket_sheet_url=docket_sheet_url,
        )
