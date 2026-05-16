"""District of Columbia Court of Appeals scraper (C-Track).

Scrapes appellate dockets from the public C-Track install at
https://efile.dcappeals.gov/. Same older HTML-form C-Track variant as
South Carolina and Nevada — shared mechanics live in
``juriscraper.sd.state.common.ctrack``.

Entry points:

- ``get_dockets()`` — convenience: walks the most recent ~30 days.
- ``get_dockets_by_date(date_range)`` — bulk scrape across a filed-date
  window.
- ``get_docket(docket_number)`` — direct lookup by appellate case
  number (e.g. ``26-CV-0339``); the site 302s on a single match.

Per-case flow:

    POST caseSearch.do  ──▶  parse_search_listing
    ── for each row ──▶  GET caseView.do?csIID=N
                          └─ parse_case_detail (yields DCAppDocket)
                               └─ for each event with documents:
                                    POST DWR getViewDocumentLinks
                                      └─ fetch_event_document_links
                                           └─ archive Request
                                                └─ handle_document_download
                                                     yields DCAppDocument
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from typing import TYPE_CHECKING, ClassVar
from urllib.parse import urljoin

from jkent.common.decorators import entry, step
from jkent.common.page_element import PageElement
from jkent.common.param_models import DateRange
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
)
from pyrate_limiter import Duration, Rate

from juriscraper.sd.state.common.ctrack import (
    SOFT_404_MARKER,
    build_dwr_doc_links_body,
    build_search_form_skeleton,
    parse_dwr_doc_link_anchors,
    parse_label_value_table,
    parse_mmddyyyy,
)

from .models import (
    DCAppDocket,
    DCAppDocketEntry,
    DCAppDocument,
    DCAppParty,
)

if TYPE_CHECKING:
    from collections.abc import Generator

    from jkent.data_types import ScraperYield


BASE_URL = "https://efile.dcappeals.gov"
SEARCH_URL = f"{BASE_URL}/public/caseSearch.do"
CASE_VIEW_URL = f"{BASE_URL}/public/caseView.do"

# DWR endpoint for resolving a docket-event icon's `(flag, deID, csIID)`
# triple to one or more document download URLs. Note: the DWR base on
# this install is `/dwr/...` (no `/public/` prefix — SC's install puts
# DWR under `/public/dwr/...`).
DWR_DOCUMENT_LINKS_URL = (
    f"{BASE_URL}/dwr/call/plaincall/AJAX.getViewDocumentLinks.dwr"
)

# Listing page cap. The server respects values up to at least 200; a
# typical month yields ~120 cases, so 200 keeps most windows on a
# single page.
PAGE_SIZE = 200

# Number of days back from "today" for the no-arg get_dockets() entry.
DEFAULT_LOOKBACK_DAYS = 30

# Sentinel emitted by the search page when csNumber yields zero matches
# (mirrors SC's behavior).
_NO_RECORDS_SENTINEL = '<span class="NoRecords">No records were found.</span>'

# Result-row case-link href: /public/caseView.do?csIID=N
_CSIID_RE = re.compile(r"csIID=(\d+)")

# Case-detail page title: "<docket>: Case View".
_CASE_VIEW_TITLE_RE = re.compile(r"<title>[^<]+:\s*Case View", re.IGNORECASE)

# documentLink icon `name` attribute encodes "flag:deID:csIID".
_DOC_ICON_NAME_RE = re.compile(r"^(\d+):(\d+):(\d+)$")


class DCCourtOfAppealsScraper(BaseScraper[DCAppDocket | DCAppDocument]):
    """Scraper for the District of Columbia Court of Appeals."""

    # === Metadata ===
    court_ids: ClassVar[set[str]] = {"dc"}
    court_url: ClassVar[str] = BASE_URL
    data_types: ClassVar[set[str]] = {"dockets"}
    status: ClassVar[ScraperStatus] = ScraperStatus.IN_DEVELOPMENT
    version: ClassVar[str] = "2026-05-05"
    requires_auth: ClassVar[bool] = False

    rate_limits: ClassVar[list[Rate] | None] = [Rate(2, Duration.SECOND)]

    # 302 from the case-number search lands directly on the detail page.
    driver_requirements: ClassVar[list[DriverRequirement]] = [
        DriverRequirement.FOLLOW_REDIRECTS,
    ]

    # =========================================================================
    # Soft-404
    # =========================================================================

    def fails_successfully(self, response: Response) -> bool:
        """Return False for invalid / out-of-range csIID responses.

        Invalid csIIDs return HTTP 500 with a "Security Error" body
        carrying the SOFT_404_MARKER. The driver only consults
        ``fails_successfully`` for 2xx responses; the 5xx is already
        treated as a failure by the driver. We keep this override so
        that *valid* 2xx detail pages that nevertheless carry the
        marker (a sealed case fronted by a 200 in some flows) are
        still classified as misses.
        """
        return SOFT_404_MARKER not in (response.text or "")

    # =========================================================================
    # Form helper
    # =========================================================================

    @classmethod
    def _build_search_form(
        cls,
        *,
        from_date: date | None = None,
        to_date: date | None = None,
        cs_number: str | None = None,
        start_row: int = 1,
        page_size: int = PAGE_SIZE,
    ) -> dict[str, str]:
        """Build the case-search form body."""
        return build_search_form_skeleton(
            start_row=start_row,
            display_rows=page_size,
            order_by="CsNumber",
            order_dir="DESC",
            extra={
                "csNumber": cs_number or "",
                "shortTitle": "",
                "lcCsNumber": "",
                "fromDt": from_date.strftime("%m/%d/%Y") if from_date else "",
                "toDt": to_date.strftime("%m/%d/%Y") if to_date else "",
                # exclude omitted → unchecked → include closed cases too
            },
        )

    # =========================================================================
    # Entry points
    # =========================================================================

    @entry(DCAppDocket)
    def get_dockets(self) -> Generator[Request, None, None]:
        """Walk the most recent 30 days of filings."""
        today = date.today()
        start = today - timedelta(days=DEFAULT_LOOKBACK_DAYS)
        yield from self._yield_listing_request(start, today)

    @entry(DCAppDocket)
    def get_dockets_by_date(
        self, date_range: DateRange
    ) -> Generator[Request, None, None]:
        """Bulk scrape all appellate filings in a filed-date window."""
        yield from self._yield_listing_request(
            date_range.start, date_range.end
        )

    @entry(DCAppDocket)
    def get_docket(self, docket_number: str) -> Generator[Request, None, None]:
        """Fetch a single docket by appellate case number.

        The site 302s a single-match case-number search straight to the
        case-detail page; we let the redirect carry through and branch
        on the final URL in ``parse_case_or_miss``.
        """
        clean = docket_number.strip()
        yield Request(
            request=HTTPRequestParams(
                method=HttpMethod.POST,
                url=SEARCH_URL,
                data=self._build_search_form(cs_number=clean),
            ),
            continuation=self.parse_case_or_miss,
            accumulated_data={"requested_docket_number": clean},
            deduplication_key=clean,
        )

    # =========================================================================
    # Listing flow
    # =========================================================================

    def _yield_listing_request(
        self, from_date: date, to_date: date, start_row: int = 1
    ) -> Generator[Request, None, None]:
        yield Request(
            request=HTTPRequestParams(
                method=HttpMethod.POST,
                url=SEARCH_URL,
                data=self._build_search_form(
                    from_date=from_date,
                    to_date=to_date,
                    start_row=start_row,
                ),
            ),
            continuation=self.parse_search_listing,
            accumulated_data={
                "from_date": from_date.isoformat(),
                "to_date": to_date.isoformat(),
                "start_row": start_row,
            },
            deduplication_key=SkipDeduplicationCheck(),
        )

    @step()
    def parse_search_listing(
        self,
        page: PageElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[DCAppDocket], None, None]:
        """Walk one page of search results.

        For each result row, enqueue a GET of the case detail. If a
        "Next" link is present, enqueue the next page by re-POSTing the
        form with an advanced ``startRow``.
        """
        # Match leaf <tr> rows where one of the TDs has a child anchor
        # whose href carries csIID — keeps ancestor table rows out.
        rows = page.query_xpath(
            "//tr[./td/a[contains(@href, 'csIID=')]]",
            "result rows",
            min_count=0,
        )

        for row in rows:
            cells = row.query_xpath(".//td", "result cells", min_count=0)
            if len(cells) < 7:
                continue
            links = cells[0].query_xpath(
                ".//a[contains(@href, 'csIID=')]",
                "case link",
                min_count=0,
                max_count=1,
            )
            if not links:
                continue
            href = links[0].get_attribute("href") or ""
            csiid_match = _CSIID_RE.search(href)
            if not csiid_match:
                continue
            site_case_id = csiid_match.group(1)
            docket_number = " ".join(links[0].text_content().split())

            case_url = urljoin(response.url, href)

            yield Request(
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url=case_url,
                ),
                continuation=self.parse_case_detail,
                accumulated_data={
                    "docket_number": docket_number,
                    "site_case_id": site_case_id,
                },
                deduplication_key=site_case_id,
            )

        # Pagination — re-POST the form with an advanced startRow.
        next_links = page.find_links(
            "//a[normalize-space(text())='Next']",
            "next page",
            min_count=0,
            max_count=2,
        )
        if next_links:
            from_date = date.fromisoformat(accumulated_data["from_date"])
            to_date = date.fromisoformat(accumulated_data["to_date"])
            next_start = int(accumulated_data["start_row"]) + PAGE_SIZE
            yield from self._yield_listing_request(
                from_date, to_date, start_row=next_start
            )

    # =========================================================================
    # Direct case-number lookup
    # =========================================================================

    @step()
    def parse_case_or_miss(
        self,
        page: PageElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[DCAppDocket], None, None]:
        """Branch on whether the case# search redirected to a detail page.

        ``response.url`` reflects the request URL even after the kent
        HTTP driver follows the 302, so we detect the case-detail page
        by its title (``"<docket>: Case View"``) and read ``csIID``
        from a self-link in the body.
        """
        text = response.text or ""

        if _NO_RECORDS_SENTINEL in text:
            return  # clean miss

        if not _CASE_VIEW_TITLE_RE.search(text):
            # Unexpected: not a case-detail page and not the no-records
            # sentinel. csNumber search should always 302 on a single
            # match. Don't speculate further — emit nothing.
            return

        site_case_id = self._read_hidden_csiid(page)

        yield from self._emit_case_detail(
            page=page,
            response=response,
            accumulated_data={
                "docket_number": accumulated_data.get(
                    "requested_docket_number", ""
                ),
                "site_case_id": site_case_id,
            },
        )

    # =========================================================================
    # Case detail
    # =========================================================================

    @step()
    def parse_case_detail(
        self,
        page: PageElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[DCAppDocket], None, None]:
        yield from self._emit_case_detail(
            page=page,
            response=response,
            accumulated_data=accumulated_data,
        )

    def _emit_case_detail(
        self,
        *,
        page: PageElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[DCAppDocket | DCAppDocument], None, None]:
        """Build and emit a ``DCAppDocket`` from a case-detail page."""
        # DC uses lowercase class="label" (vs SC's "Label").
        case_info = parse_label_value_table(page, label_class="label")
        parties = self._parse_parties(page)
        entries = self._parse_events(page)

        docket_number = accumulated_data.get(
            "docket_number"
        ) or self._parse_docket_number(page, response.url or "")
        site_case_id = accumulated_data.get("site_case_id") or ""
        costs_waived = self._parse_costs_waived(page)

        docket = DCAppDocket(
            docket_id=docket_number,
            court_id="dc",
            site_case_id=site_case_id,
            case_name=case_info.get("Short Caption", "") or docket_number,
            classification=case_info.get("Classification") or None,
            case_status=case_info.get("Case Status") or None,
            lower_court_case_number=case_info.get(
                "Superior Court or Agency Case Number"
            )
            or None,
            date_filed=parse_mmddyyyy(case_info.get("Filed Date")),
            opening_event_date=parse_mmddyyyy(
                case_info.get("Opening Event Date")
            ),
            record_completed_date=parse_mmddyyyy(
                case_info.get("Record Completed")
            ),
            briefs_completed_date=parse_mmddyyyy(
                case_info.get("Briefs Completed")
            ),
            argued_submitted_date=parse_mmddyyyy(
                case_info.get("Argued/Submitted")
            ),
            mandate_issued_date=parse_mmddyyyy(
                case_info.get("Mandate Issued")
            ),
            disposition=case_info.get("Disposition") or None,
            next_scheduled_action=case_info.get("Next Scheduled Action")
            or None,
            post_decision_matter_pending=case_info.get(
                "Post-Decision Matter Pending"
            )
            or None,
            costs_waived=costs_waived,
            parties=parties,
            entries=entries,
            source_url=response.url,
        )
        yield ParsedData(data=docket)

        # Resolve and archive per-event documents. Each event with a
        # documentLink icon needs one DWR call to turn (flag, deID,
        # csIID) into one-or-more documentID links, which we then
        # archive. The DWR ``page=`` field expects the case-view URL
        # path; re-derive it from csIID rather than ``response.url``
        # because kent reports the original request URL even after a
        # 302, and the case#-search path arrives here with
        # ``response.url`` pointing at ``/public/caseSearch.do``.
        dwr_page = (
            f"/public/caseView.do?csIID={site_case_id}"
            if site_case_id
            else (response.url or "")
        )
        for entry_obj in entries:
            if not (entry_obj.has_documents and entry_obj.event_id):
                continue
            params = [
                entry_obj.document_link_flag or "50",
                entry_obj.event_id,
                site_case_id,
            ]
            yield Request(
                request=HTTPRequestParams(
                    method=HttpMethod.POST,
                    url=DWR_DOCUMENT_LINKS_URL,
                    data=build_dwr_doc_links_body(
                        case_url=dwr_page, params=params
                    ),
                    headers={"Content-Type": "text/plain"},
                ),
                continuation=self.fetch_event_document_links,
                accumulated_data={
                    "docket_id": docket.docket_id,
                    "court_id": docket.court_id,
                    "event_id": entry_obj.event_id,
                },
                deduplication_key=f"dwr:{site_case_id}:{entry_obj.event_id}",
                nonnavigating=True,
            )

    @step()
    def fetch_event_document_links(
        self,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[DCAppDocument], None, None]:
        """Parse a DWR reply and archive each linked PDF.

        The reply embeds an HTML fragment of one or more
        ``<a href="/document/view.do?documentID=N&csIID=N">label</a>``
        anchors — one per document attached to this docket event.
        """
        for download_url, document_id, label in parse_dwr_doc_link_anchors(
            response.text or "", BASE_URL + "/"
        ):
            yield Request(
                archive=True,
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url=download_url,
                ),
                continuation=self.handle_document_download,
                expected_type="pdf",
                accumulated_data={
                    "docket_id": accumulated_data["docket_id"],
                    "court_id": accumulated_data["court_id"],
                    "event_id": accumulated_data["event_id"],
                    "document_id": document_id,
                    "download_url": download_url,
                    "label": label,
                },
                deduplication_key=f"doc:{document_id}",
            )

    @step()
    def handle_document_download(
        self,
        accumulated_data: dict,
        local_filepath: str | None = None,
    ) -> Generator[ScraperYield[DCAppDocument], None, None]:
        """Emit one ``DCAppDocument`` for an archived PDF."""
        yield ParsedData(
            data=DCAppDocument(
                docket_id=accumulated_data["docket_id"],
                court_id=accumulated_data["court_id"],
                event_id=accumulated_data["event_id"],
                document_id=accumulated_data["document_id"],
                download_url=accumulated_data["download_url"],
                label=accumulated_data["label"],
                local_path=local_filepath,
            )
        )

    # =========================================================================
    # Page parsers
    # =========================================================================

    @staticmethod
    def _read_hidden_csiid(page: PageElement) -> str:
        """Read the page's ``<input type="hidden" name="csIID">``.

        The case-detail page carries a hidden form input with the case's
        site-internal ``csIID``. This is the only reliable in-body source
        on the direct case-number lookup path — ``response.url`` reports
        the original POST URL, not the redirected detail-page URL.
        """
        inputs = page.query_xpath(
            "//input[@type='hidden' and @name='csIID']",
            "csIID hidden input",
            min_count=0,
            max_count=1,
        )
        if not inputs:
            return ""
        return inputs[0].get_attribute("value") or ""

    @staticmethod
    def _parse_docket_number(page: PageElement, url: str) -> str:
        """Recover the appellate case number from the page title.

        The title is rendered as ``"26-CV-0339: Case View"``; we lift
        the bit before the colon. Used only when the listing-driven
        ``docket_number`` wasn't passed in (e.g. on the case-number
        lookup path where we never saw a listing row).
        """
        titles = page.query_xpath_strings(
            "//title/text()", "page title", min_count=0, max_count=1
        )
        if titles:
            head = titles[0].split(":", 1)[0].strip()
            if head:
                return head
        return ""

    @staticmethod
    def _parse_costs_waived(page: PageElement) -> bool:
        """True iff the case-info table carries a ``Costs Waived`` row.

        The flag is rendered as a label-only column in a row with no
        accompanying value cell, so it doesn't show up in the
        label-value dict.
        """
        cells = page.query_xpath(
            "//td[normalize-space(.)='Costs Waived']",
            "Costs Waived flag",
            min_count=0,
            max_count=1,
        )
        return bool(cells)

    def _parse_parties(self, page: PageElement) -> list[DCAppParty]:
        """Parse the Party Information table.

        The party table sits under a `<td>Party Information</td>` title
        row. Header row: ``Appellate Role | Party Name | IFP |
        Attorney(s) | Arguing Attorney | E-Filer``. Each subsequent
        ``<tr>`` is one party, but party rows with multiple attorneys
        wrap the trailing three columns in a nested ``<table>`` that
        contains one row per attorney + the per-attorney IFP/E-Filer
        flags.
        """
        title_cells = page.query_xpath(
            "//td[normalize-space(.)='Party Information']",
            "Party Information title",
            min_count=0,
            max_count=1,
        )
        if not title_cells:
            return []

        header_rows = page.query_xpath(
            "//td[normalize-space(.)='Appellate Role']/ancestor::tr[1]",
            "Party header row",
            min_count=0,
            max_count=1,
        )
        if not header_rows:
            return []

        data_rows = header_rows[0].query_xpath(
            "./following-sibling::tr",
            "party data rows",
            min_count=0,
        )

        parties: list[DCAppParty] = []
        for row in data_rows:
            cells = row.query_xpath("./td", "party cells", min_count=0)
            if len(cells) < 3:
                # Could be a footer / spacer row.
                continue
            role = " ".join(cells[0].text_content().split())
            name = " ".join(cells[1].text_content().split())
            if not role or not name:
                continue

            ifp = self._parse_yn(self._cell_text(cells, 2))
            attorneys, arguing, e_filer_flag = self._parse_attorney_cells(
                cells[3:]
            )
            parties.append(
                DCAppParty(
                    role=role,
                    name=name,
                    ifp=ifp,
                    attorneys=attorneys,
                    arguing_attorney=arguing,
                    e_filer=e_filer_flag,
                )
            )
        return parties

    @staticmethod
    def _cell_text(cells: list[PageElement], index: int) -> str:
        if index >= len(cells):
            return ""
        return " ".join(cells[index].text_content().split())

    @staticmethod
    def _parse_yn(text: str) -> bool | None:
        text = text.strip().upper()
        if text == "Y":
            return True
        if text == "N":
            return False
        return None

    def _parse_attorney_cells(
        self, trailing_cells: list[PageElement]
    ) -> tuple[list[str], str | None, bool | None]:
        """Extract attorneys + arguing-attorney + e-filer from the
        last three party-row columns.

        Two row shapes are observed:

        - **Flat row**: 6 top-level cells, columns 3..5 are
          ``Attorney(s)``, ``Arguing Attorney``, ``E-Filer``. We read
          them directly.
        - **Nested-attorney row**: column 3 contains a ``<table>`` with
          one row per attorney; each nested row has 3 cells
          (``Attorney name``, ``Arguing? Y/N``, ``E-Filer? Y/N``) — but
          observed pages use the cells as ``Attorney name``,
          ``IFP/Arguing flag``, ``E-Filer flag``. We collect every
          attorney name and treat the last row's flags as the party's
          ``e_filer`` value.
        """
        if not trailing_cells:
            return [], None, None

        first = trailing_cells[0]
        nested_tables = first.query_xpath(
            "./table", "nested attorney table", min_count=0, max_count=1
        )
        if nested_tables:
            attorneys: list[str] = []
            e_filer_value: bool | None = None
            arguing_value: str | None = None
            inner_rows = nested_tables[0].query_xpath(
                ".//tr", "nested attorney rows", min_count=0
            )
            for inner in inner_rows:
                inner_cells = inner.query_xpath(
                    "./td", "nested attorney cells", min_count=0
                )
                if not inner_cells:
                    continue
                name = " ".join(inner_cells[0].text_content().split())
                if not name:
                    continue
                attorneys.append(name)
                # Flags propagate from each row; the last row wins.
                if len(inner_cells) >= 3:
                    e_filer_value = self._parse_yn(
                        " ".join(inner_cells[-1].text_content().split())
                    )
                if len(inner_cells) >= 2:
                    middle = " ".join(inner_cells[-2].text_content().split())
                    if middle and middle.upper() not in {"Y", "N"}:
                        arguing_value = middle
            return attorneys, arguing_value, e_filer_value

        # Flat-row case.
        attorney_cell_text = " ".join(first.text_content().split())
        attorneys = (
            [attorney_cell_text]
            if attorney_cell_text and attorney_cell_text.lower() != "pro se"
            else (["Pro Se"] if attorney_cell_text else [])
        )
        arguing = self._cell_text(trailing_cells, 1) or None
        e_filer = self._parse_yn(self._cell_text(trailing_cells, 2))
        return attorneys, arguing, e_filer

    def _parse_events(self, page: PageElement) -> list[DCAppDocketEntry]:
        """Parse the Events table (the docket).

        The events table sits under a ``<td>Events</td>`` title row and
        has 5 columns: Event Date | Status | Description | Result | PDF.
        Data rows are identified by an MM/DD/YYYY first cell; this
        avoids accidentally picking up the header row or any spacer
        rows. Document icons in the PDF cell encode
        ``name="{flag}:{deID}:{csIID}"``.
        """
        events_titles = page.query_xpath(
            "//td[normalize-space(.)='Events']",
            "Events title",
            min_count=0,
            max_count=1,
        )
        if not events_titles:
            return []
        title_rows = events_titles[0].query_xpath(
            "./ancestor::tr[1]",
            "Events title row",
            min_count=1,
            max_count=1,
        )
        data_rows = title_rows[0].query_xpath(
            "./following-sibling::tr", "event rows", min_count=0
        )

        entries: list[DCAppDocketEntry] = []
        for row in data_rows:
            cells = row.query_xpath("./td", "event cells", min_count=0)
            if len(cells) < 5:
                continue
            date_text = self._cell_text(cells, 0)
            event_date = parse_mmddyyyy(date_text)
            if event_date is None:
                # Header row or spacer.
                continue

            status = self._cell_text(cells, 1) or None
            description = self._cell_text(cells, 2)
            result = self._cell_text(cells, 3) or None

            doc_imgs = cells[4].query_xpath(
                ".//img[contains(@class, 'documentLink')]",
                "doc icon",
                min_count=0,
                max_count=1,
            )
            event_id: str | None = None
            doc_flag: str | None = None
            has_documents = False
            if doc_imgs:
                name_attr = doc_imgs[0].get_attribute("name") or ""
                match = _DOC_ICON_NAME_RE.match(name_attr)
                if match:
                    doc_flag = match.group(1)
                    event_id = match.group(2)
                    has_documents = True

            entries.append(
                DCAppDocketEntry(
                    date_filed=event_date,
                    status=status,
                    description=description,
                    result=result,
                    event_id=event_id,
                    document_link_flag=doc_flag,
                    has_documents=has_documents,
                )
            )
        return entries
