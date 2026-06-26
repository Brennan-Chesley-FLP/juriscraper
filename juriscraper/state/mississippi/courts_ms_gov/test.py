"""Minimal test scraper: fetch the docket page for one known case_num.

Exercises the real ``DocketPageParser`` against a live ``build_docket.php``
docket fragment without the speculation flow. The follow-on parties /
trial-court / oral-arg sub-fetches are not driven here — this is a smoke
test of the primary page parser.

Run with:
    uv run kent run \
        --db runs/MsApp-Test.db \
        --driver httpx \
        --params '[{"fetch_docket": {}}]' \
        juriscraper.state.mississippi.courts_ms_gov.test:TestScraper

Inspect results with:
    uv run pdd --db runs/MsApp-Test.db results list
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

from .models import BUILD_DOCKET_URL, MsAppDocket, MsAppDocketEntry
from .parsers import DocketPageParser
from .scraper import DOCKET_BODY, XHR_HEADERS

if TYPE_CHECKING:
    from collections.abc import Generator

    from jkent.common.page_element import PageElement
    from jkent.data_types import ScraperYield

CASE_NUM = 100500


class TestScraper(BaseScraper[MsAppDocket]):
    """Test scraper: fetches one known docket page by case_num."""

    court_ids: ClassVar[set[str]] = {"miss", "missctapp"}
    court_url: ClassVar[str] = BUILD_DOCKET_URL
    data_types: ClassVar[set[str]] = {"dockets"}
    status: ClassVar[ScraperStatus] = ScraperStatus.IN_DEVELOPMENT
    version: ClassVar[str] = "2026-06-27"
    last_verified: ClassVar[str] = "2026-05-03"
    requires_auth: ClassVar[bool] = False
    rate_limits: ClassVar[list[Rate] | None] = [Rate(1, Duration.SECOND)]

    @entry(MsAppDocket)
    def fetch_docket(self) -> Generator[Request, None, None]:
        """Fetch the docket page for the single test case_num."""
        yield Request(
            request=HTTPRequestParams(
                method=HttpMethod.POST,
                url=BUILD_DOCKET_URL,
                data=DOCKET_BODY.format(cn=CASE_NUM),
                headers=XHR_HEADERS,
            ),
            continuation=self.parse_docket_page,
            accumulated_data={"case_num": CASE_NUM},
        )

    @step()
    def parse_docket_page(
        self,
        page: PageElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[MsAppDocket], None, None]:
        """Parse the docket page and emit a (header-only) MsAppDocket."""
        cn = int(accumulated_data["case_num"])
        raw = DocketPageParser()(page)[0].raw_data
        entries: list[MsAppDocketEntry] = list(raw.get("entries", []))
        docket = MsAppDocket.raw(
            docket_number=raw["docket_number"],
            court=raw["court"],
            case_num=cn,
            case_name=raw["case_name"],
            date_filed=raw.get("date_filed"),
            entries=entries,
            source_url=f"{BUILD_DOCKET_URL}?cn={cn}",
            source_entry_point="fetch_docket",
        )
        yield ParsedData(docket)
