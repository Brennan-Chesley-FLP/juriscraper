"""Parser for the Briefs list page."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from jkent.common.parser import JKentParser
from jkent.data_types import XPath

from juriscraper.state.alaska.appellate_records_courts_alaska_gov.models import (
    AkBrief,
)

from ._common import parse_ak_date, safe_text, text_lines

if TYPE_CHECKING:
    from jkent.common.deferred_validation import DeferredValidation
    from jkent.common.page_element import PageElement

# "Status: Complete 5/1/2001" or "Status: Open Time status set unknown".
_ROUND_STATUS_RE = re.compile(r"Status:\s*(\S+)\s*(.*)")

# One of these wraps each briefing round's heading, status line and table.
_ROUND_BLOCK = XPath("//div[contains(@class, 'cms-brief-row')]")

_ROUND_ROWS = XPath(".//table[contains(@class, 'cms-brief-table')]//tbody/tr")


class BriefsParser(JKentParser[AkBrief]):
    """Parse the Briefs tables into one ``AkBrief`` per row.

    The page groups briefs into briefing rounds (``Original Briefing``,
    ``Supplemental Briefing``, ``Briefing After Remand``), each with its
    own heading, status line and table; every brief records the round it
    is listed under. ``history_url`` (the ``Dkt#`` cell link to the
    brief-history page) and ``document_url`` are surfaced so the step can
    chain into the history and archive documents.

    The rounds themselves come from :meth:`parse_rounds` — a round can be
    open with no briefs filed yet, so it isn't recoverable from the rows.
    """

    def __call__(self, page: PageElement) -> list[DeferredValidation[AkBrief]]:
        results: list[DeferredValidation[AkBrief]] = []
        blocks = page.query(_ROUND_BLOCK, "briefing rounds", min_count=0)
        for block in blocks:
            round_name = self._round_name(block)
            rows = block.query(_ROUND_ROWS, "brief rows", min_count=0)
            for row in rows:
                cells = row.query(XPath(".//td"), "brief cells", min_count=0)
                if len(cells) < 6:
                    continue
                history_links = cells[0].find_links(
                    XPath(".//a"), "brief history link", min_count=0
                )
                doc_links = row.find_links(
                    XPath(".//a[contains(@class, 'glyphicon-file')]"),
                    "brief doc",
                    min_count=0,
                )
                results.append(
                    AkBrief.raw(
                        entry_number=(
                            " ".join(text_lines(cells[0], "brief dkt#"))
                            or None
                        ),
                        briefing_round=round_name,
                        brief_type=safe_text(cells[2]) or None,
                        party=safe_text(cells[3]) or None,
                        status=safe_text(cells[4]) or None,
                        brief_date=parse_ak_date(safe_text(cells[5])),
                        document_url=doc_links[0].url if doc_links else None,
                        history_url=(
                            history_links[0].url if history_links else None
                        ),
                    )
                )
        return results

    @classmethod
    def parse_rounds(cls, page: PageElement) -> list[dict]:
        """One ``AkBriefingRound`` dict per briefing-round block."""
        rounds: list[dict] = []
        blocks = page.query(_ROUND_BLOCK, "briefing rounds", min_count=0)
        for block in blocks:
            status_raw = cls._status_line(block)
            status = None
            status_date = None
            match = _ROUND_STATUS_RE.match(status_raw)
            if match:
                status = match.group(1).strip() or None
                # The tail is either the date the status was set or the
                # literal "Time status set unknown".
                status_date = parse_ak_date(match.group(2).strip())
            rounds.append(
                {
                    "round_name": cls._round_name(block),
                    "status": status,
                    "status_date": status_date,
                    "status_raw": status_raw or None,
                }
            )
        return rounds

    @staticmethod
    def _round_name(block: PageElement) -> str | None:
        headings = block.query(
            XPath(".//h4[not(starts-with(normalize-space(.), 'Status:'))]"),
            "round name heading",
            min_count=0,
            max_count=1,
        )
        if not headings:
            return None
        return " ".join(safe_text(headings[0]).split()) or None

    @staticmethod
    def _status_line(block: PageElement) -> str:
        headings = block.query(
            XPath(".//h4[starts-with(normalize-space(.), 'Status:')]"),
            "round status heading",
            min_count=0,
            max_count=1,
        )
        if not headings:
            return ""
        return " ".join(safe_text(headings[0]).split())
