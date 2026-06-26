"""Parser for the P-MACS ORCA Info page (``publicLowerCourtSummary.jsp``).

The page carries originating-court / agency information for an appellate
case: Appeal From, Court/Agency, Other, the lower-court case
identifiers, related case numbers, and the trial-court decisionmaker(s).
:class:`OrcaInfoParser` returns one :class:`MnOrcaInfo` when at least one
field has a value, otherwise an empty list (empty ORCA pages would
otherwise contribute a stub record with no signal). The calling step
stamps ``source_url`` and attaches the record to the docket.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from jkent.common.deferred_validation import DeferredValidation
from jkent.common.parser import JKentParser
from jkent.data_types import XPath

from juriscraper.state.minnesota.macsnc_courts_state_mn_us.models import (
    MnOrcaInfo,
)

from ._common import extract_label, normalize_ws

if TYPE_CHECKING:
    from jkent.common.page_element import PageElement


class OrcaInfoParser(JKentParser[MnOrcaInfo]):
    """Parse the originating-court summary page into an ``MnOrcaInfo``."""

    def __call__(
        self, page: PageElement
    ) -> list[DeferredValidation[MnOrcaInfo]]:
        appeal_from = extract_label(page, "Appeal From")
        court_agency = extract_label(page, "Court/Agency")
        other = extract_label(page, "Other")
        orig_case_number = extract_label(page, "Orig. Case Number")
        orig_case_title = extract_label(page, "Orig. Case Title")
        related_raw = extract_label(page, "Related Case Number(s)")
        related_case_numbers = (
            [v.strip() for v in re.split(r",\s*", related_raw) if v.strip()]
            if related_raw
            else []
        )
        decisionmakers = self._parse_decisionmakers(page)

        if not any(
            [
                appeal_from,
                court_agency,
                other,
                orig_case_number,
                orig_case_title,
                related_case_numbers,
                decisionmakers,
            ]
        ):
            return []

        return [
            MnOrcaInfo.raw(
                appeal_from_str=appeal_from or None,
                court_agency=court_agency or None,
                other=other or None,
                orig_case_number=orig_case_number or None,
                orig_case_title=orig_case_title or None,
                related_case_numbers=related_case_numbers,
                decisionmakers=decisionmakers,
            )
        ]

    def _parse_decisionmakers(self, page: PageElement) -> list[str]:
        """Collect every name under the ``Decisionmaker(s)`` subheading.

        Each name lives in a ``<td>`` inside a small inner ``<table>``
        following the subheading row; we anchor on the subheading and
        pick up every leaf ``<td>`` that follows in document order until
        another subheading.
        """
        names: list[str] = []
        anchor_nodes = page.query(
            XPath(
                "//tr[contains(@class, 'TableSubHeading')]"
                "/td[contains(normalize-space(), 'Decisionmaker')]"
            ),
            "Decisionmaker(s) subheading",
            min_count=0,
            max_count=1,
        )
        if not anchor_nodes:
            return names

        following = page.query(
            XPath(
                "//tr[contains(@class, 'TableSubHeading')]"
                "/td[contains(normalize-space(), 'Decisionmaker')]"
                "/following::td[normalize-space() and not(*)"
                " and not(ancestor::tr[contains(@class, 'TableSubHeading')])"
                " and not(contains(@class, 'Label'))]"
            ),
            "decisionmaker name cells",
            min_count=0,
        )
        for node in following:
            name = normalize_ws(node.text_content())
            if name and name not in names:
                names.append(name)
        return names
