"""Shared helpers for the Tennessee Public Case History page parsers."""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from jkent.common.page_element import PageElement

# Case-number shape, e.g. ``M2013-02744-SC-R11-CD``. The third segment
# (``SC`` / ``COA`` / ``CCA``) selects the court.
CASE_NUMBER_RE = re.compile(
    r"^[EMW]\d{4}-\d{5}-(SC|COA|CCA)-",
    re.IGNORECASE,
)

# ASP.NET ``__doPostBack('<target>', '<arg>')`` extraction.
POSTBACK_TARGET_RE = re.compile(r"__doPostBack\('([^']+)'")


def safe_text(element: PageElement) -> str:
    """Return an element's stripped text, or ``""`` if extraction fails."""
    try:
        return element.text_content().strip()
    except Exception:
        return ""


def parse_date(raw: str | None) -> date | None:
    """Parse an ``mm/dd/yyyy`` date string.

    Returns ``None`` for missing/empty/unparseable input.
    """
    if not raw:
        return None
    text = raw.strip().replace("\xa0", " ").strip()
    if not text:
        return None
    try:
        return datetime.strptime(text, "%m/%d/%Y").date()
    except ValueError:
        return None


def court_from_docket_number(docket_number: str) -> str | None:
    """Derive the CourtListener court id from a docket number.

    Returns ``None`` for an unrecognized suffix.
    """
    from juriscraper.state.tennessee.pch_tncourts_gov.models import (
        SUFFIX_TO_COURT,
    )

    match = CASE_NUMBER_RE.match(docket_number)
    if not match:
        return None
    return SUFFIX_TO_COURT.get(match.group(1).upper())
