"""Data models for Georgia appellate courts opinions scraper.

These models extend ConsumerModel types from base.py to capture
Georgia Supreme Court and Court of Appeals opinion data.

Mapping to base.py types:
- GaOpinion -> Opinion (individual opinion document)
- GaOpinionCluster -> OpinionCluster (group of related opinions)

Supported courts:
- ga: Georgia Supreme Court
- gactapp: Georgia Court of Appeals

URL Sources:
- Supreme Court opinions: https://www.gasupreme.us/{YYYY}-opinions/
- Court of Appeals opinions: https://www.gaappeals.gov/opinion-search/

Case number formats:
- Supreme Court: S{YY}{Letter}{seq} (e.g., S25A0994)
- Court of Appeals: A{YY}{Letter}{seq} (e.g., A25A1439)

Citation formats:
- Supreme Court: Georgia Reports (Ga.)
- Court of Appeals: Georgia Appeals Reports (Ga. App.)
"""

from __future__ import annotations

from datetime import date

from kent.common.models.base import (
    Opinion,
    OpinionCluster,
)

# Court ID mapping
COURT_IDS = {
    "ga": "Georgia Supreme Court",
    "gactapp": "Georgia Court of Appeals",
}

# Court configuration for scraping
COURT_CONFIG: dict[str, dict[str, str]] = {
    "ga": {
        "name": "Georgia Supreme Court",
        "opinion_base_url": "https://www.gasupreme.us",
        "opinion_list_pattern": "/{year}-opinions/",
        "case_prefix": "S",
    },
    "gactapp": {
        "name": "Georgia Court of Appeals",
        "opinion_search_url": "https://www.gaappeals.gov/wp-content/themes/benjamin/docket/docketdate/results_all.php",
        "case_prefix": "A",
    },
}

# Case type letter descriptions for Supreme Court
GA_CASE_TYPES: dict[str, str] = {
    "A": "Direct appeal",
    "B": "Petition to appoint Special Master",
    "C": "Certiorari to Court of Appeals",
    "D": "Discretionary application",
    "E": "Certificate of probable cause (death sentence habeas)",
    "F": "Direct appeal (Family Law Pilot - pre-2017)",
    "G": "Granted certiorari",
    "H": "Certificate of probable cause (habeas)",
    "I": "Interlocutory application",
    "J": "JQC matters",
    "M": "Emergency motion to stay",
    "O": "Petition filed without lower court review",
    "P": "Automatic direct appeal (death penalty)",
    "Q": "Certified questions from federal courts",
    "R": "Interim appellate review (death penalty pre-trial)",
    "T": "Extension of time request",
    "U": "Bar unauthorized practice review",
    "W": "Cases with scheduled execution",
    "X": "Cross-appeal",
    "Y": "Attorney discipline",
    "Z": "JQC/Bar Admissions appeal",
}

# Case type letter descriptions for Court of Appeals
GACTAPP_CASE_TYPES: dict[str, str] = {
    "A": "Direct appeal",
    "D": "Discretionary application",
    "I": "Interlocutory application",
}


class GaOpinion(Opinion):
    """An individual opinion document from Georgia appellate courts.

    Extends Opinion from base.py with required fields for Georgia courts.
    """

    download_url: str
    """URL to the opinion PDF (required)"""

    type: str = "majority"
    """Opinion type: 'majority', 'dissent', 'concurrence', etc."""

    local_path: str | None = None
    """Local filesystem path where the PDF was downloaded (set by driver)"""


class GaOpinionCluster(OpinionCluster):
    """A cluster of opinions from Georgia appellate courts.

    This is the main output type yielded by the scraper for opinions.
    Each cluster represents a case with one or more opinions.

    Supports Georgia Supreme Court (ga) and Court of Appeals (gactapp).
    """

    # === Searchable fields ===
    court_id: str
    """Court identifier: 'ga' or 'gactapp'"""

    date_filed: date
    """Date the opinion was filed/published"""

    # === Required fields ===
    case_name: str
    """Case name/style (e.g., 'FRANKLIN v. THE STATE')"""

    docket_number: str
    """Case number (e.g., 'S25A0994' or 'A25A1439')"""

    # === Optional fields ===
    case_type_code: str | None = None
    """Single letter case type code (e.g., 'A', 'Y', 'D')"""

    case_type_description: str | None = None
    """Case type description (e.g., 'Direct appeal', 'Attorney discipline')"""

    disposition: str | None = None
    """Court's ruling (e.g., 'AFFIRMED', 'REVERSED', 'DISMISSED')"""

    # === Related data ===
    opinions: list[GaOpinion] = []
    """All opinions in this cluster (usually just one PDF)"""

    # === Source tracking ===
    source_url: str | None = None
    """URL of the opinion list page or search results"""
