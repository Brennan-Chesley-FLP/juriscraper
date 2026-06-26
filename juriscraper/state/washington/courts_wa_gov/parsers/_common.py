"""Shared helpers for the Washington appellate-briefs page parsers."""

from __future__ import annotations

import re

# Anchor name format for a hearing-date section, e.g. "a20260115".
HEARING_ANCHOR_RE = re.compile(r"^a(\d{4})(\d{2})(\d{2})$")

# Case LI text format: "<docket> - <case name>" where docket is e.g.
# "104,170-5" (Supreme Court) or "84401-6" (Court of Appeals).
CASE_TEXT_RE = re.compile(r"^\s*([\d,]+-\d+)\s*-\s*(.+?)\s*$", re.DOTALL)

# Empty-year signal rendered by the site (Div III early years, etc.).
EMPTY_YEAR_TEXT = "No Court Briefs were found with Scheduled Hearing Dates"


def collapse_ws(text: str) -> str:
    """Collapse runs of whitespace to single spaces and strip."""
    return re.sub(r"\s+", " ", text or "").strip()
