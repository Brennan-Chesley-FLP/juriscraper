from datetime import date, datetime
from typing import ClassVar

from pydantic import BaseModel


class ConsumerModel(BaseModel):
    """These models represent the expansive basic forms of data we'd like to extract from webpages.

    Individual Scrapers will subclass these models to add fields, make some
    fields non-optional for additional validation or annotation. The
    documentation will reference these models when it notes the kinds of
    searches that can be done, or additional fields added by a model.
    """

    pass


class Audio(ConsumerModel):
    """Oral arguments with metadata."""

    # STT status constants
    STT_NEEDED: ClassVar[int] = 0
    STT_COMPLETE: ClassVar[int] = 1
    STT_FAILED: ClassVar[int] = 2
    STT_HALLUCINATION: ClassVar[int] = 3
    STT_FILE_TOO_BIG: ClassVar[int] = 4
    STT_NO_FILE: ClassVar[int] = 5

    # STT source constants
    STT_OPENAI_WHISPER: ClassVar[int] = 1
    STT_SELF_HOSTED_WHISPER: ClassVar[int] = 2

    id: int | None = None
    date_created: datetime | None = None
    date_modified: datetime | None = None
    docket_id: int | None = None
    source: str | None = None
    case_name_short: str | None = None
    case_name: str | None = None
    case_name_full: str | None = None
    judges: str | None = None
    sha1: str | None = None
    download_url: str | None = None
    local_path_mp3: str | None = None
    local_path_original_file: str | None = None
    filepath_ia: str | None = None
    ia_upload_failure_count: int | None = None
    duration: int | None = None
    processing_complete: bool | None = None
    date_blocked: str | None = None  # DateField stored as string
    blocked: bool | None = None
    stt_status: int | None = None
    stt_source: int | None = None
    stt_transcript: str | None = None


class AudioTranscriptionMetadata(ConsumerModel):
    """Word/segment level metadata from STT models."""

    id: int | None = None
    date_created: datetime | None = None
    date_modified: datetime | None = None
    audio_id: int | None = None
    metadata: dict | None = None  # JSONField


class Person(ConsumerModel):
    """Judges, lawyers, and other legal professionals."""

    id: int | None = None
    date_created: datetime | None = None
    date_modified: datetime | None = None
    is_alias_of_id: int | None = None
    date_completed: datetime | None = None
    fjc_id: int | None = None
    slug: str | None = None
    name_first: str | None = None
    name_middle: str | None = None
    name_last: str | None = None
    name_suffix: str | None = None
    date_dob: date | None = None
    date_granularity_dob: str | None = None
    date_dod: date | None = None
    date_granularity_dod: str | None = None
    dob_city: str | None = None
    dob_state: str | None = None
    dob_country: str | None = None
    dod_city: str | None = None
    dod_state: str | None = None
    dod_country: str | None = None
    gender: str | None = None
    religion: str | None = None
    ftm_total_received: float | None = None
    ftm_eid: str | None = None
    has_photo: bool | None = None


class School(ConsumerModel):
    """Educational institutions."""

    id: int | None = None
    date_created: datetime | None = None
    date_modified: datetime | None = None
    is_alias_of_id: int | None = None
    name: str | None = None
    ein: int | None = None


