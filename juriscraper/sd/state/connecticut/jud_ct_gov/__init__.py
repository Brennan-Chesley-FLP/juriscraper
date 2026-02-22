"""Connecticut appellate courts scraper package.

Contains a unified scraper for opinions, oral arguments, and dockets from:
- Connecticut Supreme Court (conn)
- Connecticut Appellate Court (connappct)
"""

from .models import (
    ConnDocket,
    ConnDocketEntry,
    ConnDocketUnavailable,
    ConnOpinion,
    ConnOpinionCluster,
    ConnOralArgument,
    ConnTrialCaseUnavailable,
)
from .scraper import ConnScraper

__all__ = [
    # Primary scraper
    "ConnScraper",
    # Models
    "ConnDocket",
    "ConnDocketEntry",
    "ConnDocketUnavailable",
    "ConnOpinion",
    "ConnOpinionCluster",
    "ConnOralArgument",
    "ConnTrialCaseUnavailable",
]
