"""Parser for a single TAMES ``Case.aspx`` case-detail page.

One case-detail page renders the full register of actions for a single
Texas appellate case as ASP.NET-rendered HTML tables.
:class:`CaseDetailParser` routes to the correct legacy per-court parser
(Supreme Court, Court of Criminal Appeals, or Court of Appeals) based on
the docket number's format (or the page URL's ``coa=`` parameter), runs
the proven legacy lxml extraction, and adapts the result into a single
:class:`TexasDocket`.

The page does *not* carry the source URL or the entry point used to reach
it — the calling step stamps those onto the returned ``raw_data`` before
emitting (see ``scraper.py``).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from jkent.common.deferred_validation import DeferredValidation
from jkent.common.parser import JKentParser
from jkent.data_types import XPath

from juriscraper.state.texas.search_txcourts_gov.models import TexasDocket

from ._common import (
    adapt_legacy_docket,
    court_code_from_docket,
    extract_coa_param,
    make_legacy_parser,
)

if TYPE_CHECKING:
    from jkent.common.page_element import PageElement


class CaseDetailParser(JKentParser[TexasDocket]):
    """Parse one TAMES case-detail page into a single ``TexasDocket``.

    Returns a single-element list with one ``TexasDocket`` carrying the
    header scalars and the nested party / entry / document / transfer
    records. ``source_url`` and ``source_entry_point`` are stamped by the
    calling step.
    """

    def __call__(
        self, page: PageElement
    ) -> list[DeferredValidation[TexasDocket]]:
        # The legacy parsers consume the page's full HTML markup; the case
        # detail tables are addressed by their ASP.NET element ids, which
        # survive ``inner_html()`` reconstruction.
        markup = page.inner_html()

        court_code = self._detect_court_code(page)
        legacy = make_legacy_parser(court_code)
        legacy._parse_text(markup)
        return [adapt_legacy_docket(dict(legacy.data), court_code)]

    @staticmethod
    def _detect_court_code(page: PageElement) -> str | None:
        """Resolve the TAMES ``coa=`` code for this page.

        Prefers the docket number printed in the case-info panel (its
        format unambiguously identifies the court); falls back to the
        ``coa=`` query parameter on any in-page ``Case.aspx`` link.
        """
        # The docket number sits in the ``#case`` cell of the case-info panel.
        case_cells = page.query(
            XPath("//*[@id='case']"),
            "case number cell",
            min_count=0,
            max_count=1,
        )
        if case_cells:
            docket_number = case_cells[0].text_content().strip()
            code = court_code_from_docket(docket_number)
            if code:
                return code

        # Fallback: read ``coa=`` off a self-referential Case.aspx link.
        links = page.query(
            XPath(
                "//a[contains(@href, 'Case.aspx') and contains(@href, 'coa=')]"
            ),
            "case links carrying coa= param",
            min_count=0,
        )
        for link in links:
            href = link.get_attribute("href") or ""
            code = extract_coa_param(href)
            if code:
                return code
        return None
