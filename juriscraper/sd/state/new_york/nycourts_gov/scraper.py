"""New York Court of Appeals Docket Scraper (Court-PASS).

This module scrapes docket and filing data from the Court-PASS system
at courtpass.nycourts.gov. The site is behind Cloudflare managed challenge
and uses ASP.NET WebForms with ViewState-driven postback navigation,
requiring a PlaywrightDriver.

Entry points::

    - @entry search_by_argument_date(DateRange)
    - @entry search_by_decision_date(DateRange)
    - @entry search_pending()
    - @entry search_decided_after(decided_after: date)
    - @entry get_docket(docket_number: str)
    - @entry browse(argument_date?: DateRange, decision_date?: DateRange)
    - @entry browse_by_case_date(DateRange)
    - @entry enumerate_dockets(argument_date?: DateRange, decision_date?: DateRange)
    - @entry enumerate_dockets_from_page(start_page, argument_date?: DateRange, decision_date?: DateRange)
    - @entry refresh_dockets(seen_dockets: set[str], still_live: date)

Search/Browse Flow (emits NYCourtPassCase)::

    1. Entry → initial page (Search or Browse)
    2. parse_search_page → fill form with dates, submit
    3. parse_search_results → parse case tables, select each case
    4. parse_filing_detail → emit NYCourtPassCase, download files

Docket Enumeration Flow (emits NYCourtPassDocket + NYCourtPassCase)::

    1. enumerate_dockets → Docket.aspx
    2. fill_docket_search → broad OR query to match all cases
    3. parse_docket_results → paginate through all results
    4. parse_docket_detail → emit NYCourtPassDocket, click bttnDetails
    5. parse_docket_filing_detail → emit NYCourtPassCase, download files

Docket Lookup Flow (emits NYCourtPassDocket + NYCourtPassCase)::

    1. get_docket → Docket.aspx
    2. parse_docket_page → fill APL number, submit
    3. parse_docket_number_results → select case
    4. parse_docket_detail_for_entry → emit NYCourtPassDocket
    5. parse_filing_detail_from_docket → emit NYCourtPassCase, download files

Data linking:
- NYCourtPassCase, NYCourtPassDocket, and NYCourtPassFile share a
  temp_case_id (UUID) for joining in the data pipeline.

Design decisions:
- Separate scraper from NYCourtOfAppealsScraper (different site, different driver)
- Docket enumeration is independent from filing detail scraping
- File downloads require current ViewState (form POST, not direct URL)
- Generous timeouts for Cloudflare challenge on first page load
"""

from __future__ import annotations

import base64
import dataclasses
import hashlib
import logging
import re
import uuid
from datetime import date, datetime
from typing import TYPE_CHECKING, ClassVar

from kent.common.decorators import entry, step
from kent.common.exceptions import TransientException
from kent.common.page_element import PageElement
from kent.common.param_models import DateRange
from kent.data_types import (
    BaseScraper,
    DriverRequirement,
    HttpMethod,
    HTTPRequestParams,
    ParsedData,
    Request,
    Response,
    ScraperStatus,
    SkipDeduplicationCheck,
    WaitForLoadState,
    WaitForSelector,
)
from pyrate_limiter import Duration, Rate

from .models import (
    NYCourtDocketAlreadyScraped,
    NYCourtPassAttorney,
    NYCourtPassCase,
    NYCourtPassDocket,
    NYCourtPassDocketEntry,
    NYCourtPassFile,
)

if TYPE_CHECKING:
    from collections.abc import Generator

    from kent.data_types import ScraperYield

logger = logging.getLogger(__name__)

# Base URLs
COURTPASS_BASE = "https://courtpass.nycourts.gov"
SEARCH_URL = f"{COURTPASS_BASE}/Public_search.aspx"
DOCKET_URL = f"{COURTPASS_BASE}/Docket.aspx"
BROWSE_URL = f"{COURTPASS_BASE}/Public_Browse.aspx"

# ASP.NET form selectors (each page uses a different form ID)
SEARCH_FORM = "//form[@id='Form1']"
SEARCH_RESULTS_FORM = "//form[@id='Form2']"
BROWSE_FORM = "//form[@id='form1']"
BROWSE_DETAIL_FORM = "//form[@id='Form3']"
DOCKET_FORM = "//form[@id='Form2']"

# Grid control IDs used in postback __EVENTTARGET
SEARCH_GRID = "ctl00$cphMain$gvResults"
DOCKET_GRID = "ctl00$cphMain$gvResults"
BROWSE_GRID = "ctl00$cphMain$gvResults"
FILES_GRID = "ctl00$cphMain$gvFiles"

# Public_search.aspx result grids.  Pending cases (undecided) and
# decided cases appear in two separate GridViews on the results page.
SEARCH_PENDING_TABLE_ID = "cphMain_gvPublicSearchPre"
SEARCH_DECIDED_TABLE_ID = "cphMain_gvPublicSearchPost"
SEARCH_PENDING_GRID = "ctl00$cphMain$gvPublicSearchPre"
SEARCH_DECIDED_GRID = "ctl00$cphMain$gvPublicSearchPost"


_Yield = (
    NYCourtDocketAlreadyScraped
    | NYCourtPassCase
    | NYCourtPassDocket
    | NYCourtPassFile
)

# Search string that matches every case on the docket via "Find Any Words (OR)"
DOCKET_ENUMERATE_QUERY = (
    "a b c d e f g h i j k l m n o p q r s t u v w x y z 0 1 2 3 4 5 6 7 8 9"
)


