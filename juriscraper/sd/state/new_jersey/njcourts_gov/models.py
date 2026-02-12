"""Data models for New Jersey appellate courts scraper.

These models extend ConsumerModel types from base.py to capture
New Jersey court opinion data.

Mapping to base.py types:
- NewJerseyOpinion -> Opinion (individual opinion document)
- NewJerseyOpinionCluster -> OpinionCluster (group of related opinions)

Supported courts:
- nj: Supreme Court of New Jersey
- njsuperctappdiv: New Jersey Superior Court Appellate Division

Note: Tax Court opinions are also available but are tracked separately.
"""

from __future__ import annotations

import re
from datetime import date

from kent.common.models.base import (
    Opinion,
    OpinionCluster,
)

# Court ID mapping to CourtListener IDs
COURT_IDS = {
    "nj": "Supreme Court of New Jersey",
    "njsuperctappdiv": "New Jersey Superior Court Appellate Division",
}

# Opinion type to court_id mapping
# Based on the "badge" shown on the opinions page
OPINION_TYPE_TO_COURT = {
    "Supreme": "nj",
    "Published Appellate": "njsuperctappdiv",
    "Unpublished Appellate": "njsuperctappdiv",
}

# Precedential status mapping
OPINION_TYPE_TO_PRECEDENTIAL_STATUS = {
    "Supreme": "Published",
    "Published Appellate": "Published",
    "Unpublished Appellate": "Unpublished",
}


class NewJerseyOpinion(Opinion):
    """An individual opinion document from New Jersey courts.

    Extends Opinion from base.py with required fields for NJ courts.
    """

    download_url: str
    """URL to the opinion PDF"""

    local_path: str | None = None
    """Local filesystem path where the PDF was downloaded (set by driver)"""


class NewJerseyOpinionCluster(OpinionCluster):
    """A cluster of opinions from New Jersey courts.

    This is the main output type yielded by the scraper.
    Each cluster represents a single opinion.

    Docket number formats:
    - Supreme Court: A-NN-YY (e.g., A-45-24)
    - Appellate Division: A-NNNN-YY (e.g., A-2236-23)
    - Consolidated: A-NNNN-YY/A-NNNN-YY
    """

    # === Searchable fields ===
    docket_id: str  # type: ignore[assignment]
    """Docket number (e.g., 'A-45-24' or 'A-2236-23')"""

    court_id: str
    """Court identifier: 'nj' (Supreme) or 'njsuperctappdiv' (Appellate Div)"""

    date_filed: date
    """Publication date of the opinion"""

    # === Required fields from base ===
    case_name: str
    """Case name (e.g., 'Andris Arias v. County of Bergen')"""

    # === Related data ===
    opinions: list[NewJerseyOpinion] = []
    """All opinions in this cluster (typically just one)"""

    # === Source tracking ===
    source_url: str | None = None
    """URL of the page where this was found"""

    # === NJ-specific fields ===
    opinion_type: str
    """Type of opinion: 'Supreme', 'Published Appellate', 'Unpublished Appellate'"""

    certification_number: str | None = None
    """Certification number if present (e.g., '089642')"""

    is_redacted: bool = False
    """Whether this opinion is redacted"""

    is_record_impounded: bool = False
    """Whether the record is impounded"""


# Regex patterns for parsing
DOCKET_PATTERN = re.compile(
    r"([A-Z])-?(\d+(?:/\d+)*)-(\d{2})"
    r"(?:/([A-Z])-?(\d+(?:/\d+)*)-(\d{2}))?",
    re.IGNORECASE,
)
"""Pattern to match docket numbers like A-45-24 or A-2236-23/A-2237-23"""

CERTIFICATION_PATTERN = re.compile(r"\((\d{6})\)")
"""Pattern to match certification numbers like (089642)"""

# Date patterns for NJ opinions
# Format: "Mon. DD, YYYY" (e.g., "Jan. 22, 2026")
DATE_PATTERN = re.compile(r"([A-Z][a-z]{2,8})\.?\s+(\d{1,2}),\s+(\d{4})")

# Month name to number mapping (handles both abbreviated and full forms)
MONTH_MAP = {
    "Jan": 1,
    "January": 1,
    "Feb": 2,
    "February": 2,
    "Mar": 3,
    "March": 3,
    "Apr": 4,
    "April": 4,
    "May": 5,
    "Jun": 6,
    "June": 6,
    "Jul": 7,
    "July": 7,
    "Aug": 8,
    "August": 8,
    "Sep": 9,
    "Sept": 9,
    "September": 9,
    "Oct": 10,
    "October": 10,
    "Nov": 11,
    "November": 11,
    "Dec": 12,
    "December": 12,
}


def parse_nj_date(date_str: str) -> date | None:
    """Parse a date string from the NJ courts opinions page.

    Args:
        date_str: Date string like "Jan. 22, 2026" or "January 22, 2026"

    Returns:
        Parsed date or None if not parseable
    """
    match = DATE_PATTERN.search(date_str)
    if not match:
        return None

    month_str = match.group(1)
    day = int(match.group(2))
    year = int(match.group(3))

    month = MONTH_MAP.get(month_str)
    if month is None:
        return None

    try:
        return date(year, month, day)
    except ValueError:
        return None
