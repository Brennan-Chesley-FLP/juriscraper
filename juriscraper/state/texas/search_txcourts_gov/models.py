"""Data models for the Texas appellate-courts scraper (TAMES).

These models subclass ``ScrapedData`` from jkent to capture docket data for
all 17 Texas appellate courts that share the TAMES search interface:

- The Texas Supreme Court (``tex``)
- The Texas Court of Criminal Appeals (``texcrimapp``)
- The 15 Texas intermediate Courts of Appeals (``texapp``, with the
  individual district preserved on the docket via ``coa_district``)

The shape mirrors the legacy TypedDicts in
``juriscraper.state.texas.{common,supreme_court,court_of_criminal_appeals,court_of_appeals}``
but re-typed as ``ScrapedData`` for the kent pipeline. Fields that are
specific to one court (e.g. ``publication_service``, ``transfer_from`` for
COAs; ``appeals_court_ref`` for SC / CCA) are made ``Optional`` so a single
``TexasDocket`` type can carry data from any of the three court flavors.

Field names follow [`../../CL_MODELS.md`](../../CL_MODELS.md): the
CourtListener court-id string is ``court`` (not ``court_id``), the docket
number is ``docket_number`` (not ``case_number``/``docket_id``), and dates
use the ``date_*`` prefix. ``CleanString`` / ``HarmonizedCaseName`` cleaning
types come from ``juriscraper.state.common_models``.
"""

from __future__ import annotations

from datetime import date
from typing import ClassVar

from jkent.common.data_models import ScrapedData

from juriscraper.state.common_models import CleanString, HarmonizedCaseName

# =========================================================================
# Site constants
# =========================================================================

BASE_URL: str = "https://search.txcourts.gov"
SEARCH_URL: str = f"{BASE_URL}/CaseSearch.aspx"

# CourtListener court IDs this scraper covers.
SUPREME_COURT_ID: str = "tex"
COURT_OF_CRIMINAL_APPEALS_ID: str = "texcrimapp"
COURT_OF_APPEALS_ID: str = "texapp"

COURT_NAMES: dict[str, str] = {
    SUPREME_COURT_ID: "Texas Supreme Court",
    COURT_OF_CRIMINAL_APPEALS_ID: "Texas Court of Criminal Appeals",
    COURT_OF_APPEALS_ID: "Texas Courts of Appeals (1st-15th)",
}

COA_DISTRICT_NAMES: dict[int, str] = {
    1: "First Court of Appeals",
    2: "Second Court of Appeals",
    3: "Third Court of Appeals",
    4: "Fourth Court of Appeals",
    5: "Fifth Court of Appeals",
    6: "Sixth Court of Appeals",
    7: "Seventh Court of Appeals",
    8: "Eighth Court of Appeals",
    9: "Ninth Court of Appeals",
    10: "Tenth Court of Appeals",
    11: "Eleventh Court of Appeals",
    12: "Twelfth Court of Appeals",
    13: "Thirteenth Court of Appeals",
    14: "Fourteenth Court of Appeals",
    15: "Fifteenth Court of Appeals",
}


class TexasDocument(ScrapedData):
    """A single downloadable document linked from a docket entry.

    Maps to CourtListener ``RECAPDocument``. Document anchors on TAMES
    look like::

        SearchMedia.aspx?MediaVersionID=<UUID>&coa=coaNN&DT=<DocType>&MediaID=<UUID>

    The ``MediaID`` is the durable identifier; ``MediaVersionID`` changes
    across revisions of the same document.
    """

    download_url: str
    """Absolute URL of the document (joined onto search.txcourts.gov)."""

    media_id: str | None = None
    """``MediaID`` query parameter — durable identifier for the document."""

    media_version_id: str | None = None
    """``MediaVersionID`` query parameter — changes when the document is
    revised; pair with ``media_id`` to uniquely identify a revision."""

    document_type: CleanString | None = None
    """``DT`` query parameter (e.g. ``Brief``, ``Opinion``, ``Order``)."""

    description: CleanString | None = None
    """Free-text description from the table cell next to the link."""

    file_size_bytes: int | None = None
    """Parsed from the ``[ PDF/NNN KB ]`` anchor text. None if not present."""

    file_size_str: CleanString | None = None
    """Raw size hint from the anchor text (e.g. ``PDF/348 KB``)."""

    local_path: str | None = None
    """Local filesystem path once the file is archived (set by the driver
    when this document is emitted standalone from the archive handler;
    always ``None`` on the copies embedded in ``TexasDocket.documents``
    and ``TexasDocketEntry.documents``)."""

    docket_number: str | None = None
    """Parent docket number, set on the standalone post-archive emission
    so consumers can join the file back to its docket. ``None`` on the
    embedded copies."""

    docket_entry_kind: str | None = None
    """``"event"`` / ``"brief"`` — which table this document was attached
    to. Set on the standalone post-archive emission; ``None`` on the
    embedded copies."""

    docket_entry_number: int | None = None
    """1-based oldest-first index of the parent docket entry within its
    kind. Set on the standalone post-archive emission; ``None`` on the
    embedded copies."""


