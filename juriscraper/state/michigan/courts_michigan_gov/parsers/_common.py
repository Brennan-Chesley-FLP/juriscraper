"""Shared helpers for the Michigan courts JSON parsers.

The Michigan site is a pure-JSON API (Episerver SSR endpoints returning
``application/json``), so extraction works off ``dict`` payloads rather
than ``PageElement``. ``jkent``'s ``JKentParser`` is HTML-only (it wraps
an lxml node), so it does not apply here; the parsers in this package are
plain callables that take the relevant JSON fragment and return
``DeferredValidation`` records, keeping the JKentParser contract (return
``list[DeferredValidation[T]]``) so the steps stay thin (§9 — separate
extraction from navigation).
"""

from __future__ import annotations

from datetime import date, datetime


def parse_filing_date(value: str | None) -> date | None:
    """Parse the listing API's filing date into a ``date``.

    The listing returns ISO-8601 strings of the form
    ``2026-04-30T04:00:00+00:00`` or ``...Z``. Only the date portion
    matters for windowing; offsets are stripped. Returns ``None`` for
    missing/unparseable input.
    """
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except (TypeError, ValueError):
        return None


def clean_str(value: object) -> str | None:
    """Return a stripped string, or ``None`` for empty/non-string input."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None
