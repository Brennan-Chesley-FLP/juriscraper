"""Maryland Appellate Courts Scraper.

Scrapes published opinions from:
- Supreme Court of Maryland (md)
- Appellate Court of Maryland (mdctspecapp)

From: https://www.courts.state.md.us/opinions/opinions
"""

from .scraper import MarylandScraper

__all__ = ["MarylandScraper"]
