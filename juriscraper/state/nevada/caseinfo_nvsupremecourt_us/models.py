"""Data models for the Nevada appellate courts scraper.

Supported courts:
- nev: Nevada Supreme Court (docket numbers like 92415)
- nevapp: Nevada Court of Appeals (docket numbers like 92415-COA)
"""

from __future__ import annotations

from datetime import date

from jkent.common.data_models import ScrapedData


class NvAttorney(ScrapedData):
    """An attorney representing a party."""

    name: str
    firm: str | None = None


class NvParty(ScrapedData):
    """A party in the case with their representation."""

    name: str
    role: str
    attorneys: list[NvAttorney] = []


class NvRelatedCase(ScrapedData):
    """A related case linked from the Case Information header."""

    docket_number: str
    internal_id: int | None = None


class NvDocketEntry(ScrapedData):
    """A single row from the Docket Entries table."""

    date_filed: date | None = None
    entry_type: str | None = None
    description: str
    pending: bool = False
    document_number: str | None = None
    document_url: str | None = None
    combined_only: bool = False
    """True when this entry appears only in the Combined Case View, meaning
    it belongs to the related case (the other court's proceedings)."""


class NvUnavailableCase(ScrapedData):
    """A csIID that exists but returns the "rights to view" error page.

    Sealed cases and truly-invalid csIIDs are indistinguishable from the
    site's response (both render the same "You do not have rights to view
    this case" page). We emit this record whenever that page is returned so
    downstream jobs can keep track of which csIIDs are not openly fetchable.
    """

    internal_id: int
    """Site-internal csIID that produced the sealed/not-viewable page."""

    source_url: str | None = None


class NvDocument(ScrapedData):
    """A document downloaded from a docket entry.

    Yielded as a separate top-level record alongside the parent NvDocket.
    Join back to the docket via ``internal_id`` (the site-internal csIID).
    """

    internal_id: int
    """Parent case csIID — join key to NvDocket.internal_id."""

    document_number: str
    """OnBase document number (e.g., '26-16662')."""

    document_url: str

    date_filed: date | None = None
    entry_type: str | None = None
    description: str | None = None

    local_path: str | None = None
    """Filesystem path where the driver archived this document."""


class NvDocket(ScrapedData):
    """A complete Nevada appellate docket.

    Aggregates the Case Information header, Party Information table, and
    docket entries from both the original and combined case views.
    """

    docket_number: str
    """Site docket number (e.g., '92415' or '92415-COA')."""

    court_id: str
    """CourtListener court id: 'nev' or 'nevapp'."""

    internal_id: int
    """Site-internal csIID used to fetch this case."""

    case_name: str
    """Short caption from the Case Information header."""

    date_filed: date | None = None

    classification: str | None = None
    case_status: str | None = None
    disqualifications: str | None = None
    replacement: str | None = None
    panel_assigned: str | None = None
    to_sp_judge: str | None = None
    sp_status: str | None = None
    oral_argument: str | None = None
    oral_argument_location: str | None = None
    submission_date: str | None = None
    how_submitted: str | None = None

    lower_court_cases: list[str] = []
    related_cases: list[NvRelatedCase] = []

    parties: list[NvParty] = []
    entries: list[NvDocketEntry] = []

    source_url: str | None = None
