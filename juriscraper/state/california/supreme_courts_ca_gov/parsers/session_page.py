"""Parser for one oral argument session's briefs page.

Nearly every case on a session page is rendered by the same Drupal view: a
flat run of siblings -- an ``<h2>`` per case, an optional ``<p>`` note, then
an ``<ol>`` of brief links -- repeated for every case argued that session.
Nothing is nested, so each case is read by walking forward from its heading
to the next one.

Six pages in the 2010-2026 corpus also carry a hand-authored body section
built from a ``<header class="jcc-section-heading">`` instead. Three of those
are genuine cases the editor added by hand (S105876, S130263, S198132 -- each
the last case on its page, and each with links pointing at the court's
Pantheon staging host); the other three hold a "Special Note:" naming the
venue of a special session, which carries no case and is skipped. Both shapes
are read, so no case is lost to which template rendered it.

The page's own ``<h1>`` states the session title, which is where the argument
dates come from; the parser reads it rather than taking the dates on trust
from the index link that led here.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from jkent.common.parser import JKentParser
from jkent.data_types import XPath

from juriscraper.state.california.supreme_courts_ca_gov.models import (
    CalSupremeBriefCase,
    CalSupremeSessionType,
)

from ._common import (
    canonical_brief_url,
    collapse_ws,
    consolidated_case_numbers,
    court_for_docket_number,
    docket_number_from_filename,
    filename_from_url,
    parse_filed_on,
    parse_session_title,
    split_brief_title,
    split_case_heading,
)

if TYPE_CHECKING:
    from jkent.common.deferred_validation import DeferredValidation
    from jkent.common.page_element import PageElement

#: The session title, in the page hero.
_PAGE_TITLE = XPath("//h1[contains(@class, 'jcc-hero__main-title')]")

#: The one element that holds every case the Drupal view rendered. Its
#: children are the flat run of ``<h2>`` / ``<p>`` / ``<div class="jcc-list">``
#: the cases are built from; scoping to it keeps the site's chrome headings
#: from being mistaken for cases.
_VIEW_CASE_CONTAINER = XPath(
    "//div[contains(@class, 'views-element-container')]"
    "//div[contains(@class, 'jcc-section__inner')][h2]"
)

#: The container's children, in document order -- which is the only thing
#: that says which note and which list belong to which heading, since the
#: view nests nothing. A case may carry more than one note (the February 4
#: 2026 consolidated pair state both the consolidation and the pro tempore
#: assignment), so the walk collects every ``<p>`` up to the next heading
#: rather than the first one.
_VIEW_BLOCK_CHILDREN = XPath("*")

#: A hand-authored case block: the whole ``jcc-body__main`` that holds the
#: heading, its lead note, and its brief list.
_BODY_BLOCKS = XPath(
    "//div[contains(@class, 'jcc-body__main')]"
    "[.//header[contains(@class, 'jcc-section-heading')]//h2]"
)
_BODY_HEADING = XPath(".//header[contains(@class, 'jcc-section-heading')]//h2")
_BODY_NOTE = XPath(".//div[contains(@class, 'jcc-section-heading__lead')]")
_BODY_BRIEF_LIST = XPath(".//div[contains(@class, 'jcc-body__main-text')]")

#: One list item per brief, in either shape. The view's items carry a
#: ``jcc-list__item`` class and the hand-authored ones do not, so the class
#: is deliberately not required.
_BRIEF_ITEMS = XPath(".//li")

#: The PDF link inside a list item.
_BRIEF_LINK = XPath(".//a[@href]")

#: Every text node under an element. Headings and notes are read through this
#: rather than through ``text_content()`` so the selector observer sees the
#: text being consumed: an element that is *also* queried on -- as a case
#: heading is, for its sibling note and brief list -- counts as a scoping
#: container, and a container's own text is never marked consumed.
_OWN_TEXT = XPath(".//text()")


def _text_of(element: PageElement, description: str) -> str | None:
    """The visible text of ``element``, whitespace-collapsed."""
    return collapse_ws(
        " ".join(element.query_strings(_OWN_TEXT, description, min_count=0))
    )


class SessionPageParser(JKentParser[CalSupremeBriefCase]):
    """Parse a session page into one ``CalSupremeBriefCase`` per case.

    Every field is taken from this page alone: the session title and dates
    from the ``<h1>``, the case number and caption from the case heading, the
    note beneath it, and the briefs from the list that follows. The calling
    step adds only ``source_url`` and ``source_entry_point`` and fans out the
    downloads.

    A heading that states no case number falls back to the number the court
    built its brief filenames around -- the corpus's one ``"NO CASE
    ASSIGNED"`` heading sits over five files all named for S198132. A heading
    that yields no number either way is skipped: it is not a case (the
    "Special Note:" venue headings are the corpus's only instances), and
    without a number the record could be joined to nothing.
    """

    def __call__(
        self, page: PageElement
    ) -> list[DeferredValidation[CalSupremeBriefCase]]:
        session_title = collapse_ws(
            page.query(_PAGE_TITLE, "session title", min_count=1, max_count=1)[
                0
            ].text_content()
        )
        span = parse_session_title(session_title or "")
        if span is None:
            start = end = None
            kind = CalSupremeSessionType.REGULAR
        else:
            start, end, kind = span

        blocks: list[tuple[str, str | None, list[dict]]] = [
            *self._view_blocks(page),
            *self._body_blocks(page),
        ]

        cases: list[DeferredValidation[CalSupremeBriefCase]] = []
        for heading_raw, note, briefs in blocks:
            docket_number, case_name = split_case_heading(heading_raw)
            if docket_number is None:
                docket_number = next(
                    (
                        recovered
                        for brief in briefs
                        if brief["filename"]
                        and (
                            recovered := docket_number_from_filename(
                                brief["filename"]
                            )
                        )
                    ),
                    None,
                )
                if docket_number is None:
                    continue

            cases.append(
                CalSupremeBriefCase.raw(
                    court=court_for_docket_number(docket_number),
                    docket_number=docket_number,
                    case_name=case_name,
                    heading_raw=heading_raw,
                    date_argued=start if start == end else None,
                    date_session_start=start,
                    date_session_end=end,
                    session_title=session_title,
                    session_type=kind,
                    notes=note,
                    consolidated_with=consolidated_case_numbers(
                        note, docket_number
                    ),
                    briefs=briefs,
                )
            )
        return cases

    def _view_blocks(
        self, page: PageElement
    ) -> list[tuple[str, str | None, list[dict]]]:
        """The case blocks the Drupal view renders, in document order.

        The view emits one flat run of siblings for the whole session, so a
        case is everything between its heading and the next one: its notes
        (there may be several) and its brief list.
        """
        blocks: list[tuple[str, str | None, list[dict]]] = []
        for container in page.query(
            _VIEW_CASE_CONTAINER, "view case container", min_count=0
        ):
            # (heading, notes, briefs) per case, the notes and briefs filled
            # in as the walk passes them. A heading with no text still opens
            # a case, so what follows it cannot leak into the case above; the
            # empty ones are dropped at the end.
            pending: list[tuple[str, list[str], list[dict]]] = []
            for child in container.query(
                _VIEW_BLOCK_CHILDREN, "case block elements", min_count=1
            ):
                tag = child.tag_name()
                if tag == "h2":
                    heading = _text_of(child, "view case heading text")
                    pending.append((heading or "", [], []))
                    continue
                if not pending:
                    continue
                _, notes, briefs = pending[-1]
                if tag == "p":
                    note = _text_of(child, "view case note text")
                    if note:
                        notes.append(note)
                elif tag == "div" and "jcc-list" in (
                    child.get_attribute("class") or ""
                ):
                    briefs.extend(self._briefs(child))
            blocks.extend(
                (heading, " ".join(notes) or None, briefs)
                for heading, notes, briefs in pending
                if heading
            )
        return blocks

    def _body_blocks(
        self, page: PageElement
    ) -> list[tuple[str, str | None, list[dict]]]:
        """The hand-authored case blocks, in document order.

        Everything a block owns is nested inside it, so unlike the view's
        flat siblings these need no lookahead to the next heading.
        """
        blocks: list[tuple[str, str | None, list[dict]]] = []
        for block in page.query(
            _BODY_BLOCKS, "hand-authored case blocks", min_count=0
        ):
            headings = block.query(
                _BODY_HEADING, "block heading", min_count=1, max_count=1
            )
            heading_raw = _text_of(headings[0], "block heading text")
            if heading_raw is None:
                continue
            notes = block.query(
                _BODY_NOTE, "block note", min_count=0, max_count=1
            )
            lists = block.query(
                _BODY_BRIEF_LIST, "block brief list", min_count=0, max_count=1
            )
            blocks.append(
                (
                    heading_raw,
                    _text_of(notes[0], "block note text") if notes else None,
                    self._briefs(lists[0]) if lists else [],
                )
            )
        return blocks

    def _briefs(self, brief_list: PageElement) -> list[dict]:
        """The briefs in one case's list, in the order the court listed them.

        Returned as plain dicts so the whole case validates in one deferred
        pass, and so the calling step can read each brief's URL to fan out
        the downloads.
        """
        briefs: list[dict] = []
        for position, item in enumerate(
            brief_list.query(_BRIEF_ITEMS, "brief list items", min_count=0),
            start=1,
        ):
            links = item.find_links(
                _BRIEF_LINK, "brief link", min_count=0, max_count=1
            )
            description = collapse_ws(
                links[0].text
                if links
                else _text_of(item, "unlinked brief text")
            )
            url = canonical_brief_url(links[0].url) if links else None
            filed_by, document_type = split_brief_title(description or "")
            briefs.append(
                {
                    "document_number": position,
                    "description": description,
                    "document_type": document_type,
                    "filed_by": filed_by,
                    "date_filed": parse_filed_on(
                        _text_of(item, "brief filing date") or ""
                    ),
                    "url": url,
                    "filename": filename_from_url(url) if url else None,
                }
            )
        return briefs
