"""Data models for the Pennsylvania appellate courts JSON API.

Source: ``https://services.pacourts.us/public/v1`` — the public REST API
behind the AOPC "PAeDocket" mobile app. The endpoint pair is advertised by
the app's own remote config document at ``https://mobileconfig.pacourts.us``
(see ``MOBILE_CONFIG_URL``), which is how the API was discovered.

The API is backed by two case-management systems: **PACMS** (the appellate
courts) and **CPCMS**/**MDJS** (the trial courts). This scraper is scoped to
the PACMS side only — the three Pennsylvania appellate courts:

- ``pa``          Supreme Court of Pennsylvania
- ``pasuperct``   Superior Court of Pennsylvania
- ``pacommwct``   Commonwealth Court of Pennsylvania

Field names follow ``CL_MODELS.md`` (``docket_number``, ``court``, ``date_*``)
so the downstream CourtListener merge is mechanical. The API is far richer
than CourtListener's schema, so several models carry fields CL has no column
for yet (service lists, briefing due-dates, allocatur metadata); per
``CL_MODELS.md`` those are captured rather than dropped.
"""

from __future__ import annotations

from datetime import date, time

from jkent.common.data_models import ScrapedData

from juriscraper.state.common.params import CourtRange
from juriscraper.state.common_models import HarmonizedCaseName

# =========================================================================
# Site constants
# =========================================================================

#: The AOPC mobile-app remote config. Returns a list of one application
#: descriptor whose document advertises the ``services`` endpoints below.
#: Kept here as provenance — the scraper does not fetch it at runtime.
MOBILE_CONFIG_URL = "https://mobileconfig.pacourts.us"

API_BASE = "https://services.pacourts.us/public/v1"

#: Case retrieval: ``GET {CASE_URL}/{docket_number}`` (docket number
#: percent-encoded; the spaces in ``1 MAP 2024`` become ``%20``). Returns the
#: complete case document, or a hard **404** when the docket does not exist —
#: which is what makes speculative enumeration viable here.
CASE_URL = f"{API_BASE}/cases"

#: Case search: ``POST {SEARCH_URL}``. A bare ``GET`` on the same URL returns
#: an empty criteria template, which is how the searchable field list was
#: enumerated (see ``CC_NOTES.md``).
SEARCH_URL = f"{API_BASE}/cases/search"

#: The API returns **401 Unauthorized** to clients sending a default
#: Python/httpx User-Agent, and serves normally to a browser-like one. Sent on
#: every request via ``Request.permanent`` so it cascades down the chain.
BROWSER_HEADERS: dict[str, str] = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/147.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
}

#: CourtListener court id -> display name, for the three PACMS courts.
COURT_IDS: dict[str, str] = {
    "pa": "Supreme Court of Pennsylvania",
    "pasuperct": "Superior Court of Pennsylvania",
    "pacommwct": "Commonwealth Court of Pennsylvania",
}

#: ``courtName`` search-facet value -> CourtListener court id. These are the
#: exact strings the search endpoint returns in ``courtNameOptions`` and the
#: only values it accepts for the three appellate courts.
SITE_COURT_NAME_TO_COURT_ID: dict[str, str] = {
    "Supreme Court of Pennsylvania": "pa",
    "Superior Court of Pennsylvania": "pasuperct",
    "Commonwealth Court of Pennsylvania": "pacommwct",
}
COURT_ID_TO_SITE_COURT_NAME: dict[str, str] = {
    v: k for k, v in SITE_COURT_NAME_TO_COURT_ID.items()
}

