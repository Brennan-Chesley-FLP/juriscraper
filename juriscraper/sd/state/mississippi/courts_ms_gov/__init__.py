"""Mississippi appellate courts scraper package.

This package provides scrapers for Mississippi appellate court opinions:
- Mississippi Supreme Court (miss)
- Mississippi Court of Appeals (missctapp)

Entry point: https://courts.ms.gov/
"""

from .scraper import MississippiScraper

__all__ = ["MississippiScraper"]
