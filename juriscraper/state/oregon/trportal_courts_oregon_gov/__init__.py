"""Oregon appellate courts scraper for trportal.courts.oregon.gov.

Supports Oregon Supreme Court (or) and Court of Appeals (orctapp).

Data types:
- OreDocket: Docket information
- OreOralArgument: Oral argument information
"""

from .models import OreDocket, OreOralArgument
from .scraper import OregonScraper

__all__ = [
    "OregonScraper",
    "OreDocket",
    "OreOralArgument",
]