class TexasDocketEntry(ScrapedData):
    """One row from the Case Events or Appellate Briefs table.

    Maps to CourtListener ``DocketEntry``. The page presents these as two
    separate Telerik RadGrids (``grdEvents`` and ``grdBriefs``); they're
    modelled as a single entry type, disambiguated by ``kind``. Case
    Events carry a ``disposition``; Appellate Briefs carry a
    ``description``. Supreme Court entries (events and briefs)
    additionally carry a ``remarks`` column.
    """

    kind: str
    """``"event"`` for Case Events rows, ``"brief"`` for Appellate Briefs."""

    entry_number: int | None = None
    """1-based oldest-first index within this entry's ``kind``. The TAMES
    page sorts each table newest-first; we re-number bottom-to-top so the
    oldest row in each table is ``entry_number=1`` and the most recent row
    is ``entry_number=N``. ``None`` if numbering couldn't be assigned."""

    date_filed: date | None = None
    """Parsed ``Date`` column. ``None`` if the cell is blank/malformed."""

    event_type: CleanString
    """``Event Type`` column."""

    disposition: CleanString | None = None
    """``Disposition`` column (Case Events only). Empty / missing → None."""

    description: CleanString | None = None
    """``Description`` column (Appellate Briefs only). Empty → None."""

    remarks: CleanString | None = None
    """``Remarks`` column (Supreme Court only — both events and briefs).
    Empty / not present on COA and CCA pages."""

    documents: list[TexasDocument] = []
    """Documents attached to this entry, parsed from the nested doc table."""


class TexasParty(ScrapedData):
    """A party in the case, with the list of attorneys representing them.

    Maps to CourtListener ``Party`` (+ ``PartyType`` for the role)."""

    name: CleanString
    """Party name as it appears on TAMES."""

    role: CleanString
    """``PartyType`` value (e.g. ``Appellant``, ``Appellee``, ``Amicus``)."""

    representatives: list[str] = []
    """Each line of the ``Representative`` cell — typically one attorney
    name per line. Texas does not give attorney addresses or bar numbers
    on the docket page."""


class TexasOriginatingCourt(ScrapedData):
    """The trial / originating court information embedded in the docket.

    Maps to CourtListener ``OriginatingCourtInformation``."""

    name: CleanString
    """Court name as printed on TAMES (not normalized)."""

    court_type: CleanString
    """Normalized type from the legacy parser: ``texas_district``,
    ``texas_county``, ``texas_business``, ``texas_probate``,
    ``texas_justice``, ``texas_municipal``, ``texas_appellate``, or
    ``texas_unknown``."""

    county: CleanString | None = None
    """Texas county the court sits in."""

    assigned_to_str: CleanString | None = None
    """Presiding trial-court judge (CL ``assigned_to_str``). Often blank."""

    docket_number: CleanString | None = None
    """Trial-court docket number (``Court Case`` field)."""

    reporter: CleanString | None = None
    """Court reporter name. Often blank."""

    punishment: CleanString | None = None
    """Sentence / punishment for criminal cases. Empty for civil."""

    district: int | None = None
    """For district trial courts, the district number (e.g. 274)."""

    court: str | None = None
    """For appellate originating courts, the CourtListener ID (always
    ``texapp`` for Texas COA → COA transfers). None otherwise."""


class TexasTransfer(ScrapedData):
    """A case transferred between two Courts of Appeals (COA-only).

    Maps to CourtListener ``CaseTransfer``. Texas COAs balance workload by
    transferring cases to each other; the docket records both sides of the
    transfer.
    """

    other_court_name: CleanString
    """The other COA's display name (e.g. ``First Court of Appeals``)."""

    other_coa_district: int | None = None
    """The other COA's ordinal (1-15), if parsable from the court name."""

    transfer_date: date | None = None
    """Date the transfer happened."""

    origin_docket_number: CleanString | None = None
    """Docket number on the originating side of the transfer."""


