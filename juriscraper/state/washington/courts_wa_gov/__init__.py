"""Washington appellate-briefs scraper (www.courts.wa.gov).

Scrapes briefs filed for hearings before the Washington Supreme Court
and the three divisions of the Court of Appeals.

Data types:
- WaBriefCase: A case with its associated briefs for a hearing date.
- WaDownloadedBrief: Per-file archive record.
"""

from .models import (
    BRIEFS_COURTS,
    WaBrief,
    WaBriefCase,
    WaDownloadedBrief,
)
from .scraper import WashingtonBriefsScraper

__all__ = [
    "BRIEFS_COURTS",
    "WaBrief",
    "WaBriefCase",
    "WaDownloadedBrief",
    "WashingtonBriefsScraper",
]
