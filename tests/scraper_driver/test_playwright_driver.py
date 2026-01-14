"""Tests for PlaywrightDriver.

These tests require playwright browsers to be installed:
    playwright install chromium
"""

from collections.abc import Generator

import pytest

from juriscraper.scraper_driver.common.decorators import step
from juriscraper.scraper_driver.data_types import (
    BaseScraper,
    HttpMethod,
    HTTPRequestParams,
    NavigatingRequest,
    NonNavigatingRequest,
    ParsedData,
    Response,
    ScraperYield,
)
from juriscraper.scraper_driver.driver.playwright_driver import (
    PlaywrightDriver,
)


class SimplePlaywrightScraper(BaseScraper[dict]):
    """Simple scraper for testing PlaywrightDriver."""

    def __init__(self) -> None:
        self.pages_visited: list[str] = []
        self.data_collected: list[dict] = []

    def get_entry(self) -> Generator[NavigatingRequest, None, None]:
        yield NavigatingRequest(
            request=HTTPRequestParams(
                method=HttpMethod.GET,
                url="https://example.com",
            ),
            continuation="parse_home",
        )

    @step
    def parse_home(
        self, response: Response
    ) -> Generator[ScraperYield, bool | None, None]:
        self.pages_visited.append(response.url)
        yield ParsedData({"title": "Example Domain", "url": response.url})


class MultiPageScraper(BaseScraper[dict]):
    """Scraper that yields multiple NavigatingRequests."""

    def __init__(self) -> None:
        self.pages_visited: list[str] = []

    def get_entry(self) -> Generator[NavigatingRequest, None, None]:
        yield NavigatingRequest(
            request=HTTPRequestParams(
                method=HttpMethod.GET,
                url="https://example.com",
            ),
            continuation="parse_home",
        )

    @step
    def parse_home(
        self, response: Response
    ) -> Generator[ScraperYield, bool | None, None]:
        self.pages_visited.append(response.url)

        # Yield multiple navigation requests
        yield NavigatingRequest(
            request=HTTPRequestParams(
                method=HttpMethod.GET,
                url="https://httpbin.org/html",
            ),
            continuation="parse_detail",
        )

    @step
    def parse_detail(
        self, response: Response
    ) -> Generator[ScraperYield, bool | None, None]:
        self.pages_visited.append(response.url)
        yield ParsedData({"url": response.url})


class NonNavigatingScraper(BaseScraper[dict]):
    """Scraper that uses NonNavigatingRequest for API calls."""

    def __init__(self) -> None:
        self.api_responses: list[dict] = []

    def get_entry(self) -> Generator[NavigatingRequest, None, None]:
        yield NavigatingRequest(
            request=HTTPRequestParams(
                method=HttpMethod.GET,
                url="https://example.com",
            ),
            continuation="parse_home",
        )

    @step
    def parse_home(
        self, response: Response
    ) -> Generator[ScraperYield, bool | None, None]:
        # Make a non-navigating API request
        yield NonNavigatingRequest(
            request=HTTPRequestParams(
                method=HttpMethod.GET,
                url="https://httpbin.org/json",
            ),
            continuation="parse_api",
        )

    @step
    def parse_api(
        self, response: Response
    ) -> Generator[ScraperYield, bool | None, None]:
        import json

        data = json.loads(response.text)
        self.api_responses.append(data)
        yield ParsedData(data)


