"""Page parsers for the Vermont Public Portal scraper.

The two HTML pages (Smart-Search results grid, Document Viewer landing)
are parsed here; the JSON Register-of-Actions endpoints are handled in
the scraper steps.
"""

from .document_viewer import extract_download_href
from .search_results import SearchResultsParser

__all__ = ["SearchResultsParser", "extract_download_href"]
