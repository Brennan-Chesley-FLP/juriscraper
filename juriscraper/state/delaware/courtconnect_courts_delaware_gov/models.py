"""Data models for Delaware CourtConnect (courtconnect.courts.delaware.gov).

CourtConnect is the public face of Avenu/Neumo "Contexte" and fronts every
Delaware trial court from one docket-report endpoint. The court a case belongs
to is encoded in the **shape of its case id**, not in any request parameter:
``2025-1110`` is a Court of Chancery case, ``N22C-09-501`` a Superior Court
one, ``JP17-20-002897`` a Justice of the Peace one. This scraper's speculative
entry walks the Chancery ``{YYYY}-{NNNN}`` space; the single-record entry
accepts any case id the site serves.

Field names follow ``CL_MODELS.md`` so the merge into CourtListener is
mechanical.
"""

from __future__ import annotations

from datetime import date, time
from enum import Enum

from jkent.common.data_models import ScrapedData


class DeNumberSpace(str, Enum):
    """The distinct case-number spaces this scraper walks.

    CourtConnect addresses every court through one endpoint, so a "space" is a
    *number format* plus the era it covers — not a court. Two of them belong to
    the same court (Chancery before and after its 2017 renumbering), and one
    court's cases are split across an archival and a modern form.

    Ordering below is chronological within each court.
    """

    CHANCERY = "chancery"
    """Chancery ``{YYYY}-{NNNN}``, 2017-01-01 onward. Year-partitioned."""

    CHANCERY_LEGACY = "chancery_legacy"
    """Chancery's pre-2017 flat integer, running to 13013 (2016-12-30).

    Shared with a handful of unrelated Justice of the Peace cases at very low
    numbers, so records from this space are kept only when the case type
    resolves to Chancery."""

    SUPERIOR_APPEAL = "superior_appeal"
    """Superior Court's appellate docket, ``{County}{YY}A-{MM}-{NNN}``.

    Late 2009 onward. County- **and** month-partitioned: the sequence restarts
    each month, densely from 001."""

    SUPERIOR_APPEAL_ARCHIVAL = "superior_appeal_archival"
    """The same docket in its pre-2009 form, ``S{County}{YY}A-{MM}-{NNN}``.

    Observed from 1991 through 2008; ``SN08A`` hits where ``SN10A`` misses and
    ``N09A`` hits where ``N08A`` misses, so the two forms abut rather than
    overlap."""

    COMMON_PLEAS = "common_pleas"
    """Common Pleas civil, ``CPU{unit}-{YY}-{NNNNNN}``.

    Mixes appeals from the Justice of the Peace courts in with ordinary
    first-instance civil cases, and the number does not distinguish them — so
    records from this space are kept only when the case type is an appeal."""

    COMMON_PLEAS_LEGACY = "common_pleas_legacy"
    """Common Pleas civil in its older form, ``U{unit}{YY}-{MM}-{NNN}``.

    Month-partitioned, and the sequence width depends on the unit (see
    ``LEGACY_CP_SEQUENCE_WIDTH``). Same appeal filter as ``COMMON_PLEAS``."""


#: Spaces that are appellate in their entirety — every case in them is an
#: appeal, so no case-type test is needed.
WHOLLY_APPELLATE_SPACES: frozenset[DeNumberSpace] = frozenset(
    {
        DeNumberSpace.SUPERIOR_APPEAL,
        DeNumberSpace.SUPERIOR_APPEAL_ARCHIVAL,
    }
)

#: Spaces kept in full on the strength of the *court* rather than the case
#: type. Chancery is in scope as a court, so its whole docket is wanted; the
#: test exists only to drop the stray JP cases sharing the legacy integers.
CHANCERY_SPACES: frozenset[DeNumberSpace] = frozenset(
    {
        DeNumberSpace.CHANCERY,
        DeNumberSpace.CHANCERY_LEGACY,
    }
)

#: The CourtConnect application root.
BASE_URL = "https://courtconnect.courts.delaware.gov/cc/cconnect"

