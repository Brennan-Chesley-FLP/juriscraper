from __future__ import annotations

from datetime import date
from enum import Enum

from jkent.common.data_models import ScrapedData

from juriscraper.state.common_models import CleanString, HarmonizedCaseName

from .vocabularies import CodedPublicationStatus

# Court ID mapping: CourtListener ID → display name. IDs match the classic
# juriscraper opinion scrapers (juriscraper/opinions/.../state/calctapp_*),
# which give each Fourth-District division its own id — so every site
# case-number prefix maps to a distinct CourtListener court.
COURT_IDS: dict[str, str] = {
    "cal": "California Supreme Court",
    "calctapp_1st": "California Court of Appeal, First Appellate District",
    "calctapp_2nd": "California Court of Appeal, Second Appellate District",
    "calctapp_3rd": "California Court of Appeal, Third Appellate District",
    "calctapp_4th_div1": "California Court of Appeal, Fourth Appellate District, Division 1",
    "calctapp_4th_div2": "California Court of Appeal, Fourth Appellate District, Division 2",
    "calctapp_4th_div3": "California Court of Appeal, Fourth Appellate District, Division 3",
    "calctapp_5th": "California Court of Appeal, Fifth Appellate District",
    "calctapp_6th": "California Court of Appeal, Sixth Appellate District",
}

# Site internal court config: prefix → (dist param, CourtListener ID)
COURT_CONFIG: dict[str, tuple[str, str]] = {
    "S": ("0", "cal"),
    "A": ("1", "calctapp_1st"),
    "B": ("2", "calctapp_2nd"),
    "C": ("3", "calctapp_3rd"),
    "D": ("41", "calctapp_4th_div1"),
    "E": ("42", "calctapp_4th_div2"),
    "G": ("43", "calctapp_4th_div3"),
    "F": ("5", "calctapp_5th"),
    "H": ("6", "calctapp_6th"),
}

BASE_URL = "https://appellatecases.courtinfo.ca.gov"
SEARCH_URL = f"{BASE_URL}/search.cfm"


class CaAppCaseUnavailable(ScrapedData):
    """Yielded when a speculative case number search returns 'Case Not Found'.

    This may indicate the case doesn't exist, the number was never assigned,
    or the case is confidential.
    """

    docket_number: str
    """The case number that was searched (e.g., 'H000001')."""

    court: str
    """CourtListener court ID (e.g., 'calctapp_6th')."""


class CaAppDocketEntry(ScrapedData):
    """A single entry from the Docket (Register of Actions) tab.

    Maps to CourtListener ``DocketEntry``. Everything here has happened; the
    Court-of-Appeal "Scheduled Actions" tab lists things that have *not*, and
    is kept separate as ``CaAppScheduledAction``.
    """

    date_filed: date | None = None
    """Date of the docket entry (mm/dd/yyyy on site)."""

    description: CleanString
    """Description of the action (e.g., 'Petition for review filed')."""

    notes: CleanString | None = None
    """Additional notes, may contain party/attorney names."""


class CaAppScheduledAction(ScrapedData):
    """One outstanding deadline from the CoA "Future Scheduled Actions" tab.

    Deliberately **not** a ``CaAppDocketEntry``. Despite the tab's name this
    is a deadline ledger, not a calendar of sittings: the columns are
    Description / Due Date / Notes, and a row reads "Appellant's opening
    brief." against 06/17/2026 -- meaning the brief is *owed* by then.

    Folding these into ``CaAppDocket.entries`` would put rows in the
    CourtListener ``DocketEntry`` stream that assert a filing which has not
    happened, every one of them with a null ``date_filed``. It would also
    duplicate: the descriptions are the anticipated forms of entries the
    Register of Actions gets later ("Record on appeal filed.", "Filing fee.",
    "Civil case information statement filed."), so a case would carry both
    the expected and the actual row for one event.

    The nearest existing analogue is ``CaAppBrief.date_due`` -- a filing the
    court is waiting on -- not a register-of-actions row.
    """

    description: CleanString
    """What is due (e.g., "Appellant's opening brief.")."""

    date_due: date | None = None
    """The deadline. Routinely blank -- the site often puts the detail in
    ``notes`` instead ("Filing fee." / "No filing fee paid.07/23/2026")."""

    notes: CleanString | None = None
    """Free text; sometimes carries a date of its own, run together with the
    prose exactly as the site emits it."""


