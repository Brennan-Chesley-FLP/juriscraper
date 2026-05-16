"""North Carolina Appellate Courts docket scraper.

Scrapes dockets for the Supreme Court of North Carolina (``nc``) and
the North Carolina Court of Appeals (``ncctapp``). The scraper has two
entry points:

- ``get_docket(docket_number: str)`` — single-case lookup by visible
  docket number (e.g. ``26-310``, ``P26-334``, ``15P26``). Routes to
  the right court by regex on the docket format.
- ``get_dockets_by_date(date_range: DateRange)`` — surface every case
  with at least one e-filing in the window.

Per-case flow::

    get_docket
        │
        ▼
    parse_docket_search_result       (dockets.php?...&submit=Search)
        │  ── follows the link
        ▼
    parse_docket_sheet               (dockets.php?...&pdf=1) ── yields NCAppealsDocket

    get_dockets_by_date
        │
        ▼
    parse_filings_listing            (search-results.php?start_date=…)
        │  ── one Request per unique case
        │  ── pagination Request(s) for each remaining iStart offset
        ▼
    parse_docket_sheet               (dockets.php?...&pdf=1) ── yields NCAppealsDocket

The "PDF" docket sheet at ``dockets.php?…&pdf=1`` is actually styled
HTML, despite the parameter name — see ``DESIGN.md``.

Soft-404: ``parse_docket_search_result`` is reached only via an HTTP 200
response, but a miss is signalled by the literal text "0 case" inside
the result page. We flag that case in ``fails_successfully``.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import TYPE_CHECKING, ClassVar

from jkent.common.decorators import entry, step
from jkent.common.page_element import PageElement
from jkent.common.param_models import DateRange
from jkent.data_types import (
    BaseScraper,
    HttpMethod,
    HTTPRequestParams,
    ParsedData,
    Request,
    Response,
    ScraperStatus,
    SkipDeduplicationCheck,
)
from pyrate_limiter import Duration, Rate

from .models import (
    COURT_COA,
    COURT_SC,
    SITE_COURT_ID,
    NCAppealsAttorney,
    NCAppealsDocket,
    NCAppealsDocketEntry,
    NCAppealsDocument,
    NCAppealsLowerCourt,
    NCAppealsParty,
)

if TYPE_CHECKING:
    from collections.abc import Generator

    from jkent.data_types import ScraperYield


# ─── URLs ─────────────────────────────────────────────────────────────
DOCKETS_BASE = "https://appellate.nccourts.org/dockets.php"
SEARCH_RESULTS_URL = "https://www.ncappellatecourts.org/search-results.php"

PAGE_SIZE = 50  # search-results.php pages 50 cases at a time

# ─── Regexes for routing visible docket numbers to the right court ────
# COA appeals of right and petitions: ``26-310``, ``P26-334``,
# ``25-1111``, ``258A22-2`` is *not* matched here (that's SC).
_COA_DOCKET_RE = re.compile(r"^P?\d{1,2}-\d+(?:-\d+)?$")
# SC: digits, letters, two-digit year, optional ``-N`` suffix
# (e.g. ``15P26``, ``1A26``, ``1PA26``, ``258A22-2``).
_SC_DOCKET_RE = re.compile(r"^\d+[A-Z]+\d{2}(?:-\d+)?$")

# ─── Regexes for parsing surface strings ──────────────────────────────
_DATE_MDY_RE = re.compile(r"\b(\d{2})-(\d{2})-(\d{4})\b")  # 04-02-2026
_DATE_SLASH_RE = re.compile(r"\b(\d{2})/(\d{2})/(\d{4})\b")  # 05/04/2026
_BR_RE = re.compile(r"<\s*br\s*/?\s*>", re.IGNORECASE)
_WS_RE = re.compile(r"\s+")

# A "docket entry" expansion below the Documents table looks like::
#
#     2 - M-SEAL  (Allowed) - 04-06-2026
#     Filed: 04-02-2026 @ 09:37:13
#     FOR: Defendant-Appellant Sings, Janice Elaine
#     BY   : Ms. Callie S. Thomas
#               OFFICE OF THE APPELLATE DEFENDER
#
# We pull the index/type/ruling/ruling-date from the header line and
# then ``Filed:`` / ``FOR:`` / ``BY:`` from the body lines.
# Document types may contain parentheses (e.g. ``RECORD RULE 9(D)
# COPIES …``), so the type is matched non-greedily. The ruling tail
# only fires when both the parenthesised verdict *and* the trailing
# date are present, anchoring at end of line.
_ENTRY_HEADER_RE = re.compile(
    r"^(?P<idx>\d+)\s*-\s*"
    r"(?P<type>[^\n]+?)"
    r"(?:\s+\((?P<ruling>[^)\n]+)\)\s*-\s*"
    r"(?P<rdate>\d{2}-\d{2}-\d{4}))?\s*$"
)


def _clean(value: str | None) -> str | None:
    """Collapse whitespace and trim."""
    if value is None:
        return None
    text = _WS_RE.sub(" ", value).strip()
    return text or None


def _parse_date(value: str | None) -> date | None:
    """Parse the docket sheet's ``MM-DD-YYYY`` and ``MM/DD/YYYY`` dates."""
    if not value:
        return None
    match = _DATE_MDY_RE.search(value)
    fmt = "%m-%d-%Y"
    if not match:
        match = _DATE_SLASH_RE.search(value)
        fmt = "%m/%d/%Y"
    if not match:
        return None
    try:
        return datetime.strptime(match.group(0), fmt).date()
    except ValueError:
        return None


