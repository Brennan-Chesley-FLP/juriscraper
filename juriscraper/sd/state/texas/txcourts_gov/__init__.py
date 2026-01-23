"""Texas Appellate Courts scraper package.

This package contains scrapers for Texas appellate court opinions and orders:
- Texas Supreme Court (tex)
- Texas Court of Criminal Appeals (texcrimapp)
- Texas Courts of Appeals (texapp) - 1st through 15th districts
"""

from .scraper import TexasScraper

__all__ = ["TexasScraper"]
