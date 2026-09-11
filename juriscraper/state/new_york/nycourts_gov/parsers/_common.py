"""Shared helpers for the Court-PASS page parsers."""

from __future__ import annotations

import re
from datetime import date, datetime

#: What Court-PASS prints where it has nothing to print. These are the site's
#: placeholders for absence, not values -- ``Reported Below`` reads ``N/A``
#: (padded with trailing spaces) on the cases the Appellate Division never
#: reported. An affirmative statement the Court makes about a field, such as an
#: Official Citation of ``Withdrawn``, is *not* here: that is the Court's word
#: and belongs in the data.
_SENTINELS = frozenset({"n/a", "n.a.", "na", "none", "-", "--", ""})


def clean_optional(text: str | None) -> str | None:
    """A page value, or ``None`` when the page stated a placeholder.

    Collapses whitespace first, so ``'N/A                      '`` -- the way
    the filing-detail page pads ``Reported Below`` -- reads as the sentinel it
    is.
    """
    if text is None:
        return None
    collapsed = " ".join(text.split())
    if collapsed.casefold() in _SENTINELS:
        return None
    return collapsed


def collapse_ws(text: str | None) -> str | None:
    """Collapse internal whitespace runs to single spaces; ``None`` if empty.

    Court-PASS renders a person's name from fixed first/middle/last slots and
    leaves the run of spaces behind when a slot is blank (``'Frank  Brady
    Esq.'``), so a bare ``.strip()`` carries the page's column layout into the
    data.
    """
    if text is None:
        return None
    return " ".join(text.split()) or None


def collapse_ws_lines(text: str | None) -> str | None:
    """``collapse_ws`` per line, keeping the line breaks.

    For the attorney address, where the newlines separate the address lines the
    page states on separate rows and so carry meaning.
    """
    if text is None:
        return None
    lines = [
        collapsed
        for line in text.split("\n")
        if (collapsed := " ".join(line.split()))
    ]
    return "\n".join(lines) or None


# The FILINGS table appends the filer's side to the party name as a
# single-letter parenthetical -- ``Joseph Scharf (A)``, ``The People (R)``.
# Only these two letters occur (13,495 of 13,535 trailing parentheticals over
# the historical corpus; the other 40 are part of the name -- ``(12 Broadway)``,
# ``(NELA/NY)``, ``(Confidential)``), and the letter agrees with the ATTORNEY
# DETAILS ``Party Role`` on every one of the 6,579 rows where both are stated.
# So it is a role, not a name, and it belongs in its own field: matched
# case-sensitively so a genuine ``(a)`` sub-part marker is left in the name.
_PARTY_SIDE_HINT = re.compile(r"\s*\((A|R)\)\s*$")

#: what the FILINGS table's ``(A)`` / ``(R)`` stands for
PARTY_SIDE_ROLES = {"A": "Appellant", "R": "Respondent"}


def split_party_side(text: str | None) -> tuple[str | None, str | None]:
    """A FILINGS party cell as ``(name, role)``.

    ``'Joseph  Scharf (A)'`` -> ``('Joseph Scharf', 'Appellant')``. The role
    comes back ``None`` when the cell stated no side, which leaves the name
    exactly as ``collapse_ws`` would have given it.
    """
    collapsed = collapse_ws(text)
    if collapsed is None:
        return None, None
    match = _PARTY_SIDE_HINT.search(collapsed)
    if match is None:
        return collapsed, None
    return (
        collapsed[: match.start()].strip() or None,
        PARTY_SIDE_ROLES[match.group(1)],
    )


def _parse_date_mdy(text: str | None) -> date | None:
    """Parse MM/DD/YYYY date strings emitted by Court-PASS."""
    if not text:
        return None
    text = text.strip()
    if not text:
        return None
    try:
        return datetime.strptime(text, "%m/%d/%Y").date()
    except ValueError:
        return None