#: Appellate docket-number type prefixes -> (CourtListener court id, district,
#: case category). A PACMS appellate docket number is ``"<seq> <TYPE> <year>"``
#: (e.g. ``"1 MAP 2024"``); ``<TYPE>`` encodes court + district + category, and
#: ``<seq>`` restarts at 1 each calendar year within each (type, year) space.
#:
#: Verified empirically by probing ``GET /cases/{n} {TYPE} {year}`` for every
#: candidate prefix and reading back ``courtOffice.court.displayName`` and
#: ``caseCategory.name``. The three "D" prefixes that look like they should
#: exist by symmetry (``ED``/``WD``, the Eastern/Western analogues of
#: Commonwealth Court's ``MD``) return 404 for every sequence tried —
#: Commonwealth Court is a statewide court with a single ``MD``
#: original-jurisdiction space.
DOCKET_TYPES: dict[str, tuple[str, str, str]] = {
    # Supreme Court of Pennsylvania
    "MAP": ("pa", "Middle", "Appeal"),
    "EAP": ("pa", "Eastern", "Appeal"),
    "WAP": ("pa", "Western", "Appeal"),
    "MAL": ("pa", "Middle", "Allocatur"),
    "EAL": ("pa", "Eastern", "Allocatur"),
    "WAL": ("pa", "Western", "Allocatur"),
    "MM": ("pa", "Middle", "Miscellaneous"),
    "EM": ("pa", "Eastern", "Miscellaneous"),
    "WM": ("pa", "Western", "Miscellaneous"),
    # Superior Court of Pennsylvania
    "EDA": ("pasuperct", "Eastern", "Appeal"),
    "MDA": ("pasuperct", "Middle", "Appeal"),
    "WDA": ("pasuperct", "Western", "Appeal"),
    "EDM": ("pasuperct", "Eastern", "Miscellaneous"),
    "MDM": ("pasuperct", "Middle", "Miscellaneous"),
    "WDM": ("pasuperct", "Western", "Miscellaneous"),
    # Commonwealth Court of Pennsylvania (statewide, no district split)
    "CD": ("pacommwct", "", "Commonwealth"),
    "MD": ("pacommwct", "", "Miscellaneous"),
}

#: Docket-type prefixes grouped by CourtListener court id, for seeding.
DOCKET_TYPES_BY_COURT: dict[str, list[str]] = {
    court_id: [p for p, (c, _d, _c2) in DOCKET_TYPES.items() if c == court_id]
    for court_id in COURT_IDS
}


# =========================================================================
# Speculative entry parameter
# =========================================================================


class PaDocketRange(CourtRange):
    """A speculative range over one ``(court, docket type, year)`` number space.

    PACMS appellate docket numbers are ``"<seq> <TYPE> <year>"`` with ``<seq>``
    restarting at 1 each year within each ``<TYPE>``, so a single flat
    ``SpeculativeRange`` cannot address the space: the court, the type prefix
    and the year all have to ride along with the sequence number. The driver
    dispatches a speculative entry with **only** its speculative param
    (``SCRAPER_STANDARDS`` §4, "Multi-court speculative entries"), so they ride
    here and the scraper seeds one range per ``(type, year)`` pair.

    ``Speculative.from_int`` advances via ``model_copy``, so ``court_id``,
    :attr:`docket_type` and :attr:`year` survive each step of the probe.
    """

    #: ``court_id`` is inherited from ``CourtRange``.

    docket_type: str
    """The docket-number type prefix this range walks (e.g. ``"MAP"``)."""

    year: int
    """The calendar year partition this range walks (e.g. ``2024``)."""

    def search_key(self) -> str:
        """Return the site's addressing key — the docket-type prefix."""
        return self.docket_type

    def docket_number_for(self, sequence: int) -> str:
        """Build the API docket number for ``sequence`` in this range."""
        return f"{sequence} {self.docket_type} {self.year}"


# =========================================================================
# Shared leaf models
# =========================================================================


