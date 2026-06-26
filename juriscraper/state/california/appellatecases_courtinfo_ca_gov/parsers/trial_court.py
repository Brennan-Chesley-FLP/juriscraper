"""Parser for the Trial Court / Lower Court tab (``parse_trial_court``).

Court of Appeal cases expose a flat ``Trial Court Name`` / ``County`` /
``Judge`` block (``CaAppTrialCourtInfo``). Supreme Court cases expose a
richer Lower Court block that can list several linked Court-of-Appeal cases
and several trial courts (``CaAppLowerCourtInfo``), so the parser branches
on ``is_supreme`` and returns the matching single-element list.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from jkent.common.deferred_validation import DeferredValidation
from jkent.common.parser import JKentParser
from jkent.data_types import XPath

from juriscraper.state.california.appellatecases_courtinfo_ca_gov.models import (
    CaAppLowerCourtInfo,
    CaAppTrialCourtInfo,
)

from ._common import clean_text, fields_from_definition_list, parse_date

if TYPE_CHECKING:
    from jkent.common.page_element import PageElement

_TrialCourt = CaAppTrialCourtInfo | CaAppLowerCourtInfo


class TrialCourtParser(JKentParser[_TrialCourt]):
    """Extract trial-court / lower-court info.

    ``from_string`` exercises the Court-of-Appeal layout; construct
    ``TrialCourtParser(is_supreme=True)`` for the Supreme Court Lower
    Court tab.
    """

    def __init__(self, is_supreme: bool = False) -> None:
        self.is_supreme = is_supreme

    def __call__(
        self, page: PageElement
    ) -> list[DeferredValidation[_TrialCourt]]:
        dts = page.query(XPath("//dl/dt"), "tc definition terms", min_count=0)
        dds = page.query(XPath("//dl/dd"), "tc definition values", min_count=0)
        if self.is_supreme:
            return [self._parse_supreme(dts, dds)]
        return [self._parse_coa(dts, dds)]

    @staticmethod
    def _parse_coa(dts, dds) -> DeferredValidation[CaAppTrialCourtInfo]:
        fields = fields_from_definition_list(dts, dds)
        return CaAppTrialCourtInfo.raw(
            trial_court_name=clean_text(fields.get("Trial Court Name")),
            county=clean_text(fields.get("County")),
            trial_court_case_number=clean_text(
                fields.get("Trial Court Case Number")
            ),
            trial_court_judge=clean_text(fields.get("Trial Court Judge")),
            judgment_date=parse_date(fields.get("Trial Court Judgment Date")),
        )

    @staticmethod
    def _parse_supreme(dts, dds) -> DeferredValidation[CaAppLowerCourtInfo]:
        fields = fields_from_definition_list(dts, dds)

        coa_cases: list[dict] = []
        trial_courts: list[dict[str, str | None]] = []
        current_district: str | None = None
        current_trial_court: str | None = None

        for dt_el, dd_el in zip(dts, dds):
            key = dt_el.text_content().strip().rstrip(":")
            if key == "Court of Appeal District/Division":
                current_district = clean_text(dd_el.text_content())
            elif key == "Court of Appeal Case Number":
                links = dd_el.find_links(
                    XPath(".//a[contains(@href, 'searchResults.cfm')]"),
                    "CoA case link",
                    min_count=0,
                )
                coa_cases.append(
                    {
                        "district_division": current_district,
                        "docket_number": links[0].text if links else None,
                        "case_link": links[0].url if links else None,
                        "is_lead": "(lead)" in dd_el.text_content(),
                    }
                )
                current_district = None
            elif key == "Trial Court":
                current_trial_court = clean_text(dd_el.text_content())
            elif key == "Trial Court Case Number":
                trial_courts.append(
                    {
                        "name": current_trial_court,
                        "case_number": clean_text(dd_el.text_content()),
                    }
                )
                current_trial_court = None

        return CaAppLowerCourtInfo.raw(
            coa_cases=coa_cases,
            coa_disposition=clean_text(fields.get("Disposition")),
            coa_disposition_date=parse_date(fields.get("Disposition Date")),
            trial_courts=trial_courts,
        )
