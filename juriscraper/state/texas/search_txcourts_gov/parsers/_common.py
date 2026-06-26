"""Shared helpers for the Texas TAMES page parsers.

This module holds the court-routing logic (mapping a TAMES ``coa=`` code /
docket-number format to a CourtListener court id + parser), date coercion,
and the adapters that convert the legacy ``juriscraper.state.texas.*``
parser TypedDicts into the ``ScrapedData`` models. The heavy lxml
extraction itself is preserved verbatim in the legacy flat-module parsers
(``court_of_appeals`` / ``supreme_court`` / ``court_of_criminal_appeals``);
these helpers only restructure the result.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from urllib.parse import urljoin

from juriscraper.state.texas.common import COA_ORDINAL_MAP, CourtID
from juriscraper.state.texas.court_of_appeals import (
    TexasCourtOfAppealsScraper as LegacyCoaParser,
)
from juriscraper.state.texas.court_of_criminal_appeals import (
    TexasCourtOfCriminalAppealsScraper as LegacyCcaParser,
)
from juriscraper.state.texas.search_txcourts_gov.models import (
    BASE_URL,
    COA_DISTRICT_NAMES,
    COURT_OF_APPEALS_ID,
    COURT_OF_CRIMINAL_APPEALS_ID,
    SUPREME_COURT_ID,
    TexasAppealsCourtRef,
    TexasDocket,
    TexasDocketEntry,
    TexasDocument,
    TexasOriginatingCourt,
    TexasParty,
    TexasTransfer,
)
from juriscraper.state.texas.supreme_court import (
    TexasSupremeCourtScraper as LegacySupremeCourtParser,
)

# Court routing keyed off the final URL's ``coa=`` query parameter
# (``cossup`` → SC, ``coscca`` → CCA, ``coa01``..``coa15`` → COAs).
COA_PARAM_RE = re.compile(r"[?&]coa=([a-z0-9]+)", re.IGNORECASE)

# Per-court docket-number patterns. Used to route the case-detail parser to
# the right legacy parser when the final (redirected) URL is unavailable.
# Order matters: COA is checked first (its suffix is the most distinctive);
# CCA next; SC last (SC formats are short and could otherwise be greedy).
_COA_DOCKET_RE = re.compile(r"^(\d{2})-\d{2}-\d{5}-\w{2}$")
_CCA_DOCKET_RE = re.compile(
    r"^(?:WR-[\d,]+-\d{2}|AP-[\d,]+|[A-Z]{2}-\d{4}-\d{2})$",
)
_SC_LETTER_DOCKET_RE = re.compile(r"^[ABC]-\d+(?:-A)?$")
_SC_MODERN_DOCKET_RE = re.compile(r"^\d{1,2}[bB]?-\d{4}$")
_SC_WRIT_DOCKET_RE = re.compile(r"^\d{4,5}$")
# Oddly-numbered SC dockets that appear in the legacy DOCKET_NUMBER_REGEXES.
_SC_ODDBALL_DOCKETS = {"B-3872A", "D-0190", "D-2169", "D-4261"}


# =========================================================================
# Court detection / parser routing
# =========================================================================


def extract_coa_param(url: str) -> str | None:
    """Return the ``coa=`` query param value, lowercased, or ``None``.

    E.g. ``cossup`` (Supreme), ``coscca`` (CCA), ``coa07`` (7th COA). Used
    as a fallback when the docket number isn't available.
    """
    match = COA_PARAM_RE.search(url)
    return match.group(1).lower() if match else None


def court_code_from_docket(docket_number: str) -> str | None:
    """Map a Texas appellate docket number to its TAMES ``coa=`` code.

    Returns ``cossup`` / ``coscca`` / ``coa01``..``coa15``, or ``None`` if
    the docket number doesn't match any known format. Patterns derive from
    ``juriscraper.state.texas.common.DOCKET_NUMBER_REGEXES``.
    """
    if not docket_number:
        return None
    # 1st-15th Courts of Appeals — most distinctive pattern, check first.
    match = _COA_DOCKET_RE.match(docket_number)
    if match:
        ord_num = int(match.group(1))
        if 1 <= ord_num <= 15:
            return f"coa{ord_num:02d}"
    # Court of Criminal Appeals: WR-... / AP-... / PD-NNNN-NN.
    if _CCA_DOCKET_RE.match(docket_number):
        return "coscca"
    # Supreme Court — three legacy patterns plus a handful of oddballs.
    if docket_number in _SC_ODDBALL_DOCKETS:
        return "cossup"
    if _SC_LETTER_DOCKET_RE.match(docket_number):
        return "cossup"
    if _SC_MODERN_DOCKET_RE.match(docket_number):
        return "cossup"
    if _SC_WRIT_DOCKET_RE.match(docket_number):
        return "cossup"
    return None


def make_legacy_parser(court_code: str | None):
    """Pick the legacy parser instance based on the resolved ``coa=`` code."""
    if court_code == "cossup":
        return LegacySupremeCourtParser()
    if court_code == "coscca":
        return LegacyCcaParser()
    # ``coa01``..``coa15`` — or a missing / unrecognised code, in which case
    # we still try the COA parser since COA pages have the broadest field
    # surface.
    return LegacyCoaParser(court_id=CourtID.UNKNOWN.value)


def court_id_from_court_code(court_code: str | None) -> str:
    """Map a TAMES ``coa=`` code to a CourtListener court id."""
    if court_code == "cossup":
        return SUPREME_COURT_ID
    if court_code == "coscca":
        return COURT_OF_CRIMINAL_APPEALS_ID
    return COURT_OF_APPEALS_ID


def court_name_from_court_code(court_code: str | None) -> str | None:
    """Map a TAMES ``coa=`` code to a display court name."""
    if court_code == "cossup":
        return "Texas Supreme Court"
    if court_code == "coscca":
        return "Court of Criminal Appeals of Texas"
    if court_code and court_code.startswith("coa"):
        try:
            ordinal = int(court_code.removeprefix("coa"))
        except ValueError:
            return None
        return COA_DISTRICT_NAMES.get(ordinal)
    return None


def coa_district_from_docket(docket_number: str) -> int | None:
    """Return the COA ordinal (1-15) from a COA docket number, else ``None``."""
    match = _COA_DOCKET_RE.match(docket_number)
    if not match:
        return None
    ordinal = int(match.group(1))
    if 1 <= ordinal <= 15:
        return ordinal
    return None


def _other_court_district(court_name: str) -> int | None:
    """Map a COA name (e.g. ``First Court of Appeals``) to its ordinal."""
    first = court_name.split()[0].lower() if court_name else ""
    cid = COA_ORDINAL_MAP.get(first)
    if cid is None:
        return None
    # CourtID values are ``texas_coaNN`` — strip prefix to recover the number.
    suffix = cid.value.removeprefix("texas_coa")
    try:
        return int(suffix)
    except ValueError:
        return None


# =========================================================================
# Date coercion
# =========================================================================


def coerce_date(value) -> date | None:
    """Coerce a legacy date value (date / datetime / mm/dd/yyyy str) to date."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return datetime.strptime(value, "%m/%d/%Y").date()
        except ValueError:
            try:
                return date.fromisoformat(value)
            except ValueError:
                return None
    return None


