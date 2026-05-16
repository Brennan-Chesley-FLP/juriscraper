"""Tennessee Public Case History scraper.

Scrapes appellate dockets for the Tennessee Supreme Court, Court of Appeals,
and Court of Criminal Appeals from https://pch.tncourts.gov.

The site is an ASP.NET WebForms case-management system (C-Track) and exposes
a single sequence-number search that returns rows from all three courts at
once. We speculate over the 5-digit sequence segment of the case number and
infer the court from the case-number suffix.

Flow:

1. ``fetch_case_by_sequence`` (entry, SpeculativeRange)
       → GET ``SearchResults.aspx?k=<seq>&Number=True``
2. ``parse_search_results``
       → for each ``redirectToCase('<id>', ...)`` row, request the case
         detail page; if a "Next" button is shown, postback to fetch the
         next results page
3. ``parse_case_detail``
       → parse case header, overview, milestones, parties, history, record
       → for each docket-history row that has an attached PDF, postback
         the same page with ``__EVENTTARGET`` set to the row's LinkButton
         path (``archive=True``); yield the assembled ``TnDocket``
4. ``handle_document_download``
       → emit a ``TnDocument`` record with ``local_path``
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import TYPE_CHECKING, ClassVar

from jkent.common.decorators import entry, step
from jkent.common.page_element import PageElement
from jkent.common.param_models import SpeculativeRange
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
    TnDocket,
    TnDocketEntry,
    TnDocument,
    TnMilestone,
    TnParty,
    TnRecordEntry,
)

if TYPE_CHECKING:
    from collections.abc import Generator

    from jkent.data_types import ScraperYield


BASE_URL = "https://pch.tncourts.gov"
INDEX_URL = f"{BASE_URL}/index.aspx"
SEARCH_RESULTS_URL = f"{BASE_URL}/SearchResults.aspx"
CASE_DETAILS_URL = f"{BASE_URL}/CaseDetails.aspx"

SUFFIX_TO_COURT_ID: dict[str, str] = {
    "SC": "tenn",
    "COA": "tennctapp",
    "CCA": "tenncrimapp",
}

CASE_NUMBER_RE = re.compile(
    r"^[EMW]\d{4}-\d{5}-(SC|COA|CCA)-",
    re.IGNORECASE,
)
REDIRECT_TO_CASE_RE = re.compile(
    r"redirectToCase\('(\d+)',\s*'([^']+)',\s*'([^']+)'\)"
)
POSTBACK_TARGET_RE = re.compile(r"__doPostBack\('([^']+)'")


class TennesseePublicCaseHistoryScraper(BaseScraper[TnDocket | TnDocument]):
    """Scraper for the Tennessee appellate Public Case History portal.

    Covers all three Tennessee appellate courts (Supreme, Court of Appeals,
    Court of Criminal Appeals) via a single speculative entry on the
    5-digit sequence portion of the case number.
    """

    court_ids: ClassVar[set[str]] = {"tenn", "tennctapp", "tenncrimapp"}
    court_url: ClassVar[str] = BASE_URL
    data_types: ClassVar[set[str]] = {"dockets"}
    status: ClassVar[ScraperStatus] = ScraperStatus.IN_DEVELOPMENT
    version: ClassVar[str] = "2026-05-05"
    requires_auth: ClassVar[bool] = False
    rate_limits: ClassVar[list[Rate] | None] = [Rate(2, Duration.SECOND)]

    # =========================================================================
    # Helpers
    # =========================================================================

    @staticmethod
    def _parse_date(text: str | None) -> date | None:
        if not text:
            return None
        text = text.strip()
        if not text:
            return None
        try:
            return datetime.strptime(text, "%m/%d/%Y").date()
        except ValueError:
            return None

    @staticmethod
    def _safe_text(element: PageElement) -> str:
        try:
            return element.text_content().strip()
        except Exception:
            return ""

    @staticmethod
    def _court_id_from_case_number(case_number: str) -> str | None:
        match = CASE_NUMBER_RE.match(case_number)
        if not match:
            return None
        return SUFFIX_TO_COURT_ID.get(match.group(1).upper())

    @staticmethod
    def _build_postback_data(page: PageElement) -> dict[str, str]:
        """Collect ASP.NET WebForms hidden state for a postback POST.

        Returns the fields needed to issue an authentic ``__doPostBack``
        request: ``__VIEWSTATE``, ``__VIEWSTATEGENERATOR``,
        ``__EVENTVALIDATION``, the hidden state fields (``hdMastId``,
        ``hdPDF``, ``hdOpen``), the search-toolbar inputs that the page
        ships with (``txtSearch``, ``SearchTerm``), but **not** the
        submit buttons (``btnAdvanceSearch``, ``btnSearch``, paginators)
        — IIS treats *any* submit-button name in the body as the
        clicked button and short-circuits ``__EVENTTARGET`` if one is
        present, even with an empty value, redirecting the request back
        to ``/SearchResults.aspx``.
        """
        data: dict[str, str] = {}
        hidden_fields = page.query_xpath(
            "//form[@id='form1']//input[@type='hidden']",
            "hidden form fields",
            min_count=0,
        )
        for el in hidden_fields:
            name = el.get_attribute("name")
            if not name:
                continue
            data[name] = el.get_attribute("value") or ""
        # The visible search textbox.
        search_box = page.query_xpath(
            "//form[@id='form1']//input[@id='txtSearch']",
            "search textbox",
            min_count=0,
            max_count=1,
        )
        if search_box:
            data["txtSearch"] = search_box[0].get_attribute("value") or ""
        # The checked SearchTerm radio (if any).
        radios = page.query_xpath(
            "//form[@id='form1']//input[@type='radio'][@name='SearchTerm']"
            "[@checked]",
            "checked SearchTerm radio",
            min_count=0,
            max_count=1,
        )
        if radios:
            data["SearchTerm"] = radios[0].get_attribute("value") or ""
        return data

    # =========================================================================
    # Entry point
    # =========================================================================

    @entry(TnDocket)
    def fetch_case_by_sequence(self, rid: SpeculativeRange) -> Request:
        """Speculative search by 5-digit sequence number.

        A single search hits all three courts and all years simultaneously.
        Sequences in the wild range from 1 to roughly 3000 per year-court
        combination. Recommended seed: ``{"number": 1, "gap": 50}``.
        """
        sequence = f"{rid.min:05d}"
        url = f"{SEARCH_RESULTS_URL}?k={sequence}&Number=True"
        return Request(
            request=HTTPRequestParams(
                method=HttpMethod.GET,
                url=url,
                headers={
                    "Accept": "text/html",
                    "Referer": INDEX_URL,
                },
            ),
            continuation=self.parse_search_results,
            accumulated_data={"sequence": sequence, "page_number": 1},
            deduplication_key=f"seq:{sequence}",
        )

    # =========================================================================
    # Soft-404 detection
    # =========================================================================

    def fails_successfully(self, response: Response) -> bool:
        """Detect empty / no-result searches as speculative misses.

        Empty searches respond with HTTP 302 → ``/Index.aspx?count=0``.
        Without ``FOLLOW_REDIRECTS``, the persistent driver surfaces the
        302 itself; non-2xx already counts as a miss via
        ``SpeculationHTTPFailure``. We additionally guard against a 200
        with no result rows in case the server's behavior changes.
        """
        if "/SearchResults.aspx" in response.url:
            return "redirectToCase(" in response.text
        return True

    # =========================================================================
    # Step 1: Parse search results
    # =========================================================================

    @step(priority=8)
    def parse_search_results(
        self,
        page: PageElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[TnDocket], None, None]:
        """Parse a SearchResults.aspx page and follow each row.

        Each result row is a ``<tr onclick="redirectToCase('<id>', 'Number',
        'False');">`` containing two cells (case number, style). We
        enqueue a CaseDetails request per row, deduped by the C-Track
        internal id (multiple sequence searches may surface the same
        case).
        """
        sequence = accumulated_data["sequence"]
        rows = page.query_xpath(
            "//table[@id='grdSearchResult']"
            "//tr[contains(@onclick, 'redirectToCase')]",
            "result rows",
            min_count=0,
        )

        for row in rows:
            onclick = row.get_attribute("onclick") or ""
            match = REDIRECT_TO_CASE_RE.search(onclick)
            if not match:
                continue
            mast_id, search_type, _ = match.groups()

            cells = row.query_xpath(".//td", "result cells", min_count=0)
            if len(cells) < 2:
                continue
            case_number = self._safe_text(cells[0])
            case_name = self._safe_text(cells[1])

            court_id = self._court_id_from_case_number(case_number)
            if court_id is None:
                # Skip rows we don't recognize (unknown court suffix)
                continue

            detail_url = f"{CASE_DETAILS_URL}?id={mast_id}&{search_type}=True"

            yield Request(
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url=detail_url,
                    headers={
                        "Accept": "text/html",
                        "Referer": response.url,
                    },
                ),
                continuation=self.parse_case_detail,
                accumulated_data={
                    "mast_id": mast_id,
                    "case_number": case_number,
                    "case_name": case_name,
                    "court_id": court_id,
                    "sequence": sequence,
                },
                deduplication_key=f"detail:{mast_id}",
            )

        # Pagination: if a "Next" button is present and not disabled,
        # postback to fetch the next results page.
        next_buttons = page.query_xpath(
            "//input[@name='next1' and not(@disabled)]",
            "next button",
            min_count=0,
            max_count=1,
        )
        if next_buttons:
            current_page = accumulated_data.get("page_number", 1)
            next_accum = dict(accumulated_data)
            next_accum["page_number"] = current_page + 1
            # ``_build_postback_data`` harvests the hidden state
            # (``CurrentPages``, ``TotalPages``, ``TotalRecords``,
            # ``searchText``, ``searchType``, ``MobileDevice``) from
            # the rendered page; we only inject the postback target
            # plus the ``next1=Next`` "click" trigger.
            postback_data = self._build_postback_data(page)
            postback_data.update(
                {
                    "__EVENTTARGET": "btnAdvanceSearch",
                    "__EVENTARGUMENT": "",
                    "next1": "Next",
                }
            )
            yield Request(
                request=HTTPRequestParams(
                    method=HttpMethod.POST,
                    url=response.url,
                    data=postback_data,
                    headers={"Referer": INDEX_URL},
                ),
                continuation=self.parse_search_results,
                accumulated_data=next_accum,
                deduplication_key=SkipDeduplicationCheck(),
            )

    # =========================================================================
    # Step 2: Parse case detail
    # =========================================================================

    @step(priority=6)
    def parse_case_detail(
        self,
        page: PageElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[TnDocket | TnDocument], None, None]:
        """Parse the full case-detail page and yield the docket.

        Sections (each anchored by an ``<h3>``): Case Overview,
        Case Milestones, Parties, Case History (the docket), Record
        Information. PDFs attached to docket-history rows are downloaded
        as ``archive=True`` postback requests.
        """
        case_number = accumulated_data["case_number"]
        case_name = accumulated_data["case_name"]
        court_id = accumulated_data["court_id"]
        mast_id = accumulated_data["mast_id"]

        # Some result rows have an empty case-name cell; fall back to the
        # detail page's <h1>.
        if not case_name:
            title_els = page.query_xpath(
                "//h1[@class='case-title']",
                "case title",
                min_count=0,
                max_count=1,
            )
            if title_els:
                case_name = self._safe_text(title_els[0])

        docket = TnDocket(
            case_number=case_number,
            court_id=court_id,
            case_name=case_name or case_number,
            internal_case_id=mast_id,
            source_url=response.url,
        )

        # --- Case Overview ---
        # The page nests sub-sections inside ``<div id="case-overview">``,
        # so the actual one-row overview table lives in
        # ``<div id="case-overview2">``.
        overview_rows = page.query_xpath(
            "//div[@id='case-overview2']//tr[td]",
            "overview rows",
            min_count=0,
        )
        for row in overview_rows:
            cells = row.query_xpath(".//td", "overview cells", min_count=0)
            if len(cells) >= 5:
                docket.intermediate_case_number = (
                    self._safe_text(cells[0]) or None
                )
                # cells[1] is the style — already on docket.case_name
                docket.trial_court = self._safe_text(cells[2]) or None
                docket.trial_court_judge = self._safe_text(cells[3]) or None
                docket.trial_court_number = self._safe_text(cells[4]) or None
                break

        # --- Case Milestones ---
        milestone_rows = page.query_xpath(
            "//table[@id='milestones']//tr[td]",
            "milestone rows",
            min_count=0,
        )
        for row in milestone_rows:
            cells = row.query_xpath(".//td", "milestone cells", min_count=0)
            if len(cells) < 2:
                continue
            description = self._safe_text(cells[0])
            milestone_date = self._parse_date(self._safe_text(cells[1]))
            if not description:
                continue
            docket.milestones.append(
                TnMilestone(
                    description=description, milestone_date=milestone_date
                )
            )
            label = description.lower()
            if label == "application filed" and milestone_date:
                docket.date_filed = milestone_date
            elif label == "record filed" and milestone_date:
                # Use record-filed as date_filed if no application-filed date
                docket.date_filed = docket.date_filed or milestone_date
            elif label == "closed date" and milestone_date:
                docket.date_closed = milestone_date
            elif label == "decision date" and milestone_date:
                docket.decision_date = milestone_date
            elif label == "decision type":
                docket.decision_type = self._safe_text(cells[1]) or None
            elif label == "disposition":
                docket.disposition = self._safe_text(cells[1]) or None
            elif label == "panel":
                docket.panel = self._safe_text(cells[1]) or None

        # --- Parties ---
        party_rows = page.query_xpath(
            "//div[@id='case-parties']//tr[td]",
            "party rows",
            min_count=0,
        )
        for row in party_rows:
            cells = row.query_xpath(".//td", "party cells", min_count=0)
            if len(cells) < 3:
                continue
            name = self._safe_text(cells[0])
            if not name:
                continue
            docket.parties.append(
                TnParty(
                    name=name,
                    role=self._safe_text(cells[1]) or None,
                    counsel=self._safe_text(cells[2]) or None,
                )
            )

        # --- Case History (docket entries) ---
        history_rows = page.query_xpath(
            "//div[@id='case-history']//tr[td]",
            "history rows",
            min_count=0,
        )
        pdf_postbacks: list[tuple[int, str, str]] = []
        for _idx, row in enumerate(history_rows):
            cells = row.query_xpath(".//td", "history cells", min_count=0)
            if len(cells) < 4:
                continue
            entry_date = self._parse_date(self._safe_text(cells[0]))
            event = self._safe_text(cells[1])
            filer = self._safe_text(cells[2]) or None

            # PDF cell — extract the __doPostBack target if present
            postback_target: str | None = None
            pdf_links = cells[3].query_xpath(".//a", "pdf links", min_count=0)
            if pdf_links:
                href = pdf_links[0].get_attribute("href") or ""
                pb_match = POSTBACK_TARGET_RE.search(href)
                if pb_match:
                    postback_target = pb_match.group(1)

            entry = TnDocketEntry(
                date_filed=entry_date,
                event=event or "(no event)",
                filer=filer,
                document_url=postback_target,
            )
            docket.entries.append(entry)
            if postback_target:
                pdf_postbacks.append(
                    (len(docket.entries) - 1, postback_target, event)
                )

        # --- Record Information ---
        record_rows = page.query_xpath(
            "//div[@id='record-information']//tr[td]",
            "record rows",
            min_count=0,
        )
        for row in record_rows:
            cells = row.query_xpath(".//td", "record cells", min_count=0)
            if len(cells) < 3:
                continue
            volume_type = self._safe_text(cells[0])
            if not volume_type:
                continue
            docket.record_info.append(
                TnRecordEntry(
                    volume_type=volume_type,
                    volumes=self._safe_text(cells[1]) or None,
                    record_type=self._safe_text(cells[2]) or None,
                )
            )

        # --- Yield the docket first, then queue PDF downloads ---
        yield ParsedData(data=docket)

        if pdf_postbacks:
            postback_data = self._build_postback_data(page)
            for entry_index, postback_target, event in pdf_postbacks:
                request_data = {
                    **postback_data,
                    "__EVENTTARGET": postback_target,
                    "__EVENTARGUMENT": "",
                }
                yield Request(
                    request=HTTPRequestParams(
                        method=HttpMethod.POST,
                        url=response.url,
                        data=request_data,
                    ),
                    continuation=self.handle_document_download,
                    accumulated_data={
                        "case_number": case_number,
                        "court_id": court_id,
                        "event_index": entry_index,
                        "event": event,
                        "document_url": response.url,
                    },
                    archive=True,
                    expected_type="pdf",
                    deduplication_key=(f"pdf:{mast_id}:{postback_target}"),
                )

    # =========================================================================
    # Step 3: Document download handler
    # =========================================================================

    @step()
    def handle_document_download(
        self,
        local_filepath: str | None,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[TnDocument], None, None]:
        """Emit a TnDocument record for an archived PDF."""
        yield ParsedData(
            data=TnDocument(
                case_number=accumulated_data["case_number"],
                court_id=accumulated_data["court_id"],
                event_index=accumulated_data.get("event_index"),
                event=accumulated_data.get("event"),
                document_url=accumulated_data.get("document_url"),
                local_path=local_filepath,
            )
        )
