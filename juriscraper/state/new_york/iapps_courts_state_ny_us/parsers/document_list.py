"""Parser for the NYSCEF Document List page.

URL: ``https://iapps.courts.state.ny.us/nyscef/DocumentList?docketId={id}&display=all``

The documents table (``table[summary~='all documents']``) lists one filed
document per data row: document number, type (a ``ViewDocument`` link) +
description, filer + filed/received dates, and status (+ an optional
confirmation-notice link). Returns one :class:`NYSCEFDocketEntry` per row;
the calling step uses the ``download_url`` / ``confirmation_notice_url`` to
fan out archive downloads. URLs are returned relative to the page; the step
resolves them against the response URL.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from jkent.common.deferred_validation import DeferredValidation
from jkent.common.parser import JKentParser
from jkent.data_types import XPath

from juriscraper.state.new_york.iapps_courts_state_ny_us.models import (
    NYSCEFDocketEntry,
)

from ._common import parse_filed_by_cell

if TYPE_CHECKING:
    from jkent.common.page_element import PageElement


class DocumentListParser(JKentParser[NYSCEFDocketEntry]):
    """Parse the documents table into ``NYSCEFDocketEntry`` rows.

    ``download_url`` / ``confirmation_notice_url`` are the raw ``href``
    values from the page (relative); the step resolves them against the
    response URL before emitting and downloading.
    """

    def __call__(
        self, page: PageElement
    ) -> list[DeferredValidation[NYSCEFDocketEntry]]:
        rows = page.query(
            XPath(
                "//table[contains(@summary, 'all documents')]"
                "//tr[position()>1]"
            ),
            "document rows",
            min_count=0,
        )
        entries: list[DeferredValidation[NYSCEFDocketEntry]] = []
        for row in rows:
            cells = row.query(XPath(".//td"), "document cells", min_count=0)
            if len(cells) < 4:
                continue

            # Cell 0: document number.
            try:
                entry_number = int(cells[0].text_content().strip())
            except ValueError:
                continue

            # Cell 1: document type (ViewDocument link) + description.
            doc_links = cells[1].query(
                XPath(".//a[contains(@href, 'ViewDocument')]"),
                "document link",
                min_count=0,
                max_count=1,
            )
            if doc_links:
                document_type = doc_links[0].text_content().strip()
                download_url = doc_links[0].get_attribute("href") or None
            else:
                document_type = cells[1].text_content().strip()
                download_url = None

            cell1_full = cells[1].text_content().strip()
            description = cell1_full.replace(document_type, "").strip() or None

            # Cell 2: filed by + dates.
            filed_by, date_filed, date_received = parse_filed_by_cell(
                cells[2].text_content().strip()
            )

            # Cell 3: status (+ optional confirmation-notice link).
            status_els = cells[3].query(
                XPath(".//strong"), "status element", min_count=0, max_count=1
            )
            status = (
                status_els[0].text_content().strip() if status_els else None
            )
            cn_links = cells[3].query(
                XPath(".//a[contains(@href, 'ConfirmationNotice')]"),
                "confirmation notice link",
                min_count=0,
                max_count=1,
            )
            confirmation_notice_url = (
                cn_links[0].get_attribute("href") if cn_links else None
            ) or None

            entries.append(
                NYSCEFDocketEntry.raw(
                    entry_number=entry_number,
                    document_type=document_type,
                    description=description,
                    filed_by=filed_by,
                    date_filed=date_filed,
                    date_received=date_received,
                    status=status,
                    download_url=download_url,
                    confirmation_notice_url=confirmation_notice_url,
                )
            )
        return entries
