"""NYSCEF (iapps.courts.state.ny.us) page parsers."""

from .case_detail import CaseDetailParser
from .document_list import DocumentListParser
from .search_results import SearchResultsParser

__all__ = [
    "CaseDetailParser",
    "DocumentListParser",
    "SearchResultsParser",
]
