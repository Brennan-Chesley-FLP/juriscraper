"""Parser for the Parties and Attorneys tab (``parse_parties``)."""

from __future__ import annotations

import re
from html import unescape
from typing import TYPE_CHECKING

from jkent.common.deferred_validation import DeferredValidation
from jkent.common.parser import JKentParser
from jkent.data_types import XPath

from juriscraper.state.california.appellatecases_courtinfo_ca_gov.models import (
    CaAppParty,
)

from ._common import clean_text

if TYPE_CHECKING:
    from jkent.common.page_element import PageElement

# The template labels every field in a cell with an HTML comment
# (``<!-- attorney name -->``, ``<!-- attorney firm -->``, ...). These are the
# only reliable field boundaries -- see ``_parse_attorney_cell``.
_FIELD_MARKER = re.compile(
    r"<!--\s*(party|attorney)\s+(name|firm|address)\s*-->", re.IGNORECASE
)
_BREAK = re.compile(r"<br\s*/?>", re.IGNORECASE)
_TAG = re.compile(r"<[^>]*>")

# Control bytes the site emits inside otherwise ordinary text, standing in for
# punctuation it failed to encode: "El Dorado County Sheriff\x19s Department",
# "Sheriff's Office \x13 Auburn Jail". Dropped rather than guessed at -- \x19 is
# an apostrophe and \x13 a dash, but substituting either would be inventing
# characters the source does not contain.
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

# The one thing an Attorney cell says instead of naming an attorney. It carries
# no field markers, because there is no field -- surveyed over 2,500 pages, it
# is the *only* marker-less content such a cell ever holds.
_PRO_PER = "pro per"


