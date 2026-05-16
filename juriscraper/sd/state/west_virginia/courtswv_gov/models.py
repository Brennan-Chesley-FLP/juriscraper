"""Data models for the West Virginia courtswv.gov scraper.

Two CourtListener courts are involved:

- ``wva``       — Supreme Court of Appeals of West Virginia
- ``wvactapp``  — Intermediate Court of Appeals of West Virginia

The site (`courtswv.gov`) renders both court dockets through Drupal
Views with parallel field schemas (`field_sca_docket_*` vs.
`field_ica_docket_*`). The data shape is the same — we surface a single
``WVDocket`` model parametrised by ``court_id``.
"""

from __future__ import annotations

from datetime import date

from jkent.common.data_models import ScrapedData

# CourtListener IDs in scope. These are imported by the scraper so it
# can reference them by name rather than re-typing the strings.
COURT_SCA = "wva"
COURT_ICA = "wvactapp"

COURT_IDS: dict[str, str] = {
    COURT_SCA: "Supreme Court of Appeals of West Virginia",
    COURT_ICA: "Intermediate Court of Appeals of West Virginia",
}


class WVBrief(ScrapedData):
    """A brief / order linked from a case-detail page.

    Emitted top-level once the PDF has been archived. Joined back to
    its parent ``WVDocket`` on ``docket_number`` (which, for
    consolidated cases, is the component the brief is filed under —
    not the joined consolidated string).
    """

    docket_number: str
    """Docket number this brief is filed under. For consolidated cases
    the site labels component briefs with their docket-number prefix
    (``"23-753 Petitioner's Brief"``) and we store the component
    number, not the joined string."""

    court_id: str
    description: str
    """Brief label as shown on the page (e.g. ``"Petitioner's Brief"``,
    ``"23-753 Order on Appeal"``)."""

    download_url: str

    local_path: str | None = None
    """Filesystem path where the driver archived the PDF."""


class WVOrderListPDF(ScrapedData):
    """An order-list PDF surfaced from the docket listing.

    Order lists are the SCA/ICA's per-conference summary documents
    listing actions taken on a batch of cases (refusals, memorandum
    decisions, etc.). They appear in the docket listing as rows with
    no case number and a direct PDF anchor. The record captures the
    release date and PDF URL for later parsing pipelines, and is
    populated with ``local_path`` once the file has been archived.
    """

    court_id: str
    release_date: date
    """The 'docket date' of the listing row — i.e. when the order list
    was issued."""

    download_url: str
    label: str | None = None
    """Visible link text from the listing (typically ``"ORDER LIST"``)."""

    source_url: str | None = None
    """The listing page URL the row was scraped from."""

    local_path: str | None = None
    """Filesystem path where the driver archived the PDF. ``None``
    until the archive download completes."""


class WVDocket(ScrapedData):
    """One row of the WV appellate docket.

    Each detail page corresponds to one argued case (or one
    consolidated cluster). Recurring future-calendar / scheduled
    sittings are not modelled separately — the docket date and time on
    each ``WVDocket`` instance *is* the scheduled sitting.
    """

    # === Searchable / identifying fields ===
    docket_number: str
    """Primary docket number (first component for consolidated cases)."""

    court_id: str
    """``"wva"`` or ``"wvactapp"``."""

    consolidated_docket_numbers: list[str] = []
    """All docket numbers represented by this detail page. Single-case
    pages have exactly one entry (== ``docket_number``); consolidated
    pages have two or more (e.g. ``["23-753", "24-320"]``)."""

    # === Argument metadata ===
    case_name: str
    docket_date: date | None = None
    """Argument / sitting date — the row's "Docket Date" in the
    listing."""

    docket_time: str | None = None
    """Time of day for the sitting (e.g. ``"10:00 am"``); free text as
    the site renders it."""

    argument_type: str | None = None
    """``"RULE 19 ARGUMENT"``, ``"RULE 20 ARGUMENT"``, ``"ORDER LIST"``,
    ``"ADMISSIONS"``, ``"BAKER'S CUP"``, etc."""

    # === Webcast / clerk-briefs flags ===
    youtube_url: str | None = None
    """Live or archived YouTube URL for the oral argument webcast.
    Often includes a ``?t=N`` timestamp pointing at this case's slot
    inside a multi-case session."""

    clerk_has_briefs: bool = False
    """True when the docket note indicates the briefs are not posted
    online and are held only at the Clerk's office (matched on
    ``"briefs ... on file ... clerk"``-style language)."""

    # === Free-text note ===
    note: str | None = None
    """Plain-text rendering of the SCA/ICA Docket Note block, when
    present. Disqualifications, sitting-by-assignment notes, and the
    clerk-briefs sentinel all come through here."""

    source_url: str | None = None
    """The case-detail page URL this record was built from."""
