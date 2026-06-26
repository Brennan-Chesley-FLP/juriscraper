"""Parser for the NYSCEF Case Detail page.

URL: ``https://iapps.courts.state.ny.us/nyscef/CaseDetails?docketId={id}``

Carries the full caption, the "Information from Court of Original Instance"
block, and the party tables (Petitioners / Respondents) with their attorney
representations. Returns one partial :class:`NYSCEFCase` with these fields
plus the nested :class:`NYSCEFParty` records; the calling step merges it with
the search-grid fields and the document list before emitting.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, ClassVar

from jkent.common.deferred_validation import DeferredValidation
from jkent.common.parser import JKentParser
from jkent.data_types import XPath

from juriscraper.state.new_york.iapps_courts_state_ny_us.models import (
    NYSCEFAttorneyRep,
    NYSCEFCase,
    NYSCEFParty,
)

from ._common import (
    parse_attorney_reps,
    parse_date_mdy,
    split_party_name_role,
)

if TYPE_CHECKING:
    from jkent.common.page_element import PageElement


class CaseDetailParser(JKentParser[NYSCEFCase]):
    """Parse the Case Detail page into a partial ``NYSCEFCase``."""

    # Labelled originating-court fields, parsed off the block's flat text.
    _ORIG_COURT_PATTERNS: ClassVar[dict[str, str]] = {
        "originating_court_name": r"Index/Court:.*?-\s*(.*?)(?:\n|Judge:|$)",
        "originating_court_judge": r"Judge:\s*(.*?)(?:\n|Order|$)",
        "date_order_appealing_from": (
            r"Order Appealing From Date:\s*(\d{1,2}/\d{1,2}/\d{4})"
        ),
        "date_notice_of_appeal": (
            r"Notice of Appeal Date:\s*(\d{1,2}/\d{1,2}/\d{4})"
        ),
        "date_order_entered": (
            r"Order Entered Date:\s*(\d{1,2}/\d{1,2}/\d{4})"
        ),
        "date_notice_of_appeal_filed": (
            r"Notice of Appeal Filed Date:\s*(\d{1,2}/\d{1,2}/\d{4})"
        ),
        "requested_argument_time": r"Requested Argument Time:\s*(.*?)$",
    }

    def __call__(
        self, page: PageElement
    ) -> list[DeferredValidation[NYSCEFCase]]:
        fields: dict = {}

        # Full caption.
        caption_els = page.query(
            XPath(
                "//div[contains(@class, 'DataEntry_InnerBox')]"
                "//span[contains(@class, 'DataRow')]"
            ),
            "full caption element",
            min_count=0,
        )
        if caption_els:
            full_text = caption_els[0].text_content().strip()
            fields["case_name"] = (
                re.sub(r"^Full\s+Caption\s*", "", full_text).strip() or None
            )

        # Originating court block.
        info_divs = page.query(
            XPath(
                "//span[@class='Title' and contains(text(), "
                "'Information from Court of Original Instance')]"
                "/following-sibling::div[contains(@class, 'CaseSummary')]"
            ),
            "originating court info",
            min_count=0,
            max_count=1,
        )
        if info_divs:
            fields.update(self._parse_originating_court(info_divs[0]))

        # Parties.
        parties = self._parse_parties(page)

        return [NYSCEFCase.raw(parties=parties, **fields)]

    def _parse_originating_court(self, info_div: PageElement) -> dict:
        """Parse the labelled court-of-original-instance fields."""
        out: dict = {}

        index_links = info_div.query(
            XPath(".//a"), "index/court link", min_count=0, max_count=1
        )
        if index_links:
            out["originating_court_index"] = (
                index_links[0].text_content().strip() or None
            )

        text = info_div.text_content()
        for field, pattern in self._ORIG_COURT_PATTERNS.items():
            match = re.search(pattern, text, re.MULTILINE)
            if not match:
                continue
            value = match.group(1).strip()
            if field.startswith("date_"):
                out[field] = parse_date_mdy(value)
            else:
                out[field] = value or None
        return out

    def _parse_parties(
        self, page: PageElement
    ) -> list[DeferredValidation[NYSCEFParty]]:
        """Parse the Petitioners / Respondents party tables."""
        parties: list[DeferredValidation[NYSCEFParty]] = []
        party_sections = page.query(
            XPath("//div[contains(@class, 'tableHeading')]"),
            "party section headings",
            min_count=0,
        )
        for section in party_sections:
            group_name = section.text_content().strip()
            if group_name not in ("Petitioners", "Respondents"):
                continue
            tables = section.query(
                XPath("following-sibling::table[1]"),
                "party table",
                min_count=0,
                max_count=1,
            )
            if tables:
                parties.extend(self._parse_party_table(tables[0], group_name))
        return parties

    @staticmethod
    def _parse_party_table(
        table: PageElement, group_name: str
    ) -> list[DeferredValidation[NYSCEFParty]]:
        """Parse one party table (Petitioners or Respondents)."""
        parties: list[DeferredValidation[NYSCEFParty]] = []
        rows = table.query(XPath(".//tbody/tr"), "party rows", min_count=0)
        for row in rows:
            cells = row.query(XPath(".//td"), "party cells", min_count=0)
            if len(cells) < 2:
                continue
            name, role = split_party_name_role(cells[0].text_content().strip())
            attorneys = [
                NYSCEFAttorneyRep.raw(**a)
                for a in parse_attorney_reps(cells[1].text_content().strip())
            ]
            parties.append(
                NYSCEFParty.raw(
                    name=name,
                    role=role,
                    party_group=group_name,
                    attorneys=attorneys,
                )
            )
        return parties
