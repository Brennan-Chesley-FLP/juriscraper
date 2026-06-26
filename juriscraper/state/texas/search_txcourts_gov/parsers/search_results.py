"""Parser for a TAMES ``/CaseSearch.aspx`` results page.

The search results render in a Telerik RadGrid (``grdCases``). This page is
navigational, not a record page: each row points at a ``Case.aspx``
case-detail page, and the page also carries the ASP.NET hidden fields and
RadGrid pagination controls the step needs to walk the result set. The
extraction here (result rows → ``(docket_number, case_url)`` pairs, the
"N items in M pages" count, and the hidden-field harvest) lives in this
parser so all XPath stays out of the ``@step`` methods; pagination /
window-splitting decisions remain in the step.

Because results pages are not themselves dockets, this parser does not
subclass :class:`JKentParser` (which is generic over the emitted record
type); it is a plain extraction helper exposing the parsing surface the
step composes with navigation.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING
from urllib.parse import urljoin

from jkent.data_types import XPath

from juriscraper.state.texas.search_txcourts_gov.models import BASE_URL

if TYPE_CHECKING:
    from jkent.common.page_element import PageElement

_RESULT_COUNT_RE = re.compile(
    r"(\d+)\s+items?\s+in\s+\d+\s+pages?", re.IGNORECASE
)


@dataclass(frozen=True)
class SearchResultRow:
    """One result row's addressing data."""

    docket_number: str
    case_url: str


class SearchResultsParser:
    """Extract result rows, result count, and hidden fields from a page."""

    def case_rows(self, page: PageElement) -> list[SearchResultRow]:
        """Return one :class:`SearchResultRow` per result row on the page.

        Empty result sets are valid (a date window may legitimately have no
        cases), so ``min_count=0``.
        """
        rows = page.query(
            XPath(
                "//table[@id='ctl00_ContentPlaceHolder1_grdCases_ctl00']"
                "//tr[contains(@class, 'rgRow') or contains(@class, 'rgAltRow')]"
            ),
            "search result rows",
            min_count=0,
        )
        out: list[SearchResultRow] = []
        for row in rows:
            # The case-number link is in the first column. A row can carry a
            # second Case.aspx link in the "COA Case Number" column (pointing
            # at the lower COA case); restrict to the first cell so we pick
            # this row's own docket.
            links = row.query(
                XPath("./td[1]//a[contains(@href, 'Case.aspx')]"),
                "case-detail link",
                min_count=0,
                max_count=1,
            )
            if not links:
                continue
            href = links[0].get_attribute("href") or ""
            if not href:
                continue
            out.append(
                SearchResultRow(
                    docket_number=links[0].text_content().strip(),
                    case_url=urljoin(BASE_URL, href),
                )
            )
        return out

    def result_count(self, page: PageElement) -> int:
        """Read the "N items in M pages" string from the RadGrid footer."""
        info_parts = page.query_strings(
            XPath("//div[contains(@class, 'rgInfoPart')]//text()"),
            "rgInfoPart text",
            min_count=0,
        )
        joined = " ".join(t.strip() for t in info_parts if t.strip())
        match = _RESULT_COUNT_RE.search(joined)
        return int(match.group(1)) if match else 0

    def hidden_fields(self, page: PageElement) -> dict[str, str]:
        """Collect all ``<input type=hidden>`` name/value pairs from the page.

        ASP.NET WebForms requires ``__VIEWSTATE``, ``__VIEWSTATEGENERATOR``,
        ``__EVENTVALIDATION``, ``__EVENTTARGET``, ``__EVENTARGUMENT`` and a
        handful of Telerik state inputs to be re-submitted on each POST.
        """
        fields: dict[str, str] = {}
        inputs = page.query(
            XPath("//input[@type='hidden']"),
            "ASP.NET hidden fields",
            min_count=0,
        )
        for elem in inputs:
            name = elem.get_attribute("name") or ""
            if not name:
                continue
            fields[name] = elem.get_attribute("value") or ""
        return fields

    def next_page_submitter(self, page: PageElement) -> tuple[str, str] | None:
        """Return the ``(name, value)`` of the rgPageNext submit button.

        Returns ``None`` when there is no further page (either the button is
        absent or the current page is already the last one).
        """
        next_buttons = page.query(
            XPath("//input[contains(@class, 'rgPageNext')]"),
            "rgPageNext button",
            min_count=0,
            max_count=2,
        )
        current_page_has_next = page.query(
            XPath(
                "//span[contains(@class, 'rgCurrentPage')]/following-sibling::a"
            ),
            "current+next page anchor",
            min_count=0,
            max_count=2,
        )
        if not (next_buttons and current_page_has_next):
            return None
        name = next_buttons[0].get_attribute("name") or ""
        value = next_buttons[0].get_attribute("value") or ""
        return (name, value)