class Position(ConsumerModel):
    """Positions held by people (judicial, academic, etc.)."""

    # Position type constants - many constants defined in Django model
    JUDGE: ClassVar[str] = "jud"
    JUSTICE: ClassVar[str] = "jus"
    CHIEF_JUDGE: ClassVar[str] = "c-jud"
    CHIEF_JUSTICE: ClassVar[str] = "c-jus"
    MAGISTRATE: ClassVar[str] = "mag"
    # ... many more position types in Django model

    # Sector constants
    PRIVATE: ClassVar[int] = 1
    PUBLIC: ClassVar[int] = 2

    id: int | None = None
    date_created: datetime | None = None
    date_modified: datetime | None = None
    position_type: str | None = None
    job_title: str | None = None
    sector: int | None = None
    person_id: int | None = None
    court_id: str | None = None
    school_id: int | None = None
    organization_name: str | None = None
    location_city: str | None = None
    location_state: str | None = None
    appointer_id: int | None = None
    supervisor_id: int | None = None
    predecessor_id: int | None = None
    date_nominated: date | None = None
    date_elected: date | None = None
    date_recess_appointment: date | None = None
    date_referred_to_judicial_committee: date | None = None
    date_judicial_committee_action: date | None = None
    judicial_committee_action: str | None = None
    date_hearing: date | None = None
    date_confirmation: date | None = None
    date_start: date | None = None
    date_granularity_start: str | None = None
    date_termination: date | None = None
    termination_reason: str | None = None
    date_granularity_termination: str | None = None
    date_retirement: date | None = None
    nomination_process: str | None = None
    vote_type: str | None = None
    voice_vote: bool | None = None
    votes_yes: int | None = None
    votes_no: int | None = None
    votes_yes_percent: float | None = None
    votes_no_percent: float | None = None
    how_selected: str | None = None
    has_inferred_values: bool | None = None


class RetentionEvent(ConsumerModel):
    """Retention events for positions."""

    id: int | None = None
    date_created: datetime | None = None
    date_modified: datetime | None = None
    position_id: int | None = None
    retention_type: str | None = None
    date_retention: date | None = None
    votes_yes: int | None = None
    votes_no: int | None = None
    votes_yes_percent: float | None = None
    votes_no_percent: float | None = None
    unopposed: bool | None = None
    won: bool | None = None


class Education(ConsumerModel):
    """Education records for people."""

    id: int | None = None
    date_created: datetime | None = None
    date_modified: datetime | None = None
    person_id: int | None = None
    school_id: int | None = None
    degree_level: str | None = None
    degree_detail: str | None = None
    degree_year: int | None = None


class Race(ConsumerModel):
    """Race information."""

    id: int | None = None
    race: str | None = None


class PoliticalAffiliation(ConsumerModel):
    """Political party affiliations."""

    id: int | None = None
    date_created: datetime | None = None
    date_modified: datetime | None = None
    person_id: int | None = None
    political_party: str | None = None
    source: str | None = None
    date_start: date | None = None
    date_granularity_start: str | None = None
    date_end: date | None = None
    date_granularity_end: str | None = None


class Source(ConsumerModel):
    """Data source information."""

    id: int | None = None
    date_created: datetime | None = None
    date_modified: datetime | None = None
    person_id: int | None = None
    url: str | None = None
    date_accessed: date | None = None
    notes: str | None = None


class ABARating(ConsumerModel):
    """American Bar Association ratings."""

    id: int | None = None
    date_created: datetime | None = None
    date_modified: datetime | None = None
    person_id: int | None = None
    year_rated: int | None = None
    rating: str | None = None


class PartyType(ConsumerModel):
    """Links parties to dockets with role information."""

    id: int | None = None
    docket_id: int | None = None
    party_id: int | None = None
    name: str | None = None
    date_terminated: date | None = None
    extra_info: str | None = None
    highest_offense_level_opening: str | None = None
    highest_offense_level_terminated: str | None = None


class CriminalCount(ConsumerModel):
    """Criminal counts associated with a party."""

    # Status constants
    PENDING: ClassVar[int] = 1
    TERMINATED: ClassVar[int] = 2

    id: int | None = None
    party_type_id: int | None = None
    name: str | None = None
    disposition: str | None = None
    status: int | None = None


class CriminalComplaint(ConsumerModel):
    """Criminal complaints associated with a party."""

    id: int | None = None
    party_type_id: int | None = None
    name: str | None = None
    disposition: str | None = None


class Party(ConsumerModel):
    """Parties involved in cases."""

    id: int | None = None
    date_created: datetime | None = None
    date_modified: datetime | None = None
    name: str | None = None
    extra_info: str | None = None


