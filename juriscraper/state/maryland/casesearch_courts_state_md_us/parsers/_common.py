"""Shared helpers for the Maryland Case Search JSON parsers."""

from __future__ import annotations

from datetime import date, datetime


def parse_us_date(value: str | None) -> date | None:
    """Parse an ``MM/DD/YYYY`` date string.

    Returns ``None`` for missing/empty/unparseable input.
    """
    if not value:
        return None
    text = value.strip()
    if not text:
        return None
    try:
        return datetime.strptime(text, "%m/%d/%Y").date()
    except ValueError:
        return None


def clean(value: str | None) -> str | None:
    """Strip surrounding whitespace; return ``None`` for empty results."""
    if value is None:
        return None
    text = value.strip()
    return text or None
