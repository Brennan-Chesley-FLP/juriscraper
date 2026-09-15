"""Parser for the Case Description block of a CourtConnect docket report."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from jkent.common.deferred_validation import DeferredValidation
from jkent.common.parser import JKentParser
from jkent.data_types import XPath

from juriscraper.state.delaware.courtconnect_courts_delaware_gov.models import (
    DeCourtConnectDocket,
)

from ._common import (
    clean_optional,
    clean_text,
    parse_date,
    split_code_description,
)

if TYPE_CHECKING:
    from jkent.common.page_element import PageElement

#: The Case Description block is a three-column label/value table
#: (spacer, ``<b>Label:</b>``, value). It is selected by its Filing Date label
#: rather than by position: the page opens with a Report Selection Criteria
#: table of the same shape, and both sit under ``<a name=...>`` anchors the
#: site leaves unclosed, so anchor-relative XPaths depend on how the parser
#: repairs the markup.
_DESCRIPTION_TABLE = XPath('//table[.//b[normalize-space()="Filing Date:"]]')

#: The case id cell holds ``"{case_id}\n - {case_name}"``. The caption is split
#: on the first newline-plus-dash rather than on " - " anywhere, so a caption
#: that itself contains " - " stays intact.
_ID_AND_NAME = re.compile(r"^\s*(\S+)\s*(?:\n\s*-\s*(.*))?$", re.DOTALL)


class CaseDescriptionParser(JKentParser[DeCourtConnectDocket]):
    """Parse the Case Description block into a partial docket record.

    Returns a one-element list: the block describes exactly one case. The
    parties, docket entries and related cases are parsed separately and merged
    by the step, so the record here carries only the case-level metadata --
    ``court`` is not among them, since the page never names the court (see
    ``models.CASE_TYPE_COURTS``).
    """

    def __call__(
        self, page: PageElement
    ) -> list[DeferredValidation[DeCourtConnectDocket]]:
        table = page.query(
            _DESCRIPTION_TABLE,
            "case description table",
            min_count=1,
            max_count=1,
        )[0]
        fields = self._label_value_pairs(table)

        raw_id_cell = fields.get("Case ID:", "")
        docket_number, case_name = self._split_id_and_name(raw_id_cell)
        case_type = clean_optional(fields.get("Type:"))
        type_code, type_description = split_code_description(case_type)
        status_code, status_description = split_code_description(
            fields.get("Status:")
        )

        return [
            DeCourtConnectDocket.raw(
                docket_number=docket_number,
                docket_number_raw=docket_number,
                case_name=case_name,
                date_filed=parse_date(fields.get("Filing Date:")),
                case_type=case_type,
                case_type_code=type_code,
                case_type_description=type_description,
                status_code=status_code,
                status_description=status_description,
            )
        ]

    @staticmethod
    def _label_value_pairs(table: PageElement) -> dict[str, str]:
        """Read the block's ``{label: raw value}`` pairs.

        The value is returned *unnormalised* -- the Case ID cell's newline is
        the only boundary between the case id and the caption, and collapsing
        whitespace here would destroy it.
        """
        pairs: dict[str, str] = {}
        for row in table.query(
            XPath("./tr | ./tbody/tr"), "description rows", min_count=1
        ):
            cells = row.query(XPath("./td"), "description cells", min_count=0)
            if len(cells) < 3:
                continue
            if label := clean_text(cells[1].text_content()):
                pairs[label] = cells[2].text_content()
        return pairs

    @staticmethod
    def _split_id_and_name(cell_text: str) -> tuple[str | None, str | None]:
        """Split ``"2025-1110\\n - IMO 221 CHESTNUT STREET"`` into its parts."""
        text = cell_text.replace("\xa0", " ").strip()
        if not text:
            return None, None
        match = _ID_AND_NAME.match(text)
        if match is None:
            return clean_text(text), None
        docket_number, case_name = match.groups()
        return clean_text(docket_number), clean_text(case_name)
