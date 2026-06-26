"""Tennessee Public Case History scraper.

Scrapes appellate dockets for the Tennessee Supreme Court, Court of Appeals,
and Court of Criminal Appeals from https://pch.tncourts.gov.

The site is an ASP.NET WebForms case-management system (a C-Track variant
addressed by ``SearchResults.aspx`` / ``CaseDetails.aspx`` with
``__doPostBack`` / ``__VIEWSTATE``, distinct from the Thomson Reuters
``.do``/``csIID`` C-Track in ``juriscraper.state.common.ctrack``). It exposes
a single sequence-number search that returns rows from all three courts at
once. We speculate over the 5-digit sequence segment of the docket number
and infer the court from the docket-number suffix.

Per-page HTML extraction lives in the ``parsers`` package
(``SearchResultsParser`` / ``CaseDetailParser``); the steps keep navigation
concerns (the search request, pagination postbacks, and the per-case
fan-out / PDF download postbacks).

Entry points (§4):
    - dockets_by_number(docket_number)  — speculative walk of the 5-digit
      sequence segment; a single search hits all three courts and all
      years at once, so this is a multi-court speculative entry and takes
      ONLY its ``SpeculativeRange`` (no ``court_ids`` argument; the driver
      seeds a speculative entry with just its speculative param).

Flow:
    dockets_by_number → parse_search_results
                          ├→ (per row)  parse_case_detail → ParsedData(TnDocket)
                          │                 └→ (per PDF) handle_document_download
                          └→ (next page) parse_search_results
"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from jkent.common.decorators import entry, step
from jkent.common.param_models import SpeculativeRange
from jkent.data_types import (
    BaseScraper,
    DriverRequirement,
    HttpMethod,
    HTTPRequestParams,
    ParsedData,
    Request,
    Response,
    ScraperStatus,
    SkipDeduplicationCheck,
    XPath,
)
from pyrate_limiter import Duration, Rate

from .models import (
    CASE_DETAILS_URL,
    INDEX_URL,
    SEARCH_RESULTS_URL,
    TnDocket,
    TnDocument,
)
from .parsers import CaseDetailParser, SearchResultsParser

if TYPE_CHECKING:
    from collections.abc import Generator

    from jkent.common.page_element import PageElement
    from jkent.data_types import ScraperYield


class TennesseePublicCaseHistoryScraper(BaseScraper[TnDocket | TnDocument]):
    """Scraper for the Tennessee appellate Public Case History portal.

    Covers all three Tennessee appellate courts (Supreme, Court of Appeals,
    Court of Criminal Appeals) via a single speculative entry on the
    5-digit sequence portion of the docket number. The court is derived
    from the docket-number suffix at parse time.
    """

    # === Metadata ===
    court_ids: ClassVar[set[str]] = {"tenn", "tennctapp", "tenncrimapp"}
    court_url: ClassVar[str] = INDEX_URL
    data_types: ClassVar[set[str]] = {"dockets"}
    status: ClassVar[ScraperStatus] = ScraperStatus.IN_DEVELOPMENT
    version: ClassVar[str] = "2026-06-27"
    last_verified: ClassVar[str] = "2026-05-05"
    requires_auth: ClassVar[bool] = False
    driver_requirements: ClassVar[list[DriverRequirement]] = []
    rate_limits: ClassVar[list[Rate] | None] = [Rate(2, Duration.SECOND)]

    # =========================================================================
    # Entry point (§4)
    # =========================================================================

    @entry(TnDocket)
    def dockets_by_number(self, docket_number: SpeculativeRange) -> Request:
        """Speculative search by the 5-digit sequence number.

        A single search hits all three courts and all years simultaneously,
        so this is a multi-court speculative entry: per §4 it takes ONLY
        its ``SpeculativeRange`` (no ``court_ids`` argument), and the court
        is derived from the docket-number suffix at parse time.

        Sequences in the wild range from 1 to roughly 5000 per
        year-court-division combination. Recommended seed:
        ``{"min": 1, "gap": 50}``.
        """
        sequence = f"{docket_number.min:05d}"
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
            deduplication_key=f"dockets_by_number:{sequence}",
        )

    # =========================================================================
    # Soft-404 detection (§10)
    # =========================================================================

    def actually_successful(self, response: Response) -> bool:
        """Detect empty / no-result searches as speculative misses.

        Empty searches respond with HTTP 302 → ``/Index.aspx?count=0``.
        Without ``FOLLOW_REDIRECTS``, the persistent driver surfaces the
        302 itself; non-2xx already counts as a miss. We additionally
        guard against a 200 with no result rows in case the server's
        behavior changes — a successful search page carries
        ``redirectToCase(`` row handlers.
        """
        if "/SearchResults.aspx" in response.url:
            return "redirectToCase(" in response.text
        return True

    # =========================================================================
    # Step 1: Parse search results
    # =========================================================================

    @step(priority=4)
    def parse_search_results(
        self,
        page: PageElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[TnDocket], None, None]:
        """Parse a SearchResults.aspx page and follow each row.

        ``SearchResultsParser`` extracts the row identity (docket_number,
        court, case_name, internal_case_id); this step issues a
        CaseDetails request per row (deduped by the C-Track internal id)
        and posts back for the next results page when one is present.
        """
        for partial in SearchResultsParser()(page):
            row = partial.raw_data
            mast_id = row["internal_case_id"]
            detail_url = f"{CASE_DETAILS_URL}?id={mast_id}&Number=True"

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
                    "internal_case_id": mast_id,
                    "docket_number": row["docket_number"],
                    "case_name": row["case_name"],
                    "court": row["court"],
                },
                deduplication_key=f"docket_detail:{mast_id}",
            )

        # Pagination: if a "Next" button is present and not disabled,
        # postback to fetch the next results page.
        next_buttons = page.query(
            XPath("//input[@name='next1' and not(@disabled)]"),
            "next button",
            min_count=0,
            max_count=1,
        )
        if next_buttons:
            current_page = accumulated_data.get("page_number", 1)
            next_accum = dict(accumulated_data)
            next_accum["page_number"] = current_page + 1
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

    @step(priority=2)
    def parse_case_detail(
        self,
        page: PageElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[TnDocket | TnDocument], None, None]:
        """Parse the full case-detail page and yield the docket.

        ``CaseDetailParser`` owns the page extraction; this step stamps
        the row-authoritative identity fields (``docket_number``,
        ``court``, ``internal_case_id``) plus provenance, then fans out a
        download postback per docket-history row that carries a PDF.
        """
        docket_number = accumulated_data["docket_number"]
        court = accumulated_data["court"]
        mast_id = accumulated_data["internal_case_id"]
        row_case_name = accumulated_data.get("case_name")

        raw = CaseDetailParser()(page)[0].raw_data
        raw["docket_number"] = docket_number
        raw["court"] = court
        raw["internal_case_id"] = mast_id
        # Prefer the result-row caption; fall back to the detail-page <h1>.
        raw["case_name"] = (
            row_case_name or raw.get("case_name") or (docket_number)
        )
        raw["source_url"] = response.url
        raw["source_entry_point"] = "dockets_by_number"

        # Collect PDF postback targets before yielding the docket.
        pdf_postbacks: list[tuple[int, str, str]] = []
        for idx, entry_obj in enumerate(raw.get("entries", [])):
            target = getattr(entry_obj, "postback_target", None)
            if target:
                pdf_postbacks.append((idx, target, entry_obj.event))

        yield ParsedData(TnDocket.raw(**raw))

        if pdf_postbacks:
            postback_data = self._build_postback_data(page)
            for entry_index, postback_target, event in pdf_postbacks:
                request_data = {
                    **postback_data,
                    "__EVENTTARGET": postback_target,
                    "__EVENTARGUMENT": "",
                }
                # Download dedup key feeds the archived filename — avoid
                # colons (§6); use the mast id + postback target.
                safe_target = postback_target.replace("$", "-")
                yield Request(
                    request=HTTPRequestParams(
                        method=HttpMethod.POST,
                        url=response.url,
                        data=request_data,
                    ),
                    continuation=self.handle_document_download,
                    accumulated_data={
                        "docket_number": docket_number,
                        "court": court,
                        "entry_index": entry_index,
                        "event": event,
                        "source_url": response.url,
                    },
                    archive=True,
                    expected_type="pdf",
                    deduplication_key=f"pdf-{mast_id}-{safe_target}",
                )

    # =========================================================================
    # Step 3: Document download handler (priority 1 via archive=True)
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
                docket_number=accumulated_data["docket_number"],
                court=accumulated_data["court"],
                entry_index=accumulated_data.get("entry_index"),
                description=accumulated_data.get("event"),
                source_url=accumulated_data.get("source_url"),
                filepath_local=local_filepath,
            )
        )

    # =========================================================================
    # Helpers — ASP.NET WebForms postback state harvesting
    # =========================================================================

    @staticmethod
    def _build_postback_data(page: PageElement) -> dict[str, str]:
        """Collect ASP.NET WebForms hidden state for a postback POST.

        Returns the fields needed to issue an authentic ``__doPostBack``
        request: ``__VIEWSTATE``, ``__VIEWSTATEGENERATOR``,
        ``__EVENTVALIDATION``, the hidden state fields (``hdMastId``,
        ``hdPDF``, ``hdOpen``), the search-toolbar inputs the page ships
        with (``txtSearch``, ``SearchTerm``), but **not** the submit
        buttons (``btnAdvanceSearch``, ``btnSearch``, paginators) — IIS
        treats *any* submit-button name in the body as the clicked button
        and short-circuits ``__EVENTTARGET`` if one is present, even with
        an empty value, redirecting the request back to
        ``/SearchResults.aspx``.
        """
        data: dict[str, str] = {}
        hidden_fields = page.query(
            XPath("//form[@id='form1']//input[@type='hidden']"),
            "hidden form fields",
            min_count=0,
        )
        for el in hidden_fields:
            name = el.get_attribute("name")
            if not name:
                continue
            data[name] = el.get_attribute("value") or ""
        # The visible search textbox.
        search_box = page.query(
            XPath("//form[@id='form1']//input[@id='txtSearch']"),
            "search textbox",
            min_count=0,
            max_count=1,
        )
        if search_box:
            data["txtSearch"] = search_box[0].get_attribute("value") or ""
        # The checked SearchTerm radio (if any).
        radios = page.query(
            XPath(
                "//form[@id='form1']//input[@type='radio'][@name='SearchTerm']"
                "[@checked]"
            ),
            "checked SearchTerm radio",
            min_count=0,
            max_count=1,
        )
        if radios:
            data["SearchTerm"] = radios[0].get_attribute("value") or ""
        return data
