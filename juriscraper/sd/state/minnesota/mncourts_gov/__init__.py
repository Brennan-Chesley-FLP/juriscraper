"""Minnesota appellate courts scraper package.

This package provides scrapers for:
- Minnesota Supreme Court (minn)
- Minnesota Court of Appeals (minnctapp)

Entry point: MNCourtsScraper
"""

from .scraper import MNCourtsScraper

__all__ = ["MNCourtsScraper"]
