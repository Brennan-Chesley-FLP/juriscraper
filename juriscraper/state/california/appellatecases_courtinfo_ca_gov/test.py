"""Minimal test scraper: fetch a single known CA Supreme Court case (S295928).

Run with:
    uv run kent run \
        --db runs/CaSup-Test.db \
        --storage runs/CACoA-files \
        --driver playwright \
        --browser-profile ../profiles/cloudflare-firefox \
        --params '[{"fetch_supreme_court_docket": {}}]' \
        juriscraper.sd.state.california.appellatecases_courtinfo_ca_gov.test:TestScraper

Inspect results with:
    uv run pdd --db runs/CaSup-Test.db results list
    uv run pdd --db runs/CaSup-Test.db results show 1
"""

from __future__ import annotations

import re
from collections.abc import Generator
from datetime import date
from typing import TYPE_CHECKING, ClassVar
from urllib.parse import parse_qs, urlencode, urlparse

from jkent.common.decorators import entry, step
from jkent.common.page_element import PageElement
from jkent.data_types import (
    BaseScraper,
    HttpMethod,
    HTTPRequestParams,
    ParsedData,
    Request,
    Response,
    ScraperStatus,
    WaitForLoadState,
    WaitForSelector,
    XPath,
)
from pyrate_limiter import Duration, Rate

from .models import (
    BASE_URL,
    CaAppCaseUnavailable,
    CaAppDocket,
    CaAppDocketEntry,
)

if TYPE_CHECKING:
    from jkent.data_types import ScraperYield

CASE_NUMBER = "S295928"
DIST = "0"
COURT_ID = "cal"


def _parse_date(text: str) -> date | None:
    text = text.strip()
    if not text:
        return None
    m = re.match(r"(\d{2})/(\d{2})/(\d{4})", text)
    if not m:
        return None
    return date(int(m.group(3)), int(m.group(1)), int(m.group(2)))


def _clean_text(text: str | None) -> str | None:
    if text is None:
        return None
    text = text.strip()
    return text if text else None


def _build_tab_url(response_url: str, tab_page: str) -> str:
    parsed = urlparse(response_url)
    params = parse_qs(parsed.query)
    query = urlencode(
        {
            "dist": params["dist"][0],
            "doc_id": params["doc_id"][0],
            "doc_no": params["doc_no"][0],
            "request_token": params["request_token"][0],
        }
    )
    base = response_url.rsplit("/", 1)[0]
    return f"{base}/{tab_page}?{query}"


class TestScraper(BaseScraper[CaAppDocket | CaAppCaseUnavailable]):
    """Test scraper: fetches only CA Supreme Court case S295928."""

    court_ids: ClassVar[set[str]] = {"cal"}
    court_url: ClassVar[str] = BASE_URL
    data_types: ClassVar[set[str]] = {"dockets"}
    status: ClassVar[ScraperStatus] = ScraperStatus.IN_DEVELOPMENT
    version: ClassVar[str] = "2026-04-04"
    requires_auth: ClassVar[bool] = False
    rate_limits: ClassVar[list[Rate] | None] = [Rate(1, Duration.SECOND)]

    @entry(CaAppDocket)
    def fetch_supreme_court_docket(self) -> Generator[Request, None, None]:
        """Fetch the single test case S295928.

        Navigate directly to the search results URL as a GET request,
        bypassing form submission. The site accepts case number searches
        via query parameters without requiring a POST.
        """
        search_results_url = (
            f"{BASE_URL}/search/searchResults.cfm"
            f"?dist={DIST}&search=number"
            f"&query_caseNumber={CASE_NUMBER}"
        )
        yield Request(
            request=HTTPRequestParams(
                method=HttpMethod.GET,
                url=search_results_url,
            ),
            continuation=self.parse_case_summary,
            accumulated_data={
                "docket_number": CASE_NUMBER,
                "court": COURT_ID,
                "is_supreme": True,
            },
        )

    # ── Step 2: Parse Case Summary ──

    @step(
        await_list=[
            WaitForLoadState("networkidle", timeout=30000),
            WaitForSelector("h3, h4", timeout=15000),
        ],
        priority=8,
    )
    def parse_case_summary(
        self,
        page: PageElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield, None, None]:
        """Extract case summary. If 'Case Not Found', yield unavailable."""
        # Detect "Case Not Found"
        not_found = page.query(
            XPath("//h4[contains(., 'Case Not Found')]"),
            "case not found heading",
            min_count=0,
            max_count=1,
        )
        if not_found:
            yield ParsedData(
                data=CaAppCaseUnavailable(
                    docket_number=accumulated_data["docket_number"],
                    court=accumulated_data["court"],
                )
            )
            return

        accumulated_data["source_url"] = response.url

        # Extract fields from dt/dd definition list
        dts = page.query(
            XPath("//dl/dt"), "summary definition terms", min_count=0
        )
        dds = page.query(
            XPath("//dl/dd"), "summary definition values", min_count=0
        )
        fields: dict[str, str] = {}
        for dt_el, dd_el in zip(dts, dds):
            key = dt_el.text_content().strip().rstrip(":")
            val = dd_el.text_content().strip()
            fields[key] = val

        accumulated_data["case_name"] = fields.get("Case Caption", "")
        accumulated_data["case_type"] = _clean_text(
            fields.get("Case Category")
        )
        # Keep dates as strings in accumulated_data (must be JSON-serializable)
        accumulated_data["date_filed_str"] = fields.get("Start Date", "")
        accumulated_data["case_status"] = _clean_text(
            fields.get("Case Status")
        )

        # Navigate to Docket tab
        docket_url = _build_tab_url(response.url, "dockets.cfm")
        yield Request(
            request=HTTPRequestParams(method=HttpMethod.GET, url=docket_url),
            continuation=self.parse_docket,
            accumulated_data=accumulated_data,
        )

    # ── Step 3: Parse Docket tab ──

    @step(
        await_list=[
            WaitForLoadState("networkidle", timeout=30000),
            WaitForSelector("h3", timeout=15000),
        ],
        priority=7,
    )
    def parse_docket(
        self,
        page: PageElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield, None, None]:
        """Extract docket entries, then assemble and yield the docket."""
        rows = page.query(
            XPath("//table//tbody//tr"), "docket entry rows", min_count=0
        )
        entries: list[CaAppDocketEntry] = []
        for row in rows:
            cells = row.query(XPath("td"), "row cells", min_count=0)
            if len(cells) >= 2:
                entries.append(
                    CaAppDocketEntry(
                        date_filed=_parse_date(cells[0].text_content()),
                        description=cells[1].text_content().strip(),
                        notes=(
                            _clean_text(cells[2].text_content())
                            if len(cells) > 2
                            else None
                        ),
                    )
                )

        # Assemble final docket with just summary + docket entries
        docket = CaAppDocket(
            docket_number=accumulated_data["docket_number"],
            court=accumulated_data["court"],
            case_name=accumulated_data.get("case_name", ""),
            case_type=accumulated_data.get("case_type"),
            date_filed=_parse_date(accumulated_data.get("date_filed_str", "")),
            case_status=accumulated_data.get("case_status"),
            entries=entries,
            source_url=accumulated_data.get("source_url"),
        )
        yield ParsedData(data=docket)

    def actually_successful(self, response: Response) -> bool:
        """Return False for inputError redirects (malformed case numbers)."""
        return "inputError" not in response.url
