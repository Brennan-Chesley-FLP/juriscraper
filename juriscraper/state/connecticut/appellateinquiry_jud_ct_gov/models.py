"""Data models for the Connecticut appellate-inquiry docket scraper.

Records scraped from ``appellateinquiry.jud.ct.gov`` (Supreme Court ``conn``
and Appellate Court ``connappct``) and, via the trial-court link followed off
each appellate case, ``civilinquiry.jud.ct.gov`` (Superior Court
``connsuperct``).

Field names follow ``CL_MODELS.md`` so the downstream merge is mechanical:
``court`` is a CourtListener court-id string, ``docket_number`` is the cleaned
number with ``docket_number_raw`` holding the verbatim site value, and dates are
``date`` objects named ``date_*``. CT-specific columns CL has no home for yet
(``crn``, ``appeal_by``, ``disposition_method``, preliminary papers, …) are kept
as extra fields rather than dropped.
"""

from __future__ import annotations

from datetime import date

from jkent.common.data_models import ScrapedData
from pydantic import BaseModel

# Appellate docket-number prefix -> CourtListener court id.
DOCKET_PREFIX_TO_COURT: dict[str, str] = {
    "SC": "conn",
    "AC": "connappct",
}

# All courts this scraper emits records for.
COURT_IDS: dict[str, str] = {
    "conn": "Connecticut Supreme Court",
    "connappct": "Connecticut Appellate Court",
    "connsuperct": "Connecticut Superior Court",
}

TRIAL_COURT_ID = "connsuperct"


# =============================================================================
# Appellate docket (appellateinquiry.jud.ct.gov) -> CL Docket
# =============================================================================


class ConnAppAttorney(BaseModel):
    """An attorney of record on an appellate party -> CL ``Attorney``."""

    name: str
    """Attorney name (e.g. ``NAOMI T FETTERMAN``)."""

    juris_number: str | None = None
    """Connecticut juris number (e.g. ``430485``)."""


class ConnAppParty(BaseModel):
    """A party on an appellate case -> CL ``Party`` + ``PartyType``."""

    name: str
    """Party name."""

    party_type: str | None = None
    """Role on the appeal (e.g. ``Petitioner/Movant``, ``Respondent``,
    ``Appellant``); maps to CL ``PartyType.name``."""

    trial_court_party_class: str | None = None
    """The party's class in the trial court (e.g. ``Plaintiff``)."""

    attorneys: list[ConnAppAttorney] = []
    """Attorneys / self-represented counsel for this party."""


class ConnAppOriginatingCourt(BaseModel):
    """Trial-court block shown on the appellate page.

    Maps to CL ``OriginatingCourtInformation`` (the one-step-down court). The
    full trial-court case, when public, is scraped separately as a
    :class:`ConnTrialCourtDocket` by following :attr:`docket_number_url`.
    """

    docket_number: str | None = None
    """Trial-court docket number (e.g. ``HHDCV226160660S``)."""

    docket_number_url: str | None = None
    """Link to the trial-court case on ``civilinquiry.jud.ct.gov`` (civil
    cases only; criminal/family numbers render as plain text)."""

    court_name: str | None = None
    """Trial court name (e.g. ``JD COURTHOUSE AT HARTFORD``)."""

    assigned_to_str: str | None = None
    """Trial judge name(s)."""

    date_judgment: date | None = None
    """Date of the trial-court judgment."""

    judgment_for: str | None = None
    """Who prevailed at trial (e.g. ``Plaintiff``, ``Defendant``)."""

    case_type: str | None = None
    """Trial-court case type (e.g. ``CIVIL - FORECLOSURE``, ``CRIMINAL``)."""


class ConnAppPreliminaryPaper(BaseModel):
    """Per-party preliminary-paper filing dates (appellate-specific)."""

    party_name: str
    preliminary_statement_of_issues: date | None = None
    designation_clerk_appendix: date | None = None
    certificate_transcript_received: date | None = None
    docketing_statement: date | None = None
    pac_statement: date | None = None
    constitutionality_notice: date | None = None
    sealing_notice: date | None = None
    certificate_interested_entities: date | None = None


