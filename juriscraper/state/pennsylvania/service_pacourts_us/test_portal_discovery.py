"""Offline tests for the cross-domain docket-number discovery path.

``dockets_by_filing_date`` borrows the sibling UJS portal's filing-date
search (``ujsportal.pacourts.us``) to learn which dockets exist in a window,
then fetches each case from this API — see ``CC_NOTES.md`` → "Cross-domain
docket discovery". The logic lives in the plain
``PaCourtsApiScraper._portal_results_to_requests`` generator precisely so it
can be driven here without a real ``Response`` (a ``@step`` cannot be).

The fixtures are synthetic pages built to the portal's grid contract (table
id, 19 columns, the search form) rather than a saved response — per-row
extraction itself is the sibling's ``ResultsGridParser``, which this path
reuses unchanged. No network access.

Run:
    uv run python -m pytest \
        juriscraper/state/pennsylvania/service_pacourts_us/test_portal_discovery.py
"""

from __future__ import annotations

from datetime import date

from jkent.common.lxml_page_element import LxmlPageElement
from lxml import html as lxml_html

from juriscraper.state.common.params import InferrableDateRange
from juriscraper.state.pennsylvania.ujsportal_pacourts_us.models import (
    RESULT_ROW_CAP,
)
from juriscraper.state.pennsylvania.ujsportal_pacourts_us.models import (
    SEARCH_URL as PORTAL_SEARCH_URL,
)

from .scraper import PaCourtsApiScraper

# Column layout of #caseSearchResultGrid: 19 cells, docket number at index 2,
# caption at 4, filing date at 6 (see the sibling's ResultsGridParser).
_TOTAL_COLUMNS = 19
_COL_DOCKET_NUMBER = 2
_COL_CASE_CAPTION = 4
_COL_FILING_DATE = 6


def _row(docket_number: str) -> str:
    cells = [""] * _TOTAL_COLUMNS
    cells[_COL_DOCKET_NUMBER] = docket_number
    cells[_COL_CASE_CAPTION] = f"Commonwealth v. {docket_number}"
    cells[_COL_FILING_DATE] = "03/04/2026"
    return "<tr>" + "".join(f"<td>{c}</td>" for c in cells) + "</tr>"


def _page(docket_numbers: list[str]) -> LxmlPageElement:
    """Build a portal results page carrying the search form plus these rows."""
    rows = "".join(_row(dn) for dn in docket_numbers)
    html = f"""
    <html><body>
      <form id="case-search-form-id" method="post" action="/CaseSearch">
        <input type="hidden" name="__RequestVerificationToken" value="tok"/>
        <input type="hidden" name="SearchBy" value="DocketNumber"/>
        <input type="hidden" name="AppellateCourtName" value=""/>
        <input type="hidden" name="FiledStartDate" value=""/>
        <input type="hidden" name="FiledEndDate" value=""/>
        <button type="submit" name="submit" value="Search">Search</button>
      </form>
      <table id="caseSearchResultGrid"><tbody>{rows}</tbody></table>
    </body></html>
    """
    return LxmlPageElement(lxml_html.fromstring(html), PORTAL_SEARCH_URL)


def _requests(docket_numbers: list[str], start: str, end: str) -> list:
    scraper = PaCourtsApiScraper()
    return list(
        scraper._portal_results_to_requests(
            _page(docket_numbers),
            {
                "court": "pa",
                "date_gte": start,
                "date_lte": end,
                "entry_point": "dockets_by_filing_date",
            },
        )
    )


# =========================================================================
# Fan-out: portal rows -> API case fetches
# =========================================================================


def test_rows_become_api_case_fetches() -> None:
    requests = _requests(
        ["1 MAP 2024", "3 EAL 2024"], "2026-03-01", "2026-03-31"
    )

    assert [r.request.url for r in requests] == [
        "https://services.pacourts.us/public/v1/cases/1%20MAP%202024",
        "https://services.pacourts.us/public/v1/cases/3%20EAL%202024",
    ]
    # Same dedup key the speculative walk uses, so a docket reached by both
    # paths is fetched once.
    assert [r.deduplication_key for r in requests] == [
        "case:1 MAP 2024",
        "case:3 EAL 2024",
    ]
    assert {r.accumulated_data["entry_point"] for r in requests} == {
        "dockets_by_filing_date"
    }


def test_court_comes_from_the_docket_type_prefix() -> None:
    # Searched court is "pa", but the prefix says Superior — the number is
    # authoritative, and parse_case still prefers what the API reports.
    (request,) = _requests(["12 EDA 2026"], "2026-03-01", "2026-03-31")
    assert request.accumulated_data["court"] == "pasuperct"


def test_non_pacms_rows_are_skipped() -> None:
    requests = _requests(
        ["CP-51-CR-0000001-2026", "", "44 WM 2026"], "2026-03-01", "2026-03-31"
    )
    assert [r.accumulated_data["docket_number"] for r in requests] == [
        "44 WM 2026"
    ]


# =========================================================================
# The portal's 500-row cap
# =========================================================================


def _capped_rows() -> list[str]:
    return [f"{n} MAP 2026" for n in range(1, RESULT_ROW_CAP + 1)]


def test_cap_splits_the_window_instead_of_harvesting() -> None:
    requests = _requests(_capped_rows(), "2026-03-01", "2026-03-31")

    # No case fetches from a result set known to be truncated.
    assert all(r.request.url.endswith("/CaseSearch") for r in requests)
    assert [
        (r.accumulated_data["date_gte"], r.accumulated_data["date_lte"])
        for r in requests
    ] == [("2026-03-01", "2026-03-16"), ("2026-03-17", "2026-03-31")]
    # Halves carry the searched court through as the form filter.
    assert all(
        r.request.data["AppellateCourtName"] == "Supreme" for r in requests
    )
    assert all(
        r.request.data["SearchBy"] == "AppellateCourtName" for r in requests
    )


def test_single_day_at_the_cap_is_accepted_not_split() -> None:
    requests = _requests(_capped_rows(), "2026-03-04", "2026-03-04")
    assert len(requests) == RESULT_ROW_CAP
    assert all("/public/v1/cases/" in r.request.url for r in requests)


def test_under_the_cap_does_not_split() -> None:
    requests = _requests(["1 MAP 2026"], "2026-03-01", "2026-03-31")
    assert len(requests) == 1
    assert "/public/v1/cases/" in requests[0].request.url


# =========================================================================
# Entry point seeding
# =========================================================================


def test_entry_seeds_one_portal_search_per_supported_court() -> None:
    scraper = PaCourtsApiScraper()
    date_range = InferrableDateRange(
        start=date(2026, 3, 1), end=date(2026, 3, 31)
    )
    requests = list(
        scraper.dockets_by_filing_date({"pa", "pasuperct", "nysd"}, date_range)
    )
    assert [r.request.url for r in requests] == [PORTAL_SEARCH_URL] * 2
    assert [r.accumulated_data["court"] for r in requests] == [
        "pa",
        "pasuperct",
    ]
