"""Parser for the Disposition tab (``parse_disposition``).

Supreme Court dispositions are a Date/Description table; Court of Appeal
dispositions are a single key-value (rowheader/cell) block, so the parser
branches on ``is_supreme``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from jkent.common.deferred_validation import DeferredValidation
from jkent.common.parser import JKentParser
from jkent.data_types import XPath

from juriscraper.state.california.appellatecases_courtinfo_ca_gov.models import (
    CaAppDisposition,
)
from juriscraper.state.california.appellatecases_courtinfo_ca_gov.vocabularies import (
    CaPublicationStatus,
)

from ._common import cell_lines, clean_optional, clean_text, parse_date

if TYPE_CHECKING:
    from jkent.common.page_element import PageElement


class DispositionParser(JKentParser[CaAppDisposition]):
    """Extract disposition rows.

    ``from_string`` exercises the Court-of-Appeal layout; construct
    ``DispositionParser(is_supreme=True)`` for the Supreme Court table.
    """

    def __init__(self, is_supreme: bool = False) -> None:
        self.is_supreme = is_supreme

    def __call__(
        self, page: PageElement
    ) -> list[DeferredValidation[CaAppDisposition]]:
        if self.is_supreme:
            return self._parse_supreme(page)
        return self._parse_coa(page)

    @staticmethod
    def _parse_supreme(
        page: PageElement,
    ) -> list[DeferredValidation[CaAppDisposition]]:
        rows = page.query(
            XPath("//table//tbody//tr"), "SC disposition rows", min_count=0
        )
        dispositions: list[DeferredValidation[CaAppDisposition]] = []
        for row in rows:
            cells = row.query(XPath("td"), "dispo cells", min_count=0)
            if len(cells) < 2:
                continue
            dispositions.append(
                CaAppDisposition.raw(
                    disposition_date=parse_date(cells[0].text_content()),
                    description=cells[1].text_content().strip(),
                )
            )
        return dispositions

    @staticmethod
    def _parse_coa(
        page: PageElement,
    ) -> list[DeferredValidation[CaAppDisposition]]:
        headers = page.query(
            XPath(
                "//table//th | //table//td[@class='rowheader'] | //table//tr/th"
            ),
            "CoA disposition headers",
            min_count=0,
        )
        values = page.query(
            XPath("//table//td[not(@class='rowheader')]"),
            "CoA disposition values",
            min_count=0,
        )
        if not (headers and values):
            return []

        dispo: dict = {}
        for h, v in zip(headers, values):
            key = h.text_content().strip().rstrip(":")
            val = v.text_content().strip()
            if key == "Description":
                dispo["description"] = val
            elif key == "Date":
                dispo["disposition_date"] = parse_date(val)
            elif key == "Disposition Type":
                # Two fields in one cell: the type, then -- after a <br> --
                # the text of the order itself. Read whole, the "type" comes
                # out as a paragraph on nearly half of all CoA dispositions.
                type_line, *note_lines = cell_lines(v) or [""]
                dispo["disposition_type"] = clean_text(type_line)
                dispo["disposition_notes"] = clean_text("\n".join(note_lines))
            elif key == "Publication Status":
                # Both, always: the coded value is what a consumer reads, and
                # the raw cell is what distinguishes "the court stated nothing"
                # from "the court stated something the vocabulary misses" --
                # the coded field is None either way.
                raw = clean_text(val)
                dispo["publication_status_raw"] = raw
                dispo["publication_status"] = CaPublicationStatus.parse(raw)
            elif key == "Author":
                dispo["author"] = clean_text(val)
            elif key == "Participants":
                dispo["participants"] = clean_text(val)
            elif key == "Case Citation" and (citation := clean_optional(val)):
                dispo["case_citation"] = citation
        if not dispo.get("description"):
            return []
        return [CaAppDisposition.raw(**dispo)]

    @staticmethod
    def extract_case_citation(page: PageElement) -> str | None:
        """Return the page-level Case Citation on a Supreme Court page.

        SC citations live in a standalone ``Case Citation`` block rather
        than a disposition row, so the scraper promotes this onto the
        docket separately. Returns None when absent or literally "none".
        """
        citation_texts = page.query_strings(
            XPath(
                "//div[contains(text(), 'Case Citation')]"
                "/following-sibling::div/text()"
            ),
            "citation text",
            min_count=0,
        )
        if not citation_texts:
            return None
        val = clean_optional(citation_texts[0])
        if val:
            return val
        return None
