"""Parser for the SCAD argument-schedule snapshot page.

``/courts/appellate/argument-schedule`` lists the next ~2 weeks of
upcoming Appellate Division oral arguments. It is a single-page snapshot
with no date filter and no pagination.

Page structure: one ``<div class="view-grouping">`` per argument date,
each with a ``view-grouping-header`` ``<h4>`` (the date) and a
``view-grouping-content`` containing alternating
``<span class="secondary-header">`` (location) and ``<ul
class="list-group">`` blocks of cases.

:class:`ArgumentScheduleParser` returns one :class:`NJDocket` per case,
each carrying a single ``Oral Argument`` :class:`NJDocketEntry` and any
brief :class:`NJDocument` links. The scraper step owns the download
fan-out (re-reads ``documents`` for ``archive=True`` requests).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from jkent.common.deferred_validation import DeferredValidation
from jkent.common.parser import JKentParser
from jkent.data_types import XPath

from juriscraper.state.new_jersey.njcourts_gov.models import (
    NJDocket,
    NJDocketEntry,
    NJDocument,
)

from ._common import IMPOUNDED_RE, abs_url, normalise, parse_date

if TYPE_CHECKING:
    from datetime import date

    from jkent.common.page_element import PageElement


class ArgumentScheduleParser(JKentParser[NJDocket]):
    """Parse the SCAD argument-schedule snapshot into upcoming-OA dockets.

    Args:
        court: CourtListener court id stamped onto the dockets and their
            documents (``njsuperctappdiv``).

    Defaults so :meth:`JKentParser.from_string` / ``from_file`` work for
    offline structural tests.
    """

    def __init__(self, court: str = "") -> None:
        self.court = court

    def __call__(
        self, page: PageElement
    ) -> list[DeferredValidation[NJDocket]]:
        out: list[DeferredValidation[NJDocket]] = []
        groupings = page.query(
            XPath("//div[contains(@class, 'view-grouping')]"),
            "argument-schedule groupings",
            min_count=0,
        )
        for grouping in groupings:
            heading = grouping.query(
                XPath(".//h4[contains(@class, 'header-date')]"),
                "date heading",
                min_count=0,
            )
            if not heading:
                continue
            argument_date = parse_date(heading[0].text_content())
            if not argument_date:
                continue

            content = grouping.query(
                XPath(".//div[contains(@class, 'view-grouping-content')]"),
                "content",
                min_count=0,
            )
            if not content:
                continue

            current_location: str | None = None
            children = content[0].query(
                XPath("./*"), "content children", min_count=0
            )
            for child in children:
                tag = (child.tag_name() or "").lower()
                cls = child.get_attribute("class") or ""
                if "secondary-header" in cls:
                    current_location = normalise(child.text_content()) or None
                    continue
                if tag == "ul":
                    cases = child.query(
                        XPath("./li"), "case rows", min_count=0
                    )
                    for case_li in cases:
                        docket = self._parse_case(
                            case_li, argument_date, current_location
                        )
                        if docket is not None:
                            out.append(docket)
        return out

    def _parse_case(
        self,
        case_li: PageElement,
        argument_date: date,
        location: str | None,
    ) -> DeferredValidation[NJDocket] | None:
        bold = case_li.query(
            XPath(".//span[contains(@class, 'fw-bold')]"),
            "docket id span",
            min_count=0,
        )
        if not bold:
            return None
        docket_number = normalise(bold[0].text_content())
        if not docket_number:
            return None

        h6 = case_li.query(
            XPath(".//div[contains(@class, 'h6')]"), "h6", min_count=0
        )
        if not h6:
            return None
        caption_raw = normalise(h6[0].text_content())
        if caption_raw.startswith(docket_number):
            caption_raw = caption_raw[len(docket_number) :].strip()

        impounded_match = IMPOUNDED_RE.search(caption_raw)
        missing_reason: str | None = None
        if impounded_match:
            missing_reason = "RECORD IMPOUNDED"
            caption = caption_raw[: impounded_match.start()].rstrip()
        else:
            caption = caption_raw

        briefs: list[tuple[str, str]] = []
        anchors = case_li.query(
            XPath(".//a[@href]"), "case links", min_count=0
        )
        for a in anchors:
            url = abs_url(a.get_attribute("href"))
            if not url:
                continue
            briefs.append((normalise(a.text_content()) or "Briefs", url))

        documents = [
            NJDocument(
                docket_number=docket_number,
                court=self.court,
                document_url=url,
                description=desc,
            )
            for desc, url in briefs
        ]

        entries = [
            NJDocketEntry(
                description="Oral Argument",
                date_filed=argument_date,
                notes=location,
            )
        ]

        return NJDocket.raw(
            docket_number=docket_number,
            court=self.court,
            case_name=caption or docket_number,
            date_filed=argument_date,
            date_argued=argument_date,
            argument_location=location,
            missing_entries_reason=missing_reason,
            entries=entries,
            documents=documents,
        )
