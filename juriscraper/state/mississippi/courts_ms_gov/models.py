"""Data models for the Mississippi appellate courts scraper.

Both the Mississippi Supreme Court (``miss``) and the Court of Appeals of
Mississippi (``missctapp``) are served from the same backend. The court is
determined per-case from the docket-number suffix (``-SCT`` / ``-COA``).

Field names follow [`../../CL_MODELS.md`](../../CL_MODELS.md): the
CourtListener court-id string is ``court`` (not ``court_id``), dates use the
``date_*`` prefix, and ``CleanString``/``HarmonizedCaseName`` clean free-text
fields.
"""

from __future__ import annotations

from datetime import date
from typing import ClassVar

from jkent.common.data_models import ScrapedData

from juriscraper.state.common_models import CleanString, HarmonizedCaseName

COURT_NAMES: dict[str, str] = {
    "miss": "Supreme Court of Mississippi",
    "missctapp": "Court of Appeals of Mississippi",
}

# Docket-number suffix → CourtListener court id.
# Pre-1997 cases have no suffix; we default those to ``miss`` because the
# site historically routed all appellate filings through the Supreme Court
# before the Court of Appeals was created in 1995.
SUFFIX_TO_COURT: dict[str, str] = {
    "SCT": "miss",
    "COA": "missctapp",
}
DEFAULT_COURT: str = "miss"


# =========================================================================
# Site constants
# =========================================================================

BASE_URL: str = "https://courts.ms.gov"
INDEX_URL: str = f"{BASE_URL}/index.php"
BUILD_DOCKET_URL: str = f"{BASE_URL}/appellatecourts/docket/build_docket.php"


# =========================================================================
# Data models
# =========================================================================


class MsAppCaseUnavailable(ScrapedData):
    """Yielded when a speculative ``case_num`` search returns the portal's
    "no public results" page instead of a docket.

    Mirrors California's ``CaAppCaseUnavailable``: it records the searched
    id for bookkeeping so a speculative miss is a captured outcome rather
    than a silent no-op. The portal does not distinguish among the reasons
    a case may be absent — the number was never assigned, the case is not
    yet filed, or it is sealed/confidential — so none is asserted here.

    Unlike ``MsAppDocket`` this carries no ``court``: the court is decided
    from the docket-number suffix, which an unavailable case never exposes.
    """

    case_num: int
    """Mississippi's internal sequential case id that was searched (the
    ``cn=`` / ``case_num`` request parameter)."""


class MsAppAttorney(ScrapedData):
    """A single attorney representing a party.

    The portal exposes only a display name for each attorney; firm,
    address, phone, and bar number are not surfaced via the public API.
    Maps to CourtListener ``Attorney``.
    """

    name: CleanString


class MsAppParty(ScrapedData):
    """A party in the case.

    Maps to CourtListener ``Party`` (+ ``PartyType`` for the role on this
    docket).
    """

    name: CleanString
    role: CleanString | None = None
    """Appellate role label as printed by the site, e.g. ``Appellant``,
    ``Appellee``, ``Cross-Appellant``, ``Real Party in Interest`` (CL
    ``PartyType.name``).

    Empty for amici / interested parties shown without a role header.
    """

    attorneys: list[MsAppAttorney] = []


class MsAppDocketEntry(ScrapedData):
    """One row from the case's docket / register of actions.

    Maps to CourtListener ``DocketEntry``.
    """

    date_filed: date | None = None
    description: CleanString
    document_index: int | None = None
    """Position of this entry in the docket as numbered by the site
    (the ``id="desc-N"`` value). Used to join document downloads to
    their parent entry."""


class MsAppDocument(ScrapedData):
    """An archived PDF referenced from a docket entry.

    Maps to CourtListener ``RECAPDocument``.
    """

    docket_number: str
    case_num: int
    """Mississippi's internal sequential case id."""

    file_name: str
    """The ``f=`` parameter from sendPDF.php, e.g. ``500_710632.pdf``."""

    download_url: str

    description: CleanString | None = None
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
    per ruling and we capture each as its own record. Maps to CourtListener
    ``OriginatingCourtInformation`` / ``TrialCourtData``.
    """

    court_name: CleanString
    """E.g., ``Rankin Circuit Court``."""

    trial_court_case_number: CleanString | None = None
    judge: CleanString | None = None
    """Trial judge name (CL ``judge_str``)."""
    ruling_date: date | None = None
    """Date of the trial-court ruling (CL ``date_judgment``)."""


class MsAppOralArgument(ScrapedData):
    """A scheduled or archived oral argument event for the case."""

    url: str
    """Usually a Vimeo URL (livestream or recorded archive)."""

    label: CleanString | None = None
    """Display text accompanying the link."""


class MsAppDocket(ScrapedData):
    """A complete Mississippi appellate court docket — main scraper output.

    Maps to CourtListener ``Docket``.
    """

    # === Searchable fields ===
    docket_number: str
    """Public docket number — modern: ``YYYY-{TYPE}-{NNNNN}-{SCT|COA}``;
    legacy: ``YY-{TYPE}-{NNNNN}`` (pre-1997)."""

    court: str
    """``miss`` for Supreme Court cases, ``missctapp`` for Court of
    Appeals cases. Decided from the docket-number suffix."""

    case_num: int
    """Mississippi's internal sequential case id (the ``cn=`` URL
    parameter). Stable per case."""

    case_name: HarmonizedCaseName
    date_filed: date | None = None
    """Earliest docket entry date — the site does not expose a separate
    filing-date field."""

    is_consolidated: bool = False
    """Whether the caption carries the "Consolidated with case(s):" header,
    i.e. the case is part of a consolidation group. Distinguishes a
    standalone case (``False``) from a consolidated one whose sibling
    numbers the site happens not to list (``True`` with an empty
    ``consolidated_with``)."""

    consolidated_with: list[str] = []
    """Public docket numbers of other cases consolidated with this one, as
    printed under the caption's "Consolidated with case(s):" header. Empty
    for standalone cases *and* for the occasional consolidated case that
    lists no siblings (use ``is_consolidated`` to tell those apart). These
    are the sibling cases' docket-number strings (e.g. ``94-CA-01302-SCT``),
    not this case's own number."""

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

    source_entry_point: str | None = None
    """Entry point used to reach this docket (e.g.
    ``dockets_by_internal_id``)."""


class _MsAppConfig:
    """Site configuration constants, kept off the public model classes."""

    BASE_URL: ClassVar[str] = BASE_URL
    INDEX_URL: ClassVar[str] = INDEX_URL
    BUILD_DOCKET_URL: ClassVar[str] = BUILD_DOCKET_URL
    SUFFIX_TO_COURT: ClassVar[dict[str, str]] = SUFFIX_TO_COURT
    DEFAULT_COURT: ClassVar[str] = DEFAULT_COURT
    COURT_NAMES: ClassVar[dict[str, str]] = COURT_NAMES
