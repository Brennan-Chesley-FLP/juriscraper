"""Shared helpers for the Mississippi appellate-courts page parsers."""

from __future__ import annotations

import re
from datetime import date

from juriscraper.state.mississippi.courts_ms_gov.models import (
    DEFAULT_COURT,
    SUFFIX_TO_COURT,
)

# Public docket-number patterns. Modern: 4-digit year + suffix; legacy:
# 2-digit year, no suffix.
DOCKET_RE_MODERN = re.compile(
    r"\b(\d{4})-([A-Z]{1,3})-(\d{4,5})-([A-Z]{2,3})\b"
)
DOCKET_RE_LEGACY = re.compile(r"\b(\d{2})-([A-Z]{1,3})-(\d{4,5})\b")
RULING_DATE_RE = re.compile(r"Ruling Date:\s*(\d{1,2}/\d{1,2}/\d{2,4})", re.I)
TRIAL_CASE_RE = re.compile(r"Trial Court Case #\s*(.+?)\s*$")


def strip(value: str | None) -> str:
    """Collapse whitespace + non-breaking spaces in extracted text."""
    if not value:
        return ""
    return re.sub(r"\s+", " ", value.replace("\xa0", " ")).strip()


def parse_date(value: str | None) -> date | None:
    """Parse a ``M/D/YYYY`` (or ``M/D/YY``) string."""
    if not value:
        return None
    try:
        m, d, y = value.strip().split("/")
        year = int(y)
        if year < 100:
            # Two-digit years on legacy records: 70-99 → 19xx, else 20xx.
            year += 1900 if year >= 70 else 2000
        return date(year, int(m), int(d))
    except (ValueError, AttributeError):
        return None


def parse_desc_index(value: str) -> int | None:
    """Pull the integer N out of ``desc-N`` or ``dockpdf-N``."""
    m = re.search(r"-(\d+)\b", value or "")
    return int(m.group(1)) if m else None


def extract_file_param(href: str) -> str:
    """Extract the ``f=…`` parameter from a sendPDF.php URL."""
    m = re.search(r"[?&]f=([^&#]+)", href or "")
    return m.group(1) if m else ""


def court_from_docket_number(docket_number: str) -> str:
    """Return the CourtListener court id implied by the docket suffix.

    Falls back to ``DEFAULT_COURT`` for legacy (pre-1997) docket numbers
    that have no court suffix.
    """
    m = DOCKET_RE_MODERN.search(docket_number or "")
    if m:
        return SUFFIX_TO_COURT.get(m.group(4), DEFAULT_COURT)
    return DEFAULT_COURT
