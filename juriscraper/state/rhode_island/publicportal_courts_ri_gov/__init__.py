"""Rhode Island Judiciary Public Portal scraper.

Tyler Odyssey Public Portal — covers the Supreme Court of Rhode Island
(``ri``). Requires Playwright with reCAPTCHA handling
(``RCAP_HANDLER`` + ``CHROME_ALIKE``) plus DataDome-passthrough via
``JS_EVAL`` browser session.

Data types:
- ``RIDocket``: A docket from the Smart Search results page.
"""

from .models import (
    DASHBOARD_URL,
    PORTAL_URL,
    RI_COURT_NAMES,
    RI_COURTS,
    RIDocket,
    RIDocketEntry,
    RIParty,
)
from .scraper import RhodeIslandPublicPortalScraper

__all__ = [
    "DASHBOARD_URL",
    "PORTAL_URL",
    "RI_COURTS",
    "RI_COURT_NAMES",
    "RIDocket",
    "RIDocketEntry",
    "RIParty",
    "RhodeIslandPublicPortalScraper",
]
