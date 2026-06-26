"""Data models for the Hawaiʻi eCourt Kōkua appellate-docket scraper.

The portal (``jimspss1.courts.state.hi.us:8080/eCourt/ECC``) renders each
case as server-side HTML (JSF 2.0 / IceFaces 4). A single
:class:`HiAppDocket` carries everything displayed on a case-detail page —
the case header, parties & attorneys, the register of actions, and any
linked documents.

Field names follow [`../../CL_MODELS.md`](../../CL_MODELS.md): the
CourtListener court-id string is ``court`` (not ``court_id``), the case
number is ``docket_number`` (not ``case_number``), and dates use the
``date_*`` prefix.

See ``CC_NOTES.md`` for the source-form discovery and the gaps that remain
unverified pending captcha-solver support.
"""

from __future__ import annotations

from datetime import date

from jkent.common.data_models import ScrapedData

from juriscraper.state.common_models import CleanString, HarmonizedCaseName

# CourtListener court-id → display name (the courts this scraper covers).
COURT_NAMES: dict[str, str] = {
    "haw": "Supreme Court of Hawaiʻi",
    "hawapp": "Hawaii Intermediate Court of Appeals",
}


# Site court code (Filing Date Search ``courtSelect``) → CourtListener id.
SITE_COURT_TO_CL: dict[str, str] = {
    "SC": "haw",
    "CA": "hawapp",
}


# Supreme Court case-type codes (the two-letter code in ``SC{TT}-``).
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


# Intermediate Court of Appeals case-type codes (the code in ``CA{TT}-``).
ICA_CASE_TYPES: dict[str, str] = {
    "AP": "Appeal",
    "OT": "Other",
    "ST": "Agreed Statement",
}


# =========================================================================
# Data models
# =========================================================================


class HiAppAttorney(ScrapedData):
    """Attorney record attached to a party on a Hawaiʻi appellate docket.

    Maps to CourtListener ``Attorney`` (+ ``AttorneyOrganization`` for the
    firm)."""

    name: CleanString
    """Attorney name as displayed on the case detail page."""

    firm: CleanString | None = None
    """Law firm or government agency, if listed."""

    role: CleanString | None = None
    """Free-form role (e.g. "Counsel for Appellant")."""

    address: CleanString | None = None
    """Single-line address as displayed (joined from any component lines)."""

    phone: CleanString | None = None
    """Phone number as displayed."""


class HiAppParty(ScrapedData):
    """A party on a Hawaiʻi appellate docket.

    Maps to CourtListener ``Party`` (+ ``PartyType`` for the role on this
    docket)."""

    name: CleanString
    """Party name as displayed."""

    role: CleanString
    """Party role / disposition label (e.g. "Appellant", "Petitioner")."""

    attorneys: list[HiAppAttorney] = []
    """Attorneys appearing for this party."""


class HiAppDocketEntry(ScrapedData):
    """One row of the register of actions / docket history.

    Maps to CourtListener ``DocketEntry``."""

    date_filed: date | None = None
    """Filing date for the entry."""

    description: CleanString
    """Entry description / docket text as displayed."""

    notes: CleanString | None = None
    """Secondary text (clerk notes, hearing-result text, etc.)."""

    document_url: str | None = None
    """Link to the entry's document, if exposed in the row (often paywalled
    via the Subscriptions portal)."""


class HiAppDocument(ScrapedData):
    """A document associated with the case (opinion, brief, order, etc.).

    The Hawaiʻi portal exposes document metadata in the public view but
    routes the actual file behind ``Subscriptions.iface`` (paywalled). We
    therefore record metadata only; ``download_url`` may be a viewer page
    rather than a direct file.

    Maps loosely to CourtListener ``RECAPDocument``."""

    download_url: str
    """URL the docket page links to for this document."""

    document_type: CleanString | None = None
    """Type label (e.g. "Opinion", "Brief", "Order")."""

    date_filed: date | None = None
    """Date the document was filed / issued."""

    description: CleanString | None = None
    """Free-form descriptive text accompanying the document link."""


class HiAppDocket(ScrapedData):
    """A complete Hawaiʻi appellate docket (Supreme Court or ICA).

    Maps to CourtListener ``Docket`` (+ its per-court side tables). The
    ``docket_number`` is the full court-prefixed case number as displayed on
    the portal (``SCAP-22-0000234``, ``CAAP-23-0000123``, etc.).
    """

    docket_number: str
    """Full case number with prefix and dashes (``SC{TT}-{YY}-{NNNNNNN}`` or
    ``CA{TT}-{YY}-{NNNNNNN}``)."""

    court: str
    """CourtListener court id — ``haw`` or ``hawapp``."""

    case_name: HarmonizedCaseName
    """Case caption / title as displayed."""

    date_filed: date | None = None
    """Date the appellate proceeding was filed in this court."""

    case_type_code: CleanString | None = None
    """Two-letter case type code embedded in the docket number (``AP``,
    ``WC``, ``PW``, ...)."""

    case_type: CleanString | None = None
    """Human-readable case type label."""

    case_status: CleanString | None = None
    """Case status text as displayed (e.g. "Open", "Closed")."""

    date_terminated: date | None = None
    """Date the case was closed / disposed, when reported."""

    panel_str: CleanString | None = None
    """Panel or division text (ICA divisions, full-court designation). CL
    ``panel_str``."""

    appeal_from_str: CleanString | None = None
    """Trial-court case number, when displayed in the case summary. Held as
    a raw string (CL ``appeal_from_str``)."""

    assigned_to_str: CleanString | None = None
    """Trial-court judge, when displayed (CL ``assigned_to_str``)."""

    entries: list[HiAppDocketEntry] = []
    """Register-of-actions rows."""

    parties: list[HiAppParty] = []
    """Parties (and their attorneys) on the case."""

    documents: list[HiAppDocument] = []
    """Documents linked from the case detail page."""

    source_url: str | None = None
    """URL of the case detail page on the portal."""

    source_entry_point: str | None = None
    """Entry point used to reach this docket."""