class PACMSAddress(ScrapedData):
    """A mailing address attached to a case participant or attorney.

    Maps loosely onto CL ``AttorneyOrganization`` when it carries an
    ``employer_name``. The API returns the address pre-split into display
    lines rather than as structured city/state/zip fields, so the lines are
    kept verbatim.
    """

    address_lines: list[str] = []
    """Address as the API returns it, one display line per element. The last
    line is conventionally ``"City, ST ZIP"`` but is not guaranteed to be."""

    address_type: str | None = None
    """Address kind, e.g. ``"Mailing"``."""

    employer_name: str | None = None
    """Law firm / employer at this address (CL ``AttorneyOrganization.name``)."""

    phone: str | None = None
    """Primary phone number (CL ``Attorney.phone``)."""

    secondary_phone: str | None = None
    """Secondary phone number, when a second one is on file."""

    fax: str | None = None
    """Fax number (CL ``Attorney.fax``)."""

    receives_email: bool | None = None
    """Whether this address is flagged to receive e-service."""

    receives_fax: bool | None = None
    """Whether this address is flagged to receive fax service."""

    receives_mail: bool | None = None
    """Whether this address is flagged to receive postal service."""


class PACMSAttorney(ScrapedData):
    """An attorney of record for one party on this case.

    CL ``Attorney`` + ``Role`` (the attorney↔party↔docket edge). The
    ``represented_*`` fields carry the party side of that edge.
    """

    name: str | None = None
    """Attorney name as it appears on documents, e.g.
    ``"Jason David Javie, Esq."`` (CL ``Attorney.name``)."""

    display_name: str | None = None
    """Sort-order form of the name, e.g. ``"Javie, Jason David"``."""

    first_name: str | None = None
    """Given name."""

    middle_name: str | None = None
    """Middle name."""

    last_name: str | None = None
    """Family name."""

    title: str | None = None
    """Honorific or title, when present."""

    pa_bar_number: str | None = None
    """Pennsylvania bar identification number."""

    is_active: bool | None = None
    """Whether the appearance is currently active."""

    representation_type: str | None = None
    """Nature of the representation, when the API supplies it."""

    date_entry_of_appearance: date | None = None
    """Date the entry of appearance was filed."""

    date_withdrawal_of_appearance: date | None = None
    """Date the withdrawal of appearance was filed (CL ``Role.date_action``)."""

    ifp_status_type: str | None = None
    """In-forma-pauperis status recorded against this appearance."""

    represented_party_name: str | None = None
    """Name of the party this attorney represents on the case."""

    represented_party_role: str | None = None
    """That party's role, e.g. ``"Appellant"`` (CL ``Role.role_raw`` context)."""

    addresses: list[PACMSAddress] = []
    """Addresses of record for this appearance."""

    phone_numbers: list[str] = []
    """Loose phone numbers the API attaches outside the address records."""


class PACMSParty(ScrapedData):
    """A participant in the case.

    CL ``Party`` + ``PartyType`` (the party↔docket edge carries the role).
    """

    name: str | None = None
    """Party name as it appears on documents (CL ``Party.name``)."""

    display_name: str | None = None
    """Sort-order form of the name, e.g. ``"T., M."``."""

    first_name: str | None = None
    """Given name, for natural persons."""

    middle_name: str | None = None
    """Middle name, for natural persons."""

    last_name: str | None = None
    """Family name, or the whole name for organizations."""

    title: str | None = None
    """Honorific or title, when present."""

    role: str | None = None
    """Role on this docket, e.g. ``"Appellant"``/``"Appellee"``
    (CL ``PartyType.name``)."""

    role_sort_order: int | None = None
    """The API's ordering weight for the role; lower sorts first."""

    is_pro_se: bool | None = None
    """Whether the participant is self-represented."""

    aliases: list[str] = []
    """Other names on file for this participant (AKAs)."""

    date_of_birth: date | None = None
    """Primary date of birth. Normally ``None`` on appellate dockets."""

    gender: str | None = None
    """Gender as recorded by the case-management system, when present."""

    race: str | None = None
    """Race as recorded by the case-management system, when present."""

    fingerprint_status: str | None = None
    """Fingerprint status, e.g. ``"Not Applicable"`` on civil appeals."""

    ifp_status_type: str | None = None
    """In-forma-pauperis status for this participant."""

    addresses: list[PACMSAddress] = []
    """Addresses of record for this participant."""

    attorneys: list[PACMSAttorney] = []
    """Attorneys entered on this participant's behalf."""


