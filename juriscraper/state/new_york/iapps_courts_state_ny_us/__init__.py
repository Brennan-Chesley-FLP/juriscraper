"""NYSCEF (New York State Courts Electronic Filing) appellate scraper."""

from .models import (
    NYSCEFAttorneyRep,
    NYSCEFCase,
    NYSCEFDocketEntry,
    NYSCEFDownloadedDocument,
    NYSCEFParty,
)
from .parsers import (
    CaseDetailParser,
    DocumentListParser,
    SearchResultsParser,
)
from .scraper import NYSCEFScraper

__all__ = [
    "NYSCEFAttorneyRep",
    "NYSCEFCase",
    "NYSCEFDocketEntry",
    "NYSCEFDownloadedDocument",
    "NYSCEFParty",
    "CaseDetailParser",
    "DocumentListParser",
    "SearchResultsParser",
    "NYSCEFScraper",
]
