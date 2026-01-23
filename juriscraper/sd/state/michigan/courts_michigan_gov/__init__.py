"""Michigan appellate courts scraper package.

This package provides scrapers for:
- Michigan Supreme Court (mich)
- Michigan Court of Appeals (michctapp)

Data is scraped from the Opinion & Order ZIP Files page which provides
daily archives of opinions from both courts.
"""

from .scraper import MichiganScraper

__all__ = ["MichiganScraper"]
