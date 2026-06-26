"""Shared helpers for the SC C-Track page parsers."""

from __future__ import annotations

import re

# Form-text → CourtListener court ID, keyed on the human-readable
# "Court:" string the site emits on listing rows and the detail page.
COURT_NAME_TO_COURT: dict[str, str] = {
    "Supreme Court": "sc",
    "Court of Appeals": "scctapp",
}

# Listing-row case link href: /public/caseView.do?csIID=N — the csIID is
# C-Track's internal case key.
CSIID_RE = re.compile(r"csIID=(\d+)")

# Docket-event document icons carry a `name` attribute encoding the
# event ID as ``deID:{eventId}``.
DEID_RE = re.compile(r"deID:(\d+)")


def normalize_whitespace(text: str | None) -> str:
    """Collapse contiguous whitespace to a single space."""
    return " ".join((text or "").split())
