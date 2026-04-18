"""Data models for the Washington appellate briefs scraper (www.courts.wa.gov).

Briefs are hosted on the public ``/appellate_trial_courts/coaBriefs/`` pages of
``www.courts.wa.gov`` and are organized by *scheduled hearing date*.  Each
year page lists every hearing date for that year, the cases scheduled on
that date, and PDF links to every brief filed for those cases.

This is a separate data source from :mod:`acdocportal_courts_wa_gov`
(which serves per-case document search over the appellate courts' portal).
"""

from __future__ import annotations

from datetime import date

from jkent.common.data_models import ScrapedData

# CourtListener court id -> (internal briefs ``courtId`` URL param, display name).
# Each division has its own URL on the briefs site, so divisions are split
# into distinct ids here even though CourtListener lumps them under
# ``washctapp`` for opinion scraping.
BRIEFS_COURTS: dict[str, tuple[str, str]] = {
    "wash": ("A08", "Washington Supreme Court"),
    "washctappdiv1": (
        "A01",
        "Washington Court of Appeals, Division I",
    ),
    "washctappdiv2": (
        "A02",
        "Washington Court of Appeals, Division II",
    ),
    "washctappdiv3": (
        "A03",
        "Washington Court of Appeals, Division III",
    ),
}


class WaBrief(ScrapedData):
    """A single brief PDF filed in a Washington appellate case."""

    title: str
    """Link text as rendered on the briefs page (e.g.
    ``"Supplemental Brief Petitioner"``, ``"COA Brief of Appellant"``)."""

    url: str
    """Absolute URL to the PDF."""

    local_path: str | None = None
    """Local filesystem path once the archive download completes."""


class WaBriefCase(ScrapedData):
    """A case that has briefs listed for an upcoming scheduled hearing."""

    court_id: str
    """CourtListener court id — one of :data:`BRIEFS_COURTS`' keys."""

    hearing_date: date
    """Scheduled hearing date derived from the page anchor
    (``a<YYYYMMDD>``)."""

    docket_number: str
    """Docket number as shown on the briefs page.  Supreme Court cases
    use a comma-grouped form (e.g. ``"104,170-5"``); Court of Appeals
    cases are plain (e.g. ``"84401-6"``)."""

    case_name: str
    """Case caption as shown next to the docket number."""

    briefs: list[WaBrief] = []
    """All briefs filed for this case at the scheduled hearing."""

    source_url: str | None = None
    """URL of the year page that listed this case."""


class WaDownloadedBrief(ScrapedData):
    """Archive record for a downloaded brief PDF.

    Emitted separately from :class:`WaBriefCase` so archive downloads can
    be joined back in post-processing using
    ``(court_id, docket_number, hearing_date, brief_url)``.
    """

    court_id: str
    docket_number: str
    hearing_date: date
    brief_title: str
    brief_url: str
    local_path: str | None = None
