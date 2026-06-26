"""Shared helpers for the Vermont Public Portal page parsers.

These cover the two HTML pages the scraper parses (the Smart-Search
results grid and the Document Viewer landing page); the JSON
Register-of-Actions endpoints are handled in the scraper steps.
"""

from __future__ import annotations

from datetime import date, datetime
from urllib.parse import parse_qs, urlparse


def extract_roa_key(data_url: str | None) -> str | None:
    """Pull the ``id`` query parameter from a search row's ``data-url``.

    The grid renders ``<a class="caseLink"
    data-url="/app/RegisterOfActions/?id=...&isAuthenticated=False&...">``.
    The ``id`` param is the opaque key the JSON service expects (a
    *different*, longer token than the ``data-caseid`` attribute).
    """
    if not data_url:
        return None
    parsed = urlparse(data_url)
    ids = parse_qs(parsed.query).get("id")
    return ids[0] if ids else None


def parse_us_date(value: str | None) -> date | None:
    """Parse Tyler's ``mm/dd/yyyy`` (or ``mm/dd/yyyy hh:mm:ss:fff``) format."""
    if not value:
        return None
    head = value.split()[0]
    try:
        return datetime.strptime(head, "%m/%d/%Y").date()
    except ValueError:
        return None


def parse_iso_date(value: str | None) -> date | None:
    """Parse the leading ``YYYY-MM-DD`` of an ISO date/datetime string."""
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None
