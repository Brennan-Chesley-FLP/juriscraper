"""Parsers for the Pennsylvania appellate courts JSON API.

One module per response shape:

- :mod:`case_detail` — the full case document
  (``GET /public/v1/cases/{docket_number}``).
- :mod:`search_results` — the search envelope
  (``POST /public/v1/cases/search``).

Both consume decoded JSON rather than HTML, so neither subclasses
``JKentParser`` (which is bound to lxml/``PageElement``). They are plain
callables over the response mapping, which makes them directly
offline-testable against a saved response.
"""

from ._common import (
    clean_str,
    lines_of,
    name_of,
    name_parts,
    parse_date,
    parse_datetime,
    parse_time,
)
from .case_detail import CaseDetailParser, court_id_for, parse_docket_number
from .search_results import SEARCH_RESULT_CAP, SearchResultsParser

__all__ = [
    "SEARCH_RESULT_CAP",
    "CaseDetailParser",
    "SearchResultsParser",
    "clean_str",
    "court_id_for",
    "lines_of",
    "name_of",
    "name_parts",
    "parse_date",
    "parse_datetime",
    "parse_docket_number",
    "parse_time",
]
