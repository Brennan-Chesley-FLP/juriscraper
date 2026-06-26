"""Parser for one Washington appellate-briefs year page.

The briefs site (``/appellate_trial_courts/coaBriefs/``) renders, per
year, every scheduled hearing date plus the cases and briefs scheduled on
it. The server HTML is mildly malformed — ``<a name>`` anchors wrap block
elements — so sibling/ancestor XPath relationships are unreliable and the
page must be read in **document order** to attach hearing dates → cases →
briefs.

We stay on the public ``PageElement`` API (§9): read ``td.mainPage``'s
``inner_html()`` and recover document order with a small stdlib
``HTMLParser`` over that markup, rather than reaching into ``._element``.
The parser groups briefs by ``(hearing_date, docket_number, case_name)``
and returns one :class:`WaBriefCase` per group; the calling step applies
the hearing-date window filter and resolves the brief URLs against the
page URL.
"""

from __future__ import annotations

from datetime import date
from html.parser import HTMLParser
from typing import TYPE_CHECKING

from jkent.common.parser import JKentParser
from jkent.data_types import XPath

from juriscraper.state.washington.courts_wa_gov.models import WaBriefCase

from ._common import (
    CASE_TEXT_RE,
    EMPTY_YEAR_TEXT,
    HEARING_ANCHOR_RE,
    collapse_ws,
)

if TYPE_CHECKING:
    from jkent.common.deferred_validation import DeferredValidation
    from jkent.common.page_element import PageElement


class _YearPageWalker(HTMLParser):
    """Recover document order from the ``td.mainPage`` inner markup.

    Tracks the current ``a<YYYYMMDD>`` hearing-date anchor and the current
    case ``<li>``, attaching brief PDF links to the current case as they
    appear. A case-header ``<li>`` has no descendant ``<a>`` and matches
    ``"<docket> - <case name>"``; a brief ``<li>`` carries an ``<a>`` whose
    ``href`` ends in ``.pdf``.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.cases: list[dict] = []
        self._cur_hearing_date: date | None = None
        self._cur_case: dict | None = None

        # LI accumulation state.
        self._in_li = False
        self._li_text_parts: list[str] = []
        self._li_links: list[dict] = []  # {"href", "text_parts"}
        self._cur_link: dict | None = None

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        attr = dict(attrs)
        if tag == "a":
            name = attr.get("name") or ""
            m = HEARING_ANCHOR_RE.match(name)
            if m:
                self._cur_hearing_date = date(
                    int(m.group(1)), int(m.group(2)), int(m.group(3))
                )
                self._cur_case = None
            if self._in_li:
                self._cur_link = {
                    "href": attr.get("href") or "",
                    "text_parts": [],
                }
        elif tag == "li":
            self._in_li = True
            self._li_text_parts = []
            self._li_links = []
            self._cur_link = None

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._cur_link is not None:
            self._li_links.append(self._cur_link)
            self._cur_link = None
        elif tag == "li":
            self._finish_li()
            self._in_li = False

    def handle_data(self, data: str) -> None:
        if not self._in_li:
            return
        if self._cur_link is not None:
            self._cur_link["text_parts"].append(data)
        else:
            self._li_text_parts.append(data)

    def _finish_li(self) -> None:
        pdf_link = next(
            (
                link
                for link in self._li_links
                if ".pdf" in (link["href"] or "").lower()
            ),
            None,
        )
        if pdf_link is not None:
            # Brief LI: attach to the current case.
            if self._cur_case is not None:
                self._cur_case["briefs"].append(
                    {
                        "title": collapse_ws("".join(pdf_link["text_parts"])),
                        "url": pdf_link["href"],
                    }
                )
            return

        if self._li_links:
            # Has non-PDF links — not a case header.
            return

        text = collapse_ws("".join(self._li_text_parts))
        m = CASE_TEXT_RE.match(text)
        if m is not None and self._cur_hearing_date is not None:
            self._cur_case = {
                "hearing_date": self._cur_hearing_date,
                "docket": m.group(1).strip(),
                "case_name": m.group(2).strip(),
                "briefs": [],
            }
            self.cases.append(self._cur_case)


class BriefsPageParser(JKentParser[WaBriefCase]):
    """Parse a briefs year page into ``WaBriefCase`` records.

    Returns one ``WaBriefCase`` per ``(hearing_date, docket, case_name)``
    group, in document order. Brief URLs are left as the raw ``href`` on
    each case's ``briefs`` list (relative to the page) for the step to
    resolve and window-filter; ``court_id``/``source_url`` are stamped by
    the step. An empty-year page (Div III before 2008, future gaps)
    returns ``[]``.
    """

    def __call__(
        self, page: PageElement
    ) -> list[DeferredValidation[WaBriefCase]]:
        # The parser's groups carry richer per-brief data than the
        # WaBriefCase model alone, so the step calls walk_groups directly;
        # __call__ exists to satisfy the JKentParser contract and to make
        # the offline-testable shape (from_string/from_file) available.
        groups = self.walk_groups(page)
        out: list[DeferredValidation[WaBriefCase]] = []
        for g in groups:
            out.append(
                WaBriefCase.raw(
                    hearing_date=g["hearing_date"],
                    docket_number=g["docket"],
                    case_name=g["case_name"],
                )
            )
        return out

    def walk_groups(self, page: PageElement) -> list[dict]:
        """Return the raw case groups (with brief href/title) for the step.

        Each group is ``{"hearing_date", "docket", "case_name",
        "briefs": [{"title", "url"}]}``. Returns ``[]`` for an empty-year
        page or when the main container is missing.
        """
        empty_markers = page.query(
            XPath(f"//*[contains(text(), {EMPTY_YEAR_TEXT!r})]"),
            "no-briefs-found marker",
            min_count=0,
            max_count=1,
        )
        if empty_markers:
            return []

        main_pes = page.query(
            XPath("//td[@class='mainPage']"),
            "main page container",
            min_count=0,
            max_count=1,
        )
        if not main_pes:
            return []

        walker = _YearPageWalker()
        walker.feed(main_pes[0].inner_html())
        walker.close()
        return walker.cases
