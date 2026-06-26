"""Data models for the Wisconsin WSCCA scraper.

Data source:
- https://wscca.wicourts.gov/case-search

Supported courts:
- wis:      Wisconsin Supreme Court              (site courtType "SC")
- wisctapp: Wisconsin Court of Appeals (Districts 1-4, all roll up to
                                                   one CourtListener id;
                                                   site courtType "CA")

Case numbers are uniformly ``YYYY`` + 2-letter type code + 6-digit
sequence (e.g. ``2022AP000001``). The site auto-normalizes shorter
forms (``22AP1``) on submission; we always carry the canonical form.

Field names follow [`../../CL_MODELS.md`](../../CL_MODELS.md): the
CourtListener court-id string is ``court`` (not ``court_id``), the case
number is ``docket_number`` (not ``case_number``/``case_id``), and dates
use the ``date_*`` prefix.
"""

from __future__ import annotations

from datetime import date

from jkent.common.data_models import ScrapedData

from juriscraper.state.common_models import CleanString, HarmonizedCaseName

# Site courtType code -> CourtListener court id.
SITE_COURT_TYPE_TO_CL_ID: dict[str, str] = {
    "SC": "wis",
    "CA": "wisctapp",
}

# CourtListener id -> human-readable display name. Both CA districts
# fold into ``wisctapp``; districts are preserved on each WiDocket.
COURT_IDS: dict[str, str] = {
    "wis": "Wisconsin Supreme Court",
    "wisctapp": "Wisconsin Court of Appeals",
}


class WiDocketEntry(ScrapedData):
    """A single docket entry from the case's ``pastEvents`` or
    ``upcomingEvents`` array.

    Future-calendar / upcoming events are folded into this same type
    (per the kent convention) — distinguished by ``is_future``.

    Maps loosely to CourtListener ``DocketEntry``.
    """

    event_seq_no: int
    """Site-assigned sequential id for the event within the case."""

    date_filed: date | None = None
    """Filing / occurrence date for the event."""

    description: str
    """Short label (e.g. ``"Brief of Appellant"``, ``"Opinion/Decision"``,
    ``"Notice of Appeal & Circuit Court Docket Entries"``)."""

    sub_event_text: CleanString | None = None
    """Free-form details exposed when the row is expanded
    (filer, judge panel, decision text, etc.)."""

    additional_text: CleanString | None = None
    """Auxiliary comment column, often used for record / receipt notes."""

    due_date: date | None = None
    """Populated only on scheduled / delinquency-style events."""

    event_status_code: CleanString | None = None
    """E.g. ``"OCCD"`` (occurred). Normalized as-is from the API."""

    court_type_code: CleanString | None = None
    """``"CA"`` or ``"SC"`` — the court that emitted the event."""

    is_future: bool = False
    """True for ``upcomingEvents`` rows; False for ``pastEvents``."""


class WiAttorney(ScrapedData):
    """Attorney representation record.

    Maps to CourtListener ``Attorney`` (+ ``Role`` for the
    representation on this docket)."""

    name_last: CleanString | None = None
    name_first: CleanString | None = None
    name_middle: CleanString | None = None
    name_suffix: CleanString | None = None

    entered_date: date | None = None
    """Date attorney entered an appearance for the party."""

    withdrew_date: date | None = None
    """Date attorney withdrew (None when still active)."""

    atty_seq_no: int | None = None
    """Site-internal attorney sequence number (stable per-attorney id)."""


class WiParty(ScrapedData):
    """A party in the appellate case.

    Maps to CourtListener ``Party`` (+ ``PartyType`` for the role on
    this docket)."""

    name_last: CleanString | None = None
    """Last name for individuals; full business name for entities."""

    name_first: CleanString | None = None
    name_middle: CleanString | None = None
    name_suffix: CleanString | None = None

    party_types: list[str] = []
    """Roles within the case (e.g. ``["Plaintiff", "Appellant"]``,
    ``["Defendant", "Respondent"]``)."""

    party_seq_no: int | None = None
    """Site-assigned sequence id within this case."""

    attorneys: list[WiAttorney] = []
    """Attorneys representing this party."""


class WiCircuitCourtCase(ScrapedData):
    """Linked circuit-court (trial-court) case from ``ccCaseData``.

    Maps loosely to CourtListener ``OriginatingCourtInformation`` /
    ``TrialCourtData``."""

    cc_case_no: str
    cc_county: CleanString | None = None
    cc_county_no: int | None = None
    judge_name: CleanString | None = None
    """Circuit court judge of record (``ctofcName``)."""
    responsible_judge_name: CleanString | None = None
    """Currently responsible circuit court judge (``respCtofcName``)."""
    legacy_case_link: str | None = None
    """WCCA URL for the trial-court case detail."""