class ConnAppTranscript(BaseModel):
    """Per-party transcript-ordering information (appellate-specific)."""

    party_name: str
    transcripts_ordered: date | None = None
    estimated_delivery_date: date | None = None
    delivered_to_party: date | None = None
    pages: int | None = None
    delivered_to_court: date | None = None


class ConnAppDocket(ScrapedData):
    """A Connecticut Supreme/Appellate Court docket -> CL ``Docket``.

    One per ``CaseDetail.aspx`` page. Docket entries (:class:`ConnAppDocketEntry`)
    and downloaded documents (:class:`ConnAppFile`) are emitted as separate
    records joined back by ``docket_number`` + ``court``.
    """

    # --- core CL Docket fields ---
    court: str
    """CourtListener court id: ``conn`` or ``connappct``."""

    docket_number: str
    """Cleaned docket number (e.g. ``SC 250277``)."""

    docket_number_raw: str
    """Verbatim ``lblAppealNo`` text."""

    case_name: str
    """Case name (e.g. ``STATE OF CONNECTICUT v. VANCE JOHNSON``)."""

    date_filed: date | None = None
    """Date the appeal was filed (``lblDateFiled``)."""

    date_argued: date | None = None
    """Date argued / submitted (``lblArgSub``)."""

    date_terminated: date | None = None
    """Disposition date (``lblDispDt``)."""

    panel_str: str | None = None
    """Panel of judges (``lblPanel``)."""

    # --- CT-specific extras (no CL column yet) ---
    crn: int
    """Case Record Number — the opaque internal id this scraper addresses by."""

    case_status: str | None = None
    """Case status (e.g. ``Disposed``, ``Pending``, ``Denied``)."""

    appeal_by: str | None = None
    """Who filed the appeal (e.g. ``Defendant``)."""

    disposition_method: str | None = None
    """How the case was disposed (e.g. ``Party Motion``, ``Denied``)."""

    date_submitted_on_briefs: date | None = None
    """Date submitted on briefs (``lblSubmitDt``)."""

    date_response_due: date | None = None
    """Response-to-docket due date (``lblResponse2Docket``)."""

    date_record_filed: date | None = None
    """Date the record was filed (``lblRecordFiled``)."""

    date_exhibits_received: date | None = None
    """Date exhibits were received by the court (``lblExhbitsRecByCourt``)."""

    citation: str | None = None
    """Citation / rescript text (``lblRescript``)."""

    is_efiled: bool = False
    """Whether the case carries an e-filed indicator."""

    # --- nested ---
    originating_court: ConnAppOriginatingCourt | None = None
    parties: list[ConnAppParty] = []
    preliminary_papers: list[ConnAppPreliminaryPaper] = []
    transcripts: list[ConnAppTranscript] = []

    # --- provenance ---
    source_url: str | None = None
    subscription_url: str | None = None
    source_entry_point: str | None = None


class ConnAppDocketEntry(ScrapedData):
    """A row of the Case Activity table -> CL ``DocketEntry``.

    Emitted separately and joined to its docket by ``docket_number`` + ``court``.
    Downloaded documents are emitted as :class:`ConnAppFile`.
    """

    docket_number: str
    """Parent appellate docket number (cleaned, e.g. ``SC 250277``)."""

    court: str
    """CourtListener court id of the parent docket."""

    activity_type: str
    """Activity type (``lblActivity``; e.g. ``PETITION``, ``ORDER``)."""

    number: str | None = None
    """The activity's ``Number`` column (often the docket number)."""

    date_filed: date | None = None
    initiated_by: str | None = None
    description: str | None = None
    """Activity description (``lblDescription``)."""

    action: str | None = None
    action_date: date | None = None
    notice_date: date | None = None
    is_paperless: bool = False

    document_urls: list[str] = []
    """Document URLs on this activity; each is archived as a ConnAppFile."""


