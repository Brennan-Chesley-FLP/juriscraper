"""Tennessee Courts scraper package.

This package provides scrapers for Tennessee appellate courts:
- Tennessee Supreme Court (tenn)
- Court of Appeals of Tennessee (tennctapp)
- Court of Criminal Appeals of Tennessee (tenncrimapp)

Data types supported:
- judges: Judge/Justice profiles with photos
- opinions: Court opinions (PDF)
- oral_arguments: Oral argument videos (YouTube links)
- dockets: Case docket information from pch.tncourts.gov
"""

from .models import (
    TennDocket,
    TennDocketEntry,
    TennJudge,
    TennOpinion,
    TennOpinionCluster,
    TennOralArgument,
)
from .scraper import TennScraper

__all__ = [
    "TennScraper",
    "TennJudge",
    "TennOpinion",
    "TennOpinionCluster",
    "TennOralArgument",
    "TennDocket",
    "TennDocketEntry",
]
