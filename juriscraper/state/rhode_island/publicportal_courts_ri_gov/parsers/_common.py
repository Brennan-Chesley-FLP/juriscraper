"""Shared helpers for the Rhode Island Public Portal page parsers."""

from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from jkent.common.page_element import PageElement


def safe_text(element: PageElement) -> str:
    """Return an element's stripped text, or ``""`` if extraction fails."""
    try:
        return (element.text_content() or "").strip()
    except Exception:
        return ""


def clean(raw: str | None) -> str | None:
    """Strip and drop NBSPs; return ``None`` for empty results."""
    if raw is None:
        return None
    text = raw.replace("\xa0", " ").strip()
    return text or None


def parse_date(raw: str | None) -> date | None:
    """Parse an ``mm/dd/yyyy`` (or ISO / 2-digit-year) date token.

    Returns ``None`` for missing/empty/unparseable input.
    """
    if not raw:
        return None
    text = raw.replace("\xa0", " ").strip()
    if not text:
        return None
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%m/%d/%y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def find_date_in_texts(cell_texts: list[str]) -> date | None:
    """Return the first ``mm/dd/yyyy`` value found in any cell text."""
    for text in cell_texts:
        for token in text.split():
            parsed = parse_date(token)
            if parsed is not None:
                return parsed
    return None


def pick_cell(cell_texts: list[str], *, contains_any: list[str]) -> str | None:
    """Return the first cell whose text contains any of the markers."""
    for text in cell_texts:
        if any(marker.lower() in text.lower() for marker in contains_any):
            return text
    return None
