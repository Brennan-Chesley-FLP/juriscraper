"""New Mexico appellate courts scraper from NMOneSource.

Scrapes opinions from:
- New Mexico Supreme Court (nm)
- New Mexico Court of Appeals (nmctapp)

Data source: https://nmonesource.com/
"""

from .scraper import NMOneSourceScraper

__all__ = ["NMOneSourceScraper"]