#: The one endpoint this scraper reads. Takes ``case_id`` plus an (apparently
#: inert -- see CC_NOTES.md) ``begin_date``/``end_date`` docket-entry window,
#: and renders the whole case -- description, related cases, event schedule,
#: parties and docket entries -- as a single server-rendered page.
DOCKET_REPORT_URL = f"{BASE_URL}/ck_public_qry_doct.cp_dktrpt_docket_report"

#: CourtListener court ids this scraper covers, mapped to their display names.
#:
#: Delaware's Supreme Court (``del``) is **not** here because it is not on this
#: portal: the case-type vocabulary has no Supreme Court family, and every id
#: shape observed resolves to Chancery, Superior, Common Pleas or JP. Family
#: Court (``delfamct``) is likewise absent — its records are confidential.
COURT_IDS: dict[str, str] = {
    "delch": "Delaware Court of Chancery",
    "delsuperct": "Superior Court of Delaware",
    "delctcompl": "Delaware Court of Common Pleas",
}

#: Case-type prefix -> CourtListener court id.
#:
#: The leading character of the site's case-type code ("2A - CIVIL ACTIONS") is
#: the only court signal a docket report carries. Each entry below was checked
#: against a real docket on 2026-09-14:
#:
#: * ``2`` — Chancery. All 110 ``{YYYY}-{NNNN}`` cases sampled returned
#:   ``2A - CIVIL ACTIONS``, on pages whose docket text names the Register in
#:   Chancery and whose JUDGE rows name sitting Vice Chancellors.
#: * ``A`` — Superior Court's appellate docket (``AA`` administrative agency,
#:   ``AB`` from Common Pleas, ``AC`` certiorari, ``AD`` industrial accident
#:   board, ``AF`` unemployment, ``AG`` marijuana commission), seen on
#:   ``N24A-01-001``, ``S24A-01-001``, ``K24A-02-001``.
#: * ``C`` / ``L`` — Superior Court civil and lien/mortgage dockets
#:   (``N24C-04-195``, ``N19L-10-078``).
#: * ``4`` — Common Pleas (``CPU4-23-000459``, ``U497-02-290``).
#: * ``6`` — Justice of the Peace (``JP13-22-005065``, ``J0105046113``).
#: * ``3`` — Superior Court. Not confirmed against a live docket; included
#:   because every ``3*`` label in the site's own vocabulary reads
#:   "SUPERIOR CT …".
#:
#: Deliberately **unmapped**, so they fall back to the caller's court id rather
#: than to a guess: ``J`` (judgment dockets, whose second letter names the
#: *originating* court — ``JD`` Common Pleas, ``JL`` Justice of the Peace,
#: ``JH`` Division of Revenue — while the docket itself is Superior Court's),
#: and ``D`` / ``M`` / ``N`` / ``I`` / ``Z``, none of which were observed.
CASE_TYPE_COURTS: dict[str, str] = {
    "2": "delch",
    "3": "delsuperct",
    "4": "delctcompl",
    "6": "deljustpct",
    "A": "delsuperct",
    "C": "delsuperct",
    "L": "delsuperct",
}

#: Case-type codes that mark the case as an **appeal**.
#:
#: Needed only for number spaces that mix appellate and original-jurisdiction
#: cases — Common Pleas' civil docket, above all, where a JP appeal carries an
#: ordinary ``CPU…`` number indistinguishable from a first-instance debt claim.
#: Superior Court's ``A`` dockets need no such test: the whole space is
#: appellate by construction.
#:
#: Taken from the portal's own case-type dropdown. The Superior entries are
#: that court sitting as Delaware's intermediate appellate court; the Common
#: Pleas entries are appeals up from the Justice of the Peace courts and from
#: administrative bodies.
APPEAL_CASE_TYPES: frozenset[str] = frozenset(
    {
        # Superior Court sitting appellate.
        "3A",  # SUPERIOR CT CIVIL APPEALS
        "AA",  # ADMINISTRATIVE AGENCY
        "AB",  # COURT OF COMMON PLEAS
        "AC",  # CERTIORARI
        "AD",  # INDUSTRIAL ACCIDENT BOARD
        "AE",  # PUBLIC SERVICE COMMISSION
        "AF",  # UNEMPLOYMENT INSURANCE BOARD
        "AG",  # MARIJUANA COMMISSION BOARD
        "AH",  # PURCHASER CARD APPEAL JP COURT
        "AI",  # BOARD OF ASSESSMENT
        "M0",  # APPEAL FROM DISABILITY BOARD
        "CA",  # AUTO ARBITRATION APPEAL
        # Court of Common Pleas sitting appellate.
        "4L",  # JP APPEAL WITHOUT FEES
        "4M",  # JP APPEAL WITH FEES
        "4P",  # ADMINISTRATIVE MV APPEAL
        "4Q",  # RED LIGHT APPEAL
        "4R",  # DOG PANEL APPEAL
        "4S",  # SEATBELT APPEAL WITH FEES
        "4T",  # SEATBELT APPEAL WITHOUT FEES
        "4Y",  # SPEED JP APPEAL
    }
)

