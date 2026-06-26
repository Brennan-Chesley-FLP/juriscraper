"""Parser for an Arizona CoA Division Two case-detail page.

One ``caseInfolast.cfm?caseID=<id>`` page renders the full register of
actions in plain HTML tables. :class:`CaseDetailParser` extracts every
section into a single :class:`AzCoa2Docket`. The page does *not* carry
the numeric ``caseID`` or the source URL — the step stamps those onto
the returned ``raw_data`` before emitting (see ``scraper.py``).
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, ClassVar

from jkent.common.deferred_validation import DeferredValidation
from jkent.common.exceptions import ScraperAssumptionException
from jkent.common.parser import JKentParser
from jkent.data_types import XPath

from juriscraper.state.arizona.appeals2_az_gov.models import (
    AzCoa2Attorney,
    AzCoa2Decision,
    AzCoa2Docket,
    AzCoa2Filing,
    AzCoa2OralArgument,
    AzCoa2Party,
    AzCoa2Proceeding,
)

from ._common import clean, html_blocks, parse_date, safe_text

if TYPE_CHECKING:
    from jkent.common.page_element import PageElement

# Docket-number shape: "2 CA-CR 2024-0280" → ("CR", 2024, 280).
_DOCKET_RE = re.compile(
    r"^2\s+CA-(?P<type>[A-Z]{2})\s+(?P<year>\d{4})-(?P<num>\d+)\s*$"
)


class CaseDetailParser(JKentParser[AzCoa2Docket]):
    """Parse every section of an Arizona CoA Div. Two case-detail page.

    Returns a single-element list with one ``AzCoa2Docket`` carrying the
    header scalars and the nested party/filing/oral-argument/decision/
    proceeding records. ``case_id``, ``court``, ``source_url``, and
    ``source_entry_point`` are stamped by the calling step.
    """

    def __call__(
        self, page: PageElement
    ) -> list[DeferredValidation[AzCoa2Docket]]:
        header = self._parse_header(page)
        mandate = self._parse_mandate(page)
        mr_pr = self._parse_mr_pr(page)

        docket_number = header["docket_number"]
        case_type, case_year = self._derive_type_year(docket_number)

        docket = AzCoa2Docket.raw(
            docket_number=docket_number,
            case_type=case_type,
            case_year=case_year,
            case_name=header["case_name"],
            department=header.get("department"),
            county=header.get("county"),
            cause_numbers=header.get("cause_numbers", []),
            assigned_to_str=header.get("assigned_to_str"),
            date_submitted=header.get("date_submitted"),
            date_at_issue=header.get("date_at_issue"),
            at_issue_number=header.get("at_issue_number"),
            date_mandate=mandate.get("date_mandate"),
            date_mandate_vacated=mandate.get("date_mandate_vacated"),
            mr_outcome=mr_pr.get("mr_outcome"),
            date_mr_outcome=mr_pr.get("date_mr_outcome"),
            pr_outcome=mr_pr.get("pr_outcome"),
            date_pr_outcome=mr_pr.get("date_pr_outcome"),
            parties=self._parse_parties(page),
            filings=self._parse_filings(page),
            oral_arguments=self._parse_oral_arguments(page),
            decisions=self._parse_decisions(page),
            proceedings=self._parse_proceedings(page),
        )
        return [docket]

    # =====================================================================
    # Header
    # =====================================================================

    _HEADER_LABELS: ClassVar[tuple[str, ...]] = (
        "Department:",
        "County:",
        "Cause Numbers:",
        "Submitted:",
        "At Issue Date:",
        "At Issue Number:",
    )

    def _parse_header(self, page: PageElement) -> dict:
        """Extract the case header (docket #, caption, dept, county,
        cause #s, trial judge, submitted/at-issue dates).

        The header is one big ``<th class="thcurves">`` cell with
        labelled fields (``<b>Label:</b> value``) separated by ``<br>``
        and ``<p>`` markers, plus a bare-text trial-judge line wedged
        between Cause Numbers and Submitted. We split the cell's text
        on newlines and process line-by-line so the bare line stays
        attributable to the trial judge.
        """
        ths = page.query(
            XPath("//th[contains(@class, 'thcurves')]"),
            "header th",
            min_count=1,
            max_count=1,
        )
        raw = safe_text(ths[0])

        lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
        if not lines:
            raise ScraperAssumptionException("empty case header")

        first = lines[0]
        m = re.match(
            r"^(?P<docket>2\s+CA-[A-Z]{2}\s+\d{4}-\d+)\s+(?P<name>.+)$",
            first,
        )
        if not m:
            raise ScraperAssumptionException(
                f"unable to parse docket+caption from header: {first!r}"
            )
        out: dict = {
            "docket_number": m.group("docket").strip(),
            "case_name": m.group("name").strip(),
            "cause_numbers": [],
        }

        # Walk subsequent lines. A line may carry one OR several
        # "<Label>: <value>" pairs concatenated; or it may be bare text
        # (the trial judge name).
        labelled: dict[str, str] = {}
        bare_lines: list[str] = []
        for ln in lines[1:]:
            pairs = self._split_label_line(ln)
            if pairs:
                labelled.update(pairs)
            else:
                bare_lines.append(ln)

        out["department"] = clean(labelled.get("Department"))
        out["county"] = clean(labelled.get("County"))

        cause_raw = labelled.get("Cause Numbers")
        if cause_raw:
            out["cause_numbers"] = [
                c.strip() for c in re.split(r"[,;]\s*", cause_raw) if c.strip()
            ]

        out["date_submitted"] = parse_date(labelled.get("Submitted"))
        out["date_at_issue"] = parse_date(labelled.get("At Issue Date"))
        out["at_issue_number"] = clean(labelled.get("At Issue Number"))

        if bare_lines:
            out["assigned_to_str"] = bare_lines[0]

        return out

    @classmethod
    def _split_label_line(cls, line: str) -> dict[str, str] | None:
        """Split a header line into ``{label: value}`` pairs.

        Returns ``None`` when ``line`` carries no recognised label —
        the caller treats that as the bare-text trial-judge line.
        Multiple pairs on one line (e.g. ``Submitted: ... At Issue
        Date: ... At Issue Number: ...``) are split apart.
        """
        labels = cls._HEADER_LABELS
        if not any(label in line for label in labels):
            return None
        # Find each label's position; sort; slice between successive labels.
        hits: list[tuple[int, str]] = []
        for label in labels:
            for m in re.finditer(re.escape(label), line):
                hits.append((m.start(), label))
        hits.sort()
        out: dict[str, str] = {}
        for i, (start, label) in enumerate(hits):
            value_start = start + len(label)
            value_end = hits[i + 1][0] if i + 1 < len(hits) else len(line)
            out[label.rstrip(":")] = line[value_start:value_end].strip()
        return out

    # =====================================================================
    # Parties & attorneys
    # =====================================================================

    def _parse_parties(self, page: PageElement) -> list[AzCoa2Party]:
        """Parse the Party/Attorney Information table.

        Each data row is a 2-column ``(party-block, attorney-block)``
        pair. Both blocks use ``<br>`` for intra-attorney/intra-party
        line breaks and ``<p></p>`` as the block separator between
        successive attorneys (or between successive parties bundled in
        the same row, if any).

        ``text_content()`` collapses these markers, so we work off the
        cell's inner HTML and reconstruct the line/block structure by
        substituting ``<br>`` → ``\n`` and splitting on ``<p></p>``.
        """
        rows = page.query(
            XPath(
                "//table[.//th[contains(., 'Party/Attorney Information')]]//tr"
            ),
            "party table rows",
            min_count=0,
        )
        parties: list[AzCoa2Party] = []
        for row in rows:
            cells = row.query(XPath("./td"), "party row cells", min_count=0)
            if len(cells) != 2:
                # Header row (only <th>) or layout glitch; skip.
                continue
            party_blocks = html_blocks(cells[0])
            attorney_blocks = html_blocks(cells[1])
            if not party_blocks and not attorney_blocks:
                continue
            attorneys = self._parse_attorney_blocks(attorney_blocks)
            for party in self._parse_party_blocks(party_blocks):
                # Multiple parties in one row share the same attorney
                # roster (e.g. consolidated co-plaintiffs).
                party.attorneys = list(attorneys)
                parties.append(party)
        return parties

    @staticmethod
    def _parse_party_blocks(blocks: list[list[str]]) -> list[AzCoa2Party]:
        """Convert a party cell's blocks into ``AzCoa2Party`` records.

        A party cell can carry several names (consolidated parties)
        followed by one role line (e.g.
        ``KLUMP MATERIALS, LLC | KLUMP RANCHES, LLC | Plaintiffs/Appellants``).
        We emit one ``AzCoa2Party`` per name, all sharing the role.
        """
        if not blocks:
            return []
        # Most rows are one block; defensively flatten.
        all_lines: list[str] = []
        for block in blocks:
            all_lines.extend(block)
        if not all_lines:
            return []
        # The role is the last line; everything before it is a party name.
        role = all_lines[-1].rstrip(",").rstrip()
        names = [
            ln.rstrip(",").rstrip() for ln in all_lines[:-1] if ln.strip()
        ]
        if not names:
            # No name? Treat the single line as the name with no role.
            return [AzCoa2Party(name=role, role=None)]
        return [AzCoa2Party(name=name, role=role) for name in names]

    _APPOINTMENT_KEYWORDS: ClassVar[frozenset[str]] = frozenset(
        {
            "appointed",
            "retained",
            "pro bono",
            "self represented",
            "self-represented",
            "pro per",
            "court appointed",
            "in pro per",
        }
    )

    @classmethod
    def _parse_attorney_blocks(
        cls, blocks: list[list[str]]
    ) -> list[AzCoa2Attorney]:
        """Convert attorney-cell blocks into ``AzCoa2Attorney`` records.

        Each block is one attorney-appearance block of 1–3 lines:
        ``[name, firm?, appointment?]`` — the appointment line, when
        present, is one of a small known set of keywords.

        The site occasionally emits stray blocks containing only an
        appointment keyword (no name, no firm) — usually as filler
        between named-attorney blocks. Drop those.
        """
        attorneys: list[AzCoa2Attorney] = []
        for lines in blocks:
            if not lines:
                continue
            # Skip filler blocks that are only a bare appointment word.
            if all(ln.lower() in cls._APPOINTMENT_KEYWORDS for ln in lines):
                continue
            name = lines[0]
            appointment: str | None = None
            firm_lines: list[str] = []
            for extra in lines[1:]:
                if extra.lower() in cls._APPOINTMENT_KEYWORDS:
                    appointment = extra
                else:
                    firm_lines.append(extra)
            firm = "; ".join(firm_lines) or None
            attorneys.append(
                AzCoa2Attorney(name=name, firm=firm, appointment=appointment)
            )
        return attorneys

    # =====================================================================
    # Filings
    # =====================================================================

    def _parse_filings(self, page: PageElement) -> list[AzCoa2Filing]:
        """Parse the Filings, Dues, and Continuances table."""
        rows = page.query(
            XPath("//table[.//th[contains(., 'Filings, Dues')]]//tr"),
            "filings rows",
            min_count=0,
        )
        out: list[AzCoa2Filing] = []
        for row in rows:
            cells = row.query(XPath("./td"), "filings cells", min_count=0)
            if len(cells) != 6:
                continue
            doc_type = clean(safe_text(cells[0]))
            if not doc_type:
                continue
            out.append(
                AzCoa2Filing(
                    document_type=doc_type,
                    date_due=parse_date(safe_text(cells[1])),
                    document_title=clean(safe_text(cells[2])),
                    date_filed=parse_date(safe_text(cells[3])),
                    attorney=clean(safe_text(cells[4])),
                    category=clean(safe_text(cells[5])),
                )
            )
        return out

    # =====================================================================
    # Oral arguments
    # =====================================================================

    def _parse_oral_arguments(
        self, page: PageElement
    ) -> list[AzCoa2OralArgument]:
        """Parse the Calendar and Agenda Information table."""
        rows = page.query(
            XPath(
                "//table[.//th[contains(.,"
                " 'Calendar and Agenda Information')]]//tr"
            ),
            "OA rows",
            min_count=0,
        )
        out: list[AzCoa2OralArgument] = []
        for row in rows:
            cells = row.query(XPath("./td"), "OA cells", min_count=0)
            if len(cells) != 7:
                continue
            cell_texts = [safe_text(c) for c in cells]
            # Skip rows that are entirely empty.
            if not any(clean(t) for t in cell_texts):
                continue
            out.append(
                AzCoa2OralArgument(
                    date_request_due=parse_date(cell_texts[0]),
                    date_filed=parse_date(cell_texts[1]),
                    request_by=clean(cell_texts[2]),
                    request_result=clean(cell_texts[3]),
                    date_argument=parse_date(cell_texts[4]),
                    argument_time=clean(cell_texts[5]),
                    argument_type=clean(cell_texts[6]),
                )
            )
        return out

    # =====================================================================
    # Decisions
    # =====================================================================

    def _parse_decisions(self, page: PageElement) -> list[AzCoa2Decision]:
        """Parse the Decision Information table."""
        rows = page.query(
            XPath("//table[.//th[contains(., 'Decision Information')]]//tr"),
            "decision rows",
            min_count=0,
        )
        out: list[AzCoa2Decision] = []
        for row in rows:
            cells = row.query(XPath("./td"), "decision cells", min_count=0)
            if len(cells) != 3:
                continue
            cell_texts = [safe_text(c) for c in cells]
            if not any(clean(t) for t in cell_texts):
                continue
            out.append(
                AzCoa2Decision(
                    decision_type=clean(cell_texts[0]),
                    date_decision=parse_date(cell_texts[1]),
                    result_type=clean(cell_texts[2]),
                )
            )
        return out

    # =====================================================================
    # Mandate / MR-PR scalars
    # =====================================================================

    def _parse_mandate(self, page: PageElement) -> dict:
        """Parse the Mandate scalars."""
        rows = page.query(
            XPath(
                "//table[.//th[contains(., 'Mandate')"
                " and not(contains(., 'MR'))]]//tr"
            ),
            "mandate rows",
            min_count=0,
        )
        for row in rows:
            cells = row.query(XPath("./td"), "mandate cells", min_count=0)
            if len(cells) != 2:
                continue
            return {
                "date_mandate": parse_date(safe_text(cells[0])),
                "date_mandate_vacated": parse_date(safe_text(cells[1])),
            }
        return {}

    def _parse_mr_pr(self, page: PageElement) -> dict:
        """Parse the MR/PR Outcome scalars."""
        rows = page.query(
            XPath("//table[.//th[contains(., 'MR/PR Outcome')]]//tr"),
            "MR/PR rows",
            min_count=0,
        )
        for row in rows:
            cells = row.query(XPath("./td"), "MR/PR cells", min_count=0)
            if len(cells) != 4:
                continue
            return {
                "mr_outcome": clean(safe_text(cells[0])),
                "date_mr_outcome": parse_date(safe_text(cells[1])),
                "pr_outcome": clean(safe_text(cells[2])),
                "date_pr_outcome": parse_date(safe_text(cells[3])),
            }
        return {}

    # =====================================================================
    # Proceedings
    # =====================================================================

    def _parse_proceedings(self, page: PageElement) -> list[AzCoa2Proceeding]:
        """Parse the Proceedings table — the chronological master log.

        Description cells preserve internal whitespace verbatim so that
        the formatting of judicial orders (often pre-formatted text) is
        retained.
        """
        rows = page.query(
            XPath("//table[.//th[contains(., 'Proceedings')]]//tr"),
            "proceeding rows",
            min_count=0,
        )
        out: list[AzCoa2Proceeding] = []
        for row in rows:
            cells = row.query(XPath("./td"), "proceeding cells", min_count=0)
            if len(cells) != 3:
                continue
            ptype = clean(safe_text(cells[0]))
            if not ptype:
                continue
            # Description: preserve internal newlines/spacing.
            raw_desc = cells[2].text_content()
            desc = raw_desc.replace("\xa0", " ").strip("\n").rstrip()
            out.append(
                AzCoa2Proceeding(
                    proceeding_type=ptype,
                    date_proceeding=parse_date(safe_text(cells[1])),
                    description=desc,
                )
            )
        return out

    # =====================================================================
    # Helpers
    # =====================================================================

    @staticmethod
    def _derive_type_year(
        docket_number: str,
    ) -> tuple[str | None, int | None]:
        """Pull case_type + case_year from the display docket number."""
        m = _DOCKET_RE.match(docket_number)
        if not m:
            return None, None
        return m.group("type"), int(m.group("year"))
