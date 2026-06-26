"""Shared helpers for the New Jersey Judiciary (njcourts.gov) page parsers."""

from __future__ import annotations

import re
from datetime import date, datetime
from urllib.parse import urljoin

from juriscraper.state.new_jersey.njcourts_gov.models import BASE_URL

# Caption parenthetical e.g. "(091434)" — six-digit CMS id on SCOTNJ rows.
CMS_ID_RE = re.compile(r"\((\d{5,7})\)\s*$")

# "(RECORD IMPOUNDED)" appears at the end of SCAD argument-schedule captions.
IMPOUNDED_RE = re.compile(r"\(RECORD IMPOUNDED\)\s*$", re.IGNORECASE)

# Right-column event row: "Event Name : Date" (sometimes "Event Name: Date").
EVENT_LINE_RE = re.compile(r"^(?P<name>[^:]+?)\s*:\s*(?P<rest>.+)$")

# SCAD docket id cited inside a "Read Appellate Opinion A-1602-24" link text.
APPELLATE_DOCKET_RE = re.compile(r"A-?\d{1,4}-\d{2,4}")


def normalise(text: str | None) -> str:
    """Collapse whitespace and trim."""
    if not text:
        return ""
    return " ".join(text.split())


def parse_date(text: str | None) -> date | None:
    """Parse a date string from any of the formats used on njcourts.gov.

    Examples observed: ``April 10, 2026``, ``Jan. 21, 2026``,
    ``Feb. 24, 2026``, ``July 2, 2026``, ``Sept. 3, 2025``. The site
    uses both 3-letter abbreviations and the 4-letter ``Sept`` form,
    so we normalise that quirk before strptime.
    """
    if not text:
        return None
    s = normalise(text).rstrip(".")
    s = re.sub(r"^[A-Za-z]+,\s+", "", s)
    s = re.sub(r"\bSept\.\s", "Sep. ", s)
    for fmt in ("%B %d, %Y", "%b %d, %Y", "%b. %d, %Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def abs_url(href: str | None, base: str = BASE_URL) -> str | None:
    """Resolve a possibly-relative href against the site base URL."""
    if not href:
        return None
    return urljoin(base, href)


def parse_caption_block(p_h5_text: str) -> tuple[str, str | None]:
    """Pull the trailing ``(NNNNNN)`` CMS id out of an SCOTNJ caption.

    The ``<p class="h5">`` contains ``"A-40-25 In re … (091434)"`` after
    text-content normalisation. Returns ``(text_without_cms, cms_id)``.
    """
    text = normalise(p_h5_text)
    m = CMS_ID_RE.search(text)
    if not m:
        return text, None
    return text[: m.start()].rstrip(), m.group(1)