def _parse_yes_no(value: str | None) -> bool | None:
    """Parse the docket sheet's ``Yes`` / ``No`` flags."""
    if value is None:
        return None
    text = value.strip().lower()
    if not text:
        return None
    if text.startswith("y"):
        return True
    if text.startswith("n"):
        return False
    return None


def _route_court(docket_number: str) -> str:
    """Pick the CourtListener court id from a visible docket number.

    Raises ``ValueError`` if the format isn't recognised.
    """
    text = docket_number.strip().upper()
    if _COA_DOCKET_RE.match(text):
        return COURT_COA
    if _SC_DOCKET_RE.match(text):
        return COURT_SC
    raise ValueError(
        f"Docket number {docket_number!r} doesn't match any known NC "
        "appellate format (COA: 'P?YY-N', SC: 'NXY[-N]')."
    )


class NorthCarolinaAppellateScraper(
    BaseScraper[NCAppealsDocket | NCAppealsDocument]
):
    """Scraper for NC Supreme Court and Court of Appeals dockets.

    Both courts share the same docket-sheet layout, served from
    ``appellate.nccourts.org/dockets.php?…&pdf=1`` (which is HTML, not
    PDF — see DESIGN.md).
    """

    # === Metadata ===
    court_ids: ClassVar[set[str]] = {COURT_SC, COURT_COA}
    court_url: ClassVar[str] = "https://www.ncappellatecourts.org/"
    data_types: ClassVar[set[str]] = {"dockets"}
    status: ClassVar[ScraperStatus] = ScraperStatus.IN_DEVELOPMENT
    version: ClassVar[str] = "2026-05-04"
    requires_auth: ClassVar[bool] = False

    rate_limits: ClassVar[list[Rate] | None] = [Rate(1, Duration.SECOND)]

    # =========================================================================
    # Entry points
    # =========================================================================

    @entry(NCAppealsDocket)
    def get_docket(self, docket_number: str) -> Generator[Request, None, None]:
        """Look up one case by its visible docket number.

        Routes to ``court=1`` (Supreme Court) or ``court=2`` (Court of
        Appeals) by regex on the docket number.
        """
        court_id = _route_court(docket_number)
        site_court = SITE_COURT_ID[court_id]
        yield Request(
            request=HTTPRequestParams(
                method=HttpMethod.GET,
                url=DOCKETS_BASE,
                params={
                    "court": str(site_court),
                    "docket": docket_number,
                    "title": "",
                    "submit": "Search",
                },
            ),
            continuation=self.parse_docket_search_result,
            accumulated_data={
                "docket_number": docket_number,
                "court_id": court_id,
                "entry_point": "get_docket",
            },
            deduplication_key=docket_number,
        )

    @entry(NCAppealsDocket)
    def get_dockets_by_date(
        self, date_range: DateRange
    ) -> Generator[Request, None, None]:
        """Walk the e-filing library for every case touched in the date
        range.

        ``search-results.php`` filters on document filing date — i.e.
        the result is "every case with any e-filing between
        ``start_date`` and ``end_date``", not "every case opened in
        that window".

        ``bSearchTypeAnd=0`` is required: with the default ``=1`` the
        site silently ignores the date params and returns the whole
        corpus.
        """
        start = date_range.start.isoformat()
        end = date_range.end.isoformat()
        yield Request(
            request=HTTPRequestParams(
                method=HttpMethod.GET,
                url=SEARCH_RESULTS_URL,
                params={
                    "atty_first": "",
                    "atty_last": "",
                    "sDocketSearch": "",
                    "short_title": "",
                    "party": "",
                    "start_date": start,
                    "end_date": end,
                    "type": "",
                    "court_name": "",
                    "bSearchTypeAnd": "0",
                    "exact": "0",
                    "iStart": "0",
                },
            ),
            continuation=self.parse_filings_listing,
            accumulated_data={
                "start_date": start,
                "end_date": end,
                "entry_point": "get_dockets_by_date",
            },
            deduplication_key=SkipDeduplicationCheck(),
        )

    # =========================================================================
    # Soft-404 detection — only for docket-number lookups
    # =========================================================================

    def fails_successfully(self, response: Response) -> bool:
        """Flag ``dockets.php?…&submit=Search`` results with 0 cases.

        Other 200 responses (date-range listings with no rows, the rich
        docket-sheet detail page, etc.) are passed through as
        successes.
        """
        if response.status_code != 200:
            return True
        url = response.url or ""
        if "/dockets.php" not in url or "submit=Search" not in url:
            return True
        text = response.text or ""
        return not (
            "Your search returned a total of" in text and ">0 case" in text
        )

    # =========================================================================
    # Steps
    # =========================================================================

    @step()
    def parse_docket_search_result(
        self,
        page: PageElement,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[NCAppealsDocket], None, None]:
        """Follow the docket-sheet link from a 1-result search page."""
        # The result page renders: ``<a href="…&pdf=1…">{caption}</a> -
        # <strong>{docket}</strong>``. There's exactly one such link on
        # a successful single-docket lookup.
        hrefs = page.query_xpath_strings(
            "//a[contains(@href, 'pdf=1')]/@href",
            "docket sheet link",
            min_count=1,
            max_count=1,
        )
        accumulated_data["source_url"] = _normalize_url(hrefs[0])
        yield Request(
            request=HTTPRequestParams(
                method=HttpMethod.GET,
                url=accumulated_data["source_url"],
            ),
            continuation=self.parse_docket_sheet,
            accumulated_data=accumulated_data,
            deduplication_key=accumulated_data["docket_number"],
        )

    @step()
    def parse_filings_listing(
        self,
        page: PageElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[NCAppealsDocket], None, None]:
        """Walk one page of the filings listing.

        Yields one per-case Request for every unique case on the page,
        plus follow-up pagination Requests for each remaining ``iStart``
        offset listed in the page's selector dropdown.
        """
        case_blocks = page.query_xpath(
            "//div["
            "contains(@class, 'docket-')"
            " and contains(@class, 'pt-2')"
            " and not(contains(@class, 'border-top'))"
            "]",
            "case header blocks",
            min_count=0,
        )
        seen_dockets: set[str] = set()
        for block in case_blocks:
            heading = block.query_xpath_strings(
                ".//h4/text()", "case heading", min_count=0, max_count=1
            )
            if not heading:
                continue
            docket_number, _, case_name = heading[0].partition(" : ")
            docket_number = _clean(docket_number) or ""
            case_name = _clean(case_name) or ""
            if not docket_number or docket_number in seen_dockets:
                continue
            sheet_hrefs = block.query_xpath_strings(
                ".//a[contains(@href, 'pdf=1')]/@href",
                "docket sheet link",
                min_count=0,
                max_count=1,
            )
            if not sheet_hrefs:
                continue
            seen_dockets.add(docket_number)

            sheet_url = _normalize_url(sheet_hrefs[0])
            court_id = _court_from_sheet_url(sheet_url)
            yield Request(
                request=HTTPRequestParams(
                    method=HttpMethod.GET, url=sheet_url
                ),
                continuation=self.parse_docket_sheet,
                accumulated_data={
                    "docket_number": docket_number,
                    "court_id": court_id,
                    "case_name_hint": case_name,
                    "source_url": sheet_url,
                    "entry_point": accumulated_data.get("entry_point"),
                },
                deduplication_key=docket_number,
            )

        # Follow-up pages from the iStart selector. We only enqueue
        # offsets greater than the current page's so the same page
        # isn't re-fetched.
        current_offset = _current_istart(response.url)
        for offset in _pagination_offsets(page):
            if offset <= current_offset:
                continue
            yield Request(
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url=SEARCH_RESULTS_URL,
                    params={
                        "atty_first": "",
                        "atty_last": "",
                        "sDocketSearch": "",
                        "short_title": "",
                        "party": "",
                        "start_date": accumulated_data["start_date"],
                        "end_date": accumulated_data["end_date"],
                        "type": "",
                        "court_name": "",
                        "bSearchTypeAnd": "0",
                        "exact": "0",
                        "iStart": str(offset),
                    },
                ),
                continuation=self.parse_filings_listing,
                accumulated_data=accumulated_data,
                deduplication_key=SkipDeduplicationCheck(),
            )

    @step()
    def parse_docket_sheet(
        self,
        page: PageElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[
        ScraperYield[NCAppealsDocket | NCAppealsDocument], None, None
    ]:
        """Parse the rich docket-sheet HTML into ``NCAppealsDocket``,
        then fan out to the per-case filings page so the e-filed
        documents are also harvested as ``NCAppealsDocument`` rows."""
        case_name = (
            _extract_long_title(page)
            or accumulated_data.get("case_name_hint")
            or accumulated_data["docket_number"]
        )

        # SC dockets show only ``Docket Date``; COA shows both, with
        # the same value. Fall back to ``Docket Date`` when the more
        # specific label isn't on the page.
        date_filed = _parse_date(
            _label_value(page, "File Date")
        ) or _parse_date(_label_value(page, "Docket Date"))

        docket = NCAppealsDocket(
            docket_id=accumulated_data["docket_number"],
            court_id=accumulated_data["court_id"],
            case_name=case_name,
            date_filed=date_filed,
            case_type=_label_value(page, "Case Type"),
            case_closed=_parse_yes_no(_label_value(page, "Case Closed")),
            case_close_date=_parse_date(_label_value(page, "Case Close Date")),
            mediation=_parse_yes_no(_label_value(page, "Mediation")),
            docket_date=_parse_date(_label_value(page, "Docket Date")),
            file_time=_label_value(page, "File Time"),
            acquire_date=_parse_date(_label_value(page, "Acquire Date")),
            bond_collection=_parse_yes_no(
                _label_value(page, "Bond Collection")
            ),
            docket_fee=_parse_yes_no(_label_value(page, "Docket Fee")),
            pauper=_parse_yes_no(_label_value(page, "Pauper")),
            print_deposit=_parse_yes_no(_label_value(page, "Print Deposit")),
            state_appeals=_parse_yes_no(_label_value(page, "State Appeals")),
            as_of_date=_parse_date(_label_value(page, "As of")),
            venue=_label_value(page, "Venue"),
            heard_in=_label_value(page, "Heard In"),
            previous_venue=_label_value(page, "Previous Venue"),
            to_sc=_label_value(page, "To SC"),
            from_sc=_label_value(page, "From SC"),
            lower_courts=_extract_lower_courts(page),
            parties=_extract_parties_with_attorneys(page, response.text or ""),
            entries=_extract_docket_entries(page, response.text or ""),
            source_url=accumulated_data.get("source_url") or response.url,
        )
        yield ParsedData(data=docket)

        # Fan out to the per-case filings page to harvest documents.
        yield Request(
            request=HTTPRequestParams(
                method=HttpMethod.GET,
                url=SEARCH_RESULTS_URL,
                params={
                    "sDocketSearch": docket.docket_id,
                    "exact": "1",
                    "iStart": "0",
                },
            ),
            continuation=self.parse_case_filings,
            accumulated_data={
                "docket_number": docket.docket_id,
                "court_id": docket.court_id,
            },
            deduplication_key=f"filings:{docket.docket_id}",
        )

    @step()
    def parse_case_filings(
        self,
        page: PageElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[NCAppealsDocument], None, None]:
        """Walk one page of a case's e-filings list.

        Each filing is rendered as ``<a>{Type} ( {subtype} )</a> -
        Filed By: {filer} {YYYY-MM-DD}`` inside a
        ``div.docket-{id}.border-top`` block. Sealed filings drop the
        ``<a>`` and add a ``(Sealed)`` marker; we still emit those as
        ``NCAppealsDocument`` rows so downstream joins see the slot.
        """
        docket_number = accumulated_data["docket_number"]
        court_id = accumulated_data["court_id"]

        filing_blocks = page.query_xpath(
            "//div["
            "contains(@class, 'docket-')"
            " and contains(@class, 'border-top')"
            " and contains(@class, 'pt-2')"
            "]",
            "filing blocks",
            min_count=0,
        )
        for block in filing_blocks:
            doc = _parse_filing_block(block, docket_number, court_id)
            if doc is None:
                continue
            if doc.document_url:
                # Yield the archive request — the download handler
                # will emit the final ParsedData with the local path.
                yield Request(
                    archive=True,
                    request=HTTPRequestParams(
                        method=HttpMethod.GET, url=doc.document_url
                    ),
                    continuation=self.handle_document_download,
                    expected_type="pdf",
                    accumulated_data={
                        "document": doc.model_dump(mode="json"),
                    },
                    deduplication_key=(
                        f"doc:{doc.document_id}" if doc.document_id else None
                    ),
                )
            else:
                # Sealed filing — no PDF to fetch, but still record it.
                yield ParsedData(data=doc)

        # Pagination — the per-case page uses the same ``iStart``
        # selector as the date-listing page. Most cases have well
        # under 50 filings, so this branch rarely fires.
        current_offset = _current_istart(response.url)
        for offset in _pagination_offsets(page):
            if offset <= current_offset:
                continue
            yield Request(
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url=SEARCH_RESULTS_URL,
                    params={
                        "sDocketSearch": docket_number,
                        "exact": "1",
                        "iStart": str(offset),
                    },
                ),
                continuation=self.parse_case_filings,
                accumulated_data=accumulated_data,
                deduplication_key=SkipDeduplicationCheck(),
            )

    @step()
    def handle_document_download(
        self,
        accumulated_data: dict,
        local_filepath: str | None = None,
    ) -> Generator[ScraperYield[NCAppealsDocument], None, None]:
        """Emit an ``NCAppealsDocument`` once the PDF has been
        archived."""
        payload = dict(accumulated_data["document"])
        payload["local_path"] = local_filepath
        yield ParsedData(data=NCAppealsDocument.model_validate(payload))