class Role(ConsumerModel):
    """Links attorneys to parties and dockets."""

    # Attorney role constants
    ATTORNEY_TO_BE_NOTICED: ClassVar[int] = 1
    ATTORNEY_LEAD: ClassVar[int] = 2
    ATTORNEY_IN_SEALED_GROUP: ClassVar[int] = 3
    PRO_HAC_VICE: ClassVar[int] = 4
    SELF_TERMINATED: ClassVar[int] = 5
    TERMINATED: ClassVar[int] = 6
    SUSPENDED: ClassVar[int] = 7
    INACTIVE: ClassVar[int] = 8
    DISBARRED: ClassVar[int] = 9
    UNKNOWN: ClassVar[int] = 10

    id: int | None = None
    party_id: int | None = None
    attorney_id: int | None = None
    docket_id: int | None = None
    role: int | None = None
    role_raw: str | None = None
    date_action: date | None = None


class Attorney(ConsumerModel):
    """Attorneys involved in cases."""

    id: int | None = None
    date_created: datetime | None = None
    date_modified: datetime | None = None
    name: str | None = None
    contact_raw: str | None = None
    phone: str | None = None
    fax: str | None = None
    email: str | None = None


class AttorneyOrganizationAssociation(ConsumerModel):
    """Links attorneys to organizations and dockets."""

    id: int | None = None
    attorney_id: int | None = None
    attorney_organization_id: int | None = None
    docket_id: int | None = None


class AttorneyOrganization(ConsumerModel):
    """Law firms and other attorney organizations."""

    id: int | None = None
    date_created: datetime | None = None
    date_modified: datetime | None = None
    lookup_key: str | None = None
    name: str | None = None
    address1: str | None = None
    address2: str | None = None
    city: str | None = None
    state: str | None = None
    zip_code: str | None = None


class PacerHtmlFiles(ConsumerModel):
    """Original HTML content from PACER."""

    id: int | None = None
    date_created: datetime | None = None
    date_modified: datetime | None = None
    content_type_id: int | None = None
    object_id: int | None = None
    local_filepath: str | None = None
    filepath: str | None = None
    upload_type: int | None = None