class ConnAppFile(ScrapedData):
    """A downloaded appellate document -> CL ``RECAPDocument``."""

    docket_number: str
    court: str
    description: str | None = None
    """Description of the activity the document came from."""

    document_url: str
    local_path: str | None = None
    source_url: str | None = None


class ConnAppDocketUnavailable(ScrapedData):
    """An appellate case that exists but is withheld from public view.

    ``CaseDetail.aspx`` shows ``<docket> - This case is not available at this
    time.`` for these; only the docket number is recoverable.
    """

    crn: int
    docket_number: str | None = None
    court: str | None = None
    source_url: str | None = None
    message: str | None = None


# =============================================================================
# Trial court (civilinquiry.jud.ct.gov) -> CL Docket for connsuperct
# =============================================================================


class ConnTrialCourtAttorney(BaseModel):
    """An attorney appearance on a trial-court party -> CL ``Attorney``."""

    name: str | None = None
    juris_number: str | None = None
    firm: str | None = None
    contact_raw: str | None = None
    """Raw appearance text (firm, juris, address) before parsing."""

    date_filed: date | None = None
    """Appearance file date."""


class ConnTrialCourtParty(BaseModel):
    """A party on a trial-court case -> CL ``Party`` + ``PartyType``."""

    party_number: str
    """Party identifier (e.g. ``P-01``, ``D-01``, ``L-01``)."""

    name: str
    party_type: str | None = None
    """``Plaintiff`` / ``Defendant`` / ``For Notice Only`` derived from the
    party number prefix."""

    self_represented: bool = False
    non_appearing: bool = False
    attorneys: list[ConnTrialCourtAttorney] = []


class ConnTrialCourtDocket(ScrapedData):
    """A Connecticut Superior Court case -> CL ``Docket`` (``connsuperct``).

    Reached by following the trial-court link off an appellate case.
    """

    court: str = TRIAL_COURT_ID
    docket_number: str
    """Cleaned trial docket number (e.g. ``HHD-CV22-6160660-S``)."""

    docket_number_raw: str | None = None
    """Raw query-string form (e.g. ``HHDCV226160660S``)."""

    appellate_docket_number: str | None = None
    """Appellate docket that linked to this trial case (cross-reference)."""

    case_name: str
    case_type: str | None = None
    """Case type code (e.g. ``T28``)."""

    case_type_description: str | None = None
    """Full case type description (e.g. ``T28 - Torts - Malpractice``)."""

    court_location: str | None = None
    list_type: str | None = None
    date_filed: date | None = None
    """File date."""

    return_date: date | None = None
    date_disposed: date | None = None
    disposition: str | None = None
    assigned_to_str: str | None = None
    """Disposition judge / magistrate."""

    date_last_filing: date | None = None
    """Last action date."""

    parties: list[ConnTrialCourtParty] = []
    source_url: str | None = None


class ConnTrialCourtDocketEntry(ScrapedData):
    """A row of the trial-court documents table -> CL ``DocketEntry``."""

    trial_docket_number: str
    court: str = TRIAL_COURT_ID
    entry_number: str | None = None
    """Entry number (e.g. ``100.30``)."""

    date_filed: date | None = None
    filed_by: str | None = None
    """``P`` / ``D`` / ``C`` (Plaintiff / Defendant / Court)."""

    description: str | None = None
    additional_description: str | None = None
    result: str | None = None
    arguable: bool = False
    document_url: str | None = None


class ConnTrialFile(ScrapedData):
    """A downloaded trial-court document -> CL ``RECAPDocument``."""

    trial_docket_number: str
    court: str = TRIAL_COURT_ID
    description: str | None = None
    document_url: str
    local_path: str | None = None
    source_url: str | None = None


class ConnTrialCaseUnavailable(ScrapedData):
    """A trial-court case that is no longer public in civilinquiry.

    Older cases purged from ``civilinquiry`` (or reached without a session)
    redirect to an error page; we record the docket number so the gap is
    visible.
    """

    court: str = TRIAL_COURT_ID
    trial_docket_number: str
    appellate_docket_number: str | None = None
    source_url: str | None = None
    message: str | None = None
