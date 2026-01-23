"""South Carolina Courts (sccourts.org) scraper package.

This package provides scrapers for South Carolina appellate court opinions from
https://www.sccourts.org/

Supported courts:
- sc: Supreme Court of South Carolina
- scctapp: Court of Appeals of South Carolina

Data types:
- opinions: Published and unpublished opinions
"""

from .scraper import SouthCarolinaScraper

__all__ = ["SouthCarolinaScraper"]
