"""Parser for the Georgia Court of Appeals opinion-search results page.

``docketdate/results_all.php?OPstartDate=…&OPendDate=…`` renders a single
``search-results`` table of decided cases, one row per disposition. Each row
carries the case number, caption, judgment date, ruling, and — when the opinion
is online — a direct PDF link to the opinion/order. Rows from the older years
still render a "View PDF File" anchor but with an empty ``filingId``; those
yield ``pdf_url=None`` so nothing dead is queued for download (the docket's
``opinion_requestable`` is decided on the case-detail page).

The page spawns two follow-up requests per row (a case-detail fetch and a
PDF download), so it isn't a single ``ScrapedData`` record — :class:`OpinionSearchParser`
just lifts the per-row fields off the HTML into :class:`OpinionSearchRow`
dataclasses and the step owns the navigation (see ``scraper.py``). HTML
extraction stays out of the step, per ``../../SCRAPER_STANDARDS.md`` §9.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING

from jkent.data_types import XPath

from ._common import classify_opinion_href, clean, parse_long_date

if TYPE_CHECKING:
    from jkent.common.page_element import PageElement


@dataclass
class OpinionSearchRow:
    """One row of the opinion-search results table."""

    docket_number: str
    case_name: str | None
    date_judgment: date | None
    judgment_ruling: str | None
    pdf_url: str | None
    """Relative or absolute opinion-PDF href, if the opinion is online.

    ``None`` both when the row has no link and when it carries the site's dead
    placeholder (``download?filingId=`` with no id) — see
    :func:`._common.classify_opinion_href`."""


class OpinionSearchParser:
    """Lift the opinion-search result rows off the results HTML.

    Returns one :class:`OpinionSearchRow` per result row. Rows without a
    case number are skipped (header/spacer rows).
    """

    def __call__(self, page: PageElement) -> list[OpinionSearchRow]:
        rows = page.query(
            XPath("//table[contains(@class, 'search-results')]//tr[td]"),
            "opinion result rows",
            min_count=0,
        )
        out: list[OpinionSearchRow] = []
        for row in rows:
            cells = row.query(XPath(".//td"), "row cells", min_count=0)
            if len(cells) < 6:
                continue

            docket_number = clean(cells[0].text_content())
            if not docket_number:
                continue

            pdf_links = cells[5].query_strings(
                XPath(".//a/@href"),
                "opinion pdf href",
                min_count=0,
                max_count=1,
            )
            # A row whose opinion was never published online still renders a
            # "View PDF File" anchor, but with an empty ``filingId``; only a
            # link carrying a real id is a document.
            pdf_url, _requestable = classify_opinion_href(
                pdf_links[0] if pdf_links else None,
                cells[5].text_content(),
            )
            out.append(
                OpinionSearchRow(
                    docket_number=docket_number,
                    case_name=clean(cells[1].text_content()),
                    date_judgment=parse_long_date(cells[2].text_content()),
                    judgment_ruling=clean(cells[3].text_content()),
                    pdf_url=pdf_url,
                )
            )
        return out