class CaAppBriefParty(ScrapedData):
    """One party (with its attorneys) credited with filing a brief.

    The Briefs table's "Party and Attorney" cell is a ``<br>``-separated run
    of ``"<Role>: <Name>"`` lines each followed by zero or more
    ``"Attorney: <Name>"`` lines (or a bare ``"Pro Per"``), and a single cell
    can list several parties — so one cell becomes a list of these.
    """

    name: CleanString
    """Party name (e.g., 'Randy Copley')."""

    role: CleanString | None = None
    """Role on the appeal (e.g., 'Defendant and Appellant')."""

    attorneys: list[CleanString] = []
    """Attorneys named for this party. Empty when self-represented."""

    pro_per: bool = False
    """True when the cell says 'Pro Per' instead of naming an attorney."""


class CaAppBriefNotesCredit(ScrapedData):
    """A party/attorney credit recovered from the Briefs ``Notes`` cell.

    Deliberately separate from :class:`CaAppBriefParty`, and lower-fidelity:
    older cases repeat the filing party and attorney inside ``Notes`` in a
    ``Party: Last, First`` / ``Attorney: Last, First`` form, and on some rows
    that is the *only* place an attorney appears. The values are kept
    verbatim rather than reconciled into ``filed_by`` because they are not
    trustworthy as canonical names — they use ``Last, First`` order, are
    sometimes abbreviated to initials (``Atty: Tone, F.``), carry trailing
    rule/document parentheticals (``Ott, Thomas H. (Rule 40(k).)``), can be
    compound (``Eisen, Jay-Allen & Boone, Daniel``), and occasionally split
    across a ``<br>``. Roughly 77% of them merely duplicate the authoritative
    "Party and Attorney" cell.
    """

    party: CleanString | None = None
    """Party name as written in ``Notes``. None for an unpaired attorney."""

    attorneys: list[CleanString] = []
    """Attorneys the ``Notes`` cell pairs with this party (positionally)."""


class CaAppBrief(ScrapedData):
    """A brief filing record from the Briefs tab."""

    brief_type: CleanString
    """Type/description (e.g., 'Opening brief on the merits filed')."""

    date_filed: date | None = None
    """Date the brief was filed. None while the brief is still outstanding."""

    date_due: date | None = None
    """Deadline for a brief not yet filed.

    The site clears this once the brief arrives, so in practice it is
    populated exactly on the rows where ``date_filed`` is None.
    """

    filed_by: list[CaAppBriefParty] = []
    """Parties (and their attorneys) associated with the brief.

    From the authoritative "Party and Attorney" column. Left exactly as that
    column reports it — ``notes_filed_by`` is *not* merged in.
    """

    notes_filed_by: list[CaAppBriefNotesCredit] = []
    """Party/attorney credits recovered from the ``Notes`` column.

    Older cases put filing credits here, sometimes naming an attorney absent
    from ``filed_by``. Kept separate because the values are lower-fidelity;
    see :class:`CaAppBriefNotesCredit`.
    """

    notes: CleanString | None = None
    """Additional notes, with any ``Party:``/``Attorney:`` credits removed.

    Whatever prose remains after the labelled credits are lifted into
    ``notes_filed_by``. On the oldest cases this column instead continues the
    brief description (``brief_type`` "Supplemental brief filed by:" +
    ``notes`` "Respondents Cross-Appellants."), which has no labels and so
    passes through untouched.
    """


class CaAppDisposition(ScrapedData):
    """Disposition information. Structure differs between SC and CoA.

    For Supreme Court: date + description (e.g., "Opinion: Affirmed").
    For Courts of Appeal: structured fields including type, publication
    status, author, and participants.
    """

    description: CleanString
    """Disposition description (e.g., 'Voluntary dismissal')."""

    disposition_date: date | None = None
    """Disposition date."""

    disposition_type: CleanString | None = None
    """E.g., 'Final', 'Partial', 'Vacated'. CoA only."""

    disposition_notes: CleanString | None = None
    """The order's own text, which the CoA prints in the type cell.

    The site packs two things into ``Disposition Type:``, separated by a
    ``<br>``: the one-word type, then the text of the order itself ("The
    petition for writ of mandate, filed May 2, 2022 ... is denied."). On 2,788
    of 6,000 sampled Second District dispositions the cell has more than one
    line, so read whole it hands a consumer a disposition_type that is a
    paragraph. CoA only.
    """

    publication_status: CodedPublicationStatus = None
    """Publication status, coded. CoA only.

    None both when the court stated nothing and when it stated something
    :class:`~.vocabularies.CaPublicationStatus` does not cover;
    ``publication_status_raw`` tells the two apart and is always the court's
    own words.
    """

    publication_status_raw: CleanString | None = None
    """The Publication Status cell verbatim, as the site printed it."""

    author: CleanString | None = None
    """Opinion author. CoA only."""

    participants: CleanString | None = None
    """Participating justices. CoA only."""

    case_citation: CleanString | None = None
    """Case citation if assigned."""