class TexasAppealsCourtRef(ScrapedData):
    """Reference to a Court of Appeals that previously heard a case.

    Appears on Supreme Court and Court of Criminal Appeals dockets (the
    ``divCOAInfo`` panel), pointing back to the intermediate COA that
    issued the decision being reviewed.
    """

    docket_number: CleanString | None = None
    """Docket number at the COA (format ``NN-NN-NNNNN-XX``)."""

    case_url: str | None = None
    """Absolute URL of the COA case detail page."""

    disposition: CleanString | None = None
    """COA disposition (e.g. ``Affirmed``, ``Reversed and Remanded``)."""

    opinion_cite: CleanString | None = None
    """Citation for the COA opinion, if any."""

    district: CleanString | None = None
    """Raw COA district label as printed on the page."""

    court: str | None = None
    """CourtListener court ID of the COA. Always ``texapp`` for COAs that
    we can resolve, ``None`` if the district couldn't be parsed."""

    coa_district: int | None = None
    """Numeric COA district (1-15), parsed from ``district``."""

    justice: CleanString | None = None
    """Name of the COA justice who authored the opinion, if listed."""


class TexasDocket(ScrapedData):
    """A docket from any Texas appellate court reached via TAMES.

    Maps to CourtListener ``Docket`` (+ its per-court side tables). This is
    the top-level output of the scraper. One instance per case. ``court``
    identifies the issuing court; per-court fields (``coa_district`` for
    COAs, ``appeals_court_ref`` for SC / CCA, ``publication_service`` +
    ``transfer_from`` / ``transfer_to`` for COAs) are populated as
    available.
    """

    docket_number: str
    """Docket number as printed on TAMES. Format varies per court — see
    ``DOCKET_NUMBER_REGEXES`` in ``juriscraper.state.texas.common``."""

    court: str
    """CourtListener court ID. One of:
    - ``tex`` (Texas Supreme Court)
    - ``texcrimapp`` (Court of Criminal Appeals)
    - ``texapp`` (any of the 15 intermediate Courts of Appeals)"""

    coa_district: int | None = None
    """Court of Appeals ordinal, 1-15. Set only when ``court == texapp``.
    Derived from the docket number's leading two digits."""

    court_name: CleanString | None = None
    """Full name of the issuing court (e.g. ``First Court of Appeals``,
    ``Texas Supreme Court``)."""

    case_name: HarmonizedCaseName
    """Heuristically shortened case caption (``Foo v. Bar``)."""

    case_name_full: HarmonizedCaseName
    """Unshortened case caption from the TAMES ``style`` / ``v`` fields."""

    case_type: CleanString | None = None
    """Free-text case type (e.g. ``Civil Case``, ``Original Proceeding``)."""

    date_filed: date | None = None
    """Date the case was filed at this court. Parsed from ``Date Filed``."""

    parties: list[TexasParty] = []
    """Parties involved, with their attorneys."""

    originating_court: TexasOriginatingCourt | None = None
    """The trial (or other) court the case came up from."""

    entries: list[TexasDocketEntry] = []
    """Combined Case Events + Appellate Briefs rows, in document order.
    Distinguish via ``kind`` (``"event"`` vs ``"brief"``)."""

    documents: list[TexasDocument] = []
    """Flat list of all documents linked from the docket (a denormalized
    union of every entry's ``documents``). Useful for archival sweeps."""

    # COA-only fields ---------------------------------------------------

    publication_service: CleanString | None = None
    """Name of the publication service that published the case. COA-only;
    usually blank even on COA pages."""

    transfer_from: TexasTransfer | None = None
    """If this case was transferred in from another COA. COA-only."""

    transfer_to: TexasTransfer | None = None
    """If this case was transferred out to another COA. COA-only."""

    # SC / CCA-only fields ---------------------------------------------

    appeals_court_ref: TexasAppealsCourtRef | None = None
    """Reference to the COA that previously heard this case. Appears on
    Supreme Court and Court of Criminal Appeals dockets only."""

    source_url: str | None = None
    """URL of the Case.aspx page this data was parsed from."""

    source_entry_point: str | None = None
    """Entry point used to reach this docket (e.g. ``dockets_by_filing_date``)."""


class _TexasTamesConfig:
    """Site configuration constants, kept off the public model classes."""

    BASE_URL: ClassVar[str] = BASE_URL
    SEARCH_URL: ClassVar[str] = SEARCH_URL
    COURT_NAMES: ClassVar[dict[str, str]] = COURT_NAMES
    COA_DISTRICT_NAMES: ClassVar[dict[int, str]] = COA_DISTRICT_NAMES
