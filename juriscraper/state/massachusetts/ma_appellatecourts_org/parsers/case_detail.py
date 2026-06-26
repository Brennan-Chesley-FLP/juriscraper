"""Parser for a Massachusetts Appellate Courts case-detail page.

One ``/docket/{docket_id}`` page renders the full case header, parties &
attorneys, docket entries, future-calendar block, additional-information
block, and a list of document PDFs in plain HTML.
:class:`CaseDetailParser` extracts every section into a single
:class:`MaDocket`. The page does *not* carry the CourtListener ``court``
id, the site case-category, the source URL, or the entry point — the step
stamps those onto the returned ``raw_data`` before emitting (see
``scraper.py``).
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from urllib.parse import urljoin

from jkent.common.parser import JKentParser
from jkent.data_types import XPath

from juriscraper.state.massachusetts.ma_appellatecourts_org.models import (
    BASE_URL,
    MaAttorney,
    MaDocket,
    MaDocketEntry,
    MaParty,
    MaScheduledHearing,
)

from ._common import ATTORNEY_ID_RE, clean, first, parse_date

if TYPE_CHECKING:
    from jkent.common.deferred_validation import DeferredValidation
    from jkent.common.page_element import PageElement


class CaseDetailParser(JKentParser[MaDocket]):
    """Parse every section of a ma-appellatecourts.org case-detail page.

    Returns a single-element list with one ``MaDocket`` carrying the
    header scalars and the nested party/entry/scheduled-hearing records.
    ``docket_number``, ``court``, ``case_category``, ``source_url``, and
    ``source_entry_point`` are stamped by the calling step.
    """

    def __call__(
        self, page: PageElement
    ) -> list[DeferredValidation[MaDocket]]:
        case_name = first(page, "//div[@class='docket-header-1'][2]/text()")
        is_impounded = bool(
            page.query_strings(
                XPath(
                    "//div[contains(@class,'docket-header')]"
                    "//*[contains(text(),'IMPOUNDED')]/text()"
                ),
                "impounded marker",
                min_count=0,
            )
        )

        header = self._collect_header_fields(page)

        docket = MaDocket.raw(
            case_name=(case_name or "").strip(),
            date_filed=parse_date(header.get("Entry Date")),
            case_type=header.get("Case Type"),
            nature=header.get("Nature"),
            appellant=header.get("Appellant"),
            applicant=header.get("Applicant"),
            is_impounded=is_impounded,
            case_status=header.get("Case Status"),
            date_status=parse_date(header.get("Status Date")),
            brief_status=header.get("Brief Status"),
            brief_due=header.get("Brief Due"),
            date_argued=parse_date(
                header.get("Argued Date") or header.get("Arg/Submitted")
            ),
            date_decision=parse_date(header.get("Decision Date")),
            date_response=parse_date(header.get("Response Date")),
            panel_str=header.get("Panel"),
            quorum=header.get("Quorum"),
            citation=header.get("Citation"),
            sjc_number=header.get("SJC Number"),
            appeals_court_number=(
                header.get("Appeals Ct Number") or header.get("AC/SJ Number")
            ),
            sj_number=header.get("SJ Number"),
            far_number=(
                header.get("FAR Number") or header.get("DAR/FAR Number")
            ),
            full_court_number=header.get("Full Ct Number"),
            route_to_sjc=header.get("Route to SJC"),
            appeal_from_str=header.get("Lower Court"),
            lower_court_number=(
                header.get("TC Number") or header.get("Lower Ct Number")
            ),
            lower_court_judge=header.get("Lower Ct Judge"),
            date_lower_court_entry=parse_date(header.get("TC Entry Date")),
            additional_information=self._extract_additional_information(page),
            parties=self._extract_parties(page),
            entries=self._extract_docket_entries(page),
            scheduled_hearings=self._extract_scheduled_hearings(page),
            document_urls=self._extract_document_urls(page),
        )
        return [docket]

    # =====================================================================
    # Header
    # =====================================================================

    @staticmethod
    def _collect_header_fields(page: PageElement) -> dict[str, str]:
        """Extract the CASE HEADER label/value pairs into a dict.

        Each row is rendered as ``<span class="flex_span ds-bold">{label}
        <span class="flex_rt ds-normal">{value}</span></span>``. We pull
        the label from the outer span's first text node and the value from
        the inner ``flex_rt*`` span.
        """
        out: dict[str, str] = {}
        spans = page.query(
            XPath(
                "//section[contains(@class,'docket')]"
                "//span[contains(@class,'flex_span') or "
                "contains(@class,'flex_span_wide')]"
                "[span[contains(@class,'flex_rt') or "
                "contains(@class,'flex_rt_wide')]]"
            ),
            "header label spans",
            min_count=0,
        )
        for span in spans:
            # The label is the leading text node before the inner span.
            label_parts = span.query_strings(
                XPath("./text()[1]"), "label text", min_count=0, max_count=1
            )
            value_parts = span.query_strings(
                XPath(
                    ".//span[contains(@class,'flex_rt') or "
                    "contains(@class,'flex_rt_wide')]//text()"
                ),
                "value text",
                min_count=0,
            )
            label = clean(label_parts[0] if label_parts else None)
            value = clean(" ".join(value_parts))
            if label and value:
                out[label] = value
        return out

    # =====================================================================
    # Additional information
    # =====================================================================

    @staticmethod
    def _extract_additional_information(page: PageElement) -> str | None:
        """Pull the free-text ADDITIONAL INFORMATION block, when present."""
        text_parts = page.query_strings(
            XPath(
                "//section[contains(@class,'docket')]"
                "[.//div[contains(@class,'section_title')]"
                "//*[contains(text(),'ADDITIONAL INFORMATION')]]"
                "//div[contains(@class,'pl-2')]//text()"
            ),
            "additional information body",
            min_count=0,
        )
        text = " ".join(t.strip() for t in text_parts if t.strip())
        return clean(text)

    # =====================================================================
    # Parties & attorneys
    # =====================================================================

    @classmethod
    def _extract_parties(cls, page: PageElement) -> list[MaParty]:
        """Pull party rows from the INVOLVED PARTY / ATTORNEY APPEARANCE
        section."""
        party_rows = page.query(
            XPath("//div[contains(@class,'row party')]"),
            "party rows",
            min_count=0,
        )
        parties: list[MaParty] = []
        for row in party_rows:
            # Left column: name + role + statuses
            left_lines = row.query_strings(
                XPath(
                    ".//div[contains(@class,'col-12') and "
                    "not(contains(@class,'indent'))]"
                    "//span[contains(@class,'flex_span')]//text()"
                ),
                "party left text",
                min_count=0,
            )
            name = None
            role = None
            extras: list[str] = []
            # The bold name is wrapped in <b>; pull it explicitly.
            bold = row.query_strings(
                XPath(
                    ".//div[contains(@class,'col-12') and "
                    "not(contains(@class,'indent'))]"
                    "//b[1]/text()"
                ),
                "party name bold",
                min_count=0,
                max_count=1,
            )
            if bold:
                name = clean(bold[0])
            # Reconstruct the role + extra status lines from the remaining
            # text nodes (skipping the bold name's text).
            cleaned_lines: list[str] = []
            for raw in left_lines:
                stripped = raw.strip()
                if not stripped:
                    continue
                if name and stripped == name:
                    continue
                cleaned_lines.append(stripped)
            if cleaned_lines:
                role = cleaned_lines[0]
                extras = cleaned_lines[1:]

            brief_status = extras[0] if extras else None
            enlargement = extras[1] if len(extras) > 1 else None

            # Right column: attorney appearances.
            attorney_spans = row.query(
                XPath(
                    ".//div[contains(@class,'indent')]"
                    "//span[contains(@class,'flex_span')]"
                ),
                "attorney spans",
                min_count=0,
            )
            attorneys = [
                cls._parse_attorney_span(span) for span in attorney_spans
            ]

            parties.append(
                MaParty(
                    name=name or "",
                    role=role,
                    brief_status=brief_status,
                    enlargement_summary=enlargement,
                    attorneys=attorneys,
                )
            )
        return parties

    @staticmethod
    def _parse_attorney_span(span: PageElement) -> MaAttorney:
        """Parse a single attorney appearance span."""
        link_url = None
        attorney_id = None
        name_text = None
        title = None

        href_values = span.query_strings(
            XPath(".//a/@href"), "attorney href", min_count=0, max_count=1
        )
        if href_values:
            link_url = href_values[0]
            match = ATTORNEY_ID_RE.search(link_url)
            if match:
                attorney_id = match.group(1)

        link_text_parts = span.query_strings(
            XPath(".//a//text()"), "attorney link text", min_count=0
        )
        if link_text_parts:
            joined = " ".join(t.strip() for t in link_text_parts if t.strip())
            joined = clean(joined) or ""
            # The link text is "Name, Title" — split on the *last* comma.
            if "," in joined:
                head, _, tail = joined.rpartition(",")
                name_text = clean(head)
                title = clean(tail)
            else:
                name_text = joined or None

        if not name_text:
            # Pro-se / non-linked attorneys: take the span's whole text.
            all_text = span.query_strings(
                XPath(".//text()"), "attorney text", min_count=0
            )
            joined = " ".join(t.strip() for t in all_text if t.strip())
            joined = clean(joined) or ""
            if "," in joined:
                head, _, tail = joined.rpartition(",")
                name_text = clean(head)
                title = clean(tail)
            else:
                name_text = joined or None

        span_text = " ".join(
            t.strip()
            for t in span.query_strings(
                XPath(".//text()"), "withdraw probe", min_count=0
            )
            if t.strip()
        )
        withdrawn = "Withdrawn" in span_text

        return MaAttorney(
            name=name_text or "",
            title=title,
            withdrawn=withdrawn,
            attorney_url=link_url,
            attorney_id=attorney_id,
        )

    # =====================================================================
    # Docket entries
    # =====================================================================

    @staticmethod
    def _extract_docket_entries(page: PageElement) -> list[MaDocketEntry]:
        """Parse the DOCKET ENTRIES table."""
        rows = page.query(
            XPath(
                "//table[contains(@class,'docket_entries')]"
                "//tr[not(contains(@class,'subhead'))]"
            ),
            "docket entry rows",
            min_count=0,
        )
        entries: list[MaDocketEntry] = []
        for row in rows:
            cells = row.query_strings(
                XPath("./td"), "docket cells", min_count=0
            )
            if len(cells) < 3:
                continue
            date_text, paper, description = cells[0], cells[1], cells[2]
            entry_date = parse_date(date_text)
            description_clean = clean(description) or ""
            if not (entry_date or paper.strip() or description_clean):
                continue
            entries.append(
                MaDocketEntry(
                    date_filed=entry_date,
                    paper_number=clean(paper),
                    description=description_clean,
                )
            )
        return entries

    # =====================================================================
    # Future calendar (scheduled hearings)
    # =====================================================================

    @staticmethod
    def _extract_scheduled_hearings(
        page: PageElement,
    ) -> list[MaScheduledHearing]:
        """Pull rows from the optional FUTURE CALENDAR block."""
        blocks = page.query(
            XPath(
                "//section[contains(@class,'docket')]"
                "[.//div[contains(@class,'section_title')]"
                "//*[contains(text(),'FUTURE CALENDAR')]]"
                "//div[contains(@class,'calendar-results-date') or "
                "contains(@class,'calendar-results-presiding')]"
            ),
            "future calendar blocks",
            min_count=0,
        )
        out: list[MaScheduledHearing] = []
        current_when: str | None = None
        current_location: str | None = None
        for block in blocks:
            classes = " ".join(
                block.query_strings(
                    XPath("./@class"), "block class", min_count=0
                )
            )
            text_lines = [
                t.strip()
                for t in block.query_strings(
                    XPath(".//text()"), "lines", min_count=0
                )
                if t.strip()
            ]
            if "calendar-results-date" in classes:
                current_when = text_lines[0] if text_lines else None
                current_location = (
                    text_lines[1] if len(text_lines) > 1 else None
                )
            elif "calendar-results-presiding" in classes:
                presiding = next(
                    (
                        line[len("Presiding:") :].strip()
                        for line in text_lines
                        if line.lower().startswith("presiding:")
                    ),
                    None,
                )
                out.append(
                    MaScheduledHearing(
                        scheduled_for=current_when,
                        presiding=presiding,
                        location=current_location,
                    )
                )
        return out

    # =====================================================================
    # Documents
    # =====================================================================

    @staticmethod
    def _extract_document_urls(page: PageElement) -> list[str]:
        """Pull the unique PDF links from the DOCUMENTS block."""
        hrefs = page.query_strings(
            XPath("//div[contains(@class,'documents_list')]//li/a/@href"),
            "document hrefs",
            min_count=0,
        )
        seen: list[str] = []
        for href in hrefs:
            absolute = urljoin(BASE_URL, href)
            if absolute not in seen:
                seen.append(absolute)
        return seen

    @staticmethod
    def document_label_for_url(page: PageElement, url: str) -> str | None:
        """Find the visible label for a document link."""
        labels = page.query_strings(
            XPath(
                f"//div[contains(@class,'documents_list')]//li"
                f"/a[contains(@href,'{url.rsplit('/', 1)[-1]}')][1]/text()"
            ),
            "document label",
            min_count=0,
            max_count=1,
        )
        return clean(labels[0]) if labels else None