#: County letters used in Superior Court case ids.
COUNTY_CODES: dict[str, str] = {
    "N": "New Castle",
    "K": "Kent",
    "S": "Sussex",
}

#: Common Pleas unit numbers, as they appear in ``CPU{unit}-…`` and
#: ``U{unit}{YY}-…`` ids. The county reading follows relative volume (unit 4 is
#: several times the size of 5 and 6, matching New Castle's share of the
#: state), and is recorded as an inference, not a site-stated fact.
COMMON_PLEAS_UNITS: dict[int, str] = {
    4: "New Castle (inferred)",
    5: "Kent (inferred)",
    6: "Sussex (inferred)",
}

#: Sequence width in the **legacy** Common Pleas ``U{unit}{YY}-{MM}-…`` ids.
#:
#: Per *unit*, not per year — verified 2026-09-14 by probing the same month of
#: the same years across units: ``U400-05-001`` and ``U600-05-0001`` behave
#: opposite ways, and ``U500-05-0001`` hits where ``U500-05-001`` misses, in
#: both 2000 and 2005.
LEGACY_CP_SEQUENCE_WIDTH: dict[int, int] = {4: 3, 5: 4, 6: 3}

#: The site's placeholder for "this case has no such rows".
ABSENT_SECTION_PHRASES = (
    "no related cases were found",
    "no case events were found",
    "no docket entries found",
)

#: What the docket report renders instead of a case when ``case_id`` does not
#: exist. Returned with HTTP 200, so it is a soft-404 (see
#: ``DeCourtConnectScraper.actually_successful``).
SOFT_404_PHRASE = "no case was found"


class DeCourtConnectParty(ScrapedData):
    """One row of the Case Parties table.

    CourtConnect models judges and attorneys as party rows alongside the
    litigants, distinguished only by ``party_type``, and ties an attorney to
    the litigant it represents through ``associated_sequence_number`` (the
    "Assoc" column, which names another row's ``sequence_number``). The rows
    are kept verbatim -- splitting them into CL's Party/Attorney/Role graph is
    a downstream concern, and the association is only recoverable from these
    two columns.
    """

    sequence_number: int | None = None
    """The row's "Seq #" -- this party's index within the case."""

    associated_sequence_number: int | None = None
    """The "Assoc" column: the ``sequence_number`` of the row this one is tied
    to. On an ATTORNEY row it is the party represented; on a litigant row it
    points back at the attorney."""

    id_code: str | None = None
    """The site's person id for this party (``@4209677`` for a case-specific
    party record, ``002234`` for a bar-registered attorney or judge).

    Recorded but **never followed**: the person-detail link the site hangs off
    this id rejects an id-only lookup with "Search criteria entered is
    invalid", and the name search that would reach it returns no records at all
    for Chancery case types. The id is still worth keeping -- it is the only
    stable identifier the site gives a person, and it joins parties across
    cases without name matching."""

    party_type: str | None = None
    """The "Type" column: PLAINTIFF, DEFENDANT, JUDGE, ATTORNEY, ..."""

    name: str | None = None
    """The party's name as printed."""

    date_terminated: date | None = None
    """The "Party End Date" column, when the party left the case."""

    contact_raw: str | None = None
    """The address block, newline-joined. The site prints "unavailable" for a
    party with no address on file; that is normalised to ``None``."""

    aliases: list[str] = []
    """Names in the "Aliases" cell. The site prints "none" when there are
    none; that is normalised to an empty list."""


