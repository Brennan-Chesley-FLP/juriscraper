"""Minimal test scraper: fetch a single known AZ CoA Div. Two case detail.

The case-detail page is publicly accessible without cookies or captcha, so
this exercises the real ``CaseDetailParser`` against a live page without the
search/captcha flow.

Run with:
    uv run kent run \
        --db runs/AzCoa2-Test.db \
        --driver httpx \
        --params '[{"fetch_case": {}}]' \
        juriscraper.state.arizona.appeals2_az_gov.test:TestScraper

Inspect results with:
    uv run pdd --db runs/AzCoa2-Test.db results list
    uv run pdd --db runs/AzCoa2-Test.db results show 1
"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from jkent.common.decorators import entry, step
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

from .models import CASE_DETAIL_URL, COURT_ID, AzCoa2Docket
from .parsers import CaseDetailParser

if TYPE_CHECKING:
    from collections.abc import Generator

    from jkent.common.page_element import PageElement
    from jkent.data_types import ScraperYield

CASE_ID = 134401


class TestScraper(BaseScraper[AzCoa2Docket]):
    """Test scraper: fetches a single known case-detail page by caseID."""

    court_ids: ClassVar[set[str]] = {COURT_ID}
    court_url: ClassVar[str] = CASE_DETAIL_URL
    data_types: ClassVar[set[str]] = {"dockets"}
    status: ClassVar[ScraperStatus] = ScraperStatus.IN_DEVELOPMENT
    version: ClassVar[str] = "2026-06-26"
    last_verified: ClassVar[str] = "2026-05-02"
    requires_auth: ClassVar[bool] = False
    rate_limits: ClassVar[list[Rate] | None] = [Rate(1, Duration.SECOND)]

    @entry(AzCoa2Docket)
    def fetch_case(self) -> Generator[Request, None, None]:
        """Fetch the single test case by caseID."""
        yield Request(
            request=HTTPRequestParams(
                method=HttpMethod.GET,
                url=CASE_DETAIL_URL,
                params={"caseID": str(CASE_ID)},
                headers={"Accept": "text/html"},
            ),
            continuation=self.parse_case_detail,
            accumulated_data={"case_id": CASE_ID},
        )

    @step()
    def parse_case_detail(
        self,
        page: PageElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[AzCoa2Docket], None, None]:
        """Parse the case-detail page and emit one AzCoa2Docket."""
        raw = CaseDetailParser()(page)[0].raw_data
        raw["case_id"] = int(accumulated_data["case_id"])
        raw["court"] = COURT_ID
        raw["source_url"] = response.url
        raw["source_entry_point"] = "fetch_case"
        yield ParsedData(AzCoa2Docket.raw(**raw))
