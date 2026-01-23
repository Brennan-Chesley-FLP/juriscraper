"""Data models for California appellate courts scraper.

These models extend ConsumerModel types from base.py to capture
California Supreme Court and Courts of Appeal opinion data.

Mapping to base.py types:
- CalOpinion -> Opinion (individual opinion document)
- CalOpinionCluster -> OpinionCluster (group of related opinions)

Supported courts:
- cal: California Supreme Court (case prefix: S)
- calctapp1d: 1st District Court of Appeal (case prefix: A)
- calctapp2d: 2nd District Court of Appeal (case prefix: B)
- calctapp3d: 3rd District Court of Appeal (case prefix: C)
- calctapp4d: 4th District Court of Appeal, Division 1/2/3 (case prefix: D/E/G)
- calctapp5d: 5th District Court of Appeal (case prefix: F)
- calctapp6d: 6th District Court of Appeal (case prefix: H)
- calappdeptsuper: Appellate Division (various prefixes)
"""

from __future__ import annotations

from datetime import date
from typing import Annotated

from juriscraper.scraper_driver.common.models.base import (
    Opinion,
    OpinionCluster,
)
from juriscraper.scraper_driver.common.searchable import (
    DateRange,
    SetFilter,
    UniqueMatch,
)

# Court ID mapping - maps case number prefix to court_id
# S = Supreme Court, A = 1st DCA, B = 2nd DCA, C = 3rd DCA,
# D = 4th DCA Div 1, E = 4th DCA Div 2, G = 4th DCA Div 3,
# F = 5th DCA, H = 6th DCA
CASE_PREFIX_TO_COURT = {
    "S": "cal",
    "A": "calctapp1d",
    "B": "calctapp2d",
    "C": "calctapp3d",
    "D": "calctapp4d",  # 4th District, Division One
    "E": "calctapp4d",  # 4th District, Division Two
    "G": "calctapp4d",  # 4th District, Division Three
    "F": "calctapp5d",
    "H": "calctapp6d",
}

# Source names from dropdown values
SOURCE_TO_COURT = {
    "Supreme Court": "cal",
    "1st District Court of Appeal": "calctapp1d",
    "2nd District Court of Appeal": "calctapp2d",
    "3rd District Court of Appeal": "calctapp3d",
    "4th District Court of Appeal, Division One": "calctapp4d",
    "4th District Court of Appeal, Division Two": "calctapp4d",
    "4th District Court of Appeal, Division Three": "calctapp4d",
    "5th District Court of Appeal": "calctapp5d",
    "6th District Court of Appeal": "calctapp6d",
    "Appellate Division": "calappdeptsuper",
}

COURT_IDS = {
    "cal": "California Supreme Court",
    "calctapp1d": "California Court of Appeal, First Appellate District",
    "calctapp2d": "California Court of Appeal, Second Appellate District",
    "calctapp3d": "California Court of Appeal, Third Appellate District",
    "calctapp4d": "California Court of Appeal, Fourth Appellate District",
    "calctapp5d": "California Court of Appeal, Fifth Appellate District",
    "calctapp6d": "California Court of Appeal, Sixth Appellate District",
    "calappdeptsuper": "California Superior Court, Appellate Division",
}


class CalOpinion(Opinion):
    """An individual opinion document from California appellate courts.

    Extends Opinion from base.py with required fields for CA courts.
    """

    download_url: str  # Required - URL to PDF
    """URL to the opinion PDF"""

    type: str = "majority"
    """Opinion type: 'majority' for main opinion (CA doesn't typically separate)"""

    local_path: str | None = None
    """Local filesystem path where the PDF was downloaded (set by driver)"""


class CalOpinionCluster(OpinionCluster):
    """A cluster of opinions from California appellate courts.

    This is the main output type yielded by the scraper.
    Each cluster represents a case opinion. California typically
    publishes opinions as single PDFs (not separated by majority/dissent).

    Supports California Supreme Court and all Districts of the
    Courts of Appeal.
    """

    # === Searchable fields ===
    case_number: Annotated[str, UniqueMatch()]  # Required, searchable
    """Case number (e.g., 'S275272M' for Supreme Court, 'A172153' for 1st DCA)"""

    court_id: Annotated[str, SetFilter()]  # Required, searchable
    """Court identifier: 'cal', 'calctapp1d', 'calctapp2d', etc."""

    date_filed: Annotated[date, DateRange()]  # Required, searchable
    """Date the opinion was filed/published"""

    # === Required fields from base ===
    case_name: str  # Required
    """Case name (e.g., 'L.A. Police Protective League v. City of L.A.')"""

    # === Related data ===
    opinions: list[CalOpinion] = []
    """All opinions in this cluster (typically just one for CA)"""

    # === California-specific fields ===
    precedential_status: str = "Published"
    """Publication status: 'Published' or 'Unpublished'"""

    source_court: str | None = None
    """Source court name as shown on website (e.g., '2nd District Court of Appeal')"""

    division: str | None = None
    """Court division if applicable (e.g., 'Division One', 'CA2/6')"""

    related_cases: list[str] = []
    """Related case numbers (some opinions have consolidated/related cases)"""

    case_info_url: str | None = None
    """URL to case information search page for this case"""

    other_formats_url: str | None = None
    """URL to other formats page for this opinion"""

    # === Source tracking ===
    source_url: str | None = None
    """URL of the opinions list page where this was found"""
