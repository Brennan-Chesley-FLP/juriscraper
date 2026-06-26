"""Parsers for the trial-court ``civilinquiry`` ``PublicCaseDetail.aspx`` page.

``TrialCourtCaseParser`` extracts the Superior Court docket (with parties and
attorneys); ``TrialActivitiesParser`` extracts the Motions/Pleadings/Documents
rows. The site prefixes every element id with ``ctl00_ContentPlaceHolder1_…`` so
selectors match by ``contains(@id, …)``. ``docket_number_raw`` and the
``appellate_docket_number`` cross-reference are supplied by the step.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from jkent.common.deferred_validation import DeferredValidation
from jkent.common.parser import JKentParser
from jkent.data_types import XPath

from juriscraper.state.connecticut.appellateinquiry_jud_ct_gov.models import (
    ConnTrialCourtAttorney,
    ConnTrialCourtDocket,
    ConnTrialCourtDocketEntry,
    ConnTrialCourtParty,
)

from ._common import clean_text, juris_number, parse_date, strip_label

if TYPE_CHECKING:
    from jkent.common.page_element import PageElement

# "MAKI LAW LLC  (437597)467 NAUBUC AVENUE ..." -> firm before "(", juris digits.
_FIRM_RE = re.compile(r"^(.*?)\s*\((\d+)\)")

_PARTY_TYPE_BY_PREFIX = {
    "P": "Plaintiff",
    "D": "Defendant",
    "L": "For Notice Only",
}


def _ends_with_text(page: PageElement, id_suffix: str) -> str | None:
    """Cleaned text of the span whose id *ends with* ``id_suffix``.

    civilinquiry prefixes every id with ``ctl00_ContentPlaceHolder1_…`` and
    pairs each value span (``…lblBasicCaseType``) with a label span
    (``…lblBasicCaseTypeTitle``). A ``contains`` match would grab the label
    (it sorts first in document order), so we anchor on the end of the id.
    """
    elems = page.query(
        XPath(
            f"//span[substring(@id, string-length(@id) - "
            f"{len(id_suffix) - 1}) = '{id_suffix}']"
        ),
        f"span id ends with {id_suffix}",
        min_count=0,
    )
    return clean_text(elems[0].text_content()) if elems else None


class TrialCourtCaseParser(JKentParser[ConnTrialCourtDocket]):
    """Parse one civilinquiry ``PublicCaseDetail.aspx`` page."""

    def __call__(
        self, page: PageElement
    ) -> list[DeferredValidation[ConnTrialCourtDocket]]:
        case_type_full = _ends_with_text(page, "lblBasicCaseType")
        case_type = None
        if case_type_full and " - " in case_type_full:
            case_type = case_type_full.split(" - ", 1)[0].strip()
        elif case_type_full:
            case_type = case_type_full

        docket = ConnTrialCourtDocket.raw(
            docket_number=_ends_with_text(page, "lblDocketNo") or "Unknown",
            case_name=_ends_with_text(page, "lblCaseCaption") or "Unknown",
            case_type=case_type,
            case_type_description=case_type_full,
            court_location=_ends_with_text(page, "lblBasicLocation"),
            list_type=_ends_with_text(page, "lblBasicListType"),
            date_filed=parse_date(
                strip_label(_ends_with_text(page, "lblFileDate"))
            ),
            return_date=parse_date(
                strip_label(_ends_with_text(page, "lblReturnDate"))
            ),
            date_disposed=parse_date(
                _ends_with_text(page, "lblBasicDispositionDate")
            ),
            disposition=_ends_with_text(page, "lblBasicDisposition"),
            assigned_to_str=_ends_with_text(page, "lblBasicDispJudge"),
            date_last_filing=parse_date(
                _ends_with_text(page, "lblBasicLastAction")
            ),
            parties=self._parse_parties(page),
        )
        return [docket]

    @staticmethod
    def _parse_parties(page: PageElement) -> list[ConnTrialCourtParty]:
        rows = page.query(
            XPath(
                "//table[contains(@id, 'gvParties')]//tr"
                "[.//span[contains(@id, 'lblPlaintDefPartyNo')]]"
            ),
            "trial party rows",
            min_count=0,
        )
        parties: list[ConnTrialCourtParty] = []
        for row in rows:
            num_spans = row.query(
                XPath(".//span[contains(@id, 'lblPlaintDefPartyNo')]"),
                "party number",
                min_count=1,
                max_count=1,
            )
            party_number = clean_text(num_spans[0].text_content())
            name_spans = row.query(
                XPath(".//span[contains(@id, 'lblPtyPartyName')]"),
                "party name",
                min_count=0,
            )
            name = (
                clean_text(name_spans[0].text_content())
                if name_spans
                else None
            )
            if not party_number or not name:
                continue

            party_type = _PARTY_TYPE_BY_PREFIX.get(party_number[0].upper())
            self_rep = bool(
                row.query(
                    XPath(
                        ".//span[contains(@id, 'lblAppearanceTitle')]"
                        "[contains(text(), 'Self-Rep')]"
                    ),
                    "self-represented indicator",
                    min_count=0,
                )
            )
            non_appearing = bool(
                row.query(
                    XPath(".//span[contains(@id, 'lblNonAppearing')]"),
                    "non-appearing indicator",
                    min_count=0,
                )
            )

            attorneys: list[ConnTrialCourtAttorney] = []
            info1 = row.query(
                XPath(".//span[contains(@id, 'lblAppearanceInfo1')]"),
                "attorney appearance info",
                min_count=0,
            )
            info2 = row.query(
                XPath(".//span[contains(@id, 'lblAppearanceInfo2')]"),
                "attorney appearance date",
                min_count=0,
            )
            for idx, info in enumerate(info1):
                contact_raw = clean_text(info.text_content())
                if not contact_raw:
                    continue
                firm = None
                juris = None
                fm = _FIRM_RE.match(contact_raw)
                if fm:
                    firm = clean_text(fm.group(1))
                    juris = fm.group(2)
                else:
                    juris = juris_number(contact_raw)
                date_filed = (
                    parse_date(strip_label(info2[idx].text_content()))
                    if idx < len(info2)
                    else None
                )
                attorneys.append(
                    ConnTrialCourtAttorney(
                        firm=firm,
                        juris_number=juris,
                        contact_raw=contact_raw,
                        date_filed=date_filed,
                    )
                )

            parties.append(
                ConnTrialCourtParty(
                    party_number=party_number,
                    name=name,
                    party_type=party_type,
                    self_represented=self_rep,
                    non_appearing=non_appearing,
                    attorneys=attorneys,
                )
            )
        return parties


class TrialActivitiesParser(JKentParser[ConnTrialCourtDocketEntry]):
    """Parse the trial-court documents table (``gvDocuments``).

    Columns: Entry No, File Date, Filed By, Description, Arguable. The
    Description cell carries the document link, additional description, and
    result. ``trial_docket_number`` is supplied by the step; the document href
    is captured relative and resolved by the step.
    """

    def __call__(
        self, page: PageElement
    ) -> list[DeferredValidation[ConnTrialCourtDocketEntry]]:
        rows = page.query(
            XPath("//table[contains(@id, 'gvDocuments')]//tr[td]"),
            "trial document rows",
            min_count=0,
        )
        entries: list[DeferredValidation[ConnTrialCourtDocketEntry]] = []
        for row in rows:
            cells = row.query(XPath("./td"), "document cells", min_count=0)
            if len(cells) < 4:
                continue

            entry_number = clean_text(cells[0].text_content())
            date_filed = parse_date(cells[1].text_content())

            filed_by_spans = cells[2].query(
                XPath(".//span[contains(@id, 'lblFiledBy')]"),
                "filed by",
                min_count=0,
            )
            filed_by = (
                clean_text(filed_by_spans[0].text_content())
                if filed_by_spans
                else clean_text(cells[2].text_content())
            )

            doc_links = cells[3].query(
                XPath(".//a[contains(@id, 'hlnkDocument')]"),
                "document link",
                min_count=0,
            )
            document_url = (
                doc_links[0].get_attribute("href") if doc_links else None
            )
            description = (
                clean_text(doc_links[0].text_content())
                if doc_links
                else clean_text(cells[3].text_content())
            )
            add_desc = cells[3].query(
                XPath(".//span[contains(@id, 'lblAddDesc')]"),
                "additional description",
                min_count=0,
            )
            result = cells[3].query(
                XPath(".//span[contains(@id, 'lblResult')]"),
                "result",
                min_count=0,
            )
            arguable = False
            if len(cells) > 4:
                arguable = (
                    clean_text(cells[4].text_content()) or ""
                ).lower() == "yes"

            entries.append(
                ConnTrialCourtDocketEntry.raw(
                    entry_number=entry_number,
                    date_filed=date_filed,
                    filed_by=filed_by,
                    description=description,
                    additional_description=(
                        clean_text(add_desc[0].text_content())
                        if add_desc
                        else None
                    ),
                    result=clean_text(result[0].text_content())
                    if result
                    else None,
                    arguable=arguable,
                    document_url=document_url,
                )
            )
        return entries
