"""Parser for a Tennessee PCH ``CaseDetails.aspx`` page.

One case-detail page renders the full register of actions in plain HTML
tables under five ``<h3>`` sections: Case Overview, Case Milestones,
Parties, Case History (the docket), and Record Information.
:class:`CaseDetailParser` extracts every section into a single
:class:`TnDocket`. The page does *not* carry the numeric ``MastCastID``
or the source URL — the step stamps ``internal_case_id``, ``court``,
``source_url``, and ``source_entry_point`` onto the returned ``raw_data``
before emitting (see ``scraper.py``).

The docket number and court are read from the result row (carried in
``accumulated_data``) and likewise stamped by the step, since the
detail-page header repeats them but the row value is authoritative for
court derivation.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from jkent.common.parser import JKentParser
from jkent.data_types import XPath

from juriscraper.state.tennessee.pch_tncourts_gov.models import (
    TnDocket,
    TnDocketEntry,
    TnMilestone,
    TnParty,
    TnRecordEntry,
)

from ._common import POSTBACK_TARGET_RE, parse_date, safe_text

if TYPE_CHECKING:
    from jkent.common.deferred_validation import DeferredValidation
    from jkent.common.page_element import PageElement


# Milestone label (lowercased) → the scalar field it also populates on the
# docket. Date-valued milestones map to a date field; text-valued ones to a
# text field (handled separately below).
_MILESTONE_DATE_FIELDS: dict[str, str] = {
    "application filed": "date_filed",
    "record filed": "date_filed",  # only if date_filed still unset
    "closed date": "date_closed",
    "decision date": "date_decision",
}
_MILESTONE_TEXT_FIELDS: dict[str, str] = {
    "decision type": "decision_type",
    "disposition": "disposition",
    "panel": "panel_str",
}


class CaseDetailParser(JKentParser[TnDocket]):
    """Parse every section of a Tennessee PCH case-detail page.

    Returns a single-element list with one partial ``TnDocket`` carrying
    the header scalars (overview, milestones) and nested
    party/milestone/entry/record records. The page does not carry the
    authoritative ``docket_number``/``court``/``internal_case_id`` —
    those come from the result row and are stamped onto the returned
    ``raw_data`` by the calling step, along with ``source_url`` and
    ``source_entry_point``.

    A placeholder ``docket_number``/``court`` is supplied so ``.raw()``
    captures the page-detail caption; the step overwrites both with the
    row-authoritative values before emitting.
    """

    def __call__(
        self, page: PageElement
    ) -> list[DeferredValidation[TnDocket]]:
        # Detail-page caption (some result rows have no style).
        case_name: str | None = None
        title_els = page.query(
            XPath("//h1[@class='case-title']"),
            "case title",
            min_count=0,
            max_count=1,
        )
        if title_els:
            case_name = safe_text(title_els[0]) or None

        overview = self._parse_overview(page)
        milestones, milestone_scalars = self._parse_milestones(page)

        docket = TnDocket.raw(
            # Identity placeholders — the step overwrites these with the
            # row-authoritative docket_number/court.
            docket_number="",
            court="",
            case_name=case_name or "",
            intermediate_docket_number=overview.get(
                "intermediate_docket_number"
            ),
            trial_court=overview.get("trial_court"),
            assigned_to_str=overview.get("assigned_to_str"),
            trial_court_docket_number=overview.get(
                "trial_court_docket_number"
            ),
            date_filed=milestone_scalars.get("date_filed"),
            date_closed=milestone_scalars.get("date_closed"),
            date_decision=milestone_scalars.get("date_decision"),
            disposition=milestone_scalars.get("disposition"),
            decision_type=milestone_scalars.get("decision_type"),
            panel_str=milestone_scalars.get("panel_str"),
            milestones=milestones,
            parties=self._parse_parties(page),
            entries=self._parse_history(page),
            record_info=self._parse_record_info(page),
        )
        return [docket]

    # =====================================================================
    # Case Overview
    # =====================================================================

    def _parse_overview(self, page: PageElement) -> dict:
        """Parse the one-row Case Overview table.

        The page nests sub-sections inside ``<div id="case-overview">``,
        so the actual one-row overview table lives in
        ``<div id="case-overview2">``.
        """
        out: dict = {}
        overview_rows = page.query(
            XPath("//div[@id='case-overview2']//tr[td]"),
            "overview rows",
            min_count=0,
        )
        for row in overview_rows:
            cells = row.query(XPath(".//td"), "overview cells", min_count=0)
            if len(cells) >= 5:
                out["intermediate_docket_number"] = safe_text(cells[0]) or None
                # cells[1] is the style — already on case_name.
                out["trial_court"] = safe_text(cells[2]) or None
                out["assigned_to_str"] = safe_text(cells[3]) or None
                out["trial_court_docket_number"] = safe_text(cells[4]) or None
                break
        return out

    # =====================================================================
    # Case Milestones
    # =====================================================================

    def _parse_milestones(
        self, page: PageElement
    ) -> tuple[list[TnMilestone], dict]:
        """Parse the Case Milestones table.

        Returns the milestone rows plus a dict of scalar fields folded
        onto the docket (``date_filed``, ``date_closed``,
        ``date_decision``, ``disposition``, ``decision_type``,
        ``panel_str``).
        """
        milestones: list[TnMilestone] = []
        scalars: dict = {}
        milestone_rows = page.query(
            XPath("//table[@id='milestones']//tr[td]"),
            "milestone rows",
            min_count=0,
        )
        for row in milestone_rows:
            cells = row.query(XPath(".//td"), "milestone cells", min_count=0)
            if len(cells) < 2:
                continue
            description = safe_text(cells[0])
            value_text = safe_text(cells[1])
            milestone_date = parse_date(value_text)
            if not description:
                continue
            milestones.append(
                TnMilestone(
                    description=description, date_milestone=milestone_date
                )
            )
            label = description.lower()
            field = _MILESTONE_DATE_FIELDS.get(label)
            if field and milestone_date:
                if label == "record filed":
                    # Only when application-filed didn't set it.
                    scalars["date_filed"] = (
                        scalars.get("date_filed") or milestone_date
                    )
                else:
                    scalars[field] = milestone_date
            text_field = _MILESTONE_TEXT_FIELDS.get(label)
            if text_field:
                scalars[text_field] = value_text or None
        return milestones, scalars

    # =====================================================================
    # Parties
    # =====================================================================

    def _parse_parties(self, page: PageElement) -> list[TnParty]:
        """Parse the Parties table on the case-detail page."""
        party_rows = page.query(
            XPath("//div[@id='case-parties']//tr[td]"),
            "party rows",
            min_count=0,
        )
        out: list[TnParty] = []
        for row in party_rows:
            cells = row.query(XPath(".//td"), "party cells", min_count=0)
            if len(cells) < 3:
                continue
            name = safe_text(cells[0])
            if not name:
                continue
            out.append(
                TnParty(
                    name=name,
                    role=safe_text(cells[1]) or None,
                    counsel=safe_text(cells[2]) or None,
                )
            )
        return out

    # =====================================================================
    # Case History (docket entries)
    # =====================================================================

    def _parse_history(self, page: PageElement) -> list[TnDocketEntry]:
        """Parse the Case History table (the docket / register of actions).

        Rows with an attached PDF carry the ``__doPostBack`` target on the
        entry's ``postback_target`` field; the step uses it to download.
        """
        history_rows = page.query(
            XPath("//div[@id='case-history']//tr[td]"),
            "history rows",
            min_count=0,
        )
        out: list[TnDocketEntry] = []
        for row in history_rows:
            cells = row.query(XPath(".//td"), "history cells", min_count=0)
            if len(cells) < 4:
                continue
            entry_date = parse_date(safe_text(cells[0]))
            event = safe_text(cells[1])
            filer = safe_text(cells[2]) or None

            postback_target: str | None = None
            pdf_links = cells[3].query(XPath(".//a"), "pdf links", min_count=0)
            if pdf_links:
                href = pdf_links[0].get_attribute("href") or ""
                pb_match = POSTBACK_TARGET_RE.search(href)
                if pb_match:
                    postback_target = pb_match.group(1)

            out.append(
                TnDocketEntry(
                    date_filed=entry_date,
                    event=event or "(no event)",
                    filer=filer,
                    postback_target=postback_target,
                )
            )
        return out

    # =====================================================================
    # Record Information
    # =====================================================================

    def _parse_record_info(self, page: PageElement) -> list[TnRecordEntry]:
        """Parse the Record Information table on the case-detail page."""
        record_rows = page.query(
            XPath("//div[@id='record-information']//tr[td]"),
            "record rows",
            min_count=0,
        )
        out: list[TnRecordEntry] = []
        for row in record_rows:
            cells = row.query(XPath(".//td"), "record cells", min_count=0)
            if len(cells) < 3:
                continue
            volume_type = safe_text(cells[0])
            if not volume_type:
                continue
            out.append(
                TnRecordEntry(
                    volume_type=volume_type,
                    volumes=safe_text(cells[1]) or None,
                    record_type=safe_text(cells[2]) or None,
                )
            )
        return out
