"""Parser for the Mississippi parties pane (``listby=pty``).

Layout: groups of ``<TABLE BGCOLOR="#003366">`` blocks, each headed by a
``laptcell`` role label and a name cell, with ``liaptcell`` rows for each
attorney. The site's HTML for the attorney rows is malformed — each
attorney's ``<table>`` is opened but never explicitly closed, so lxml
normalises by nesting them. We therefore walk every ``<td
class="liaptcell">`` in document order and assign each to the nearest
preceding party-header table, matching by
``count(preceding::table[bgcolor='#003366'])`` (a stable 1-based index).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from jkent.common.deferred_validation import DeferredValidation
from jkent.common.parser import JKentParser
from jkent.data_types import XPath

from juriscraper.state.mississippi.courts_ms_gov.models import (
    MsAppAttorney,
    MsAppParty,
)

from ._common import strip

if TYPE_CHECKING:
    from jkent.common.page_element import PageElement


class PartiesParser(JKentParser[MsAppParty]):
    """Parse the parties + attorneys block into ``MsAppParty`` records."""

    def __call__(
        self, page: PageElement
    ) -> list[DeferredValidation[MsAppParty]]:
        party_blocks = page.query(
            XPath(
                "//table[translate(@bgcolor, 'abcdef', 'ABCDEF')='#003366']"
            ),
            "party header tables",
            min_count=0,
        )

        parties_state: list[dict] = []
        for block in party_blocks:
            role_cells = block.query(
                XPath(".//td[@class='laptcell']"),
                "role cell",
                min_count=0,
                max_count=1,
            )
            role = strip(role_cells[0].text_content()) if role_cells else ""
            name_cells = block.query(
                XPath(".//tr[1]/td[not(@class='laptcell')]"),
                "party name cell",
                min_count=0,
                max_count=1,
            )
            if not name_cells:
                continue
            name = strip(name_cells[0].text_content())
            if not name:
                continue
            parties_state.append({"role": role, "name": name, "attorneys": []})

        # Bucket each attorney row to its nearest preceding party block.
        # We can't compare PageElement instances by identity, so use
        # ``count(preceding::table[bgcolor='#003366'])`` as a stable
        # 1-based index into ``parties_state``.
        liaptcells = page.query(
            XPath("//td[@class='liaptcell']"),
            "attorney anchor cells",
            min_count=0,
        )
        for cell in liaptcells:
            sibs = cell.query(
                XPath("../td[not(@class='liaptcell')][1]"),
                "attorney name cell",
                min_count=0,
                max_count=1,
            )
            if not sibs:
                continue
            atty_name = strip(sibs[0].text_content())
            if not atty_name or atty_name == "No Attorney Representation":
                continue
            count_strs = cell.query_strings(
                XPath(
                    "string(count(preceding::table["
                    "translate(@bgcolor, 'abcdef', 'ABCDEF')='#003366']))"
                ),
                "preceding party header count",
                min_count=0,
                max_count=1,
            )
            if not count_strs:
                continue
            try:
                idx = int(float(count_strs[0])) - 1
            except (TypeError, ValueError):
                continue
            if not 0 <= idx < len(parties_state):
                continue
            atty_list: list[str] = parties_state[idx]["attorneys"]
            if atty_name not in atty_list:
                atty_list.append(atty_name)

        return [
            MsAppParty.raw(
                name=str(state["name"]),
                role=str(state["role"]) or None,
                attorneys=[MsAppAttorney(name=n) for n in state["attorneys"]],
            )
            for state in parties_state
        ]
