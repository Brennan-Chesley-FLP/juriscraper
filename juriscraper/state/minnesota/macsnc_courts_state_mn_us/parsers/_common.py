"""Shared helpers for the Minnesota P-MACS page parsers."""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import TYPE_CHECKING

from jkent.data_types import XPath

if TYPE_CHECKING:
    from jkent.common.page_element import PageElement


# Separator we use to join multi-select option text into the entry
# ``details`` dict-of-strings. Each individual option may contain ``;``
# or ``,`` (e.g. ``"Williams, Dale Allen, Sr.; Appellant: o/b/o Pro Se"``)
# so a generic separator like ``";"`` would split it. ``" || "`` is
# unlikely to appear in any displayed option text.
MULTI_VALUE_SEP = " || "


def parse_date(text: str | None) -> date | None:
    """Parse P-MACS date strings (``MM/DD/YYYY`` or ISO)."""
    if not text:
        return None
    text = text.strip()
    for fmt in ("%m/%d/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def normalize_ws(text: str | None) -> str:
    """Collapse contiguous whitespace to a single space and trim."""
    if not text:
        return ""
    return re.sub(r"\s+", " ", text).strip()


def split_br_lines(inner_html: str) -> list[str]:
    """Split a cell's inner HTML on ``<br>`` and return cleaned lines.

    Columns like Attorney(s) separate names with ``<br>`` tags which
    ``text_content()`` collapses; we recover them by stripping markup
    off each ``<br>``-delimited chunk.
    """
    if not inner_html:
        return []
    chunks = re.split(r"(?i)<br\s*/?>", inner_html)
    out: list[str] = []
    for chunk in chunks:
        stripped = re.sub(r"<[^>]+>", "", chunk)
        stripped = stripped.replace("\xa0", " ").replace("&nbsp;", " ")
        stripped = re.sub(r"\s+", " ", stripped).strip()
        if stripped:
            out.append(stripped)
    return out


def cell_lines(cell: PageElement) -> list[str]:
    """``<br>``-aware text extraction for a table cell.

    Uses ``inner_html()`` (public API) — it includes the cell's leading
    text node, so no private lxml access is needed. ``text_content()``
    would collapse the ``<br>`` markers that delimit the lines.
    """
    try:
        inner = cell.inner_html() or ""
    except (AttributeError, Exception):  # noqa: BLE001
        inner = ""
    return split_br_lines(inner)


def extract_label(page: PageElement, label: str) -> str:
    """Return the value cell text that follows a label cell.

    Case Information uses ``<td class="label">{Label}:</td><td>{Value}</td>``
    pairs; the ORCA page uses ``class="Label"`` (capital L). The XPath
    lowercases the class attribute so it works for both casings, and
    matches the label text exactly (with trailing colon).
    """
    nodes = page.query(
        XPath(
            f"//td[contains(translate(@class, 'L', 'l'), 'label') and "
            f"normalize-space(text())='{label}:']/following-sibling::td[1]"
        ),
        f"label cell for {label!r}",
        min_count=0,
        max_count=1,
    )
    if not nodes:
        return ""
    return normalize_ws(nodes[0].text_content())


def radio_tail_text(cell: PageElement) -> str:
    """Return the visible label after the cell's checked radio input.

    The displayed value of a radio field is the text node *following*
    the ``<input type="radio" checked>`` element. ``query_strings`` with
    an XPath selecting that text node keeps this on the public
    ``PageElement`` API (no ``._element`` access).
    """
    strings = cell.query_strings(
        XPath(
            ".//input[@type='radio'][@checked]/following-sibling::text()[1]"
        ),
        "checked radio tail text",
        min_count=0,
        max_count=1,
    )
    return normalize_ws(strings[0]) if strings else ""