class CaAppAttorney(ScrapedData):
    """Attorney representation record.

    Maps to CourtListener ``Attorney`` (+ ``AttorneyOrganization`` for the
    firm).
    """

    name: CleanString
    """Attorney name."""

    firm: CleanString | None = None
    """Firm or organization name."""

    address: CleanString | None = None
    """Full address (multi-line joined)."""


class CaAppParty(ScrapedData):
    """A party in the case.

    Maps to CourtListener ``Party`` (+ ``PartyType`` for the role on this
    docket).
    """

    name: CleanString
    """Party name."""

    role: CleanString | None = None
    """Role in the case (e.g., 'Defendant and Appellant')."""

    address: CleanString | None = None
    """Party address if provided."""

    attorneys: list[CaAppAttorney] = []
    """Attorneys representing this party.

    Several, routinely: the Attorney cell holds one name/firm/address block per
    attorney, and 18,429 of the Third District's held two or more.
    """

    pro_per: bool = False
    """True when the Attorney cell says "Pro Per" instead of naming anyone.

    Its own field rather than an attorney record, matching
    ``CaAppBriefParty.pro_per``. Reading it as a name invented an attorney
    called "Pro Per" on 34,780 of the Third District's party rows -- 14% of
    them -- which reads as representation where there is none.
    """


class CaAppTrialCourtInfo(ScrapedData):
    """Trial court information from the Trial Court tab (CoA cases).

    Maps to CourtListener ``OriginatingCourtInformation`` /
    ``TrialCourtData``.
    """

    trial_court_name: CleanString | None = None
    """E.g., 'San Francisco County Superior Court - Main' (CL ``court_name``)."""

    county: CleanString | None = None
    """County name."""

    trial_court_case_number: str | None = None
    """Trial court case number (CL ``docket_number_raw``)."""

    trial_court_judge: CleanString | None = None
    """Name of the trial court judge (CL ``judge_str``)."""

    judgment_date: date | None = None
    """Trial court judgment date (CL ``date_judgment``)."""


class CaAppCoaCaseLink(ScrapedData):
    """A single Court of Appeal case linked from an SC Lower Court tab."""

    district_division: CleanString | None = None
    """Court of Appeal district/division (e.g., 'Fourth Appellate District, Division Three')."""

    docket_number: str | None = None
    """Court of Appeal case number (e.g., 'G001513')."""

    case_link: str | None = None
    """URL to the Court of Appeal case page."""

    is_lead: bool = False
    """Whether this is the lead CoA case."""


class CaAppTrialCourtRef(ScrapedData):
    """One trial-court matter underlying a Supreme Court case.

    Sourced from either of the two places the SC pages name a trial court:
    the Lower Court tab's ``Trial Court`` / ``Trial Court Case Number`` pairs,
    or -- when that tab has no data at all, which is the case for 139,775 of
    the 302,103 SC dockets in a full sweep -- the summary page's ``Trial Court
    Case`` block.
    """

    name: CleanString | None = None
    """Trial court name, e.g. 'Fresno County Superior Court - Main'."""

    case_number: str | None = None
    """Trial court case number."""

    is_lead: bool = False
    """Whether the site marks this matter '(lead)' among consolidated ones."""


class CaAppLowerCourtInfo(ScrapedData):
    """Lower court information from the Lower Court tab (SC cases).

    An SC case may have multiple linked CoA cases and multiple trial
    courts (e.g., consolidated appeals from different lower courts).
    """

    coa_cases: list[CaAppCoaCaseLink] = []
    """Court of Appeal cases linked from this SC case."""

    coa_disposition: CleanString | None = None
    """CoA disposition (e.g., 'Affirmed in full')."""

    coa_disposition_date: date | None = None
    """CoA disposition date."""

    trial_courts: list[CaAppTrialCourtRef] = []
    """Trial court matters underlying this SC case.

    Filled from the Lower Court tab when it has data, and otherwise from the
    summary page's ``Trial Court Case`` block -- the two never both appear.
    """


