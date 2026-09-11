"""Shared helpers for the PA appellate JSON-API parsers.

These parsers consume JSON, not HTML, so they are **not**
``JKentParser`` subclasses — that base class is bound to lxml/``PageElement``
(``JKentParser.from_string`` builds an ``LxmlPageElement``). They are plain
callables that take the decoded ``json_content`` mapping, which keeps them
fully offline-testable: pass a saved response dict straight in.
"""

from __future__ import annotations

from datetime import date, datetime, time
from typing import Any

#: PACMS renders "no value" for some datetime fields as a year-1 sentinel
#: (``"0001-01-01T00:00:00-05:00"``) rather than JSON ``null`` — observed on
#: the ``reArgument*RegistryEntry`` slots of a case with no reargument
#: history. Anything at or before this year is treated as absent.
_NULL_YEAR = 1


def parse_datetime(value: Any) -> datetime | None:
    """Parse a PACMS ISO-8601 timestamp into an aware ``datetime``.

    Returns ``None`` for ``None``, blank strings, unparseable values, and the
    year-1 sentinel PACMS uses in place of ``null``.
    """
    if not value or not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.year <= _NULL_YEAR:
        return None
    return parsed


def parse_date(value: Any) -> date | None:
    """Parse a PACMS timestamp down to its calendar date.

    The API stamps every date field as a full timestamp in the court's local
    zone; CourtListener stores plain dates, so the local calendar date is
    what we keep (``.date()`` on the aware value, no UTC conversion — an
    ``08:00-04:00`` filing is an August 20th filing, not the 20th at noon UTC).
    """
    parsed = parse_datetime(value)
    return parsed.date() if parsed else None


def parse_time(value: Any) -> time | None:
    """Parse the time-of-day component of a PACMS timestamp.

    Returns ``None`` when the value is absent or lands exactly on midnight —
    PACMS uses ``T00:00:00`` for date-only fields, so a midnight time carries
    no information and would otherwise fabricate a precise filing time.
    """
    parsed = parse_datetime(value)
    if parsed is None:
        return None
    result = parsed.time()
    return None if result == time(0, 0, 0) else result


def clean_str(value: Any) -> str | None:
    """Normalize a scalar to a stripped string, or ``None`` if empty.

    The API frequently returns ``""`` where it means "not set"
    (e.g. ``currentProgramStatus``), so empty strings collapse to ``None``.
    """
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def as_dict(value: Any) -> dict[str, Any]:
    """Return ``value`` when it is a mapping, else an empty mapping.

    The API returns fully-null placeholder objects (every key present, every
    value ``None``) instead of omitting an absent relation, so callers can
    chain ``as_dict`` without guarding each hop.
    """
    return value if isinstance(value, dict) else {}


def as_list(value: Any) -> list[Any]:
    """Return ``value`` when it is a list, else an empty list."""
    return value if isinstance(value, list) else []


def dig(data: Any, *keys: str) -> Any:
    """Walk a chain of mapping keys, returning ``None`` if any hop is missing."""
    current = data
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def name_of(value: Any) -> str | None:
    """Flatten a PACMS name object to its best single-string form.

    PACMS name objects carry ``documentName`` (how the name is written on
    documents, e.g. ``"Jason David Javie, Esq."``) and ``displayName`` (the
    sort form, ``"Javie, Jason David"``). ``documentName`` is preferred
    because it matches how CourtListener stores ``Party.name`` /
    ``Attorney.name``; ``displayName`` is the fallback.
    """
    name = as_dict(value)
    return clean_str(name.get("documentName")) or clean_str(
        name.get("displayName")
    )


def name_parts(value: Any) -> dict[str, str | None]:
    """Split a PACMS name object into the structured fields our models carry."""
    name = as_dict(value)
    return {
        "name": name_of(value),
        "display_name": clean_str(name.get("displayName")),
        "first_name": clean_str(name.get("firstName")),
        "middle_name": clean_str(name.get("middleName")),
        "last_name": clean_str(name.get("lastName")),
        "title": clean_str(name.get("title")),
    }


def lines_of(value: Any) -> list[str]:
    """Normalize a PACMS ``*Lines`` array to a list of non-empty strings."""
    return [text for text in (clean_str(v) for v in as_list(value)) if text]


def entity_id(value: Any) -> str | None:
    """Extract the scalar id from a PACMS ``{caseSystem, id}`` identifier."""
    raw = dig(value, "id")
    return clean_str(raw)
