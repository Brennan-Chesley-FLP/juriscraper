"""Minimal test scraper: fetch one AZ Supreme Court case-type list page.

Exercises ``CaseListParser`` against a live ``stage_ASC_CR.htm`` page and
emits the ``AzAppDocket`` rows (no PDF downloads, to keep the test light).

Run with:
    uv run kent run \
        --db runs/AzApp-Test.db \
        --driver httpx \
        --params '[{"fetch_case_list": {}}]' \
        juriscraper.state.arizona.apps_azcourts_gov.test:TestScraper

Inspect results with:
    uv run pdd --db runs/AzApp-Test.db results list
    uv run pdd --db runs/AzApp-Test.db results show 1
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

from .models import BASE_URL, AzAppDocket
from .parsers import CaseListParser

if TYPE_CHECKING:
    from collections.abc import Generator

    from jkent.common.page_element import PageElement
    from jkent.data_types import ScraperYield

COURT_ID = "ariz"
CASE_TYPE = "CR"


class TestScraper(BaseScraper[AzAppDocket]):
    """Test scraper: fetches the ASC active-criminal case list."""

    court_ids: ClassVar[set[str]] = {COURT_ID}
    court_url: ClassVar[str] = BASE_URL
    data_types: ClassVar[set[str]] = {"dockets"}
    status: ClassVar[ScraperStatus] = ScraperStatus.IN_DEVELOPMENT
    version: ClassVar[str] = "2026-06-26"
    last_verified: ClassVar[str] = "2026-05-02"
    requires_auth: ClassVar[bool] = False
    rate_limits: ClassVar[list[Rate] | None] = [Rate(1, Duration.SECOND)]

    @entry(AzAppDocket)
    def fetch_case_list(self) -> Generator[Request, None, None]:
        """Fetch the ASC active-criminal case-list page."""
        yield Request(
            request=HTTPRequestParams(
                method=HttpMethod.GET,
                url=f"{BASE_URL}stage_ASC_{CASE_TYPE}.htm",
                headers={"Accept": "text/html"},
            ),
            continuation=self.parse_case_list,
            accumulated_data={"court": COURT_ID, "case_type": CASE_TYPE},
        )

    @step()
    def parse_case_list(
        self,
        page: PageElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[AzAppDocket], None, None]:
        """Parse the list page and emit AzAppDocket rows (no PDF archives)."""
        for docket in CaseListParser()(page):
            raw = docket.raw_data
            raw["court"] = accumulated_data["court"]
            raw["case_type"] = accumulated_data["case_type"]
            raw["source_url"] = response.url
            yield ParsedData(AzAppDocket.raw(**raw))