class NYCourtPassScraper(BaseScraper[_Yield]):
    """Scraper for NY Court of Appeals dockets from Court-PASS.

    Court-PASS (courtpass.nycourts.gov) provides docket information,
    attorney details, and filing documents for cases before the
    New York Court of Appeals.

    The site is behind Cloudflare and uses ASP.NET WebForms,
    requiring PlaywrightDriver for all interactions.
    """

    # === Metadata ===
    court_ids: ClassVar[set[str]] = {"ny"}
    court_url: ClassVar[str] = COURTPASS_BASE
    data_types: ClassVar[set[str]] = {"dockets"}
    status: ClassVar[ScraperStatus] = ScraperStatus.IN_DEVELOPMENT
    version: ClassVar[str] = "2026-03-02"
    requires_auth: ClassVar[bool] = False
    driver_requirements: ClassVar[list[DriverRequirement]] = [
        DriverRequirement.JS_EVAL,
        DriverRequirement.FF_ALIKE,
    ]

    rate_limits: ClassVar[list[Rate] | None] = [Rate(1, Duration.SECOND)]

    # =========================================================================
    # Helpers
    # =========================================================================

    @staticmethod
    def _parse_date_mdy(text: str) -> date | None:
        """Parse MM/DD/YYYY date string from Court-PASS pages.

        Args:
            text: Date string like '03/10/2026'

        Returns:
            Parsed date or None
        """
        text = text.strip()
        if not text:
            return None
        try:
            return datetime.strptime(text, "%m/%d/%Y").date()
        except ValueError:
            return None

    @staticmethod
    def _normalize_whitespace(text: str) -> str:
        """Collapse all contiguous whitespace to a single space."""
        return " ".join(text.split())

    @staticmethod
    def _extract_detail_fields(
        page: PageElement,
        detail_span_id: str = "cphMain_lbDetails",
    ) -> dict:
        """Extract structured fields from a Court-PASS filing detail page.

        The 2026-04 redesign broke up the old nested ``<table>`` layout
        into semantic elements:

        - ``<div class="case-caption">`` holds the party lines + the ``v.`` separator.
        - ``<dl class="case-details">`` holds ``<dt>Label</dt><dd>Value</dd>``
          pairs for Argument Date / Decision Date / Opinion By / Official
          Citation / Reported Below (labels no longer end with ``:``).
        - ``<section class="case-issues">`` holds ``<p class="case-issues-category">``
          category blurbs and ``<p class="case-issues-text">`` descriptions.

        Args:
            page: The page element to extract from.
            detail_span_id: The ID of the detail span.  Browse/Search
                filing detail uses ``cphMain_lbDetails``; the docket
                filing detail uses ``cphMain_lbDetails2``.

        Returns a dict with keys: case_name, argument_date_str,
        decision_date_str, opinion_by, official_citation, issues,
        issue_details, no_files_for_case.
        """
        span_xpath = f"//span[@id='{detail_span_id}']"

        # -- Case name: join every text node under .case-caption, which
        #    gives us "<party> v. <party>" in one pass.
        caption_parts = page.query_xpath_strings(
            f"{span_xpath}//div[contains(@class, 'case-caption')]//text()",
            "case caption text",
            min_count=0,
        )
        case_name = " ".join(t.strip() for t in caption_parts if t.strip())

        # -- Metadata: build a {label: value} map from <dl class="case-details">.
        #    Each <dt> is the label, its immediately-following <dd> the value.
        detail_map: dict[str, str] = {}
        dt_elements = page.query_xpath(
            f"{span_xpath}//dl[contains(@class, 'case-details')]/dt",
            "case-details dt",
            min_count=0,
        )
        for dt in dt_elements:
            label = dt.text_content().strip().rstrip(":").strip()
            if not label:
                continue
            value_parts = dt.query_xpath_strings(
                "./following-sibling::dd[1]//text()",
                "case-details value",
                min_count=0,
            )
            value = " ".join(p.strip() for p in value_parts if p.strip())
            detail_map[label.casefold()] = value

        def _m(label: str) -> str | None:
            v = detail_map.get(label.casefold())
            return v or None

        argument_date_str = _m("Argument Date")
        decision_date_str = _m("Decision Date")
        opinion_by = _m("Opinion By")
        official_citation = _m("Official Citation")

        # Dates should look like MM/DD/YYYY — anything else is noise.
        if argument_date_str and not re.match(
            r"\d{2}/\d{2}/\d{4}", argument_date_str
        ):
            argument_date_str = None
        if decision_date_str and not re.match(
            r"\d{2}/\d{2}/\d{4}", decision_date_str
        ):
            decision_date_str = None

        # -- Issues: parallel arrays of categories and descriptive blurbs. --
        issues = [
            t.strip()
            for t in page.query_xpath_strings(
                f"{span_xpath}//p[contains(@class, 'case-issues-category')]//text()",
                "issue categories",
                min_count=0,
            )
            if t.strip()
        ]
        issue_details = [
            t.strip()
            for t in page.query_xpath_strings(
                f"{span_xpath}//p[contains(@class, 'case-issues-text')]//text()",
                "issue description text",
                min_count=0,
            )
            if t.strip()
        ]

        # no-files marker is still a plain trailing text node, but we also
        # want to catch the old exact phrase just in case the server still
        # emits it elsewhere.
        detail_texts = page.query_xpath_strings(
            f"{span_xpath}//text()",
            "filing detail text",
            min_count=0,
        )
        detail_text = " ".join(
            t.strip() for t in detail_texts if t.strip()
        ).lower()
        no_files_for_case = (
            "there are no files available for this case" in detail_text
        )

        return {
            "case_name": case_name,
            "argument_date_str": argument_date_str,
            "decision_date_str": decision_date_str,
            "opinion_by": opinion_by,
            "official_citation": official_citation,
            "issues": issues,
            "issue_details": issue_details,
            "no_files_for_case": no_files_for_case,
        }

    @staticmethod
    def _extract_docket_detail_fields(
        page: PageElement,
    ) -> dict:
        """Extract structured fields from a Court-PASS docket detail page.

        In the 2026-04 redesign the case info moved from a flat
        ``<table>`` to a ``<dl class="case-details">`` definition list
        and the docket-number anchor became a ``<button
        onclick="CallDetails()">``.  The FILINGS and ATTORNEY DETAILS
        tables below it kept their ``<table>`` shape (attorney rows
        separated by a divider), so only the first-section XPath needed
        updating.

        Returns a dict with keys: docket_number, argument_date_str,
        case_name, docket_entries, attorneys.
        """
        detail_span = "//span[@id='cphMain_lbDetails']"
        case_details_dl = f"{detail_span}//dl[@class='case-details']"

        # -- Docket number from the new <button onclick="CallDetails()"> --
        docket_links = page.query_xpath_strings(
            f"{detail_span}//button[contains(@onclick, 'CallDetails')]//text()",
            "docket number",
            min_count=0,
        )
        docket_number = None
        for link_text in docket_links:
            dn_match = re.search(r"[A-Z]+-\d{4}-\d{5}", link_text)
            if dn_match:
                docket_number = dn_match.group(0)
                break

        # -- Argument date from the case-details <dl>: <dt>Argument Date</dt><dd>...</dd> --
        arg_date_texts = page.query_xpath_strings(
            f"{case_details_dl}"
            "/dt[contains(text(),'Argument Date')]/following-sibling::dd[1]//text()",
            "argument date",
            min_count=0,
        )
        argument_date_str = None
        for t in arg_date_texts:
            t = t.strip()
            if re.match(r"\d{2}/\d{2}/\d{4}", t):
                argument_date_str = t
                break

        # -- Case title from the case-details <dl>: <dt>Title</dt><dd>...</dd> --
        title_texts = page.query_xpath_strings(
            f"{case_details_dl}"
            "/dt[contains(text(),'Title')]/following-sibling::dd[1]//text()",
            "case title",
            min_count=0,
        )
        case_name = " ".join(t.strip() for t in title_texts if t.strip())

        # -- FILINGS table: find table containing "FILINGS" header --
        # Data rows are <tr> with <td> cells (skip header/th rows)
        docket_entries: list[dict] = []
        filings_tables = page.query_xpath(
            f"{detail_span}//table[.//strong[contains(text(),'FILINGS')]]",
            "filings table",
            min_count=0,
        )
        if filings_tables:
            filing_rows = filings_tables[0].query_xpath(
                ".//tr[td[not(@colspan)]]",
                "filing data rows",
                min_count=0,
            )
            for filing_row in filing_rows:
                cells = filing_row.query_xpath(
                    "td", "filing cells", min_count=0
                )
                if len(cells) < 4:
                    continue
                docket_entries.append(
                    {
                        "filing_type": cells[0].text_content().strip(),
                        "party": cells[1].text_content().strip() or None,
                        "date_due": cells[2].text_content().strip(),
                        "date_received": cells[3].text_content().strip(),
                    }
                )

        # -- ATTORNEY DETAILS table --
        # Each attorney block is a sequence of label/value <tr> rows,
        # separated by a divider row (colspan="2" with teal background).
        attorneys: list[dict] = []
        att_tables = page.query_xpath(
            f"{detail_span}"
            "//table[.//strong[contains(text(),'ATTORNEY DETAILS')]]",
            "attorney table",
            min_count=0,
        )
        if att_tables:
            all_rows = att_tables[0].query_xpath(
                ".//tr", "attorney rows", min_count=0
            )
            current: dict[str, str | None] = {}
            for row in all_rows:
                cells = row.query_xpath("td", "cells", min_count=0)
                if not cells:
                    continue

                # Skip header row (contains <strong>ATTORNEY DETAILS</strong>)
                first_text = cells[0].text_content().strip()
                if "ATTORNEY DETAILS" in first_text:
                    continue

                # Divider row: colspan="2" with background style
                colspan = cells[0].get_attribute("colspan")
                if colspan and int(colspan) >= 2:
                    # Flush current attorney
                    if current.get("party_name"):
                        attorneys.append(dict(current))
                    current = {}
                    continue

                if len(cells) < 2:
                    continue

                label = cells[0].text_content().strip().rstrip(":")
                value = cells[1].text_content().strip()

                if label == "Party Name":
                    # Flush previous attorney if starting a new one
                    if current.get("party_name"):
                        attorneys.append(dict(current))
                    current = {
                        "party_name": value,
                        "party_role": "",
                        "firm": None,
                        "attorney_name": None,
                        "address": None,
                        "phone": None,
                    }
                elif label == "Party Role":
                    current["party_role"] = value
                elif label == "Firm":
                    current["firm"] = value or None
                elif label == "Attorney":
                    current["attorney_name"] = value or None
                elif label == "Address":
                    current["address"] = value or None
                elif label == "Phone":
                    current["phone"] = value.strip() or None
                elif not label and value and current.get("address"):
                    # Continuation of address (second/third line)
                    current["address"] += "\n" + value

            # Flush last attorney
            if current.get("party_name"):
                attorneys.append(dict(current))

        return {
            "docket_number": docket_number,
            "case_name": case_name,
            "argument_date_str": argument_date_str,
            "docket_entries": docket_entries,
            "attorneys": attorneys,
        }

    @classmethod
    def _build_docket_entries(
        cls, raw_entries: list[dict]
    ) -> list[NYCourtPassDocketEntry]:
        """Convert raw dicts to NYCourtPassDocketEntry objects."""
        return [
            NYCourtPassDocketEntry(
                filing_type=e["filing_type"],
                party=e.get("party"),
                date_due=cls._parse_date_mdy(e.get("date_due", "")),
                date_received=cls._parse_date_mdy(e.get("date_received", "")),
            )
            for e in raw_entries
        ]

    @staticmethod
    def _build_attorneys(
        raw_attorneys: list[dict],
    ) -> list[NYCourtPassAttorney]:
        """Convert raw dicts to NYCourtPassAttorney objects."""
        return [
            NYCourtPassAttorney(
                party_name=a["party_name"],
                party_role=a.get("party_role", ""),
                firm=a.get("firm"),
                attorney_name=a.get("attorney_name"),
                address=a.get("address"),
                phone=a.get("phone"),
            )
            for a in raw_attorneys
        ]

    @staticmethod
    def _date_range_to_accumulated(
        argument_date: DateRange | None,
        decision_date: DateRange | None,
    ) -> dict:
        """Serialize optional DateRange params into accumulated_data keys."""
        d: dict = {}
        if argument_date:
            d["argument_date_start"] = argument_date.start.isoformat()
            d["argument_date_end"] = argument_date.end.isoformat()
        if decision_date:
            d["decision_date_start"] = decision_date.start.isoformat()
            d["decision_date_end"] = decision_date.end.isoformat()
        return d

    @classmethod
    def _date_in_range(
        cls,
        parsed: date | None,
        range_start_str: str | None,
        range_end_str: str | None,
    ) -> bool:
        """Check whether a parsed date falls within an optional range.

        Returns True (in range / no filtering) when:
        - No range is configured (both strings are None)
        - The parsed date is None (unknown dates are never filtered)
        - The parsed date falls within [start, end]
        """
        if not range_start_str or not parsed:
            return True
        start = date.fromisoformat(range_start_str)
        end = date.fromisoformat(range_end_str) if range_end_str else start
        return start <= parsed <= end

    # =========================================================================
    # Entry Points
    # =========================================================================

    @entry(NYCourtPassDocket)
    def search_by_argument_date(
        self,
        date_range: DateRange,
    ) -> Generator[Request, None, None]:
        """Search Court-PASS by argument date range."""
        yield Request(
            request=HTTPRequestParams(
                method=HttpMethod.GET,
                url=SEARCH_URL,
            ),
            continuation=self.parse_search_page,
            accumulated_data={
                "search_type": "argument",
                "date_start": date_range.start.isoformat(),
                "date_end": date_range.end.isoformat(),
                "entry_point": "search_by_argument_date",
                "coa_site_source": "search",
            },
        )

    @entry(NYCourtPassDocket)
    def search_by_decision_date(
        self,
        date_range: DateRange,
    ) -> Generator[Request, None, None]:
        """Search Court-PASS by decision date range."""
        yield Request(
            request=HTTPRequestParams(
                method=HttpMethod.GET,
                url=SEARCH_URL,
            ),
            continuation=self.parse_search_page,
            accumulated_data={
                "search_type": "decision",
                "date_start": date_range.start.isoformat(),
                "date_end": date_range.end.isoformat(),
                "entry_point": "search_by_decision_date",
                "coa_site_source": "search",
            },
        )

    @entry(NYCourtPassDocket)
    def get_docket(
        self,
        docket_number: str,
    ) -> Generator[Request, None, None]:
        """Look up a specific docket by APL number (e.g., 'APL-2024-00177')."""
        yield Request(
            request=HTTPRequestParams(
                method=HttpMethod.GET,
                url=DOCKET_URL,
            ),
            continuation=self.parse_docket_page,
            accumulated_data={
                "docket_number": docket_number,
                "entry_point": "get_docket",
                "coa_site_source": "docket",
            },
        )

    @entry(NYCourtPassDocket)
    def browse(
        self,
        argument_date: DateRange,
        decision_date: DateRange,
    ) -> Generator[Request, None, None]:
        """Browse all cases in the alphabetical listing.

        Args:
            argument_date: If set, skip cases whose argument date
                falls outside this range.
            decision_date: If set, skip cases whose decision date
                falls outside this range.
        """
        yield Request(
            request=HTTPRequestParams(
                method=HttpMethod.GET,
                url=BROWSE_URL,
            ),
            continuation=self.parse_browse_page,
            accumulated_data={
                "entry_point": "browse",
                "coa_site_source": "browse",
                **self._date_range_to_accumulated(
                    argument_date, decision_date
                ),
            },
        )

    @entry(NYCourtPassDocket)
    def enumerate_dockets(
        self,
        argument_date: DateRange,
        decision_date: DateRange,
    ) -> Generator[Request, None, None]:
        """Enumerate all undecided dockets on Court-PASS.

        Searches the docket page with a broad OR query that matches
        every case, then paginates through all results, selecting
        each one to capture docket detail.

        Args:
            argument_date: If set, skip dockets whose argument date
                falls outside this range.
            decision_date: If set, skip dockets whose decision date
                falls outside this range.  Decision date is checked
                at the filing detail page since it may not be on the
                grid.
        """
        yield Request(
            request=HTTPRequestParams(
                method=HttpMethod.GET,
                url=DOCKET_URL,
            ),
            continuation=self.fill_docket_search,
            accumulated_data={
                "entry_point": "enumerate_dockets",
                "coa_site_source": "docket",
                **self._date_range_to_accumulated(
                    argument_date, decision_date
                ),
            },
        )

    @entry(NYCourtPassDocket)
    def enumerate_dockets_from_page(
        self,
        start_page: int,
        argument_date: DateRange,
        decision_date: DateRange,
    ) -> Generator[Request, None, None]:
        """Enumerate dockets starting from a specific page number.

        Same as ``enumerate_dockets`` but begins at ``start_page``
        instead of page 1.  Uses the recovery path: the search is
        submitted, ``parse_docket_results`` sees page 1 but expects
        ``start_page``, and ``_recover_docket_pagination`` steps
        forward through the ellipsis pagination links until reaching
        the target page.
        """
        yield Request(
            request=HTTPRequestParams(
                method=HttpMethod.GET,
                url=DOCKET_URL,
            ),
            continuation=self.fill_docket_search,
            accumulated_data={
                "entry_point": "enumerate_dockets",
                "coa_site_source": "docket",
                "target_page": start_page,
                **self._date_range_to_accumulated(
                    argument_date, decision_date
                ),
            },
        )

    @entry(NYCourtPassCase)
    def search_pending(self) -> Generator[Request, None, None]:
        """Enumerate all pending (undecided) cases from Public_search.aspx.

        Submits the search form with the same ``DOCKET_ENUMERATE_QUERY``
        alphabet + OR trick used by ``enumerate_dockets`` so every case
        matches, then pages through the ``cphMain_gvPublicSearchPre``
        grid and clicks each row into ``parse_filing_detail`` for the
        full case record.

        The initial request is emitted with ``priority=11``: we prefer
        pending case search to run after docket search (priority 3-6)
        is completed.
        """
        yield Request(
            request=HTTPRequestParams(
                method=HttpMethod.GET,
                url=SEARCH_URL,
            ),
            continuation=self.fill_search_pending,
            accumulated_data={
                "entry_point": "search_pending",
                "coa_site_source": "search",
            },
            priority=11,
            # SEARCH_URL is shared with search_decided_after; skip the
            # default URL-based dedup so both entry points can coexist.
            deduplication_key=SkipDeduplicationCheck(),
        )

    @entry(NYCourtPassCase)
    def search_decided_after(
        self,
        decided_after: date,
    ) -> Generator[Request, None, None]:
        """Enumerate all cases decided on or after ``decided_after``.

        Submits the search form with the OR-alphabet trick and a
        decision-date range of ``[decided_after, 9999-12-31]``, then
        pages through the ``cphMain_gvPublicSearchPost`` grid and
        clicks each row into ``parse_filing_detail`` for the full
        case record.

        The initial request is emitted with ``priority=15``: we prefer
        decided case search to run after both docket search (3-6) and
        pending search (11) are completed.
        """
        yield Request(
            request=HTTPRequestParams(
                method=HttpMethod.GET,
                url=SEARCH_URL,
            ),
            continuation=self.fill_search_decided_after,
            accumulated_data={
                "entry_point": "search_decided_after",
                "coa_site_source": "search",
                "decided_after": decided_after.isoformat(),
            },
            priority=15,
            # SEARCH_URL is shared with search_pending; skip the default
            # URL-based dedup so both entry points can coexist.
            deduplication_key=SkipDeduplicationCheck(),
        )

    # =========================================================================
    # Search Flow: Steps 1-2 (search page → results)
    # =========================================================================

    @step(
        xsd="xsds/courtpass_search_page.xsd",
        await_list=[
            WaitForLoadState("networkidle", timeout=60000),
            WaitForSelector("#Form1", timeout=30000),
        ],
    )
    def parse_search_page(
        self,
        page: PageElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[_Yield], None, None]:
        """Fill the Public_search.aspx form with a date range and submit.

        The redesigned 2026-04 page uses plain ``dp*`` text inputs in
        MM/DD/YYYY format instead of Telerik RadDatePicker controls —
        no ClientState / ISO companion fields anymore.
        """
        search_type = accumulated_data["search_type"]
        date_start = accumulated_data["date_start"]
        date_end = accumulated_data["date_end"]

        start_dt = date.fromisoformat(date_start)
        end_dt = date.fromisoformat(date_end)
        start_mdy = start_dt.strftime("%m/%d/%Y")
        end_mdy = end_dt.strftime("%m/%d/%Y")

        form = page.find_form(SEARCH_FORM, "search form")

        if search_type == "argument":
            start_picker = "dpStartAppealGrantedDate"
            end_picker = "dpEndAppealGrantedDate"
        else:
            start_picker = "dpStartDecisionDate"
            end_picker = "dpEndDecisionDate"

        yield form.submit(
            data={
                f"ctl00$cphMain${start_picker}": start_mdy,
                f"ctl00$cphMain${end_picker}": end_mdy,
            },
            submit_selector="input[name='ctl00$cphMain$btnFind']",
            continuation=self.parse_search_results,
            accumulated_data=accumulated_data,
        )

    @step(
        xsd="xsds/courtpass_search_page.xsd",
        await_list=[
            WaitForLoadState("networkidle", timeout=30000),
            WaitForSelector("#Form1", timeout=15000),
        ],
    )
    def parse_search_results(
        self,
        page: PageElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[_Yield], None, None]:
        """Parse search results and select each case.

        The results page has two possible tables:
        - Pending Cases (gvPending)
        - Decided Cases (gvDecided)

        Each row has: Title, Argument Date, Decision Date, Argument Number,
        and a Select button.
        """
        # Parse both pending and decided tables
        for table_id in ("gvPending", "gvDecided"):
            rows = page.query_xpath(
                f"//table[@id='cphMain_{table_id}']//tr[position()>1]",
                f"{table_id} result rows",
                min_count=0,
            )

            for i, row in enumerate(rows):
                cells = row.query_xpath("td", "row cells", min_count=0)
                if len(cells) < 4:
                    continue

                title = self._normalize_whitespace(cells[0].text_content())
                arg_date = cells[1].text_content().strip()
                dec_date = cells[2].text_content().strip()

                # The Select button triggers a postback
                # __EVENTTARGET = grid control, __EVENTARGUMENT = "OpenFiles$N"
                grid_id = f"ctl00$cphMain${table_id}"

                form = page.find_form(SEARCH_FORM, "results form")
                yield form.submit(
                    data={
                        "__EVENTTARGET": grid_id,
                        "__EVENTARGUMENT": f"OpenFiles${i}",
                    },
                    continuation=self.parse_filing_detail,
                    accumulated_data={
                        **accumulated_data,
                        "case_title_from_search": title,
                        "argument_date_from_search": arg_date,
                        "decision_date_from_search": dec_date,
                    },
                    deduplication_key=SkipDeduplicationCheck(),
                )

    # =========================================================================
    # Shared: Filing Detail (Step 3)
    # =========================================================================

    @step(
        xsd="xsds/courtpass_filing_detail.xsd",
        await_list=[
            WaitForLoadState("networkidle", timeout=30000),
            WaitForSelector("#cphMain_lbDetails", timeout=15000),
        ],
    )
    def parse_filing_detail(
        self,
        page: PageElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[_Yield], None, None]:
        """Parse the filing detail page.

        Extracts:
        - Case title
        - Argument date
        - Issues and issue details
        - Opinion by / citation (decided cases)
        - File list with availability

        Then navigates to Docket page to cross-reference.

        Due to concurrent workers sharing a browser context, the
        server may return a different case than the one selected from
        the browse/search results (session-state race).  We detect
        this by comparing the case name on the filing detail page to
        the title from the results grid and skip the case if they
        don't match.
        """
        # Extract structured fields from the detail page
        fields = self._extract_detail_fields(page)

        case_name = fields["case_name"]
        if not case_name:
            case_name = accumulated_data.get(
                "case_title_from_search", "Unknown"
            )

        argument_date = self._parse_date_mdy(fields["argument_date_str"] or "")
        decision_date = self._parse_date_mdy(fields["decision_date_str"] or "")
        # Fall back to search results if not on the page
        if not decision_date:
            dec_date_str = accumulated_data.get(
                "decision_date_from_search", ""
            )
            decision_date = (
                self._parse_date_mdy(dec_date_str) if dec_date_str else None
            )

        issues = fields["issues"]
        issue_details = fields["issue_details"]
        opinion_by = fields["opinion_by"]
        official_citation = fields[
            "official_citation"
        ] or accumulated_data.get("citation_from_search")
        argument_number = accumulated_data.get("argument_number_from_search")

        # Parse files table
        files_info: list[dict] = []
        file_rows = page.query_xpath(
            "//table[contains(@id, 'gvFiles')]//tr[position()>1]",
            "file rows",
            min_count=0,
        )
        for j, file_row in enumerate(file_rows):
            file_cells = file_row.query_xpath("td", "file cells", min_count=0)
            if len(file_cells) < 2:
                continue

            file_name = file_cells[0].text_content().strip()

            # Check if the file has a download button or "Not Available"
            # Available downloads have a plain ``<input type="submit">``;
            # unavailable ones still render a submit button but with
            # ``disabled="disabled"`` and value ``Not Available``.
            buttons = file_row.query_xpath(
                ".//input[@type='submit']",
                "download button",
                min_count=0,
            )
            enabled_buttons = [
                b for b in buttons if not b.get_attribute("disabled")
            ]
            available = len(enabled_buttons) > 0

            button_name = (
                enabled_buttons[0].get_attribute("name") if available else None
            )

            files_info.append(
                {
                    "file_name": file_name,
                    "available": available,
                    "button_name": button_name,
                    "row_index": j,
                }
            )

        # UUID links NYCourtPassCase, NYCourtPassDocket/Docketless,
        # and NYCourtPassFile together in the data pipeline.
        temp_case_id = str(uuid.uuid4())

        # Build file model objects for the case
        files = [
            NYCourtPassFile(
                file_name=f["file_name"],
                file_index=f.get("row_index"),
                available=f.get("available", True),
                temp_case_id=temp_case_id,
            )
            for f in files_info
        ]

        # Emit NYCourtPassCase with all case/filing data
        yield ParsedData(
            data=NYCourtPassCase(
                temp_case_id=temp_case_id,
                case_name=case_name,
                case_name_abbrev=accumulated_data.get("case_title_from_search")
                or None,
                argument_date=argument_date,
                decision_date=decision_date,
                issues=issues,
                issue_details=issue_details,
                opinion_by=opinion_by,
                official_citation=official_citation,
                argument_number=argument_number,
                no_files_for_case=fields["no_files_for_case"],
                files=files,
                source_url=response.url,
                source_entry_point=accumulated_data.get("entry_point"),
                coa_site_source=accumulated_data.get("coa_site_source"),
                search_page=accumulated_data.get("search_page"),
                search_row=accumulated_data.get("search_row"),
                aria_case_info=accumulated_data.get("aria_case_info"),
            )
        )

        # Download available files while we have the live page with buttons.
        # Browse + Public_search (Pending/Decided) filing detail pages use
        # Form3; the older search-by-date filing detail uses Form1.
        _detail_form3_entry_points = (
            "browse",
            "search_pending",
            "search_decided_after",
        )
        entry_point = accumulated_data.get("entry_point", "")
        files_form_selector = (
            BROWSE_DETAIL_FORM
            if entry_point.startswith(_detail_form3_entry_points)
            else SEARCH_FORM
        )
        available_files = [f for f in files_info if f.get("available")]
        file_name_prefix = base64.b64encode(
            f"{case_name}-{argument_date}-{decision_date}".encode()
        ).decode()
        for file_info in available_files:
            button_name = file_info.get("button_name")
            if not button_name:
                continue

            form = page.find_form(files_form_selector, "files form")
            file_suffix = base64.b64encode(
                f"{file_info['file_name']}".encode()
            ).decode()
            name_sha = hashlib.sha1(
                f"{file_name_prefix}-{file_suffix}".encode()
            ).hexdigest()
            yield form.submit(
                submit_selector=f"input[name='{button_name}']",
                continuation=self.handle_file_download,
                accumulated_data={
                    "temp_case_id": temp_case_id,
                    "file_name": file_info["file_name"],
                    "file_index": file_info["row_index"],
                },
                bypass_rate_limit=True,
                priority=0,
                archive=True,
                expected_type="pdf",
                deduplication_key=name_sha,
            )

    # =========================================================================
    # Docket Enumeration Flow
    # =========================================================================

    @step(
        xsd="xsds/courtpass_docket_page.xsd",
        await_list=[
            WaitForLoadState("networkidle", timeout=60000),
            WaitForSelector("#Form2", timeout=30000),
        ],
        priority=6,
    )
    def fill_docket_search(
        self,
        page: PageElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[_Yield], None, None]:
        """Fill the Docket search form and submit to enumerate all dockets.

        Searches with a broad OR query that matches every case, then
        paginates through all results in ``parse_docket_results``.

        If ``target_page`` is set in accumulated_data (from a lost-context
        recovery), it is forwarded as ``page_number`` so that
        ``parse_docket_results`` will detect the page mismatch (actual=1,
        expected=N) and jump directly to the target page.
        """
        target_page = accumulated_data.get("target_page", 1)

        form = page.find_form(DOCKET_FORM, "docket search form")
        yield form.submit(
            data={
                "ctl00$cphMain$tbPartyNames": DOCKET_ENUMERATE_QUERY,
                "ctl00$cphMain$ddlFindParty": "FindOR",
            },
            submit_selector="input[name='ctl00$cphMain$btnFind']",
            continuation=self.parse_docket_results,
            accumulated_data={
                **accumulated_data,
                "page_number": target_page,
            },
        )

    @step(
        xsd="xsds/courtpass_docket_page.xsd",
        await_list=[
            WaitForLoadState("networkidle", timeout=30000),
            WaitForSelector("#Form2", timeout=15000),
        ],
        priority=5,
    )
    def parse_docket_results(
        self,
        page: PageElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[_Yield], None, None]:
        """Parse docket search results and handle pagination.

        Each row has: Title, Argument Date, Decision Date, Select button.
        Pages have 10 results. Pagination links use __doPostBack.

        Uses the same page-guaranteeing strategy as ``parse_browse_results``
        to handle race conditions from concurrent workers.
        """
        expected_page = accumulated_data.get("page_number", 1)

        # --- Detect wrong page type (session-state race) ---
        # A concurrent worker may have navigated the shared session to
        # a detail page.  If we see a detail span instead of the
        # results grid, raise so the driver retries this request.
        wrong_page = page.query_xpath(
            "//span[@id='cphMain_lbDetails' or @id='cphMain_lbDetails2']",
            "detail span (wrong page)",
            min_count=0,
        )
        if wrong_page:
            raise TransientException(
                "parse_docket_results received a detail page "
                "instead of results (session-state race)"
            )

        rows = page.query_xpath(
            "//table[contains(@id, 'gvResults')]//tr[position()>1]",
            "docket result rows",
            min_count=0,
        )

        # Separate data rows from pagination row
        data_rows = []
        pagination_row = None
        for row in rows:
            page_links = row.query_xpath(
                ".//a[contains(@href, 'Page$')]",
                "pagination links",
                min_count=0,
            )
            if page_links:
                pagination_row = row
            else:
                data_rows.append(row)

        # --- Detect lost search context ---
        # The server may return an empty results page (no grid at all)
        # after many pages of pagination.  When this happens there are
        # no data rows, no pagination row, and no page indicator.  If
        # we expected a page > 1, re-initiate the search and jump to
        # the target page from the fresh context.
        #
        # Guard against infinite loops: if recovery has already been
        # attempted MAX times, give up and stop pagination.
        MAX_RECOVERY_ATTEMPTS = 3
        recovery_attempts = accumulated_data.get("recovery_attempts", 0)
        if not data_rows and pagination_row is None and expected_page > 1:
            if recovery_attempts >= MAX_RECOVERY_ATTEMPTS:
                logger.warning(
                    "Docket pagination: giving up after %d recovery "
                    "attempts at page %d",
                    recovery_attempts,
                    expected_page,
                )
                return
            yield from self._reinitiate_docket_search(
                expected_page, accumulated_data
            )
            return

        # --- Validate actual page matches expected page ---
        actual_page = self._detect_actual_page(page)
        if actual_page is not None and actual_page != expected_page:
            yield from self._recover_docket_pagination(
                page,
                pagination_row,
                expected_page,
                actual_page,
                accumulated_data,
            )
            return

        arg_start = accumulated_data.get("argument_date_start")
        arg_end = accumulated_data.get("argument_date_end")
        dec_start = accumulated_data.get("decision_date_start")
        dec_end = accumulated_data.get("decision_date_end")

        for i, row in enumerate(data_rows):
            cells = row.query_xpath("td", "row cells", min_count=0)
            if len(cells) < 3:
                continue

            # Argument Date is the second column (index 1)
            argument_date_from_grid = cells[1].text_content().strip()
            # Decision Date is the third column (index 2)
            decision_date_from_grid = cells[2].text_content().strip()

            # Skip dockets whose dates fall outside the requested range
            if not self._date_in_range(
                self._parse_date_mdy(argument_date_from_grid),
                arg_start,
                arg_end,
            ):
                continue
            if not self._date_in_range(
                self._parse_date_mdy(decision_date_from_grid),
                dec_start,
                dec_end,
            ):
                continue

            # New (2026-04) Docket.aspx grid uses named submit buttons
            # (id ``cphMain_gvResults_btnSelect_{i}``) instead of the old
            # __doPostBack(OpenFiles$N) postback.  aria-label carries a
            # rendered case-name + argument-date summary.
            select_buttons = row.query_xpath(
                ".//input[contains(@id, 'btnSelect')]",
                "select button",
                min_count=0,
            )
            aria_case_info = (
                select_buttons[0].get_attribute("aria-label")
                if select_buttons
                else None
            )

            form = page.find_form(DOCKET_FORM, "docket results form")
            yield form.submit(
                data={},
                submit_selector=f"#cphMain_gvResults_btnSelect_{i}",
                continuation=self.parse_docket_detail,
                accumulated_data={
                    **accumulated_data,
                    "temp_case_id": str(uuid.uuid4()),
                    "decision_date_from_grid": decision_date_from_grid,
                    "search_page": expected_page,
                    "search_row": i,
                    "aria_case_info": aria_case_info,
                },
                deduplication_key=SkipDeduplicationCheck(),
            )

        # Handle pagination — find next page link
        next_page = expected_page + 1
        yield from self._navigate_to_next_docket_page(
            page,
            pagination_row,
            next_page,
            accumulated_data,
        )

    @step(
        xsd="xsds/courtpass_docket_page.xsd",
        await_list=[
            WaitForLoadState("networkidle", timeout=30000),
            WaitForSelector("#Form2", timeout=15000),
        ],
        priority=4,
    )
    def parse_docket_detail(
        self,
        page: PageElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[_Yield], None, None]:
        """Parse the docket detail page and emit NYCourtPassDocket.

        Extracts APL number, argument date, filings table,
        and attorney details.  Then navigates to the filing detail
        page via the hidden ``bttnDetails`` button to collect case
        data and download files.
        """
        fields = self._extract_docket_detail_fields(page)
        docket_number = fields["docket_number"]

        # Short-circuit for refresh_dockets: if the docket was already
        # scraped and its decision date predates still_live, emit a
        # lightweight confirmation instead of the full scrape.
        seen_dockets = accumulated_data.get("seen_dockets")
        if seen_dockets is not None and docket_number:
            still_live_str = accumulated_data.get("still_live", "")
            dec_str = accumulated_data.get("decision_date_from_grid", "")
            decision_date = self._parse_date_mdy(dec_str) if dec_str else None
            still_live = (
                date.fromisoformat(still_live_str) if still_live_str else None
            )
            if (
                docket_number in seen_dockets
                and decision_date
                and still_live
                and decision_date < still_live
            ):
                yield ParsedData(
                    data=NYCourtDocketAlreadyScraped(
                        docket_number=docket_number,
                    )
                )
                return

        argument_date = self._parse_date_mdy(fields["argument_date_str"] or "")

        # --- decision_date range filtering ---
        # If the grid had a decision date, it was already filtered in
        # parse_docket_results.  If it was empty (undecided case), we
        # must defer the NYCourtPassDocket emission until
        # parse_docket_filing_detail confirms the decision date.
        dec_start = accumulated_data.get("decision_date_start")
        grid_dec_str = accumulated_data.get("decision_date_from_grid", "")
        grid_dec = self._parse_date_mdy(grid_dec_str) if grid_dec_str else None
        defer_docket = False

        if dec_start and not grid_dec:
            # Decision date unknown from grid — defer emission
            defer_docket = True

        if not defer_docket:
            yield ParsedData(
                data=NYCourtPassDocket(
                    temp_case_id=accumulated_data.get("temp_case_id", ""),
                    docket_number=docket_number,
                    case_name=fields["case_name"],
                    argument_date=argument_date,
                    docket_entries=self._build_docket_entries(
                        fields["docket_entries"]
                    ),
                    attorneys=self._build_attorneys(fields["attorneys"]),
                    search_page=accumulated_data.get("search_page"),
                    search_row=accumulated_data.get("search_row"),
                    aria_case_info=accumulated_data.get("aria_case_info"),
                )
            )

        # Navigate to filing detail page to collect case data and files.
        # The bttnDetails button is hidden (visibility:hidden, width:0),
        # so we can't use submit_selector (Playwright can't click it).
        # Instead, use __EVENTTARGET postback to trigger the same
        # server-side handler — kent's driver will call form.submit()
        # via JS when it sees __EVENTTARGET in field_data.
        filing_detail_data = {
            **accumulated_data,
            "docket_number": docket_number,
        }
        if defer_docket:
            # Pass raw docket fields so parse_docket_filing_detail
            # can emit the docket after confirming the decision date.
            filing_detail_data["deferred_docket"] = {
                "temp_case_id": accumulated_data.get("temp_case_id", ""),
                "docket_number": docket_number,
                "case_name": fields["case_name"],
                "argument_date_str": fields["argument_date_str"],
                "docket_entries": fields["docket_entries"],
                "attorneys": fields["attorneys"],
                "search_page": accumulated_data.get("search_page"),
                "search_row": accumulated_data.get("search_row"),
                "aria_case_info": accumulated_data.get("aria_case_info"),
            }

        form = page.find_form(DOCKET_FORM, "docket detail form")
        yield form.submit(
            data={
                "__EVENTTARGET": "ctl00$cphMain$bttnDetails",
                "__EVENTARGUMENT": "",
            },
            continuation=self.parse_docket_filing_detail,
            accumulated_data=filing_detail_data,
            deduplication_key=SkipDeduplicationCheck(),
        )

    @step(
        xsd="xsds/courtpass_filing_detail.xsd",
        await_list=[
            WaitForLoadState("networkidle", timeout=30000),
            WaitForSelector("#cphMain_lbDetails2", timeout=15000),
        ],
        priority=3,
    )
    def parse_docket_filing_detail(
        self,
        page: PageElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[_Yield], None, None]:
        """Parse the filing detail page reached from the docket.

        Same data as ``parse_filing_detail`` but accessed via the
        docket flow.  Uses ``#cphMain_lbDetails2`` (not
        ``#cphMain_lbDetails``) and ``DOCKET_FORM`` for file downloads.
        """
        fields = self._extract_detail_fields(
            page, detail_span_id="cphMain_lbDetails2"
        )

        case_name = fields["case_name"] or "Unknown"
        argument_date = self._parse_date_mdy(fields["argument_date_str"] or "")
        decision_date = self._parse_date_mdy(fields["decision_date_str"] or "")

        # --- decision_date range filtering ---
        # Decision date is now known from the filing detail page.
        # If it falls outside the requested range, skip file downloads
        # and all data emission (including any deferred docket).
        dec_start = accumulated_data.get("decision_date_start")
        dec_end = accumulated_data.get("decision_date_end")
        if not self._date_in_range(decision_date, dec_start, dec_end):
            return

        # Emit deferred NYCourtPassDocket if parse_docket_detail
        # deferred it because the grid had no decision date.
        deferred = accumulated_data.get("deferred_docket")
        if deferred:
            yield ParsedData(
                data=NYCourtPassDocket(
                    temp_case_id=deferred["temp_case_id"],
                    docket_number=deferred["docket_number"],
                    case_name=deferred["case_name"],
                    argument_date=self._parse_date_mdy(
                        deferred["argument_date_str"] or ""
                    ),
                    docket_entries=self._build_docket_entries(
                        deferred["docket_entries"]
                    ),
                    attorneys=self._build_attorneys(deferred["attorneys"]),
                    search_page=deferred.get("search_page"),
                    search_row=deferred.get("search_row"),
                    aria_case_info=deferred.get("aria_case_info"),
                )
            )

        temp_case_id = accumulated_data.get("temp_case_id", "")
        docket_number = accumulated_data.get("docket_number", "")

        # Parse files table
        files_info: list[dict] = []
        file_rows = page.query_xpath(
            "//table[contains(@id, 'gvFiles')]//tr[position()>1]",
            "file rows",
            min_count=0,
        )
        for j, file_row in enumerate(file_rows):
            file_cells = file_row.query_xpath("td", "file cells", min_count=0)
            if len(file_cells) < 2:
                continue

            file_name = file_cells[0].text_content().strip()

            # Available downloads have a plain ``<input type="submit">``;
            # unavailable ones still render a submit button but with
            # ``disabled="disabled"`` and value ``Not Available``.
            buttons = file_row.query_xpath(
                ".//input[@type='submit']",
                "download button",
                min_count=0,
            )
            enabled_buttons = [
                b for b in buttons if not b.get_attribute("disabled")
            ]
            available = len(enabled_buttons) > 0

            button_name = (
                enabled_buttons[0].get_attribute("name") if available else None
            )

            files_info.append(
                {
                    "file_name": file_name,
                    "available": available,
                    "button_name": button_name,
                    "row_index": j,
                }
            )

        files = [
            NYCourtPassFile(
                file_name=f["file_name"],
                file_index=f.get("row_index"),
                available=f.get("available", True),
                temp_case_id=temp_case_id,
                docket_number=docket_number or None,
            )
            for f in files_info
        ]

        yield ParsedData(
            data=NYCourtPassCase(
                temp_case_id=temp_case_id,
                case_name=case_name,
                argument_date=argument_date,
                decision_date=decision_date,
                issues=fields["issues"],
                issue_details=fields["issue_details"],
                opinion_by=fields["opinion_by"],
                official_citation=fields["official_citation"],
                no_files_for_case=fields["no_files_for_case"],
                files=files,
                source_url=response.url,
                source_entry_point=accumulated_data.get("entry_point"),
                coa_site_source=accumulated_data.get("coa_site_source"),
                docket_number=docket_number or None,
                search_page=accumulated_data.get("search_page"),
                search_row=accumulated_data.get("search_row"),
                aria_case_info=accumulated_data.get("aria_case_info"),
            )
        )

        file_name_prefix = base64.b64encode(
            f"{case_name}-{argument_date}-{decision_date}".encode()
        ).decode()

        # Download available files
        available_files = [f for f in files_info if f.get("available")]
        for file_info in available_files:
            button_name = file_info.get("button_name")
            if not button_name:
                continue

            form = page.find_form(DOCKET_FORM, "docket files form")
            file_suffix = base64.b64encode(
                f"{file_info['file_name']}".encode()
            ).decode()
            name_sha = hashlib.sha1(
                f"{file_name_prefix}-{file_suffix}".encode()
            ).hexdigest()
            yield form.submit(
                submit_selector=f"input[name='{button_name}']",
                continuation=self.handle_file_download,
                accumulated_data={
                    "temp_case_id": temp_case_id,
                    "docket_number": docket_number,
                    "file_name": file_info["file_name"],
                    "file_index": file_info["row_index"],
                },
                bypass_rate_limit=True,
                priority=0,
                archive=True,
                expected_type="pdf",
                deduplication_key=name_sha,
            )

    @step(
        await_list=[
            # There are 3 large files that take a bit of time
            WaitForLoadState("networkidle", timeout=90000),
        ]
    )
    def handle_file_download(
        self,
        local_filepath: str | None,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[_Yield], None, None]:
        """Handle a downloaded file.

        Yields a NYCourtPassFile with the local path and temp_case_id
        so it can be joined with the parent NYCourtPassDocket later
        in the data pipeline.
        """
        yield ParsedData(
            data=NYCourtPassFile(
                file_name=accumulated_data.get("file_name", ""),
                file_index=accumulated_data.get("file_index"),
                local_path=local_filepath,
                available=True,
                temp_case_id=accumulated_data.get("temp_case_id"),
                docket_number=accumulated_data.get("docket_number"),
            )
        )

    # =========================================================================
    # Docket Entry Point Flow (Steps for get_docket)
    # =========================================================================

    @step(
        xsd="xsds/courtpass_docket_page.xsd",
        await_list=[
            WaitForLoadState("networkidle", timeout=60000),
            WaitForSelector("#Form2", timeout=30000),
        ],
    )
    def parse_docket_page(
        self,
        page: PageElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[_Yield], None, None]:
        """Fill the Docket search form with an APL number and submit."""
        docket_number = accumulated_data["docket_number"]

        # APL numbers are in format APL-YYYY-NNNNN
        # The form may have separate fields for prefix, year, number
        # or a single text field
        form = page.find_form(DOCKET_FORM, "docket form")

        # Try single text field first
        apl_field = form.get_field("ctl00$cphMain$txtAPL")
        if apl_field:
            yield form.submit(
                data={"ctl00$cphMain$txtAPL": docket_number},
                submit_selector="input[name='ctl00$cphMain$bttnFind']",
                continuation=self.parse_docket_number_results,
                accumulated_data=accumulated_data,
            )
        else:
            # Split APL number into parts: APL-2024-00177
            parts = docket_number.split("-")
            form_data = {}
            if len(parts) == 3:
                form_data["ctl00$cphMain$txtPrefix"] = parts[0]
                form_data["ctl00$cphMain$txtYear"] = parts[1]
                form_data["ctl00$cphMain$txtNumber"] = parts[2]

            yield form.submit(
                data=form_data,
                submit_selector="input[name='ctl00$cphMain$bttnFind']",
                continuation=self.parse_docket_number_results,
                accumulated_data=accumulated_data,
            )

    @step(
        xsd="xsds/courtpass_docket_page.xsd",
        await_list=[
            WaitForLoadState("networkidle", timeout=30000),
            WaitForSelector("#Form2", timeout=15000),
        ],
    )
    def parse_docket_number_results(
        self,
        page: PageElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[_Yield], None, None]:
        """Parse docket search results when searching by APL number.

        Select the first matching result to view docket detail.
        """
        rows = page.query_xpath(
            "//table[contains(@id, 'gvResults')]//tr[position()>1]",
            "docket results",
            min_count=0,
        )

        if rows:
            # Select the first result
            form = page.find_form(DOCKET_FORM, "docket results form")
            yield form.submit(
                data={
                    "__EVENTTARGET": DOCKET_GRID,
                    "__EVENTARGUMENT": "OpenFiles$0",
                },
                continuation=self.parse_docket_detail_for_entry,
                accumulated_data=accumulated_data,
                deduplication_key=SkipDeduplicationCheck(),
            )

    @step(
        xsd="xsds/courtpass_docket_page.xsd",
        await_list=[
            WaitForLoadState("networkidle", timeout=30000),
            WaitForSelector("#Form2", timeout=15000),
        ],
    )
    def parse_docket_detail_for_entry(
        self,
        page: PageElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[_Yield], None, None]:
        """Parse docket detail from the get_docket entry point.

        Emits NYCourtPassDocket immediately, then clicks the
        CallDetails button to navigate to the filing detail page
        (which will emit NYCourtPassCase).
        """
        fields = self._extract_docket_detail_fields(page)
        argument_date = self._parse_date_mdy(fields["argument_date_str"] or "")

        # Generate temp_case_id to link docket + case + files
        temp_case_id = str(uuid.uuid4())

        yield ParsedData(
            data=NYCourtPassDocket(
                temp_case_id=temp_case_id,
                docket_number=(
                    fields["docket_number"]
                    or accumulated_data.get("docket_number")
                ),
                case_name=fields["case_name"] or "Unknown",
                argument_date=argument_date,
                docket_entries=self._build_docket_entries(
                    fields["docket_entries"]
                ),
                attorneys=self._build_attorneys(fields["attorneys"]),
            )
        )

        # Click CallDetails button to go to filing detail page
        form = page.find_form(DOCKET_FORM, "docket detail form")
        yield form.submit(
            submit_selector="input[name='ctl00$cphMain$bttnDetails']",
            continuation=self.parse_filing_detail_from_docket,
            accumulated_data={
                "temp_case_id": temp_case_id,
                "entry_point": accumulated_data.get("entry_point"),
            },
            deduplication_key=SkipDeduplicationCheck(),
        )

    @step(
        xsd="xsds/courtpass_filing_detail.xsd",
        await_list=[
            WaitForLoadState("networkidle", timeout=30000),
            WaitForSelector("#cphMain_lbDetails", timeout=15000),
        ],
    )
    def parse_filing_detail_from_docket(
        self,
        page: PageElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[_Yield], None, None]:
        """Parse filing detail page when coming from the docket entry.

        Emits NYCourtPassCase with case/filing data and downloads
        files.  The NYCourtPassDocket was already emitted by
        parse_docket_detail_for_entry.
        """
        temp_case_id = accumulated_data.get("temp_case_id", str(uuid.uuid4()))

        # Extract structured fields from the detail page
        fields = self._extract_detail_fields(page)

        case_name = fields["case_name"] or "Unknown"
        argument_date = self._parse_date_mdy(fields["argument_date_str"] or "")
        decision_date = self._parse_date_mdy(fields["decision_date_str"] or "")

        # Parse files table
        files_info: list[dict] = []
        file_rows = page.query_xpath(
            "//table[contains(@id, 'gvFiles')]//tr[position()>1]",
            "file rows",
            min_count=0,
        )
        for j, file_row in enumerate(file_rows):
            file_cells = file_row.query_xpath("td", "file cells", min_count=0)
            if len(file_cells) < 2:
                continue

            file_name = file_cells[0].text_content().strip()
            # Available downloads have a plain ``<input type="submit">``;
            # unavailable ones still render a submit button but with
            # ``disabled="disabled"`` and value ``Not Available``.
            buttons = file_row.query_xpath(
                ".//input[@type='submit']",
                "download button",
                min_count=0,
            )
            enabled_buttons = [
                b for b in buttons if not b.get_attribute("disabled")
            ]
            available = len(enabled_buttons) > 0
            button_name = (
                enabled_buttons[0].get_attribute("name") if available else None
            )

            files_info.append(
                {
                    "file_name": file_name,
                    "available": available,
                    "button_name": button_name,
                    "row_index": j,
                }
            )

        # Build file model objects for the case
        files = [
            NYCourtPassFile(
                file_name=f["file_name"],
                file_index=f.get("row_index"),
                available=f.get("available", True),
                temp_case_id=temp_case_id,
            )
            for f in files_info
        ]

        # Emit NYCourtPassCase
        yield ParsedData(
            data=NYCourtPassCase(
                temp_case_id=temp_case_id,
                case_name=case_name,
                argument_date=argument_date,
                decision_date=decision_date,
                issues=fields["issues"],
                issue_details=fields["issue_details"],
                opinion_by=fields["opinion_by"],
                official_citation=fields["official_citation"],
                no_files_for_case=fields["no_files_for_case"],
                files=files,
                source_url=response.url,
                source_entry_point=accumulated_data.get("entry_point"),
                coa_site_source=accumulated_data.get("coa_site_source"),
                search_page=accumulated_data.get("search_page"),
                search_row=accumulated_data.get("search_row"),
                aria_case_info=accumulated_data.get("aria_case_info"),
            )
        )
        file_name_prefix = base64.b64encode(
            f"{case_name}-{argument_date}-{decision_date}".encode()
        ).decode()
        # Download available files
        available_files = [f for f in files_info if f.get("available")]
        for file_info in available_files:
            button_name = file_info.get("button_name")
            if not button_name:
                continue
            file_suffix = base64.b64encode(
                f"{file_info['file_name']}".encode()
            ).decode()
            form = page.find_form(SEARCH_FORM, "files form")
            name_sha = hashlib.sha1(
                f"{file_name_prefix}-{file_suffix}".encode()
            ).hexdigest()
            yield form.submit(
                submit_selector=f"input[name='{button_name}']",
                continuation=self.handle_file_download,
                accumulated_data={
                    "temp_case_id": temp_case_id,
                    "file_name": file_info["file_name"],
                    "file_index": file_info["row_index"],
                },
                archive=True,
                expected_type="pdf",
                deduplication_key=name_sha,
            )

    # =========================================================================
    # Browse Flow
    # =========================================================================

    @step(
        xsd="xsds/courtpass_browse_page.xsd",
        await_list=[
            WaitForLoadState("networkidle", timeout=60000),
            WaitForSelector("#form1", timeout=30000),
        ],
    )
    def parse_browse_date_page(
        self,
        page: PageElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[_Yield], None, None]:
        """Fill the browse page date range and click browse.

        Uses the same Telerik RadDatePicker mechanism as the search page.
        """
        date_start = accumulated_data["date_start"]
        date_end = accumulated_data["date_end"]

        start_dt = date.fromisoformat(date_start)
        end_dt = date.fromisoformat(date_end)
        start_mdy = start_dt.strftime("%m/%d/%Y")
        end_mdy = end_dt.strftime("%m/%d/%Y")

        form = page.find_form(BROWSE_FORM, "browse form")
        yield form.submit(
            data={
                # The 2026-04 redesign replaced Telerik RadDatePicker with
                # plain dp* text inputs; there's also a new ``rblDate``
                # radio gate that must be set to "Decided" to apply the
                # date filter (otherwise the server treats it as all-cases).
                "ctl00$cphMain$rblDate": "Decided",
                "ctl00$cphMain$dpStartDecisionDate": start_mdy,
                "ctl00$cphMain$dpEndDecisionDate": end_mdy,
            },
            submit_selector="input[name='ctl00$cphMain$bttnAlpha']",
            continuation=self.parse_browse_results,
            accumulated_data={
                **accumulated_data,
                "page_number": accumulated_data.get("page_number", 1),
            },
        )

    @step(
        xsd="xsds/courtpass_browse_page.xsd",
        await_list=[
            WaitForLoadState("networkidle", timeout=60000),
            WaitForSelector("#form1", timeout=30000),
        ],
    )
    def parse_browse_page(
        self,
        page: PageElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[_Yield], None, None]:
        """Click the 'Browse Alphabetical Case Name Listing' button."""
        form = page.find_form(BROWSE_FORM, "browse form")
        yield form.submit(
            submit_selector="input[name='ctl00$cphMain$bttnAlpha']",
            continuation=self.parse_browse_results,
            accumulated_data={
                **accumulated_data,
                "page_number": accumulated_data.get("page_number", 1),
            },
        )

    @staticmethod
    def _detect_actual_page(
        page: PageElement,
    ) -> int | None:
        """Detect the actual grid page from the pagination row.

        ASP.NET GridView renders the current page number as a plain
        ``<span>`` (not a hyperlink) inside the pagination row.

        Returns:
            The page number shown as current, or None if not found.
        """
        spans = page.query_xpath(
            "//table[contains(@id, 'gvResults')]"
            "//tr[last()]//td//span[not(ancestor::a)]",
            "current page indicator",
            min_count=0,
        )
        for span in spans:
            text = span.text_content().strip()
            if text.isdigit():
                return int(text)
        return None

    @staticmethod
    def _extract_visible_page_numbers(
        pagination_row: PageElement,
    ) -> list[int]:
        """Extract all page numbers available as links in the pagination row.

        Returns:
            Sorted list of page numbers that appear as ``Page$N`` links.
        """
        links = pagination_row.query_xpath(
            ".//a[contains(@href, 'Page$')]",
            "pagination page links",
            min_count=0,
        )
        pages: list[int] = []
        for link in links:
            href = link.get_attribute("href") or ""
            m = re.search(r"Page\$(\d+)", href)
            if m:
                pages.append(int(m.group(1)))
        return sorted(pages)

    @step(
        xsd="xsds/courtpass_browse_page.xsd",
        await_list=[
            WaitForLoadState("networkidle", timeout=30000),
            WaitForSelector("#form1", timeout=15000),
        ],
    )
    def parse_browse_results(
        self,
        page: PageElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[_Yield], None, None]:
        """Parse browse results and handle pagination.

        Each row has: Title, Argument Date, Decision Date, Select button.
        Pages have 10 results. Pagination links use __doPostBack.

        Due to concurrent workers sharing a browser context, the ASP.NET
        server may return a different page than requested (session-state
        race).  We detect this by comparing the expected page number to
        the ``<span>`` indicator in the pagination row and recover by
        navigating toward the correct page.
        """
        expected_page = accumulated_data.get("page_number", 1)

        # --- Detect wrong page type (session-state race) ---
        # A concurrent worker may have navigated the shared session to
        # a filing detail page.  If we see a detail span instead of
        # the results grid, raise so the driver retries this request.
        wrong_page = page.query_xpath(
            "//span[@id='cphMain_lbDetails' or @id='cphMain_lbDetails2']",
            "detail span (wrong page)",
            min_count=0,
        )
        if wrong_page:
            raise TransientException(
                "parse_browse_results received a detail page "
                "instead of results (session-state race)"
            )

        rows = page.query_xpath(
            "//table[contains(@id, 'gvResults')]//tr[position()>1]",
            "browse result rows",
            min_count=0,
        )

        # Filter out pagination row (contains <a> links with page numbers)
        data_rows = []
        pagination_row = None
        for row in rows:
            # Pagination rows have anchor links with Page$ arguments
            page_links = row.query_xpath(
                ".//a[contains(@href, 'Page$')]",
                "pagination links",
                min_count=0,
            )
            if page_links:
                pagination_row = row
            else:
                data_rows.append(row)

        # --- Detect lost browse context ---
        # The server may return the initial browse page (no grid at all)
        # after many pages of pagination.  When this happens there are
        # no data rows, no pagination row, and no page indicator.  If
        # we expected a page > 1, re-initiate the browse and jump to
        # the target page from the fresh context.
        MAX_RECOVERY_ATTEMPTS = 3
        recovery_attempts = accumulated_data.get("recovery_attempts", 0)
        if not data_rows and pagination_row is None and expected_page > 1:
            if recovery_attempts >= MAX_RECOVERY_ATTEMPTS:
                logger.warning(
                    "Browse pagination: giving up after %d recovery "
                    "attempts at page %d",
                    recovery_attempts,
                    expected_page,
                )
                return
            yield from self._reinitiate_browse(expected_page, accumulated_data)
            return

        # --- Validate actual page matches expected page ---
        actual_page = self._detect_actual_page(page)
        if actual_page is not None and actual_page != expected_page:
            # Server returned wrong page (session-state race).
            # Skip data rows to avoid duplicates; attempt to recover
            # pagination toward the expected page.
            yield from self._recover_pagination(
                page,
                pagination_row,
                expected_page,
                actual_page,
                accumulated_data,
            )
            return

        arg_start = accumulated_data.get("argument_date_start")
        arg_end = accumulated_data.get("argument_date_end")
        dec_start = accumulated_data.get("decision_date_start")
        dec_end = accumulated_data.get("decision_date_end")

        for i, row in enumerate(data_rows):
            cells = row.query_xpath("td", "row cells", min_count=0)
            if len(cells) < 3:
                continue

            title = self._normalize_whitespace(cells[0].text_content())
            arg_date = cells[1].text_content().strip()
            dec_date = cells[2].text_content().strip()

            # Skip cases whose dates fall outside the requested range
            if not self._date_in_range(
                self._parse_date_mdy(arg_date), arg_start, arg_end
            ):
                continue
            if not self._date_in_range(
                self._parse_date_mdy(dec_date), dec_start, dec_end
            ):
                continue

            # As of 2026-04, the Court-PASS browse grid replaced its
            # __doPostBack(OpenFiles$N) buttons with real named submits
            # (``ctl00$cphMain$gvResults$ctl{i+2}$btnSelect``, id
            # ``cphMain_gvResults_btnSelect_{i}``). ASP.NET's event
            # validation rejects the old postback shape, so we click the
            # new button instead. The aria-label on the button carries a
            # rendered "case name + dates" blurb we capture as a
            # tie-breaker for cases whose detail page has no title.
            select_buttons = row.query_xpath(
                ".//input[contains(@id, 'btnSelect')]",
                "select button",
                min_count=0,
            )
            aria_case_info = (
                select_buttons[0].get_attribute("aria-label")
                if select_buttons
                else None
            )

            form = page.find_form(BROWSE_FORM, "browse form")
            yield form.submit(
                data={},
                submit_selector=f"#cphMain_gvResults_btnSelect_{i}",
                continuation=self.parse_filing_detail,
                accumulated_data={
                    **accumulated_data,
                    "case_title_from_search": title,
                    "argument_date_from_search": arg_date,
                    "decision_date_from_search": dec_date,
                    "search_type": None,  # Not from search
                    "search_page": expected_page,
                    "search_row": i,
                    "aria_case_info": aria_case_info,
                },
                deduplication_key=SkipDeduplicationCheck(),
            )

        # Handle pagination — find next page link
        next_page = expected_page + 1
        yield from self._navigate_to_next_browse_page(
            page,
            pagination_row,
            next_page,
            accumulated_data,
        )

    def _recover_pagination(
        self,
        page: PageElement,
        pagination_row: PageElement | None,
        expected_page: int,
        actual_page: int,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[_Yield], None, None]:
        """Recover when the server returned the wrong browse page.

        Navigates toward ``expected_page`` by choosing the closest
        visible page link, or the forward/backward ellipsis, to shift
        the pagination window in the right direction.
        """
        if pagination_row is None:
            return

        visible = self._extract_visible_page_numbers(pagination_row)
        if not visible:
            return

        # Last page: no forward links exist beyond the current page.
        if max(visible) < actual_page:
            return

        if expected_page in visible:
            # Target page is directly reachable
            target = expected_page
        elif expected_page > actual_page:
            # Need to go forward — pick the highest visible page
            target = max(visible)
        else:
            # Need to go backward — pick the lowest visible page
            target = min(visible)

        form = page.find_form(BROWSE_FORM, "browse pagination recovery")
        yield form.submit(
            data={
                "__EVENTTARGET": BROWSE_GRID,
                "__EVENTARGUMENT": f"Page${target}",
            },
            continuation=self.parse_browse_results,
            accumulated_data={
                **accumulated_data,
                "page_number": expected_page
                if target == expected_page
                else target,
            },
            deduplication_key=SkipDeduplicationCheck(),
        )

    def _navigate_to_next_browse_page(
        self,
        page: PageElement,
        pagination_row: PageElement | None,
        next_page: int,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[_Yield], None, None]:
        """Navigate to the next browse page, with recovery if the link
        is not in the current pagination window.

        If ``Page$next_page`` is visible, navigate directly.  Otherwise,
        use the forward ellipsis (highest visible page) to shift the
        pagination window closer.
        """
        if pagination_row is None:
            return

        visible = self._extract_visible_page_numbers(pagination_row)
        if not visible:
            return

        # Detect last page: current page (span) is beyond all clickable
        # links, meaning there are no forward pages to navigate to.
        actual_page = self._detect_actual_page(page)
        if actual_page is not None and max(visible) < actual_page:
            return

        if next_page in visible:
            target = next_page
            target_page_number = next_page
        elif any(p > next_page for p in visible):
            # The window already contains pages beyond our target;
            # there's no page N+1 link, so we've likely reached the end
            # or the window skipped it.  Use the closest page >= next.
            target = min(p for p in visible if p >= next_page)
            target_page_number = target
        elif visible:
            # next_page is beyond the visible window.
            # Use the highest visible page (forward ellipsis) to shift.
            target = max(visible)
            target_page_number = target
        else:
            return

        form = page.find_form(BROWSE_FORM, "browse pagination")
        yield form.submit(
            data={
                "__EVENTTARGET": BROWSE_GRID,
                "__EVENTARGUMENT": f"Page${target}",
            },
            continuation=self.parse_browse_results,
            accumulated_data={
                **accumulated_data,
                "page_number": target_page_number,
            },
            deduplication_key=SkipDeduplicationCheck(),
        )

    # ---- Browse re-initiation ----

    def _reinitiate_browse(
        self,
        target_page: int,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[_Yield], None, None]:
        """Re-initiate the browse after the server lost context.

        Yields a fresh GET to Public_Browse.aspx.  The continuation
        depends on the original entry point:

        - ``browse``: goes to ``parse_browse_page`` (clicks the
          alphabetical listing button)
        - ``browse_by_case_date``: goes to ``parse_browse_date_page``
          (fills in the date range and submits)

        After the browse is re-submitted, ``parse_browse_results``
        will receive page 1 but expect ``target_page``, triggering
        ``_recover_pagination`` to step forward through the pagination
        links until reaching the target page.

        Increments ``recovery_attempts`` so the caller can detect
        infinite loops.
        """
        recovery_attempts = accumulated_data.get("recovery_attempts", 0) + 1
        logger.info(
            "Browse pagination: re-initiating browse for page %d (attempt %d)",
            target_page,
            recovery_attempts,
        )

        entry_point = accumulated_data.get("entry_point", "browse")

        if entry_point == "browse_by_case_date":
            continuation = self.parse_browse_date_page
        else:
            continuation = self.parse_browse_page

        yield Request(
            request=HTTPRequestParams(
                method=HttpMethod.GET,
                url=BROWSE_URL,
            ),
            continuation=continuation,
            accumulated_data={
                **accumulated_data,
                "page_number": target_page,
                "recovery_attempts": recovery_attempts,
            },
            deduplication_key=SkipDeduplicationCheck(),
        )

    # ---- Docket pagination helpers ----

    def _reinitiate_docket_search(
        self,
        target_page: int,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[_Yield], None, None]:
        """Re-initiate the docket search after the server lost context.

        Yields a fresh GET to Docket.aspx with ``target_page`` in
        accumulated_data.  ``fill_docket_search`` will re-submit the
        search and set ``page_number`` to ``target_page``.  When
        ``parse_docket_results`` receives page 1 but expects page N,
        ``_recover_docket_pagination`` will step forward through the
        pagination ellipsis links until reaching the target.

        Increments ``recovery_attempts`` so the caller can detect
        infinite loops.
        """
        recovery_attempts = accumulated_data.get("recovery_attempts", 0) + 1
        logger.info(
            "Docket pagination: re-initiating search for page %d (attempt %d)",
            target_page,
            recovery_attempts,
        )
        yield Request(
            request=HTTPRequestParams(
                method=HttpMethod.GET,
                url=DOCKET_URL,
            ),
            continuation=self.fill_docket_search,
            accumulated_data={
                **accumulated_data,
                "target_page": target_page,
                "recovery_attempts": recovery_attempts,
            },
            deduplication_key=SkipDeduplicationCheck(),
        )

    def _recover_docket_pagination(
        self,
        page: PageElement,
        pagination_row: PageElement | None,
        expected_page: int,
        actual_page: int,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[_Yield], None, None]:
        """Recover when the docket results server returned the wrong page.

        If the target page is visible in the pagination row, jumps
        directly.  Otherwise steps forward via the highest visible
        page (typically the ``...`` ellipsis link) and keeps
        ``page_number`` set to the original target so the next
        ``parse_docket_results`` call will continue stepping.
        """
        if pagination_row is None:
            return

        visible = self._extract_visible_page_numbers(pagination_row)
        if not visible:
            return

        # Last page: no forward links exist beyond the current page.
        if max(visible) < actual_page:
            return

        if expected_page in visible:
            target = expected_page
        elif expected_page > actual_page:
            # Step forward via highest visible link (the "..." ellipsis)
            target = max(visible)
        else:
            target = min(visible)

        form = page.find_form(DOCKET_FORM, "docket pagination recovery")
        yield form.submit(
            data={
                "__EVENTTARGET": DOCKET_GRID,
                "__EVENTARGUMENT": f"Page${target}",
            },
            continuation=self.parse_docket_results,
            accumulated_data={
                **accumulated_data,
                "page_number": expected_page,
            },
            deduplication_key=SkipDeduplicationCheck(),
        )

    def _navigate_to_next_docket_page(
        self,
        page: PageElement,
        pagination_row: PageElement | None,
        next_page: int,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[_Yield], None, None]:
        """Navigate to the next docket results page.

        Same strategy as ``_navigate_to_next_browse_page`` but targets
        the docket form/grid and continues to ``parse_docket_results``.
        """
        if pagination_row is None:
            return

        visible = self._extract_visible_page_numbers(pagination_row)
        if not visible:
            return

        actual_page = self._detect_actual_page(page)
        if actual_page is not None and max(visible) < actual_page:
            return

        if next_page in visible:
            target = next_page
            target_page_number = next_page
        elif any(p > next_page for p in visible):
            target = min(p for p in visible if p >= next_page)
            target_page_number = target
        elif visible:
            target = max(visible)
            target_page_number = target
        else:
            return

        form = page.find_form(DOCKET_FORM, "docket pagination")
        yield form.submit(
            data={
                "__EVENTTARGET": DOCKET_GRID,
                "__EVENTARGUMENT": f"Page${target}",
            },
            continuation=self.parse_docket_results,
            accumulated_data={
                **accumulated_data,
                "page_number": target_page_number,
            },
            deduplication_key=SkipDeduplicationCheck(),
        )

    # =========================================================================
    # Pending / Decided Search Flow (search_pending, search_decided_after)
    # =========================================================================
    #
    # The Public_search.aspx form defines ``ctl00$cphMain$ddlMainHead``
    # (Primary Subject Matter Classification) with an
    # ``onchange="__doPostBack(...)"`` AutoPostBack handler.  When the
    # Playwright driver iterates the form's default fields and calls
    # ``select_option`` on it — even with its pre-existing empty value
    # — the change event fires a postback that navigates the page and
    # detaches every other form element from the DOM, breaking the
    # subsequent submit click.  Stripping the field from the form
    # before ``form.submit()`` both removes it from the fill loop and
    # from the POST body.  The server is happy to receive the POST
    # without it (the category filter is simply unused).
    _AUTOPOSTBACK_SEARCH_FIELDS: ClassVar[frozenset[str]] = frozenset(
        {"ctl00$cphMain$ddlMainHead"}
    )

    @classmethod
    def _strip_autopostback_fields(cls, form):
        """Return a copy of ``form`` without any AutoPostBack fields.

        See the section comment above for why this is necessary.
        """
        return dataclasses.replace(
            form,
            fields=[
                f
                for f in form.fields
                if f.name not in cls._AUTOPOSTBACK_SEARCH_FIELDS
            ],
        )

    #
    # Both entry points submit the Public_search.aspx form with the
    # DOCKET_ENUMERATE_QUERY alphabet + OR trick so every case matches,
    # then page through one of the two result grids:
    #
    #   cphMain_gvPublicSearchPre   — Pending Cases
    #     Columns: Select | Title | Calendar Date | Argument Number
    #   cphMain_gvPublicSearchPost  — Decided Cases
    #     Columns: Select | Title | Decision Date | Citation
    #
    # These steps mirror parse_search_results: each grid row yields an
    # OpenFiles$N postback to parse_filing_detail at its default
    # priority (9), ahead of this step's pagination requests (16), so
    # detail pages are scraped before the queue advances to the next
    # page of results.

    @step(
        xsd="xsds/courtpass_search_page.xsd",
        await_list=[
            WaitForLoadState("networkidle", timeout=60000),
            WaitForSelector("#Form1", timeout=30000),
        ],
        priority=11,
    )
    def fill_search_pending(
        self,
        page: PageElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[_Yield], None, None]:
        """Submit Public_search.aspx with the OR-alphabet query."""
        form = self._strip_autopostback_fields(
            page.find_form(SEARCH_FORM, "search form")
        )
        yield form.submit(
            data={
                "ctl00$cphMain$txtPartyName": DOCKET_ENUMERATE_QUERY,
                "ctl00$cphMain$ddlFindParty": "FindOR",
            },
            submit_selector="input[name='ctl00$cphMain$btnFind']",
            continuation=self.parse_pending_search_results,
            accumulated_data={
                **accumulated_data,
                "page_number": 1,
            },
            # Follows a SkipDeduplicationCheck'd GET; the POST body
            # matches the decided-after flow's initial submit closely
            # enough that the default hash can collide.
            deduplication_key=SkipDeduplicationCheck(),
        )

    @step(
        xsd="xsds/courtpass_search_page.xsd",
        await_list=[
            WaitForLoadState("networkidle", timeout=60000),
            WaitForSelector("#Form1", timeout=30000),
        ],
        priority=15,
    )
    def fill_search_decided_after(
        self,
        page: PageElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[_Yield], None, None]:
        """Submit Public_search.aspx with an open-ended decision date range.

        Public_search was redesigned in 2026-04 and the Telerik
        RadDatePicker was replaced with plain ``dp*`` text inputs.  No
        hidden ClientState / ISO companion fields remain — just the two
        visible MM/DD/YYYY boxes.
        """
        decided_after_str = accumulated_data["decided_after"]
        start_dt = date.fromisoformat(decided_after_str)
        end_dt = date(9999, 12, 31)
        start_mdy = start_dt.strftime("%m/%d/%Y")
        end_mdy = end_dt.strftime("%m/%d/%Y")

        form = self._strip_autopostback_fields(
            page.find_form(SEARCH_FORM, "search form")
        )
        yield form.submit(
            data={
                "ctl00$cphMain$txtPartyName": DOCKET_ENUMERATE_QUERY,
                "ctl00$cphMain$ddlFindParty": "FindOR",
                "ctl00$cphMain$dpStartDecisionDate": start_mdy,
                "ctl00$cphMain$dpEndDecisionDate": end_mdy,
            },
            submit_selector="input[name='ctl00$cphMain$btnFind']",
            continuation=self.parse_decided_search_results,
            accumulated_data={
                **accumulated_data,
                "page_number": 1,
            },
            # Follows a SkipDeduplicationCheck'd GET; the POST body
            # matches the pending flow's initial submit closely enough
            # that the default hash can collide.
            deduplication_key=SkipDeduplicationCheck(),
        )

    @staticmethod
    def _split_search_grid_rows(
        page: PageElement, table_id: str
    ) -> tuple[list[PageElement], PageElement | None]:
        """Split a Public_search grid's rows into data rows and the pagination row.

        Returns ``(data_rows, pagination_row)``.  ``pagination_row`` is
        the last ``<tr>`` in the grid if it contains ``Page$N`` links,
        otherwise ``None``.
        """
        rows = page.query_xpath(
            f"//table[@id='{table_id}']//tr[position()>1]",
            f"{table_id} rows",
            min_count=0,
        )
        data_rows: list[PageElement] = []
        pagination_row: PageElement | None = None
        for row in rows:
            page_links = row.query_xpath(
                ".//a[contains(@href, 'Page$')]",
                "pagination links",
                min_count=0,
            )
            if page_links:
                pagination_row = row
            else:
                data_rows.append(row)
        return data_rows, pagination_row

    @staticmethod
    def _detect_actual_page_from_row(
        pagination_row: PageElement,
    ) -> int | None:
        """Detect the grid's current page from the pagination row.

        ASP.NET GridView renders the current page as a plain ``<span>``
        inside the pagination row (all other pages are hyperlinks).
        """
        spans = pagination_row.query_xpath(
            ".//span[not(ancestor::a)]",
            "current page indicator",
            min_count=0,
        )
        for span in spans:
            text = span.text_content().strip()
            if text.isdigit():
                return int(text)
        return None

    @classmethod
    def _paginate_search_grid(
        cls,
        page: PageElement,
        pagination_row: PageElement | None,
        next_page: int,
        grid_control: str,
        continuation,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[_Yield], None, None]:
        """Navigate to the next page of a Public_search grid.

        If ``next_page`` is visible, jump directly.  Otherwise shift
        the pagination window forward via the highest visible page
        (the ``...`` ellipsis) and keep targeting ``next_page`` from
        the new window.

        Returns without yielding when the grid has no forward links
        (``max(visible) <= actual_page``), i.e. we've reached the
        site's last page.  This guards against an infinite loop when
        the server caps pagination and the window never advances past
        the current page.
        """
        if pagination_row is None:
            return

        visible = cls._extract_visible_page_numbers(pagination_row)
        if not visible:
            return

        # Last-page check: if no visible link leads forward of the
        # current page, we're stuck at the end — return rather than
        # clicking backwards into an oscillation.
        actual_page = cls._detect_actual_page_from_row(pagination_row)
        if actual_page is not None and max(visible) <= actual_page:
            return

        if next_page in visible:
            target = next_page
            target_page_number = next_page
        elif any(p > next_page for p in visible):
            target = min(p for p in visible if p >= next_page)
            target_page_number = target
        else:
            # next_page is beyond the window — click the ellipsis
            # (highest visible link) to advance, keep targeting next_page.
            target = max(visible)
            target_page_number = next_page

        form = page.find_form(SEARCH_RESULTS_FORM, "search pagination")
        yield form.submit(
            data={
                "__EVENTTARGET": grid_control,
                "__EVENTARGUMENT": f"Page${target}",
            },
            continuation=continuation,
            accumulated_data={
                **accumulated_data,
                "page_number": target_page_number,
            },
            deduplication_key=SkipDeduplicationCheck(),
        )

    @step(
        xsd="xsds/courtpass_search_page.xsd",
        await_list=[
            WaitForLoadState("networkidle", timeout=30000),
            WaitForSelector("#Form2", timeout=15000),
        ],
        priority=12,
    )
    def parse_pending_search_results(
        self,
        page: PageElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[_Yield], None, None]:
        """Parse the Pending Cases grid and follow each row into filing detail.

        For every row, yields an ``OpenFiles$N`` postback targeting
        ``parse_filing_detail`` — which runs at its default priority
        (9), ahead of this step's pagination requests (priority 16),
        so detail pages are fully scraped before the queue advances to
        the next page of results.  Pagination is then yielded to
        continue the walk.
        """
        expected_page = accumulated_data.get("page_number", 1)
        data_rows, pagination_row = self._split_search_grid_rows(
            page, SEARCH_PENDING_TABLE_ID
        )

        # If the pending grid isn't on the page at all, stop.  This can
        # happen when the server drops context after many pages.
        if not data_rows and pagination_row is None:
            return

        for i, row in enumerate(data_rows):
            cells = row.query_xpath("td", "row cells", min_count=0)
            if len(cells) < 4:
                continue
            case_name = self._normalize_whitespace(cells[1].text_content())
            if not case_name:
                continue
            calendar_date_str = cells[2].text_content().strip()
            argument_number = cells[3].text_content().strip() or None

            # New (2026-04) pending-results grid has named submit buttons
            # (id ``cphMain_gvPublicSearchPre_btnSelect_{i}``).
            select_buttons = row.query_xpath(
                ".//input[contains(@id, 'btnSelect')]",
                "select button",
                min_count=0,
            )
            aria_case_info = (
                select_buttons[0].get_attribute("aria-label")
                if select_buttons
                else None
            )

            form = page.find_form(SEARCH_RESULTS_FORM, "pending results form")
            yield form.submit(
                data={},
                submit_selector=f"#cphMain_gvPublicSearchPre_btnSelect_{i}",
                continuation=self.parse_filing_detail,
                accumulated_data={
                    **accumulated_data,
                    "case_title_from_search": case_name,
                    "argument_date_from_search": calendar_date_str,
                    "decision_date_from_search": "",
                    "argument_number_from_search": argument_number,
                    "search_page": expected_page,
                    "search_row": i,
                    "aria_case_info": aria_case_info,
                },
                deduplication_key=SkipDeduplicationCheck(),
            )

        yield from self._paginate_search_grid(
            page,
            pagination_row,
            expected_page + 1,
            SEARCH_PENDING_GRID,
            self.parse_pending_search_results,
            accumulated_data,
        )

    @step(
        xsd="xsds/courtpass_search_page.xsd",
        await_list=[
            WaitForLoadState("networkidle", timeout=30000),
            WaitForSelector("#Form2", timeout=15000),
        ],
        priority=16,
    )
    def parse_decided_search_results(
        self,
        page: PageElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[_Yield], None, None]:
        """Parse the Decided Cases grid and follow each row into filing detail.

        For every row, yields an ``OpenFiles$N`` postback targeting
        ``parse_filing_detail`` — which runs at its default priority
        (9), ahead of this step's pagination requests (priority 16),
        so detail pages are fully scraped before the queue advances to
        the next page of results.  Rows whose decision date falls
        before ``decided_after`` are skipped as a guard against the
        server ignoring the date filter.  Pagination is then yielded
        to continue the walk.
        """
        expected_page = accumulated_data.get("page_number", 1)
        data_rows, pagination_row = self._split_search_grid_rows(
            page, SEARCH_DECIDED_TABLE_ID
        )

        if not data_rows and pagination_row is None:
            return

        decided_after_str = accumulated_data.get("decided_after")
        decided_after = (
            date.fromisoformat(decided_after_str)
            if decided_after_str
            else None
        )

        for i, row in enumerate(data_rows):
            cells = row.query_xpath("td", "row cells", min_count=0)
            if len(cells) < 4:
                continue
            case_name = self._normalize_whitespace(cells[1].text_content())
            if not case_name:
                continue
            decision_date_str = cells[2].text_content().strip()
            decision_date = self._parse_date_mdy(decision_date_str)
            citation = self._normalize_whitespace(cells[3].text_content())

            if (
                decided_after
                and decision_date
                and decision_date < decided_after
            ):
                continue

            # New (2026-04) decided-results grid has named submit buttons
            # (id ``cphMain_gvPublicSearchPost_btnSelect_{i}``).
            select_buttons = row.query_xpath(
                ".//input[contains(@id, 'btnSelect')]",
                "select button",
                min_count=0,
            )
            aria_case_info = (
                select_buttons[0].get_attribute("aria-label")
                if select_buttons
                else None
            )

            form = page.find_form(SEARCH_RESULTS_FORM, "decided results form")
            yield form.submit(
                data={},
                submit_selector=f"#cphMain_gvPublicSearchPost_btnSelect_{i}",
                continuation=self.parse_filing_detail,
                accumulated_data={
                    **accumulated_data,
                    "case_title_from_search": case_name,
                    "argument_date_from_search": "",
                    "decision_date_from_search": decision_date_str,
                    "citation_from_search": citation or None,
                    "search_page": expected_page,
                    "search_row": i,
                    "aria_case_info": aria_case_info,
                },
                deduplication_key=SkipDeduplicationCheck(),
            )

        yield from self._paginate_search_grid(
            page,
            pagination_row,
            expected_page + 1,
            SEARCH_DECIDED_GRID,
            self.parse_decided_search_results,
            accumulated_data,
        )


Site = NYCourtPassScraper
