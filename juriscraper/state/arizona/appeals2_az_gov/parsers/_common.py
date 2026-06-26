"""Shared helpers for the Arizona CoA Division Two page parsers."""

from __future__ import annotations

import re
from datetime import date, datetime
from html import unescape
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from jkent.common.page_element import PageElement


def safe_text(element: PageElement) -> str:
    """Return an element's stripped text, or ``""`` if extraction fails."""
    try:
        return element.text_content().strip()
    except Exception:
        return ""


def parse_date(raw: str | None) -> date | None:
    """Parse an ``mm/dd/yyyy`` (or ISO / 2-digit-year) date.

    Returns ``None`` for missing/empty/unparseable input.
    """
    if not raw:
        return None
    text = raw.strip().replace("\xa0", " ").strip()
    if not text:
        return None
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%m/%d/%y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def clean(raw: str | None) -> str | None:
    """Strip, collapse trailing whitespace, drop NBSPs.

    Returns ``None`` for empty results.
    """
    if raw is None:
        return None
    text = raw.replace("\xa0", " ").strip()
    text = re.sub(r"[ \t]+\n", "\n", text)
    if not text:
        return None
    return text


def html_blocks(cell: PageElement) -> list[list[str]]:
    """Convert a cell's inner HTML to a list of blocks; each block is a
    list of non-empty trimmed lines.

    ``<br>`` becomes a line break, ``<p></p>`` becomes a block boundary.
    Empty blocks (and blocks containing only whitespace) are dropped.
    HTML entities are unescaped.

    Works off the cell's markup (via the ``PageElement.inner_html()``
    public API) because ``text_content()`` collapses the ``<br>``/``<p>``
    markers that carry the line/block structure. ``inner_html()`` includes
    the cell's leading text node (the first party name in this site's
    layout), so no manual lxml assembly is needed.
    """
    markup = cell.inner_html()
    # Normalise <br> variants to a line break.
    markup = re.sub(r"(?i)<br\s*/?>", "\n", markup)
    # <p></p> (empty paragraph) is the block separator.
    block_sentinel = "\x00BLOCK\x00"
    markup = re.sub(r"(?i)<p\s*[^/>]*>\s*</p\s*>", block_sentinel, markup)
    # Strip any remaining tags.
    markup = re.sub(r"<[^>]+>", "", markup)
    markup = unescape(markup)
    blocks: list[list[str]] = []
    for raw_block in markup.split(block_sentinel):
        lines = [
            re.sub(r"\s+", " ", ln).strip() for ln in raw_block.splitlines()
        ]
        lines = [ln for ln in lines if ln]
        if lines:
            blocks.append(lines)
    return blocks
