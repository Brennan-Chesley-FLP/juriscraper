"""Alabama appellate courts scraper for publicportal.alappeals.gov.

Supports Alabama Supreme Court (ala), Court of Civil Appeals (alactapp),
and Court of Criminal Appeals (alacrimapp).

Data types:
- AlaOpinionCluster: Individual opinions (May 2023+)
- AlaHistoricalReleaseList: Weekly PDF bundles (pre-May 2023)
- AlaOralArgument: Oral argument information
- AlaDocket: Docket information
"""

from .models import (
    AlaDocket,
    AlaDocument,
    AlaHistoricalReleaseList,
    AlaOpinionCluster,
    AlaOralArgument,
)
from .scraper import AlabamaScraper

__all__ = [
    "AlabamaScraper",
    "AlaDocket",
    "AlaDocument",
    "AlaHistoricalReleaseList",
    "AlaOpinionCluster",
    "AlaOralArgument",
]