class PACMSFiler(ScrapedData):
    """The filer credited with a registry (docket) entry."""

    filer_type: str | None = None
    """Filer category, e.g. ``"Court"`` or a party-side value."""

    name: str | None = None
    """Filer name, e.g. ``"Per Curiam"`` for court-issued entries."""

    participant_role: str | None = None
    """The filer's role on the case, when they are a participant."""

    representing: list[str] = []
    """Names of the participants this filer was acting for."""


class PACMSService(ScrapedData):
    """One service record hung off a registry entry.

    Who a filing was served on, how, and whether it was distributed. CL has no
    service table; captured per ``CL_MODELS.md`` rather than dropped.
    """

    sent_method_name: str | None = None
    """Service method, e.g. ``"eService"``."""

    date_sent: date | None = None
    """Date the document was sent."""

    status: str | None = None
    """Service status, e.g. ``"Distributed"``."""

    date_status: date | None = None
    """Date the service status was set."""

    served_by_name: str | None = None
    """Name of the party/office that served the document."""

    served_to_name: str | None = None
    """Name of the recipient."""


class PACMSDocketEntry(ScrapedData):
    """One row of the PACMS register of actions (a ``registryEntries`` item).

    CL ``DocketEntry``. The API has no per-entry document URL — see
    ``CC_NOTES.md``, "Documents" — so there is no ``RECAPDocument`` analogue
    to emit from this API.
    """

    date_filed: date | None = None
    """Date the entry was filed (CL ``DocketEntry.date_filed``)."""

    time_filed: time | None = None
    """Time of day the entry was filed, when the API supplies one
    (CL ``DocketEntry.time_filed``)."""

    entry_number: int | None = None
    """The API's ``sequenceNumber`` for the entry
    (CL ``DocketEntry.entry_number``)."""

    description: str | None = None
    """Text of the entry (CL ``DocketEntry.description``). Populated from
    ``documentTitle`` when present, else the ``registryEntryCode``."""

    registry_entry_code: str | None = None
    """The coded entry type, e.g.
    ``"Order Granting Application for Nunc Pro Tunc Relief"``."""

    document_title: str | None = None
    """Full document title as filed, when distinct from the code."""

    document_number: str | None = None
    """Document number the court assigned, when present."""

    date_document: date | None = None
    """Date on the document itself, when it differs from the filed date."""

    is_sealed: bool | None = None
    """Whether the entry is sealed."""

    date_order_exited: date | None = None
    """Date an order on this entry was exited."""

    comment_lines: list[str] = []
    """Free-text comment lines attached to the entry, one per display line.
    For orders this is frequently the full text of the order."""

    applies_to: list[str] = []
    """Names of the participants the entry applies to."""

    filers: list[PACMSFiler] = []
    """Who filed the entry."""

    service: list[PACMSService] = []
    """Service records generated by the entry."""

    entry_role: str | None = None
    """Which slot this entry came from. ``"registry"`` for a normal register
    row; ``"final_disposition"``, ``"remittal"``, ``"reargument_petition"`` or
    ``"reargument_disposition"`` for the four singleton entries the API also
    surfaces as dedicated top-level objects."""


