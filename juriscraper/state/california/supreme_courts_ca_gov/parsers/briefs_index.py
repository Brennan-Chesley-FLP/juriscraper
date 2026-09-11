"""Parser for the briefs index at ``/case-information/briefs-argued-cases``.

The index is one Drupal accordion, one panel per year ("Current Year", then
2025 down to 2010), each holding a link per oral argument session. The link
text carries the session's dates -- which is the whole of the site's
date addressing: there is no date search, so the scraper reads the span out
of every link and fetches only the session pages that overlap its window.

The panel headings are deliberately ignored. They restate the year already in
each link, and the first one reads "Current Year" rather than a year at all.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from jkent.common.parser import JKentParser
from jkent.data_types import XPath

from juriscraper.state.california.supreme_courts_ca_gov.models import (
    CalSupremeArgumentSession,
)

from ._common import collapse_ws, parse_session_title

if TYPE_CHECKING:
    from jkent.common.deferred_validation import DeferredValidation
    from jkent.common.page_element import PageElement

#: Every session link on the index, in document order (newest first). Matched
#: by href prefix rather than by accordion structure: the same links are the
#: only ones on the page that point one level below the index itself.
_SESSION_LINKS = XPath(
    "//a[contains(@href, '/case-information/briefs-argued-cases/')]"
)


class BriefsIndexParser(JKentParser[CalSupremeArgumentSession]):
    """Parse the briefs index into one record per oral argument session.

    Returns the sessions in the order the page lists them (newest first),
    each carrying the URL of its own briefs page. A link whose text states no
    parseable date span is skipped rather than emitted dateless -- the step
    counts what came back and fails the page if the count collapses.
    """

    def __call__(
        self, page: PageElement
    ) -> list[DeferredValidation[CalSupremeArgumentSession]]:
        links = page.find_links(
            _SESSION_LINKS, "oral argument session links", min_count=1
        )

        sessions: list[DeferredValidation[CalSupremeArgumentSession]] = []
        seen: set[str] = set()
        for link in links:
            title = collapse_ws(link.text)
            if title is None or link.url in seen:
                continue
            span = parse_session_title(title)
            if span is None:
                continue
            seen.add(link.url)
            start, end, kind = span
            sessions.append(
                CalSupremeArgumentSession.raw(
                    court="cal",
                    session_title=title,
                    date_session_start=start,
                    date_session_end=end,
                    session_type=kind,
                    source_url=link.url,
                )
            )
        return sessions
