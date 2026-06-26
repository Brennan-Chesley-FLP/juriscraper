"""Parser for the Washington DW Courts search-results page.

The appellate case-number search returns one card
(``.dw-search-result``) per participant in the case; every card for a
given case shares the same case-detail link (``casekey``/``courtname``
query params). :class:`SearchResultsParser` extracts the participants and
the case-link metadata; the step does the navigation (following the
single case-detail link).
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING
from urllib.parse import parse_qs, urlparse

from jkent.common.parser import JKentParser
from jkent.data_types import XPath

from juriscraper.state.washington.dw_courts_wa_gov.models import (
    DWWAParticipant,
)

from ._common import parse_dw_date

if TYPE_CHECKING:
    from datetime import date

    from jkent.common.deferred_validation import DeferredValidation
    from jkent.common.page_element import PageElement


class SearchResultsParser(JKentParser[DWWAParticipant]):
    """Parse search-result cards into participants + case-link metadata."""

    def __call__(
        self, page: PageElement
    ) -> list[DeferredValidation[DWWAParticipant]]:
        return [
            DWWAParticipant.raw(**p.model_dump())
            for p in self.parse(page)["participants"]
        ]

    def parse(self, page: PageElement) -> dict:
        """Return ``{participants, case_key, case_link_href, court_name,
        date_filed}``.

        ``case_link_href`` is the raw (possibly relative) href the step
        must resolve against the page URL. Returns empty participants and
        ``None`` link fields on a speculative miss (no cards).
        """
        cards = page.query(
            XPath(
                "//div[contains(@class, 'dw-search-result')"
                " and .//div[contains(@class, 'dw-search-result-left')]"
                " and .//div[contains(@class, 'dw-search-result-right')]]"
            ),
            "search result cards",
            min_count=0,
        )

        participants: list[DWWAParticipant] = []
        case_key: str | None = None
        case_link_href: str | None = None
        court_name: str | None = None
        date_filed: date | None = None

        for card in cards:
            name = _extract_field(card, "Name")
            role = _extract_field(card, "Participant Code")
            review_type = _extract_field(card, "Review Type")
            if name:
                participants.append(
                    DWWAParticipant(
                        name=name,
                        role=role,
                        review_type=review_type,
                    )
                )

            if case_link_href is None:
                links = card.query(
                    XPath(".//a[contains(@href, 'casekey')]"),
                    "case detail link",
                    min_count=0,
                    max_count=1,
                )
                if links:
                    href = links[0].get_attribute("href")
                    if href:
                        case_link_href = href
                        params = parse_qs(urlparse(href).query)
                        case_key = (params.get("casekey") or [None])[0]
                        court_name_raw = (params.get("courtname") or [None])[0]
                        if court_name_raw:
                            court_name = court_name_raw

            if date_filed is None:
                right_els = card.query(
                    XPath(
                        ".//div[contains(@class, 'dw-search-result-right')]"
                    ),
                    "card right panel",
                    min_count=0,
                    max_count=1,
                )
                if right_els:
                    right_text = right_els[0].text_content()
                    fd_match = re.search(r"File Date:\s*([\d-]+)", right_text)
                    if fd_match:
                        date_filed = parse_dw_date(fd_match.group(1))

        return {
            "participants": participants,
            "case_key": case_key,
            "case_link_href": case_link_href,
            "court_name": court_name,
            "date_filed": date_filed,
        }


def _extract_field(card: PageElement, label: str) -> str | None:
    """Extract a labeled value from a search-result card.

    Card fields are rendered as::

        <span class="semi-bold ...">Label: </span>
        <span class="...">Value</span>

    within ``.dw-icon-row`` divs.
    """
    rows = card.query(
        XPath(
            f".//div[contains(@class, 'dw-icon-row')]"
            f"[.//span[contains(text(), '{label}')]]"
        ),
        f"card row for {label}",
        min_count=0,
    )
    if not rows:
        return None
    spans = rows[0].query(
        XPath(
            ".//span[contains(@class, 'mdc-typography--body2')]"
            "[not(contains(@class, 'semi-bold'))]"
        ),
        f"value span for {label}",
        min_count=0,
    )
    if spans:
        text = spans[-1].text_content().strip()
        return text if text else None
    return None
