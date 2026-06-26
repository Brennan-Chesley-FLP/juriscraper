"""Washington DW Courts scraper (dw.courts.wa.gov).

Scrapes appellate dockets via the Appellate Courts case-number search.
Requires Playwright with reCAPTCHA handling (RCAP_HANDLER + CHROME_ALIKE).

Data types:
- DWWADocket: A docket with participants and event entries.
"""

from .models import (
    DW_COURTS,
    DWWADocket,
    DWWADocketEntry,
    DWWAParticipant,
)
from .scraper import DwCourtRange, DWCourtsScraper

__all__ = [
    "DW_COURTS",
    "DWCourtsScraper",
    "DWWADocket",
    "DWWADocketEntry",
    "DWWAParticipant",
    "DwCourtRange",
]
