"""Data models for the Washington DW Courts scraper (dw.courts.wa.gov).

Data source:
- https://dw.courts.wa.gov/

This scraper covers the Appellate Courts case-number search.  The search
returns one "card" per participant in the case; all cards share the same
``case_key`` and link URL.  The case-summary/docket page lists every
event for the case in a Tabulator table whose data is embedded in the
page source as an inline JavaScript array.

Courts:
- wash:          A08  Washington Supreme Court
- washctappdiv1: A01  Court of Appeals Division I
- washctappdiv2: A02  Court of Appeals Division II
- washctappdiv3: A03  Court of Appeals Division III

Field names follow [`../../CL_MODELS.md`](../../CL_MODELS.md): the
CourtListener court-id string is ``court`` (not ``court_id``), the case
number is ``docket_number`` (not ``case_number``), and dates use the
``date_*`` prefix.
"""

from __future__ import annotations

from datetime import date

from jkent.common.data_models import ScrapedData

# CourtListener court id -> (DW internal court code, display name).
DW_COURTS: dict[str, tuple[str, str]] = {
    "wash": ("A08", "SUPREME COURT"),
    "washctappdiv1": ("A01", "COURT OF APPEALS DIVISION I"),
    "washctappdiv2": ("A02", "COURT OF APPEALS DIVISION II"),
    "washctappdiv3": ("A03", "COURT OF APPEALS DIVISION III"),
}


class DWWAParticipant(ScrapedData):
    """A participant extracted from a search-result card.

    Maps to CourtListener ``Party`` (+ ``PartyType`` for the role)."""

    name: str
    """Participant name as shown on the card (e.g. ``"Salvo, Michael"``)."""

    role: str | None = None
    """Role in the case (e.g. ``"Appellant"``, ``"Respondent"``).  From
    the card's "Participant Code" field (CL ``PartyType.name``)."""

    review_type: str | None = None
    """How the case arrived at this court (e.g. ``"Notice of Appeal"``)."""


class DWWADocketEntry(ScrapedData):
    """A single event row from the Tabulator docket table.

    Maps to CourtListener ``DocketEntry``."""

    date_filed: date | None = None
    """Date of the event (from the ``eventDate`` JS field, format ``MM-DD-YY``)."""

    description: str
    """Description of the event (e.g. ``"Notice of Appeal"``,
    ``"Appellants brief"``).  From the ``eventDescription`` JS field."""

    action: str
    """Action taken (e.g. ``"Filed"``, ``"Status Changed"``,
    ``"Sent by Court"``)."""


class DWWADocket(ScrapedData):
    """A docket from the Washington DW Courts site.

    Aggregates participant info from the search-result cards and event
    entries from the case-summary page.  Maps to CourtListener
    ``Docket``."""

    docket_number: str
    """Case number as searched (e.g. ``"871463"``)."""

    court: str
    """CourtListener court id — one of :data:`DW_COURTS`' keys."""

    case_key: str
    """DW-internal case key extracted from the case-summary URL
    (e.g. ``"185253276"``).  Uniquely identifies the case in the DW
    database."""

    date_filed: date | None = None
    """Filing date from the search-result card."""

    court_name: str | None = None
    """Court display name from the case-summary page header
    (e.g. ``"COA, Division I"``)."""

    participants: list[DWWAParticipant] = []
    """Participants extracted from the search-result cards (one card
    per participant)."""

    entries: list[DWWADocketEntry] = []
    """Docket entries from the case-summary Tabulator table."""

    source_url: str | None = None
    """URL of the case-summary page."""

    source_entry_point: str | None = None
    """Entry point used to reach this docket."""
