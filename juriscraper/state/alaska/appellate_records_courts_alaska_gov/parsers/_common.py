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

# The case-title span renders a cross-appeal reference as
# ``[Cross Appeal: <a>S18495</a>]``, followed by a bare duplicate anchor.
_CROSS_APPEAL_HTML_RE = re.compile(r"\[Cross Appeal:\s*<a[^>]*>(.*?)</a>\]")
_CROSS_APPEAL_TEXT_RE = re.compile(r"Cross Appeal:\s*([A-Za-z0-9-]+)")


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


def text_lines(element: PageElement, description: str) -> list[str]:
    """Return an element's non-empty text lines.

    Goes through an explicit ``text()`` query rather than
    ``text_content()`` so selector observers see the text nodes as
    consumed; splitting each node on newlines keeps the line list
    identical to what ``text_content().split("\\n")`` produced.
    """
    try:
        chunks = element.query_strings(
            XPath(".//text()"), description, min_count=0
        )
    except Exception:
        return []
    return [
        line.strip()
        for chunk in chunks
        for line in chunk.split("\n")
        if line.strip()
    ]


def parse_case_title(page: PageElement) -> dict:
    """Parse the case-title block that heads every case page.

    The block carries the case number and name, the case status, an
    optional ``[Cross Appeal: …]`` reference, and one badge div per
    special status (a one-letter glyph plus a tooltip spelling it out,
    e.g. ``E`` / ``Expedited``). Every case page repeats it; only the
    Case Summary page's copy is kept, on the ``AkDocket``.
    """
    out: dict = {}

    # The name span is the unadorned one; the status span carries
    # ``title="Case Status"`` and the badge tooltips live in child divs.
    name_spans = page.query(
        XPath("//div[contains(@class, 'cms-case-name')]/span[not(@title)]"),
        "case title span",
        min_count=0,
        max_count=1,
    )
    if name_spans:
        span = name_spans[0]
        cross_links = span.query(
            XPath(".//a"), "cross-appeal links", min_count=0
        )
        title_text = " ".join(text_lines(span, "case title text"))
        cross_match = _CROSS_APPEAL_HTML_RE.search(
            span.inner_html()
        ) or _CROSS_APPEAL_TEXT_RE.search(title_text)
        if cross_match:
            out["cross_appeal_docket_number"] = cross_match.group(1).strip()
        # The reference renders twice: once inside the "[Cross Appeal: …]"
        # brackets addressed by legacy ``caseID``, then again as a bare
        # anchor carrying the encrypted ``q`` token we actually want.
        for link in cross_links:
            token = extract_q_token(link.get_attribute("href"))
            if token:
                out["cross_appeal_internal_id"] = token
                break

    status_spans = page.query(
        XPath(
            "//div[contains(@class, 'cms-case-name')]"
            "/span[@title='Case Status']"
        ),
        "case status span",
        min_count=0,
        max_count=1,
    )
    if status_spans:
        status = safe_text(status_spans[0])
        if status:
            out["case_status"] = status

    flags: list[str] = []
    for badge in page.query(
        XPath(
            "//div[contains(@class, 'cms-case-name')]"
            "//div[contains(@class, 'specialStatusFlag')]"
        ),
        "special status badges",
        min_count=0,
    ):
        tooltip = badge.query_strings(
            XPath("./span[contains(@class, 'cms-tooltiptext')]/text()"),
            "special status tooltip",
            min_count=0,
            max_count=1,
        )
        glyph = badge.query_strings(
            XPath("./text()"), "special status glyph", min_count=0
        )
        label = next(
            (
                text.strip()
                for text in (*tooltip, *glyph)
                if text and text.strip()
            ),
            "",
        )
        if label:
            flags.append(label)
    if flags:
        out["special_status_flags"] = flags

    return out


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
    lines = text_lines(addr_el, "attorney address lines")
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
