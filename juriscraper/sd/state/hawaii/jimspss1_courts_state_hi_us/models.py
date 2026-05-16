"""Hawaii eCourt Kōkua appellate-docket models.

See ``DESIGN.md`` for the source-form discovery and the gaps that remain
unverified pending captcha-solver support.
"""

from __future__ import annotations

from datetime import date

from jkent.common.data_models import ScrapedData

COURT_IDS: dict[str, str] = {
    "haw": "Supreme Court of Hawaiʻi",
    "hawapp": "Hawaii Intermediate Court of Appeals",
}


SITE_COURT_TO_CL: dict[str, str] = {
    "SC": "haw",
    "CA": "hawapp",
}


SC_CASE_TYPES: dict[str, str] = {
    "AD": "Attorney Discipline",
    "AP": "Appeal",
    "CQ": "Certified Question",
    "EC": "Election Contest",
    "FD": "Judicial Financial Disclosure",
    "MF": "Miscellaneous Filings",
    "OT": "Other",
    "PR": "Petition to Resign / Surrender Law License",
    "PW": "Petition for Writ",
    "RQ": "Reserved Question",
    "RU": "Rule",
    "WC": "Application for Writ of Certiorari",
}


ICA_CASE_TYPES: dict[str, str] = {
    "AP": "Appeal",
    "OT": "Other",
    "ST": "Agreed Statement",
}


class HiAppAttorney(ScrapedData):
    """Attorney record attached to a party on a Hawaiʻi appellate docket."""

    name: str
    """Attorney name as displayed on the case detail page."""

    firm: str | None = None
    """Law firm or government agency, if listed."""

    role: str | None = None
    """Free-form role (e.g. "Counsel for Appellant")."""

    address: str | None = None
    """Single-line address as displayed (joined from any component lines)."""

    phone: str | None = None
    """Phone number as displayed."""


class HiAppParty(ScrapedData):
    """A party on a Hawaiʻi appellate docket."""

    name: str
    """Party name as displayed."""

    role: str
    """Party role / disposition label (e.g. "Appellant", "Petitioner")."""

    attorneys: list[HiAppAttorney] = []
    """Attorneys appearing for this party."""


class HiAppDocketEntry(ScrapedData):
    """One row of the register of actions / docket history."""

    date_filed: date | None = None
    """Filing date for the entry."""

    description: str
    """Entry description / docket text as displayed."""

    notes: str | None = None
    """Secondary text (clerk notes, hearing-result text, etc.)."""

    document_url: str | None = None
    """Link to the entry's document, if exposed in the row (often paywalled
    via the Subscriptions portal)."""


class HiAppDocument(ScrapedData):
    """A document associated with the case (opinion, brief, order, etc.).

    The Hawaiʻi portal exposes document metadata in the public view but
    routes the actual file behind ``Subscriptions.iface`` (paywalled). We
    therefore record metadata only; ``download_url`` may be a viewer page
    rather than a direct file."""

    download_url: str
    """URL the docket page links to for this document."""

    document_type: str | None = None
    """Type label (e.g. "Opinion", "Brief", "Order")."""

    date_filed: date | None = None
    """Date the document was filed / issued."""

    description: str | None = None
    """Free-form descriptive text accompanying the document link."""


class HiAppDocket(ScrapedData):
    """A complete Hawaiʻi appellate docket (Supreme Court or ICA).

    The ``docket_id`` is the full court-prefixed case number as displayed
    on the portal (``SCAP-22-0000234``, ``CAAP-23-0000123``, etc.).
    """

    docket_id: str
    """Full case number with prefix and dashes (``SC{TT}-{YY}-{NNNNNNN}`` or
    ``CA{TT}-{YY}-{NNNNNNN}``)."""

    court_id: str
    """CourtListener court id — ``haw`` or ``hawapp``."""

    case_name: str
    """Case caption / title as displayed."""

    date_filed: date | None = None
    """Date the appellate proceeding was filed in this court."""

    case_type_code: str | None = None
    """Two-letter case type code embedded in the docket id (``AP``, ``WC``,
    ``PW``, ...)."""

    case_type: str | None = None
    """Human-readable case type label."""

    case_status: str | None = None
    """Case status text as displayed (e.g. "Open", "Closed")."""

    date_terminated: date | None = None
    """Date the case was closed / disposed, when reported."""

    panel: str | None = None
    """Panel or division text (ICA divisions, full-court designation)."""

    lower_court_case_number: str | None = None
    """Trial-court case number, when displayed in the case summary."""

    lower_court_judge: str | None = None
    """Trial-court judge, when displayed."""

    entries: list[HiAppDocketEntry] = []
    """Register-of-actions rows."""

    parties: list[HiAppParty] = []
    """Parties (and their attorneys) on the case."""

    documents: list[HiAppDocument] = []
    """Documents linked from the case detail page."""

    source_url: str | None = None
    """URL of the case detail page on the portal."""
