"""Shared helpers for the NYSCEF page parsers."""

from __future__ import annotations

import re
from datetime import date, datetime

_DATE_RE = re.compile(r"(\d{1,2}/\d{1,2}/\d{4})")


def parse_date_mdy(text: str | None) -> date | None:
    """Parse the first ``MM/DD/YYYY`` date found in ``text``.

    Returns ``None`` for missing/empty/unparseable input.
    """
    if not text:
        return None
    match = _DATE_RE.search(text)
    if not match:
        return None
    try:
        return datetime.strptime(match.group(1), "%m/%d/%Y").date()
    except ValueError:
        return None


def extract_query_param(url: str | None, *names: str) -> str | None:
    """Return the first present ``name=value`` query value from ``url``.

    Tries each ``name`` in order (e.g. ``docIndex`` then ``docId``) and
    returns the raw, un-decoded value. ``None`` if none match.
    """
    if not url:
        return None
    for name in names:
        match = re.search(rf"{re.escape(name)}=([^&]+)", url)
        if match:
            return match.group(1)
    return None


def split_party_name_role(text: str) -> tuple[str, str | None]:
    """Split ``"Party Name , Role"`` into ``(name, role)``.

    The role is the trailing ``, <Role>`` token; party names may themselves
    contain commas (e.g. ``AC 31, LLC , Respondent``). Roles may be compound
    (``Plaintiff-Appellant``). Returns ``(text, None)`` when no role matches.
    """
    role_pattern = re.compile(
        r",\s*((?:Plaintiff|Defendant|Third-Party[\s-]?\w*)?-?"
        r"(?:Appellant|Respondent|Petitioner|Intervenor|"
        r"Mailing Party|Amicus Curiae))\s*$"
    )
    match = role_pattern.search(text)
    if match:
        role = match.group(1).strip()
        name = text[: match.start()].strip()
        return name, role
    return text.strip(), None


def parse_attorney_reps(text: str) -> list[dict]:
    """Parse the attorney-representation cell into structured records.

    Text format (per attorney, blocks separated by blank lines)::

        ATTORNEY_NAME on MM/DD/YYYY
        Firm Name

    Returns a list of ``{"name", "firm", "date_consent"}`` dicts.
    ``"none recorded"`` (or empty) yields ``[]``.
    """
    attorneys: list[dict] = []
    if not text or text.strip().lower() == "none recorded":
        return attorneys

    for raw_block in re.split(r"\n\s*\n", text):
        block = raw_block.strip()
        if not block:
            continue
        match = re.match(
            r"(.+?)\s+on\s+(\d{1,2}/\d{1,2}/\d{4})\s*(.*)",
            block,
            re.DOTALL,
        )
        if match:
            attorneys.append(
                {
                    "name": match.group(1).strip(),
                    "firm": match.group(3).strip() or None,
                    "date_consent": parse_date_mdy(match.group(2)),
                }
            )
        else:
            attorneys.append(
                {
                    "name": block.split("\n")[0].strip(),
                    "firm": None,
                    "date_consent": None,
                }
            )
    return attorneys


def parse_filed_by_cell(
    text: str,
) -> tuple[str | None, date | None, date | None]:
    """Parse the Document-List "Filed By" cell.

    Format::

        FILED_BY_NAME
        Filed: MM/DD/YYYY
        Received: MM/DD/YYYY

    Returns ``(filed_by, date_filed, date_received)``.
    """
    lines = [line.strip() for line in text.split("\n") if line.strip()]
    filed_by = lines[0] if lines else None
    date_filed: date | None = None
    date_received: date | None = None
    for line in lines:
        if line.startswith("Filed:"):
            date_filed = parse_date_mdy(line)
        elif line.startswith("Received:"):
            date_received = parse_date_mdy(line)
    return filed_by, date_filed, date_received