# =============================================================================
# Module-level parsing helpers
# =============================================================================


def _normalize_url(url: str) -> str:
    """The site sometimes emits ``http://`` for cross-host links."""
    if url.startswith("http://appellate.nccourts.org"):
        return "https://" + url[len("http://") :]
    return url


def _court_from_sheet_url(url: str) -> str:
    """Pull ``court=1|2`` from a docket-sheet URL."""
    match = re.search(r"[?&]court=(\d+)", url)
    if match and match.group(1) == "1":
        return COURT_SC
    return COURT_COA


def _current_istart(url: str | None) -> int:
    if not url:
        return 0
    match = re.search(r"[?&]iStart=(\d+)", url)
    return int(match.group(1)) if match else 0


def _pagination_offsets(page: PageElement) -> list[int]:
    """Pull every ``iStart=N`` value from the page-select dropdown."""
    options = page.query_xpath_strings(
        "//select[@id='pageSelect']/option/@value",
        "page-select options",
        min_count=0,
    )
    offsets: set[int] = set()
    for value in options:
        match = re.search(r"[?&]iStart=(\d+)", value)
        if match:
            offsets.add(int(match.group(1)))
    return sorted(offsets)


def _label_value(page: PageElement, label: str) -> str | None:
    """Return the value cell after a ``<td><b|strong>{label}:</b|strong></td>``.

    The docket sheet alternates label / value cells inside
    ``<table>`` rows. The label might be wrapped in ``<b>`` or in
    ``<strong>``, so we match ``*`` (any element) whose normalised text
    is exactly ``{label}:``.
    """
    xpath = (
        f"//td[*[normalize-space(text())='{label}:']]/following-sibling::td[1]"
    )
    cells = page.query_xpath(xpath, f"label:{label}", min_count=0, max_count=1)
    if not cells:
        return None
    return _clean(cells[0].text_content())


