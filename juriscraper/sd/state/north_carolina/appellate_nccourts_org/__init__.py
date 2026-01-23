"""North Carolina Appellate Courts scraper package.

This package provides scraping functionality for:
- nc: North Carolina Supreme Court
- ncctapp: North Carolina Court of Appeals

Data source: https://appellate.nccourts.org/opinion-filings/
"""

from .scraper import NorthCarolinaScraper

__all__ = ["NorthCarolinaScraper"]
