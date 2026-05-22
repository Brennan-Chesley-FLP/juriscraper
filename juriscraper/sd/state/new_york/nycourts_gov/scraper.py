"""New York Court of Appeals Docket Scraper (Court-PASS).

This module scrapes docket and filing data from the Court-PASS system
at courtpass.nycourts.gov. The site is behind Cloudflare managed challenge
and uses ASP.NET WebForms with ViewState-driven postback navigation,
requiring a PlaywrightDriver.

Entry points::

    - @entry search_pending()
    - @entry search_decided_after(decided_after: date)
    - @entry get_docket(docket_number: str)
    - @entry browse(argument_date?: DateRange, decision_date?: DateRange)
    - @entry browse_by_case_date(DateRange)
    - @entry enumerate_dockets(argument_date?: DateRange, decision_date?: DateRange)
    - @entry enumerate_dockets_from_page(start_page, argument_date?: DateRange, decision_date?: DateRange)

Search Flow — pending cases (emits NYCourtPassCase)::

    1. search_pending → Public_search.aspx
    2. fill_search_pending → submit OR-alphabet party-name query
    3. parse_pending_search_results → walk gvPublicSearchPre rows
    4. parse_filing_detail → emit NYCourtPassCase, download files

Search Flow — decided cases (emits NYCourtPassCase)::

    1. search_decided_after → Public_search.aspx
    2. fill_search_decided_after → submit decision-date range
    3. parse_decided_search_results → walk gvPublicSearchPost rows
    4. parse_filing_detail → emit NYCourtPassCase, download files

Browse Flow (emits NYCourtPassCase)::

    1. browse / browse_by_case_date → Public_Browse.aspx
    2. parse_browse_page / parse_browse_date_page → submit form
    3. parse_browse_results → walk gvResults rows
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
import urllib.parse
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
from pydantic import BaseModel
from pyrate_limiter import Duration, Rate

from .models import (
    NYCourtPassAttorney,
    NYCourtPassCase,
    NYCourtPassDocket,
    NYCourtPassDocketEntry,
    NYCourtPassFile,
    NYCourtPassOralArgument,
    NYDocketFailure,
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
    NYCourtPassCase
    | NYCourtPassDocket
    | NYCourtPassFile
    | NYCourtPassOralArgument
    | NYDocketFailure
)

# Court-PASS serves oral-argument webcasts and audio as an ASX (Advanced
# Stream Redirector) XML stub rather than a PDF: the gvFiles download
# button replies with ``Content-Disposition: Attachment`` +
# ``application/octet-stream`` and a ~200-byte XML body whose ``<ref
# href>`` points at ``mms://media.courts.state.ny.us/...wmv`` — the same
# path is reachable over plain HTTP (the BigIP front-end 302s to an
# Azure blob). Rows whose file_name matches ``ORAL_ARGUMENT_MEDIA_RE``
# are routed through ``handle_oral_argument_download`` so the stub can
# be parsed and a ``NYCourtPassOralArgument`` record emitted with the
# resolved ``.wmv`` URL, deferring the actual recording download to an
# out-of-band process.
ASX_MEDIA_HOST = "media.courts.state.ny.us"
ASX_REF_HREF_RE = re.compile(
    r"<ref\b[^>]*\bhref\s*=\s*[\"']([^\"']+)[\"']",
    re.IGNORECASE,
)
ORAL_ARGUMENT_MEDIA_RE = re.compile(
    r"Oral-Argument-(Webcast|Audio)",
    re.IGNORECASE,
)

# Search string that matches every case on the docket via "Find Any Words (OR)"
DOCKET_ENUMERATE_QUERY = (
    "a b c d e f g h i j k l m n o p q r s t u v w x y z 0 1 2 3 4 5 6 7 8 9"
)

# Cap on how many times parse_docket_filing_detail will re-walk via a
# docket-number search to recover from a bttnDetails caption mismatch.
MAX_FILING_DETAIL_RECOVERY = 2


class NetDocketTarget(BaseModel):
    """A single target case for the ``net_docket`` entry point.

    The grid filter matches rows by ``aria_case_info``; the docket-detail
    filter then verifies the resulting docket number, which disambiguates
    aria collisions (e.g. the "Matter of Anonymous" cluster maps a single
    aria-label to 9+ distinct dockets).
    """

    aria_case_info: str
    docket_number: str


class NetDocketTargets(BaseModel):
    """Wrapper around a list of ``NetDocketTarget`` for entry params."""

    targets: list[NetDocketTarget]


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
        DriverRequirement.STRICTLY_SERIAL,
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
    def _canonicalize_caption(text: str) -> str:
        """Normalize a case caption for cross-page substring comparison.

        The docket-detail Title cell for consolidated cases concatenates
        every party-pair with literal ``<br />`` text (the source HTML
        double-encodes the tag) or long runs of dashes/underscores as
        visual separators. The filing-detail caption shows only one
        pair. Strip those artifacts so the filing caption can be matched
        as a contiguous substring of the docket caption.
        """
        if not text:
            return ""
        text = re.sub(r"<br\s*/?>", " ", text)
        text = re.sub(r"&lt;br\s*/?&gt;", " ", text)
        text = re.sub(r"[-_]{3,}", " ", text)
        return " ".join(text.split())

    @staticmethod
    def _caption_substring_match(filing: str, docket: str) -> bool:
        """Whitespace-insensitive substring check between two captions.

        The filing-detail page wraps the case caption in three
        ``<div class="case-caption-line">`` elements (party / "v." /
        party). For captions that don't follow the implicit
        Plaintiff-v-Defendant template — e.g. ``Matter of X v Y. (App.
        Div. No. NNNNN)`` — the template injects the literal ``v.``
        between unrelated fragments, so our text-node-joining extractor
        produces ``"(App. Di v. No. NNNNN)"`` while the docket-detail
        page (which uses a single ``<dd>``) renders it as ``"(App. Div.
        No. NNNNN)"``. Strip all whitespace before the substring check
        so this one-space discrepancy doesn't trigger a false-mismatch.
        Genuine drift (e.g. different App. Div. numbers) remains
        detectable because the underlying tokens still differ.
        """
        if not filing or not docket:
            return False
        return re.sub(r"\s+", "", filing) in re.sub(r"\s+", "", docket)

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

    def _emit_docket_failure(
        self,
        accumulated_data: dict,
        *,
        observed_filing_caption: str | None,
        failed_docket_search: bool,
    ) -> Generator[ScraperYield[_Yield], None, None]:
        """Yield a NYDocketFailure built from ``deferred_docket`` (the
        docket-detail payload staged in parse_docket_detail) with fallback
        to top-level accumulated_data when individual fields are missing.

        Used from three sites: filing-detail caption mismatch exhausting
        recovery, recovery search returning no rows, and recovery search
        receiving a malformed docket number it cannot submit.
        """
        deferred = accumulated_data.get("deferred_docket") or {}
        yield ParsedData(
            data=NYDocketFailure(
                temp_case_id=(
                    deferred.get("temp_case_id")
                    or accumulated_data.get("temp_case_id", "")
                ),
                docket_number=(
                    deferred.get("docket_number")
                    or accumulated_data.get("docket_number")
                ),
                case_name=deferred.get("case_name") or "",
                argument_date=self._parse_date_mdy(
                    deferred.get("argument_date_str") or ""
                ),
                docket_entries=self._build_docket_entries(
                    deferred.get("docket_entries") or []
                ),
                attorneys=self._build_attorneys(
                    deferred.get("attorneys") or []
                ),
                search_page=(
                    deferred.get("search_page")
                    or accumulated_data.get("search_page")
                ),
                search_row=(
                    deferred.get("search_row")
                    if deferred.get("search_row") is not None
                    else accumulated_data.get("search_row")
                ),
                aria_case_info=(
                    deferred.get("aria_case_info")
                    or accumulated_data.get("aria_case_info")
                ),
                observed_filing_caption=observed_filing_caption,
                recovery_attempts=accumulated_data.get(
                    "filing_detail_recovery_attempts", 0
                ),
                failed_docket_search=failed_docket_search,
            )
        )

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
                "coa_site_source": "search_pending",
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
                "coa_site_source": "search_decided",
                "decided_after": decided_after.isoformat(),
            },
            priority=15,
            # SEARCH_URL is shared with search_pending; skip the default
            # URL-based dedup so both entry points can coexist.
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
        total_files = len(files_info)
        files = [
            NYCourtPassFile(
                file_name=f["file_name"],
                file_index=f.get("row_index"),
                document_number=total_files - i,
                available=f.get("available", True),
                temp_case_id=temp_case_id,
            )
            for i, f in enumerate(files_info)
        ]
        document_numbers_by_row = {
            f["row_index"]: total_files - i for i, f in enumerate(files_info)
        }

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
                search_grid=accumulated_data.get("search_grid"),
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
            is_oral_argument_media = bool(
                ORAL_ARGUMENT_MEDIA_RE.search(file_info["file_name"])
            )
            yield form.submit(
                submit_selector=f"input[name='{button_name}']",
                continuation=(
                    self.handle_oral_argument_download
                    if is_oral_argument_media
                    else self.handle_file_download
                ),
                accumulated_data={
                    "temp_case_id": temp_case_id,
                    "file_name": file_info["file_name"],
                    "file_index": file_info["row_index"],
                    "document_number": document_numbers_by_row.get(
                        file_info["row_index"]
                    ),
                },
                bypass_rate_limit=True,
                priority=0,
                archive=True,
                expected_type="asx" if is_oral_argument_media else "pdf",
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

        Each row has three columns: Select button, Title, Argument Date.
        Decision date is not in the grid; it's only available on the
        filing detail page. Pages have 10 results. Pagination links use
        __doPostBack.

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

        # Pick rows by content, not by ``position()`` — the 2026-04
        # redesign separated the column header into ``<thead>``, so a
        # per-parent ``position()>1`` predicate would silently drop the
        # first ``<tbody>`` row (i.e., btnSelect_0 on every page).
        data_rows = list(
            page.query_xpath(
                "//table[contains(@id, 'gvResults')]"
                "//tr[.//input[contains(@id, 'btnSelect')]]",
                "docket data rows",
                min_count=0,
            )
        )
        pagination_rows = page.query_xpath(
            "//table[contains(@id, 'gvResults')]"
            "//tr[.//a[contains(@href, 'Page$')]]",
            "docket pagination rows",
            min_count=0,
        )
        pagination_row = pagination_rows[0] if pagination_rows else None

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
        # ASP.NET pagination links beyond the true last page silently
        # clamp: requesting Page$N+1 where N is the last page returns
        # page N again, but the rendered pagination row still shows
        # forward links for N+1, N+2, ... so the naive recovery would
        # resubmit Page$N+1 forever.  Bound the loop.
        MAX_PAGINATION_RECOVERY_ATTEMPTS = 3
        actual_page = self._detect_actual_page(page)
        if actual_page is not None and actual_page != expected_page:
            pagination_attempts = accumulated_data.get(
                "pagination_recovery_attempts", 0
            )
            if pagination_attempts >= MAX_PAGINATION_RECOVERY_ATTEMPTS:
                logger.warning(
                    "Docket pagination: giving up after %d recovery "
                    "attempts navigating from actual page %d to expected "
                    "page %d (server likely clamped past last page)",
                    pagination_attempts,
                    actual_page,
                    expected_page,
                )
                return
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

        for i, row in enumerate(data_rows):
            cells = row.query_xpath("td", "row cells", min_count=0)
            if len(cells) < 3:
                continue

            # cells[0]=Select button, cells[1]=Title, cells[2]=Argument Date.
            case_title_from_grid = self._normalize_whitespace(
                cells[1].text_content()
            )
            argument_date_from_grid = cells[2].text_content().strip()

            # Skip dockets whose argument date is outside the requested
            # range. Decision date isn't in the grid; it's enforced later
            # in parse_docket_filing_detail.
            if not self._date_in_range(
                self._parse_date_mdy(argument_date_from_grid),
                arg_start,
                arg_end,
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
                    "case_title_from_search": case_title_from_grid,
                    "argument_date_from_grid": argument_date_from_grid,
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
        yield from self._process_docket_detail_page(page, accumulated_data)

    def _process_docket_detail_page(
        self,
        page: PageElement,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[_Yield], None, None]:
        """Shared docket-detail handling: extract fields, emit (or defer)
        NYCourtPassDocket, and submit the bttnDetails postback to load
        filing detail.

        Called from parse_docket_detail (after a normal btnSelect click)
        and from parse_docket_recovery_select_row when Court-PASS
        short-circuits a single-result docket-number search directly to
        the docket-detail page.
        """
        fields = self._extract_docket_detail_fields(page)
        # On the short-circuit response, the docket number is rendered
        # without its APL/CTQ/JCR prefix, so the extractor's regex
        # misses it. Fall back to what the original chain captured.
        docket_number = fields["docket_number"] or accumulated_data.get(
            "docket_number"
        )

        # Some older cases render an empty Argument Date <dd> on the
        # docket-detail page even when the docket grid clearly showed
        # the date.  Fall back to the grid's argument-date column when
        # the detail page omits it.
        argument_date = self._parse_date_mdy(
            fields["argument_date_str"]
            or accumulated_data.get("argument_date_from_grid")
            or ""
        )

        # The docket grid carries no decision date, so when a decision
        # date range is configured we defer NYCourtPassDocket emission
        # until parse_docket_filing_detail can confirm the date.
        dec_start = accumulated_data.get("decision_date_start")
        defer_docket = bool(dec_start)

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
            "case_name_from_docket_detail": self._canonicalize_caption(
                fields["case_name"] or ""
            ),
        }
        if defer_docket:
            # Pass raw docket fields so parse_docket_filing_detail
            # can emit the docket after confirming the decision date.
            filing_detail_data["deferred_docket"] = {
                "temp_case_id": accumulated_data.get("temp_case_id", ""),
                "docket_number": docket_number,
                "case_name": fields["case_name"],
                "argument_date_str": (
                    fields["argument_date_str"]
                    or accumulated_data.get("argument_date_from_grid")
                ),
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

        # The bttnDetails postback occasionally returns the filing detail
        # for a neighboring case: it reads the server's ``session.currentCase``
        # to render lbDetails2, and that state can drift from what
        # btnSelect_N set. Compare the caption from the preceding
        # docket-detail page; if it doesn't agree, recover by re-walking
        # via a docket-number search (which forces a single-row grid and
        # re-pins session state). Plain TransientException retry never
        # fixes this because it re-submits bttnDetails alone.
        #
        # Consolidated dockets concatenate multiple captions on the
        # docket-detail page but show only one on the filing-detail
        # page, so accept any contiguous substring match.
        docket_case_name = accumulated_data.get("case_name_from_docket_detail")
        filing_case_name = self._canonicalize_caption(case_name)
        if (
            docket_case_name
            and filing_case_name
            and filing_case_name != "Unknown"
            and not self._caption_substring_match(
                filing_case_name, docket_case_name
            )
        ):
            recovery_attempts = accumulated_data.get(
                "filing_detail_recovery_attempts", 0
            )
            if recovery_attempts >= MAX_FILING_DETAIL_RECOVERY:
                logger.warning(
                    "parse_docket_filing_detail: caption mismatch "
                    "persisted after %d recovery attempts for docket "
                    "%s; emitting NYDocketFailure (docket-detail "
                    "showed %r, filing-detail shows %r)",
                    recovery_attempts,
                    accumulated_data.get("docket_number"),
                    docket_case_name,
                    filing_case_name,
                )
                yield from self._emit_docket_failure(
                    accumulated_data,
                    observed_filing_caption=filing_case_name,
                    failed_docket_search=False,
                )
                return
            logger.info(
                "parse_docket_filing_detail: caption mismatch for "
                "docket %s (attempt %d); re-walking via docket-number "
                "search",
                accumulated_data.get("docket_number"),
                recovery_attempts + 1,
            )
            # Drop ``case_name_from_docket_detail`` (parse_docket_detail
            # will repopulate it on re-entry) but keep ``deferred_docket``
            # as a fallback for NYDocketFailure if the recovery's
            # docket-number search itself fails.
            recovery_ad = {
                k: v
                for k, v in accumulated_data.items()
                if k != "case_name_from_docket_detail"
            }
            recovery_ad["filing_detail_recovery_attempts"] = (
                recovery_attempts + 1
            )
            yield Request(
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url=DOCKET_URL,
                ),
                continuation=self.parse_docket_recovery_fill_search,
                accumulated_data=recovery_ad,
                deduplication_key=SkipDeduplicationCheck(),
            )
            return

        # Fall back to the docket-grid argument date when the filing
        # detail page omits it (matches the docket-detail fallback in
        # ``_process_docket_detail_page``).
        argument_date = self._parse_date_mdy(
            fields["argument_date_str"]
            or accumulated_data.get("argument_date_from_grid")
            or ""
        )
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

        total_files = len(files_info)
        files = [
            NYCourtPassFile(
                file_name=f["file_name"],
                file_index=f.get("row_index"),
                document_number=total_files - i,
                available=f.get("available", True),
                temp_case_id=temp_case_id,
                docket_number=docket_number or None,
            )
            for i, f in enumerate(files_info)
        ]
        document_numbers_by_row = {
            f["row_index"]: total_files - i for i, f in enumerate(files_info)
        }

        yield ParsedData(
            data=NYCourtPassCase(
                temp_case_id=temp_case_id,
                case_name=case_name,
                case_name_abbrev=accumulated_data.get("case_title_from_search")
                or None,
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
                search_grid=accumulated_data.get("search_grid"),
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
            is_oral_argument_media = bool(
                ORAL_ARGUMENT_MEDIA_RE.search(file_info["file_name"])
            )
            yield form.submit(
                submit_selector=f"input[name='{button_name}']",
                continuation=(
                    self.handle_oral_argument_download
                    if is_oral_argument_media
                    else self.handle_file_download
                ),
                accumulated_data={
                    "temp_case_id": temp_case_id,
                    "docket_number": docket_number,
                    "file_name": file_info["file_name"],
                    "file_index": file_info["row_index"],
                    "document_number": document_numbers_by_row.get(
                        file_info["row_index"]
                    ),
                },
                bypass_rate_limit=True,
                priority=0,
                archive=True,
                expected_type="asx" if is_oral_argument_media else "pdf",
                deduplication_key=name_sha,
            )

    @step(
        xsd="xsds/courtpass_docket_page.xsd",
        await_list=[
            WaitForLoadState("networkidle", timeout=60000),
            WaitForSelector("#Form2", timeout=30000),
        ],
        priority=2,
    )
    def parse_docket_recovery_fill_search(
        self,
        page: PageElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[_Yield], None, None]:
        """Fill the Docket search form with the target docket number.

        Recovery step for parse_docket_filing_detail caption mismatches.
        Mirrors ``parse_docket_page`` but routes the result to
        ``parse_docket_recovery_select_row`` so we rejoin the main
        enumerate_dockets chain (preserving accumulated_data such as
        ``temp_case_id`` and ``case_title_from_search``).
        """
        docket_number = accumulated_data["docket_number"]
        parts = docket_number.split("-")
        if len(parts) != 3:
            logger.warning(
                "parse_docket_recovery_fill_search: cannot split "
                "docket_number %r into prefix/year/number; emitting "
                "NYDocketFailure",
                docket_number,
            )
            yield from self._emit_docket_failure(
                accumulated_data,
                observed_filing_caption=None,
                failed_docket_search=True,
            )
            return
        form = page.find_form(DOCKET_FORM, "docket form")
        yield form.submit(
            data={
                "ctl00$cphMain$ddlCaseId": parts[0],
                "ctl00$cphMain$tbCaseIdYear": parts[1],
                "ctl00$cphMain$tbCaseIdNum": parts[2],
            },
            submit_selector="input[name='ctl00$cphMain$btnFind']",
            continuation=self.parse_docket_recovery_select_row,
            accumulated_data=accumulated_data,
            deduplication_key=SkipDeduplicationCheck(),
        )

    @step(
        xsd="xsds/courtpass_docket_page.xsd",
        await_list=[
            WaitForLoadState("networkidle", timeout=30000),
            WaitForSelector("#Form2", timeout=15000),
        ],
        priority=2,
    )
    def parse_docket_recovery_select_row(
        self,
        page: PageElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[_Yield], None, None]:
        """Click btnSelect_0 on a single-row docket-number search result.

        Recovery step for parse_docket_filing_detail caption mismatches.
        The docket-number search returns at most one matching row, so
        clicking btnSelect_0 unambiguously pins the server's
        ``session.currentCase`` to the case we want. Continues into the
        existing ``parse_docket_detail`` so the rest of the chain runs
        normally.

        Court-PASS may also short-circuit when the search has exactly one
        match, returning the docket-detail page directly without an
        intervening grid; we detect that via the CallDetails button on
        the docket-detail span and route into the shared
        ``_process_docket_detail_page`` helper without re-clicking.
        """
        data_rows = page.query_xpath(
            "//table[contains(@id, 'gvResults')]"
            "//tr[.//input[contains(@id, 'btnSelect')]]",
            "recovery docket data rows",
            min_count=0,
        )
        if not data_rows:
            # No grid — either we're on a "No Matching Cases" page or
            # Court-PASS short-circuited to the docket-detail page.
            # The CallDetails button is only rendered when the detail
            # span is populated, so it cleanly distinguishes the two.
            call_details_button = page.query_xpath(
                "//span[@id='cphMain_lbDetails']"
                "//button[contains(@onclick, 'CallDetails')]",
                "CallDetails button on short-circuit detail",
                min_count=0,
            )
            if call_details_button:
                logger.info(
                    "parse_docket_recovery_select_row: Court-PASS "
                    "short-circuited the docket-number search for %s "
                    "to the detail page; continuing into bttnDetails "
                    "postback directly",
                    accumulated_data.get("docket_number"),
                )
                yield from self._process_docket_detail_page(
                    page, accumulated_data
                )
                return
            logger.warning(
                "parse_docket_recovery_select_row: docket-number "
                "search returned no rows for %r; emitting "
                "NYDocketFailure(failed_docket_search=True)",
                accumulated_data.get("docket_number"),
            )
            yield from self._emit_docket_failure(
                accumulated_data,
                observed_filing_caption=None,
                failed_docket_search=True,
            )
            return
        form = page.find_form(DOCKET_FORM, "recovery docket results form")
        yield form.submit(
            data={},
            submit_selector="#cphMain_gvResults_btnSelect_0",
            continuation=self.parse_docket_detail,
            accumulated_data=accumulated_data,
            deduplication_key=SkipDeduplicationCheck(),
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
                document_number=accumulated_data.get("document_number"),
                local_path=local_filepath,
                available=True,
                temp_case_id=accumulated_data.get("temp_case_id"),
                docket_number=accumulated_data.get("docket_number"),
            )
        )

    @step
    def handle_oral_argument_download(
        self,
        local_filepath: str | None,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[_Yield], None, None]:
        """Resolve an oral-argument ASX redirect stub.

        Court-PASS serves Oral-Argument-Webcast / Oral-Argument-Audio
        rows as a tiny ASX (Advanced Stream Redirector) XML stub with
        ``Content-Disposition: Attachment``, so the file lands on disk
        like any other archive download. This step parses the
        ``mms://media.courts.state.ny.us/...wmv`` reference out of the
        stub and emits a ``NYCourtPassOralArgument`` recording the
        stub's on-disk path alongside the resolved HTTP URL of the
        ``.wmv``. The actual recording download is deferred to an
        out-of-band process.
        """
        parsed = self._parse_asx_redirect_stub(local_filepath)
        if parsed is None:
            logger.warning(
                "handle_oral_argument_download: could not parse ASX stub at %r "
                "for file_name=%r; skipping wmv emission",
                local_filepath,
                accumulated_data.get("file_name"),
            )
            return

        _, resolved_url = parsed
        assert local_filepath is not None  # implied by parsed is not None
        yield ParsedData(
            data=NYCourtPassOralArgument(
                asx_url=local_filepath,
                wmv_url=resolved_url,
                filename=accumulated_data.get("file_name", ""),
                temp_case_id=accumulated_data.get("temp_case_id"),
                docket_number=accumulated_data.get("docket_number"),
            )
        )

    @staticmethod
    def _parse_asx_redirect_stub(
        local_filepath: str | None,
    ) -> tuple[str, str] | None:
        """Parse an ASX redirect stub at ``local_filepath``.

        Returns ``(original_mms_href, resolved_http_url)`` if the file
        is a recognizable ASX stub pointing at
        ``mms://media.courts.state.ny.us/...``, otherwise ``None``. The
        check is deliberately conservative — file extension AND content
        prefix AND the expected media host must all match — so a stray
        non-ASX archive never gets misinterpreted as a redirect.
        """
        if not local_filepath or not local_filepath.lower().endswith(".asx"):
            return None
        try:
            with open(local_filepath, "rb") as f:
                head = f.read(8192)
        except OSError:
            return None
        text = head.decode("utf-8", errors="replace").lstrip()
        if not text.lower().startswith("<asx"):
            return None
        match = ASX_REF_HREF_RE.search(text)
        if not match:
            return None
        href = match.group(1).strip()
        parsed = urllib.parse.urlsplit(href)
        if parsed.scheme.lower() != "mms":
            return None
        if parsed.hostname != ASX_MEDIA_HOST:
            return None
        quoted_path = urllib.parse.quote(parsed.path, safe="/%")
        resolved = urllib.parse.urlunsplit(
            ("http", parsed.netloc, quoted_path, parsed.query, parsed.fragment)
        )
        return href, resolved

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
        """Fill the Docket search form with an APL/CTQ/JCR number and submit.

        The 2026-04 redesign replaced the old single ``txtAPL`` field
        (and an even older ``txtPrefix``/``txtYear``/``txtNumber``
        variant) with a case-type dropdown + year + number trio, and
        renamed the submit button from ``bttnFind`` to ``btnFind``.
        """
        docket_number = accumulated_data["docket_number"]
        parts = docket_number.split("-")
        if len(parts) != 3:
            logger.warning(
                "parse_docket_page: cannot split docket_number %r "
                "into prefix/year/number",
                docket_number,
            )
            return
        form = page.find_form(DOCKET_FORM, "docket form")
        yield form.submit(
            data={
                "ctl00$cphMain$ddlCaseId": parts[0],
                "ctl00$cphMain$tbCaseIdYear": parts[1],
                "ctl00$cphMain$tbCaseIdNum": parts[2],
            },
            submit_selector="input[name='ctl00$cphMain$btnFind']",
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

        Select the first (and only) matching result to view docket detail.
        The 2026-04 redesign moved row detection to a named submit button
        (``cphMain_gvResults_btnSelect_0``); the old ``OpenFiles$N``
        postback shape is now rejected by ASP.NET event validation.

        Court-PASS may also short-circuit when the search has exactly one
        match, returning the docket-detail page directly without an
        intervening grid; we detect that via the CallDetails button on
        the docket-detail span and route into the shared
        ``_process_docket_detail_for_entry`` helper without re-clicking.
        """
        data_rows = page.query_xpath(
            "//table[contains(@id, 'gvResults')]"
            "//tr[.//input[contains(@id, 'btnSelect')]]",
            "docket results data rows",
            min_count=0,
        )
        if not data_rows:
            call_details_button = page.query_xpath(
                "//span[@id='cphMain_lbDetails']"
                "//button[contains(@onclick, 'CallDetails')]",
                "CallDetails button on short-circuit detail",
                min_count=0,
            )
            if call_details_button:
                logger.info(
                    "parse_docket_number_results: Court-PASS "
                    "short-circuited the docket-number search for %s "
                    "to the detail page; continuing into bttnDetails "
                    "postback directly",
                    accumulated_data.get("docket_number"),
                )
                yield from self._process_docket_detail_for_entry(
                    page, accumulated_data
                )
                return
            logger.warning(
                "parse_docket_number_results: no rows for docket %r",
                accumulated_data.get("docket_number"),
            )
            return

        form = page.find_form(DOCKET_FORM, "docket results form")
        yield form.submit(
            data={},
            submit_selector="#cphMain_gvResults_btnSelect_0",
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
        yield from self._process_docket_detail_for_entry(
            page, accumulated_data
        )

    def _process_docket_detail_for_entry(
        self,
        page: PageElement,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[_Yield], None, None]:
        """Shared docket-detail handling for the get_docket entry point.

        Called from parse_docket_detail_for_entry (after a normal
        btnSelect_0 click) and from parse_docket_number_results when
        Court-PASS short-circuits a single-result docket-number search
        directly to the docket-detail page.
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

        # Trigger the bttnDetails postback to load the filing detail
        # into cphMain_lbDetails2. The button is ``display:none`` so we
        # can't click it via submit_selector; submit via __EVENTTARGET
        # instead, matching the enumerate_dockets flow.
        form = page.find_form(DOCKET_FORM, "docket detail form")
        yield form.submit(
            data={
                "__EVENTTARGET": "ctl00$cphMain$bttnDetails",
                "__EVENTARGUMENT": "",
            },
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
            WaitForSelector("#cphMain_lbDetails2", timeout=15000),
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

        # The bttnDetails postback populates cphMain_lbDetails2 (the
        # docket-detail section in cphMain_lbDetails stays present from
        # the prior render). Extract from lbDetails2 so we get the
        # filing-side fields (decision date, issues, citation, files).
        fields = self._extract_detail_fields(
            page, detail_span_id="cphMain_lbDetails2"
        )

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
        total_files = len(files_info)
        files = [
            NYCourtPassFile(
                file_name=f["file_name"],
                file_index=f.get("row_index"),
                document_number=total_files - i,
                available=f.get("available", True),
                temp_case_id=temp_case_id,
            )
            for i, f in enumerate(files_info)
        ]
        document_numbers_by_row = {
            f["row_index"]: total_files - i for i, f in enumerate(files_info)
        }

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
                search_grid=accumulated_data.get("search_grid"),
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
            is_oral_argument_media = bool(
                ORAL_ARGUMENT_MEDIA_RE.search(file_info["file_name"])
            )
            yield form.submit(
                submit_selector=f"input[name='{button_name}']",
                continuation=(
                    self.handle_oral_argument_download
                    if is_oral_argument_media
                    else self.handle_file_download
                ),
                accumulated_data={
                    "temp_case_id": temp_case_id,
                    "file_name": file_info["file_name"],
                    "file_index": file_info["row_index"],
                    "document_number": document_numbers_by_row.get(
                        file_info["row_index"]
                    ),
                },
                archive=True,
                expected_type="asx" if is_oral_argument_media else "pdf",
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

        # Pick rows by content; see parse_docket_results for the
        # ``position()>1`` pitfall on the new ``<thead>``/``<tbody>`` shape.
        data_rows = list(
            page.query_xpath(
                "//table[contains(@id, 'gvResults')]"
                "//tr[.//input[contains(@id, 'btnSelect')]]",
                "browse data rows",
                min_count=0,
            )
        )
        pagination_rows = page.query_xpath(
            "//table[contains(@id, 'gvResults')]"
            "//tr[.//a[contains(@href, 'Page$')]]",
            "browse pagination rows",
            min_count=0,
        )
        pagination_row = pagination_rows[0] if pagination_rows else None

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
        # See parse_docket_results: ASP.NET pagination links past the
        # true last page silently clamp, so the naive recovery would
        # loop forever.  Bound the loop.
        MAX_PAGINATION_RECOVERY_ATTEMPTS = 3
        actual_page = self._detect_actual_page(page)
        if actual_page is not None and actual_page != expected_page:
            pagination_attempts = accumulated_data.get(
                "pagination_recovery_attempts", 0
            )
            if pagination_attempts >= MAX_PAGINATION_RECOVERY_ATTEMPTS:
                logger.warning(
                    "Browse pagination: giving up after %d recovery "
                    "attempts navigating from actual page %d to expected "
                    "page %d (server likely clamped past last page)",
                    pagination_attempts,
                    actual_page,
                    expected_page,
                )
                return
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
                "pagination_recovery_attempts": accumulated_data.get(
                    "pagination_recovery_attempts", 0
                )
                + 1,
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
                "pagination_recovery_attempts": 0,
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
                "pagination_recovery_attempts": accumulated_data.get(
                    "pagination_recovery_attempts", 0
                )
                + 1,
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
                "pagination_recovery_attempts": 0,
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
    # Each grid row yields a click on its named btnSelect button, sending
    # the user to parse_filing_detail at the default priority (9), ahead
    # of this step's pagination requests (16), so detail pages are
    # scraped before the queue advances to the next page of results.

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

        Returns ``(data_rows, pagination_row)``.  Rows are picked by
        content rather than position so the 2026-04 ``<thead>``/``<tbody>``
        split doesn't strip the first data row (the per-parent-context
        ``position()>1`` predicate would silently drop ``<tbody>``'s
        first ``<tr>``).
        """
        data_rows = page.query_xpath(
            f"//table[@id='{table_id}']//tr[.//input[contains(@id, 'btnSelect')]]",
            f"{table_id} data rows",
            min_count=0,
        )
        pagination_rows = page.query_xpath(
            f"//table[@id='{table_id}']//tr[.//a[contains(@href, 'Page$')]]",
            f"{table_id} pagination rows",
            min_count=0,
        )
        return list(data_rows), (
            pagination_rows[0] if pagination_rows else None
        )

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
                    "search_grid": "pending",
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
                    "search_grid": "decided",
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

    # =========================================================================
    # net_docket Flow — Targeted Net-Catch of Cases Unreachable by
    # Docket-Number Search but Visible in the Wide Enumeration Grid
    # =========================================================================
    #
    # Some cases (typically older ones) appear in the docket grid but
    # aren't indexed for docket-number lookup. The enumerate_dockets flow
    # captures them, but bttnDetails drift causes their filing-detail to
    # come back as the wrong case, and the docket-number-search recovery
    # path can't help (the case isn't searchable).
    #
    # This flow takes a JSONL of {aria_case_info, docket_number} targets,
    # re-walks the grid with the magic OR-string, and only clicks rows
    # whose aria matches a target. It then verifies the docket_number on
    # the docket-detail page (to disambiguate aria collisions like the
    # "Matter of Anonymous" cluster) before submitting bttnDetails. On
    # filing-detail caption mismatch, it emits NYDocketFailure directly
    # — no recovery, since these cases are unrecoverable by definition.
    #
    # Logic largely duplicates the enumerate_dockets steps; kept separate
    # to avoid entangling the two flows.

    @entry(NYCourtPassDocket)
    def net_docket(
        self,
        targets: NetDocketTargets,
    ) -> Generator[Request, None, None]:
        """Re-walk the docket grid to catch specific target cases.

        ``targets`` lists ``(aria_case_info, docket_number)`` pairs. Rows
        whose ``aria-label`` matches an entry are clicked; the resulting
        docket-detail page's ``docket_number`` must also match a target
        before we proceed to filing detail.

        Re-running with a filtered-down target list after each pass lets
        the caller iterate until everything reachable has been captured.
        """
        aria_targets = sorted({t.aria_case_info for t in targets.targets})
        docket_targets = sorted({t.docket_number for t in targets.targets})
        logger.info(
            "net_docket: %d unique aria-labels / %d unique docket "
            "numbers across %d input pairs",
            len(aria_targets),
            len(docket_targets),
            len(targets.targets),
        )
        yield Request(
            request=HTTPRequestParams(
                method=HttpMethod.GET,
                url=DOCKET_URL,
            ),
            continuation=self.net_fill_docket_search,
            accumulated_data={
                "entry_point": "net_docket",
                "coa_site_source": "docket",
                "net_aria_targets": aria_targets,
                "net_docket_targets": docket_targets,
            },
        )

    @step(
        xsd="xsds/courtpass_docket_page.xsd",
        await_list=[
            WaitForLoadState("networkidle", timeout=60000),
            WaitForSelector("#Form2", timeout=30000),
        ],
    )
    def net_fill_docket_search(
        self,
        page: PageElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[_Yield], None, None]:
        """Submit the wide enumerate query for the net_docket flow.

        Mirrors ``fill_docket_search``: when ``target_page`` is set in
        accumulated_data (from a lost-context recovery), it is forwarded
        as ``page_number`` so ``net_parse_docket_results`` detects the
        page mismatch and jumps forward to the target page.
        """
        target_page = accumulated_data.get("target_page", 1)
        form = page.find_form(DOCKET_FORM, "docket search form")
        yield form.submit(
            data={
                "ctl00$cphMain$tbPartyNames": DOCKET_ENUMERATE_QUERY,
                "ctl00$cphMain$ddlFindParty": "FindOR",
            },
            submit_selector="input[name='ctl00$cphMain$btnFind']",
            continuation=self.net_parse_docket_results,
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
    def net_parse_docket_results(
        self,
        page: PageElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[_Yield], None, None]:
        """Walk the docket grid, clicking only rows in the target set.

        No date filtering — the goal is wide coverage. Rows whose
        ``aria-label`` isn't in the targets file are skipped silently.
        """
        expected_page = accumulated_data.get("page_number", 1)

        wrong_page = page.query_xpath(
            "//span[@id='cphMain_lbDetails' or @id='cphMain_lbDetails2']",
            "detail span (wrong page)",
            min_count=0,
        )
        if wrong_page:
            raise TransientException(
                "net_parse_docket_results received a detail page "
                "instead of results (session-state race)"
            )

        data_rows = list(
            page.query_xpath(
                "//table[contains(@id, 'gvResults')]"
                "//tr[.//input[contains(@id, 'btnSelect')]]",
                "docket data rows",
                min_count=0,
            )
        )
        pagination_rows = page.query_xpath(
            "//table[contains(@id, 'gvResults')]"
            "//tr[.//a[contains(@href, 'Page$')]]",
            "docket pagination rows",
            min_count=0,
        )
        pagination_row = pagination_rows[0] if pagination_rows else None

        # Lost-context: re-initiate the search and resume at the target
        # page.  Bounded to avoid infinite loops when the server has
        # genuinely run out of pages.
        MAX_RECOVERY_ATTEMPTS = 3
        recovery_attempts = accumulated_data.get("recovery_attempts", 0)
        if not data_rows and pagination_row is None and expected_page > 1:
            if recovery_attempts >= MAX_RECOVERY_ATTEMPTS:
                logger.warning(
                    "net_parse_docket_results: giving up after %d "
                    "recovery attempts at page %d",
                    recovery_attempts,
                    expected_page,
                )
                return
            yield from self._net_reinitiate_docket_search(
                expected_page, accumulated_data
            )
            return

        # Pagination drift: server returned a different page than we
        # asked for.  Step forward via the visible pagination links.
        MAX_PAGINATION_RECOVERY_ATTEMPTS = 3
        actual_page = self._detect_actual_page(page)
        if actual_page is not None and actual_page != expected_page:
            pagination_attempts = accumulated_data.get(
                "pagination_recovery_attempts", 0
            )
            if pagination_attempts >= MAX_PAGINATION_RECOVERY_ATTEMPTS:
                logger.warning(
                    "net_parse_docket_results: giving up after %d "
                    "recovery attempts navigating from actual page %d "
                    "to expected page %d (server likely clamped past "
                    "last page)",
                    pagination_attempts,
                    actual_page,
                    expected_page,
                )
                return
            yield from self._net_recover_docket_pagination(
                page,
                pagination_row,
                expected_page,
                actual_page,
                accumulated_data,
            )
            return

        aria_set = set(accumulated_data.get("net_aria_targets") or [])

        # Children continue into the docket-detail step, which only needs
        # ``net_docket_targets``. Drop the aria list so we don't store an
        # extra ~50KB on every child request.
        child_accumulated_base = {
            k: v
            for k, v in accumulated_data.items()
            if k != "net_aria_targets"
        }

        for i, row in enumerate(data_rows):
            select_buttons = row.query_xpath(
                ".//input[contains(@id, 'btnSelect')]",
                "select button",
                min_count=0,
            )
            if not select_buttons:
                continue
            aria_case_info = select_buttons[0].get_attribute("aria-label")
            if not aria_case_info or aria_case_info not in aria_set:
                continue

            cells = row.query_xpath("td", "row cells", min_count=0)
            case_title_from_grid = (
                self._normalize_whitespace(cells[1].text_content())
                if len(cells) >= 2
                else ""
            )
            argument_date_from_grid = (
                cells[2].text_content().strip() if len(cells) >= 3 else ""
            )

            form = page.find_form(DOCKET_FORM, "docket results form")
            yield form.submit(
                data={},
                submit_selector=f"#cphMain_gvResults_btnSelect_{i}",
                continuation=self.net_parse_docket_detail,
                accumulated_data={
                    **child_accumulated_base,
                    "temp_case_id": str(uuid.uuid4()),
                    "case_title_from_search": case_title_from_grid,
                    "argument_date_from_grid": argument_date_from_grid,
                    "search_page": expected_page,
                    "search_row": i,
                    "aria_case_info": aria_case_info,
                },
                deduplication_key=SkipDeduplicationCheck(),
            )

        next_page = expected_page + 1
        yield from self._net_navigate_to_next_docket_page(
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
    def net_parse_docket_detail(
        self,
        page: PageElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[_Yield], None, None]:
        """Verify the clicked row's docket_number and submit bttnDetails.

        Resolves aria-case-info collisions: aria-label uniqueness isn't
        guaranteed (e.g. "Matter of Anonymous" maps to 9+ different
        dockets), so we confirm the docket-detail page actually shows a
        target docket before proceeding. Non-target dockets are dropped
        silently.
        """
        fields = self._extract_docket_detail_fields(page)
        docket_number = fields["docket_number"]
        docket_set = set(accumulated_data.get("net_docket_targets") or [])
        if not docket_number or docket_number not in docket_set:
            logger.info(
                "net_parse_docket_detail: docket %r on this page is "
                "not in the target set (aria collision); dropping",
                docket_number,
            )
            return

        # The filing-detail step and file-download requests don't need
        # the targets list anymore — strip it so we don't bloat
        # accumulated_data.
        filing_detail_data = {
            k: v
            for k, v in accumulated_data.items()
            if k != "net_docket_targets"
        }
        filing_detail_data.update(
            {
                "docket_number": docket_number,
                "case_name_from_docket_detail": self._canonicalize_caption(
                    fields["case_name"] or ""
                ),
                "deferred_docket": {
                    "temp_case_id": accumulated_data.get("temp_case_id", ""),
                    "docket_number": docket_number,
                    "case_name": fields["case_name"],
                    "argument_date_str": (
                        fields["argument_date_str"]
                        or accumulated_data.get("argument_date_from_grid")
                    ),
                    "docket_entries": fields["docket_entries"],
                    "attorneys": fields["attorneys"],
                    "search_page": accumulated_data.get("search_page"),
                    "search_row": accumulated_data.get("search_row"),
                    "aria_case_info": accumulated_data.get("aria_case_info"),
                },
            }
        )

        form = page.find_form(DOCKET_FORM, "docket detail form")
        yield form.submit(
            data={
                "__EVENTTARGET": "ctl00$cphMain$bttnDetails",
                "__EVENTARGUMENT": "",
            },
            continuation=self.net_parse_docket_filing_detail,
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
    def net_parse_docket_filing_detail(
        self,
        page: PageElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[_Yield], None, None]:
        """Emit NYCourtPassDocket + NYCourtPassCase + file downloads, or
        emit NYDocketFailure if the bttnDetails postback drifted.

        Unlike ``parse_docket_filing_detail``, there's no recovery: by
        definition these cases aren't findable by docket-number search,
        so a re-walk would just hit the same drift.
        """
        fields = self._extract_detail_fields(
            page, detail_span_id="cphMain_lbDetails2"
        )
        case_name = fields["case_name"] or "Unknown"

        docket_case_name = accumulated_data.get("case_name_from_docket_detail")
        filing_case_name = self._canonicalize_caption(case_name)
        if (
            docket_case_name
            and filing_case_name
            and filing_case_name != "Unknown"
            and not self._caption_substring_match(
                filing_case_name, docket_case_name
            )
        ):
            logger.warning(
                "net_parse_docket_filing_detail: caption mismatch for "
                "docket %s; emitting NYDocketFailure (docket-detail "
                "showed %r, filing-detail shows %r)",
                accumulated_data.get("docket_number"),
                docket_case_name,
                filing_case_name,
            )
            yield from self._emit_docket_failure(
                accumulated_data,
                observed_filing_caption=filing_case_name,
                failed_docket_search=False,
            )
            return

        argument_date = self._parse_date_mdy(
            fields["argument_date_str"]
            or accumulated_data.get("argument_date_from_grid")
            or ""
        )
        decision_date = self._parse_date_mdy(fields["decision_date_str"] or "")

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

        total_files = len(files_info)
        files = [
            NYCourtPassFile(
                file_name=f["file_name"],
                file_index=f.get("row_index"),
                document_number=total_files - i,
                available=f.get("available", True),
                temp_case_id=temp_case_id,
                docket_number=docket_number or None,
            )
            for i, f in enumerate(files_info)
        ]
        document_numbers_by_row = {
            f["row_index"]: total_files - i for i, f in enumerate(files_info)
        }

        yield ParsedData(
            data=NYCourtPassCase(
                temp_case_id=temp_case_id,
                case_name=case_name,
                case_name_abbrev=accumulated_data.get("case_title_from_search")
                or None,
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
                search_grid=accumulated_data.get("search_grid"),
            )
        )

        file_name_prefix = base64.b64encode(
            f"{case_name}-{argument_date}-{decision_date}".encode()
        ).decode()
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
            is_oral_argument_media = bool(
                ORAL_ARGUMENT_MEDIA_RE.search(file_info["file_name"])
            )
            yield form.submit(
                submit_selector=f"input[name='{button_name}']",
                continuation=(
                    self.handle_oral_argument_download
                    if is_oral_argument_media
                    else self.handle_file_download
                ),
                accumulated_data={
                    "temp_case_id": temp_case_id,
                    "docket_number": docket_number,
                    "file_name": file_info["file_name"],
                    "file_index": file_info["row_index"],
                    "document_number": document_numbers_by_row.get(
                        file_info["row_index"]
                    ),
                },
                bypass_rate_limit=True,
                priority=0,
                archive=True,
                expected_type="asx" if is_oral_argument_media else "pdf",
                deduplication_key=name_sha,
            )

    def _net_reinitiate_docket_search(
        self,
        target_page: int,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[_Yield], None, None]:
        """Mirror of ``_reinitiate_docket_search`` for the net flow."""
        recovery_attempts = accumulated_data.get("recovery_attempts", 0) + 1
        logger.info(
            "net_parse_docket_results: re-initiating search for page %d "
            "(attempt %d)",
            target_page,
            recovery_attempts,
        )
        yield Request(
            request=HTTPRequestParams(
                method=HttpMethod.GET,
                url=DOCKET_URL,
            ),
            continuation=self.net_fill_docket_search,
            accumulated_data={
                **accumulated_data,
                "target_page": target_page,
                "recovery_attempts": recovery_attempts,
            },
            deduplication_key=SkipDeduplicationCheck(),
        )

    def _net_recover_docket_pagination(
        self,
        page: PageElement,
        pagination_row: PageElement | None,
        expected_page: int,
        actual_page: int,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[_Yield], None, None]:
        """Mirror of ``_recover_docket_pagination`` for the net flow.

        Same pagination-jump strategy but continues to
        ``net_parse_docket_results``.
        """
        if pagination_row is None:
            return

        visible = self._extract_visible_page_numbers(pagination_row)
        if not visible:
            return

        if max(visible) < actual_page:
            return

        if expected_page in visible:
            target = expected_page
        elif expected_page > actual_page:
            target = max(visible)
        else:
            target = min(visible)

        form = page.find_form(DOCKET_FORM, "docket pagination recovery")
        yield form.submit(
            data={
                "__EVENTTARGET": DOCKET_GRID,
                "__EVENTARGUMENT": f"Page${target}",
            },
            continuation=self.net_parse_docket_results,
            accumulated_data={
                **accumulated_data,
                "page_number": expected_page,
                "pagination_recovery_attempts": accumulated_data.get(
                    "pagination_recovery_attempts", 0
                )
                + 1,
            },
            deduplication_key=SkipDeduplicationCheck(),
        )

    def _net_navigate_to_next_docket_page(
        self,
        page: PageElement,
        pagination_row: PageElement | None,
        next_page: int,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[_Yield], None, None]:
        """Mirror of ``_navigate_to_next_docket_page`` for the net flow.

        Same pagination logic but continues to
        ``net_parse_docket_results``.
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
            continuation=self.net_parse_docket_results,
            accumulated_data={
                **accumulated_data,
                "page_number": target_page_number,
                "pagination_recovery_attempts": 0,
            },
            deduplication_key=SkipDeduplicationCheck(),
        )


Site = NYCourtPassScraper
