"""Shared helpers for the California appellate-courts page parsers."""

from __future__ import annotations

import re
from datetime import date
from typing import TYPE_CHECKING

from jkent.data_types import XPath

if TYPE_CHECKING:
    from jkent.common.page_element import PageElement

DefinitionPair = tuple["PageElement", "PageElement | None"]

#: The division line in the banner every case tab renders above its content.
_DIVISION_LINE = re.compile(r"^Division\s+(\S+)$")

#: The banner's other constant line, which labels the case-number link.
_CASE_NUMBER_LABEL = "Case Number"


def parse_date(text: str | None) -> date | None:
    """Parse an mm/dd/yyyy date string, returning None for empty/invalid."""
    if text is None:
        return None
    text = text.strip()
    if not text:
        return None
    m = re.match(r"(\d{2})/(\d{2})/(\d{4})", text)
    if not m:
        return None
    return date(int(m.group(3)), int(m.group(1)), int(m.group(2)))


def clean_text(text: str | None) -> str | None:
    """Strip and return None for empty strings."""
    if text is None:
        return None
    text = text.strip()
    return text if text else None


# Placeholders the site prints in a value slot to mean "nothing here". Stored
# verbatim they read as data: a case citation of "none" looks like a citation.
_ABSENT_VALUES = {"none", "no data found", "n/a"}


def clean_optional(text: str | None) -> str | None:
    """Like :func:`clean_text`, but also treat the site's placeholders as absent.

    The Supreme Court summary prints ``none`` in the Case Citation slot when a
    case has no citation -- on 294,221 of 296,617 dockets in a full sweep, i.e.
    99.2% of them. Passing that through would hand a consumer the string "none"
    where it expects a citation.
    """
    cleaned = clean_text(text)
    if cleaned is None or cleaned.lower() in _ABSENT_VALUES:
        return None
    return cleaned


def cell_lines(element: PageElement | None) -> list[str]:
    """Read an element's ``<br>``-separated lines.

    ``text_content()`` drops ``<br>`` entirely, gluing the lines it separated
    into one run ("Fresno County Superior Court - Main3237203"). Collecting
    the text nodes individually keeps the boundaries.
    """
    if element is None:
        return []
    return [
        line
        for text in element.query_strings(
            XPath(".//text()"), "element lines", min_count=0
        )
        if (line := " ".join(text.split()))
    ]


def tab_header(page: PageElement) -> tuple[str | None, str | None]:
    """Read the ``(case_name, division)`` banner that every case tab renders.

    Each tab (Docket, Briefs, Disposition, Parties, Trial Court) repeats a
    two-line banner above its content: the case caption, then ``Division X``.
    It is the *only* place the division appears on a Supreme Court case --
    the SC summary ``<dl>`` has no Division term at all, so ``division`` was
    null on all 302,103 SC dockets of a full sweep while every tab page was
    printing "Division SF" (or LA/SD/SA/FR, the court's sitting location).

    Reading it here also consumes the banner, which is otherwise the single
    largest residual cluster on every non-summary tab.
    """
    lines = page.query_strings(
        XPath("//div[contains(@class, 'fw-bold')]/text()"),
        "case tab header lines",
        min_count=0,
    )
    case_name: str | None = None
    division: str | None = None
    for raw in lines:
        line = " ".join(raw.split())
        if not line or line == _CASE_NUMBER_LABEL:
            continue
        if match := _DIVISION_LINE.match(line):
            division = match.group(1)
        elif case_name is None:
            case_name = line
    return case_name, division


def definition_list_pairs(page: PageElement) -> list[DefinitionPair]:
    """Pair up every ``<dl>``'s terms and values in document order.

    The site renders case metadata as a ``<dl>`` of ``<dt>`` terms and ``<dd>``
    values, but the two are **not** always balanced, so they cannot be read as
    parallel lists and zipped: a Supreme Court summary ends with a ``<dt>``
    holding the "NOTE:" disclaimer and a bare ``<dt>Cross Referenced Cases:</dt>``
    label, neither of which has a ``<dd>``. Zipping shifts every later value
    onto the wrong term.

    Measured against a full sweep of both a Supreme Court and a Third District
    run, zipping differed from correct pairing on 9,881 pages -- all Supreme
    Court summaries, and in every case only inside the cross-referenced-cases
    block, where each caption landed on the *previous* case. No field any parser
    read was ever wrong (the unbalanced terms trail them all), but reading that
    block at all requires pairing this way. Third District pages and the Lower
    Court tab were unaffected: perfectly balanced, or unbalanced only by a
    trailing ``<dt>`` that ``zip`` merely truncated.

    So each ``<dt>`` is paired with the ``<dd>`` that *immediately* follows it,
    and with ``None`` when the next sibling is another ``<dt>``. Walking each
    ``<dl>``'s children separately also keeps a trailing ``<dt>`` in one list
    from pairing with a leading ``<dd>`` in the next.

    Returns the ``(term_element, value_element_or_None)`` pairs — elements, not
    text, because callers also need to read links out of both sides.
    """
    pairs: list[DefinitionPair] = []
    for dl in page.query(XPath("//dl"), "definition lists", min_count=0):
        children = dl.query(
            XPath("*"), "definition list children", min_count=0
        )
        for i, child in enumerate(children):
            if child.tag_name() != "dt":
                continue
            following = children[i + 1] if i + 1 < len(children) else None
            pairs.append(
                (
                    child,
                    following
                    if following is not None and following.tag_name() == "dd"
                    else None,
                )
            )
    return pairs


def definition_term(dt_el: PageElement) -> str:
    """Read a ``<dt>``'s label, without its trailing colon."""
    return dt_el.text_content().strip().rstrip(":")


def fields_from_definition_list(
    pairs: list[DefinitionPair],
) -> dict[str, str]:
    """Build a ``{term: value}`` dict from :func:`definition_list_pairs`.

    Terms with no ``<dd>`` are left out entirely rather than mapped to a
    neighbour's value.
    """
    return {
        definition_term(dt_el): dd_el.text_content().strip()
        for dt_el, dd_el in pairs
        if dd_el is not None
    }
