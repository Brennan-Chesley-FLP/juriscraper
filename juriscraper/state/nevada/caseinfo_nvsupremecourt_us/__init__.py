"""Nevada appellate courts scraper for caseinfo.nvsupremecourt.us.

Supports the Nevada Supreme Court (nev) and the Nevada Court of Appeals
(nevapp).

Data types:
- NvDocket: Complete case docket from original and combined case views.
- NvDocument: Archived docket-entry document, joinable via internal_id (csIID).
- NvUnavailableCase: A csIID whose page returns the "rights to view" error.
"""

from .models import NvDocket, NvDocument, NvUnavailableCase
from .scraper import NevadaScraper

__all__ = [
    "NevadaScraper",
    "NvDocket",
    "NvDocument",
    "NvUnavailableCase",
]
