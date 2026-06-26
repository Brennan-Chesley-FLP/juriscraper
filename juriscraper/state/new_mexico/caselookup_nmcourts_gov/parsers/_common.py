"""Shared helpers for the New Mexico Case Lookup page parsers."""

from __future__ import annotations

import re
from datetime import date, datetime

_DATE_RE = re.compile(r"\b(\d{1,2}/\d{1,2}/\d{4})\b")


def clean(text: str | None) -> str:
    """Collapse whitespace and trim, returning ``""`` for empty input."""
    if not text:
        return ""
    return re.sub(r"\s+", " ", text).strip()


def parse_us_date(value: str | None) -> date | None:
    """Parse ``MM/DD/YYYY`` from a (possibly noisy) cell value.

    Returns ``None`` for missing/empty/unparseable input.
    """
    if not value:
        return None
    match = _DATE_RE.search(value)
    if not match:
        return None
    try:
        return datetime.strptime(match.group(1), "%m/%d/%Y").date()
    except ValueError:
        return None


def xpath_string(value: str) -> str:
    """Produce an XPath 1.0 string literal that survives embedded quotes.

    XPath 1.0 has no escape sequence inside string literals. If the text
    contains both kinds of quotes, fall back to ``concat()``; otherwise wrap
    in the safer quote.
    """
    if "'" not in value:
        return f"'{value}'"
    if '"' not in value:
        return f'"{value}"'
    parts = value.split("'")
    joined = ', "\'", '.join(f"'{p}'" for p in parts)
    return f"concat({joined})"
