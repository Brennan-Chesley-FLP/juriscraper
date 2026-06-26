"""Shared helpers for the Massachusetts Appellate Courts page parsers."""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import TYPE_CHECKING

from jkent.data_types import XPath

if TYPE_CHECKING:
    from jkent.common.page_element import PageElement


# ─── Regexes for parsing surface strings ─────────────────────────────
DATE_RE = re.compile(r"\b(\d{1,2}/\d{1,2}/\d{4})\b")
ATTORNEY_ID_RE = re.compile(r"/attorney/(\d+)")
SESSION_DATE_RE = re.compile(
    r"(?P<wd>\w+),\s+(?P<mon>\w+)\s+(?P<day>\d+)(?:st|nd|rd|th)?\s+"
    r"(?P<year>\d{4}),\s+(?P<time>\d{1,2}:\d{2}\s*[AP]M)",
    re.IGNORECASE,
)


def first(page: PageElement, xpath: str) -> str | None:
    """Return the first stripped string for ``xpath``, or ``None``."""
    values = page.query_strings(XPath(xpath), xpath, min_count=0, max_count=1)
    if not values:
        return None
    text = values[0].strip()
    return text or None


def clean(value: str | None) -> str | None:
    """Collapse whitespace; return ``None`` for empty results."""
    if value is None:
        return None
    text = " ".join(value.split())
    return text or None


def parse_date(value: str | None) -> date | None:
    """Parse the ``MM/DD/YYYY`` dates the site uses."""
    if not value:
        return None
    match = DATE_RE.search(value)
    if not match:
        return None
    try:
        return datetime.strptime(match.group(1), "%m/%d/%Y").date()
    except ValueError:
        return None


def parse_session_when(text: str) -> tuple[date | None, str | None]:
    """Parse a calendar heading like ``Monday, May 4th 2026, 9:00 AM``."""
    if not text:
        return None, None
    match = SESSION_DATE_RE.search(text)
    if not match:
        return None, None
    raw_date = (
        f"{match.group('mon')} {match.group('day')} {match.group('year')}"
    )
    try:
        parsed = datetime.strptime(raw_date, "%B %d %Y").date()
    except ValueError:
        parsed = None
    time_part = match.group("time").upper().strip()
    return parsed, time_part
