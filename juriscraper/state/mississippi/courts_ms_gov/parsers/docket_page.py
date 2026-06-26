"""Parser for the Mississippi docket page (``docket_type=docket``).

The case-header response renders the public docket number, the caption, and
the register of actions (``<tr class="entry">`` rows, each optionally paired
with a ``<tr class="dockpdf-N">`` PDF-link sibling) as an HTML fragment.

:class:`DocketPageParser.__call__` returns one partial
:class:`MsAppDocket` carrying the header scalars + parsed entries; the
``court``, ``case_num``, and ``source_url`` are stamped by the calling step
(the fragment carries the case number only as the public docket string).
:meth:`DocketPageParser.documents` extracts the PDF references separately so
the step can schedule each as an archive request.
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING
from urllib.parse import urljoin

from jkent.common.deferred_validation import DeferredValidation
from jkent.common.parser import JKentParser
from jkent.data_types import XPath

from juriscraper.state.mississippi.courts_ms_gov.models import (
    MsAppDocket,
    MsAppDocketEntry,
    MsAppDocument,
)

from ._common import (
    court_from_docket_number,
    extract_file_param,
    parse_date,
    parse_desc_index,
    strip,
)

if TYPE_CHECKING:
    from jkent.common.page_element import PageElement


class DocketPageParser(JKentParser[MsAppDocket]):
    """Parse the case header + docket entries into a partial docket."""

    def __call__(
        self, page: PageElement
    ) -> list[DeferredValidation[MsAppDocket]]:
        docket_number = self._docket_number(page)
        case_name = self._case_name(page)
        entries, earliest_date = self._entries(page)

        docket = MsAppDocket.raw(
            docket_number=docket_number,
            court=court_from_docket_number(docket_number),
            case_name=case_name,
            date_filed=earliest_date,
            entries=entries,
        )
        return [docket]

    # =====================================================================
    # Header
    # =====================================================================

    def _docket_number(self, page: PageElement) -> str:
        cells = page.query(
            XPath("//td[@class='casenum']"),
            "case header cell",
            min_count=1,
            max_count=1,
        )
        return strip(cells[0].text_content())

    def _case_name(self, page: PageElement) -> str:
        # Caption is the distinctive font-size:18px bold cell; the page only
        # has one such cell.
        cells = page.query(
            XPath(
                "//td[contains(@style, 'font-size:18px')"
                " and contains(@style, 'font-weight:bold')]"
            ),
            "case caption cell",
            min_count=1,
            max_count=1,
        )
        return strip(cells[0].text_content())

    # =====================================================================
    # Docket entries
    # =====================================================================

    def _entries(
        self, page: PageElement
    ) -> tuple[list[MsAppDocketEntry], date | None]:
        """Parse each ``<tr class="entry">`` row into an ``MsAppDocketEntry``.

        Returns the entries plus the earliest entry date seen (the site
        exposes no separate filing-date field).
        """
        entries: list[MsAppDocketEntry] = []
        earliest_date: date | None = None

        entry_rows = page.query(
            XPath("//tr[@class='entry']"), "docket entry rows", min_count=0
        )
        for row in entry_rows:
            date_strs = row.query_strings(
                XPath(".//td[@class='DATE']/text()"),
                "entry date",
                min_count=0,
                max_count=1,
            )
            desc_cells = row.query(
                XPath(".//td[contains(@class,'DESCRIPTION')]"),
                "entry description cell",
                min_count=0,
                max_count=1,
            )
            if not desc_cells:
                continue
            description = strip(desc_cells[0].text_content())
            entry_date = parse_date(date_strs[0]) if date_strs else None
            if entry_date and (
                earliest_date is None or entry_date < earliest_date
            ):
                earliest_date = entry_date

            desc_id_attrs = desc_cells[0].query_strings(
                XPath("./@id"), "desc id", min_count=0, max_count=1
            )
            doc_idx = parse_desc_index(
                desc_id_attrs[0] if desc_id_attrs else ""
            )

            entries.append(
                MsAppDocketEntry(
                    date_filed=entry_date,
                    description=description,
                    document_index=doc_idx,
                )
            )
        return entries, earliest_date

    # =====================================================================
    # Documents (PDF references) — extracted for the step to archive
    # =====================================================================

    def documents(
        self,
        page: PageElement,
        *,
        base_url: str,
        docket_number: str,
        case_num: int,
        entries: list[MsAppDocketEntry],
    ) -> list[MsAppDocument]:
        """Extract every referenced PDF as an ``MsAppDocument``.

        PDF rows live as siblings: ``<tr class="dockpdf-N">`` with one
        ``sendPDF.php`` anchor. Each PDF inherits the date of the parent
        docket entry it shares an index with. ``base_url`` is the response
        URL the relative ``href`` is resolved against.
        """
        documents: list[MsAppDocument] = []
        pdf_rows = page.query(
            XPath("//tr[contains(@class,'dockpdf-')]"),
            "pdf entry rows",
            min_count=0,
        )
        for pdf_row in pdf_rows:
            class_attr = (
                pdf_row.query_strings(
                    XPath("./@class"), "pdf class", min_count=0, max_count=1
                )
                or [""]
            )[0]
            doc_idx = parse_desc_index(class_attr)

            anchors = pdf_row.query(
                XPath(".//a[contains(@href, 'sendPDF.php')]"),
                "pdf link",
                min_count=0,
                max_count=1,
            )
            if not anchors:
                continue
            href = anchors[0].query_strings(
                XPath("./@href"), "pdf href", min_count=1, max_count=1
            )[0]
            file_param = extract_file_param(href)
            description = strip(anchors[0].text_content())
            download_url = urljoin(base_url, href)

            # Match back to the parent entry to inherit its date.
            parent_date: date | None = None
            if doc_idx is not None:
                for ent in entries:
                    if ent.document_index == doc_idx:
                        parent_date = ent.date_filed
                        break

            documents.append(
                MsAppDocument(
                    docket_number=docket_number,
                    case_num=case_num,
                    file_name=file_param,
                    download_url=download_url,
                    description=description or None,
                    date_filed=parent_date,
                    document_index=doc_idx,
                )
            )
        return documents
