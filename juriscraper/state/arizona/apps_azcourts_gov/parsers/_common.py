"""Shared helpers for the Arizona appellate-courts (AppellaDockets) parsers.

The backend publishes static HTML with auto-generated ``htmldwXXXX`` CSS
classes (the leading hex changes between nightly builds), so selectors rely
on document structure (column order, anchor text, hidden cells) rather than
class names. PDF hrefs use Windows-style backslashes; we normalise them to
forward-slash absolute URLs.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import TYPE_CHECKING

from jkent.data_types import XPath

from juriscraper.state.arizona.apps_azcourts_gov.models import BASE_URL

if TYPE_CHECKING:
    from jkent.common.page_element import PageElement

# Hidden-cell text format: "M/D/YYYY HH:MM:SS\<COURT>\<TYPE>\<FILE>.PDF".
# Extract the timestamp prefix (left of the first backslash).
TIMESTAMP_PATH_RE = re.compile(
    r"^(?P<ts>\d{1,2}/\d{1,2}/\d{4}\s+\d{1,2}:\d{2}:\d{2})\\(?P<path>.+)$"
)
# Match attorney bracket suffix: "[AZ-9001]", "[AZ]", "[OH]", etc.
# Captures (jurisdiction, optional number).
BAR_BRACKET_RE = re.compile(
    r"\[\s*(?P<juris>[A-Za-z]+)\s*(?:-?\s*(?P<num>\d+))?\s*\]"
)
PDF_HREF_RE = re.compile(r"\.pdf$", re.I)


def safe_text(element: PageElement) -> str:
    """Return an element's stripped text, or ``""`` if extraction fails."""
    try:
        return element.text_content().strip()
    except Exception:
        return ""


def normalise_pdf_href(href: str) -> str:
    """Convert backslash-style hrefs to a clean absolute URL.

    AppellaDockets emits Windows paths (``ASC\\CR\\CR260127.PDF``). The
    server accepts backslashes verbatim, but we normalise to forward slashes
    so the URLs round-trip cleanly through dedup keys, logging, and any
    downstream consumer.
    """
    clean = href.replace("\\", "/").lstrip("/")
    return BASE_URL + clean


def parse_timestamp(raw: str) -> datetime | None:
    """Parse the ``M/D/YYYY HH:MM:SS`` hidden timestamp."""
    try:
        return datetime.strptime(raw.strip(), "%m/%d/%Y %H:%M:%S")
    except ValueError:
        return None


def iter_pdf_rows(page: PageElement) -> list[PageElement]:
    """Return all ``<tr>`` rows containing a PDF link.

    The anchor may be in column 0 (case-type pages) or column 1 (index
    pages), so we match by href suffix anywhere in the row.
    """
    return page.query(
        XPath(
            "//tr[.//a[contains(translate(@href,"
            " 'ABCDEFGHIJKLMNOPQRSTUVWXYZ',"
            " 'abcdefghijklmnopqrstuvwxyz'), '.pdf')]]"
        ),
        "case rows",
        min_count=0,
    )


def extract_row_pdf_link(row: PageElement) -> tuple[str, str] | None:
    """Return ``(docket_number, pdf_url)`` for a case row, or ``None``.

    The PDF anchor is in column 0 on case-type pages, but in column 1 on the
    index pages (lower-court / party / attorney). We match the anchor by href
    shape rather than position.

    State Bar (SB) anchors include a ``<small> [Ending]</small>`` status
    badge inside the anchor; we use the anchor's first text node so
    ``docket_number`` doesn't pick up that badge.
    """
    anchors = row.query(XPath(".//a[@href]"), "row anchors", min_count=0)
    for a in anchors:
        href = a.get_attribute("href") or ""
        if not PDF_HREF_RE.search(href):
            continue
        leading = a.query_strings(
            XPath("./text()[1]"),
            "anchor leading text",
            min_count=0,
            max_count=1,
        )
        if leading and leading[0].strip():
            docket_number = leading[0].strip()
        else:
            docket_number = safe_text(a)
        if not docket_number:
            continue
        return docket_number, normalise_pdf_href(href)
    return None


def extract_row_timestamp_and_path(
    row: PageElement,
) -> tuple[datetime | None, str | None]:
    """Pull the ``(timestamp, path)`` pair out of a row's hidden cells.

    Hidden cell format: ``M/D/YYYY HH:MM:SS\\<COURT>\\<TYPE>\\<FILE>.PDF``.
    Both the canonical and ``_update`` variants emit it.
    """
    hidden_cells = row.query(
        XPath(".//td[contains(@style, 'visibility:hidden')]"),
        "hidden cells",
        min_count=0,
    )
    for cell in hidden_cells:
        text = safe_text(cell)
        match = TIMESTAMP_PATH_RE.match(text)
        if match:
            ts = parse_timestamp(match.group("ts"))
            return ts, match.group("path")
    return None, None