class FjcIntegratedDatabase(ConsumerModel):
    """FJC Integrated Database entries."""

    # Origin constants
    ORIG: ClassVar[int] = 1
    REMOVED: ClassVar[int] = 2
    REMANDED: ClassVar[int] = 3
    REINSTATED: ClassVar[int] = 4
    TRANSFERRED: ClassVar[int] = 5
    MULTI_DIST: ClassVar[int] = 6
    APPEAL_FROM_MAG: ClassVar[int] = 7
    SECOND_REOPEN: ClassVar[int] = 8
    THIRD_REOPEN: ClassVar[int] = 9
    FOURTH_REOPEN: ClassVar[int] = 10
    FIFTH_REOPEN: ClassVar[int] = 11
    SIXTH_REOPEN: ClassVar[int] = 12
    MULTI_DIST_ORIG: ClassVar[int] = 13

    # Jurisdiction constants
    GOV_PLAIN: ClassVar[int] = 1
    GOV_DEF: ClassVar[int] = 2
    FED_Q: ClassVar[int] = 3
    DIV_OF_CITZ: ClassVar[int] = 4
    LOCAL_Q: ClassVar[int] = 5

    # Arbitration constants
    MANDATORY: ClassVar[str] = "M"
    VOLUNTARY: ClassVar[str] = "V"
    EXEMPT: ClassVar[str] = "E"
    YES: ClassVar[str] = "Y"

    # Class action constants
    CLASS_ACTION_DENIED: ClassVar[int] = 2
    CLASS_ACTION_GRANTED: ClassVar[int] = 3

    # Procedural progress constants
    NO_COURT_ACTION_PRE_ISSUE_JOINED: ClassVar[int] = 1
    ORDER_ENTERED: ClassVar[int] = 2
    HEARING_HELD: ClassVar[int] = 11
    ORDER_DECIDED: ClassVar[int] = 12
    NO_COURT_ACTION_POST_ISSUE_JOINED: ClassVar[int] = 3
    JUDGMENT_ON_MOTION: ClassVar[int] = 4
    PRETRIAL_CONFERENCE_HELD: ClassVar[int] = 5
    DURING_COURT_TRIAL: ClassVar[int] = 6
    DURING_JURY_TRIAL: ClassVar[int] = 7
    AFTER_COURT_TRIAL: ClassVar[int] = 8
    AFTER_JURY_TRIAL: ClassVar[int] = 9
    OTHER_PROCEDURAL_PROGRESS: ClassVar[int] = 10
    REQUEST_FOR_DE_NOVO: ClassVar[int] = 13

    # Disposition constants
    TRANSFER_TO_DISTRICT: ClassVar[int] = 0
    REMANDED_TO_STATE: ClassVar[int] = 1
    TRANSFER_TO_MULTI: ClassVar[int] = 10
    REMANDED_TO_AGENCY: ClassVar[int] = 11
    WANT_OF_PROSECUTION: ClassVar[int] = 2
    LACK_OF_JURISDICTION: ClassVar[int] = 3
    VOLUNTARILY_DISMISSED: ClassVar[int] = 12
    SETTLED: ClassVar[int] = 13
    OTHER_DISMISSAL: ClassVar[int] = 14
    DEFAULT: ClassVar[int] = 4
    CONSENT: ClassVar[int] = 5
    MOTION_BEFORE_TRIAL: ClassVar[int] = 6
    JURY_VERDICT: ClassVar[int] = 7
    DIRECTED_VERDICT: ClassVar[int] = 8
    COURT_TRIAL: ClassVar[int] = 9
    AWARD_OF_ARBITRATOR: ClassVar[int] = 15
    STAYED_PENDING_BANKR: ClassVar[int] = 16
    OTHER_DISPOSITION: ClassVar[int] = 17
    STATISTICAL_CLOSING: ClassVar[int] = 18
    APPEAL_AFFIRMED: ClassVar[int] = 19
    APPEAL_DENIED: ClassVar[int] = 20

    # Nature of judgment constants
    NO_MONEY: ClassVar[int] = 0
    MONEY_ONLY: ClassVar[int] = 1
    MONEY_AND: ClassVar[int] = 2
    INJUNCTION: ClassVar[int] = 3
    FORFEITURE_ETC: ClassVar[int] = 4
    COSTS_ONLY: ClassVar[int] = 5
    COSTS_AND_FEES: ClassVar[int] = 6

    # Judgment favor constants
    PLAINTIFF: ClassVar[int] = 1
    DEFENDANT: ClassVar[int] = 2
    PLAINTIFF_AND_DEFENDANT: ClassVar[int] = 3
    UNKNOWN_FAVORING: ClassVar[int] = 4

    # Pro se constants
    PRO_SE_NONE: ClassVar[int] = 0
    PRO_SE_PLAINTIFFS: ClassVar[int] = 1
    PRO_SE_DEFENDANTS: ClassVar[int] = 2
    PRO_SE_BOTH: ClassVar[int] = 3

    id: int | None = None
    date_created: datetime | None = None
    date_modified: datetime | None = None
    dataset_source: int | None = None
    circuit_id: str | None = None
    district_id: str | None = None
    office: str | None = None
    docket_number: str | None = None
    origin: int | None = None
    date_filed: date | None = None
    jurisdiction: int | None = None
    nature_of_suit: int | None = None
    title: str | None = None
    section: str | None = None
    subsection: str | None = None
    diversity_of_residence: int | None = None
    class_action: bool | None = None
    monetary_demand: int | None = None
    county_of_residence: int | None = None
    arbitration_at_filing: str | None = None
    arbitration_at_termination: str | None = None
    multidistrict_litigation_docket_number: str | None = None
    plaintiff: str | None = None
    defendant: str | None = None
    date_transfer: date | None = None
    transfer_office: str | None = None
    transfer_docket_number: str | None = None
    transfer_origin: str | None = None
    date_terminated: date | None = None
    termination_class_action_status: int | None = None
    procedural_progress: int | None = None
    disposition: int | None = None
    nature_of_judgement: int | None = None
    amount_received: int | None = None
    judgment: int | None = None
    pro_se: int | None = None
    year_of_tape: int | None = None
    nature_of_offense: str | None = None
    version: int | None = None


