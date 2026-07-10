"""Parsers for the ``ncappellatecourts.org/search-results.php`` pages.

Two page-types share the eFiling library's HTML:

- the **date-range listing** (``DocketListingParser``) — repeating
  ``div.docket-{N}`` case-header blocks, one per case touched in the
  window, each with a link to the case's docket sheet; plus the
  ``#pageSelect`` pagination dropdown.
- the **per-case filings** page (``CaseFilingsParser``) — one
  ``div.docket-{N}.border-top`` block per filing (a multi-volume filing
  holds one document row per volume within its block), with the same
  pagination dropdown.

Both parsers keep extraction here; the steps own navigation (per-case
fan-out, pagination, archive downloads) — see ``scraper.py``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

from jkent.common.parser import JKentParser
from jkent.data_types import XPath

from juriscraper.state.north_carolina.ncappellatecourts_org.models import (
    NCAppealsDocument,
)

from ._common import (
    _DOC_ID_RE,
    _ISTART_RE,
    _VOLUME_NUM_RE,
    clean,
    court_from_sheet_url,
    normalize_url,
)

if TYPE_CHECKING:
    from jkent.common.page_element import PageElement


@dataclass
class ListedCase:
    """One unique case extracted from a date-range listing page."""

    docket_number: str
    court: str
    case_name: str
    sheet_url: str


_FILING_TEXT_RE = re.compile(
    r"^(?P<rest>.*?)\s*-\s*Filed By:\s*(?P<filer>.+?)\s+"
    r"(?P<date>\d{4}-\d{2}-\d{2})\s*$",
    re.DOTALL,
)

# The ``Volume N of M`` label a multi-volume filing prints after its type.
_VOLUME_TEXT_RE = re.compile(r"\s*Volume\s+\d+\s+of\s+\d+\s*")


def pagination_offsets(page: PageElement) -> list[int]:
    """Pull every ``iStart=N`` value from the page-select dropdown.

    Shared by both the date-range listing and the per-case filings
    pages — both use the same ``#pageSelect`` dropdown.
    """
    options = page.query_strings(
        XPath("//select[@id='pageSelect']/option/@value"),
        "page-select options",
        min_count=0,
    )
    offsets: set[int] = set()
    for value in options:
        match = _ISTART_RE.search(value)
        if match:
            offsets.add(int(match.group(1)))
    return sorted(offsets)


class DocketListingParser(JKentParser[NCAppealsDocument]):
    """Extract the unique cases from one date-range listing page.

    Returns no models directly (the step turns each ``ListedCase`` into a
    docket-sheet Request); use :meth:`cases` to get the structured
    tuples. ``__call__`` is required by ``JKentParser`` but returns an
    empty list here — the navigation lives in the step.
    """

    def __call__(self, page: PageElement) -> list:  # pragma: no cover
        return []

    def cases(self, page: PageElement, court_sc: str, court_coa: str) -> list:
        """Return the unique cases on this listing page as
        :class:`ListedCase` records."""
        case_blocks = page.query(
            XPath(
                "//div["
                "contains(@class, 'docket-')"
                " and contains(@class, 'pt-2')"
                " and not(contains(@class, 'border-top'))"
                "]"
            ),
            "case header blocks",
            min_count=0,
        )
        out: list[ListedCase] = []
        seen_dockets: set[str] = set()
        for block in case_blocks:
            # The heading is ``{docket} : {caption}``. A caption may wrap
            # across several ``<br>``-separated lines (the full party block:
            # ``MARC HUBBARD,`` / ``Plaintiff-Appellant`` / ``v.`` / …), so
            # read the whole ``h4``'s text and collapse it to one line rather
            # than picking a single text node.
            heading_elems = block.query(
                XPath(".//h4"),
                "case heading",
                min_count=0,
                max_count=1,
            )
            heading = (
                clean(heading_elems[0].text_content())
                if heading_elems
                else None
            )
            if not heading:
                continue
            docket_number, _, case_name = heading.partition(" : ")
            docket_number = clean(docket_number) or ""
            case_name = clean(case_name) or ""
            if not docket_number or docket_number in seen_dockets:
                continue
            sheet_hrefs = block.query_strings(
                XPath(".//a[contains(@href, 'pdf=1')]/@href"),
                "docket sheet link",
                min_count=0,
                max_count=1,
            )
            if not sheet_hrefs:
                continue
            seen_dockets.add(docket_number)
            sheet_url = normalize_url(sheet_hrefs[0])
            out.append(
                ListedCase(
                    docket_number=docket_number,
                    court=court_from_sheet_url(sheet_url, court_sc, court_coa),
                    case_name=case_name,
                    sheet_url=sheet_url,
                )
            )
        return out


class CaseFilingsParser(JKentParser[NCAppealsDocument]):
    """Extract the e-filing rows from one per-case filings page.

    Returns one fully-built (non-deferred) :class:`NCAppealsDocument`
    per filing row; the step decides whether to archive the PDF or yield
    the (sealed) row directly. ``__call__`` returns an empty list; use
    :meth:`documents`.
    """

    def __call__(self, page: PageElement) -> list:  # pragma: no cover
        return []

    def documents(
        self, page: PageElement, docket_number: str, court: str
    ) -> list[NCAppealsDocument]:
        """Return one ``NCAppealsDocument`` per filing row on the page.

        Each ``border-top`` block is one *filing*, but a filing can hold
        several document rows: a multi-volume record renders one
        ``<a show-file.php…&volume_number=N>`` row per volume, all inside
        a single block. We therefore descend to the per-row ``div`` under
        the block's ``col-12`` wrapper and parse each independently — one
        ``NCAppealsDocument`` per row. Rows that carry no filing text
        (the trailing spacer, the "Additional filings included within
        this document" note) parse to ``None`` and are skipped.
        """
        filing_blocks = page.query(
            XPath(
                "//div["
                "contains(@class, 'docket-')"
                " and contains(@class, 'border-top')"
                " and contains(@class, 'pt-2')"
                "]"
            ),
            "filing blocks",
            min_count=0,
        )
        out: list[NCAppealsDocument] = []
        for block in filing_blocks:
            rows = block.query(
                XPath(".//div[contains(@class, 'col-12')]/div"),
                "filing rows",
                min_count=0,
            )
            for row in rows:
                doc = self._parse_filing_block(row, docket_number, court)
                if doc is not None:
                    out.append(doc)
        return out

    @classmethod
    def _parse_filing_block(
        cls, row: PageElement, docket_number: str, court: str
    ) -> NCAppealsDocument | None:
        """Extract one filing's metadata + URL from a single document row.

        Returns ``None`` for rows that don't represent a filing (e.g.
        the trailing spacer, or the "Additional filings included within
        this document" note that lists bundled sub-filings with no
        download links of their own).
        """
        # Combined text content drives type / filer / date parsing. A
        # trailing ``(Sealed)`` marker is split off before the regex
        # runs; we record it as a flag rather than letting it fall into
        # the date-anchored regex.
        body = clean(row.text_content()) or ""
        is_sealed = False
        if body.endswith("(Sealed)"):
            is_sealed = True
            body = body[: -len("(Sealed)")].strip()

        match = _FILING_TEXT_RE.match(body)
        if not match:
            return None
        # A multi-volume filing renders ``Type ( subtype )Volume N of M``
        # (the ``<br>`` between them collapses to nothing in text), so
        # drop the volume label before splitting the type. The volume is
        # preserved on ``document_id`` / ``document_url`` below.
        type_subtype = _VOLUME_TEXT_RE.sub(
            "", clean(match.group("rest")) or ""
        )
        document_type, subtype = cls._split_type_subtype(type_subtype)
        filer = clean(match.group("filer"))
        try:
            filed = datetime.strptime(match.group("date"), "%Y-%m-%d").date()
        except ValueError:
            filed = None

        href_values = row.query_strings(
            XPath(".//a[contains(@href, 'show-file.php')]/@href"),
            "show-file href",
            min_count=0,
            max_count=1,
        )

        document_url: str | None = None
        document_id: str | None = None
        if href_values:
            document_url = normalize_url(href_values[0])
            id_match = _DOC_ID_RE.search(document_url)
            if id_match:
                document_id = id_match.group(1)
                # Volumes of one filing share a ``document_id`` but differ
                # by ``volume_number`` — fold the volume in so each volume
                # keeps a distinct id (and a distinct archive dedup key).
                vol_match = _VOLUME_NUM_RE.search(document_url)
                if vol_match:
                    document_id = f"{document_id}-{vol_match.group(1)}"

        return NCAppealsDocument(
            docket_number=docket_number,
            court=court,
            document_type=document_type,
            document_subtype=subtype,
            filer=filer,
            date_filed=filed,
            is_sealed=is_sealed,
            document_id=document_id,
            document_url=document_url,
        )

    @staticmethod
    def _split_type_subtype(text: str) -> tuple[str, str | None]:
        """Split ``Type ( subtype )`` allowing nested parens in subtype.

        The site renders sub-type text like ``record (printed)``, so we
        can't rely on a non-greedy ``[^)]*`` match. Instead, slice on the
        *first* ``(`` and the *last* ``)`` — the outer pair always frames
        the subtype, even when it contains its own parens.
        """
        if "(" not in text or not text.rstrip().endswith(")"):
            return text.strip(), None
        head, _, tail = text.partition("(")
        inner = tail.rstrip()[:-1]  # drop trailing ')'
        return head.strip(), clean(inner) or None