class CaAppCrossReferencedCase(ScrapedData):
    """A related case listed under "Cross Referenced Cases".

    Its markup is unlike every other field in the summary ``<dl>``: the block
    opens with a bare ``<dt>Cross Referenced Cases:</dt>`` that has no ``<dd>``,
    and then each case is a further ``<dt>`` holding the link, paired with a
    ``<dd>`` carrying the caption. So it is read from the
    ``a[id^="relatedCase_"]`` anchors rather than by term lookup.
    """

    docket_number: str
    """The related case's number (e.g., 'S168103')."""

    case_name: CleanString | None = None
    """Caption as printed beside the link (e.g., 'LUCAS (DAVID ALLEN) ON H.C.')."""

    case_link: str | None = None
    """URL of the related case's summary page."""


class CaDocumentType(str, Enum):
    """What a :class:`CaDocument` is, as opposed to what file format it is in.

    The case summary page links these under separate labels, each with its own
    anchor id, so the kind is known from the markup rather than guessed at:
    "Supreme Court Opinion" / "Court of Appeal Opinion" (``a#pdf``, ``a#doc``)
    versus "Supreme Court Order" (``a#courtOrders``).
    """

    OPINION = "opinion"
    ORDER = "order"


class CaOpinionCollection(str, Enum):
    """Which ``courts.ca.gov`` collection an opinion file is served from.

    Read off the URL path segment (``/opinions/<segment>/``). It records *where
    the court hosts the file*, which is **not** the same as whether the opinion
    was published — do not infer one from the other. Measured over the Third
    District: 88 dockets whose disposition reads "Signed Published" have their
    file under ``nonpub``, and 97 "Signed Unpublished" ones sit under
    ``revpub``. ``CaAppDisposition.publication_status`` is the authoritative
    signal for publication.

    An unrecognised segment becomes ``UNKNOWN`` rather than failing the scrape:
    only two of the nine courts have been swept, so the vocabulary is probably
    incomplete, and the raw segment is always recoverable from
    ``CaDocument.source_url``.
    """

    NONPUB = "nonpub"
    """Unpublished-opinion collection. The bulk of Court of Appeal files."""

    PUBLISHED_AFTER_REVIEW = "revpub"
    """Published following a grant of review."""

    UNPUBLISHED_AFTER_REVIEW = "revnppub"
    """Not published following a grant of review."""

    ARCHIVE = "archive"
    """Archived opinions. The bulk of Supreme Court files, but also used by the
    Courts of Appeal (1,128 Third District files) — not an SC-only path."""

    DOCUMENTS = "documents"
    """Generic document collection."""

    UNKNOWN = "unknown"
    """A segment this vocabulary does not cover — the signal to add a member."""

    @classmethod
    def _missing_(cls, value: object) -> CaOpinionCollection:
        """Map any unrecognised segment to ``UNKNOWN`` instead of raising."""
        return cls.UNKNOWN


class CaDocument(ScrapedData):
    """A document archived from a case summary page.

    Yielded separately from ``CaAppDocket`` so that consumers can stitch the
    file back to its docket via ``docket_number`` + ``court``. One instance per
    file, so a case offering its opinion as both PDF and DOC produces two
    records. Maps to CourtListener ``RECAPDocument``.

    This is the *only* representation of a case's documents — ``CaAppDocket``
    deliberately carries no opinion-URL fields, because a fixed pair of them
    could name neither the ``.DOC`` files nor the orders.
    """

    docket_number: str
    """Case number (e.g., 'A081492'), matches CaAppDocket.docket_number."""

    court: str
    """CourtListener court ID, matches CaAppDocket.court."""

    document_type: CaDocumentType
    """What kind of document this is (opinion or order)."""

    file_format: str
    """File extension, lowercased (e.g., 'pdf', 'doc', 'docx').

    Separate from ``document_type``: the same opinion is published as both a
    PDF and a word-processor file, and which of ``.doc``/``.docx`` you get
    depends on the case's age.
    """

    source_collection: CaOpinionCollection | None = None
    """Which ``courts.ca.gov`` opinion collection served the file.

    None when the URL has no ``/opinions/<segment>/`` path — court orders, for
    instance, come from ``/documents/`` on the appellatecases host itself.
    """

    source_url: str
    """Original URL the file was downloaded from."""

    local_path: str | None = None
    """Path returned by the archive handler. None if the download was skipped."""


