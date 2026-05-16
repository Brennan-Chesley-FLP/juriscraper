"""North Dakota appellate courts scraper for portal.ctrack.ndcourts.gov.

Supports the North Dakota Supreme Court (nd).

Data types:
- NdDocket: Docket information
- NdOralArgument: Oral argument information
"""

from .models import NdDocket, NdOralArgument
from .scraper import NorthDakotaScraper

__all__ = [
    "NorthDakotaScraper",
    "NdDocket",
    "NdOralArgument",
]
