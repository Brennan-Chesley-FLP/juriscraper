"""Page-level parsers for the Court-PASS scraper.

Each Parser is a Callable that takes the page element a step received and
returns a list of ``DeferredValidation[NYCourtPassDocket]`` partials
containing only the fields that this particular page contributes to the
eventual NYCourtPassDocket. Non-extractable fields (temp_case_id,
docket_number, search_page, source_url, etc.) are filled in by the step
from accumulated_data and the response.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import TYPE_CHECKING

from jkent.common.checked_html import CheckedHtmlElement
from jkent.common.deferred_validation import DeferredValidation
from jkent.common.lxml_page_element import LxmlPageElement
from jkent.common.parser import KentParser
from lxml import html as lxml_html

from .models import (
    NYCourtPassAttorney,
    NYCourtPassDocket,
    NYCourtPassDocketEntry,
    NYCourtPassFile,
)

if TYPE_CHECKING:
    from jkent.common.page_element import PageElement


def _parse_date_mdy(text: str | None) -> date | None:
    """Parse MM/DD/YYYY date strings emitted by Court-PASS."""
    if not text:
        return None
    text = text.strip()
    if not text:
        return None
    try:
        return datetime.strptime(text, "%m/%d/%Y").date()
    except ValueError:
        return None


class FilingDetailParser(KentParser[NYCourtPassDocket]):
    """Parse the filing-detail span (``cphMain_lbDetails2``) and ``gvFiles``.

    The filing-detail page is reached via the hidden ``bttnDetails``
    postback from the docket-detail page. It carries the decision-side
    fields (decision date, opinion by, citation, issues) and the file
    list. Both ``parse_docket_filing_detail`` and
    ``parse_filing_detail_from_docket`` extract from the same span id;
    this parser is shared between them.
    """

    SPAN_ID = "cphMain_lbDetails2"

    def __call__(
        self, page: PageElement
    ) -> list[DeferredValidation[NYCourtPassDocket]]:
        span_xpath = f"//span[@id='{self.SPAN_ID}']"

        caption_parts = page.query_xpath_strings(
            f"{span_xpath}//div[contains(@class, 'case-caption')]//text()",
            "case caption text",
            min_count=0,
        )
        case_name = " ".join(t.strip() for t in caption_parts if t.strip())

        detail_map: dict[str, str] = {}
        dt_elements = page.query_xpath(
            f"{span_xpath}//dl[contains(@class, 'case-details')]/dt",
            "case-details dt",
            min_count=0,
        )
        for dt in dt_elements:
            label = dt.text_content().strip().rstrip(":").strip()
            if not label:
                continue
            value_parts = dt.query_xpath_strings(
                "./following-sibling::dd[1]//text()",
                "case-details value",
                min_count=0,
            )
            value = " ".join(p.strip() for p in value_parts if p.strip())
            detail_map[label.casefold()] = value

        def _m(label: str) -> str | None:
            v = detail_map.get(label.casefold())
            return v or None

        argument_date_str = _m("Argument Date")
        decision_date_str = _m("Decision Date")
        opinion_by = _m("Opinion By")
        official_citation = _m("Official Citation")

        if argument_date_str and not re.match(
            r"\d{2}/\d{2}/\d{4}", argument_date_str
        ):
            argument_date_str = None
        if decision_date_str and not re.match(
            r"\d{2}/\d{2}/\d{4}", decision_date_str
        ):
            decision_date_str = None

        issues = self._extract_issue_strings(
            page, f"{span_xpath}//p[contains(@class, 'case-issues-category')]"
        )
        issue_details = self._extract_issue_strings(
            page, f"{span_xpath}//p[contains(@class, 'case-issues-text')]"
        )

        # The bogus inline <style> that pollutes issue_details can also
        # swallow the gvFiles table and the "no files" marker (lxml
        # extends the unclosed <style> through end-of-document). When
        # that happens, the swallowed HTML is preserved verbatim inside
        # the <style>'s text — re-parse it and use that fragment as the
        # source of truth for files + the marker.
        swallowed_html = self._extract_swallowed_html(page, span_xpath)
        if swallowed_html is not None:
            files_source = self._wrap_html_fragment(swallowed_html)
            marker_text = swallowed_html.lower()
        else:
            files_source = page
            detail_texts = page.query_xpath_strings(
                f"{span_xpath}//text()",
                "filing detail text",
                min_count=0,
            )
            marker_text = " ".join(
                t.strip() for t in detail_texts if t.strip()
            ).lower()

        no_files_for_case = (
            "there are no files available for this case" in marker_text
        )
        files = self._parse_files(files_source)

        return [
            NYCourtPassDocket.raw(
                case_name=case_name,
                argument_date=_parse_date_mdy(argument_date_str),
                decision_date=_parse_date_mdy(decision_date_str),
                opinion_by=opinion_by,
                official_citation=official_citation,
                issues=issues,
                issue_details=issue_details,
                no_files_for_case=no_files_for_case,
                files=files,
                reconstituted_html=swallowed_html is not None,
            )
        ]

    @classmethod
    def _extract_issue_strings(
        cls, page: PageElement, xpath: str
    ) -> list[str]:
        """One ``str`` per ``<p>`` matching ``xpath`` (joined text content).

        Court-PASS pages occasionally inline ``<style pdffontname=...>``
        without a closing tag as a PDF-derived font marker. lxml then
        treats every subsequent character — through ``</p></section>``,
        the file table, footer, scripts — as the ``<style>``'s text and
        the issue ``<p>``'s ``text_content()`` swallows it all. Trim
        each ``<p>``'s text at the literal ``</p>``/``</section>`` it
        included.
        """
        elements = page.query_xpath(xpath, "issue p", min_count=0)
        out: list[str] = []
        for el in elements:
            text = cls._strip_style_leakage(el.text_content()).strip()
            if text:
                out.append(text)
        return out

    @staticmethod
    def _strip_style_leakage(text: str) -> str:
        """Truncate text at the first ``</p>`` or ``</section>`` literal.

        These appear as real characters in extracted text only when an
        unclosed ``<style>`` swallowed downstream markup (see
        ``_extract_issue_strings``). Legitimate issue text never quotes
        raw HTML tags.
        """
        for sentinel in ("</p>", "</section>"):
            idx = text.find(sentinel)
            if idx >= 0:
                text = text[:idx]
        return text

    @staticmethod
    def _extract_swallowed_html(
        page: PageElement, span_xpath: str
    ) -> str | None:
        """Return HTML the bogus ``<style pdffontname=...>`` swallowed.

        Court-PASS occasionally emits ``<p class="case-issues-text">``
        containing a ``<style pdffontname=...>`` with NO closing tag.
        lxml treats ``<style>`` as raw text and extends it to the
        document-level ``</style>`` near ``</html>``, swallowing the
        file table and any "no files" marker as literal text inside the
        ``<style>``.

        The swallowed text begins with the italicized citation that
        belongs in ``issue_details``; the rest of the page begins at
        the first ``</section>`` (or ``</p>``) the style absorbed.
        Return everything from that point on, or ``None`` if no
        leakage is detected.
        """
        styles = page.query_xpath(
            f"{span_xpath}//p[contains(@class, 'case-issues-text')]"
            "/style[@pdffontname]",
            "style leakage detector",
            min_count=0,
        )
        if not styles:
            return None
        text = styles[0].text_content()
        for sentinel in ("</section>", "</p>"):
            idx = text.find(sentinel)
            if idx >= 0:
                return text[idx + len(sentinel) :]
        return None

    @staticmethod
    def _wrap_html_fragment(html_fragment: str) -> PageElement:
        """Wrap raw HTML text in an LxmlPageElement for re-querying."""

        element = lxml_html.fromstring(f"<div>{html_fragment}</div>")
        return LxmlPageElement(CheckedHtmlElement(element, ""), url="")

    @staticmethod
    def _parse_files(page: PageElement) -> list[NYCourtPassFile]:
        """Walk ``gvFiles`` and build NYCourtPassFile rows.

        ``temp_case_id`` and ``docket_number`` are not on the page; the
        step injects them after pulling raw_data from this parser.
        ``document_number`` is computed as ``total_files - row_index`` —
        bottom-up numbering, matching the downstream pipeline.
        """
        files_info: list[dict] = []
        file_rows = page.query_xpath(
            "//table[contains(@id, 'gvFiles')]//tr[position()>1]",
            "file rows",
            min_count=0,
        )
        for j, file_row in enumerate(file_rows):
            file_cells = file_row.query_xpath("td", "file cells", min_count=0)
            if len(file_cells) < 2:
                continue
            file_name = file_cells[0].text_content().strip()
            buttons = file_row.query_xpath(
                ".//input[@type='submit']",
                "download button",
                min_count=0,
            )
            enabled_buttons = [
                b for b in buttons if not b.get_attribute("disabled")
            ]
            available = len(enabled_buttons) > 0
            files_info.append(
                {
                    "file_name": file_name,
                    "available": available,
                    "row_index": j,
                }
            )

        total_files = len(files_info)
        return [
            NYCourtPassFile(
                file_name=f["file_name"],
                file_index=f["row_index"],
                document_number=total_files - i,
                available=f["available"],
            )
            for i, f in enumerate(files_info)
        ]


class DocketDetailParser(KentParser[NYCourtPassDocket]):
    """Parse the docket-detail span (``cphMain_lbDetails``).

    The docket-detail page carries the case caption, argument date,
    FILINGS table (docket_entries), and ATTORNEY DETAILS table
    (attorneys). Used from ``parse_docket_detail`` (enumerate flow) and
    ``parse_docket_detail_for_entry`` (get_docket flow).
    """

    SPAN_XPATH = "//span[@id='cphMain_lbDetails']"

    def __call__(
        self, page: PageElement
    ) -> list[DeferredValidation[NYCourtPassDocket]]:
        case_details_dl = f"{self.SPAN_XPATH}//dl[@class='case-details']"

        docket_links = page.query_xpath_strings(
            f"{self.SPAN_XPATH}//button[contains(@onclick, 'CallDetails')]//text()",
            "docket number",
            min_count=0,
        )
        docket_number: str | None = None
        for link_text in docket_links:
            dn_match = re.search(r"[A-Z]+-\d{4}-\d{5}", link_text)
            if dn_match:
                docket_number = dn_match.group(0)
                break

        arg_date_texts = page.query_xpath_strings(
            f"{case_details_dl}"
            "/dt[contains(text(),'Argument Date')]/following-sibling::dd[1]//text()",
            "argument date",
            min_count=0,
        )
        argument_date_str: str | None = None
        for t in arg_date_texts:
            t = t.strip()
            if re.match(r"\d{2}/\d{2}/\d{4}", t):
                argument_date_str = t
                break

        title_texts = page.query_xpath_strings(
            f"{case_details_dl}"
            "/dt[contains(text(),'Title')]/following-sibling::dd[1]//text()",
            "case title",
            min_count=0,
        )
        case_name = " ".join(t.strip() for t in title_texts if t.strip())

        docket_entries = self._parse_filings(page)
        attorneys = self._parse_attorneys(page)

        return [
            NYCourtPassDocket.raw(
                docket_number=docket_number,
                case_name=case_name,
                argument_date=_parse_date_mdy(argument_date_str),
                docket_entries=docket_entries,
                attorneys=attorneys,
            )
        ]

    def _parse_filings(
        self, page: PageElement
    ) -> list[NYCourtPassDocketEntry]:
        filings_tables = page.query_xpath(
            f"{self.SPAN_XPATH}//table[.//strong[contains(text(),'FILINGS')]]",
            "filings table",
            min_count=0,
        )
        if not filings_tables:
            return []
        filing_rows = filings_tables[0].query_xpath(
            ".//tr[td[not(@colspan)]]",
            "filing data rows",
            min_count=0,
        )
        entries: list[NYCourtPassDocketEntry] = []
        for filing_row in filing_rows:
            cells = filing_row.query_xpath("td", "filing cells", min_count=0)
            if len(cells) < 4:
                continue
            entries.append(
                NYCourtPassDocketEntry(
                    filing_type=cells[0].text_content().strip(),
                    party=cells[1].text_content().strip() or None,
                    date_due=_parse_date_mdy(cells[2].text_content()),
                    date_received=_parse_date_mdy(cells[3].text_content()),
                )
            )
        return entries

    def _parse_attorneys(self, page: PageElement) -> list[NYCourtPassAttorney]:
        att_tables = page.query_xpath(
            f"{self.SPAN_XPATH}"
            "//table[.//strong[contains(text(),'ATTORNEY DETAILS')]]",
            "attorney table",
            min_count=0,
        )
        if not att_tables:
            return []
        all_rows = att_tables[0].query_xpath(
            ".//tr", "attorney rows", min_count=0
        )
        attorneys: list[NYCourtPassAttorney] = []
        current: dict[str, str | None] = {}
        for row in all_rows:
            cells = row.query_xpath("td", "cells", min_count=0)
            if not cells:
                continue

            first_text = cells[0].text_content().strip()
            if "ATTORNEY DETAILS" in first_text:
                continue

            colspan = cells[0].get_attribute("colspan")
            if colspan and int(colspan) >= 2:
                if current.get("party_name"):
                    attorneys.append(self._build_attorney(current))
                current = {}
                continue

            if len(cells) < 2:
                continue

            label = cells[0].text_content().strip().rstrip(":")
            value = cells[1].text_content().strip()

            if label == "Party Name":
                if current.get("party_name"):
                    attorneys.append(self._build_attorney(current))
                current = {
                    "party_name": value,
                    "party_role": "",
                    "firm": None,
                    "attorney_name": None,
                    "address": None,
                    "phone": None,
                }
            elif label == "Party Role":
                current["party_role"] = value
            elif label == "Firm":
                current["firm"] = value or None
            elif label == "Attorney":
                current["attorney_name"] = value or None
            elif label == "Address":
                current["address"] = value or None
            elif label == "Phone":
                current["phone"] = value.strip() or None
            elif not label and value and current.get("address"):
                current["address"] += "\n" + value

        if current.get("party_name"):
            attorneys.append(self._build_attorney(current))
        return attorneys

    @staticmethod
    def _build_attorney(raw: dict) -> NYCourtPassAttorney:
        return NYCourtPassAttorney(
            party_name=raw["party_name"],
            party_role=raw.get("party_role", ""),
            firm=raw.get("firm"),
            attorney_name=raw.get("attorney_name"),
            address=raw.get("address"),
            phone=raw.get("phone"),
        )


class DocketResultsParser(KentParser[NYCourtPassDocket]):
    """Parse each row of the ``gvResults`` docket search grid.

    Returns one ``DeferredValidation[NYCourtPassDocket]`` per data row,
    carrying the fields that survive into NYCourtPassDocket:
    ``case_short_name``, ``argument_date``, ``aria_case_info``, plus
    ``search_row`` (the 0-based row index within this page). The step
    injects ``search_page`` from accumulated_data and generates
    ``temp_case_id``.

    Rows whose argument date is outside the requested range are still
    returned; date-range filtering remains in the step so it can also
    skip yielding the row's navigation submit.
    """

    def __call__(
        self, page: PageElement
    ) -> list[DeferredValidation[NYCourtPassDocket]]:
        data_rows = page.query_xpath(
            "//table[contains(@id, 'gvResults')]"
            "//tr[.//input[contains(@id, 'btnSelect')]]",
            "docket data rows",
            min_count=0,
        )
        results: list[DeferredValidation[NYCourtPassDocket]] = []
        for i, row in enumerate(data_rows):
            cells = row.query_xpath("td", "row cells", min_count=0)
            if len(cells) < 3:
                continue
            case_title = " ".join(cells[1].text_content().split())
            argument_date_str = cells[2].text_content().strip()
            select_buttons = row.query_xpath(
                ".//input[contains(@id, 'btnSelect')]",
                "select button",
                min_count=0,
            )
            aria_case_info = (
                select_buttons[0].get_attribute("aria-label")
                if select_buttons
                else None
            )
            results.append(
                NYCourtPassDocket.raw(
                    case_short_name=case_title or None,
                    argument_date=_parse_date_mdy(argument_date_str),
                    aria_case_info=aria_case_info,
                    search_row=i,
                )
            )
        return results