class PartiesParser(JKentParser[CaAppParty]):
    """Parse the Party / Attorney table into one ``CaAppParty`` per row.

    One party per row -- the party cell never lists more than one, unlike the
    Briefs tab's "Party and Attorney" cell. The *attorney* cell does: it holds
    one name/firm/address block per attorney representing that party.
    """

    def __call__(
        self, page: PageElement
    ) -> list[DeferredValidation[CaAppParty]]:
        rows = page.query(
            XPath("//table//tbody//tr"), "party rows", min_count=0
        )
        parties: list[DeferredValidation[CaAppParty]] = []
        for row in rows:
            cells = row.query(XPath("td"), "party cells", min_count=0)
            if len(cells) < 2:
                continue

            name, role, address_lines = self._parse_party_cell(cells[0])
            attorneys, pro_per = self._parse_attorney_cell(cells[1])
            if not attorneys and not pro_per and self._cell_lines(cells[1]):
                # Text that is neither a field marker nor "Pro Per": the
                # template changed. Re-query so the failure carries the selector
                # rather than silently dropping every attorney on the page.
                page.query(
                    XPath('//comment()[contains(., "attorney name")]'),
                    "attorney field markers",
                    min_count=1,
                )

            parties.append(
                CaAppParty.raw(
                    name=name,
                    role=clean_text(role),
                    address=(
                        ", ".join(address_lines) if address_lines else None
                    ),
                    attorneys=attorneys,
                    pro_per=pro_per,
                )
            )
        return parties

    @classmethod
    def _cell_lines(cls, cell: PageElement) -> list[str]:
        """Read a cell's ``<br>``-separated lines, comments stripped."""
        return cls._chunk_lines(_FIELD_MARKER.sub("", cell.inner_html()))

    @staticmethod
    def _chunk_lines(chunk: str) -> list[str]:
        """Split a run of cell HTML into its ``<br>``-separated text lines.

        ``text_content()`` cannot be used for this: it drops ``<br>``, gluing
        the lines it separated into one run. Only ``<br>`` ever appears inside
        these cells (surveyed over 2,166 of them), but any residual tag is
        stripped rather than trusted not to exist.
        """
        return [
            line
            for part in _BREAK.split(chunk)
            if (
                line := " ".join(
                    _CONTROL.sub("", unescape(_TAG.sub("", part))).split()
                )
            )
        ]

    @classmethod
    def _segments(cls, cell: PageElement) -> list[tuple[str, list[str]]]:
        """Split a cell into ``(field_name, lines)`` runs, split on its markers.

        ``field_name`` is the marker's second word — "name", "firm" or
        "address". Text before the first marker is dropped: the template always
        opens a populated cell with one.
        """
        html = cell.inner_html()
        segments: list[tuple[str, list[str]]] = []
        for match, next_match in zip(
            (matches := list(_FIELD_MARKER.finditer(html))),
            [*matches[1:], None],
        ):
            end = next_match.start() if next_match else len(html)
            segments.append(
                (
                    match.group(2).lower(),
                    cls._chunk_lines(html[match.end() : end]),
                )
            )
        return segments

    @classmethod
    def _parse_party_cell(
        cls, cell: PageElement
    ) -> tuple[str, str | None, list[str]]:
        """Split a party cell into (name, role, address_lines).

        The ``party name`` run is a single ``"Name : Role"`` line (or just
        ``"Name"``); the ``party address`` run holds the address.
        """
        name_lines: list[str] = []
        address_lines: list[str] = []
        for field, lines in cls._segments(cell):
            if field == "name":
                name_lines += lines
            else:
                address_lines += lines
        if not name_lines:
            # No markers at all (or an empty cell) -- fall back to reading the
            # cell whole, so a party is still recorded.
            name_lines = cls._cell_lines(cell)
        if not name_lines:
            return "", None, []
        first, *extra = name_lines
        name, sep, role = first.partition(" : ")
        return (
            name.strip(),
            (role.strip() if sep else None),
            extra + address_lines,
        )

    @classmethod
    def _parse_attorney_cell(
        cls, cell: PageElement
    ) -> tuple[list[dict], bool]:
        """Split an attorney cell into ``(attorneys, pro_per)``.

        A single cell routinely names several attorneys -- C094616 credits
        three to "The People" -- so the field markers are what make the cell
        representable. Reading it positionally (line 1 name, line 2 firm, rest
        address) collapsed every such cell into one record and buried the other
        attorneys in its ``address``: 18,429 attorney records across the Third
        District held two or more attorneys' details mashed together.

        The markers also fix the name/firm split. ``<!-- attorney firm -->`` is
        emitted even for an attorney that has no firm line, so the positional
        read shifted the first address line into ``firm`` on 62,672 of 243,473
        records ("Office of the State Attorney General" / firm "1515 K Street -
        Suite 5").

        A ``name`` marker opens a new attorney; ``firm`` and ``address`` attach
        to the one most recently opened. A self-represented party's cell carries
        no markers at all, just "Pro Per" -- that returns no attorney and sets
        the flag, where reading it positionally invented an attorney *named*
        "Pro Per" (34,780 of the Third District's party rows).
        """
        attorneys: list[dict] = []
        pro_per = False
        for field, lines in cls._segments(cell):
            if field == "name":
                if not lines:
                    # An empty cell still carries the marker triple.
                    continue
                first, *extra = lines
                if first.lower() == _PRO_PER:
                    pro_per = True
                    continue
                attorneys.append(
                    {"name": first, "firm": None, "address": extra or None}
                )
                continue
            if not attorneys or not lines:
                continue
            if field == "firm" and attorneys[-1]["firm"] is None:
                attorneys[-1]["firm"] = " ".join(lines)
            else:
                attorneys[-1]["address"] = (
                    attorneys[-1]["address"] or []
                ) + lines
        if not attorneys and not pro_per:
            pro_per = any(
                line.lower() == _PRO_PER for line in cls._cell_lines(cell)
            )
        return [
            {
                "name": a["name"],
                "firm": a["firm"],
                "address": ", ".join(a["address"]) if a["address"] else None,
            }
            for a in attorneys
        ], pro_per
