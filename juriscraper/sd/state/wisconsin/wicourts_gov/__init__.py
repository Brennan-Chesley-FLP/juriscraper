"""Wisconsin Appellate Courts Scraper.

Scrapes published and unpublished opinions from:
- Wisconsin Supreme Court (wis)
- Wisconsin Court of Appeals (wisctapp)
"""

from .scraper import WisconsinScraper

__all__ = ["WisconsinScraper"]