class OriginatingCourtInformation(ConsumerModel):
    """Lower court metadata for appellate cases."""

    id: int | None = None
    date_created: datetime | None = None
    date_modified: datetime | None = None
    docket_number: str | None = None
    docket_number_raw: str | None = None
    assigned_to_id: int | None = None
    assigned_to_str: str | None = None
    ordering_judge_id: int | None = None
    ordering_judge_str: str | None = None
    court_reporter: str | None = None
    date_disposed: date | None = None
    date_filed: date | None = None
    date_judgment: date | None = None
    date_judgment_eod: date | None = None
    date_filed_noa: date | None = None
    date_received_coa: date | None = None
    date_rehearing_denied: date | None = None


class Docket(ConsumerModel):
    """Master model linking opinions, audio, and docket entries."""

    id: int | None = None
    date_created: datetime | None = None
    date_modified: datetime | None = None
    source: int | None = None
    court_id: str | None = None
    appeal_from_id: str | None = None
    parent_docket_id: int | None = None
    appeal_from_str: str | None = None
    originating_court_information_id: int | None = None
    idb_data_id: int | None = None
    assigned_to_id: int | None = None
    assigned_to_str: str | None = None
    referred_to_id: int | None = None
    referred_to_str: str | None = None
    panel_str: str | None = None
    date_last_index: datetime | None = None
    date_cert_granted: date | None = None
    date_cert_denied: date | None = None
    date_argued: date | None = None
    date_reargued: date | None = None
    date_reargument_denied: date | None = None
    date_filed: date | None = None
    date_terminated: date | None = None
    date_last_filing: date | None = None
    case_name_short: str | None = None
    case_name: str | None = None
    case_name_full: str | None = None
    slug: str | None = None
    docket_number: str | None = None
    docket_number_core: str | None = None
    docket_number_raw: str | None = None
    federal_dn_office_code: str | None = None
    federal_dn_case_type: str | None = None
    federal_dn_judge_initials_assigned: str | None = None
    federal_dn_judge_initials_referred: str | None = None
    federal_defendant_number: int | None = None
    pacer_case_id: str | None = None
    cause: str | None = None
    nature_of_suit: str | None = None
    jury_demand: str | None = None
    jurisdiction_type: str | None = None
    appellate_fee_status: str | None = None
    appellate_case_type_information: str | None = None
    mdl_status: str | None = None
    filepath_local: str | None = None
    filepath_ia: str | None = None
    filepath_ia_json: str | None = None
    ia_upload_failure_count: int | None = None
    ia_needs_upload: bool | None = None
    ia_date_first_change: datetime | None = None
    view_count: int | None = None
    date_blocked: date | None = None
    blocked: bool | None = None


class DocketEntry(ConsumerModel):
    """Individual entries/filings in a docket."""

    id: int | None = None
    date_created: datetime | None = None
    date_modified: datetime | None = None
    docket_id: int | None = None
    date_filed: date | None = None
    time_filed: str | None = None  # TimeField stored as string
    entry_number: int | None = None
    recap_sequence_number: str | None = None
    pacer_sequence_number: int | None = None
    description: str | None = None


class AbstractPacerDocument(ConsumerModel):
    """Abstract base for PACER documents."""

    date_upload: datetime | None = None
    document_number: str | None = None
    attachment_number: int | None = None
    pacer_doc_id: str | None = None
    is_available: bool | None = None
    is_free_on_pacer: bool | None = None
    is_sealed: bool | None = None


