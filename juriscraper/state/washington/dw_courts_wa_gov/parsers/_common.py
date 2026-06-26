"""Shared helpers for the Washington DW Courts page parsers."""

from __future__ import annotations

import re
from datetime import date

# Date format used on the site: MM-DD-YY.
_DW_DATE_RE = re.compile(r"^(\d{2})-(\d{2})-(\d{2})$")


def parse_dw_date(text: str | None) -> date | None:
    """Parse ``MM-DD-YY`` into a :class:`date`.

    Two-digit years are interpreted as 2000-2099 (the site doesn't carry
    data before 2000). Returns ``None`` for missing/unparseable input.
    """
    if not text:
        return None
    m = _DW_DATE_RE.match(text.strip())
    if not m:
        return None
    month, day, year_2 = int(m.group(1)), int(m.group(2)), int(m.group(3))
    year = 2000 + year_2
    try:
        return date(year, month, day)
    except ValueError:
        return None