class DeCourtConnectDocketEntry(ScrapedData):
    """One row of the Docket Entries table (or of the Case Event Schedule).

    The table renders each entry as two rows: a summary row (filing date/time,
    description, name, monetary) and an "Entry:" row holding the full text.
    Both are folded into one record here.
    """

    date_filed: date | None = None
    """Filing date from the first column."""

    time_filed: time | None = None
    """Filing time, printed under the date in the same cell."""

    description: str | None = None
    """The short description ("CIVIL ACTION CASE FILED")."""

    name: str | None = None
    """The "Name" column -- the filing party, as printed."""

    monetary: str | None = None
    """The "Monetary" column, verbatim. Kept as a string: it is blank on every
    Chancery entry sampled, and on the judgment dockets where amounts do appear
    they are carried in the entry text, not this column."""

    entry_text: str | None = None
    """The "Entry:" row's full text, newlines preserved. On Chancery this is
    where the "DATE DOCKETED" line and the File & ServeXpress pointer live."""

    sequence_number: int | None = None
    """Zero-based index of the entry within its section, preserving page order
    for entries that share a filing date."""

    source_section: str = "docket_entries"
    """Which section the row came from: ``docket_entries`` or
    ``case_event_schedule``. Scheduled/future events are docket entries too --
    they are not a separate record type -- so the section is a label on the
    entry rather than a model of its own."""

    extra_fields: dict[str, str] = {}
    """Header -> value for any column this model does not name. Populated for
    Case Event Schedule rows, whose column set is unknown: no case sampled on
    2026-09-14 had a populated event schedule, so the parser reads that table
    generically rather than inventing a shape for it."""


class DeCourtConnectRelatedCase(ScrapedData):
    """One row of the Related Cases section.

    Read generically for the same reason as the event schedule: the section
    exists on every docket report and was empty on all 128 cases sampled
    (110 Chancery + 18 from other Delaware courts), so its columns have never
    been observed.
    """

    docket_number: str | None = None
    """The related case's id, when a column plausibly holds one."""

    extra_fields: dict[str, str] = {}
    """Header -> value for the row's remaining columns."""


class DeCourtConnectDocket(ScrapedData):
    """A Delaware CourtConnect case: the whole docket report, one record."""

    court: str
    """CourtListener court id (``delch`` for the ``{YYYY}-{NNNN}`` space)."""

    docket_number: str
    """The case id as the site addresses it (``2025-1110``)."""

    docket_number_raw: str
    """The case id exactly as printed in the Case Description block."""

    case_name: str | None = None
    """The caption printed after the case id.

    **Truncated by the site** to roughly 50 characters ("MIAMI BEACH FIRE &
    POLICE PENSION FND v JBS WISCON"), so it is a short caption, not a full
    one -- hence ``case_name`` rather than ``case_name_full``."""

    date_filed: date | None = None
    """The Filing Date, printed as "Thursday , February 27th, 2025"."""

    date_last_filing: date | None = None
    """Latest ``date_filed`` across the docket entries; derived, not printed."""

    case_type: str | None = None
    """The Type line verbatim ("2A - CIVIL ACTIONS")."""

    case_type_code: str | None = None
    """The code half of the Type line ("2A")."""

    case_type_description: str | None = None
    """The description half of the Type line ("CIVIL ACTIONS")."""

    status_code: str | None = None
    """The code half of the Status line ("CLOSED")."""

    status_description: str | None = None
    """The description half of the Status line. The two halves are identical on
    every case sampled, but the site renders them as a pair and they are stored
    as one."""

    assigned_to_str: str | None = None
    """The JUDGE party row's name, as a string. CourtConnect has no separate
    judge field -- the judge is a party row -- so this is derived from
    ``parties``."""

    parties: list[DeCourtConnectParty] = []
    """Every Case Parties row, litigants and judges and attorneys alike."""

    docket_entries: list[DeCourtConnectDocketEntry] = []
    """Docket Entries rows, plus any Case Event Schedule rows (tagged by
    ``source_section``)."""

    related_cases: list[DeCourtConnectRelatedCase] = []
    """Related Cases rows."""

    source_url: str | None = None
    """The docket-report URL this record was read from."""

    source_entry_point: str | None = None
    """Which entry point produced the record."""
