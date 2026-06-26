"""Shared helpers for the Oklahoma OSCN page parsers."""

from __future__ import annotations

import json
import re
from datetime import date, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from jkent.common.page_element import PageElement


def parse_date(text: str | None) -> date | None:
    """Parse OSCN date strings (``MM/DD/YYYY`` or ``MM-DD-YYYY`` / ISO).

    Returns ``None`` for missing/empty/``-``/unparseable input.
    """
    if not text:
        return None
    text = text.strip()
    if not text or text == "-":
        return None
    for fmt in ("%m/%d/%Y", "%m-%d-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def normalize_ws(text: str | None) -> str:
    """Collapse runs of whitespace and trim."""
    if not text:
        return ""
    return re.sub(r"\s+", " ", text).strip()


def or_none(value: str) -> str | None:
    """Return ``value`` unless it is empty or the OSCN ``-`` placeholder."""
    return value if value and value != "-" else None


def extract_json_style(text: str) -> dict:
    """Parse the embedded ``json_style`` JSON block.

    Accepts either the bare JSON body (e.g. the ``text_content()`` of the
    ``<script id="json_style">`` node) or a larger blob still containing
    the ``<script id="json_style">...</script>`` wrapper. Returns an empty
    dict when the block is missing or unparseable. The block exposes the
    canonical case number (which can differ from the URL ``number=``
    parameter for prefixed case types), ``cmid``, and the ``court`` token
    used to build the Track-Case URL.
    """
    if not text:
        return {}
    candidate = text.strip()
    m = re.search(
        r'<script[^>]*id="json_style"[^>]*>(.*?)</script>',
        candidate,
        re.DOTALL,
    )
    if m:
        candidate = m.group(1).strip()
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        return {}


def row_color(row_html: str) -> str | None:
    """Return the dominant ``<font color="...">`` value in a docket row.

    OSCN repeats the colour across every cell in a row, so the first match
    is typically representative. Returns the hex string (uppercased)
    without the leading ``#``.
    """
    m = re.search(r'<font[^>]*color="([0-9A-Fa-f]{6})"', row_html)
    return m.group(1).upper() if m else None


def cell_lines(cell: PageElement) -> list[str]:
    """Return the cell's text broken on ``<br>`` boundaries.

    OSCN cells separate attorney address segments with ``<br>`` tags,
    which collapse to nothing inside ``text_content()``. We work off the
    cell's inner HTML (via the public ``PageElement.inner_html()`` API,
    which includes the cell's leading text node), split on ``<br>``, strip
    remaining markup, and unescape ``&nbsp;``.
    """
    full = cell.inner_html() or ""
    if not full:
        return []
    chunks = re.split(r"(?i)<br\s*/?>", full)
    out: list[str] = []
    for chunk in chunks:
        stripped = re.sub(r"<[^>]+>", "", chunk)
        stripped = stripped.replace("\xa0", " ").replace("&nbsp;", " ")
        stripped = re.sub(r"\s+", " ", stripped).strip()
        if stripped:
            out.append(stripped)
    return out
