"""Data models for the Georgia Court of Appeals scraper.

The site backs a single CourtListener court (``gactapp``). Case numbers
follow ``A{YY}{LETTER}{NNNN}`` (e.g. ``A26A1234``); the letter encodes the
appeal type — see ``CASE_TYPE_DESCRIPTIONS``.

Field names follow [`../../CL_MODELS.md`](../../CL_MODELS.md): the
CourtListener court-id string is ``court`` (not ``court_id``), and dates use
the ``date_*`` prefix.
"""

from __future__ import annotations

from datetime import date

from jkent.common.data_models import ScrapedData

from juriscraper.state.common_models import CleanString, HarmonizedCaseName

COURT_ID: str = "gactapp"
COURT_NAME: str = "Court of Appeals of the State of Georgia"

CASE_TYPE_DESCRIPTIONS: dict[str, str] = {
    "A": "Direct appeal",
    "D": "Discretionary application to appeal",
    "E": "Emergency motion",
    "I": "Interlocutory application",
    "O": "Original proceeding",
}


class GaCoaAttorney(ScrapedData):
    """One attorney row from the case-detail page.

    The detail page renders attorneys in two stacked tables (one per side),
    each row carrying a side label and a single name. We do not see firm or
    contact information on this site. Maps to CourtListener ``Attorney`` (+
    ``Role`` for the side on this docket).
    """

    name: CleanString
    side: CleanString | None = None
    """'Appellant' or 'Appellee' (rarely 'Cross-Appellant', etc.)."""


class GaCoaDocketEntry(ScrapedData):
    """A row of "Filings, Motions, and Court Actions" or "Court Initiated Actions".

    The detail page lists each entry as an alternating ``<kind> Date`` /
    ``<kind>`` row pair, where the kind is ``Filing``, ``Motion``, or
    ``Court Action``; the parser pairs them. There are no per-entry document
    links — the entry is text-only. Maps to CourtListener ``DocketEntry``.
    """

    date_filed: date | None = None
    description: CleanString
    entry_type: CleanString | None = None
    """Row kind as labelled on the page: 'Filing', 'Motion', 'Court Action'."""

    court_initiated: bool = False
    """True when the court, not a party, produced the entry.

    Covers every row of the "Court Initiated Actions" section plus the
    ``Court Action`` rows the filings section interleaves with motions (the
    court's ruling on the motion above it, e.g. 'EXT GRANTED').
    """


class GaCoaTrialCourtInfo(ScrapedData):
    """The "Trial Court Information" block on the detail page.

    Maps to CourtListener ``OriginatingCourtInformation``."""

    case_number: CleanString | None = None
    additional_case_numbers: list[CleanString] = []
    """Companion trial-court case numbers.

    The block repeats its ``Case Number`` row once per consolidated
    lower-court case (up to four seen) while sharing one clerk/judge/county.
    """

    clerk: CleanString | None = None
    judge: CleanString | None = None
    county: CleanString | None = None
    court: CleanString | None = None
    """Court level, e.g. 'State Court', 'Superior Court', 'Probate Court'."""

    date_appealed_order: date | None = None
    """Date of the lower-court order being appealed."""

    date_notice_of_appeal: date | None = None


class GaCoaSupremeCourtInfo(ScrapedData):
    """The "Supreme Court Information" block — present when the case has gone
    to (or come from) the Georgia Supreme Court.

    The detail page renders this as a generic key/value list; the scraper
    captures all rows verbatim into ``rows`` and also pulls out a few common
    fields when they appear.
    """

    sc_case_number: CleanString | None = None
    transfer_date: date | None = None
    rows: list[dict[str, str]] = []
    """Raw header/value pairs as seen on the page."""


class GaCoaOpinion(ScrapedData):
    """An archived opinion/order PDF.

    Both the date-range opinion search and the detail page's ``Opinion/Order``
    row link the same underlying PDF on ``efast.gaappeals.gov``, and both fan
    out an archive request for it under one dedup key. Maps to CourtListener
    ``RECAPDocument``.
    """

    docket_number: str
    """e.g. 'A26A0274' — joins back to a GaCoaDocket."""

    download_url: str
    """The original ``efast.gaappeals.gov/download?filingId=…`` URL."""

    filing_id: str | None = None
    """The ``filingId`` UUID parsed out of ``download_url``."""

    date_judgment: date | None = None
    """Disposition date as shown in the search results table."""

    judgment_ruling: CleanString | None = None
    """e.g. 'AFFIRMED', 'DISCRETIONARY APPLICATION DENIED', 'DISMISSED'."""

    local_path: str | None = None

    source_entry_point: str | None = None
    """Entry point used to reach this opinion (e.g. ``opinions_by_decision_date``)."""


class GaCoaDocket(ScrapedData):
    """A complete Georgia Court of Appeals docket.

    Maps to CourtListener ``Docket`` (+ its per-court side tables)."""

    # === Searchable fields ===
    docket_number: str
    """Public case number, e.g. 'A26A1234'."""

    court: str = COURT_ID
    """CourtListener court ID (``gactapp``)."""

    date_filed: date | None = None
    """The 'Docket/Notice Date' from the detail page."""

    case_name: HarmonizedCaseName
    """The 'Style' from the detail page."""

    # === Case metadata ===
    case_type: CleanString | None = None
    """One-letter code; see ``CASE_TYPE_DESCRIPTIONS``."""

    case_type_description: CleanString | None = None

    case_status: CleanString | None = None
    """e.g. 'Case Pending', 'Case Pending-Briefs Filed', 'Case Closed'."""

    date_remittitur: date | None = None
    """When remittitur has issued, else None."""

    term: CleanString | None = None
    """Court term the case was assigned to, e.g. 'April'."""

    supreme_court_transfer: CleanString | None = None
    """Free-text marker when the case has been transferred to/from GA Supreme Court."""

    calendar_date: CleanString | None = None
    """Calendar period text, e.g. 'May 2026'. Free-form, not always parseable."""

    # === Disposition ===
    date_judgment: date | None = None
    judgment_ruling: CleanString | None = None
    """e.g. 'DISMISSED', 'DISCRETIONARY APPLICATION DENIED'.

    Both fields come from the detail page's ``COA Judgment/Ruling`` cell
    (``RULING (date)``), which appears only once the case is decided; the
    opinion-search row supplies them as a fallback.
    """

    opinion_url: str | None = None
    """``efast.gaappeals.gov/download?filingId=…`` from the detail page's
    ``Opinion/Order`` row — present alongside ``judgment_ruling``, and archived
    as a ``GaCoaOpinion`` joined back on ``docket_number``."""

    opinion_filing_id: str | None = None
    """The ``filingId`` UUID parsed out of ``opinion_url``."""

    # === Nested data ===
    entries: list[GaCoaDocketEntry] = []
    attorneys: list[GaCoaAttorney] = []
    trial_court: GaCoaTrialCourtInfo | None = None
    supreme_court: GaCoaSupremeCourtInfo | None = None

    source_url: str | None = None
    """The detail-page URL used to build this record."""

    source_entry_point: str | None = None
    """Entry point used to reach this docket (e.g. ``dockets_by_number``)."""


# =========================================================================
# Site constants
# =========================================================================

SITE_BASE = "https://www.gaappeals.gov"
DOCKET_BASE = f"{SITE_BASE}/wp-content/themes/benjamin/docket"
DETAIL_URL = f"{DOCKET_BASE}/results_one_record.php"
OPINION_SEARCH_URL = f"{DOCKET_BASE}/docketdate/results_all.php"