class RECAPDocument(AbstractPacerDocument):
    """Docket Documents and Attachments from RECAP."""

    # Document type constants
    PACER_DOCUMENT: ClassVar[int] = 1
    ATTACHMENT: ClassVar[int] = 2

    id: int | None = None
    date_created: datetime | None = None
    date_modified: datetime | None = None
    docket_entry_id: int | None = None
    document_type: int | None = None
    description: str | None = None
    acms_document_guid: str | None = None
    local_filepath: str | None = None
    sha1: str | None = None
    page_count: int | None = None
    file_size: int | None = None
    filepath_local: str | None = None
    filepath_ia: str | None = None
    ia_upload_failure_count: int | None = None
    thumbnail: str | None = None
    thumbnail_status: int | None = None
    plain_text: str | None = None
    ocr_status: int | None = None


class BankruptcyInformation(ConsumerModel):
    """Bankruptcy case information."""

    id: int | None = None
    date_created: datetime | None = None
    date_modified: datetime | None = None
    docket_id: int | None = None
    date_converted: datetime | None = None
    date_last_to_file_claims: datetime | None = None
    date_last_to_file_govt: datetime | None = None
    date_debtor_dismissed: datetime | None = None
    chapter: str | None = None
    trustee_str: str | None = None


class Claim(ConsumerModel):
    """Bankruptcy claims."""

    id: int | None = None
    date_created: datetime | None = None
    date_modified: datetime | None = None
    docket_id: int | None = None
    date_claim_modified: datetime | None = None
    date_original_entered: datetime | None = None
    date_original_filed: datetime | None = None
    date_last_amendment_entered: datetime | None = None
    date_last_amendment_filed: datetime | None = None
    claim_number: str | None = None
    creditor_details: str | None = None
    creditor_id: str | None = None
    status: str | None = None
    entered_by: str | None = None
    filed_by: str | None = None
    amount_claimed: str | None = None
    unsecured_claimed: str | None = None
    secured_claimed: str | None = None
    priority_claimed: str | None = None
    description: str | None = None
    remarks: str | None = None


class ClaimHistory(AbstractPacerDocument):
    """History entries for bankruptcy claims."""

    # Claim document type constants
    DOCKET_ENTRY: ClassVar[int] = 1
    CLAIM_ENTRY: ClassVar[int] = 2

    id: int | None = None
    date_created: datetime | None = None
    date_modified: datetime | None = None
    claim_id: int | None = None
    date_filed: date | None = None
    claim_document_type: int | None = None
    description: str | None = None
    claim_doc_id: str | None = None
    pacer_dm_id: int | None = None
    pacer_case_id: str | None = None
    local_filepath: str | None = None
    sha1: str | None = None
    page_count: int | None = None
    file_size: int | None = None
    filepath_local: str | None = None
    filepath_ia: str | None = None
    ia_upload_failure_count: int | None = None
    thumbnail: str | None = None
    thumbnail_status: int | None = None
    plain_text: str | None = None
    ocr_status: int | None = None


