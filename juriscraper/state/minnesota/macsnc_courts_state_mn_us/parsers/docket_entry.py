"""Parser for a P-MACS docket-entry detail page (``docketEntry.do``).

The page repeats the parent case info up top (label cells use
``class="label"``, lowercase) and then renders an entry-specific section
(``class="Label"``, uppercase). :class:`DocketEntryParser` scopes to the
uppercase section to harvest the entry's label/value fields, and pulls
every ``document.do`` anchor into one :class:`MnDocument` per file. The
step owns the archive fan-out and the typed-field promotion onto the
existing :class:`MnDocketEntry`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from urllib.parse import urljoin

from jkent.common.deferred_validation import DeferredValidation
from jkent.common.parser import JKentParser
from jkent.data_types import XPath

from juriscraper.state.minnesota.macsnc_courts_state_mn_us.models import (
    MnDocketEntry,
    MnDocument,
)

from ._common import (
    MULTI_VALUE_SEP,
    normalize_ws,
    parse_date,
    radio_tail_text,
)

if TYPE_CHECKING:
    from jkent.common.page_element import PageElement


class DocketEntryParser(JKentParser[MnDocument]):
    """Parse a docket-entry detail page.

    ``__call__`` returns one ``DeferredValidation[MnDocument]`` per
    ``document.do`` anchor on the page (these are the per-record output).
    :meth:`parse_detail_fields` separately returns the entry-section
    label/value map, which the step folds onto the parent entry via
    :func:`populate_entry_typed_fields`.

    ``base_url`` (the page URL) absolutises the document hrefs; pass it on
    construction. ``doc_entry_id`` is the parent entry's ``deID`` and is
    stamped onto every returned ``MnDocument``.
    """

    def __init__(self, base_url: str = "", doc_entry_id: str | None = None):
        self._base_url = base_url
        self._doc_entry_id = doc_entry_id

    def __call__(
        self, page: PageElement
    ) -> list[DeferredValidation[MnDocument]]:
        anchors = page.query(
            XPath("//a[contains(@href, '/ctrack/document.do?document=')]"),
            "document.do download anchors",
            min_count=0,
        )
        documents: list[DeferredValidation[MnDocument]] = []
        for anchor in anchors:
            href = anchor.get_attribute("href")
            if not href:
                continue
            absolute = urljoin(self._base_url, href)
            label = normalize_ws(anchor.text_content())
            documents.append(
                MnDocument.raw(
                    label=label or "(unlabeled)",
                    document_url=absolute,
                    doc_entry_id=self._doc_entry_id,
                )
            )
        return documents

    def parse_detail_fields(self, page: PageElement) -> dict[str, str]:
        """Return every label / value pair from the entry-specific section.

        The case-info repeat at the top uses ``class="label"`` (lowercase);
        the entry section uses ``class="Label"`` (uppercase). We scope to
        the uppercase variant via exact match.

        Each value cell can render as one or more ``<option selected>``,
        one or more ``<input type=radio checked>``, or plain text.
        """
        label_cells = page.query(
            XPath("//td[@class='Label']"),
            "entry-section label cells",
            min_count=0,
        )
        fields: dict[str, str] = {}
        for label_cell in label_cells:
            label_text = normalize_ws(label_cell.text_content()).rstrip(":")
            if not label_text:
                continue
            value_cells = label_cell.query(
                XPath("./following-sibling::td[1]"),
                "value cell after label",
                min_count=0,
                max_count=1,
            )
            if not value_cells:
                continue
            value = self._extract_field_value(value_cells[0])
            if value:
                fields[label_text] = value
        return fields

    @staticmethod
    def _extract_field_value(cell: PageElement) -> str:
        """Read the displayed value out of a label/value cell.

        Selects: read ``<option selected>`` text(s), joined with
        ``MULTI_VALUE_SEP`` for multi-selects. Radios: the visible label
        is the text following the ``checked`` input. Plain text:
        ``text_content()``.
        """
        selected_opts = cell.query(
            XPath(".//option[@selected]"),
            "selected options",
            min_count=0,
        )
        if selected_opts:
            texts = [normalize_ws(o.text_content()) for o in selected_opts]
            return MULTI_VALUE_SEP.join(t for t in texts if t)

        checked_radios = cell.query(
            XPath(".//input[@type='radio'][@checked]"),
            "checked radio inputs",
            min_count=0,
            max_count=1,
        )
        if checked_radios:
            return radio_tail_text(cell)

        # Empty <select> with no selected option — treat as blank.
        unselected_select = cell.query(
            XPath(".//select"),
            "any select",
            min_count=0,
            max_count=1,
        )
        if unselected_select:
            return ""

        return normalize_ws(cell.text_content())


def populate_entry_typed_fields(
    entry: MnDocketEntry, details: dict[str, str]
) -> None:
    """Promote well-known label/value pairs into typed fields on ``entry``.

    Unknown labels remain only in ``entry.details``.
    """
    entry.entry_status = details.get("Status") or None
    entry.thread_to = details.get("Thread to") or None
    entry.method_of_receipt = details.get("Method of Receipt") or None
    entry.method_of_service = details.get("Method of Service") or None
    entry.method_of_payment = details.get("Method of Payment") or None
    entry.indicate_service = details.get("Indicate Service") or None
    entry.filing_fee = details.get("Filing Fee") or None
    entry.filing_date_time = details.get("Filing Date") or None
    entry.docket_entry_date_time = details.get("Docket Entry Date") or None
    entry.disposition_type = details.get("Order Disposition Type") or None
    entry.disposition_details = details.get("Disposition Details") or None
    entry.other_signatures = details.get("Other Signatures") or None
    entry.reporters = details.get("Reporter(s)") or None
    entry.date_of_hearings = details.get("Date of Hearing(s)") or None
    entry.comments = details.get("Comments") or None
    entry.other_deficiencies = details.get("Other Deficiencies") or None

    entry.postmark_date = parse_date(
        details.get("Postmark Date (if by mail)") or ""
    )

    filed_by_raw = details.get("Filed By") or ""
    entry.filed_by = (
        [v for v in filed_by_raw.split(MULTI_VALUE_SEP) if v.strip()]
        if filed_by_raw
        else []
    )
    signed_by_raw = details.get("Signed By") or ""
    entry.signed_by = (
        [v for v in signed_by_raw.split(MULTI_VALUE_SEP) if v.strip()]
        if signed_by_raw
        else []
    )