def _extract_long_title(page: PageElement) -> str | None:
    """Pull the case caption from ``<div class='long_title'>``."""
    parts = page.query_xpath_strings(
        "//div[contains(@class, 'long_title')]//text()",
        "long title",
        min_count=0,
    )
    if not parts:
        return None
    # Replace internal blank lines with " v. " spacing collapsed.
    joined = " ".join(p.strip() for p in parts if p.strip())
    return _clean(joined)


def _extract_lower_courts(page: PageElement) -> list[NCAppealsLowerCourt]:
    """Pull the Lower Court Number(s) block(s).

    The block uses the same ``<td><b>{label}:</b></td><td>{value}</td>``
    pattern. Most cases have exactly one such block; a few have
    several (one per origin court).
    """
    out: list[NCAppealsLowerCourt] = []
    # Each block lives inside a table that follows a
    # ``<div class='section_tab'>Lower Court Number(s)</div>``.
    tables = page.query_xpath(
        "//div[contains(@class, 'section_tab')"
        " and contains(., 'Lower Court Number')]"
        "/following-sibling::table[1]",
        "lower court tables",
        min_count=0,
        max_count=1,
    )
    for table in tables:
        # The fields are repeated inside the table; collect them in
        # order and split into per-block records by every appearance
        # of "Location:".
        rows = table.query_xpath(".//tr[td]", "lower-court rows", min_count=0)
        current: dict[str, str] = {}
        for row in rows:
            cell_elements = row.query_xpath(
                "./td", "lower-court cells", min_count=0
            )
            cells = [_clean(c.text_content()) or "" for c in cell_elements]
            if len(cells) < 2:
                continue
            label = (cells[0] or "").rstrip(":")
            value = cells[1]
            if label.lower() == "location":
                if current:
                    out.append(_build_lower_court(current))
                current = {"location": value or ""}
            elif label.lower() == "judge":
                current["judge"] = value or ""
            elif label.lower() in {"case", "case #"}:
                current["case_number"] = value or ""
        if current:
            out.append(_build_lower_court(current))
    return out