class Court(ConsumerModel):
    """Court information model."""

    # Jurisdiction constants
    FEDERAL_APPELLATE: ClassVar[str] = "F"
    FEDERAL_DISTRICT: ClassVar[str] = "FD"
    FEDERAL_BANKRUPTCY: ClassVar[str] = "FB"
    FEDERAL_BANKRUPTCY_PANEL: ClassVar[str] = "FBP"
    FEDERAL_SPECIAL: ClassVar[str] = "FS"
    STATE_SUPREME: ClassVar[str] = "S"
    STATE_APPELLATE: ClassVar[str] = "SA"
    STATE_TRIAL: ClassVar[str] = "ST"
    STATE_SPECIAL: ClassVar[str] = "SS"
    STATE_ATTORNEY_GENERAL: ClassVar[str] = "SAG"
    TRIBAL_SUPREME: ClassVar[str] = "TRS"
    TRIBAL_APPELLATE: ClassVar[str] = "TRA"
    TRIBAL_TRIAL: ClassVar[str] = "TRT"
    TRIBAL_SPECIAL: ClassVar[str] = "TRX"
    TERRITORY_SUPREME: ClassVar[str] = "TS"
    TERRITORY_APPELLATE: ClassVar[str] = "TA"
    TERRITORY_TRIAL: ClassVar[str] = "TT"
    TERRITORY_SPECIAL: ClassVar[str] = "TSP"
    MILITARY_APPELLATE: ClassVar[str] = "MA"
    MILITARY_TRIAL: ClassVar[str] = "MT"
    COMMITTEE: ClassVar[str] = "C"
    INTERNATIONAL: ClassVar[str] = "I"
    TESTING_COURT: ClassVar[str] = "T"

    id: str | None = None
    parent_court_id: str | None = None
    pacer_court_id: int | None = None
    pacer_has_rss_feed: bool | None = None
    pacer_rss_entry_types: str | None = None
    date_last_pacer_contact: datetime | None = None
    fjc_court_id: str | None = None
    date_modified: datetime | None = None
    in_use: bool | None = None
    has_opinion_scraper: bool | None = None
    has_oral_argument_scraper: bool | None = None
    position: float | None = None
    citation_string: str | None = None
    short_name: str | None = None
    full_name: str | None = None
    url: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    jurisdiction: str | None = None
    notes: str | None = None


class Courthouse(ConsumerModel):
    """Physical courthouse location model."""

    id: int | None = None
    court_id: str | None = None
    court_seat: bool | None = None
    building_name: str | None = None
    address1: str | None = None
    address2: str | None = None
    city: str | None = None
    county: str | None = None
    state: str | None = None
    zip_code: str | None = None
    country_code: str | None = None


class OpinionCluster(ConsumerModel):
    """Cluster of related court opinions."""

    # SCDB decision direction constants
    SCDB_CONSERVATIVE: ClassVar[int] = 1
    SCDB_LIBERAL: ClassVar[int] = 2
    SCDB_UNSPECIFIABLE: ClassVar[int] = 3

    id: int | None = None
    date_created: datetime | None = None
    date_modified: datetime | None = None
    docket_id: int | None = None
    judges: str | None = None
    date_filed: date | None = None
    date_filed_is_approximate: bool | None = None
    slug: str | None = None
    case_name_short: str | None = None
    case_name: str | None = None
    case_name_full: str | None = None
    scdb_id: str | None = None
    scdb_decision_direction: int | None = None
    scdb_votes_majority: int | None = None
    scdb_votes_minority: int | None = None
    source: str | None = None
    procedural_history: str | None = None
    attorneys: str | None = None
    nature_of_suit: str | None = None
    posture: str | None = None
    syllabus: str | None = None
    headnotes: str | None = None
    summary: str | None = None
    disposition: str | None = None
    history: str | None = None
    other_dates: str | None = None
    cross_reference: str | None = None
    correction: str | None = None
    citation_count: int | None = None
    precedential_status: str | None = None
    date_blocked: date | None = None
    blocked: bool | None = None
    filepath_json_harvard: str | None = None
    filepath_pdf_harvard: str | None = None
    arguments: str | None = None
    headmatter: str | None = None


class BaseCitation(ConsumerModel):
    """Base citation model."""

    # Citation type constants
    FEDERAL: ClassVar[int] = 1
    STATE: ClassVar[int] = 2
    STATE_REGIONAL: ClassVar[int] = 3
    SPECIALTY: ClassVar[int] = 4
    SCOTUS_EARLY: ClassVar[int] = 5
    LEXIS: ClassVar[int] = 6
    WEST: ClassVar[int] = 7
    NEUTRAL: ClassVar[int] = 8
    JOURNAL: ClassVar[int] = 9

    volume: str | None = None
    reporter: str | None = None
    page: str | None = None
    type: int | None = None


class Citation(BaseCitation):
    """Citation to an OpinionCluster."""

    id: int | None = None
    date_created: datetime | None = None
    date_modified: datetime | None = None
    cluster_id: int | None = None


