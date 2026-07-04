"""Data models for the NYSCEF appellate scraper (iapps.courts.state.ny.us).

These models capture appellate case data from the New York State Courts
Electronic Filing system (NYSCEF), which hosts electronic-filing records
for the four Appellate Division departments and the Court of Claims.

Data source:
- https://iapps.courts.state.ny.us/nyscef/

Courts covered (CourtListener IDs):
- ``nyappd1`` Appellate Division - 1st Dept
- ``nyappd2`` Appellate Division - 2nd Dept
- ``nyappd3`` Appellate Division - 3rd Dept
- ``nyappd4`` Appellate Division - 4th Dept
- ``nysctcl`` NYS Court of Claims

Case number format: ``YYYY-NNNNN`` (e.g. ``2024-00003``).

Field names follow [`../../CL_MODELS.md`](../../CL_MODELS.md): the
CourtListener court-id string is ``court`` (not a display name), the case
identifier is ``docket_number`` (not ``case_number``), and dates use the
``date_*`` prefix. The verbatim site court name is kept in
``court_name_raw`` and the verbatim docket string in ``docket_number_raw``.
"""

from __future__ import annotations

from datetime import date

from jkent.common.data_models import ScrapedData

from juriscraper.state.common_models import CleanString, HarmonizedCaseName

# CL court id → the <select name="txtCounty"> option value on the NYSCEF
# CaseSearch form. Used to seed date searches per court.
COURT_TO_COUNTY: dict[str, str] = {
    "nyappd1": "95",  # Appellate Division - 1st Dept
    "nyappd2": "96",  # Appellate Division - 2nd Dept
    "nyappd3": "97",  # Appellate Division - 3rd Dept
    "nyappd4": "98",  # Appellate Division - 4th Dept
    "nysctcl": "99",  # NYS Court of Claims
}

# Verbatim court name (as it appears on the results/detail pages) → CL court
# id. Used to resolve ``court`` from a result row when the entry point did not
# pin a single court (the ``docket_by_number`` flow).
COURT_NAME_TO_ID: dict[str, str] = {
    "Appellate Division - 1st Dept": "nyappd1",
    "Appellate Division - 2nd Dept": "nyappd2",
    "Appellate Division - 3rd Dept": "nyappd3",
    "Appellate Division - 4th Dept": "nyappd4",
    "NYS Court of Claims": "nysctcl",
    "Court of Claims": "nysctcl",
}


class NYSCEFAttorneyRep(ScrapedData):
    """An attorney representation record from the Case Detail page.

    Maps to CourtListener ``Attorney`` (+ ``AttorneyOrganization`` for the
    firm, ``Role`` for the representation date)."""

    name: CleanString
    """Attorney name (e.g. ``FLYNN, ERIN K``)."""

    firm: CleanString | None = None
    """Law-firm / organisation name, if listed."""

    date_consent: date | None = None
    """Date the attorney entered an appearance (from ``on MM/DD/YYYY``).
    CL ``Role.date_action`` is the nearest analogue."""


class NYSCEFParty(ScrapedData):
    """A party from the Case Detail page.

    Maps to CourtListener ``Party`` (+ ``PartyType`` for the role on this
    docket)."""

    name: CleanString
    """Party name (e.g. ``Melissa Fawer``)."""

    role: CleanString | None = None
    """Party's role on the docket (CL ``PartyType.name``): ``Appellant`` /
    ``Respondent`` / ``Petitioner`` / etc. May be compound
    (``Plaintiff-Appellant``). ``None`` when not parseable."""

    party_group: CleanString | None = None
    """Section heading the party appeared under (``Petitioners`` /
    ``Respondents``)."""

    attorneys: list[NYSCEFAttorneyRep] = []
    """Attorneys representing this party."""


class NYSCEFDocketEntry(ScrapedData):
    """A document row from the Document List page.

    Maps to CourtListener ``DocketEntry`` (+ ``RECAPDocument`` for the
    file)."""

    entry_number: int
    """Document sequence number (the ``#`` column). CL ``entry_number``."""

    document_type: CleanString
    """Document type (e.g. ``APPELLANT'S BRIEF``, ``DECISION AND ORDER``)."""

    description: CleanString | None = None
    """Extra description text after the link (e.g. ``Volume 1 of 2``)."""

    filed_by: CleanString | None = None
    """Person/entity who filed the document."""

    date_filed: date | None = None
    """Date filed (``Filed: MM/DD/YYYY``). CL ``DocketEntry.date_filed``."""

    date_received: date | None = None
    """Date received by the court (``Received: MM/DD/YYYY``)."""

    status: CleanString | None = None
    """Processing status (e.g. ``Processed``)."""

    download_url: str | None = None
    """Absolute URL to view/download the document
    (``ViewDocument?docIndex=...``)."""

    confirmation_notice_url: str | None = None
    """Absolute URL of the confirmation-notice PDF
    (``ConfirmationNotice?docId=...``), if present."""


