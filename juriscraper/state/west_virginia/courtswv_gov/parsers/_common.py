"""Shared helpers for the West Virginia courtswv.gov page parsers."""

from __future__ import annotations

import re
from datetime import date, datetime

# Split consolidated case-no strings on either separator: " & " or " and ".
_CONSOLIDATED_SPLIT_RE = re.compile(r"\s*(?:&|and)\s*", re.IGNORECASE)

_LISTING_DATE_RE = re.compile(r"\b(\d{2}/\d{2}/\d{4})\b")

_CLERK_BRIEFS_RE = re.compile(
    r"briefs?[\s\S]{0,40}?(?:on file|filed)[\s\S]{0,40}?clerk",
    re.IGNORECASE,
)


def split_docket_numbers(case_no_text: str) -> list[str]:
    """Split a possibly-consolidated case-no string into components."""
    if not case_no_text:
        return []
    return [
        p.strip()
        for p in _CONSOLIDATED_SPLIT_RE.split(case_no_text)
        if p.strip()
    ]


def parse_listing_date(raw: str | None) -> date | None:
    """Parse the ``MM/DD/YYYY`` date in a listing row."""
    if not raw:
        return None
    match = _LISTING_DATE_RE.search(raw)
    if not match:
        return None
    try:
        return datetime.strptime(match.group(1), "%m/%d/%Y").date()
    except ValueError:
        return None


def date_from_iso(value: str | None) -> date | None:
    """Parse an ISO date string, tolerating ``None`` / bad input."""
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def parse_detail_iso_datetime(raw: str | None) -> date | None:
    """Parse a ``<time datetime=...>`` ISO value into a ``date``."""
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def parse_detail_rendered_date(raw: str | None) -> date | None:
    """Parse a rendered date like ``"Wednesday, April 22, 2026"``."""
    if not raw:
        return None
    for fmt in ("%A, %B %d, %Y", "%B %d, %Y"):
        try:
            return datetime.strptime(raw.strip(), fmt).date()
        except ValueError:
            continue
    return None


def clerk_holds_briefs(note_text: str | None) -> bool:
    """True when the docket note signals briefs are held at the Clerk's
    office (not posted online)."""
    return bool(note_text and _CLERK_BRIEFS_RE.search(note_text))


def component_for_brief(
    description: str,
    consolidated_numbers: list[str],
    primary_docket_number: str,
) -> str:
    """Pick which docket number a brief belongs to in a consolidated case.

    The site labels component briefs with their docket-number prefix
    (``"23-753 Petitioner's Brief"``). When the description starts with
    a known component, we assign the brief to that component. Otherwise
    we fall back to the primary docket number.
    """
    if not description or len(consolidated_numbers) <= 1:
        return primary_docket_number
    for component in consolidated_numbers:
        if description.lower().startswith(component.lower()):
            return component
    return primary_docket_number


def row_matches_query(case_no_text: str, query: str) -> bool:
    """Check whether the listing row's case-no contains the requested
    docket number.

    ``combine=`` searches multiple columns, so we re-verify here that
    the row really does match the user's docket-number query before
    following its detail link. Comparison is case-insensitive and
    matches against any component of a consolidated case-no string.
    """
    if not query:
        return True
    components = split_docket_numbers(case_no_text)
    needle = query.lower().strip()
    for component in components:
        if component.lower() == needle:
            return True
    # Fall back to substring match (handles formatting drift like
    # "25-ICA-280" vs "25-ica-280").
    return needle in case_no_text.lower()
