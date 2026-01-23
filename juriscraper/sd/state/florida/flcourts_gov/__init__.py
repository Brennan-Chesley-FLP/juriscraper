"""Florida appellate courts scraper module.

This module contains scrapers for Florida appellate courts:
- Florida Supreme Court (fla)
- Florida District Courts of Appeal (fladistctapp1-6)

Data is scraped from the unified Florida Courts website (flcourts.gov).
"""

from .scraper import FloridaScraper

__all__ = ["FloridaScraper"]
