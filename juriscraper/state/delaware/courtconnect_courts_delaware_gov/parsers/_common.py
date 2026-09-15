"""Shared helpers for the Delaware CourtConnect page parsers."""

from __future__ import annotations

import re
from datetime import date, time
from typing import TYPE_CHECKING

from jkent.data_types import XPath

if TYPE_CHECKING:
    from jkent.common.page_element import PageElement

#: "30-SEP-2025" -- the form every table cell uses.
_DMY = re.compile(r"^(\d{1,2})-([A-Za-z]{3})-(\d{4})$")

#: "Thursday , February 27th, 2025" -- the Case Description block's form. The
#: weekday is padded to a fixed width, so the run of spaces before the comma
#: varies; the month is padded the same way. Both are absorbed by ``\s*``.
_LONG_DATE = re.compile(
    r"^(?:[A-Za-z]+\s*,\s*)?"  # optional weekday
    r"([A-Za-z]+)\s+"  # month name
    r"(\d{1,2})(?:st|nd|rd|th)?\s*,\s*"  # ordinal day
    r"(\d{4})$"  # year
)

#: "11:37 AM"
_TIME = re.compile(r"^(\d{1,2}):(\d{2})\s*([AP]M)$", re.IGNORECASE)

_MONTHS = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}

#: Values the site prints in a slot to mean "nothing here". Stored verbatim
#: they read as data -- an address of "unavailable", an alias named "none".
_ABSENT_VALUES = {"none", "unavailable", "n/a", "not available"}


def clean_text(text: str | None) -> str | None:
    """Collapse whitespace; return None for an empty result.

    ``\xa0`` is included in ``str.split``'s whitespace set, which matters here:
    every value cell on this site opens with a literal ``&nbsp;``.
    """
    if text is None:
        return None
    collapsed = " ".join(text.split())
    return collapsed or None


def clean_optional(text: str | None) -> str | None:
    """Like :func:`clean_text`, but map the site's placeholders to None."""
    cleaned = clean_text(text)
    if cleaned is None or cleaned.lower() in _ABSENT_VALUES:
        return None
    return cleaned


def parse_date(text: str | None) -> date | None:
    """Parse either date form the site prints; None if it parses as neither.

    Both forms are accepted by one function because the two are never
    ambiguous with each other and callers do not otherwise care which section
    of the page a date came from.
    """
    cleaned = clean_text(text)
    if cleaned is None:
        return None
    if match := _DMY.match(cleaned):
        day, month, year = match.groups()
        if (month_number := _MONTHS.get(month.lower())) is None:
            return None
        return date(int(year), month_number, int(day))
    if match := _LONG_DATE.match(cleaned):
        month, day, year = match.groups()
        if (month_number := _MONTHS.get(month[:3].lower())) is None:
            return None
        return date(int(year), month_number, int(day))
    return None


def parse_time(text: str | None) -> time | None:
    """Parse a "HH:MM AM" clock time; None if it does not match."""
    cleaned = clean_text(text)
    if cleaned is None:
        return None
    match = _TIME.match(cleaned)
    if match is None:
        return None
    hour, minute, meridiem = match.groups()
    hour = int(hour) % 12
    if meridiem.upper() == "PM":
        hour += 12
    return time(hour, int(minute))


def split_code_description(text: str | None) -> tuple[str | None, str | None]:
    """Split a ``"CODE - DESCRIPTION"`` pair, as used by Type and Status.

    Splits on the *first* " - " only: a description may contain further
    hyphens, but the code never does.

    Reads through :func:`clean_optional`, because the site prints ``none`` in
    these slots when it has no value: JP case 13-87-C1227 has ``<i>none</i>``
    for its Status, which taken literally becomes a status *code* of "none".
    """
    cleaned = clean_optional(text)
    if cleaned is None:
        return None, None
    code, separator, description = cleaned.partition(" - ")
    if not separator:
        return cleaned, None
    return code.strip() or None, description.strip() or None


def cell_lines(element: PageElement | None) -> list[str]:
    """Read a cell's ``<br>``-separated lines.

    ``text_content()`` drops ``<br>`` entirely, gluing the lines it separated
    into one run -- a docket entry's date cell reads "15-NOV-202409:04 AM", and
    an attorney's address collapses its street and city lines together.
    Collecting the text nodes individually keeps the boundaries.
    """
    if element is None:
        return []
    return [
        line
        for text in element.query_strings(
            XPath(".//text()"), "cell text lines", min_count=0
        )
        if (line := " ".join(text.split()))
    ]


def parse_int(text: str | None) -> int | None:
    """Parse a small integer cell (Seq #, Assoc); None when not a number."""
    cleaned = clean_text(text)
    if cleaned is None or not cleaned.isdigit():
        return None
    return int(cleaned)


def header_labels(rows: list[PageElement]) -> list[str]:
    """Read a table's column labels from its ``<th>`` header row.

    Returns ``[]`` when the table has no header row, which is what the generic
    section parsers key off to fall back to positional reading.
    """
    for row in rows:
        headers = row.query(XPath("./th"), "header cells", min_count=0)
        if headers:
            return [
                clean_text(header.text_content()) or "" for header in headers
            ]
    return []
