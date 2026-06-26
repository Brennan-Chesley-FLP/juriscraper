"""Data models for the Missouri Case.net appellate scraper.

Case.net serves four appellate courts (Supreme Court + three
Court of Appeals districts) plus all 46 trial-court circuits from a
single backend. This scraper covers only the appellate courts.

Field names follow [`../../CL_MODELS.md`](../../CL_MODELS.md): the
CourtListener court-id string is ``court`` (not ``court_id``), the
public docket number is ``docket_number`` (not ``case_number``), and
dates use the ``date_*`` prefix.
"""

from __future__ import annotations

from datetime import date

from jkent.common.data_models import ScrapedData

from juriscraper.state.common_models import CleanString, HarmonizedCaseName

# CourtListener court IDs for the four Missouri appellate courts.
COURT_IDS: dict[str, str] = {
    "mo": "Supreme Court of Missouri",
    "moctapped": "Missouri Court of Appeals, Eastern District",
    "moctappsd": "Missouri Court of Appeals, Southern District",
    "moctappwd": "Missouri Court of Appeals, Western District",
}

# Site-internal courtId (`courtId` in JSON, `courtCode` on the search
# form) → CourtListener court id. Read off search results and case
# header responses to route a case to its CourtListener court.
SITE_COURT_TO_CL: dict[str, str] = {
    "OSCDB0024_SUP": "mo",
    "SMPDB0005_EAP": "moctapped",
    "SMPDB0001_SAP": "moctappsd",
    "SMPDB0001_WAP": "moctappwd",
}

# CourtListener court id → site-internal countyCode for the search form
# query string. countyCode is a separate dropdown on the form even
# though it's effectively the court's short code for appellate courts.
CL_COURT_TO_COUNTY: dict[str, str] = {
    "mo": "SUP",
    "moctapped": "EAP",
    "moctappsd": "SAP",
    "moctappwd": "WAP",
}

# CourtListener court id → site-internal courtCode (the search-form
# value). Inverse of SITE_COURT_TO_CL, kept explicit for readability.
CL_COURT_TO_SITE: dict[str, str] = {
    "mo": "OSCDB0024_SUP",
    "moctapped": "SMPDB0005_EAP",
    "moctappsd": "SMPDB0001_SAP",
    "moctappwd": "SMPDB0001_WAP",
}


class MoAttorney(ScrapedData):
    """Attorney representation record from ``cases/party.do``.

    Maps to CourtListener ``Attorney`` (+ ``Role`` for the role on this
    docket)."""

    name: CleanString
    """Formatted attorney name (LAST, FIRST MIDDLE)."""

    role: CleanString | None = None
    """Role description, e.g. "Attorney for Appellant" (CL ``role_raw``)."""

    role_code: str | None = None
    """Short code for the role, e.g. "AAPL", "ARES"."""

    address: CleanString | None = None
    """Multi-line address as returned by the API (CL ``contact_raw``)."""

    phone: str | None = None
    """Formatted phone number."""

    date_start: date | None = None
    """Date the attorney was associated with the case."""


class MoParty(ScrapedData):
    """A party in a Missouri appellate case.

    Maps to CourtListener ``Party`` (+ ``PartyType`` for the role on this
    docket)."""

    name: CleanString
    """Formatted party name."""

    role: CleanString | None = None
    """Role description, e.g. "Appellant", "Respondent" (CL
    ``PartyType.name``)."""

    role_code: str | None = None
    """Short code, e.g. "APEL", "RES"."""

    address: CleanString | None = None
    """Multi-line party address; may be empty."""

    phone: str | None = None
    """Formatted phone number; may be empty."""

    date_start: date | None = None
    """Date the party was added to the case."""

    attorneys: list[MoAttorney] = []
    """Attorneys representing this party."""


class MoTrialCourtInfo(ScrapedData):
    """Reference to an originating trial-court case.

    A Missouri appellate case can reference one or more trial-court
    cases via the ``circuitCaseNo`` array on the case header, plus an
    optional free-text ``appellateOriginNo`` line. We capture both. Maps
    loosely to CourtListener ``OriginatingCourtInformation`` /
    ``TrialCourtData``."""

    docket_number: str
    """Trial-court docket number, e.g. "24SL-CC05580"."""

    court_id: str | None = None
    """Site-internal trial court id, e.g. "CT21" (St. Louis County)."""

    label: CleanString | None = None
    """Free-text label when the value comes from the appellateOriginNo
    line rather than the circuitCaseNo array (e.g. "JASPER COUNTY
    CIRCUIT COURT 23AO-CR00672-01")."""


