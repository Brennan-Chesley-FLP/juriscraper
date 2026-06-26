"""Alaska appellate courts scraper for appellate-records.courts.alaska.gov.

Supports the Alaska Supreme Court (``ak``) and Court of Appeals
(``akctapp``).

Data types:
- ``AkDocket``: a complete case docket aggregated across all case tabs.
- ``AkDocument``: an archived document, joined to its docket by
  ``docket_number``.
"""

from .models import AkDocket, AkDocument
from .scraper import AlaskaScraper

__all__ = [
    "AkDocket",
    "AkDocument",
    "AlaskaScraper",
]