# =========================================================================
# Legacy TypedDict → ScrapedData adapters
# =========================================================================


def _adapt_document(legacy_doc: dict) -> TexasDocument:
    """Adapt one legacy document TypedDict to a ``TexasDocument``."""
    url = legacy_doc.get("document_url", "")
    # The legacy parser already absolute-resolves the URL via lxml's
    # rewrite_links; fall back to manual urljoin just in case.
    if url and not url.startswith("http"):
        url = urljoin(BASE_URL, url)
    size_bytes = legacy_doc.get("file_size_bytes")
    return TexasDocument(
        download_url=url,
        media_id=legacy_doc.get("media_id") or None,
        media_version_id=legacy_doc.get("media_version_id") or None,
        description=legacy_doc.get("description") or None,
        file_size_bytes=int(size_bytes) if size_bytes else None,
        file_size_str=legacy_doc.get("file_size_str") or None,
    )


def _adapt_originating_court(
    legacy_oc: dict | None,
) -> TexasOriginatingCourt | None:
    """Adapt the legacy originating-court TypedDict to ``ScrapedData``."""
    if not legacy_oc:
        return None
    return TexasOriginatingCourt(
        name=legacy_oc.get("name", ""),
        court_type=legacy_oc.get("court_type", ""),
        county=legacy_oc.get("county") or None,
        assigned_to_str=legacy_oc.get("judge") or None,
        docket_number=legacy_oc.get("case") or None,
        reporter=legacy_oc.get("reporter") or None,
        punishment=legacy_oc.get("punishment") or None,
        district=legacy_oc.get("district"),
        court=legacy_oc.get("court_id"),
    )


def _adapt_transfer(legacy_transfer: dict | None) -> TexasTransfer | None:
    """Adapt the legacy transfer TypedDict to ``ScrapedData``."""
    if not legacy_transfer:
        return None
    # The legacy TypedDict stores ``court_id`` (e.g. "texas_coa07"), not a
    # display name; rebuild the display name from our ordinal map.
    other_court_id = legacy_transfer.get("court_id") or ""
    suffix = other_court_id.removeprefix("texas_coa")
    try:
        other_district = int(suffix)
    except ValueError:
        other_district = None
    other_name = (
        COA_DISTRICT_NAMES.get(other_district, other_court_id)
        if other_district is not None
        else other_court_id
    )
    return TexasTransfer(
        other_court_name=other_name,
        other_coa_district=other_district,
        transfer_date=coerce_date(legacy_transfer.get("date")),
        origin_docket_number=legacy_transfer.get("origin_docket") or None,
    )