class MoDocketEntry(ScrapedData):
    """A single row of the Docket Entries tab.

    Maps to CourtListener ``DocketEntry``."""

    date_filed: date | None = None
    """``filingDate`` parsed from MM/DD/YYYY."""

    description: CleanString
    """``docketDesc`` — short label, e.g. "Appl for Tran SC Filed in SC"."""

    text: CleanString | None = None
    """``docketText`` — long-form free-text description, when present."""

    sequence_number: int | None = None
    """Per-case sequence number (counts up from 1, oldest first)."""

    docket_code: str | None = None
    """Short code for the entry type, e.g. "EMTR4"."""

    filing_party_name: CleanString | None = None
    """Full name of the filer (attorney or party)."""

    filing_party_role: CleanString | None = None
    """``eventDesc`` — e.g. "Attorney for Respondent"."""

    behalf_of_parties: CleanString | None = None
    """``behalfOfPartiesNames`` — names of parties on whose behalf the
    filing was made."""

    confidential: bool = False
    """True when the entry's documents are non-public."""


class MoDocument(ScrapedData):
    """A downloadable PDF attached to a docket entry.

    Maps to CourtListener ``RECAPDocument``."""

    download_url: str
    """Absolute URL to the PDF (``/fv/c/{title}.PDF?courtCode=...&di=...``)."""

    document_id: int
    """``documentId`` (a.k.a. ``cebdmsdId``) — globally-unique within Case.net."""

    document_title: CleanString
    """Display title used in the file viewer URL path (CL ``description``)."""

    document_extension: str
    """File extension reported by the API (typically "PDF")."""

    docket_sequence: int | None = None
    """``docketSeq`` — links the document back to a ``MoDocketEntry``."""

    parent_document_id: int | None = None
    """When the document is a nested attachment under another document
    (Case.net's ``documentModels`` tree — e.g. an Application for
    Transfer carries the underlying Court of Appeals opinion as a
    nested model), this is the ``documentId`` of the wrapper."""

    filepath_local: str | None = None
    """Local path written by the archive request, when downloaded (CL
    ``filepath_local``)."""


class MoDocket(ScrapedData):
    """Top-level scraped record: one Missouri appellate court case.

    Maps to CourtListener ``Docket`` (+ its per-court side tables)."""

    docket_number: str
    """Appellate docket number, e.g. "SC101613"."""

    court: str
    """CourtListener court id (one of COURT_IDS)."""

    site_court_id: str
    """Site-internal courtId, e.g. "OSCDB0024_SUP". Useful for
    constructing follow-up URLs without re-deriving from court."""

    case_name: HarmonizedCaseName
    """``caseDesc`` — style of case, e.g. "STATE V. RAMSEY COSTA"."""

    date_filed: date | None = None
    """``filingDate`` of the appellate case."""

    case_type: CleanString | None = None
    """Long-form case type label, e.g. "AP Tran to SC- Post Opinion"."""

    case_type_code: str | None = None
    """Short type code, e.g. "A5"."""

    location: CleanString | None = None
    """Court-name string returned by the API (full uppercase)."""

    disposition: CleanString | None = None
    """``caseDispositionDetail.dispositionDescription`` — "Not
    Disposed" until the case has been decided, then the disposition
    text."""

    disposed: bool = False
    """``disposed`` flag from the header."""

    dismissed: bool = False
    """True when the header ``dismissed`` field is "T"."""

    appellate_origin: CleanString | None = None
    """Free-text ``appellateOriginNo.caseValue`` describing the
    underlying lower-court chain (e.g. "JASPER COUNTY CIRCUIT COURT
    23AO-CR00672-01; SD38704")."""

    related_appellate_docket: str | None = None
    """``appellateCaseNo.caseValue`` — sibling appellate case that
    fed into this one (e.g. a Court of Appeals case whose Application
    for Transfer brought it before the Supreme Court)."""

    related_appellate_court: str | None = None
    """CourtListener id of ``related_appellate_docket``, when the
    site's courtId is recognised."""

    trial_courts: list[MoTrialCourtInfo] = []
    """Trial-court refs from ``circuitCaseNo`` plus the appellate
    origin label."""

    parties: list[MoParty] = []
    """Parties + their attorneys."""

    entries: list[MoDocketEntry] = []
    """Docket Entries tab rows, oldest-first."""

    documents: list[MoDocument] = []
    """All downloadable documents referenced by docket entries."""

    source_url: str | None = None
    """Public case page URL on courts.mo.gov."""

    source_entry_point: str | None = None
    """Entry point used to reach this docket (e.g.
    ``dockets_by_filing_date``)."""
