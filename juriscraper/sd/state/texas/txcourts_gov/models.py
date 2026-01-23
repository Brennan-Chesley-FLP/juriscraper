"""Data models for Texas appellate courts scraper.

These models extend ConsumerModel types from base.py to capture
Texas Supreme Court, Court of Criminal Appeals, and Courts of Appeals
opinions and orders.

Supported courts (from courts.toml):
- tex: Texas Supreme Court
- texcrimapp: Texas Court of Criminal Appeals
- texapp: Texas Courts of Appeals (all 15 district courts)

Texas has two high courts:
- Supreme Court of Texas: highest court for CIVIL matters
- Court of Criminal Appeals: highest court for CRIMINAL matters

Plus 15 intermediate Courts of Appeals.
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
)

# Court codes used on search.txcourts.gov
# Supreme Court and Court of Criminal Appeals use different code patterns
COURT_CODE_TO_ID: dict[str, str] = {
    "cossup": "tex",  # Texas Supreme Court
    "coscca": "texcrimapp",  # Texas Court of Criminal Appeals
    # Courts of Appeals use coa01-coa15
    "coa01": "texapp",  # 1st Court of Appeals (Houston)
    "coa02": "texapp",  # 2nd Court of Appeals (Fort Worth)
    "coa03": "texapp",  # 3rd Court of Appeals (Austin)
    "coa04": "texapp",  # 4th Court of Appeals (San Antonio)
    "coa05": "texapp",  # 5th Court of Appeals (Dallas)
    "coa06": "texapp",  # 6th Court of Appeals (Texarkana)
    "coa07": "texapp",  # 7th Court of Appeals (Amarillo)
    "coa08": "texapp",  # 8th Court of Appeals (El Paso)
    "coa09": "texapp",  # 9th Court of Appeals (Beaumont)
    "coa10": "texapp",  # 10th Court of Appeals (Waco)
    "coa11": "texapp",  # 11th Court of Appeals (Eastland)
    "coa12": "texapp",  # 12th Court of Appeals (Tyler)
    "coa13": "texapp",  # 13th Court of Appeals (Corpus Christi-Edinburg)
    "coa14": "texapp",  # 14th Court of Appeals (Houston)
    "coa15": "texapp",  # 15th Court of Appeals (Austin, statewide jurisdiction)
}

# Reverse mapping: CourtListener court_id to list of court codes
COURT_ID_TO_CODES: dict[str, list[str]] = {
    "tex": ["cossup"],
    "texcrimapp": ["coscca"],
    "texapp": [f"coa{i:02d}" for i in range(1, 16)],
}

# All supported court IDs
COURT_IDS: set[str] = {"tex", "texcrimapp", "texapp"}

# Display names for courts
COURT_NAMES: dict[str, str] = {
    "tex": "Supreme Court of Texas",
    "texcrimapp": "Court of Criminal Appeals of Texas",
    "texapp": "Texas Courts of Appeals",
}

# Court code display names
COURT_CODE_NAMES: dict[str, str] = {
    "cossup": "Supreme Court of Texas",
    "coscca": "Court of Criminal Appeals of Texas",
    "coa01": "1st Court of Appeals (Houston)",
    "coa02": "2nd Court of Appeals (Fort Worth)",
    "coa03": "3rd Court of Appeals (Austin)",
    "coa04": "4th Court of Appeals (San Antonio)",
    "coa05": "5th Court of Appeals (Dallas)",
    "coa06": "6th Court of Appeals (Texarkana)",
    "coa07": "7th Court of Appeals (Amarillo)",
    "coa08": "8th Court of Appeals (El Paso)",
    "coa09": "9th Court of Appeals (Beaumont)",
    "coa10": "10th Court of Appeals (Waco)",
    "coa11": "11th Court of Appeals (Eastland)",
    "coa12": "12th Court of Appeals (Tyler)",
    "coa13": "13th Court of Appeals (Corpus Christi-Edinburg)",
    "coa14": "14th Court of Appeals (Houston)",
    "coa15": "15th Court of Appeals (Austin)",
}


class TexasOpinion(Opinion):
    """An individual opinion document from Texas appellate courts.

    Extends Opinion from base.py with required fields for Texas courts.
    """

    download_url: str
    """URL to the opinion/order PDF (required)"""

    type: str = "majority"
    """Opinion type: 'opinion', 'order', 'concurrence', 'dissent', etc."""

    local_path: str | None = None
    """Local filesystem path where the PDF was downloaded (set by driver)"""

    # Texas-specific fields
    author: str | None = None
    """Name of the opinion author (Justice/Judge or 'Per Curiam')"""

    published: bool = True
    """Whether the opinion is published (vs. memorandum/unpublished)"""


class TexasOpinionCluster(OpinionCluster):
    """A cluster of opinions from Texas appellate courts.

    This is the main output type yielded by the scraper for opinions.
    Each cluster represents a case that may have multiple opinions
    (majority, dissents, concurrences, orders).

    Supports:
    - Texas Supreme Court (tex)
    - Court of Criminal Appeals (texcrimapp)
    - Courts of Appeals 1-15 (texapp)
    """

    # === Searchable fields ===
    court_id: Annotated[str, SetFilter()]
    """Court identifier: 'tex', 'texcrimapp', 'texapp'"""

    date_decided: Annotated[date | None, DateRange()] = None
    """Date the opinion was decided/filed"""

    # === Required fields ===
    case_name: str
    """Case name/style (e.g., 'State v. Smith')"""

    docket_number: str
    """Case/docket number (e.g., '24-0581', 'PD-0523-25', '01-24-00183-CV')"""

    # === Optional fields ===
    court_code: str | None = None
    """Internal court code (e.g., 'cossup', 'coscca', 'coa01')"""

    court_name: str | None = None
    """Display name of the court"""

    disposition: str | None = None
    """Case disposition (e.g., 'AFFIRM TC JUDGMENT', 'REVERSE AND RENDER')"""

    judges: str | None = None
    """List of judges/justices on the panel (semicolon-separated)"""

    author: str | None = None
    """Name of the authoring judge/justice"""

    lower_court: str | None = None
    """Lower court from which the appeal originated"""

    county: str | None = None
    """County of origin"""

    case_type: str | None = None
    """Case type: 'civil', 'criminal'"""

    category: str | None = None
    """Category from handdown list (e.g., 'HABEAS CORPUS RELIEF GRANTED')"""

    # === Related data ===
    opinions: list[TexasOpinion] = []
    """All opinions/orders in this cluster"""

    # === Source tracking ===
    source_url: str | None = None
    """URL of the handdown/opinions listing page"""
