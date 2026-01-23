"""Virginia Courts scraper package.

This package contains scrapers for Virginia appellate court opinions:
- Supreme Court of Virginia (va)
- Court of Appeals of Virginia (vactapp)

Entry point: https://www.vacourts.gov/
"""

from .scraper import VirginiaScraper

__all__ = ["VirginiaScraper"]
