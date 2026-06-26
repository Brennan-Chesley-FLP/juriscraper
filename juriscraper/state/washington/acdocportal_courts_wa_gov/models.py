"""Data models for the Washington ACDocPortal scraper.

Data source:
- https://acdocportal.courts.wa.gov/PublicAccess/

Supported courts:
- wash:      Washington Supreme Court        (7-digit case numbers, e.g. 1048343)
- washctapp: Washington Court of Appeals     (6-digit case numbers, e.g. 871463)

The site exposes a JSON "KeywordSearch" API that returns every public
document filed on a given case in a single response.  Each row in that
response becomes one :class:`WaDocketEntry`; the full set is aggregated
into one :class:`WaDocket` per case.

Field names follow [`../../CL_MODELS.md`](../../CL_MODELS.md): the
CourtListener court-id string is ``court`` (not ``court_id``), the case
number is ``docket_number`` (not ``case_number``/``docket_id``), and dates
use the ``date_*`` prefix.
"""

from __future__ import annotations

from datetime import date

from jkent.common.data_models import ScrapedData

# CourtListener court id -> human-readable court name.
COURT_IDS: dict[str, str] = {
    "wash": "Washington Supreme Court",
    "washctapp": "Washington Court of Appeals",
}

# Court -> KeywordSearch body params.  Discovered by inspecting the
# portal's AJAX traffic.
COURT_QUERY_PARAMS: dict[str, dict[str, int]] = {
    "wash": {"query_id": 194, "keyword_id": 172},
    "washctapp": {"query_id": 193, "keyword_id": 168},
}

# Expected case-number width as documented on each search form.
COURT_CASE_NUM_DIGITS: dict[str, int] = {
    "wash": 7,
    "washctapp": 6,
}


class WaDocketEntry(ScrapedData):
    """A single document / filing row from the ACDocPortal search API.

    Maps loosely to CourtListener ``DocketEntry`` (+ ``RECAPDocument``
    for the linked PDF)."""

    date_filed: date | None = None
    """Date the document was filed or issued (the "Doc Filed Date" column)."""

    filing_type: str | None = None
    """Top-level filing category (e.g. ``"Order"``, ``"Brief"``, ``"Motion Party"``,
    ``"Ruling"``, ``"E-Mail"``)."""

    filing_subtype: str | None = None
    """Sub-category (e.g. ``"Granting Review"``, ``"Amicus Curiae"``,
    ``"Extend Time to File"``)."""

    document_name: str
    """Human-readable description concatenated by the portal.  Format is roughly:
    ``"- <case#> - <access> - <type> - <subtype> - <start> - <end> - <note> -"``."""

    anchor_case_number: str | None = None
    """Raw value of the "Anchor Case Number" column (often empty)."""

    document_id: str
    """Opaque token used in the download URL.  Contains URL-unsafe characters."""

    document_url: str
    """Fully-qualified URL that returns the document as a PDF."""

    local_path: str | None = None
    """Local filesystem path after archiving (populated downstream)."""


class WaDownloadedDocument(ScrapedData):
    """A downloaded document file, yielded after archiving completes.

    Emitted separately from :class:`WaDocket` so archive downloads can
    proceed independently.  Join back to the parent case with
    ``(court, docket_number, document_id)``.

    Maps to CourtListener ``RECAPDocument``."""

    court: str
    """CourtListener court id: ``wash`` or ``washctapp``."""

    docket_number: str
    document_id: str
    document_url: str
    local_path: str | None = None


class WaDocket(ScrapedData):
    """A Washington appellate-court docket.

    Constructed from the full set of document rows returned for a given
    case number by the ACDocPortal KeywordSearch API.  Maps to
    CourtListener ``Docket``."""

    docket_number: str
    """Case number (7 digits for Supreme Court, 6 digits for Court of Appeals)."""

    court: str
    """CourtListener court id: ``"wash"`` or ``"washctapp"``."""

    case_name: str
    """Case short title (e.g. ``"Gary Yetter v. Department of Labor & Industries"``).
    Derived from the repeating "Case Title" column on every result row."""

    anchor_case_number: str | None = None
    """Non-empty when the portal reports an "anchor" case number (rare)."""

    truncated: bool = False
    """True when the API reports it truncated results (``QueryLimit`` reached)."""

    entries: list[WaDocketEntry] = []
    """One entry per document / filing row returned by the search API."""

    source_url: str | None = None
    """URL of the public search page for this court (for reference)."""

    source_entry_point: str | None = None
    """Entry point used to reach this docket."""
