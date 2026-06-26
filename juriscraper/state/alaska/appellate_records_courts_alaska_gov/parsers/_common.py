"""Shared helpers for the Alaska appellate-records page parsers."""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import TYPE_CHECKING
from urllib.parse import parse_qs, urlparse

from jkent.data_types import XPath

if TYPE_CHECKING:
    from jkent.common.page_element import PageElement

# Date formats seen across the CMS: M/D/YYYY, the hidden ISO date opened
# column (YYYY-MM-DD), and the oral-argument date/time stamp.
_DATE_FORMATS = ("%m/%d/%Y", "%Y-%m-%d", "%m/%d/%Y %I:%M %p")

# A line that looks like a phone number marks the address/phone split in an
# attorney ``<address>`` block.
PHONE_PATTERN = re.compile(r"[\d\(\)\-\s]{7,}")


def parse_ak_date(text: str | None) -> date | None:
    """Parse a date from the formats used across the Alaska CMS."""
    if not text:
        return None
    text = text.strip()
    if not text:
        return None
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def safe_text(element: PageElement) -> str:
    """Return an element's stripped text content, never raising."""
    try:
        return element.text_content().strip()
    except Exception:
        return ""


def extract_q_token(href: str | None) -> str | None:
    """Extract the encrypted ``q`` parameter from a case URL."""
    if not href:
        return None
    params = parse_qs(urlparse(href).query, keep_blank_values=True)
    q_values = params.get("q")
    return q_values[0] if q_values else None


def court_from_case_number(case_number: str) -> str:
    """Map a case number prefix to a CourtListener court id.

    ``A#####`` → ``akctapp`` (Court of Appeals); everything else
    (``S#####``) → ``ak`` (Supreme Court).
    """
    if case_number and case_number[0].upper() == "A":
        return "akctapp"
    return "ak"


def parse_attorney(addr_el: PageElement) -> dict:
    """Parse one attorney ``<address>`` block into an ``AkAttorney`` dict.

    Each block contains the attorney's name inside a ``<strong>`` tag
    followed by free-text address lines and an optional phone line. The
    first line matching the phone pattern marks the split between address
    and phone.
    """
    strong_els = addr_el.query(
        XPath(".//strong"), "attorney name", min_count=0
    )
    name = safe_text(strong_els[0]) if strong_els else None
    lines = [
        line.strip() for line in safe_text(addr_el).split("\n") if line.strip()
    ]
    # Drop the leading name line and any duplicate name lines.
    addr_lines = [line for line in lines[1:] if line != name]
    contact_raw: str | None = None
    phone: str | None = None
    for i, line in enumerate(addr_lines):
        if PHONE_PATTERN.match(line):
            phone = line
            contact_raw = ", ".join(addr_lines[:i]) or None
            break
    else:
        contact_raw = ", ".join(addr_lines) or None
    return {"name": name, "contact_raw": contact_raw, "phone": phone}


def collect_glyphicon_labels(page: PageElement) -> dict[str, bool]:
    """Collect every glyphicon checkbox state on a page, keyed by label.

    Each checkbox is a ``<span>`` with class ``glyphicon-check`` /
    ``glyphicon-ok`` (True) or ``glyphicon-unchecked`` / ``glyphicon-remove``
    (False), preceded by either bare text or a sibling span containing the
    label. The label set is open-ended upstream, so we capture every flag
    found rather than matching a fixed list.
    """
    result: dict[str, bool] = {}
    icons = page.query(
        XPath(
            "//span[contains(@class, 'glyphicon-check')"
            " or contains(@class, 'glyphicon-unchecked')"
            " or contains(@class, 'glyphicon-ok')"
            " or contains(@class, 'glyphicon-remove')]"
        ),
        "motion flag glyphicons",
        min_count=0,
    )
    for icon in icons:
        cls = icon.get_attribute("class") or ""
        if "glyphicon-ok" in cls or "glyphicon-check" in cls:
            value = True
        elif "glyphicon-unchecked" in cls or "glyphicon-remove" in cls:
            value = False
        else:
            continue

        # Label: the text immediately preceding the icon. Prefer the
        # preceding sibling's tail text, then its text content, then the
        # parent's leading text.
        label = ""
        preceding = icon.query_strings(
            XPath(
                "preceding-sibling::*[1]//text()[normalize-space()][last()]"
            ),
            "flag label (preceding element text)",
            min_count=0,
            max_count=1,
        )
        tail = icon.query_strings(
            XPath(
                "preceding-sibling::node()[normalize-space()][1][self::text()]"
            ),
            "flag label (preceding text node)",
            min_count=0,
            max_count=1,
        )
        parent_text = icon.query_strings(
            XPath("../text()[normalize-space()][1]"),
            "flag label (parent leading text)",
            min_count=0,
            max_count=1,
        )
        for candidate in (tail, preceding, parent_text):
            if candidate and candidate[0].strip():
                label = candidate[0].strip()
                break

        if label:
            result[label] = value
    return result
