"""Alaska Appellate Courts Scraper.

Scrapes docket data from Alaska Supreme Court and Court of Appeals
at appellate-records.courts.alaska.gov.

Supported courts:
- Alaska Supreme Court (ak) - case numbers S#####
- Alaska Court of Appeals (akctapp) - case numbers A#####

Entry points:
  - get_dockets: prefix search driven by ScraperParams.case_number
  - supreme_dockets_by_prefix / appeals_dockets_by_prefix: integer-driven
    3-digit prefix search (e.g., 0 -> S000/A000 -> up to 100 cases)
  - fetch_supreme_court_docket / fetch_court_of_appeals_docket:
    speculative single-case probe by 5-digit number

  The server returns up to 1000 matches per search. All results are
  in the HTML (client-side pagination only).

Flow per case:
  1. parse_search_results -> extract case links from search HTML
  2. parse_case_general -> case summary, opinions, lower court, related
  3. parse_case_parties -> participants & attorneys
  4. parse_case_records -> record entries
  5. parse_case_docket -> docket entries + document archives
  6. parse_case_motions -> motions list
  7. parse_motion_detail -> motion detail pages (sequential chain)
  8. parse_case_briefs -> briefs list
  9. parse_brief_history -> brief history pages (sequential chain)
  10. Final step yields AkDocket + remaining document archives
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import TYPE_CHECKING, ClassVar
from urllib.parse import parse_qs, urljoin, urlparse

from jkent.common.decorators import entry, step
from jkent.common.page_element import PageElement
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
)
from pyrate_limiter import Duration, Rate

from .models import (
    AkAttorney,
    AkBrief,
    AkDocket,
    AkDocketEntry,
    AkDocument,
    AkLowerCourtInfo,
    AkMotion,
    AkMotionFlag,
    AkOpinion,
    AkParty,
    AkRecordEntry,
    AkRelatedCase,
)

if TYPE_CHECKING:
    from collections.abc import Generator

    from jkent.data_types import ScraperYield

BASE_URL = "https://appellate-records.courts.alaska.gov/CMSPublic"


class AlaskaScraper(BaseScraper[AkDocket | AkDocument]):
    """Scraper for Alaska appellate court dockets.

    Usage:
        # Search for all S19xxx / A19xxx cases
        params = AlaskaScraper.params()
        params.AkDocket.case_number.value = "19"
        scraper = AlaskaScraper(params=params)

        # Search only Supreme Court
        params = AlaskaScraper.params()
        params.AkDocket.case_number.value = "19"
        params.AkDocket.court_id.values = {"ak"}
        scraper = AlaskaScraper(params=params)
    """

    # === Metadata ===
    court_ids: ClassVar[set[str]] = {"ak", "akctapp"}
    court_url: ClassVar[str] = "https://appellate-records.courts.alaska.gov/"
    data_types: ClassVar[set[str]] = {"dockets"}
    status: ClassVar[ScraperStatus] = ScraperStatus.IN_DEVELOPMENT
    version: ClassVar[str] = "2026-05-18a"
    requires_auth: ClassVar[bool] = False

    rate_limits: ClassVar[list[Rate] | None] = [Rate(4, Duration.SECOND)]

    driver_requirements: ClassVar[list[DriverRequirement]] = [
        DriverRequirement.H11_HEADER_FIXES,
        DriverRequirement.FOLLOW_REDIRECTS,
    ]

    COURT_LETTER: ClassVar[dict[str, str]] = {
        "ak": "S",
        "akctapp": "A",
    }

    # =========================================================================
    # Helpers
    # =========================================================================

    def _parse_date(self, text: str | None) -> date | None:
        """Parse date from various formats used on the site.

        Handles: M/D/YYYY, YYYY-MM-DD, M/D/YYYY h:mm AM/PM
        """
        if not text:
            return None
        text = text.strip()
        if not text:
            return None

        for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%m/%d/%Y %I:%M %p"):
            try:
                return datetime.strptime(text, fmt).date()
            except ValueError:
                continue
        return None

    def _extract_q_token(self, href: str) -> str | None:
        """Extract the q parameter from a case URL."""
        if not href:
            return None
        parsed = urlparse(href)
        params = parse_qs(parsed.query, keep_blank_values=True)
        q_values = params.get("q")
        if q_values:
            return q_values[0]
        return None

    def _court_id_from_case_number(self, case_number: str) -> str:
        """Determine court_id from case number prefix."""
        if case_number and case_number[0].upper() == "A":
            return "akctapp"
        return "ak"

    def _safe_text(self, element: PageElement) -> str:
        """Extract text content, stripped and safe."""
        try:
            return element.text_content().strip()
        except Exception:
            return ""

    _PHONE_PATTERN: ClassVar[re.Pattern[str]] = re.compile(r"[\d\(\)\-\s]{7,}")

    def _parse_attorney(self, addr_el: PageElement) -> AkAttorney:
        """Parse a single ``<address>`` block into an AkAttorney.

        Each block contains the attorney's name inside a ``<strong>``
        tag followed by free-text address lines and an optional phone
        line. The first line matching the phone pattern marks the
        split between address and phone.
        """
        strong_els = addr_el.query_xpath(
            ".//strong", "attorney name", min_count=0
        )
        name = self._safe_text(strong_els[0]) if strong_els else None
        lines = [
            line.strip()
            for line in self._safe_text(addr_el).split("\n")
            if line.strip()
        ]
        # Drop the leading name line and any duplicate name lines
        addr_lines = [line for line in lines[1:] if line != name]
        address: str | None = None
        phone: str | None = None
        for i, line in enumerate(addr_lines):
            if self._PHONE_PATTERN.match(line):
                phone = line
                address = ", ".join(addr_lines[:i]) or None
                break
        else:
            address = ", ".join(addr_lines) or None
        return AkAttorney(name=name, address=address, phone=phone)

    def _get_target_courts(self) -> set[str]:
        """Get court IDs to scrape from params."""
        if self._params is None:
            return set(self.COURT_LETTER.keys())
        try:
            proxy = self._params.AkDocket
            searchable = proxy.get_searchable_fields()
            court_field = searchable.get("court_id")
            if court_field and court_field.is_set():
                return court_field.values & set(self.COURT_LETTER.keys())
        except AttributeError:
            pass
        return set(self.COURT_LETTER.keys())

    def _get_case_number_prefix(self) -> str | None:
        """Get case number prefix from params."""
        if self._params is None:
            return None
        try:
            proxy = self._params.AkDocket
            searchable = proxy.get_searchable_fields()
            field = searchable.get("case_number")
            if field and field.is_set():
                return field.value
        except AttributeError:
            pass
        return None

    def _yield_archive_request(
        self,
        url: str,
        case_number: str,
        court_id: str,
        docket_number: str | None,
        source: str,
    ) -> Request:
        """Build an archive request that emits an AkDocument on completion."""
        return Request(
            archive=True,
            request=HTTPRequestParams(
                method=HttpMethod.GET,
                url=url,
            ),
            continuation=self.handle_document_download,
            accumulated_data={
                "case_number": case_number,
                "court_id": court_id,
                "docket_number": docket_number,
                "source": source,
                "document_url": url,
            },
        )

    # =========================================================================
    # Entry points
    # =========================================================================

    @entry(AkDocket)
    def get_dockets(self) -> Generator[Request, None, None]:
        """Bulk docket search by case number prefix.

        Reads case_number from ScraperParams as the digit prefix
        (e.g., "19" for S19xxx/A19xxx). Zero-padded if needed.
        Searches each target court.
        """
        prefix = self._get_case_number_prefix()
        if prefix is None:
            return

        # Left-pad single digits: "2" -> "02"
        if len(prefix) <= 2:
            prefix = prefix.zfill(2)

        target_courts = self._get_target_courts()

        for court_id in sorted(target_courts):
            letter = self.COURT_LETTER[court_id]
            search_term = f"{letter}{prefix}"
            url = f"{BASE_URL}/Search/CaseNumber?CaseNumber={search_term}"

            yield Request(
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url=url,
                    headers={"Accept": "text/html"},
                ),
                continuation=self.parse_search_results,
                accumulated_data={"search_term": search_term},
            )

    @entry(AkDocket)
    def fetch_supreme_court_docket(self, rid: SpeculativeRange) -> Request:
        """Speculative docket fetcher for the Alaska Supreme Court.

        Probes a single case number ``S{rid.min:05d}`` per call. The
        driver enumerates ``rid.min`` sequentially across the seed range
        and continues advancing until ``gap`` consecutive misses.
        """
        return self._make_speculative_request("S", rid.min)

    @entry(AkDocket)
    def fetch_court_of_appeals_docket(self, rid: SpeculativeRange) -> Request:
        """Speculative docket fetcher for the Alaska Court of Appeals.

        Probes a single case number ``A{rid.min:05d}`` per call.
        """
        return self._make_speculative_request("A", rid.min)

    @entry(AkDocket)
    def supreme_dockets_by_prefix(
        self, prefix: int
    ) -> Generator[Request, None, None]:
        """Bulk-search Supreme Court dockets by 3-digit prefix.

        ``prefix`` is zero-padded to 3 digits and prepended with ``S``.
        For 5-digit Alaska case numbers, a 3-digit prefix matches up to
        100 cases (e.g., ``S000`` matches S00000-S00099), well under
        the server's 1000-result cap. parse_search_results iterates
        every match row, so a single call yields all hits.
        """
        yield self._make_prefix_search_request("S", prefix)

    @entry(AkDocket)
    def appeals_dockets_by_prefix(
        self, prefix: int
    ) -> Generator[Request, None, None]:
        """Bulk-search Court of Appeals dockets by 3-digit prefix.

        ``prefix`` is zero-padded to 3 digits and prepended with ``A``.
        See ``supreme_dockets_by_prefix`` for behavior.
        """
        yield self._make_prefix_search_request("A", prefix)

    def _make_speculative_request(
        self, letter: str, case_number_int: int
    ) -> Request:
        """Build a search request for one specific case number.

        Alaska case numbers are 5-digit sequential integers prefixed by
        ``S`` (Supreme Court) or ``A`` (Court of Appeals). The
        ``CaseNumber`` search returns at most one full-match row for an
        exact number, plus any partial-match rows for related cases.
        """
        case_number = f"{letter}{case_number_int:05d}"
        return self._make_search_request(case_number)

    def _make_prefix_search_request(
        self, letter: str, prefix_int: int
    ) -> Request:
        """Build a search request for a 3-digit case-number prefix."""
        search_term = f"{letter}{prefix_int:03d}"
        return self._make_search_request(search_term)

    def _make_search_request(self, search_term: str) -> Request:
        url = f"{BASE_URL}/Search/CaseNumber?CaseNumber={search_term}"
        return Request(
            request=HTTPRequestParams(
                method=HttpMethod.GET,
                url=url,
                headers={"Accept": "text/html"},
            ),
            continuation=self.parse_search_results,
            accumulated_data={"search_term": search_term},
            deduplication_key=search_term,
        )

    # =========================================================================
    # Soft-404 detection (for speculative probing)
    # =========================================================================

    def fails_successfully(self, response: Response) -> bool:
        """Return False for empty search-results pages (soft-404).

        The CMS search endpoint returns HTTP 200 even when a case
        number does not exist; both result tables always render a
        ``<tr><td colspan="5">No … Results Found</td></tr>``
        placeholder. Real result rows always carry a
        ``class="search-link"`` anchor on the case-number cell, which
        the placeholder lacks.
        """
        if "/Search/CaseNumber" not in response.url:
            return True
        return "search-link" in response.text

    # =========================================================================
    # Step 1: Parse search results
    # =========================================================================

    @step()
    def parse_search_results(
        self,
        page: PageElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[AkDocket], None, None]:
        """Parse case search results HTML.

        Both full-match and partial-match tables are parsed.
        All rows are present in the HTML (client-side pagination only).
        Server caps at 1000 results.
        """
        for table_id in ("tblFullSearch", "tblPartialSearch"):
            rows = page.query_xpath(
                f"//table[@id='{table_id}']//tbody/tr",
                f"{table_id} rows",
                min_count=0,
            )

            for row in rows:
                cells = row.query_xpath(".//td", "row cells", min_count=0)
                if len(cells) < 4:
                    continue

                # Cell 0: case number + link
                links = cells[0].query_xpath(
                    ".//a[@class='search-link']",
                    "case link",
                    min_count=0,
                )
                if not links:
                    continue

                case_number_raw = self._safe_text(links[0])
                href = links[0].get_attribute("href")
                if not href or not case_number_raw:
                    continue

                case_number = case_number_raw.replace("-", "").strip()
                q_token = self._extract_q_token(href)
                case_url = urljoin(response.url, href)

                # Cell 1: case name
                name_els = cells[1].query_xpath(
                    ".//div[@class='divCaseName']",
                    "case name div",
                    min_count=0,
                )
                case_name = self._safe_text(name_els[0]) if name_els else ""

                # Cell 2: case type
                case_type = self._safe_text(cells[2])

                # Cell 3: status
                case_status = self._safe_text(cells[3])

                # Cell 5: date opened (hidden in page view, uses YYYY-MM-DD)
                date_filed = None
                if len(cells) > 5:
                    date_filed = self._parse_date(self._safe_text(cells[5]))

                court_id = self._court_id_from_case_number(case_number)

                docket = AkDocket(
                    case_number=case_number,
                    court_id=court_id,
                    date_filed=date_filed,
                    case_name=case_name or case_number,
                    internal_case_id=q_token,
                    case_type=case_type or None,
                    case_status=case_status or None,
                    source_url=case_url,
                )

                yield Request(
                    request=HTTPRequestParams(
                        method=HttpMethod.GET,
                        url=case_url,
                        headers={"Accept": "text/html"},
                    ),
                    continuation=self.parse_case_general,
                    accumulated_data={
                        "docket_data": docket.model_dump(mode="json"),
                        "tab_urls": {},
                    },
                )

    # =========================================================================
    # Step 2: Case Summary (General)
    # =========================================================================

    @step(priority=8)
    def parse_case_general(
        self,
        page: PageElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[AkDocket], None, None]:
        """Parse the Case Summary page."""
        docket = AkDocket.model_validate(accumulated_data["docket_data"])

        # --- Extract tab URLs from navigation ---
        tab_urls: dict[str, str] = {}
        nav_links = page.find_links(
            "//ul[contains(@class, 'cms-submenu')]//a",
            "nav tabs",
            min_count=0,
        )
        for link in nav_links:
            text = link.text.strip().lower()
            if "participant" in text:
                tab_urls["parties"] = link.url
            elif "record" in text:
                tab_urls["records"] = link.url
            elif "docket" in text:
                tab_urls["docket"] = link.url
            elif "motion" in text:
                tab_urls["motions"] = link.url
            elif "brief" in text:
                tab_urls["briefs"] = link.url

        # --- Case header ---
        header_spans = page.query_xpath(
            "//div[contains(@class, 'cms-case-name')]//span",
            "case header spans",
            min_count=0,
        )
        if header_spans:
            header_text = self._safe_text(header_spans[0])
            # Extract cross-appeal: "[Cross Appeal: S19029]"
            cross_match = re.search(
                r"\[Cross Appeal:\s*<a[^>]*>(.*?)</a>\]",
                header_spans[0].inner_html(),
            )
            if not cross_match:
                cross_match = re.search(r"Cross Appeal:\s*(\S+)", header_text)
            if cross_match:
                docket.cross_appeal_case_number = cross_match.group(1).strip()
            # Cross-appeal internal ID from link
            cross_links = header_spans[0].query_xpath(
                ".//a", "cross-appeal links", min_count=0
            )
            if cross_links:
                cross_href = cross_links[0].get_attribute("href")
                if cross_href:
                    docket.cross_appeal_internal_id = self._extract_q_token(
                        cross_href
                    )

            # Status is in pull-right span
            if len(header_spans) > 1:
                docket.case_status = (
                    self._safe_text(header_spans[1]) or docket.case_status
                )

        # --- Case info from dl ---
        # Full Case Caption
        caption_els = page.query_xpath(
            "//dt[contains(text(), 'Full Case Caption')]"
            "/following-sibling::dd[1]",
            "caption",
            min_count=0,
        )
        if caption_els:
            docket.full_caption = self._safe_text(caption_els[0]) or None

        # Case Type
        type_els = page.query_xpath(
            "//dt[contains(text(), 'Case Type')]/following-sibling::dd[1]",
            "case type",
            min_count=0,
        )
        if type_els:
            docket.case_type = self._safe_text(type_els[0]) or docket.case_type

        # Date Filed
        date_els = page.query_xpath(
            "//dt[contains(text(), 'Date Filed')]/following-sibling::dd[1]",
            "date filed",
            min_count=0,
        )
        if date_els:
            parsed = self._parse_date(self._safe_text(date_els[0]))
            if parsed:
                docket.date_filed = parsed

        # Contact Case Manager (visible text is name + phone; an
        # adjacent <a href="mailto:..."> link, when present, holds the
        # case manager's email address).
        mgr_els = page.query_xpath(
            "//dt[contains(text(), 'Contact Case Manager')]"
            "/following-sibling::dd[1]",
            "case manager",
            min_count=0,
        )
        if mgr_els:
            docket.contact_case_manager = self._safe_text(mgr_els[0]) or None
            mailto_links = mgr_els[0].query_xpath_strings(
                ".//a[starts-with(@href, 'mailto:')]/@href",
                "case manager mailto link",
                min_count=0,
                max_count=1,
            )
            if mailto_links:
                email = mailto_links[0].removeprefix("mailto:").strip()
                # Strip any query string (e.g., "?subject=...").
                email = email.split("?", 1)[0]
                docket.case_manager_email = email or None

        # --- Oral Argument ---
        oa_status = page.query_xpath(
            "//dt[contains(text(), 'Status')]/following-sibling::dd[1]",
            "OA status",
            min_count=0,
        )
        if oa_status:
            docket.oral_argument_status = self._safe_text(oa_status[0]) or None

        oa_datetime = page.query_xpath(
            "//dt[contains(text(), 'Date/Time')]/following-sibling::dd[1]",
            "OA date/time",
            min_count=0,
        )
        if oa_datetime:
            docket.oral_argument_datetime = (
                self._safe_text(oa_datetime[0]) or None
            )

        oa_min = page.query_xpath(
            "//dt[contains(text(), 'Min/Side')]/following-sibling::dd[1]",
            "OA min/side",
            min_count=0,
        )
        if oa_min:
            docket.oral_argument_min_per_side = (
                self._safe_text(oa_min[0]) or None
            )

        oa_loc = page.query_xpath(
            "//dt[contains(text(), 'Location')]/following-sibling::dd[1]",
            "OA location",
            min_count=0,
        )
        if oa_loc:
            docket.oral_argument_location = self._safe_text(oa_loc[0]) or None

        oa_video_links = page.find_links(
            "//dt[contains(text(), 'Video')]/following-sibling::dd[1]//a",
            "OA video link",
            min_count=0,
        )
        if oa_video_links:
            docket.oral_argument_video_url = oa_video_links[0].url

        # --- Note ---
        note_h4 = page.query_xpath(
            "//h4[contains(text(), 'Note')]", "note heading", min_count=0
        )
        if note_h4:
            note_siblings = page.query_xpath(
                "//h4[contains(text(), 'Note')]/following-sibling::*[1]",
                "note content",
                min_count=0,
            )
            if note_siblings:
                docket.note = self._safe_text(note_siblings[0]) or None

        # --- Opinions table ---
        opinion_rows = page.query_xpath(
            "//h5[contains(text(), 'Opinions')]"
            "/following-sibling::table[1]//tbody/tr",
            "opinion rows",
            min_count=0,
        )
        for row in opinion_rows:
            cells = row.query_xpath(".//td", "opinion cells", min_count=0)
            if len(cells) < 6:
                continue
            doc_links = row.find_links(
                ".//a[contains(@class, 'glyphicon-file')]",
                "opinion doc link",
                min_count=0,
            )
            doc_url = doc_links[0].url if doc_links else None
            opinion = AkOpinion(
                number=self._safe_text(cells[0]) or None,
                opinion_type=self._safe_text(cells[1]) or None,
                decision=self._safe_text(cells[2]) or None,
                opinion_date=self._parse_date(self._safe_text(cells[3])),
                citation=self._safe_text(cells[4]) or None,
                document_url=doc_url,
            )
            docket.opinions.append(opinion)
            if doc_url:
                yield self._yield_archive_request(
                    doc_url,
                    case_number=docket.case_number,
                    court_id=docket.court_id,
                    docket_number=opinion.number,
                    source="opinion",
                )

        # --- Lower Court table ---
        lc_rows = page.query_xpath(
            "//h5[contains(text(), 'Lower Court')]"
            "/following-sibling::table[1]//tbody/tr",
            "lower court rows",
            min_count=0,
        )
        for row in lc_rows:
            cells = row.query_xpath(".//td", "lower court cells", min_count=0)
            if len(cells) < 5:
                continue
            lc = AkLowerCourtInfo(
                case_number=self._safe_text(cells[0]) or None,
                judgment_date=self._parse_date(self._safe_text(cells[1])),
                distribution_date=self._parse_date(self._safe_text(cells[2])),
                court_or_agency=self._safe_text(cells[3]) or None,
                judge=self._safe_text(cells[4]) or None,
            )
            docket.lower_court_info.append(lc)

        # --- Related Cases table ---
        rc_rows = page.query_xpath(
            "//h5[contains(text(), 'Related Appellate')]"
            "/following-sibling::table[1]//tbody/tr",
            "related case rows",
            min_count=0,
        )
        for row in rc_rows:
            cells = row.query_xpath(".//td", "related case cells", min_count=0)
            if len(cells) < 5:
                continue
            rc_links = cells[0].query_xpath(
                ".//a", "related case link", min_count=0
            )
            internal_id = None
            if rc_links:
                rc_href = rc_links[0].get_attribute("href")
                internal_id = (
                    self._extract_q_token(rc_href) if rc_href else None
                )
            rc = AkRelatedCase(
                case_number=self._safe_text(cells[0]) or None,
                case_name=self._safe_text(cells[1]) or None,
                case_type=self._safe_text(cells[2]) or None,
                relationship=self._safe_text(cells[3]) or None,
                status=self._safe_text(cells[4]) or None,
                internal_id=internal_id,
            )
            docket.related_cases.append(rc)

        # --- Continue to Parties tab ---
        parties_url = tab_urls.get("parties")
        if parties_url:
            yield Request(
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url=parties_url,
                    headers={"Accept": "text/html"},
                ),
                continuation=self.parse_case_parties,
                accumulated_data={
                    "docket_data": docket.model_dump(mode="json"),
                    "tab_urls": tab_urls,
                },
            )
        else:
            # No parties tab; skip to records or yield
            yield from self._continue_chain(docket, tab_urls, "records")

    # =========================================================================
    # Step 3: Participants & Attorneys
    # =========================================================================

    @step(priority=7)
    def parse_case_parties(
        self,
        page: PageElement,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[AkDocket], None, None]:
        """Parse Participants & Attorneys page."""
        docket = AkDocket.model_validate(accumulated_data["docket_data"])
        tab_urls = accumulated_data["tab_urls"]

        rows = page.query_xpath(
            "//table[contains(@class, 'cms-party-table')]//tbody/tr",
            "party rows",
            min_count=0,
        )
        for row in rows:
            cells = row.query_xpath(".//td", "party cells", min_count=0)
            if len(cells) < 4:
                continue

            addr_els = cells[3].query_xpath(
                ".//address", "attorney address", min_count=0
            )
            attorneys = [self._parse_attorney(addr) for addr in addr_els]

            party = AkParty(
                name=self._safe_text(cells[0]),
                role=self._safe_text(cells[1]) or None,
                side=self._safe_text(cells[2]) or None,
                attorneys=attorneys,
            )
            docket.parties.append(party)

        yield from self._continue_chain(docket, tab_urls, "records")

    # =========================================================================
    # Step 4: Record
    # =========================================================================

    @step(priority=6)
    def parse_case_records(
        self,
        page: PageElement,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[AkDocket], None, None]:
        """Parse Record page.

        Cases with multiple trial-court source files render an
        ``<h4>Trial Court Case <number></h4>`` heading followed by its
        own ``cms-record-table``. We iterate per table and resolve each
        table's trial-court via the nearest preceding TC heading.
        """
        docket = AkDocket.model_validate(accumulated_data["docket_data"])
        tab_urls = accumulated_data["tab_urls"]

        record_tables = page.query_xpath(
            "//table[contains(@class, 'cms-record-table')]",
            "record tables",
            min_count=0,
        )
        for table in record_tables:
            tc_h4s = table.query_xpath(
                "./preceding::h4[contains(text(), 'Trial Court Case')][1]",
                "preceding trial-court heading",
                min_count=0,
                max_count=1,
            )
            tc_case = None
            if tc_h4s:
                # The case number sits inside a child <span>, so we
                # need text_content() rather than direct-child text().
                match = re.search(
                    r"Trial Court Case\s+(\S+)", self._safe_text(tc_h4s[0])
                )
                if match:
                    tc_case = match.group(1).strip()

            rows = table.query_xpath(".//tbody/tr", "record rows", min_count=0)
            for row in rows:
                cells = row.query_xpath(".//td", "record cells", min_count=0)
                if len(cells) < 5:
                    continue
                rec = AkRecordEntry(
                    trial_court_case=tc_case,
                    record_type=self._safe_text(cells[0]) or None,
                    status=self._safe_text(cells[1]) or None,
                    record_date=self._parse_date(self._safe_text(cells[2])),
                    filed_or_issued_by=self._safe_text(cells[3]) or None,
                    role=self._safe_text(cells[4]) or None,
                )
                docket.records.append(rec)

        yield from self._continue_chain(docket, tab_urls, "docket")

    # =========================================================================
    # Step 5: Docket
    # =========================================================================

    @step(priority=5)
    def parse_case_docket(
        self,
        page: PageElement,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[AkDocket], None, None]:
        """Parse Docket page (By Date view, all rows in HTML)."""
        docket = AkDocket.model_validate(accumulated_data["docket_data"])
        tab_urls = accumulated_data["tab_urls"]

        rows = page.query_xpath(
            "//table[@id='DocketList']//tbody/tr"
            "[not(contains(@class, 'grouping'))]",
            "docket rows",
            min_count=0,
        )
        for row in rows:
            cells = row.query_xpath(".//td", "docket cells", min_count=0)
            if len(cells) < 6:
                continue

            doc_links = row.find_links(
                ".//a[contains(@class, 'documentLink')]",
                "docket doc link",
                min_count=0,
            )
            doc_url = doc_links[0].url if doc_links else None

            entry = AkDocketEntry(
                docket_number=self._safe_text(cells[0]) or None,
                item=self._safe_text(cells[2]) or None,
                status=self._safe_text(cells[3]) or None,
                date_filed_or_issued=self._parse_date(
                    self._safe_text(cells[4])
                ),
                filed_or_issued_by=self._safe_text(cells[5]) or None,
                document_url=doc_url,
            )
            docket.entries.append(entry)

            if doc_url:
                yield self._yield_archive_request(
                    doc_url,
                    case_number=docket.case_number,
                    court_id=docket.court_id,
                    docket_number=entry.docket_number,
                    source="docket",
                )

        yield from self._continue_chain(docket, tab_urls, "motions")

    # =========================================================================
    # Step 6: Motions and Orders (list)
    # =========================================================================

    @step(priority=4)
    def parse_case_motions(
        self,
        page: PageElement,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[AkDocket], None, None]:
        """Parse Motions and Orders list page."""
        docket = AkDocket.model_validate(accumulated_data["docket_data"])
        tab_urls = accumulated_data["tab_urls"]

        motion_detail_items: list[dict] = []

        rows = page.query_xpath(
            "//table[contains(@class, 'cms-motion-table')]//tbody/tr",
            "motion rows",
            min_count=0,
        )
        for idx, row in enumerate(rows):
            cells = row.query_xpath(".//td", "motion cells", min_count=0)
            if len(cells) < 6:
                continue

            # Dkt# cell may have a link to detail page
            detail_links = cells[0].query_xpath(
                ".//a", "motion detail link", min_count=0
            )
            detail_url = None
            if detail_links:
                href = detail_links[0].get_attribute("href")
                if href:
                    detail_url = urljoin(
                        "https://appellate-records.courts.alaska.gov", href
                    )

            doc_links = row.find_links(
                ".//a[contains(@class, 'glyphicon-file')]",
                "motion doc link",
                min_count=0,
            )
            doc_url = doc_links[0].url if doc_links else None

            motion = AkMotion(
                docket_number=self._safe_text(cells[0]) or None,
                motion_type=self._safe_text(cells[2]) or None,
                filed_or_issued_by=self._safe_text(cells[3]) or None,
                motion_date=self._parse_date(self._safe_text(cells[4])),
                status=self._safe_text(cells[5]) or None,
                document_url=doc_url,
                detail_url=detail_url,
            )
            docket.motions.append(motion)

            if doc_url:
                yield self._yield_archive_request(
                    doc_url,
                    case_number=docket.case_number,
                    court_id=docket.court_id,
                    docket_number=motion.docket_number,
                    source="motion",
                )

            if detail_url:
                motion_detail_items.append({"index": idx, "url": detail_url})

        # Chain to motion details or briefs
        if motion_detail_items:
            first = motion_detail_items[0]
            yield Request(
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url=first["url"],
                    headers={"Accept": "text/html"},
                ),
                continuation=self.parse_motion_detail,
                accumulated_data={
                    "docket_data": docket.model_dump(mode="json"),
                    "tab_urls": tab_urls,
                    "motion_index": first["index"],
                    "pending_motion_details": motion_detail_items[1:],
                },
            )
        else:
            yield from self._continue_chain(docket, tab_urls, "briefs")

    # =========================================================================
    # Step 7: Motion Detail (sequential chain)
    # =========================================================================

    @step(priority=3)
    def parse_motion_detail(
        self,
        page: PageElement,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[AkDocket], None, None]:
        """Parse a single motion detail page.

        Updates the motion at the given index with detail info,
        then continues to the next detail or briefs.
        """
        docket = AkDocket.model_validate(accumulated_data["docket_data"])
        tab_urls = accumulated_data["tab_urls"]
        motion_index = accumulated_data["motion_index"]
        pending = accumulated_data["pending_motion_details"]

        if motion_index < len(docket.motions):
            motion = docket.motions[motion_index]
            self._parse_motion_detail_page(page, motion, docket.case_number)
            # Archive any order documents found
            for order in motion.orders:
                order_doc_url = order.get("document_url")
                if order_doc_url:
                    yield self._yield_archive_request(
                        order_doc_url,
                        case_number=docket.case_number,
                        court_id=docket.court_id,
                        docket_number=order.get("docket_number"),
                        source="order",
                    )

        if pending:
            nxt = pending[0]
            yield Request(
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url=nxt["url"],
                    headers={"Accept": "text/html"},
                ),
                continuation=self.parse_motion_detail,
                accumulated_data={
                    "docket_data": docket.model_dump(mode="json"),
                    "tab_urls": tab_urls,
                    "motion_index": nxt["index"],
                    "pending_motion_details": pending[1:],
                },
            )
        else:
            yield from self._continue_chain(docket, tab_urls, "briefs")

    def _parse_motion_detail_page(
        self, page: PageElement, motion: AkMotion, case_number: str
    ) -> None:
        """Extract detail info from a motion detail page in-place."""
        # Metadata from dt/dd pairs (labels often have trailing colons)
        dd_map: dict[str, str] = {}
        dt_els = page.query_xpath("//dt", "detail dts", min_count=0)
        for dt in dt_els:
            label = self._safe_text(dt).rstrip(":").strip()
            dd_els = dt.query_xpath(
                "./following-sibling::dd[1]", "detail dd", min_count=0
            )
            if dd_els:
                dd_map[label] = self._safe_text(dd_els[0])

        motion.response_due_date = dd_map.get("Response Due Date") or None
        motion.extension_number = dd_map.get("Extension Number") or None
        motion.total_extensions = (
            dd_map.get("Total Number of Extensions") or None
        )
        motion.days_requested = dd_map.get("Days Requested") or None
        # Site uses "Previous Days Extended" for prior extensions
        motion.days_extended = (
            dd_map.get("Previous Days Extended")
            or dd_map.get("Days Extended")
            or None
        )
        # Site uses "Total Extension if Granted" for total extension
        motion.total_days_extended = (
            dd_map.get("Total Extension if Granted")
            or dd_map.get("Total Days Extended")
            or None
        )
        motion.current_due_date = dd_map.get("Current Due Date") or None
        motion.requested_due_date = dd_map.get("Requested Due Date") or None

        # Checkboxes (glyphicon-based). Each checkbox is a glyphicon
        # span preceded by either bare text (Emergency, Full Court) or
        # a span with descriptive text (Unopposed appears as "Moving
        # party says motion is Unopposed"). The label set is
        # open-ended upstream, so capture every flag found.
        for label, value in self._collect_glyphicon_labels(page).items():
            motion.flags.append(
                AkMotionFlag(motion_flag=label, motion_value=value)
            )

        # Oppositions: table is inside a div following the h4
        opp_rows = page.query_xpath(
            "//h4[contains(text(), 'Oppositions')]"
            "/following-sibling::div[1]//table//tbody/tr",
            "opposition rows",
            min_count=0,
        )
        for row in opp_rows:
            cells = row.query_xpath(".//td", "opposition cells", min_count=0)
            if cells:
                motion.oppositions.append(
                    {"text": " | ".join(self._safe_text(c) for c in cells)}
                )

        # Orders: table is inside a div following the h4
        order_rows = page.query_xpath(
            "//h4[contains(text(), 'Orders')]"
            "/following-sibling::div[1]//table//tbody/tr",
            "order rows",
            min_count=0,
        )
        for row in order_rows:
            cells = row.query_xpath(".//td", "order cells", min_count=0)
            if len(cells) < 4:
                continue
            doc_links = row.find_links(
                ".//a[contains(@class, 'glyphicon-file')]",
                "order doc",
                min_count=0,
            )
            order = {
                "docket_number": self._safe_text(cells[0]) or None,
                "ruling": self._safe_text(cells[2]) or None,
                "distribution_date": self._safe_text(cells[3]) or None,
                "new_due_date": (
                    self._safe_text(cells[4]) if len(cells) > 4 else None
                ),
                "document_url": doc_links[0].url if doc_links else None,
            }
            motion.orders.append(order)

    def _collect_glyphicon_labels(self, page: PageElement) -> dict[str, bool]:
        """Collect all glyphicon checkbox states keyed by label.

        Each checkbox is a span with class glyphicon-check (True) or
        glyphicon-unchecked (False), preceded by either bare text or
        a sibling span containing the label.
        """
        # Use raw lxml access for maximum flexibility with mixed content
        result: dict[str, bool] = {}
        try:
            tree = page._element._element
        except AttributeError:
            return result

        icons = tree.xpath(
            "//span[contains(@class, 'glyphicon-check')"
            " or contains(@class, 'glyphicon-unchecked')"
            " or contains(@class, 'glyphicon-ok')"
            " or contains(@class, 'glyphicon-remove')]"
        )
        for icon in icons:
            cls = icon.get("class", "") or ""
            if "glyphicon-ok" in cls or "glyphicon-check" in cls:
                value = True
            elif "glyphicon-unchecked" in cls or "glyphicon-remove" in cls:
                value = False
            else:
                continue

            # Find label: try preceding sibling (element or text)
            label = ""
            parent = icon.getparent()
            if parent is None:
                continue
            siblings = list(parent)
            try:
                idx = siblings.index(icon)
            except ValueError:
                continue
            if idx > 0:
                prev = siblings[idx - 1]
                # Tail text of previous element comes between it and icon
                tail = (prev.tail or "").strip()
                if tail:
                    label = tail
                else:
                    # Try the text content of previous sibling element
                    label = prev.text_content().strip()
            else:
                # No previous sibling - use parent's text (text before children)
                label = (parent.text or "").strip()

            if label:
                # Strip "Moving party says motion is" prefix etc.
                result[label] = value
        return result

    # =========================================================================
    # Step 8: Briefs
    # =========================================================================

    @step(priority=2)
    def parse_case_briefs(
        self,
        page: PageElement,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[AkDocket], None, None]:
        """Parse Briefs page."""
        docket = AkDocket.model_validate(accumulated_data["docket_data"])

        brief_history_items: list[dict] = []

        rows = page.query_xpath(
            "//table[contains(@class, 'cms-brief-table')]//tbody/tr",
            "brief rows",
            min_count=0,
        )
        for idx, row in enumerate(rows):
            cells = row.query_xpath(".//td", "brief cells", min_count=0)
            if len(cells) < 6:
                continue

            # Dkt# may link to brief history
            history_links = cells[0].query_xpath(
                ".//a", "brief history link", min_count=0
            )
            history_url = None
            if history_links:
                href = history_links[0].get_attribute("href")
                if href:
                    history_url = urljoin(
                        "https://appellate-records.courts.alaska.gov",
                        href,
                    )

            doc_links = row.find_links(
                ".//a[contains(@class, 'glyphicon-file')]",
                "brief doc",
                min_count=0,
            )
            doc_url = doc_links[0].url if doc_links else None

            brief = AkBrief(
                docket_number=self._safe_text(cells[0]) or None,
                brief_type=self._safe_text(cells[2]) or None,
                party=self._safe_text(cells[3]) or None,
                status=self._safe_text(cells[4]) or None,
                brief_date=self._parse_date(self._safe_text(cells[5])),
                document_url=doc_url,
                history_url=history_url,
            )
            docket.briefs.append(brief)

            if doc_url:
                yield self._yield_archive_request(
                    doc_url,
                    case_number=docket.case_number,
                    court_id=docket.court_id,
                    docket_number=brief.docket_number,
                    source="brief",
                )

            if history_url:
                brief_history_items.append({"index": idx, "url": history_url})

        if brief_history_items:
            first = brief_history_items[0]
            yield Request(
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url=first["url"],
                    headers={"Accept": "text/html"},
                ),
                continuation=self.parse_brief_history,
                accumulated_data={
                    "docket_data": docket.model_dump(mode="json"),
                    "brief_index": first["index"],
                    "pending_brief_histories": brief_history_items[1:],
                },
            )
        else:
            yield ParsedData(data=docket)

    # =========================================================================
    # Step 9: Brief History (sequential chain)
    # =========================================================================

    @step(priority=1)
    def parse_brief_history(
        self,
        page: PageElement,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[AkDocket], None, None]:
        """Parse a single brief history page."""
        docket = AkDocket.model_validate(accumulated_data["docket_data"])
        brief_index = accumulated_data["brief_index"]
        pending = accumulated_data["pending_brief_histories"]

        if brief_index < len(docket.briefs):
            brief = docket.briefs[brief_index]

            # Brief type and filing party from dt/dd
            dt_els = page.query_xpath("//dt", "brief dts", min_count=0)
            for dt in dt_els:
                label = self._safe_text(dt).rstrip(":")
                dd_els = dt.query_xpath(
                    "./following-sibling::dd[1]", "brief dd", min_count=0
                )
                if dd_els:
                    val = self._safe_text(dd_els[0])
                    if "Brief Type" in label:
                        # Augment existing brief_type from list
                        if val:
                            brief.brief_type = val
                    elif "Filing Party" in label:
                        brief.filing_party = val or None

            # History table
            hist_rows = page.query_xpath(
                "//table[contains(@class, 'cms-brief-table')]//tbody/tr",
                "brief history rows",
                min_count=0,
            )
            for row in hist_rows:
                cells = row.query_xpath(".//td", "history cells", min_count=0)
                if len(cells) < 5:
                    continue
                doc_links = row.find_links(
                    ".//a[contains(@class, 'glyphicon-file')]",
                    "history doc",
                    min_count=0,
                )
                doc_url = doc_links[0].url if doc_links else None
                entry = {
                    "docket_number": self._safe_text(cells[0]) or None,
                    "type": self._safe_text(cells[2]) or None,
                    "date_filed_or_issued": (
                        self._safe_text(cells[3]) or None
                    ),
                    "date_due_or_status": (self._safe_text(cells[4]) or None),
                    "document_url": doc_url,
                }
                brief.history.append(entry)
                if doc_url:
                    yield self._yield_archive_request(
                        doc_url,
                        case_number=docket.case_number,
                        court_id=docket.court_id,
                        docket_number=entry.get("docket_number"),
                        source="brief_history",
                    )

        if pending:
            nxt = pending[0]
            yield Request(
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url=nxt["url"],
                    headers={"Accept": "text/html"},
                ),
                continuation=self.parse_brief_history,
                accumulated_data={
                    "docket_data": docket.model_dump(mode="json"),
                    "brief_index": nxt["index"],
                    "pending_brief_histories": pending[1:],
                },
            )
        else:
            yield ParsedData(data=docket)

    # =========================================================================
    # Document download handler
    # =========================================================================

    @step()
    def handle_document_download(
        self,
        response: Response,
        local_filepath: str | None,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[AkDocument], None, None]:
        """Emit an AkDocument record for an archived file.

        The CMS 302-redirects to ``/CMSPublic/Search`` for documents it
        does not have on file (most opinions from before ~2012). The
        driver follows the redirect transparently and archives the
        search-page HTML; we detect this via the final ``Content-Type``
        header (``text/html`` vs ``application/pdf``) and surface it as
        ``missing_redirected``.
        """
        content_type = (response.headers.get("content-type") or "").lower()
        missing_redirected = "application/pdf" not in content_type
        yield ParsedData(
            data=AkDocument(
                case_number=accumulated_data["case_number"],
                court_id=accumulated_data["court_id"],
                docket_number=accumulated_data.get("docket_number"),
                source=accumulated_data.get("source"),
                document_url=accumulated_data.get("document_url"),
                local_path=local_filepath,
                missing_redirected=missing_redirected,
            )
        )

    # =========================================================================
    # Chain helper
    # =========================================================================

    def _continue_chain(
        self,
        docket: AkDocket,
        tab_urls: dict[str, str],
        next_tab: str,
    ) -> Generator[Request | ParsedData, None, None]:
        """Continue to the next tab in the chain, or yield final docket.

        Tab order: parties -> records -> docket -> motions -> briefs
        """
        tab_chain = ["parties", "records", "docket", "motions", "briefs"]
        continuations = {
            "parties": self.parse_case_parties,
            "records": self.parse_case_records,
            "docket": self.parse_case_docket,
            "motions": self.parse_case_motions,
            "briefs": self.parse_case_briefs,
        }

        # Find the next available tab starting from next_tab
        start = (
            tab_chain.index(next_tab)
            if next_tab in tab_chain
            else len(tab_chain)
        )
        for tab in tab_chain[start:]:
            url = tab_urls.get(tab)
            if url:
                yield Request(
                    request=HTTPRequestParams(
                        method=HttpMethod.GET,
                        url=url,
                        headers={"Accept": "text/html"},
                    ),
                    continuation=continuations[tab],
                    accumulated_data={
                        "docket_data": docket.model_dump(mode="json"),
                        "tab_urls": tab_urls,
                    },
                )
                return

        # No more tabs - yield final docket
        yield ParsedData(data=docket)
