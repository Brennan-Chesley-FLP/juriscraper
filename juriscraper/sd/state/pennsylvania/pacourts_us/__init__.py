"""Pennsylvania Appellate Courts Scraper.

Scrapes opinions from Pennsylvania's three appellate courts:
- Supreme Court of Pennsylvania (pa)
- Superior Court of Pennsylvania (pasuperct)
- Commonwealth Court of Pennsylvania (pacommwct)

Uses RSS feeds from https://www.pacourts.us/Rss/Opinions/
"""

from .scraper import PennsylvaniaScraper

__all__ = ["PennsylvaniaScraper"]
