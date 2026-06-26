"""Parser for the DC C-Track case-detail page (``caseView.do?csIID=N``)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from jkent.common.deferred_validation import DeferredValidation
from jkent.common.parser import JKentParser
from jkent.data_types import XPath

from juriscraper.state.common.ctrack import (
    parse_label_value_table,
    parse_mmddyyyy,
)
from juriscraper.state.district_of_columbia.efile_dcappeals_gov.models import (  # noqa: E501
    DCAppDocket,
    DCAppDocketEntry,
    DCAppParty,
)

from ._common import DOC_ICON_NAME_RE, normalize_whitespace, parse_yn

if TYPE_CHECKING:
    from jkent.common.page_element import PageElement


def read_hidden_csiid(page: PageElement) -> str:
    """Read the page's ``<input type="hidden" name="csIID">``.

    The case-detail page carries a hidden form input with the case's
    site-internal ``csIID``. This is the only reliable in-body source on
    the direct case-number lookup path — ``response.url`` reports the
    original POST URL, not the redirected detail-page URL.
    """
    inputs = page.query(
        XPath("//input[@type='hidden' and @name='csIID']"),
        "csIID hidden input",
        min_count=0,
        max_count=1,
    )
    if not inputs:
        return ""
    return inputs[0].get_attribute("value") or ""


class CaseDetailParser(JKentParser[DCAppDocket]):
    """Parse one DC case-detail page into a single ``DCAppDocket``.

    Reads the case-info label/value table (DC uses lowercase
    ``class="label"``), the 6-column Party Information table, and the
    5-column Events table. ``site_case_id`` and ``source_url`` are filled
    by the calling step (the case#-search path arrives here via a 302
    that hides the final URL).
    """

    def __call__(
        self, page: PageElement
    ) -> list[DeferredValidation[DCAppDocket]]:
        case_info = parse_label_value_table(page, label_class="label")

        return [
            DCAppDocket.raw(
                docket_number=self._docket_number_from_title(page),
                court="dc",
                case_name=case_info.get("Short Caption") or None,
                classification=case_info.get("Classification") or None,
                case_status=case_info.get("Case Status") or None,
                lower_court_case_number=case_info.get(
                    "Superior Court or Agency Case Number"
                )
                or None,
                date_filed=parse_mmddyyyy(case_info.get("Filed Date")),
                date_opening_event=parse_mmddyyyy(
                    case_info.get("Opening Event Date")
                ),
                date_record_completed=parse_mmddyyyy(
                    case_info.get("Record Completed")
                ),
                date_briefs_completed=parse_mmddyyyy(
                    case_info.get("Briefs Completed")
                ),
                date_argued=parse_mmddyyyy(case_info.get("Argued/Submitted")),
                date_mandate_issued=parse_mmddyyyy(
                    case_info.get("Mandate Issued")
                ),
                disposition=case_info.get("Disposition") or None,
                next_scheduled_action=case_info.get("Next Scheduled Action")
                or None,
                post_decision_matter_pending=case_info.get(
                    "Post-Decision Matter Pending"
                )
                or None,
                costs_waived=self._costs_waived(page),
                parties=self._parties(page),
                docket_entries=self._events(page),
            )
        ]

    @staticmethod
    def _docket_number_from_title(page: PageElement) -> str | None:
        """Recover the appellate case number from the page title.

        The title is rendered as ``"26-CV-0339: Case View"``; we lift the
        bit before the colon.
        """
        titles = page.query_strings(
            XPath("//title/text()"), "page title", min_count=0, max_count=1
        )
        if titles:
            head = titles[0].split(":", 1)[0].strip()
            if head:
                return head
        return None

    @staticmethod
    def _costs_waived(page: PageElement) -> bool:
        """True iff the case-info table carries a ``Costs Waived`` row.

        The flag is rendered as a label-only column in a row with no
        accompanying value cell, so it doesn't show up in the
        label/value dict.
        """
        cells = page.query(
            XPath("//td[normalize-space(.)='Costs Waived']"),
            "Costs Waived flag",
            min_count=0,
            max_count=1,
        )
        return bool(cells)

    def _parties(self, page: PageElement) -> list[DCAppParty]:
        """Parse the Party Information table.

        The party table sits under a ``<td>Party Information</td>`` title
        row. Header row: ``Appellate Role | Party Name | IFP |
        Attorney(s) | Arguing Attorney | E-Filer``. Each subsequent
        ``<tr>`` is one party, but party rows with multiple attorneys
        wrap the trailing three columns in a nested ``<table>`` that
        contains one row per attorney + the per-attorney IFP/E-Filer
        flags.
        """
        title_cells = page.query(
            XPath("//td[normalize-space(.)='Party Information']"),
            "Party Information title",
            min_count=0,
            max_count=1,
        )
        if not title_cells:
            return []

        header_rows = page.query(
            XPath("//td[normalize-space(.)='Appellate Role']/ancestor::tr[1]"),
            "Party header row",
            min_count=0,
            max_count=1,
        )
        if not header_rows:
            return []

        data_rows = header_rows[0].query(
            XPath("./following-sibling::tr"),
            "party data rows",
            min_count=0,
        )

        parties: list[DCAppParty] = []
        for row in data_rows:
            cells = row.query(XPath("./td"), "party cells", min_count=0)
            if len(cells) < 3:
                # Could be a footer / spacer row.
                continue
            role = normalize_whitespace(cells[0].text_content())
            name = normalize_whitespace(cells[1].text_content())
            if not role or not name:
                continue

            attorneys, arguing, e_filer = self._parse_attorney_cells(cells[3:])
            parties.append(
                DCAppParty(
                    role=role,
                    name=name,
                    ifp=parse_yn(self._cell_text(cells, 2)),
                    attorneys=attorneys,
                    arguing_attorney=arguing,
                    e_filer=e_filer,
                )
            )
        return parties

    @staticmethod
    def _cell_text(cells: list[PageElement], index: int) -> str:
        if index >= len(cells):
            return ""
        return normalize_whitespace(cells[index].text_content())

    def _parse_attorney_cells(
        self, trailing_cells: list[PageElement]
    ) -> tuple[list[str], str | None, bool | None]:
        """Extract attorneys + arguing-attorney + e-filer from the last
        three party-row columns.

        Two row shapes are observed:

        - **Flat row**: 6 top-level cells, columns 3..5 are
          ``Attorney(s)``, ``Arguing Attorney``, ``E-Filer``. We read
          them directly.
        - **Nested-attorney row**: column 3 contains a ``<table>`` with
          one row per attorney; each nested row has 3 cells
          (``Attorney name``, ``IFP/Arguing flag``, ``E-Filer flag``).
          We collect every attorney name and treat the last row's flags
          as the party's ``e_filer`` value.
        """
        if not trailing_cells:
            return [], None, None

        first = trailing_cells[0]
        nested_tables = first.query(
            XPath("./table"), "nested attorney table", min_count=0, max_count=1
        )
        if nested_tables:
            attorneys: list[str] = []
            e_filer_value: bool | None = None
            arguing_value: str | None = None
            inner_rows = nested_tables[0].query(
                XPath(".//tr"), "nested attorney rows", min_count=0
            )
            for inner in inner_rows:
                inner_cells = inner.query(
                    XPath("./td"), "nested attorney cells", min_count=0
                )
                if not inner_cells:
                    continue
                name = normalize_whitespace(inner_cells[0].text_content())
                if not name:
                    continue
                attorneys.append(name)
                # Flags propagate from each row; the last row wins.
                if len(inner_cells) >= 3:
                    e_filer_value = parse_yn(inner_cells[-1].text_content())
                if len(inner_cells) >= 2:
                    middle = normalize_whitespace(
                        inner_cells[-2].text_content()
                    )
                    if middle and middle.upper() not in {"Y", "N"}:
                        arguing_value = middle
            return attorneys, arguing_value, e_filer_value

        # Flat-row case.
        attorney_cell_text = normalize_whitespace(first.text_content())
        attorneys = (
            [attorney_cell_text]
            if attorney_cell_text and attorney_cell_text.lower() != "pro se"
            else (["Pro Se"] if attorney_cell_text else [])
        )
        arguing = self._cell_text(trailing_cells, 1) or None
        e_filer = parse_yn(self._cell_text(trailing_cells, 2))
        return attorneys, arguing, e_filer

    def _events(self, page: PageElement) -> list[DCAppDocketEntry]:
        """Parse the Events table (the docket).

        The events table sits under a ``<td>Events</td>`` title row and
        has 5 columns: Event Date | Status | Description | Result | PDF.
        Data rows are identified by an MM/DD/YYYY first cell; this avoids
        accidentally picking up the header row or any spacer rows.
        Document icons in the PDF cell encode
        ``name="{flag}:{deID}:{csIID}"``.
        """
        events_titles = page.query(
            XPath("//td[normalize-space(.)='Events']"),
            "Events title",
            min_count=0,
            max_count=1,
        )
        if not events_titles:
            return []
        title_rows = events_titles[0].query(
            XPath("./ancestor::tr[1]"),
            "Events title row",
            min_count=1,
            max_count=1,
        )
        data_rows = title_rows[0].query(
            XPath("./following-sibling::tr"), "event rows", min_count=0
        )

        entries: list[DCAppDocketEntry] = []
        for row in data_rows:
            cells = row.query(XPath("./td"), "event cells", min_count=0)
            if len(cells) < 5:
                continue
            event_date = parse_mmddyyyy(self._cell_text(cells, 0))
            if event_date is None:
                # Header row or spacer.
                continue

            doc_imgs = cells[4].query(
                XPath(".//img[contains(@class, 'documentLink')]"),
                "doc icon",
                min_count=0,
                max_count=1,
            )
            event_id: str | None = None
            doc_flag: str | None = None
            has_documents = False
            if doc_imgs:
                match = DOC_ICON_NAME_RE.match(
                    doc_imgs[0].get_attribute("name") or ""
                )
                if match:
                    doc_flag = match.group(1)
                    event_id = match.group(2)
                    has_documents = True

            entries.append(
                DCAppDocketEntry(
                    date_filed=event_date,
                    status=self._cell_text(cells, 1) or None,
                    description=self._cell_text(cells, 2),
                    result=self._cell_text(cells, 3) or None,
                    event_id=event_id,
                    document_link_flag=doc_flag,
                    has_documents=has_documents,
                )
            )
        return entries