def _build_lower_court(d: dict[str, str]) -> NCAppealsLowerCourt:
    return NCAppealsLowerCourt(
        location=d.get("location") or None,
        judge=d.get("judge") or None,
        case_number=d.get("case_number") or None,
    )


def _extract_parties_with_attorneys(
    page: PageElement, raw_html: str = ""
) -> list[NCAppealsParty]:
    """Pull the Parties table and zip it with the Attorneys section.

    Parties are read from the structured table; their attorneys are
    parsed best-effort from the free-text Attorneys section. The
    section is malformed HTML (stray ``</strong></b>`` after the first
    party), so we operate on the raw HTML slice between the
    ``<div … >Attorneys</div>`` heading and the closing ``</main>``
    rather than walking the lxml tree.
    """
    party_names_elems = page.query_xpath(
        "//td[@headers='party_name_id']",
        "party names",
        min_count=0,
    )
    party_roles_elems = page.query_xpath(
        "//td[@headers='role_id']",
        "party roles",
        min_count=0,
    )
    raw_pairs: list[tuple[str, str]] = []
    for name_el, role_el in zip(party_names_elems, party_roles_elems):
        name = _clean(name_el.text_content())
        role = _clean(role_el.text_content())
        if name:
            raw_pairs.append((name, role or ""))

    attorneys_by_party = _extract_attorney_blocks_from_html(raw_html)

    parties: list[NCAppealsParty] = []
    for name, role in raw_pairs:
        parties.append(
            NCAppealsParty(
                name=name,
                role=role or None,
                attorneys=attorneys_by_party.get(name, []),
            )
        )
    return parties


