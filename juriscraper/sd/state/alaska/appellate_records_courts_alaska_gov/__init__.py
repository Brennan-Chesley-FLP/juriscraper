"""Alaska appellate courts scraper for appellate-records.courts.alaska.gov.

Supports Alaska Supreme Court (ak) and Court of Appeals (akctapp).

Data types:
- AkDocket: Complete case docket with all tabs
"""

from .models import AkDocket
from .scraper import AlaskaScraper

__all__ = [
    "AlaskaScraper",
    "AkDocket",
]
