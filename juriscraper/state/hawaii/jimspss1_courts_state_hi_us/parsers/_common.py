"""Shared helpers for the Hawaiʻi eCourt Kōkua page parsers."""

from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING

from jkent.data_types import XPath

if TYPE_CHECKING:
    from jkent.common.page_element import PageElement

# Hawaii eCourt date entry / display format (e.g. "01-APR-2026"). The server
# strictly enforces this on input; values are also rendered this way.
SITE_DATE_FORMAT = "%d-%b-%Y"


def parse_site_date(value: str | None) -> date | None:
    """Parse the eCourt date format (``DD-MMM-YYYY``).

    Returns ``None`` for missing/empty/unparseable input.
    """
    if not value:
        return None
    try:
        return datetime.strptime(
            value.strip().upper(), SITE_DATE_FORMAT
        ).date()
    except ValueError:
        return None


def clean(raw: str | None) -> str | None:
    """Strip, drop NBSPs; return ``None`` for an empty result."""
    if raw is None:
        return None
    text = raw.replace("\xa0", " ").strip()
    return text or None


def value_for_label(page: PageElement, label: str) -> str | None:
    """Return the text in the cell immediately following a label cell.

    The Hawaiʻi case summary is rendered as ``<td>Label:</td><td>value</td>``
    pairs; matching is case-insensitive and tolerant of trailing colons.
    """
    lower = label.lower()
    candidates = page.query_strings(
        XPath(
            f"//td[normalize-space(translate(text(),"
            f" 'ABCDEFGHIJKLMNOPQRSTUVWXYZ',"
            f" 'abcdefghijklmnopqrstuvwxyz'))="
            f" '{lower}:' or normalize-space(translate(text(),"
            f" 'ABCDEFGHIJKLMNOPQRSTUVWXYZ',"
            f" 'abcdefghijklmnopqrstuvwxyz'))="
            f" '{lower}']/following-sibling::td[1]//text()"
        ),
        f"value for label {label!r}",
        min_count=0,
    )
    text = " ".join(s.strip() for s in candidates if s.strip())
    return text or None
