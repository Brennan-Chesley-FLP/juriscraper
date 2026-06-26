"""Parser for a P-MACS case-detail page (``publicCaseMaintenance.do``).

One case page renders a Case Information label/value block, a Party
Information table, and a Docket Information table. :class:`CaseDetailParser`
extracts all three into a single :class:`MnDocket`. The numeric
``csNameID`` / ``csInstanceID`` ids are read from the page's hidden form
inputs here; the calling step prefers the values it parsed from the URL
and stamps ``court`` / ``source_url`` / ``source_entry_point`` before
emitting (see ``scraper.py``).
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from urllib.parse import parse_qs, urljoin, urlparse

from jkent.common.deferred_validation import DeferredValidation
from jkent.common.parser import JKentParser
from jkent.data_types import XPath

from juriscraper.state.minnesota.macsnc_courts_state_mn_us.models import (
    JURISDICTION_TO_COURT_ID,
    MnDocket,
    MnDocketEntry,
    MnParty,
)

from ._common import cell_lines, extract_label, normalize_ws, parse_date

if TYPE_CHECKING:
    from jkent.common.page_element import PageElement


class CaseDetailParser(JKentParser[MnDocket]):
    """Parse one case-detail page into a single ``MnDocket``.

    ``base_url`` (the page URL) is used to absolutise docket-entry hrefs;
    pass it on construction. ``court``, ``source_url``, and the
    ``source_entry_point`` are stamped by the calling step.
    """

    def __init__(self, base_url: str = "") -> None:
        self._base_url = base_url

    def __call__(
        self, page: PageElement
    ) -> list[DeferredValidation[MnDocket]]:
        docket_number = extract_label(page, "Case Number")
        jurisdiction = extract_label(page, "Jurisdiction")
        court = JURISDICTION_TO_COURT_ID.get(jurisdiction or "", "")

        short_title = extract_label(page, "Short Title")
        full_title = extract_label(page, "Full Title")
        case_name = short_title or full_title or docket_number

        cs_name_id, cs_instance_id = self._extract_case_ids(page)

        return [
            MnDocket.raw(
                docket_number=docket_number,
                court=court,
                case_name=case_name,
                short_title=short_title or None,
                full_title=full_title or None,
                summary=extract_label(page, "Summary") or None,
                citation=extract_label(page, "Citation") or None,
                date_filed=parse_date(extract_label(page, "Filing Date")),
                classification=extract_label(page, "Classification") or None,
                status=extract_label(page, "Status") or None,
                jurisdiction=jurisdiction or None,
                orca=extract_label(page, "ORCA") or None,
                hearing_type=extract_label(page, "Hearing Type") or None,
                parties=self._parse_parties(page),
                entries=self._parse_docket_entries(page),
                cs_name_id=cs_name_id,
                cs_instance_id=cs_instance_id,
            )
        ]

    @staticmethod
    def _extract_case_ids(
        page: PageElement,
    ) -> tuple[str | None, str | None]:
        """Pull ``csNameID`` / ``csInstanceID`` from hidden form inputs."""
        cs_name_id: str | None = None
        cs_instance_id: str | None = None
        for field in ("csNameID", "csInstanceID"):
            nodes = page.query(
                XPath(f"//input[@type='hidden' and @name='{field}']"),
                f"hidden {field} input",
                min_count=0,
                max_count=1,
            )
            value = nodes[0].get_attribute("value") if nodes else None
            if field == "csNameID" and value:
                cs_name_id = value
            elif field == "csInstanceID" and value:
                cs_instance_id = value
        return cs_name_id, cs_instance_id

    def _parse_parties(self, page: PageElement) -> list[MnParty]:
        rows = page.query(
            XPath(
                "//tr[contains(@class, 'TableHeading')]"
                "/td[normalize-space()='Party Information']"
                "/ancestor::table[1]"
                "//tr[contains(@class, 'OddRow') or contains(@class, 'EvenRow')]"
            ),
            "party rows",
            min_count=0,
        )
        parties: list[MnParty] = []
        for row in rows:
            cells = row.query(XPath("./td"), "party cells", min_count=0)
            if len(cells) < 4:
                continue
            macs_id = normalize_ws(cells[0].text_content()) or None
            role = normalize_ws(cells[1].text_content()) or None
            name = normalize_ws(cells[2].text_content())
            if not name:
                continue
            attorney_lines = cell_lines(cells[3])
            attorneys = [
                line for line in attorney_lines if line.lower() != "pro se"
            ]
            parties.append(
                MnParty(
                    macs_id=macs_id,
                    role=role,
                    name=name,
                    attorneys=attorneys,
                )
            )
        return parties

    def _parse_docket_entries(self, page: PageElement) -> list[MnDocketEntry]:
        rows = page.query(
            XPath(
                "//tr[contains(@class, 'TableHeading')]"
                "/td[normalize-space()='Docket Information']"
                "/ancestor::table[1]"
                "//tr[contains(@class, 'OddRow') or contains(@class, 'EvenRow')]"
            ),
            "docket rows",
            min_count=0,
        )
        entries: list[MnDocketEntry] = []
        for row in rows:
            cells = row.query(XPath("./td"), "docket cells", min_count=0)
            if len(cells) < 6:
                continue
            description = normalize_ws(cells[0].text_content())
            jurisdiction = normalize_ws(cells[1].text_content())
            filing_date = parse_date(normalize_ws(cells[2].text_content()))
            entry_type = normalize_ws(cells[3].text_content())
            filing_type = normalize_ws(cells[4].text_content())
            status = normalize_ws(cells[5].text_content())

            entry_url: str | None = None
            doc_entry_id: str | None = None
            anchor_nodes = cells[0].query(
                XPath(".//a"), "entry anchor", min_count=0, max_count=1
            )
            if anchor_nodes:
                href = anchor_nodes[0].get_attribute("href")
                if href:
                    entry_url = urljoin(self._base_url, href)
                    qs = parse_qs(urlparse(entry_url).query)
                    doc_entry_id = (qs.get("deID") or [None])[0]

            entries.append(
                MnDocketEntry(
                    date_filed=filing_date,
                    description=description or None,
                    docket_entry_type=entry_type or None,
                    filing_type=filing_type or None,
                    status=status or None,
                    jurisdiction=jurisdiction or None,
                    doc_entry_id=doc_entry_id,
                    entry_url=entry_url,
                )
            )
        return entries
