"""Data models for the Supreme Court of Georgia docket scraper.

The site backs a single CourtListener court (``ga``). Case numbers follow
``S{YY}{LETTER}{NNNN}`` (e.g. ``S26A0125``); the letter encodes the type of
appeal (see ``CASE_TYPE_DESCRIPTIONS``).
"""

from __future__ import annotations

from datetime import date

from jkent.common.data_models import ScrapedData

CASE_TYPE_DESCRIPTIONS: dict[str, str] = {
    "A": "Direct appeal of a superior/state/probate/juvenile court order",
    "B": "Petition to appoint a Special Master in disciplinary proceedings",
    "C": "Petition for a writ of certiorari to review a Court of Appeals decision",
    "D": "Discretionary application to appeal an order entered in superior or state court",
    "E": "Certificate of probable cause to review a death-penalty habeas decision",
    "F": "Family Law Pilot Project direct appeal (largely defunct after 2017)",
    "G": "Granted petition for a writ of certiorari",
    "H": "Certificate of probable cause to review a post-conviction habeas denial",
    "I": "Interlocutory application to appeal",
    "J": "Judicial Qualifications Commission matters before formal charges are filed",
    "M": "Emergency motion to temporarily stay a lower-court order",
    "O": "Petition filed without prior lower-court review",
    "P": "Automatic direct appeal of a capital case in which the death sentence has been imposed",
    "Q": "Question of law certified to the Supreme Court by a federal court",
    "R": "Interim appellate review of pre-trial orders in death-penalty cases",
    "T": "Request for extension of time to file a notice of appeal, application or petition",
    "U": "Review of State Bar Standing Committee on the Unauthorized Practice of Law advisory opinions",
    "W": "Matters in cases in which an execution has been scheduled",
    "X": "Cross-appeal",
    "Y": "Attorney discipline case originating with the State Bar of Georgia",
    "Z": "Appeal originating with the JQC or the Office of Bar Admissions",
}


class GaScAttorney(ScrapedData):
    """One row of the case's ``attorneys`` array.

    The portal mixes attorneys and self-represented parties in this list;
    ``party_type`` tags which side ("Appellant", "Appellee", etc.). For
    pro-se appellants the ``firm`` slot is sometimes used to carry a GDC
    inmate id rather than a firm name.
    """

    first_name: str | None = None
    middle_name: str | None = None
    last_name: str | None = None
    suffix: str | None = None
    title: str | None = None
    firm: str | None = None
    street_address_1: str | None = None
    street_address_2: str | None = None
    city: str | None = None
    state: str | None = None
    zip: str | None = None
    phone: str | None = None
    party_type: str | None = None
    """Side of the case: 'Appellant', 'Appellee', 'Real Party in Interest', etc."""


class GaScDocketEntry(ScrapedData):
    """A single ``filingsAndOrders`` row.

    The portal uses one row to represent both filings and the orders that
    dispose of them — when an order has been entered against a filing, the
    same row carries ``order_type`` and ``order_date`` in addition to the
    filing fields.
    """

    filing_type: str
    """e.g. 'APPELLANT - Brief of Appellant', 'CERTIORARI - Petition for Writ of Certiorari'."""

    date_filed: date | None = None
    time_filed: str | None = None
    """Time portion of ``filingDateTime`` ('HH:MM:SS') when present."""

    order_type: str | None = None
    """Disposition text when the row also represents an order, else None."""

    order_date: date | None = None

    docketed_in_error: bool = False
    """True when the clerk has flagged the row as docketed in error."""


class GaScJudgment(ScrapedData):
    """One row of the ``judgments`` array."""

    judgment: str
    """Disposition, e.g. 'Affirmed', 'Certiorari - Writ denied'."""

    judgment_line: str | None = None
    """Per-curiam line, e.g. 'All the Justices concur.'"""

    judgment_date: date | None = None


class GaScDocket(ScrapedData):
    """A complete Supreme Court of Georgia docket."""

    # === Searchable fields ===
    docket_number: str
    """Public case number (e.g. 'S26A0125')."""

    court_id: str = "ga"

    date_filed: date | None = None
    """``docketDate`` from the API."""

    case_name: str
    """``caseStyle`` from the API."""

    # === Case metadata ===
    case_type: str | None = None
    """One-letter code; see ``CASE_TYPE_DESCRIPTIONS`` for the meaning."""

    case_type_description: str | None = None
    """Resolved long-form description of ``case_type`` when known."""

    case_status: str | None = None
    """e.g. 'Docketed', 'Remittitur', 'Judgment'."""

    description: str | None = None
    """Short description supplied by the API, e.g. 'Criminal - Certiorari'."""

    docket_calendar: str | None = None
    """Calendar period, e.g. 'December 2025'."""

    calendar_case: bool | None = None
    """Whether the case has been calendared for oral argument."""

    county: str | None = None
    """County of origin."""

    lower_court_case_numbers: str | None = None
    """Free-form trial-court docket id(s); may include multiple values."""

    # === Nested data ===
    entries: list[GaScDocketEntry] = []
    judgments: list[GaScJudgment] = []
    attorneys: list[GaScAttorney] = []

    source_url: str | None = None
    """The case-detail API URL used to build this record."""