def _adapt_appeals_court_ref(
    legacy_ac: dict | None,
) -> TexasAppealsCourtRef | None:
    """Adapt the SC / CCA ``appeals_court`` TypedDict to ``ScrapedData``.

    Maps the legacy ``texas_coaNN`` court id to CourtListener's ``texapp``
    and parses the COA district from the printed label. The legacy
    ``case_number`` / ``case_url`` fields are lists (one COA case may be
    referenced more than once); the first entry is used.
    """
    if not legacy_ac:
        return None
    district_label = legacy_ac.get("district") or ""
    coa_district = (
        _other_court_district(district_label) if district_label else None
    )
    legacy_court_id = legacy_ac.get("court_id") or ""
    if legacy_court_id.startswith("texas_coa"):
        cl_court_id = COURT_OF_APPEALS_ID
    elif not legacy_court_id or legacy_court_id == CourtID.UNKNOWN.value:
        cl_court_id = None
    else:
        cl_court_id = legacy_court_id

    def _first(value):
        if isinstance(value, (list | tuple)):
            return value[0] if value else None
        return value or None

    return TexasAppealsCourtRef(
        docket_number=_first(legacy_ac.get("case_number")),
        case_url=_first(legacy_ac.get("case_url")),
        disposition=legacy_ac.get("disposition") or None,
        opinion_cite=legacy_ac.get("opinion_cite") or None,
        district=district_label or None,
        court=cl_court_id,
        coa_district=coa_district,
        justice=legacy_ac.get("justice") or None,
    )


def adapt_legacy_docket(legacy: dict, court_code: str | None):
    """Convert a legacy parser's TypedDict to a ``TexasDocket`` deferred value.

    Handles output from any of the three parsers (COA, SC, CCA) by falling
    back to ``.get()`` on per-court keys (``publication_service``,
    ``transfer_from``, ``transfer_to`` for COAs; ``appeals_court`` for
    SC / CCA; ``remarks`` on SC events / briefs). The provenance fields
    (``source_url`` / ``source_entry_point``) are stamped by the calling
    step, since they aren't present on the page.
    """
    docket_number = legacy["docket_number"]
    court_id = court_id_from_court_code(court_code)
    coa_district = (
        coa_district_from_docket(docket_number)
        if court_id == COURT_OF_APPEALS_ID
        else None
    )
    court_name = court_name_from_court_code(court_code) or (
        COA_DISTRICT_NAMES.get(coa_district)
        if coa_district is not None
        else None
    )

    # TAMES sorts each table newest-first. Number bottom-to-top within each
    # kind so the oldest row in each table is entry_number=1.
    legacy_events = list(legacy.get("case_events") or [])
    legacy_briefs = list(legacy.get("appellate_briefs") or [])

    entries: list[TexasDocketEntry] = []
    documents: list[TexasDocument] = []

    for i, ev in enumerate(legacy_events):
        entry_documents = [
            _adapt_document(d) for d in (ev.get("attachments") or [])
        ]
        entries.append(
            TexasDocketEntry(
                kind="event",
                entry_number=len(legacy_events) - i,
                date_filed=coerce_date(ev.get("date")),
                event_type=ev.get("type", ""),
                disposition=ev.get("disposition") or None,
                remarks=ev.get("remarks") or None,
                documents=entry_documents,
            )
        )
        documents.extend(entry_documents)

    for i, brief in enumerate(legacy_briefs):
        brief_documents = [
            _adapt_document(d) for d in (brief.get("attachments") or [])
        ]
        entries.append(
            TexasDocketEntry(
                kind="brief",
                entry_number=len(legacy_briefs) - i,
                date_filed=coerce_date(brief.get("date")),
                event_type=brief.get("type", ""),
                description=brief.get("description") or None,
                remarks=brief.get("remarks") or None,
                documents=brief_documents,
            )
        )
        documents.extend(brief_documents)

    parties = [
        TexasParty(
            name=p.get("name", ""),
            role=p.get("type", ""),
            representatives=list(p.get("representatives") or []),
        )
        for p in (legacy.get("parties") or [])
    ]

    return TexasDocket.raw(
        docket_number=docket_number,
        court=court_id,
        coa_district=coa_district,
        court_name=court_name,
        case_name=legacy.get("case_name", ""),
        case_name_full=legacy.get("case_name_full", ""),
        case_type=legacy.get("case_type") or None,
        date_filed=coerce_date(legacy.get("date_filed")),
        parties=parties,
        originating_court=_adapt_originating_court(
            legacy.get("originating_court")
        ),
        entries=entries,
        documents=documents,
        publication_service=legacy.get("publication_service") or None,
        transfer_from=_adapt_transfer(legacy.get("transfer_from")),
        transfer_to=_adapt_transfer(legacy.get("transfer_to")),
        appeals_court_ref=_adapt_appeals_court_ref(
            legacy.get("appeals_court")
        ),
    )
