"""Data models for Louisiana Supreme Court scraper.

These models extend ConsumerModel types from base.py to capture
Louisiana Supreme Court opinion data.

Mapping to base.py types:

- LouisianaOpinion -> Opinion (individual opinion document)
- LouisianaOpinionCluster -> OpinionCluster (group of related opinions)

Supported court:

- la: Supreme Court of Louisiana

Case number format:

- ``{year}-{type}-{number}`` e.g., 2025-C-01635
- Type codes: C (civil), K (criminal), KK (criminal writ), CC (civil certified),
  B (disciplinary), BA (bar admission), OB (disciplinary appeal), etc.
"""

from __future__ import annotations

from datetime import date

from kent.common.models.base import (
    Opinion,
    OpinionCluster,
)

# Court ID mapping to CourtListener ID
COURT_ID = "la"
COURT_NAME = "Supreme Court of Louisiana"


class LouisianaOpinion(Opinion):
    """An individual opinion document from Louisiana Supreme Court.

    Extends Opinion from base.py with required fields for Louisiana courts.
    """

    download_url: str
    """URL to the opinion PDF"""

    opinion_type: str
    """Opinion type: 'per_curiam', 'opinion', 'action', 'rehearing', 'concurrence', 'dissent'"""

    author: str | None = None
    """Author of the opinion (e.g., 'Weimer, C.J.', 'Hughes, J.')"""

    local_path: str | None = None
    """Local filesystem path where the PDF was downloaded (set by driver)"""


class LouisianaOpinionCluster(OpinionCluster):
    """A cluster of opinions from Louisiana Supreme Court.

    This is the main output type yielded by the scraper.
    Each cluster represents a case that may have multiple related documents
    (main opinion, concurrences, dissents).
    """

    # === Searchable fields ===
    docket_id: str  # type: ignore[assignment]
    """Case number (e.g., '2025-C-01635')"""

    court_id: str
    """Court identifier: 'la' (Supreme Court of Louisiana)"""

    date_filed: date
    """Date the opinion was filed/released"""

    # === Required fields from base ===
    case_name: str
    """Case name (e.g., 'JAMES CARNEZ BURNS VS. LOOMIS ARMORED US, LLC')"""

    # === Related data ===
    opinions: list[LouisianaOpinion] = []
    """All opinions/orders in this cluster"""

    # === Source tracking ===
    source_url: str | None = None
    """URL of the page where this was found"""

    # === Louisiana-specific fields ===
    parish: str | None = None
    """Parish of origin (e.g., 'Parish of Caddo')"""

    disposition: str | None = None
    """Disposition text (e.g., 'Writ application granted', 'AFFIRMED')"""

    release_number: str | None = None
    """News release number (e.g., '2026-001')"""

    release_type: str | None = None
    """Type of release: 'actions', 'opinions', 'rehearings'"""

    votes: list[str] = []
    """List of justice votes/dissents (e.g., 'Hughes, J., would grant.')"""

    case_type_code: str | None = None
    """Case type code from docket number (e.g., 'C', 'K', 'KK', 'B')"""
