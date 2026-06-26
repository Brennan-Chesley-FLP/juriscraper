"""Shared helpers for the DC C-Track page parsers."""

from __future__ import annotations

import re

# Result-row case-link href: /public/caseView.do?csIID=N
CSIID_RE = re.compile(r"csIID=(\d+)")

# documentLink icon `name` attribute encodes "flag:deID:csIID".
DOC_ICON_NAME_RE = re.compile(r"^(\d+):(\d+):(\d+)$")


def normalize_whitespace(text: str | None) -> str:
    """Collapse contiguous whitespace to a single space."""
    return " ".join((text or "").split())


def parse_yn(text: str | None) -> bool | None:
    """Parse a ``Y``/``N`` flag cell to a tri-state bool."""
    cleaned = normalize_whitespace(text).upper()
    if cleaned == "Y":
        return True
    if cleaned == "N":
        return False
    return None
