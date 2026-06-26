"""Connecticut appellate-inquiry docket scraper package.

Dockets for the Connecticut Supreme Court (``conn``) and Appellate Court
(``connappct``) from ``appellateinquiry.jud.ct.gov``, plus the linked Superior
Court (``connsuperct``) trial-court cases from ``civilinquiry.jud.ct.gov``.
"""

from .models import (
    ConnAppDocket,
    ConnAppDocketEntry,
    ConnAppDocketUnavailable,
    ConnAppFile,
    ConnTrialCaseUnavailable,
    ConnTrialCourtDocket,
    ConnTrialCourtDocketEntry,
    ConnTrialFile,
)
from .scraper import ConnAppInquiryScraper

__all__ = [
    "ConnAppInquiryScraper",
    "ConnAppDocket",
    "ConnAppDocketEntry",
    "ConnAppDocketUnavailable",
    "ConnAppFile",
    "ConnTrialCaseUnavailable",
    "ConnTrialCourtDocket",
    "ConnTrialCourtDocketEntry",
    "ConnTrialFile",
]