class Opinion(ConsumerModel):
    """Individual legal opinion."""

    # Opinion type constants
    COMBINED: ClassVar[str] = "010combined"
    UNANIMOUS: ClassVar[str] = "015unamimous"
    LEAD: ClassVar[str] = "020lead"
    PLURALITY: ClassVar[str] = "025plurality"
    CONCURRENCE: ClassVar[str] = "030concurrence"
    CONCUR_IN_PART: ClassVar[str] = "035concurrenceinpart"
    DISSENT: ClassVar[str] = "040dissent"
    ADDENDUM: ClassVar[str] = "050addendum"
    REMITTUR: ClassVar[str] = "060remittitur"
    REHEARING: ClassVar[str] = "070rehearing"
    ON_THE_MERITS: ClassVar[str] = "080onthemerits"
    ON_MOTION_TO_STRIKE: ClassVar[str] = "090onmotiontostrike"
    TRIAL_COURT: ClassVar[str] = "100trialcourt"

    id: int | None = None
    date_created: datetime | None = None
    date_modified: datetime | None = None
    cluster_id: int | None = None
    author_id: int | None = None
    author_str: str | None = None
    per_curiam: bool | None = None
    joined_by_str: str | None = None
    type: str | None = None
    sha1: str | None = None
    page_count: int | None = None
    download_url: str | None = None
    local_path: str | None = None
    plain_text: str | None = None
    html: str | None = None
    html_lawbox: str | None = None
    html_columbia: str | None = None
    html_anon_2020: str | None = None
    xml_harvard: str | None = None
    html_with_citations: str | None = None
    extracted_by_ocr: bool | None = None
    ordering_key: int | None = None
    main_version_id: int | None = None


class OpinionsCited(ConsumerModel):
    """Many-to-many relationship tracking which opinions cite others."""

    id: int | None = None
    date_created: datetime | None = None
    date_modified: datetime | None = None
    citing_opinion_id: int | None = None
    cited_opinion_id: int | None = None
    depth: int | None = None
    quoted: bool | None = None
    treatment: int | None = None


class OpinionsCitedByRECAPDocument(ConsumerModel):
    """RECAP documents citing opinions."""

    id: int | None = None
    date_created: datetime | None = None
    date_modified: datetime | None = None
    citing_document_id: int | None = None
    cited_opinion_id: int | None = None
    depth: int | None = None
    quoted: bool | None = None
    treatment: int | None = None


class Parenthetical(ConsumerModel):
    """Brief snippets showing how a case is cited."""

    id: int | None = None
    date_created: datetime | None = None
    date_modified: datetime | None = None
    describing_opinion_id: int | None = None
    described_opinion_id: int | None = None
    group_id: int | None = None
    text: str | None = None
    score: float | None = None


class ParentheticalGroup(ConsumerModel):
    """Groups of related parentheticals."""

    id: int | None = None
    date_created: datetime | None = None
    date_modified: datetime | None = None
    opinion_id: int | None = None
    representative_id: int | None = None
    score: float | None = None
    size: int | None = None


class Tag(ConsumerModel):
    """User-facing tags for dockets/opinions."""

    id: int | None = None
    date_created: datetime | None = None
    date_modified: datetime | None = None
    name: str | None = None


class SearchQuery(ConsumerModel):
    """Saved search queries."""

    id: int | None = None
    date_created: datetime | None = None
    date_modified: datetime | None = None
    query: str | None = None


class ClusterRedirection(ConsumerModel):
    """Redirects for merged case clusters."""

    id: int | None = None
    old_cluster_id: int | None = None
    new_cluster_id: int | None = None


class ScotusDocketMetadata(ConsumerModel):
    """Supreme Court specific metadata."""

    id: int | None = None
    date_created: datetime | None = None
    date_modified: datetime | None = None
    docket_id: int | None = None
    argument_date: date | None = None
    reargument_date: date | None = None
    disposition: str | None = None
    petition_date: date | None = None
    case_distributed_date: date | None = None
