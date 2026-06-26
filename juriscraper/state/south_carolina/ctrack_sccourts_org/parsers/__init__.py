"""C-Track page parsers for the South Carolina appellate scraper."""

from .case_detail import CaseDetailParser
from .search_listing import SearchListingParser

__all__ = [
    "CaseDetailParser",
    "SearchListingParser",
]