@pytest.mark.asyncio
class TestPlaywrightDriverBasic:
    """Basic tests for PlaywrightDriver functionality."""

    async def test_simple_navigation(self):
        """Test basic page navigation."""
        scraper = SimplePlaywrightScraper()
        results: list[dict] = []

        async def collect_data(data: dict) -> None:
            results.append(data)

        async with PlaywrightDriver(
            scraper=scraper,
            headless=True,
            on_data=collect_data,
        ) as driver:
            await driver.run()

        assert len(results) == 1
        assert results[0]["title"] == "Example Domain"
        assert "example.com" in results[0]["url"]
        assert len(scraper.pages_visited) == 1

    async def test_multi_page_navigation(self):
        """Test navigation across multiple pages."""
        scraper = MultiPageScraper()
        results: list[dict] = []

        async def collect_data(data: dict) -> None:
            results.append(data)

        async with PlaywrightDriver(
            scraper=scraper,
            headless=True,
            on_data=collect_data,
        ) as driver:
            await driver.run()

        assert len(scraper.pages_visited) == 2
        assert "example.com" in scraper.pages_visited[0]
        assert "httpbin.org" in scraper.pages_visited[1]

    async def test_non_navigating_request(self):
        """Test NonNavigatingRequest for API calls."""
        scraper = NonNavigatingScraper()
        results: list[dict] = []

        async def collect_data(data: dict) -> None:
            results.append(data)

        async with PlaywrightDriver(
            scraper=scraper,
            headless=True,
            on_data=collect_data,
        ) as driver:
            await driver.run()

        assert len(results) == 1
        # httpbin.org/json returns a specific structure
        assert "slideshow" in results[0]

    async def test_context_manager(self):
        """Test that context manager properly starts and stops browser."""
        scraper = SimplePlaywrightScraper()

        driver = PlaywrightDriver(scraper=scraper, headless=True)

        # Before start, browser is None
        assert driver._browser is None
        assert driver._context is None

        async with driver:
            # Inside context, browser is running
            assert driver._browser is not None
            assert driver._context is not None
            await driver.run()

        # After exit, browser is closed
        assert driver._browser is None
        assert driver._context is None

    async def test_explicit_lifecycle(self):
        """Test explicit start/stop lifecycle."""
        scraper = SimplePlaywrightScraper()
        driver = PlaywrightDriver(scraper=scraper, headless=True)

        await driver.start()
        try:
            assert driver._browser is not None
            await driver.run()
        finally:
            await driver.stop()

        assert driver._browser is None


@pytest.mark.asyncio
class TestPlaywrightDriverHeaders:
    """Test that headers are captured correctly."""

    async def test_response_headers_captured(self):
        """Test that HTTP headers are captured from navigation."""
        scraper = SimplePlaywrightScraper()
        captured_headers: list[dict] = []

        class HeaderCaptureScraper(BaseScraper[dict]):
            def get_entry(self) -> Generator[NavigatingRequest, None, None]:
                yield NavigatingRequest(
                    request=HTTPRequestParams(
                        method=HttpMethod.GET,
                        url="https://httpbin.org/headers",
                    ),
                    continuation="parse_headers",
                )

            @step
            def parse_headers(
                self, response: Response
            ) -> Generator[ScraperYield, bool | None, None]:
                captured_headers.append(dict(response.headers))
                yield ParsedData({"headers": response.headers})

        scraper = HeaderCaptureScraper()

        async with PlaywrightDriver(scraper=scraper, headless=True) as driver:
            await driver.run()

        assert len(captured_headers) == 1
        # httpbin returns content-type header
        headers = captured_headers[0]
        assert any("content-type" in k.lower() for k in headers)


@pytest.mark.asyncio
class TestPlaywrightDriverBrowserOptions:
    """Test browser configuration options."""

    async def test_custom_user_agent(self):
        """Test that custom user agent is applied."""
        custom_ua = "CustomBot/1.0"
        captured_ua: list[str] = []

        class UAScraper(BaseScraper[dict]):
            def get_entry(self) -> Generator[NavigatingRequest, None, None]:
                yield NavigatingRequest(
                    request=HTTPRequestParams(
                        method=HttpMethod.GET,
                        url="https://example.com",
                    ),
                    continuation="parse_home",
                )

            @step
            def parse_home(
                self, response: Response
            ) -> Generator[ScraperYield, bool | None, None]:
                # Use NonNavigatingRequest to get raw JSON from httpbin
                yield NonNavigatingRequest(
                    request=HTTPRequestParams(
                        method=HttpMethod.GET,
                        url="https://httpbin.org/user-agent",
                    ),
                    continuation="parse_ua",
                )

            @step
            def parse_ua(
                self, response: Response
            ) -> Generator[ScraperYield, bool | None, None]:
                import json

                data = json.loads(response.text)
                captured_ua.append(data.get("user-agent", ""))
                yield ParsedData(data)

        scraper = UAScraper()

        async with PlaywrightDriver(
            scraper=scraper,
            headless=True,
            user_agent=custom_ua,
        ) as driver:
            await driver.run()

        assert len(captured_ua) == 1
        assert custom_ua in captured_ua[0]
