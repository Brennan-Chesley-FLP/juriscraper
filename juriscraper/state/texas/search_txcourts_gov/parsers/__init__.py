"""Page parsers for the Texas appellate-courts (TAMES) scraper."""

from .case_detail import CaseDetailParser
from .search_results import SearchResultRow, SearchResultsParser

__all__ = [
    "CaseDetailParser",
    "SearchResultRow",
    "SearchResultsParser",
]
