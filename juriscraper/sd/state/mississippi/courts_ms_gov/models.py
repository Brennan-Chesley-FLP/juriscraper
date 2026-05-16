"""Data models for the Mississippi appellate courts scraper.

Both the Mississippi Supreme Court (`miss`) and the Court of Appeals of
Mississippi (`missctapp`) are served from the same backend. The court
is determined per-case from the docket-number suffix (`-SCT` / `-COA`).
"""

from __future__ import annotations

from datetime import date

from jkent.common.data_models import ScrapedData

COURT_IDS: dict[str, str] = {
    "miss": "Supreme Court of Mississippi",
    "missctapp": "Court of Appeals of Mississippi",
}

# Docket-number suffix → CourtListener court id.
# Pre-1997 cases have no suffix; we default those to ``miss`` because the
# site historically routed all appellate filings through the Supreme Court
# before the Court of Appeals was created in 1995.
SUFFIX_TO_COURT_ID: dict[str, str] = {
    "SCT": "miss",
    "COA": "missctapp",
}
DEFAULT_COURT_ID: str = "miss"


class MsAppAttorney(ScrapedData):
    """An attorney representing a party.

    The portal exposes only a display name for each attorney; firm,
    address, phone, and bar number are not surfaced via the public API.
    """

    name: str


class MsAppParty(ScrapedData):
    """A party in the case."""

    name: str
    role: str | None = None
    """Appellate role label as printed by the site, e.g. ``Appellant``,
    ``Appellee``, ``Cross-Appellant``, ``Real Party in Interest``.

    Empty for amici / interested parties shown without a role header.
    """

    attorneys: list[MsAppAttorney] = []


class MsAppDocketEntry(ScrapedData):
    """One row from the case's docket / register of actions."""

    date_filed: date | None = None
    description: str
    document_index: int | None = None
    """Position of this entry in the docket as numbered by the site
    (the ``id="desc-N"`` value). Used to join document downloads to
    their parent entry."""


class MsAppDocument(ScrapedData):
    """An archived PDF referenced from a docket entry."""

    docket_number: str
    case_num: int
    """Mississippi's internal sequential case id."""

    file_name: str
    """The ``f=`` parameter from sendPDF.php, e.g. ``500_710632.pdf``."""

    download_url: str

    description: str | None = None
    """Description text of the parent docket entry."""

    date_filed: date | None = None
    document_index: int | None = None
    """Index of the parent docket entry (matches ``MsAppDocketEntry``)."""

    local_path: str | None = None
    """Filesystem path where the driver archived this PDF."""


class MsAppTrialCourt(ScrapedData):
    """A lower-court ruling cited on the appellate docket.

    Some appellate cases consolidate rulings from multiple trial courts;
    in that case the case-info pane repeats the trial-court block once
    per ruling and we capture each as its own record.
    """

    court_name: str
    """E.g., ``Rankin Circuit Court``."""

    trial_court_case_number: str | None = None
    judge: str | None = None
    ruling_date: date | None = None


class MsAppOralArgument(ScrapedData):
    """A scheduled or archived oral argument event for the case."""

    url: str
    """Usually a Vimeo URL (livestream or recorded archive)."""

    label: str | None = None
    """Display text accompanying the link."""


class MsAppDocket(ScrapedData):
    """A complete Mississippi appellate court docket."""

    # === Searchable fields ===
    docket_number: str
    """Public docket number — modern: ``YYYY-{TYPE}-{NNNNN}-{SCT|COA}``;
    legacy: ``YY-{TYPE}-{NNNNN}`` (pre-1997)."""

    court_id: str
    """``miss`` for Supreme Court cases, ``missctapp`` for Court of
    Appeals cases. Decided from the docket-number suffix."""

    case_num: int
    """Mississippi's internal sequential case id (the ``cn=`` URL
    parameter). Stable per case."""

    case_name: str
    date_filed: date | None = None
    """Earliest docket entry date — the site does not expose a separate
    filing-date field."""

    # === Nested data ===
    entries: list[MsAppDocketEntry] = []
    parties: list[MsAppParty] = []
    trial_courts: list[MsAppTrialCourt] = []
    oral_arguments: list[MsAppOralArgument] = []

    document_count: int = 0
    """Number of archived ``MsAppDocument`` records yielded for this
    case (yielded as separate top-level records)."""

    source_url: str
    """The canonical detail URL: ``index.php?cn={case_num}#dispArea``."""
