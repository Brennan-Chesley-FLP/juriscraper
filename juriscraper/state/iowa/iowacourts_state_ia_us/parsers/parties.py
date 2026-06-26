"""Parser for the Iowa Parties tab (``AViewParties``).

The table holds both human parties and attorneys/firms, distinguished only
by the role text. Each row is ``[name, role, status]`` with the name linked
as ``<a href="/ESAWebApp/AViewAttorney?<id>">``. :class:`PartiesParser`
returns one :class:`IowaParty` per linked row.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from jkent.common.deferred_validation import DeferredValidation
from jkent.common.parser import JKentParser
from jkent.data_types import XPath

from juriscraper.state.iowa.iowacourts_state_ia_us.models import IowaParty

from ._common import clean_text

if TYPE_CHECKING:
    from jkent.common.page_element import PageElement

# Pattern attorney/party links use to identify the underlying record:
# /ESAWebApp/AViewAttorney?AT0014845  or  ?SC1000371  or  ?STATEIOWA
ATTORNEY_LINK_RE = re.compile(r"AViewAttorney\?(.+)$")


class PartiesParser(JKentParser[IowaParty]):
    """Read the Parties table, one ``IowaParty`` per linked row."""

    def __call__(
        self, page: PageElement
    ) -> list[DeferredValidation[IowaParty]]:
        # Skip the header row (Name | Role | Status); every subsequent row
        # has three cells in the same order.
        rows = page.query(
            XPath("//tr[td[a[contains(@href, 'AViewAttorney')]]]"),
            "party rows",
            min_count=0,
        )

        parties: list[DeferredValidation[IowaParty]] = []
        for row in rows:
            anchors = row.query(
                XPath(".//a[contains(@href, 'AViewAttorney')]"),
                "party link",
                min_count=0,
                max_count=1,
            )
            if not anchors:
                continue
            name = clean_text(anchors[0].text_content())
            href = anchors[0].get_attribute("href") or ""
            site_id_match = ATTORNEY_LINK_RE.search(href)
            site_id = site_id_match.group(1) if site_id_match else None

            tds = row.query(XPath("./td"), "party cells", min_count=0)
            cell_texts = [clean_text(td.text_content()) for td in tds]
            # cells == [name, role, status]
            role = cell_texts[1] if len(cell_texts) > 1 else ""
            status = (
                cell_texts[2]
                if len(cell_texts) > 2 and cell_texts[2]
                else None
            )

            parties.append(
                IowaParty.raw(
                    name=name,
                    role=role,
                    status=status,
                    site_id=site_id,
                )
            )
        return parties
