"""Shared helpers for the California appellate-courts page parsers."""

from __future__ import annotations

import re
from datetime import date


def parse_date(text: str | None) -> date | None:
    """Parse an mm/dd/yyyy date string, returning None for empty/invalid."""
    if text is None:
        return None
    text = text.strip()
    if not text:
        return None
    m = re.match(r"(\d{2})/(\d{2})/(\d{4})", text)
    if not m:
        return None
    return date(int(m.group(3)), int(m.group(1)), int(m.group(2)))


def clean_text(text: str | None) -> str | None:
    """Strip and return None for empty strings."""
    if text is None:
        return None
    text = text.strip()
    return text if text else None


def fields_from_definition_list(dts, dds) -> dict[str, str]:
    """Build a ``{term: value}`` dict from parallel dt/dd element lists.

    The site renders case metadata as a ``<dl>`` of ``<dt>`` terms and
    ``<dd>`` values; trailing colons on the term are stripped.
    """
    fields: dict[str, str] = {}
    for dt_el, dd_el in zip(dts, dds):
        key = dt_el.text_content().strip().rstrip(":")
        val = dd_el.text_content().strip()
        fields[key] = val
    return fields
