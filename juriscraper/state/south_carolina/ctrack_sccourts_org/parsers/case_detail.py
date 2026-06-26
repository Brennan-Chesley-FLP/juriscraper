"""Parser for the SC C-Track case-detail page (``caseView.do?csIID=N``)."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from jkent.common.deferred_validation import DeferredValidation
from jkent.common.parser import JKentParser
from jkent.data_types import XPath

from juriscraper.state.common.ctrack import (
    parse_label_value_table,
    parse_mmddyyyy,
)
from juriscraper.state.south_carolina.ctrack_sccourts_org.models import (
    SCAppDocket,
    SCAppDocketEntry,
    SCAppParty,
)

from ._common import COURT_NAME_TO_COURT, DEID_RE, normalize_whitespace

if TYPE_CHECKING:
    from jkent.common.page_element import PageElement


class CaseDetailParser(JKentParser[SCAppDocket]):
    """Parse one SC case-detail page into a single ``SCAppDocket``.

    Reads the case-info label/value table, the Party Information table,
    and the Event Information table. ``site_case_id`` and ``source_url``
    are not reliably on the page (the case#-search path lands here via a
    302 that hides the final URL), so the calling step fills those in.
    """

    def __call__(
        self, page: PageElement
    ) -> list[DeferredValidation[SCAppDocket]]:
        case_info = parse_label_value_table(page, label_class="Label")

        return [
            SCAppDocket.raw(
                docket_number=self._docket_number(page),
                court=COURT_NAME_TO_COURT.get(case_info.get("Court", "")),
                case_name=case_info.get("Short Title") or None,
                case_name_full=self._full_title(page),
                classification=case_info.get("Classification") or None,
                case_status=case_info.get("Case Status") or None,
                consolidated=case_info.get("Consolidated") or None,
                date_filed=parse_mmddyyyy(case_info.get("Filed Date")),
                date_argued=parse_mmddyyyy(
                    case_info.get("Oral Argument Date")
                ),
                date_disposed=parse_mmddyyyy(
                    case_info.get("Disposition Date")
                ),
                disposition_type=case_info.get("Disposition Type") or None,
                date_remittitur=parse_mmddyyyy(
                    case_info.get("Remittitur Date")
                ),
                appeal_from_str=case_info.get("Lower Court or Tribunal")
                or None,
                parties=self._parties(page),
                docket_entries=self._events(page),
            )
        ]

    def _docket_number(self, page: PageElement) -> str | None:
        spans = page.query(
            XPath("//span[@id='csNumber']"),
            "csNumber span",
            min_count=0,
            max_count=1,
        )
        if not spans:
            return None
        return normalize_whitespace(spans[0].text_content()) or None

    def _full_title(self, page: PageElement) -> str | None:
        divs = page.query(
            XPath("//div[@id='fullTitle']"),
            "fullTitle div",
            min_count=0,
            max_count=1,
        )
        if not divs:
            return None
        return normalize_whitespace(divs[0].text_content()) or None

    def _parties(self, page: PageElement) -> list[SCAppParty]:
        """Parse the Party Information table (``id='partyInfo'``)."""
        rows = page.query(
            XPath("//table[@id='partyInfo']//tbody//tr"),
            "party rows",
            min_count=0,
        )
        parties: list[SCAppParty] = []
        for row in rows:
            # Subheading rows carry `class="TableSubHeading"` and 4 cells
            # of column titles ("Appellate Role" / "Party Name" / ...).
            if "tablesubheading" in (row.get_attribute("class") or "").lower():
                continue
            cells = row.query(XPath(".//td"), "party cells", min_count=0)
            if len(cells) < 4:
                continue
            role = normalize_whitespace(cells[0].text_content())
            name = normalize_whitespace(cells[1].text_content())
            if not (role and name):
                continue
            former = normalize_whitespace(cells[2].text_content()).upper()
            attorneys = [
                normalize_whitespace(part)
                for part in re.split(r"[\r\n]+", cells[3].text_content() or "")
                if part.strip()
            ]
            parties.append(
                SCAppParty(
                    role=role,
                    name=name,
                    is_former=former == "Y",
                    attorneys=attorneys,
                )
            )
        return parties

    def _events(self, page: PageElement) -> list[SCAppDocketEntry]:
        """Parse the Event Information table.

        The events table is the third ``class="FormTable"`` table on the
        page (after the case-info and parties tables) and has three
        columns: Filed Date, Event Information, Doc. We locate event rows
        by structure — a TR with exactly three TDs whose first TD reads
        ``MM/DD/YYYY`` — which is robust to the table lacking a stable
        id/class.
        """
        rows = page.query(
            XPath(
                "//tr[count(./td)=3 and "
                "translate(normalize-space(./td[1]/text()),"
                "'0123456789','') = '//']"
            ),
            "event rows",
            min_count=0,
        )
        entries: list[SCAppDocketEntry] = []
        for row in rows:
            cells = row.query(XPath(".//td"), "event cells", min_count=3)

            event_id: str | None = None
            has_documents = False
            doc_imgs = cells[2].query(
                XPath(".//img[contains(@class, 'documentLink')]"),
                "doc icons",
                min_count=0,
                max_count=1,
            )
            if doc_imgs:
                deid_match = DEID_RE.search(
                    doc_imgs[0].get_attribute("name") or ""
                )
                if deid_match:
                    event_id = deid_match.group(1)
                    has_documents = True

            entries.append(
                SCAppDocketEntry(
                    date_filed=parse_mmddyyyy(
                        normalize_whitespace(cells[0].text_content())
                    ),
                    description=normalize_whitespace(cells[1].text_content()),
                    event_id=event_id,
                    has_documents=has_documents,
                )
            )
        return entries
