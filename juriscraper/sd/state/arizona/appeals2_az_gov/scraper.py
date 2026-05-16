"""Arizona Court of Appeals, Division Two scraper.

Site: https://www.appeals2.az.gov/ODSPlus/

Two entry points cover the user-facing search modes:

- ``active_cases``      — POSTs ``ActiveCase=Y``;
                          returns every currently-active case.
- ``cases_by_year``     — POSTs ``CaseYear=<year>``;
                          returns every case filed in that year.
- ``fetch_case``        — direct GET of a single case detail by
                          ``caseID``.

The site has a plaintext captcha bound to the ColdFusion session, so
each search starts with a GET to ``caseInfo.cfm`` (to seed the cookie
jar and get a fresh captcha number); the next step parses the number
out of the HTML and POSTs it with the search criteria. ``httpx.Client``
keeps the cookies across the chain.

Flow:
    entry → submit_search_form → parse_search_results
                                  └→ (per case) parse_case_detail → ParsedData
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import TYPE_CHECKING, ClassVar

from jkent.common.decorators import entry, step
from jkent.common.exceptions import ScraperAssumptionException
from jkent.common.page_element import PageElement
from jkent.data_types import (
    BaseScraper,
    HttpMethod,
    HTTPRequestParams,
    ParsedData,
    Request,
    Response,
    ScraperStatus,
)
from pyrate_limiter import Duration, Rate

from .models import (
    COURT_ID,
    AzCoa2Attorney,
    AzCoa2Decision,
    AzCoa2Docket,
    AzCoa2Filing,
    AzCoa2OralArgument,
    AzCoa2Party,
    AzCoa2Proceeding,
    CaseId,
    YearSearch,
)

if TYPE_CHECKING:
    from collections.abc import Generator

    from jkent.data_types import ScraperYield


SEARCH_FORM_URL = "https://www.appeals2.az.gov/ODSPlus/caseInfo.cfm"
SEARCH_POST_URL = "https://www.appeals2.az.gov/ODSPlus/caseInfo2.cfm"
CASE_DETAIL_URL = "https://www.appeals2.az.gov/ODSPlus/caseInfolast.cfm"

# Captcha appears as: Enter <strong><font color="FF0000">7820</font></strong>
_CAPTCHA_RE = re.compile(r"<strong><font[^>]*>(?P<code>\d+)</font></strong>")
# Docket-number shape: "2 CA-CR 2024-0280" → ("CR", 2024, 280).
_DOCKET_RE = re.compile(
    r"^2\s+CA-(?P<type>[A-Z]{2})\s+(?P<year>\d{4})-(?P<num>\d+)\s*$"
)
_CASE_ID_RE = re.compile(r"caseInfolast\.cfm\?caseID=(\d+)", re.I)


class AzCoa2Scraper(BaseScraper[AzCoa2Docket]):
    """Scraper for Arizona Court of Appeals, Division Two.

    Captures the full register of actions for each case — parties &
    attorneys, filings/continuances, oral-argument calendar entries,
    decisions, mandate info, MR/PR outcomes, and the chronological
    proceedings log — straight off the case-detail HTML page.
    """

    court_ids: ClassVar[set[str]] = {COURT_ID}
    court_url: ClassVar[str] = SEARCH_FORM_URL
    data_types: ClassVar[set[str]] = {"dockets"}
    status: ClassVar[ScraperStatus] = ScraperStatus.IN_DEVELOPMENT
    version: ClassVar[str] = "2026-05-02"
    requires_auth: ClassVar[bool] = False
    rate_limits: ClassVar[list[Rate] | None] = [Rate(2, Duration.SECOND)]

    # =========================================================================
    # Helpers
    # =========================================================================

    @staticmethod
    def _safe_text(element: PageElement) -> str:
        try:
            return element.text_content().strip()
        except Exception:
            return ""

    @staticmethod
    def _parse_date(raw: str | None) -> date | None:
        """Parse a ``mm/dd/yyyy`` date; return ``None`` on missing/empty."""
        if not raw:
            return None
        text = raw.strip().replace("\xa0", " ").strip()
        if not text:
            return None
        for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%m/%d/%y"):
            try:
                return datetime.strptime(text, fmt).date()
            except ValueError:
                continue
        return None

    @staticmethod
    def _clean(raw: str | None) -> str | None:
        """Strip, collapse internal whitespace, drop NBSPs; return ``None``
        for empty results."""
        if raw is None:
            return None
        text = raw.replace("\xa0", " ").strip()
        text = re.sub(r"[ \t]+\n", "\n", text)
        if not text:
            return None
        return text

    # =========================================================================
    # Entry: search the form
    # =========================================================================

    @entry(AzCoa2Docket)
    def active_cases(self) -> Generator[Request, None, None]:
        """Search for every currently-active case.

        Posts the search form with ``ActiveCase=Y`` and no other filters.
        A single response carries all results (~700-800 active cases at
        any given time; no pagination).
        """
        yield from self._seed_search({"search_kind": "active"})

    @entry(AzCoa2Docket)
    def cases_by_year(
        self, params: YearSearch
    ) -> Generator[Request, None, None]:
        """Search for every case filed in ``params.year``.

        Years between 1990 and the current year are accepted by the
        site's form. Newer years return ~700-1000 cases per response;
        older years return fewer.
        """
        if params.year < 1990 or params.year > date.today().year:
            raise ScraperAssumptionException(
                f"year {params.year} is outside the site's supported range"
            )
        yield from self._seed_search(
            {"search_kind": "year", "year": params.year}
        )

    @entry(AzCoa2Docket)
    def fetch_case(self, params: CaseId) -> Generator[Request, None, None]:
        """Direct fetch of one case detail by ``caseID``.

        The case-detail page is publicly accessible without cookies or
        captcha, so this skips the search flow entirely.
        """
        yield Request(
            request=HTTPRequestParams(
                method=HttpMethod.GET,
                url=CASE_DETAIL_URL,
                params={"caseID": str(params.case_id)},
                headers={"Accept": "text/html"},
            ),
            continuation=self.parse_case_detail,
            accumulated_data={"case_id": params.case_id},
            deduplication_key=f"case:{params.case_id}",
        )

    def _seed_search(
        self, accumulated: dict
    ) -> Generator[Request, None, None]:
        """Yield the GET to seed cookies + captcha for a search.

        The ``accumulated_data`` dict carries the search criteria
        forward to ``submit_search_form`` which converts them to a POST
        body.
        """
        yield Request(
            request=HTTPRequestParams(
                method=HttpMethod.GET,
                url=SEARCH_FORM_URL,
                headers={"Accept": "text/html"},
            ),
            continuation=self.submit_search_form,
            accumulated_data=accumulated,
        )

    # =========================================================================
    # Step: parse captcha + POST search form
    # =========================================================================

    @step()
    def submit_search_form(
        self,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[Request, None, None]:
        """Parse the four-digit captcha out of the GET response, then
        POST ``caseInfo2.cfm`` with the search criteria.

        Cookies set on the GET (CFID, CFTOKEN) flow automatically through
        ``httpx.Client`` to the POST.
        """
        match = _CAPTCHA_RE.search(response.text)
        if not match:
            raise ScraperAssumptionException(
                "captcha number not found on caseInfo.cfm — "
                "site layout may have changed"
            )
        code = match.group("code")

        data: dict[str, str] = {"searchverifycode": code}
        kind = accumulated_data["search_kind"]
        if kind == "active":
            data["ActiveCase"] = "Y"
        elif kind == "year":
            data["CaseYear"] = str(accumulated_data["year"])
        else:
            raise ScraperAssumptionException(f"unknown search_kind: {kind!r}")

        yield Request(
            request=HTTPRequestParams(
                method=HttpMethod.POST,
                url=SEARCH_POST_URL,
                data=data,
                headers={
                    "Accept": "text/html",
                    "Content-Type": "application/x-www-form-urlencoded",
                },
            ),
            continuation=self.parse_search_results,
            accumulated_data=accumulated_data,
        )

    # =========================================================================
    # Step: extract case IDs from the search results page
    # =========================================================================

    @step()
    def parse_search_results(
        self,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[Request, None, None]:
        """Pull every ``caseID`` from the result page and dispatch a
        case-detail fetch for each.

        The result page has no real pagination — all hits are emitted
        inline (verified up to ~1000 results per search). If the site
        ever paginates we'll see the cap show up as a fixed result count
        and need to add a follow-link step here.
        """
        text = response.text
        if "Please go back" in text and "verification code" in text:
            raise ScraperAssumptionException(
                "captcha rejection — verification code did not match. "
                "Likely a parser regression in submit_search_form."
            )

        seen: set[int] = set()
        for case_id_str in _CASE_ID_RE.findall(text):
            case_id = int(case_id_str)
            if case_id in seen:
                continue
            seen.add(case_id)
            yield Request(
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url=CASE_DETAIL_URL,
                    params={"caseID": str(case_id)},
                    headers={"Accept": "text/html"},
                ),
                continuation=self.parse_case_detail,
                accumulated_data={"case_id": case_id},
                deduplication_key=f"case:{case_id}",
            )

    # =========================================================================
    # Step: parse one case detail page
    # =========================================================================

    @step()
    def parse_case_detail(
        self,
        page: PageElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[AzCoa2Docket], None, None]:
        """Parse every section of a case-detail HTML page."""
        case_id = int(accumulated_data["case_id"])

        header = self._parse_header(page)
        parties = self._parse_parties(page)
        filings = self._parse_filings(page)
        oral_arguments = self._parse_oral_arguments(page)
        decisions = self._parse_decisions(page)
        mandate = self._parse_mandate(page)
        mr_pr = self._parse_mr_pr(page)
        proceedings = self._parse_proceedings(page)

        docket_number = header["docket_number"]
        case_type, case_year = self._derive_type_year(docket_number)

        docket = AzCoa2Docket(
            docket_number=docket_number,
            case_id=case_id,
            court_id=COURT_ID,
            case_type=case_type,
            case_year=case_year,
            case_name=header["case_name"],
            department=header.get("department"),
            county=header.get("county"),
            cause_numbers=header.get("cause_numbers", []),
            trial_judge=header.get("trial_judge"),
            submitted_date=header.get("submitted_date"),
            at_issue_date=header.get("at_issue_date"),
            at_issue_number=header.get("at_issue_number"),
            mandate_date=mandate.get("mandate_date"),
            mandate_vacated_date=mandate.get("mandate_vacated_date"),
            mr_outcome=mr_pr.get("mr_outcome"),
            mr_outcome_date=mr_pr.get("mr_outcome_date"),
            pr_outcome=mr_pr.get("pr_outcome"),
            pr_outcome_date=mr_pr.get("pr_outcome_date"),
            parties=parties,
            filings=filings,
            oral_arguments=oral_arguments,
            decisions=decisions,
            proceedings=proceedings,
            source_url=response.url,
        )
        yield ParsedData(data=docket)

    # =========================================================================
    # Section parsers
    # =========================================================================

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
        ths = page.query_xpath(
            "//th[contains(@class, 'thcurves')]",
            "header th",
            min_count=1,
            max_count=1,
        )
        raw = self._safe_text(ths[0])

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

        out["department"] = self._clean(labelled.get("Department"))
        out["county"] = self._clean(labelled.get("County"))

        cause_raw = labelled.get("Cause Numbers")
        if cause_raw:
            out["cause_numbers"] = [
                c.strip() for c in re.split(r"[,;]\s*", cause_raw) if c.strip()
            ]

        out["submitted_date"] = self._parse_date(labelled.get("Submitted"))
        out["at_issue_date"] = self._parse_date(labelled.get("At Issue Date"))
        out["at_issue_number"] = self._clean(labelled.get("At Issue Number"))

        if bare_lines:
            out["trial_judge"] = bare_lines[0]

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
        rows = page.query_xpath(
            "//table[.//th[contains(., 'Party/Attorney Information')]]//tr",
            "party table rows",
            min_count=0,
        )
        parties: list[AzCoa2Party] = []
        for row in rows:
            cells = row.query_xpath("./td", "party row cells", min_count=0)
            if len(cells) != 2:
                # Header row (only <th>) or layout glitch; skip.
                continue
            party_blocks = self._html_blocks(cells[0])
            attorney_blocks = self._html_blocks(cells[1])
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
    def _html_blocks(cell: PageElement) -> list[list[str]]:
        """Convert a cell's inner HTML to a list of blocks; each block
        is a list of non-empty trimmed lines.

        ``<br>`` becomes a line break, ``<p></p>`` becomes a block
        boundary. Empty blocks (and blocks containing only whitespace)
        are dropped. HTML entities are unescaped.

        We assemble the inner HTML manually rather than using
        ``cell.inner_html()`` — kent's implementation iterates only
        over child elements, so the cell's leading text node (the
        first party name in this site's layout) is silently dropped.
        """
        from html import unescape

        from lxml import etree

        try:
            elem = cell._element._element  # type: ignore[attr-defined]
        except AttributeError:
            return []
        leading = elem.text or ""
        children = "".join(
            etree.tostring(child, encoding="unicode", method="html")
            for child in elem
        )
        markup = leading + children
        # Normalise <br> variants to a line break.
        markup = re.sub(r"(?i)<br\s*/?>", "\n", markup)
        # <p></p> (empty paragraph) is the block separator.
        block_sentinel = "\x00BLOCK\x00"
        markup = re.sub(
            r"(?i)<p\s*[^/>]*>\s*</p\s*>",
            block_sentinel,
            markup,
        )
        # Strip any remaining tags.
        markup = re.sub(r"<[^>]+>", "", markup)
        markup = unescape(markup)
        blocks: list[list[str]] = []
        for raw_block in markup.split(block_sentinel):
            lines = [
                re.sub(r"\s+", " ", ln).strip()
                for ln in raw_block.splitlines()
            ]
            lines = [ln for ln in lines if ln]
            if lines:
                blocks.append(lines)
        return blocks

    @staticmethod
    def _parse_party_blocks(
        blocks: list[list[str]],
    ) -> list[AzCoa2Party]:
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
        cls,
        blocks: list[list[str]],
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

    def _parse_filings(self, page: PageElement) -> list[AzCoa2Filing]:
        """Parse the Filings, Dues, and Continuances table."""
        rows = page.query_xpath(
            "//table[.//th[contains(., 'Filings, Dues')]]//tr",
            "filings rows",
            min_count=0,
        )
        out: list[AzCoa2Filing] = []
        for row in rows:
            cells = row.query_xpath("./td", "filings cells", min_count=0)
            if len(cells) != 6:
                continue
            doc_type = self._clean(self._safe_text(cells[0]))
            if not doc_type:
                continue
            out.append(
                AzCoa2Filing(
                    document_type=doc_type,
                    due_date=self._parse_date(self._safe_text(cells[1])),
                    document_title=self._clean(self._safe_text(cells[2])),
                    filing_date=self._parse_date(self._safe_text(cells[3])),
                    attorney=self._clean(self._safe_text(cells[4])),
                    category=self._clean(self._safe_text(cells[5])),
                )
            )
        return out

    def _parse_oral_arguments(
        self, page: PageElement
    ) -> list[AzCoa2OralArgument]:
        """Parse the Calendar and Agenda Information table."""
        rows = page.query_xpath(
            "//table[.//th[contains(.,"
            " 'Calendar and Agenda Information')]]//tr",
            "OA rows",
            min_count=0,
        )
        out: list[AzCoa2OralArgument] = []
        for row in rows:
            cells = row.query_xpath("./td", "OA cells", min_count=0)
            if len(cells) != 7:
                continue
            cell_texts = [self._safe_text(c) for c in cells]
            # Skip rows that are entirely empty.
            if not any(self._clean(t) for t in cell_texts):
                continue
            out.append(
                AzCoa2OralArgument(
                    request_due=self._parse_date(cell_texts[0]),
                    filed=self._parse_date(cell_texts[1]),
                    request_by=self._clean(cell_texts[2]),
                    request_result=self._clean(cell_texts[3]),
                    argument_date=self._parse_date(cell_texts[4]),
                    argument_time=self._clean(cell_texts[5]),
                    argument_type=self._clean(cell_texts[6]),
                )
            )
        return out

    def _parse_decisions(self, page: PageElement) -> list[AzCoa2Decision]:
        """Parse the Decision Information table."""
        rows = page.query_xpath(
            "//table[.//th[contains(., 'Decision Information')]]//tr",
            "decision rows",
            min_count=0,
        )
        out: list[AzCoa2Decision] = []
        for row in rows:
            cells = row.query_xpath("./td", "decision cells", min_count=0)
            if len(cells) != 3:
                continue
            cell_texts = [self._safe_text(c) for c in cells]
            if not any(self._clean(t) for t in cell_texts):
                continue
            out.append(
                AzCoa2Decision(
                    decision_type=self._clean(cell_texts[0]),
                    decision_date=self._parse_date(cell_texts[1]),
                    result_type=self._clean(cell_texts[2]),
                )
            )
        return out

    def _parse_mandate(self, page: PageElement) -> dict:
        """Parse the Mandate scalars."""
        rows = page.query_xpath(
            "//table[.//th[contains(., 'Mandate')"
            " and not(contains(., 'MR'))]]//tr",
            "mandate rows",
            min_count=0,
        )
        for row in rows:
            cells = row.query_xpath("./td", "mandate cells", min_count=0)
            if len(cells) != 2:
                continue
            return {
                "mandate_date": self._parse_date(self._safe_text(cells[0])),
                "mandate_vacated_date": self._parse_date(
                    self._safe_text(cells[1])
                ),
            }
        return {}

    def _parse_mr_pr(self, page: PageElement) -> dict:
        """Parse the MR/PR Outcome scalars."""
        rows = page.query_xpath(
            "//table[.//th[contains(., 'MR/PR Outcome')]]//tr",
            "MR/PR rows",
            min_count=0,
        )
        for row in rows:
            cells = row.query_xpath("./td", "MR/PR cells", min_count=0)
            if len(cells) != 4:
                continue
            return {
                "mr_outcome": self._clean(self._safe_text(cells[0])),
                "mr_outcome_date": self._parse_date(self._safe_text(cells[1])),
                "pr_outcome": self._clean(self._safe_text(cells[2])),
                "pr_outcome_date": self._parse_date(self._safe_text(cells[3])),
            }
        return {}

    def _parse_proceedings(self, page: PageElement) -> list[AzCoa2Proceeding]:
        """Parse the Proceedings table — the chronological master log.

        Description cells preserve internal whitespace verbatim so that
        the formatting of judicial orders (often pre-formatted text) is
        retained.
        """
        rows = page.query_xpath(
            "//table[.//th[contains(., 'Proceedings')]]//tr",
            "proceeding rows",
            min_count=0,
        )
        out: list[AzCoa2Proceeding] = []
        for row in rows:
            cells = row.query_xpath("./td", "proceeding cells", min_count=0)
            if len(cells) != 3:
                continue
            ptype = self._clean(self._safe_text(cells[0]))
            if not ptype:
                continue
            # Description: preserve internal newlines/spacing.
            raw_desc = cells[2].text_content()
            desc = raw_desc.replace("\xa0", " ").strip("\n").rstrip()
            out.append(
                AzCoa2Proceeding(
                    proceeding_type=ptype,
                    proceeding_date=self._parse_date(
                        self._safe_text(cells[1])
                    ),
                    description=desc,
                )
            )
        return out

    @staticmethod
    def _derive_type_year(docket_number: str) -> tuple[str | None, int | None]:
        """Pull case_type + case_year from the display docket number."""
        m = _DOCKET_RE.match(docket_number)
        if not m:
            return None, None
        return m.group("type"), int(m.group("year"))
