"""Parser for a Hawaiʻi eCourt Kōkua case-detail page.

One ``CaseSearchView``/``CaseSearch.iface`` case-detail render carries the
case summary, register of actions, parties & attorneys, and any document
links in server-side IceFaces HTML. :class:`CaseDetailParser` extracts every
section into a single :class:`HiAppDocket`.

The page does **not** reliably carry the full court-prefixed docket number,
the CourtListener ``court``, or the source URL — the calling step stamps
those onto the returned ``raw_data`` before emitting (see ``scraper.py``).

TODO(empirical): the eCourt Kōkua result/detail layout could not be captured
during reconnaissance (every search submission is gated by invisible
reCAPTCHA, unsolvable today — see ``CC_NOTES.md``). The XPaths here follow
the JSF/IceFaces conventions used elsewhere in the JIMS portal (label-then-
value summary cells, an ``iceDatTbl`` register of actions). Validate on the
first operational run and adjust accordingly.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from jkent.common.parser import JKentParser
from jkent.data_types import XPath

from juriscraper.state.hawaii.jimspss1_courts_state_hi_us.models import (
    HiAppAttorney,
    HiAppDocket,
    HiAppDocketEntry,
    HiAppDocument,
    HiAppParty,
)

from ._common import clean, parse_site_date, value_for_label

if TYPE_CHECKING:
    from jkent.common.deferred_validation import DeferredValidation
    from jkent.common.page_element import PageElement


class CaseDetailParser(JKentParser[HiAppDocket]):
    """Parse every section of a Hawaiʻi appellate case-detail page.

    Returns a single-element list with one ``HiAppDocket`` carrying the
    header scalars and the nested party / docket-entry / document records.
    ``docket_number``, ``court``, ``case_type_code``, ``case_type``,
    ``source_url`` and ``source_entry_point`` are stamped by the calling
    step.
    """

    def __call__(
        self, page: PageElement
    ) -> list[DeferredValidation[HiAppDocket]]:
        case_name = value_for_label(page, "Caption") or value_for_label(
            page, "Case Title"
        )
        case_status = value_for_label(page, "Case Status") or value_for_label(
            page, "Status"
        )
        date_filed = parse_site_date(value_for_label(page, "Filing Date"))
        date_terminated = parse_site_date(
            value_for_label(page, "Disposition Date")
            or value_for_label(page, "Closed Date")
        )
        panel_str = value_for_label(page, "Panel") or value_for_label(
            page, "Division"
        )
        appeal_from_str = value_for_label(
            page, "Trial Court Case Number"
        ) or value_for_label(page, "Lower Court Case Number")
        assigned_to_str = value_for_label(page, "Trial Court Judge")

        docket = HiAppDocket.raw(
            case_name=case_name,
            date_filed=date_filed,
            case_status=clean(case_status),
            date_terminated=date_terminated,
            panel_str=clean(panel_str),
            appeal_from_str=clean(appeal_from_str),
            assigned_to_str=clean(assigned_to_str),
            entries=self._parse_docket_entries(page),
            parties=self._parse_parties(page),
            documents=self._parse_documents(page),
        )
        return [docket]

    # =====================================================================
    # Register of actions
    # =====================================================================

    def _parse_docket_entries(
        self, page: PageElement
    ) -> list[HiAppDocketEntry]:
        """Parse the register-of-actions table.

        TODO(empirical): column order on the actual page is unverified."""
        rows = page.query(
            XPath(
                "//table[contains(@class, 'iceDatTbl')]"
                "[.//th[contains(translate(text(),"
                " 'ABCDEFGHIJKLMNOPQRSTUVWXYZ',"
                " 'abcdefghijklmnopqrstuvwxyz'), 'docket')]"
                " or .//th[contains(translate(text(),"
                " 'ABCDEFGHIJKLMNOPQRSTUVWXYZ',"
                " 'abcdefghijklmnopqrstuvwxyz'), 'register')]]"
                "//tbody/tr"
            ),
            "docket entry rows",
            min_count=0,
        )
        out: list[HiAppDocketEntry] = []
        for row in rows:
            cells = row.query_strings(
                XPath(".//td//text()"), "docket cell texts", min_count=0
            )
            cells = [c.strip() for c in cells if c.strip()]
            if not cells:
                continue
            date_filed = parse_site_date(cells[0])
            description = cells[1] if len(cells) > 1 else cells[0]
            notes = cells[2] if len(cells) > 2 else None
            out.append(
                HiAppDocketEntry(
                    date_filed=date_filed,
                    description=description,
                    notes=notes,
                )
            )
        return out

    # =====================================================================
    # Parties & attorneys
    # =====================================================================

    def _parse_parties(self, page: PageElement) -> list[HiAppParty]:
        """Parse the parties section.

        TODO(empirical): JSF portals here typically render parties as nested
        tables or repeated panels; refine selectors after a real run."""
        rows = page.query(
            XPath(
                "//*[contains(translate(@id, 'PARTIES', 'parties'),"
                " 'parties')]"
                "//table[contains(@class, 'iceDatTbl')]//tbody/tr"
            ),
            "party rows",
            min_count=0,
        )
        out: list[HiAppParty] = []
        for row in rows:
            cells = row.query_strings(
                XPath(".//td//text()"), "party cell texts", min_count=0
            )
            cells = [c.strip() for c in cells if c.strip()]
            if len(cells) < 2:
                continue
            name, role, *rest = cells
            attorney_text = rest[0] if rest else None
            attorneys: list[HiAppAttorney] = []
            if attorney_text:
                attorneys.append(HiAppAttorney(name=attorney_text))
            out.append(HiAppParty(name=name, role=role, attorneys=attorneys))
        return out

    # =====================================================================
    # Documents
    # =====================================================================

    def _parse_documents(self, page: PageElement) -> list[HiAppDocument]:
        """Collect document links surfaced on the case detail page.

        These often link to a viewer / Subscriptions paywall rather than a
        direct PDF, so we record metadata only. Hrefs are returned as found;
        the calling step resolves them against the page URL."""
        links = page.query(
            XPath(
                "//a[contains(@href, 'Document') or contains(@href,"
                " 'Opinion') or contains(@href, '.pdf')]"
            ),
            "document links",
            min_count=0,
        )
        out: list[HiAppDocument] = []
        for link in links:
            href = link.get_attribute("href")
            if not href:
                continue
            text = clean(link.text_content())
            out.append(HiAppDocument(download_url=href, description=text))
        return out
