"""Colorado appellate courts scraper package.

This package provides scrapers for Colorado Supreme Court and Court of Appeals opinions
from the Colorado Judicial Branch website.

Scrapers:
- ColoradoScraper: Scrapes opinions from both courts

Courts covered:
- colo: Colorado Supreme Court
- coloctapp: Colorado Court of Appeals
"""

from .scraper import ColoradoScraper

__all__ = ["ColoradoScraper"]
