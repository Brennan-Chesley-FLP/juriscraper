"""Shared helpers for the Iowa Appellate Courts page parsers."""

from __future__ import annotations

import re
from datetime import date, datetime


def parse_date(value: str | None) -> date | None:
    """Parse a ``MM/DD/YYYY`` date string; ``None`` when missing/unparseable."""
    if not value:
        return None
    s = value.strip()
    if not s:
        return None
    try:
        return datetime.strptime(s, "%m/%d/%Y").date()
    except ValueError:
        return None


def clean_text(text: str | None) -> str:
    """Collapse whitespace and trim non-breaking spaces."""
    if not text:
        return ""
    return re.sub(r"\s+", " ", text.replace("\xa0", " ")).strip()