class PACMSDisposition(ScrapedData):
    """A disposition event on the case (a ``dispositionEvents`` item)."""

    disposition: str | None = None
    """The disposition itself, e.g. ``"Affirmed"``."""

    disposition_category: str | None = None
    """Category of the disposition, e.g. ``"Decided"``."""

    date_disposition: date | None = None
    """Date of the disposition (feeds CL ``Docket.date_terminated`` when
    :attr:`is_final`)."""

    date_disposition_filed: date | None = None
    """Date the dispositional document was filed, when distinct."""

    disposition_method: str | None = None
    """How the case was disposed, when the API supplies it."""

    is_final: bool | None = None
    """Whether this is the final disposition of the case."""

    journal_number: str | None = None
    """Journal number for the disposition, when assigned."""

    date_judgment: date | None = None
    """Date of the judgment associated with the disposition."""

    was_defendant_present: bool | None = None
    """Whether the defendant was present; criminal cases only."""

    disposing_authority_str: str | None = None
    """Judge or authority that entered the disposition, as a string
    (CL ``*_str`` convention — resolution happens downstream)."""

    filer_names: list[str] = []
    """Names credited with the disposition, e.g. ``["Per Curiam"]``. For an
    authored opinion this carries the authoring justice."""

    comment_lines: list[str] = []
    """Free-text lines of the disposition, one per display line. Usually the
    operative text of the order."""


class PACMSBriefingScheduleItem(ScrapedData):
    """One paper-book / brief obligation on the case briefing schedule.

    A **deadline ledger**, not a calendar: each row is a filing obligation
    with a due date and (once satisfied) a filed date. Kept as its own type
    rather than folded into :class:`PACMSDocketEntry`, which records events
    that actually happened.
    """

    type_name: str | None = None
    """Kind of paper book, e.g. ``"Brief"``, ``"Reply Brief"``,
    ``"Reproduced Record"``."""

    date_due: date | None = None
    """Current due date for the filing."""

    date_filed: date | None = None
    """Date it was actually filed; ``None`` while outstanding."""

    party_name: str | None = None
    """Party who owes (or filed) the paper book."""

    party_role: str | None = None
    """That party's role, e.g. ``"Appellant"``."""


class PACMSOriginatingCourt(ScrapedData):
    """Lower-court origin of the appeal (a ``caseOriginations`` item).

    CL ``OriginatingCourtInformation`` — one step down the chain.
    """

    docket_number: str | None = None
    """Docket number in the lower court
    (CL ``OriginatingCourtInformation.docket_number``)."""

    court_name: str | None = None
    """Lower court/tribunal name as the source spells it."""

    court_office_name: str | None = None
    """Specific office/division within the lower tribunal, when present."""

    assigned_to_str: str | None = None
    """Lower-court judge, as a string (CL ``assigned_to_str``)."""

    initial_authority_str: str | None = None
    """The initial deciding authority, when the API distinguishes it from
    the one whose order is on appeal."""

    otn: str | None = None
    """Offense tracking number, for criminal originations."""

    ltn: str | None = None
    """Local tracking number, for criminal originations."""


class PACMSRelatedCase(ScrapedData):
    """A related case reference.

    Populated from ``caseHistory`` (the same matter's other PACMS dockets) and
    ``crossCourtCaseHistory`` (its dockets in other PA courts). Maps loosely
    onto CL ``CaseTransfer`` — an appeal chain — but the API does not label
    the transfer type, so the relationship is recorded verbatim instead.
    """

    docket_number: str | None = None
    """Docket number of the related case."""

    case_name: str | None = None
    """Short caption of the related case."""

    date_filed: date | None = None
    """Filing date of the related case."""

    status_name: str | None = None
    """Status of the related case, e.g. ``"Closed"``."""

    court: str | None = None
    """CourtListener court id, when the related case is in one of the three
    appellate courts; ``None`` for trial-court references."""

    court_name: str | None = None
    """Court name as the API spells it."""

    court_office_name: str | None = None
    """Court office/district of the related case."""

    api_url: str | None = None
    """The API ``href`` for the related case — directly fetchable."""

    relationship: str | None = None
    """Which list the reference came from: ``"case_history"`` or
    ``"cross_court_case_history"``."""


