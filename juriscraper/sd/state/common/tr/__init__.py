"""Common infrastructure for TR Portal (Thomson Reuters C-Track) scrapers.

Multiple state appellate court systems use the Thomson Reuters C-Track
Public Portal. These portals share a common REST API structure with
endpoints for cases, parties, docket entries, calendar events, hearings,
and publications.

Known deployments:
- Alabama: https://publicportal.alappeals.gov
- Oregon: https://trportal.courts.oregon.gov
"""

from .models import TRCourtConfig, TRDocket, TRDocketEntry, TROralArgument
from .scraper import TRPortalMixin

__all__ = [
    "TRCourtConfig",
    "TRDocket",
    "TRDocketEntry",
    "TROralArgument",
    "TRPortalMixin",
]
