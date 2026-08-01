"""Parser for the CaseNumber search-results page."""

from __future__ import annotations

from typing import TYPE_CHECKING

from jkent.common.parser import JKentParser
from jkent.data_types import XPath

from juriscraper.state.alaska.appellate_records_courts_alaska_gov.models import (
    AkDocket,
)

from ._common import (
    court_from_case_number,
    extract_q_token,
    parse_ak_date,
    safe_text,
    text_lines,
)

if TYPE_CHECKING:
    from jkent.common.deferred_validation import DeferredValidation
    from jkent.common.page_element import PageElement


class SearchResultsParser(JKentParser[AkDocket]):
    """Parse the full-match and partial-match search tables.

    Returns one ``DeferredValidation[AkDocket]`` per result row carrying
    the search-level fields (docket_number, court, case_name, date_filed,
    internal_case_id, case_type, case_status, source_url). All rows are
    present in the HTML — the CMS paginates client-side and caps at 1000
    results.
    """

    def __call__(
        self, page: PageElement
    ) -> list[DeferredValidation[AkDocket]]:
        results: list[DeferredValidation[AkDocket]] = []
        for table_id in ("tblFullSearch", "tblPartialSearch"):
            rows = page.query(
                XPath(f"//table[@id='{table_id}']//tbody/tr"),
                f"{table_id} rows",
                min_count=0,
            )
            for row in rows:
                cells = row.query(XPath(".//td"), "row cells", min_count=0)
                if len(cells) < 4:
                    continue

                # Cell 0: case number + link. Real result rows always carry
                # a ``search-link`` anchor; the "No Results Found" placeholder
                # row does not.
                links = cells[0].find_links(
                    XPath(".//a[@class='search-link']"),
                    "case link",
                    min_count=0,
                )
                if not links:
                    continue
                case_number_raw = (links[0].text or "").strip()
                case_url = links[0].url
                if not case_url or not case_number_raw:
                    continue

                docket_number = case_number_raw.replace("-", "").strip()

                # Cell 1: case name (inside a divCaseName).
                name_els = cells[1].query(
                    XPath(".//div[@class='divCaseName']"),
                    "case name div",
                    min_count=0,
                )
                case_name = safe_text(name_els[0]) if name_els else ""

                # Cell 4: trial court number(s), one per <br>-separated
                # line (a case can appeal more than one lower-court file).
                trial_court_numbers: list[str] = []
                if len(cells) > 4:
                    trial_court_numbers = text_lines(
                        cells[4], "trial court numbers"
                    )

                # Cell 5: date opened (hidden column, ISO formatted).
                date_filed = None
                if len(cells) > 5:
                    date_filed = parse_ak_date(safe_text(cells[5]))

                results.append(
                    AkDocket.raw(
                        docket_number=docket_number,
                        docket_number_raw=case_number_raw,
                        court=court_from_case_number(docket_number),
                        date_filed=date_filed,
                        case_name=case_name or docket_number,
                        internal_case_id=extract_q_token(case_url),
                        case_type=safe_text(cells[2]) or None,
                        case_status=safe_text(cells[3]) or None,
                        trial_court_numbers=trial_court_numbers,
                        source_url=case_url,
                    )
                )
        return results