class PACMSSupremeCourtInfo(ScrapedData):
    """Supreme-Court-specific case metadata (``supremeCourtInformation``).

    Present on Supreme Court dockets; the allocatur (discretionary review)
    fields are the PA analogue of cert grant/denial. Maps onto a
    court-specific 1:1 side-table in CL (cf. ``ScotusDocketMetadata``).
    """

    allocatur_docket_number: str | None = None
    """Docket number of the allocatur petition this appeal was granted from."""

    date_allocatur_granted: date | None = None
    """Date allocatur was granted (CL ``Docket.date_cert_granted``)."""

    allocatur_grant_order_lines: list[str] = []
    """Text of the allocatur grant order, one display line per element."""

    date_appealed_order: date | None = None
    """Date of the order being appealed."""

    date_appeal_jurisdiction_noted: date | None = None
    """Date the court noted jurisdiction over the appeal."""

    appeal_of_paragraph_lines: list[str] = []
    """The "appeal of" recital identifying the order under review."""

    comment_lines: list[str] = []
    """Free-text commentary on the Supreme Court record."""

    intermediate_court_name: str | None = None
    """Intermediate appellate court the case passed through."""

    intermediate_docket_number: str | None = None
    """Docket number in that intermediate court."""

    intermediate_disposition: str | None = None
    """How the intermediate court disposed of the case."""

    date_reargument_denied: date | None = None
    """Date reargument was denied (CL ``Docket.date_reargument_denied``)."""

    reargument_disposition: str | None = None
    """Disposition of a reargument petition."""

    referring_court_name: str | None = None
    """Court that referred the matter, when applicable."""

    panel_member_names: list[str] = []
    """Justices on the panel (feeds CL ``Docket.panel_str``)."""


class PACMSOriginalRecordItem(ScrapedData):
    """A component of the certified original record transmitted on appeal."""

    contents: str | None = None
    """What the item is, e.g. ``"Part(s)"``."""

    description: str | None = None
    """Count or descriptor for the item."""

    date_filed: date | None = None
    """Date the record component was filed with the appellate court."""

    date_remittal: date | None = None
    """Date the component was remitted to the lower court."""

    comment_lines: list[str] = []
    """Free-text notes on the record component."""


class PACMSProcessingStatus(ScrapedData):
    """One entry in the case's processing-status history."""

    processing_status: str | None = None
    """Status value, e.g. ``"Completed"``, ``"Awaiting Briefing"``."""

    date_status_change: date | None = None
    """Date the case entered this status."""


class PACMSAssessmentTotals(ScrapedData):
    """Compact financial summary for the case.

    The API exposes a full transaction-level fee ledger
    (``assessmentGrandTotals.assessmentCategoryTotals[].assessments[]
    .transactions[]``). Only the category rollups are captured: appellate
    filing-fee ledgers carry little research value relative to their size, and
    CourtListener has nowhere to put them. Recorded as a deliberate omission in
    ``CC_NOTES.md`` so ``revise-scraper`` dispositions it rather than
    re-discovering it.
    """

    category: str | None = None
    """Assessment category, e.g. ``"Costs/Fees"``. ``None`` on the grand
    total row."""

    total_assessments: float | None = None
    """Total assessed in this category."""

    total_payments: float | None = None
    """Total paid (negative in the source; kept as returned)."""

    total_adjustments: float | None = None
    """Total adjustments applied."""

    total_non_monetary: float | None = None
    """Total non-monetary credit applied."""

    current_balance: float | None = None
    """Outstanding balance."""


# =========================================================================
# Main record
# =========================================================================


