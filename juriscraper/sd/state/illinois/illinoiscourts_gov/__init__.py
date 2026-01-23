"""Illinois Courts scraper package.

Scrapes opinions from the Illinois Supreme Court and Appellate Court
using their RSS feeds.
"""

from .models import IllinoisOpinion, IllinoisOpinionCluster
from .scraper import IllinoisScraper

__all__ = [
    "IllinoisOpinion",
    "IllinoisOpinionCluster",
    "IllinoisScraper",
]