class WiCitation(ScrapedData):
    """Reporter citation (from ``citnData``)."""

    volume: CleanString | None = None
    publisher: CleanString | None = None
    page: int | None = None
    court_type_code: CleanString | None = None
    doc_seq_no: int | None = None


class WiDocument(ScrapedData):
    """A downloadable filing on the case (one row from ``documents``).

    Maps to CourtListener ``RECAPDocument``."""

    doc_id: int
    """Site-assigned document id used in the download URL path."""

    doc_name: str
    """Display name (e.g. ``"Brief of Appellant"``)."""

    event_descr: CleanString | None = None
    """Originating event description
    (e.g. ``"Brief & Appendix of Appellant(s)"``)."""

    event_code: CleanString | None = None
    """Internal event-type code (e.g. ``"BAP"``, ``"BRS"``, ``"BRY"``)."""

    event_seq_no: int | None = None
    """Cross-references the matching ``WiDocketEntry.event_seq_no``."""

    pages: CleanString | None = None
    """Page range as displayed (e.g. ``"1-14"``)."""

    doc_stamp_date: date | None = None
    """Date the document was filed/stamped."""

    download_url: str
    """``/api/case/{caseNo}/document/{docId}`` (resolved to absolute)."""

    local_path: str | None = None
    """Local filesystem path after archiving (populated downstream)."""


class WiDocket(ScrapedData):
    """A Wisconsin appellate-court docket — main scraper output.

    Built from the JSON object at ``/api/case/{caseNo}``. Maps to
    CourtListener ``Docket`` (+ its per-court side tables)."""

    docket_number: str
    """Canonical 12-character case number, e.g. ``"2022AP000001"``
    (CL ``Docket.docket_number``)."""

    court: str
    """CourtListener court id: ``"wis"`` or ``"wisctapp"``."""

    court_type_code: str
    """Site code: ``"SC"`` or ``"CA"``."""

    case_name: HarmonizedCaseName
    """Short caption (e.g. ``"Jennifer Buth v. Daniel Pyawasay"``)."""

    case_name_full: CleanString | None = None
    """Full multi-line caption with party roles (``longCaption``)."""

    date_filed: date | None = None
    """Initial appellate filing date."""

    case_status_code: CleanString | None = None
    """One of ``CL`` / ``OP`` / ``PR`` / ``RE`` / ``RM`` / ``RO``."""

    case_status_description: CleanString | None = None
    """Friendly version of ``case_status_code``."""

    class_code: CleanString | None = None
    """WCIS class code (e.g. ``"30301"``)."""

    class_code_description: CleanString | None = None
    """Friendly version of ``class_code`` (e.g. ``"Money Judgment"``)."""

    filing_district: int | None = None
    """District at filing (CA only; 1-4)."""

    current_district: int | None = None
    """District currently handling the case (CA only; 1-4)."""

    panel_str: CleanString | None = None
    """Panel size (e.g. ``"3"`` or ``"3 Judge Panel"``). CL
    ``Docket.panel_str``."""

    county_name: CleanString | None = None
    county_no: int | None = None

    disposition_code: CleanString | None = None
    disposition_description: CleanString | None = None
    date_disposition: date | None = None
    """Disposition date (``dispoDate``)."""

    is_confidential: bool = False
    """True if the case is flagged confidential by the clerk."""

    case_suffix: CleanString | None = None
    """Optional suffix used for consolidated / re-opened cases."""

    parties: list[WiParty] = []
    entries: list[WiDocketEntry] = []
    """Combined list of ``pastEvents`` + ``upcomingEvents``,
    distinguished by ``WiDocketEntry.is_future``."""
    documents: list[WiDocument] = []
    citations: list[WiCitation] = []
    """Reporter citations (Wis. 2d, N.W.2d, etc.)."""
    circuit_court_cases: list[WiCircuitCourtCase] = []
    """Linked trial-court cases."""

    rss_url: str | None = None
    """``/rss/case/{caseNo}`` per-case RSS feed (resolved to absolute)."""

    source_url: str | None = None
    """Public case-detail SPA URL (``/case/{caseNo}``)."""

    source_entry_point: str | None = None
    """Entry point used to reach this docket (e.g.
    ``dockets_by_number``)."""


class WiDownloadedDocument(ScrapedData):
    """A document file fetched via archive=True.

    Emitted separately so document archiving can proceed independently
    of docket assembly. Join back to the parent docket via
    ``(court, docket_number, doc_id)``."""

    court: str
    docket_number: str
    doc_id: int
    download_url: str
    local_path: str | None = None