class CaOpinionEvidence(str, Enum):
    """What showed that a published opinion exists, on a docket with no file.

    The two courts state it differently, so the signal differs by court rather
    than being one rule applied twice.
    """

    PUBLICATION_STATUS = "publication_status"
    """A Court of Appeal disposition whose Publication Status says published."""

    OPINION_DISPOSITION = "opinion_disposition"
    """A Supreme Court disposition whose description records an opinion
    ("Opinion: Reversed"). The Supreme Court has no Publication Status field at
    all -- null on all 298,163 dispositions of a full sweep -- and its opinions
    are published as a matter of course, so the disposition is the signal."""


class CaUnavailableOpinion(ScrapedData):
    """A published opinion the site records but offers no file for.

    Emitted when a docket's disposition says the opinion was published (or
    partially published) yet the case summary page carries no opinion link, so
    no ``CaDocument`` can be produced. courts.ca.gov only serves opinion files
    for a limited window; older published opinions live in the Official Reports
    instead. This record is the evidence that such an opinion exists and the
    handle for fetching it from another source.

    Measured: 2,647 in the Third District (3,655 dockets are published, but only
    about 1,008 come with a file) and 2,864 in the Supreme Court. Both skew old
    — the Third District's are heaviest in 1986-1990 with only a handful after
    2020 — which is consistent with the serving window rather than with a scrape
    failure.

    ``case_citation`` is the most useful field for finding the text elsewhere
    and is present on 64% of the Third District's; everything else here is
    present on essentially all of them. Deliberately self-sufficient rather than
    a pointer into ``CaAppDocket``, so a consumer resolving these does not have
    to join back — though ``docket_number`` + ``court`` still match the docket.
    """

    docket_number: str
    """Case number, matches CaAppDocket.docket_number."""

    court: str
    """CourtListener court ID, matches CaAppDocket.court."""

    evidence: CaOpinionEvidence
    """Which signal showed a published opinion exists."""

    publication_status: CodedPublicationStatus = None
    """The disposition's publication status, coded (e.g. ``SIGNED_PUBLISHED``).

    Court of Appeal only -- the Supreme Court states none, so these records rely
    on ``disposition_description`` instead. Every one of these records is a
    *published* opinion, so in practice this is one of the five members whose
    ``published`` is true.
    """

    publication_status_raw: CleanString | None = None
    """The Publication Status cell verbatim, as the site printed it."""

    case_name: HarmonizedCaseName | None = None
    """Case caption."""

    case_citation: CleanString | None = None
    """Official Reports citation, when the site states one. The best handle for
    retrieving the opinion from elsewhere."""

    disposition_description: CleanString | None = None
    """What the court did (e.g. 'Affirmed in full')."""

    disposition_date: date | None = None
    """Date of the disposition -- in practice the opinion's date."""

    disposition_type: CleanString | None = None
    """E.g. 'Final'."""

    author: CleanString | None = None
    """Authoring justice."""

    participants: CleanString | None = None
    """Participating justices."""

    date_filed: date | None = None
    """Docket filing date."""

    date_terminated: date | None = None
    """Docket completion date."""

    trial_court_case_numbers: list[str] = []
    """Trial court case numbers, for cross-referencing against other sources."""

    supreme_court_case_number: str | None = None
    """Supreme Court case number, when review was sought."""

    source_url: str | None = None
    """The case summary page this was observed on."""


