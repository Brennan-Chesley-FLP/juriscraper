"""Washington Appellate Courts scraper (acdocportal.courts.wa.gov).

Supports Washington Supreme Court (wash) and Washington Court of Appeals
(washctapp).

Data types:
- WaDocket: A docket with all public documents for a given case number.
- WaDownloadedDocument: Per-file archive record joined by (court_id,
  docket_id, document_id).
"""

from .models import COURT_IDS, WaDocket, WaDocketEntry, WaDownloadedDocument
from .scraper import WashingtonAcdocPortalScraper

__all__ = [
    "COURT_IDS",
    "WaDocket",
    "WaDocketEntry",
    "WaDownloadedDocument",
    "WashingtonAcdocPortalScraper",
]