def _extract_attorney_blocks_from_html(
    raw_html: str,
) -> dict[str, list[NCAppealsAttorney]]:
    """Best-effort attorney parser keyed on the trailing party name.

    Slices the raw HTML between the ``Attorneys`` section heading and
    the closing ``</main>``, then splits on ``Attorney for {role} -
    {party}`` markers. The shared firm / address / phone block at the
    end of each party's section is copied onto every attorney in that
    block.
    """
    out: dict[str, list[NCAppealsAttorney]] = {}
    if not raw_html:
        return out
    section_match = re.search(
        r"<div[^>]*class='section_tab'[^>]*>\s*Attorneys\s*</div>"
        r"(.*?)</main>",
        raw_html,
        re.DOTALL | re.IGNORECASE,
    )
    if not section_match:
        return out
    section_text = section_match.group(1)
    # Split on the per-party heading. The site sometimes typos the
    # closing tag (``</stong>`` instead of ``</strong>``); we accept
    # either.
    party_chunks = re.split(
        r"<strong>\s*Attorney for ([^<]+)</(?:strong|stong)>",
        section_text,
    )
    # re.split with a capture group emits: [pre, group1, body1, group2, body2, ...]
    for i in range(1, len(party_chunks), 2):
        heading = party_chunks[i]
        body_html = party_chunks[i + 1] if i + 1 < len(party_chunks) else ""
        # Heading shape: ``{role} - {party_name}``
        _, _, party_name = heading.partition(" - ")
        party_name = _clean(party_name) or _clean(heading) or ""
        if not party_name:
            continue
        body_text = _strip_tags(_BR_RE.sub("\n", body_html))
        lines = [
            line.strip() for line in body_text.split("\n") if line.strip()
        ]
        attorneys = _parse_attorney_lines(lines)
        if attorneys:
            out.setdefault(party_name, []).extend(attorneys)
    return out


