"""Parser for the Case Summary (General) page."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from jkent.common.parser import JKentParser
from jkent.data_types import XPath

from juriscraper.state.alaska.appellate_records_courts_alaska_gov.models import (
    AkDocket,
)

from ._common import (
    extract_q_token,
    parse_ak_date,
    parse_case_title,
    safe_text,
    text_lines,
)

if TYPE_CHECKING:
    from jkent.common.deferred_validation import DeferredValidation
    from jkent.common.page_element import PageElement

# Oral-argument video links are written as a protocol-relative prefix in
# front of an already-absolute URL (``href="//https://www.ktoo.org/…"``),
# which resolves to an unusable address.
_DOUBLED_SCHEME_RE = re.compile(r"^(?:[a-z][a-z0-9+.-]*:)?//(?=https?://)")


def _clean_video_url(url: str | None) -> str | None:
    """Undo the doubled scheme in an oral-argument video link."""
    if not url:
        return None
    return _DOUBLED_SCHEME_RE.sub("", url)


class CaseGeneralParser(JKentParser[AkDocket]):
    """Parse the Case Summary page into a single ``AkDocket`` fragment.

    Emits only the General-page fields (plus the opinions, lower-court,
    and related-case child lists); the step merges this fragment onto the
    docket built up from the search row. Navigation concerns (tab URLs,
    opinion document downloads) stay in the step.
    """

    def __call__(
        self, page: PageElement
    ) -> list[DeferredValidation[AkDocket]]:
        d: dict = {}

        d.update(parse_case_title(page))
        self._parse_summary_fields(page, d)
        self._parse_oral_argument(page, d)
        self._parse_note(page, d)
        d["opinions"] = self._parse_opinions(page)
        d["lower_court_info"] = self._parse_lower_court(page)
        d["related_cases"] = self._parse_related_cases(page)

        return [AkDocket.raw(**d)]

    # -- sections ---------------------------------------------------------

    def _parse_summary_fields(self, page: PageElement, d: dict) -> None:
        caption = self._dd_text(page, "Full Case Caption")
        if caption:
            d["case_name_full"] = caption
        case_type = self._dd_text(page, "Case Type")
        if case_type:
            d["case_type"] = case_type
        date_filed = parse_ak_date(self._dd_text(page, "Date Filed"))
        if date_filed:
            d["date_filed"] = date_filed

        mgr_els = page.query(
            XPath(
                "//dt[contains(text(), 'Contact Case Manager')]"
                "/following-sibling::dd[1]"
            ),
            "case manager",
            min_count=0,
        )
        if mgr_els:
            manager = " ".join(text_lines(mgr_els[0], "case manager contact"))
            if manager:
                d["contact_case_manager"] = manager
            mailto = mgr_els[0].query_strings(
                XPath(".//a[starts-with(@href, 'mailto:')]/@href"),
                "case manager mailto link",
                min_count=0,
                max_count=1,
            )
            if mailto:
                email = mailto[0].removeprefix("mailto:").split("?", 1)[0]
                if email:
                    d["case_manager_email"] = email

    def _parse_oral_argument(self, page: PageElement, d: dict) -> None:
        status = self._dd_text(page, "Status")
        if status:
            d["oral_argument_status"] = status
        dt = self._dd_text(page, "Date/Time")
        if dt:
            d["oral_argument_datetime"] = dt
        mps = self._dd_text(page, "Min/Side")
        if mps:
            d["oral_argument_min_per_side"] = mps
        loc = self._dd_text(page, "Location")
        if loc:
            d["oral_argument_location"] = loc
        video_links = page.find_links(
            XPath(
                "//dt[contains(text(), 'Video')]/following-sibling::dd[1]//a"
            ),
            "OA video link",
            min_count=0,
        )
        if video_links:
            d["oral_argument_video_url"] = _clean_video_url(video_links[0].url)

    def _parse_note(self, page: PageElement, d: dict) -> None:
        """Capture the free-text note beside the Oral Argument block.

        Notes carry consolidation and argument-time arrangements
        ("Consolidated with S-18044; 20 min per side for both cases"),
        so they are worth keeping verbatim.
        """
        page.query(
            XPath("//div[contains(@class, 'cms-notes-div')]//h4"),
            "note heading",
            min_count=0,
        )
        note_els = page.query(
            XPath("//div[contains(@class, 'cms-note-text')]"),
            "note content",
            min_count=0,
        )
        note = " ".join(
            text for el in note_els if (text := safe_text(el))
        ).strip()
        if note:
            d["note"] = note

    def _parse_opinions(self, page: PageElement) -> list[dict]:
        opinions: list[dict] = []
        rows = page.query(
            XPath(
                "//h5[contains(text(), 'Opinions')]"
                "/following-sibling::table[1]//tbody/tr"
            ),
            "opinion rows",
            min_count=0,
        )
        for row in rows:
            cells = row.query(XPath(".//td"), "opinion cells", min_count=0)
            if len(cells) < 6:
                continue
            doc_links = row.find_links(
                XPath(".//a[contains(@class, 'glyphicon-file')]"),
                "opinion doc link",
                min_count=0,
            )
            opinions.append(
                {
                    "number": safe_text(cells[0]) or None,
                    "opinion_type": safe_text(cells[1]) or None,
                    "decision": safe_text(cells[2]) or None,
                    "opinion_date": parse_ak_date(safe_text(cells[3])),
                    "citation": safe_text(cells[4]) or None,
                    "document_url": doc_links[0].url if doc_links else None,
                }
            )
        return opinions

    def _parse_lower_court(self, page: PageElement) -> list[dict]:
        rows = page.query(
            XPath(
                "//h5[contains(text(), 'Lower Court')]"
                "/following-sibling::table[1]//tbody/tr"
            ),
            "lower court rows",
            min_count=0,
        )
        out: list[dict] = []
        for row in rows:
            cells = row.query(XPath(".//td"), "lower court cells", min_count=0)
            if len(cells) < 5:
                continue
            out.append(
                {
                    "docket_number": safe_text(cells[0]) or None,
                    "judgment_date": parse_ak_date(safe_text(cells[1])),
                    "distribution_date": parse_ak_date(safe_text(cells[2])),
                    "court_or_agency": safe_text(cells[3]) or None,
                    "judge_str": safe_text(cells[4]) or None,
                }
            )
        return out

    def _parse_related_cases(self, page: PageElement) -> list[dict]:
        rows = page.query(
            XPath(
                "//h5[contains(text(), 'Related Appellate')]"
                "/following-sibling::table[1]//tbody/tr"
            ),
            "related case rows",
            min_count=0,
        )
        out: list[dict] = []
        for row in rows:
            cells = row.query(
                XPath(".//td"), "related case cells", min_count=0
            )
            if len(cells) < 5:
                continue
            rc_links = cells[0].query(
                XPath(".//a"), "related case link", min_count=0
            )
            internal_id = None
            if rc_links:
                internal_id = extract_q_token(
                    rc_links[0].get_attribute("href")
                )
            out.append(
                {
                    "docket_number": safe_text(cells[0]) or None,
                    "case_name": safe_text(cells[1]) or None,
                    "case_type": safe_text(cells[2]) or None,
                    "relationship": safe_text(cells[3]) or None,
                    "status": safe_text(cells[4]) or None,
                    "internal_id": internal_id,
                }
            )
        return out

    # -- helpers ----------------------------------------------------------

    @staticmethod
    def _dd_text(page: PageElement, label: str) -> str:
        """Return the ``<dd>`` text following the ``<dt>`` whose text
        contains ``label`` (empty string if absent)."""
        els = page.query(
            XPath(
                f"//dt[contains(text(), '{label}')]/following-sibling::dd[1]"
            ),
            f"{label} value",
            min_count=0,
        )
        return safe_text(els[0]) if els else ""
