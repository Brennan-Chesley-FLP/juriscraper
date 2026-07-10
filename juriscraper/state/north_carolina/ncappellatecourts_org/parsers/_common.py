"""Shared helpers for the North Carolina Appellate Courts page parsers."""

from __future__ import annotations

import re
from datetime import date, datetime

# ─── Regexes for parsing surface strings ──────────────────────────────
_DATE_MDY_RE = re.compile(r"\b(\d{2})-(\d{2})-(\d{4})\b")  # 04-02-2026
_DATE_SLASH_RE = re.compile(r"\b(\d{2})/(\d{2})/(\d{4})\b")  # 05/04/2026
_BR_RE = re.compile(r"<\s*br\s*/?\s*>", re.IGNORECASE)
_WS_RE = re.compile(r"\s+")

# Pull ``court=1|2`` from a docket-sheet URL.
_COURT_PARAM_RE = re.compile(r"[?&]court=(\d+)")
# Pull ``iStart=N`` from a pagination URL.
_ISTART_RE = re.compile(r"[?&]iStart=(\d+)")
# Pull the document id from a ``show-file.php`` URL.
_DOC_ID_RE = re.compile(r"document_id=(\d+)")
# Pull the 1-based volume from a multi-volume ``show-file.php`` URL.
_VOLUME_NUM_RE = re.compile(r"volume_number=(\d+)")


def clean(value: str | None) -> str | None:
    """Collapse whitespace and trim. Returns ``None`` for empty results."""
    if value is None:
        return None
    text = _WS_RE.sub(" ", value).strip()
    return text or None


def parse_date(value: str | None) -> date | None:
    """Parse the docket sheet's ``MM-DD-YYYY`` and ``MM/DD/YYYY`` dates."""
    if not value:
        return None
    match = _DATE_MDY_RE.search(value)
    fmt = "%m-%d-%Y"
    if not match:
        match = _DATE_SLASH_RE.search(value)
        fmt = "%m/%d/%Y"
    if not match:
        return None
    try:
        return datetime.strptime(match.group(0), fmt).date()
    except ValueError:
        return None


def parse_yes_no(value: str | None) -> bool | None:
    """Parse the docket sheet's ``Yes`` / ``No`` flags."""
    if value is None:
        return None
    text = value.strip().lower()
    if not text:
        return None
    if text.startswith("y"):
        return True
    if text.startswith("n"):
        return False
    return None


def normalize_url(url: str) -> str:
    """The site sometimes emits ``http://`` for cross-host links."""
    if url.startswith("http://appellate.nccourts.org"):
        return "https://" + url[len("http://") :]
    return url


def court_from_sheet_url(url: str, court_sc: str, court_coa: str) -> str:
    """Pull ``court=1|2`` from a docket-sheet URL → CL court id."""
    match = _COURT_PARAM_RE.search(url)
    if match and match.group(1) == "1":
        return court_sc
    return court_coa


def current_istart(url: str | None) -> int:
    """Return the ``iStart`` offset on a search-results URL (0 if none)."""
    if not url:
        return 0
    match = _ISTART_RE.search(url)
    return int(match.group(1)) if match else 0


def strip_tags(html: str) -> str:
    """Strip the small set of inline tags the docket sheet uses."""
    text = re.sub(r"<[^>]+>", "", html)
    text = text.replace("&nbsp;", " ").replace("&#160;", " ")
    text = text.replace("&amp;", "&")
    text = text.replace("&lt;", "<").replace("&gt;", ">")
    return text