def _parse_attorney_lines(lines: list[str]) -> list[NCAppealsAttorney]:
    """Walk one party's attorney block.

    Heuristics: any line that starts with an honorific
    (``Mr.``, ``Ms.``, ``Mrs.``, ``Mx.``, ``Dr.``) starts a new
    attorney; the next line is the title; subsequent lines are the
    shared firm / address / phone block applied retroactively to all
    attorneys parsed from this block.
    """
    HONORIFICS = ("Mr.", "Ms.", "Mrs.", "Mx.", "Dr.", "Hon.")
    attorneys: list[NCAppealsAttorney] = []
    shared_lines: list[str] = []
    pending: NCAppealsAttorney | None = None
    expecting_title = False

    def _commit_pending() -> None:
        nonlocal pending, expecting_title
        if pending is not None:
            attorneys.append(pending)
            pending = None
            expecting_title = False

    for raw in lines:
        line = raw.strip()
        # Cloudflare's email placeholder appears as ``[email protected]``
        # after &nbsp; / &#160; have been collapsed to spaces; skip it.
        if not line or line.lower() == "[email protected]":
            continue
        if line.startswith(HONORIFICS):
            _commit_pending()
            name = line
            role = None
            if "[" in line and "]" in line:
                name, _, bracket = line.partition("[")
                role = bracket.rstrip("]").strip() or None
            pending = NCAppealsAttorney(name=_clean(name) or line, role=role)
            expecting_title = True
            continue
        if pending is not None and expecting_title:
            pending.title = line
            expecting_title = False
            continue
        # Anything after the title belongs to the shared firm block.
        # ``pending`` may still hold the most recent attorney; we'll
        # commit it once the block ends.
        shared_lines.append(line)

    _commit_pending()

    # Distribute the shared firm/address/phone block.
    if shared_lines and attorneys:
        firm = shared_lines[0]
        phone: str | None = None
        address_lines = shared_lines[1:]
        if address_lines and re.match(
            r"^\(?\d{3}\)?\s*\d{3}\s*[-]?\s*\d{4}", address_lines[-1]
        ):
            phone = address_lines.pop().strip()
        address = ", ".join(address_lines) if address_lines else None
        for atty in attorneys:
            atty.firm = firm
            atty.address = address
            atty.phone = phone
    return attorneys


def _extract_docket_entries(
    page: PageElement, raw_html: str
) -> list[NCAppealsDocketEntry]:
    """Pull the Documents table rows and merge in the free-text
    expansion (filed_at / filed_for / filed_by / order_text)."""
    rows = page.query_xpath(
        "//table[@aria-labelledby='document_tab']//tr[td]",
        "document table rows",
        min_count=0,
    )
    entries: list[NCAppealsDocketEntry] = []
    for row in rows:
        cell_elements = row.query_xpath("./td", "document cells", min_count=0)
        cells = [_clean(c.text_content()) or "" for c in cell_elements]
        if len(cells) < 9:
            continue
        first = cells[0] or ""
        match = re.match(r"\((\d+)\)\s*(.+)$", first)
        if not match:
            continue
        idx = int(match.group(1))
        doc_type = _clean(match.group(2)) or ""
        entries.append(
            NCAppealsDocketEntry(
                number=idx,
                document_type=doc_type,
                date_received=_parse_date(cells[1]),
                cert_of_service=_parse_date(cells[2]),
                rec_brf_due=cells[3] or None,
                response_due=cells[4] or None,
                response_received=_parse_date(cells[5]),
                mailed_out=_parse_date(cells[6]),
                ruling=cells[7] or None,
                ruling_date=_parse_date(cells[8]),
            )
        )
    if not entries:
        return entries

    # Merge in the free-text expansion: the chunk between the Documents
    # table and the next ``<div … class='section_tab'>`` heading. We
    # parse this off the raw HTML rather than the lxml tree because
    # the structure is just hr-separated text, not a real container.
    expansions = _extract_entry_expansions(raw_html)
    for entry_obj in entries:
        details = expansions.get(entry_obj.number)
        if not details:
            continue
        entry_obj.filed_at = details.get("filed_at")
        entry_obj.filed_for = details.get("filed_for")
        entry_obj.filed_by = details.get("filed_by")
        entry_obj.order_text = details.get("order_text")
    return entries