# Court-PASS occasionally emits a PDF-derived font marker —
# ``<style pdffontname=...>`` with NO closing tag — inside
# ``<p class="case-issues-text">``. lxml treats ``<style>`` as raw text and
# extends it to the document-level ``</style>`` near ``</html>``, swallowing
# the gvFiles table and the "no files" marker into the style element. Dropping
# the bogus open tag (its content is the citation that belongs inline) lets the
# page parse normally, so downstream parsers can assume a clean DOM. Applied
# as the ``@step(preprocess=...)`` hook on the two filing-detail steps.
_PDF_STYLE_RE = re.compile(r"<style[^>]*\bpdffontname\b[^>]*>", re.I)


def repair_pdffont_leakage(text: str) -> str:
    """Strip Court-PASS's unclosed ``<style pdffontname=...>`` font markers."""
    return _PDF_STYLE_RE.sub("", text)


# Court-PASS writes a consolidated caption as several captions separated by a
# horizontal rule, and *escapes* the markup for it -- the Title element's text
# literally contains ``&lt;br /&gt;-------------&lt;br /&gt;``. Unescaped by the
# HTML parse, that reaches the model as a literal ``<br />`` in the case name.
_ESCAPED_BREAK = re.compile(r"<\s*br\s*/?\s*>", re.I)
#: the rule itself, as a run of hyphens or underscores on its own
_CAPTION_RULE = re.compile(r"[-_]{3,}")


def clean_case_title(parts: list[str]) -> str:
    """Join a Title/caption element's text nodes into one case name.

    Folds the escaped ``<br />`` markup and the hyphen rules Court-PASS uses to
    separate the captions of consolidated companion cases into a single ``; ``,
    so the name reads as a caption rather than carrying the page's typography.
    Whitespace, including the newlines the site indents captions with, is
    collapsed.
    """
    joined = " ".join(part.strip() for part in parts if part.strip())
    joined = _ESCAPED_BREAK.sub(" ", joined)
    joined = _CAPTION_RULE.sub(";", joined)
    # a rule sat between two breaks, so the fold above leaves ` ; ` runs, and
    # the caption it ended already carried its own comma
    joined = re.sub(r"\s*(?:[,;]\s*)*;(?:\s*[,;])*\s*", "; ", joined)
    # Court-PASS leaves a doubled comma where a party name is blank
    joined = re.sub(r",\s*,+", ",", joined)
    return re.sub(r"\s+", " ", joined).strip(" ;,")


#: What each ``gvFiles`` download button's ``value`` says about the document
#: behind it. The Court labels the button by what it will hand you rather than
#: leaving the type to be sniffed from the bytes: 15193 ``Download PDF``, 605
#: ``Video`` and 5584 ``Not Available`` over the 5091 filing-detail pages in
#: the 2026-08-22 corpus, with the ``aria-label`` extension agreeing with the
#: label on every single row.
_BUTTON_LABEL_TYPES = {
    "download pdf": "pdf",
    "video": "asx",
}

#: ``aria-label`` reads ``"<button label>: <file name>.<ext>"``. Sealed rows
#: are the only place the extension is not already implied by the label, and
#: they are also the only place it varies (``txt``, ``docx``, ``rtf``).
_ARIA_EXTENSION_RE = re.compile(r"\.([A-Za-z0-9]{1,5})\s*$")


def file_type_from_button(button) -> str | None:
    """The extension a ``gvFiles`` download button states, lowercased.

    Prefers the button's own ``value`` -- ``Download PDF`` and ``Video`` name
    the type unambiguously -- and falls back to the extension in
    ``aria-label``, which is what carries it for ``Not Available`` rows. Both
    are absent only if the Court restyles the grid, in which case this returns
    ``None`` and the caller is no worse off than before it was read.

    :param button: the row's submit input, or ``None`` if it has none
    :return: an extension without its dot, or ``None``
    """
    if button is None:
        return None
    label = (button.get_attribute("value") or "").strip().casefold()
    if label in _BUTTON_LABEL_TYPES:
        return _BUTTON_LABEL_TYPES[label]
    aria = button.get_attribute("aria-label") or ""
    match = _ARIA_EXTENSION_RE.search(aria)
    return match.group(1).lower() if match else None