class CaAppDocket(ScrapedData):
    """Main output model -- a complete California appellate case docket.

    Maps to CourtListener ``Docket`` (+ its per-court side tables).
    """

    # Identifiers
    docket_number: str
    """Case number (e.g., 'S295804', 'A170000')."""

    court: str
    """CourtListener court ID (e.g., 'cal', 'calctapp_1st')."""

    # Case metadata
    case_name: HarmonizedCaseName
    """Case caption (e.g., 'PEOPLE v. SMITH')."""

    case_type: CleanString | None = None
    """Case category (SC) or case type (CoA)."""

    division: CleanString | None = None
    """Division number or name (e.g., '4', 'SF').

    Populated on exactly three courts, and it means something different on the
    Supreme Court than on the Courts of Appeal. The SC's values are its sitting
    locations (SF, LA, SD, FR, SA), not divisions. The First and Second
    Districts give a real division number. The remaining six courts render the
    ``Division:`` label with an empty value -- the Fourth District's divisions
    are already carried by the court id, and the Third, Fifth and Sixth have no
    divisions -- so None there is the site's own blank, not a missed selector.

    The legacy tail is the court's, not ours: 30,121 Second District dockets
    say ``p`` and 2,491 say ``a``; 522 First District ones say ``v``. Verified
    against the stored page for B004324, whose markup reads
    ``<dt>Division:</dt><dd>p</dd>``.
    """

    date_filed: date | None = None
    """Filing date (CoA) or start date (SC)."""

    date_terminated: date | None = None
    """Completion date. CoA only (CL ``date_terminated``)."""

    case_status: CleanString | None = None
    """Case status (e.g., 'closed; remittitur issued'). SC only."""

    date_argued: str | None = None
    """Oral argument date/time, raw text. CoA only (CL ``date_argued``).

    Also absent on the Fourth District, Division 2, which never emits the
    ``Oral Argument Date/Time:`` row -- 0 of 83,116 dockets in the August 2026
    sweep, including 22,259 that have an oral-argument docket entry. Checked
    against six random closed-and-argued Division 2 pages: the label is not in
    the markup. The other seven CoA courts fill it on 7-23% of dockets.
    """

    issues: CleanString | None = None
    """Issues text. SC only."""

    case_citation: CleanString | None = None
    """Case citation if assigned."""

    # Opinion files are not fields here -- each one is a separate
    # CaDocument result, stitched back via docket_number + court. That is
    # the single representation for both court types: it carries the download
    # (local_path) and a real document_type, so it covers the .DOC files that a
    # fixed "docx" field cannot.

    # Related case numbers
    coa_case_numbers: list[str] = []
    """Court of Appeal case numbers linked from SC case."""

    cross_referenced_cases: list[CaAppCrossReferencedCase] = []
    """Related cases from the "Cross Referenced Cases" block."""

    supreme_court_case_number: str | None = None
    """Supreme Court case number linked from a CoA case summary.

    The reciprocal of ``coa_case_numbers``: the CoA page's "Supreme Court
    Case" field, present when review was sought. Scalar because the field
    carries exactly one link wherever it appears.
    """

    trial_court_case_numbers: list[str] = []
    """Trial court case numbers associated with this CoA case.

    Usually one entry (taken from the case summary "Trial Court Case"
    field). When a docket number matches multiple rows on the search-
    results page (consolidated lower-court matters under a single CoA
    docket), all of the row's trial-court numbers are collected here.
    """

    # Nested data
    entries: list[CaAppDocketEntry] = []
    """Docket entries from the Register of Actions -- things that happened."""

    scheduled_actions: list[CaAppScheduledAction] = []
    """Outstanding deadlines from the CoA "Future Scheduled Actions" tab.

    Kept out of ``entries`` on purpose: these have not happened.

    Empty on three courts, because their pages carry no ``a#actionTab`` at all
    and so the tab is never fetched: the Supreme Court (six tabs, not seven),
    the Third District and the Fifth District. Verified on stored parties pages
    for each -- 0 of 296,776 / 98,044 / 28,677 dockets respectively in the
    August 2026 sweep, against 1.6-8.4% of dockets on the other six courts.
    """

    briefs: list[CaAppBrief] = []
    """Brief filings."""

    dispositions: list[CaAppDisposition] = []
    """Disposition records."""

    parties: list[CaAppParty] = []
    """Parties and their attorneys."""

    trial_court_info: CaAppTrialCourtInfo | None = None
    """Trial court details. CoA only."""

    lower_court_info: CaAppLowerCourtInfo | None = None
    """Lower court details. SC only."""

    source_url: str | None = None
    """URL of the case summary page."""

    source_entry_point: str | None = None
    """Entry point used to reach this docket (e.g., 'dockets_by_number')."""

    subscription_urls: list[str] = []
    """URLs to subscribe to e-mail notifications for *this* case.

    Read off ``a[id^="emailLink"]``, not off ``/email.cfm``: the left-hand nav
    carries an "E-mail" button pointing at the court-wide
    ``/email.cfm?dist=0`` subscription form, which is site chrome. Matched by
    href it landed on every docket alongside the real per-case link.
    """