def _extract_entry_expansions(raw_html: str) -> dict[int, dict[str, str]]:
    """Grab the free-text register-of-actions expansion blocks.

    The block sits between the Documents table close-tag and the next
    ``<div … class='section_tab'>`` heading. Each entry is delimited
    by ``<br><hr>`` and starts with ``N - TYPE  (Ruling) - RulingDate``.
    """
    # The expansion sits after the Documents table's ``</table>`` and
    # ends at the next ``section_tab`` heading. The exact whitespace /
    # ``<br>`` count between the close-tag and the first ``<hr>``
    # varies by case, so we anchor on the table close and the next
    # section heading and let the body soak up everything in between.
    end_re = re.search(
        r"</table>\s*(?:<\s*br\s*/?\s*>\s*)*<\s*hr\s*/?\s*>"
        r"(.*?)<div[^>]*class='section_tab'",
        raw_html,
        re.DOTALL | re.IGNORECASE,
    )
    if not end_re:
        return {}
    chunk = end_re.group(1)
    raw_blocks = re.split(r"<\s*hr\s*/?\s*>", chunk, flags=re.IGNORECASE)
    out: dict[int, dict[str, str]] = {}
    for raw_block in raw_blocks:
        if not raw_block.strip():
            continue
        # Pull the order text before stripping HTML (so we keep the
        # blockquote whitespace).
        order_match = re.search(
            r"<blockquote[^>]*>(.*?)</blockquote>",
            raw_block,
            re.DOTALL | re.IGNORECASE,
        )
        order_text = (
            _clean(_strip_tags(order_match.group(1))) if order_match else None
        )

        body_html = (
            raw_block[: order_match.start()] if order_match else raw_block
        )
        plain = _strip_tags(_BR_RE.sub("\n", body_html))
        lines = [
            stripped
            for stripped in (line.strip() for line in plain.split("\n"))
            if stripped
        ]
        if not lines:
            continue
        header = _ENTRY_HEADER_RE.match(lines[0])
        if not header:
            continue
        idx = int(header.group("idx"))
        details: dict[str, str] = {}
        for line in lines[1:]:
            if line.lower().startswith("filed:"):
                details["filed_at"] = _clean(line[len("filed:") :]) or ""
            elif line.lower().startswith("for:"):
                details["filed_for"] = _clean(line[len("for:") :]) or ""
            elif line.lower().startswith("by"):
                # e.g. ``BY   : Ms. Callie S. Thomas``
                _, _, after = line.partition(":")
                details["filed_by"] = _clean(after) or ""
        if order_text:
            details["order_text"] = order_text
        out[idx] = details
    return out


_FILING_TEXT_RE = re.compile(
    r"^(?P<rest>.*?)\s*-\s*Filed By:\s*(?P<filer>.+?)\s+"
    r"(?P<date>\d{4}-\d{2}-\d{2})\s*$",
    re.DOTALL,
)
_DOC_ID_RE = re.compile(r"document_id=(\d+)")


def _split_type_subtype(text: str) -> tuple[str, str | None]:
    """Split ``Type ( subtype )`` allowing nested parens in the subtype.

    The site renders sub-type text like ``record (printed)``, so we
    can't rely on a non-greedy ``[^)]*`` match. Instead, slice on the
    *first* ``(`` and the *last* ``)`` — the outer pair always frames
    the subtype, even when it contains its own parens.
    """
    if "(" not in text or not text.rstrip().endswith(")"):
        return text.strip(), None
    head, _, tail = text.partition("(")
    inner = tail.rstrip()[:-1]  # drop trailing ')'
    return head.strip(), _clean(inner) or None


def _parse_filing_block(
    block: PageElement, docket_number: str, court_id: str
) -> NCAppealsDocument | None:
    """Extract one filing's metadata + URL from its container div.

    Returns None for blocks that don't represent a filing (e.g. the
    case-header row that opens each per-case page, or empty
    spacers).
    """
    # Combined text content drives type / filer / date parsing. A
    # trailing ``(Sealed)`` marker is split off before the regex runs;
    # we record it as a flag rather than letting it fall into the
    # date-anchored regex.
    body = _clean(block.text_content()) or ""
    is_sealed = False
    if body.endswith("(Sealed)"):
        is_sealed = True
        body = body[: -len("(Sealed)")].strip()

    match = _FILING_TEXT_RE.match(body)
    if not match:
        return None
    type_subtype = _clean(match.group("rest")) or ""
    document_type, subtype = _split_type_subtype(type_subtype)
    filer = _clean(match.group("filer"))
    try:
        filed = datetime.strptime(match.group("date"), "%Y-%m-%d").date()
    except ValueError:
        filed = None

    href_values = block.query_xpath_strings(
        ".//a[contains(@href, 'show-file.php')]/@href",
        "show-file href",
        min_count=0,
        max_count=1,
    )

    document_url: str | None = None
    document_id: str | None = None
    if href_values:
        document_url = _normalize_url(href_values[0])
        id_match = _DOC_ID_RE.search(document_url)
        if id_match:
            document_id = id_match.group(1)

    return NCAppealsDocument(
        docket_id=docket_number,
        court_id=court_id,
        document_type=document_type,
        document_subtype=subtype,
        filer=filer,
        date_filed=filed,
        is_sealed=is_sealed,
        document_id=document_id,
        document_url=document_url,
    )


def _strip_tags(html: str) -> str:
    """Strip the small set of inline tags the docket sheet uses."""
    text = re.sub(r"<[^>]+>", "", html)
    text = text.replace("&nbsp;", " ").replace("&#160;", " ")
    text = text.replace("&amp;", "&")
    text = text.replace("&lt;", "<").replace("&gt;", ">")
    return text
