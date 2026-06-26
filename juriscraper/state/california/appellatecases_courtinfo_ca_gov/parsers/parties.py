"""Parser for the Parties and Attorneys tab (``parse_parties``)."""

from __future__ import annotations

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


class PartiesParser(JKentParser[CaAppParty]):
    """Parse the Party / Attorney table into one ``CaAppParty`` per row.

    Each row has a Party cell ("Name : Role" then address lines) and an
    Attorney cell ("Name" then firm then address lines). Identical
    structure for Supreme Court and Court of Appeal.
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

            name, role, address_lines = self._parse_party_cell(
                cells[0].text_content().strip()
            )
            attorneys = self._parse_attorney_cell(
                cells[1].text_content().strip()
            )

            parties.append(
                CaAppParty.raw(
                    name=name,
                    role=clean_text(role),
                    address=(
                        ", ".join(address_lines) if address_lines else None
                    ),
                    attorneys=attorneys,
                )
            )
        return parties

    @staticmethod
    def _parse_party_cell(
        party_text: str,
    ) -> tuple[str, str | None, list[str]]:
        """Split a party cell into (name, role, address_lines).

        The first line is "Name : Role" (or just "Name"); the remaining
        lines are the address.
        """
        lines = [ln.strip() for ln in party_text.split("\n") if ln.strip()]
        if not lines:
            return "", None, []
        first = lines[0]
        if " : " in first:
            name, role = first.split(" : ", 1)
        else:
            name, role = first, None
        return name.strip(), role, lines[1:]

    @staticmethod
    def _parse_attorney_cell(attorney_text: str) -> list[dict]:
        """Split an attorney cell into a single-attorney list.

        Line 1 is the attorney name, line 2 (if present) the firm, and the
        remainder the address.
        """
        lines = [ln.strip() for ln in attorney_text.split("\n") if ln.strip()]
        if not lines:
            return []
        return [
            {
                "name": lines[0],
                "firm": lines[1] if len(lines) > 1 else None,
                "address": ", ".join(lines[2:]) if len(lines) > 2 else None,
            }
        ]