class PACMSDocket(ScrapedData):
    """A complete Pennsylvania appellate court case (CL ``Docket``).

    One record per PACMS docket, assembled from a single
    ``GET /public/v1/cases/{docket_number}`` response — the API returns the
    whole case document in one call, so there is no multi-page tab walk.
    """

    # --- Identity -------------------------------------------------------
    docket_number: str
    """The appellate docket number, e.g. ``"1 MAP 2024"``
    (CL ``Docket.docket_number``)."""

    docket_number_raw: str | None = None
    """Docket number exactly as the API returned it, before any normalization."""

    court: str
    """CourtListener court id: ``pa``, ``pasuperct`` or ``pacommwct``."""

    docket_type: str | None = None
    """The docket-number type prefix, e.g. ``"MAP"`` (see ``DOCKET_TYPES``)."""

    district: str | None = None
    """Court district the docket type encodes: ``"Middle"``, ``"Eastern"``,
    ``"Western"``, or ``""`` for statewide Commonwealth Court."""

    filing_year: int | None = None
    """Year component of the docket number."""

    pacms_case_id: str | None = None
    """The API's internal case id (``id.id``), stable across requests."""

    case_system: str | None = None
    """Case-management system of record; ``"PACMS"`` for appellate cases."""

    # --- Caption --------------------------------------------------------
    case_name: HarmonizedCaseName | None = None
    """Short caption, e.g. ``"M.T., Aplt. v. Pa State Police"``
    (CL ``Docket.case_name``)."""

    case_name_full: str | None = None
    """Full caption, built by joining ``longCaptionLines``
    (CL ``Docket.case_name_full``)."""

    caption_lines: list[str] = []
    """The long caption as the API returns it, one display line per element."""

    # --- Dates ----------------------------------------------------------
    date_filed: date | None = None
    """Date the appeal was filed (CL ``Docket.date_filed``)."""

    date_docketed: date | None = None
    """Date the case was docketed, when it differs from the filing date."""

    date_terminated: date | None = None
    """Date of the final disposition (CL ``Docket.date_terminated``)."""

    date_last_filing: date | None = None
    """Date of the most recent register entry
    (CL ``Docket.date_last_filing``); derived from ``docket_entries``."""

    date_cert_granted: date | None = None
    """Date allocatur (discretionary review) was granted — the PA analogue of
    cert granted (CL ``Docket.date_cert_granted``)."""

    date_reargument_denied: date | None = None
    """Date reargument was denied (CL ``Docket.date_reargument_denied``)."""

    date_lower_court_appeal_filing: date | None = None
    """Date the appeal was filed in / transmitted from the lower court."""

    date_order_application: date | None = None
    """Date of the order or application that started the matter."""

    date_actual_received: date | None = None
    """Date the filing was actually received, when tracked separately."""

    date_initiation: date | None = None
    """Case initiation date, when distinct from the filing date."""

    date_arrest: date | None = None
    """Arrest date; criminal originations only."""

    date_complaint: date | None = None
    """Complaint date; criminal originations only."""

    date_last_payment: date | None = None
    """Date of the most recent payment on the case."""

    # --- Status & classification ---------------------------------------
    status_name: str | None = None
    """Case status, e.g. ``"Active"``, ``"Closed"``."""

    current_processing_status: str | None = None
    """Latest processing status, e.g. ``"Completed"``."""

    date_processing_status_change: date | None = None
    """Date the case entered :attr:`current_processing_status`."""

    current_program_status: str | None = None
    """Program status, when the case is in a court program."""

    case_category: str | None = None
    """Category of the case, e.g. ``"Appeal"``, ``"Allocatur"``,
    ``"Miscellaneous"``."""

    docket_type_name: str | None = None
    """The API's docket-type name for the category, e.g. ``"Appeal"``."""

    docket_type_category: str | None = None
    """The docket type's own grouping, e.g. ``"Case Creation"``."""

    case_types: list[str] = []
    """Subject-matter case types, e.g. ``["Megan's Law / SORNA"]``
    (closest CL analogue: ``Docket.nature_of_suit``)."""

    case_flags: list[str] = []
    """Flags on the case, e.g. ``["Sealed Record"]``."""

    is_sealed_record: bool | None = None
    """Whether the record is sealed."""

    is_nebbia_in_effect: bool | None = None
    """Whether a Nebbia (bail-source) requirement is in effect."""

    claim_amount: float | None = None
    """Amount in controversy, for civil matters
    (closest CL analogue: ``Docket.jury_demand``)."""

    order_type: str | None = None
    """Type of the order under review, e.g. ``"Order"``."""

    initiating_document_name: str | None = None
    """Document that initiated the appeal, e.g. ``"Notice of Appeal"``
    (closest CL analogue: ``Docket.cause``)."""

    lower_tribunal_category: str | None = None
    """Category of the tribunal appealed from, e.g.
    ``"Administrative Agency"``."""

    # --- Court office ---------------------------------------------------
    court_office_name: str | None = None
    """Full office name, e.g. ``"Supreme Court Middle District"``."""

    court_office_code: str | None = None
    """Office code, e.g. ``"AP-SUP-M"``."""

    court_office_type: str | None = None
    """Office type, e.g. ``"Supreme"``."""

    court_name: str | None = None
    """Court display name as the API spells it."""

    county: str | None = None
    """County, when the case carries one (usually empty on appellate dockets)."""

    judicial_district: str | None = None
    """Judicial district, when present."""

    # --- People ---------------------------------------------------------
    assigned_to_str: str | None = None
    """Assigned judge, as a string (CL ``Docket.assigned_to_str``)."""

    panel_str: str | None = None
    """Panel members, comma-joined (CL ``Docket.panel_str``); sourced from
    ``supremeCourtInformation.panelMemberNames``."""

    # --- Origination ----------------------------------------------------
    originating_docket_numbers: str | None = None
    """All lower-court docket numbers, as the API's comma-joined string."""

    root_originating_docket_number: str | None = None
    """Docket number at the original tribunal, ``≥1`` step down."""

    root_originating_authority_str: str | None = None
    """Judge at the original tribunal (CL ``TrialCourtData.judge_str``)."""

    root_originating_organization_str: str | None = None
    """Name of the original tribunal (CL ``TrialCourtData.court_name``)."""

    appeal_from_str: str | None = None
    """Court appealed from, as a string (CL ``Docket.appeal_from_str``)."""

    # --- Tracking numbers -----------------------------------------------
    primary_otn: str | None = None
    """Primary offense tracking number, for criminal appeals."""

    primary_ltn: str | None = None
    """Primary local tracking number."""

    primary_police_incident_no: str | None = None
    """Primary police incident/complaint number."""

    # --- Next event ------------------------------------------------------
    next_event: str | None = None
    """Next scheduled event on the case, from ``latestCaseEvent``."""

    date_next_event_due: date | None = None
    """Due date of :attr:`next_event`."""

    # --- Child collections ----------------------------------------------
    docket_entries: list[PACMSDocketEntry] = []
    """The register of actions, plus the four singleton registry entries the
    API surfaces separately (tagged via ``entry_role``)."""

    parties: list[PACMSParty] = []
    """Case participants, each with their attorneys attached."""

    dispositions: list[PACMSDisposition] = []
    """Disposition events on the case."""

    briefing_schedule: list[PACMSBriefingScheduleItem] = []
    """Briefing deadline ledger."""

    originating_courts: list[PACMSOriginatingCourt] = []
    """Lower-court origins of the appeal."""

    related_cases: list[PACMSRelatedCase] = []
    """Same-matter and cross-court docket references."""

    original_record_contents: list[PACMSOriginalRecordItem] = []
    """Components of the certified original record."""

    processing_statuses: list[PACMSProcessingStatus] = []
    """Full processing-status history."""

    assessment_totals: list[PACMSAssessmentTotals] = []
    """Category-level financial rollups (see :class:`PACMSAssessmentTotals`)."""

    supreme_court_information: PACMSSupremeCourtInfo | None = None
    """Supreme-Court-specific metadata, when the API supplies it."""

    # --- Provenance -------------------------------------------------------
    source_url: str | None = None
    """The API URL this record was fetched from."""

    source_entry_point: str | None = None
    """Which entry point produced this record."""
