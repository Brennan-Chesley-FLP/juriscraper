"""Georgia Appellate Courts Scraper.

Scrapes opinions from Georgia Supreme Court (ga) and Court of Appeals (gactapp).
"""

from .models import (
    COURT_CONFIG,
    COURT_IDS,
    GaOpinion,
    GaOpinionCluster,
)
from .scraper import GeorgiaScraper

__all__ = [
    "COURT_CONFIG",
    "COURT_IDS",
    "GaOpinion",
    "GaOpinionCluster",
    "GeorgiaScraper",
]
