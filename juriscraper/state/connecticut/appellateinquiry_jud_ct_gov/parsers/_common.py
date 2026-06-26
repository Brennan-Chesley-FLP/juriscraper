"""Shared helpers for the Connecticut appellate-inquiry page parsers."""

from __future__ import annotations

import re
from datetime import date

from jkent.common.page_element import PageElement
from jkent.data_types import XPath

# m/d/yyyy or mm/dd/yyyy anywhere in the text.
_DATE_RE = re.compile(r"(\d{1,2})/(\d{1,2})/(\d{4})")
# "Juris: 430485" -> 430485
_JURIS_RE = re.compile(r"(\d{4,})")


def parse_date(text: str | None) -> date | None:
    """Parse the first ``m/d/yyyy`` date in ``text``; None if none/invalid."""
    if not text:
        return None
    m = _DATE_RE.search(text)
    if not m:
        return None
    try:
        return date(int(m.group(3)), int(m.group(1)), int(m.group(2)))
    except ValueError:
        return None


def clean_text(text: str | None) -> str | None:
    """Collapse whitespace; return None for empty (incl. ``&nbsp;``)."""
    if text is None:
        return None
    text = " ".join(text.split()).strip()
    return text or None


def cell_date(cells: list[PageElement], idx: int) -> date | None:
    """``parse_date`` of the ``idx``-th table cell, or None if absent."""
    if len(cells) <= idx:
        return None
    return parse_date(cells[idx].text_content())


def span_text(page: PageElement, span_id: str) -> str | None:
    """Return cleaned text of the ``<span id=...>`` (exact id), or None.

    ``min_count=0`` because most appellate detail fields are optional.
    """
    elems = page.query(
        XPath(f"//span[@id='{span_id}']"), f"{span_id} span", min_count=0
    )
    return clean_text(elems[0].text_content()) if elems else None


def span_text_contains(page: PageElement, id_fragment: str) -> str | None:
    """Return cleaned text of the first ``<span>`` whose id contains the
    fragment (for civilinquiry's ``ctl00_...`` prefixed ids)."""
    elems = page.query(
        XPath(f"//span[contains(@id, '{id_fragment}')]"),
        f"span id~={id_fragment}",
        min_count=0,
    )
    return clean_text(elems[0].text_content()) if elems else None


def span_date(page: PageElement, span_id: str) -> date | None:
    """``parse_date`` of an exact-id span's text."""
    return parse_date(span_text(page, span_id))


def strip_label(text: str | None) -> str | None:
    """Drop a leading ``Label:`` prefix (civilinquiry renders ``File Date:
    09/19/2022`` in a single span)."""
    if text is None:
        return None
    return (
        clean_text(text.split(":", 1)[-1]) if ":" in text else clean_text(text)
    )


def juris_number(text: str | None) -> str | None:
    """Extract the digits from a ``Juris: 430485`` string."""
    if not text:
        return None
    m = _JURIS_RE.search(text)
    return m.group(1) if m else None
