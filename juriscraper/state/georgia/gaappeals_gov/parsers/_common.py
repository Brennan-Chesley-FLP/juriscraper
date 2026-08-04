"""Shared helpers for the Georgia Court of Appeals page parsers."""

from __future__ import annotations

import re
from datetime import date, datetime
from urllib.parse import parse_qs, urlparse

# Values the site uses to mean "this section is empty".
PLACEHOLDER_VALUES = {"", "none", "n/a"}

_FILING_ID_PATTERN = re.compile(r"filingId=([0-9a-fA-F-]+)")

# 'DISMISSED (July 7, 2026)' — the detail page packs the ruling and its
# disposition date into the one 'COA Judgment/Ruling' cell.
_JUDGMENT_PATTERN = re.compile(r"^(?P<ruling>.+?)\s*\((?P<date>[^)]+)\)$")


def clean(value: str | None) -> str | None:
    """Collapse whitespace; return ``None`` for empty/None inputs."""
    if value is None:
        return None
    text = " ".join(value.split())
    return text or None


def none_unless_meaningful(value: str | None) -> str | None:
    """``clean`` but also map the site's placeholder values to ``None``."""
    text = clean(value)
    if text is None or text.lower() in PLACEHOLDER_VALUES:
        return None
    return text


def parse_long_date(value: str | None) -> date | None:
    """Parse a date in the site's display format.

    Handles ``April 15, 2026``, ``January 29,2026`` (note the missing space
    seen on the search-results page), and a couple of other variants.
    Returns ``None`` for ``None``, empty strings, or the literal ``None``.
    """
    text = clean(value)
    if text is None or text.lower() in PLACEHOLDER_VALUES:
        return None
    # The site sometimes omits a space after the comma ('January 29,2026').
    normalized = re.sub(r",\s*", ", ", text)
    for fmt in ("%B %d, %Y", "%b %d, %Y"):
        try:
            return datetime.strptime(normalized, fmt).date()
        except ValueError:
            continue
    return None


def parse_iso_date(value: str | None) -> date | None:
    """Parse an ``YYYY-MM-DD`` (or longer ISO) string to a ``date``."""
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def parse_judgment(value: str | None) -> tuple[str | None, date | None]:
    """Split a ``COA Judgment/Ruling`` cell into ``(ruling, date)``.

    The detail page renders it as ``DISMISSED (July 7, 2026)``; the
    opinion-search results table splits the two into separate columns. When
    the parenthesised date is missing the whole string is taken as the ruling.
    """
    text = none_unless_meaningful(value)
    if text is None:
        return None, None
    match = _JUDGMENT_PATTERN.match(text)
    if match is None:
        return text, None
    return (
        none_unless_meaningful(match.group("ruling")),
        parse_long_date(match.group("date")),
    )


def extract_filing_id(url: str) -> str | None:
    """Pull the ``filingId`` UUID out of an opinion-download URL."""
    parsed = urlparse(url)
    params = parse_qs(parsed.query)
    ids = params.get("filingId")
    return ids[0] if ids else None