class NYSCEFDownloadedDocument(ScrapedData):
    """A downloaded document file from the NYSCEF Document List page.

    Maps to CourtListener ``RECAPDocument``. Yielded separately from
    ``NYSCEFCase`` so archive downloads proceed independently; join back to
    the parent case via ``iapps_internal_docket_id``."""

    iapps_internal_docket_id: str
    """NYSCEF internal docket id (base64) — join key to ``NYSCEFCase``."""

    entry_number: int
    """Document sequence number within the case (matches
    ``NYSCEFDocketEntry.entry_number``)."""

    document_type: CleanString
    """Document type (e.g. ``APPELLANT'S BRIEF``)."""

    download_url: str
    """Source URL (``ViewDocument?docIndex=...``)."""

    local_path: str | None = None
    """Local filesystem path where the file was saved (set by the driver)."""


class NYSCEFCase(ScrapedData):
    """A case from the NYSCEF system — the main scraper output.

    Maps to CourtListener ``Docket`` (+ ``OriginatingCourtInformation`` for
    the court-of-original-instance fields). Combines data from three pages:
    Search Results (basic info), Case Detail (parties, originating court,
    full caption), and Document List (filed documents)."""

    # === Identifiers ===
    docket_number: str
    """NYSCEF case number, cleaned (e.g. ``2024-00003``). CL
    ``docket_number``."""

    docket_number_raw: str | None = None
    """Verbatim case-number string as found on the page, if it differs."""

    court: str
    """CourtListener court id (e.g. ``nyappd1``). Resolved from the entry
    point or from the result-row court name via ``COURT_NAME_TO_ID``."""

    court_name_raw: str | None = None
    """Verbatim court name as displayed on the site (e.g. ``Appellate
    Division - 1st Dept``)."""

    iapps_internal_docket_id: str | None = None
    """NYSCEF internal docket id (base64, from the URL ``docketId`` param)."""

    # === Case info ===
    case_name: HarmonizedCaseName | None = None
    """Full case caption with all parties. CL ``case_name``."""

    case_name_short: CleanString | None = None
    """Short caption (e.g. ``AC 31, LLC v. Melissa Fawer et al``). CL
    ``case_name_short``."""

    case_type: CleanString | None = None
    """Case type (e.g. ``Civil Action - General``)."""

    efiling_status: CleanString | None = None
    """eFiling status (e.g. ``Partial Participation Recorded``)."""

    case_status: CleanString | None = None
    """Case status from the search results, if present."""

    date_received: date | None = None
    """Date the case was received/filed in NYSCEF. CL ``date_filed``."""

    # === Originating court (appellate cases) → CL OriginatingCourtInformation
    originating_court_index: CleanString | None = None
    """Index number from the court of original instance
    (e.g. ``850250/2017``). CL ``OriginatingCourtInformation.docket_number``."""

    originating_court_name: CleanString | None = None
    """Court of original instance (e.g. ``New York Supreme Civil``)."""

    originating_court_judge: CleanString | None = None
    """Judge from the court of original instance. CL ``assigned_to_str``."""

    date_order_appealing_from: date | None = None
    """Date of the order being appealed."""

    date_notice_of_appeal: date | None = None
    """Date of the notice of appeal."""

    date_order_entered: date | None = None
    """Date the order was entered."""

    date_notice_of_appeal_filed: date | None = None
    """Date the notice of appeal was filed. CL
    ``OriginatingCourtInformation.date_filed_noa``."""

    requested_argument_time: CleanString | None = None
    """Requested argument time (e.g. ``Appellant :15 / Respondent :15``)."""

    # === Parties & documents ===
    parties: list[NYSCEFParty] = []
    """All parties in the case with their attorneys."""

    docket_entries: list[NYSCEFDocketEntry] = []
    """All documents filed in the case (CL ``DocketEntry`` rows)."""

    # === Provenance ===
    source_url: str | None = None
    """Absolute URL of the page this record was assembled from."""

    source_entry_point: str | None = None
    """Entry point used to reach this case (e.g. ``dockets_by_filing_date``)."""
