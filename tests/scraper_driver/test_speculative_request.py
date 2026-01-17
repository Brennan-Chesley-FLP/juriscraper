"""Tests for SpeculativeRequest (Step 19).

This module tests the speculative request feature which allows scrapers to
yield requests that may or may not exist, with the driver determining whether
to continue based on the response status code and an optional callback.

Test cases:
- Basic speculative yield/resume flow
- 2xx responses auto-continue (True)
- Non-2xx responses with no callback (False)
- Non-2xx responses with callback deciding True/False
- Multiple sequential speculative yields
- Deduplication of speculative requests
- Generator termination after False
"""

from collections.abc import Generator
from unittest.mock import MagicMock

import pytest

from juriscraper.scraper_driver.common.decorators import step
from juriscraper.scraper_driver.common.searchable import ScraperParams
from juriscraper.scraper_driver.data_types import (
    BaseScraper,
    HttpMethod,
    HTTPRequestParams,
    NavigatingRequest,
    ParsedData,
    Response,
    ScraperYield,
    SpeculativeRequest,
)
from juriscraper.scraper_driver.driver.sync_driver import SyncDriver

# =============================================================================
# Test Scrapers
# =============================================================================


class SimpleSpeculativeScraper(BaseScraper[dict]):
    """Scraper that yields speculative requests and tracks results."""

    def __init__(self) -> None:
        self.speculative_results: list[bool] = []
        self.pages_processed: list[int] = []
        self._params = ScraperParams()

    def get_entry(self) -> Generator[NavigatingRequest, None, None]:
        yield NavigatingRequest(
            request=HTTPRequestParams(
                method=HttpMethod.GET, url="https://example.com/start"
            ),
            continuation="parse_start",
        )

    @step(speculative=True)
    def parse_start(
        self, response: Response, speculative_id: int = 1
    ) -> Generator[ScraperYield, bool | None, None]:
        """Initial page - yield a speculative request."""
        page = 1
        while page <= 5:
            should_continue = yield SpeculativeRequest(
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url=f"https://example.com/page/{page}",
                ),
                continuation="parse_page",
                speculative_id=page,
            )
            self.speculative_results.append(
                should_continue if should_continue is not None else False
            )
            if not should_continue:
                break
            page += 1

    @step
    def parse_page(
        self, response: Response
    ) -> Generator[ScraperYield, bool | None, None]:
        """Parse a speculative page."""
        # Extract page number from URL
        page_num = int(response.url.split("/")[-1])
        self.pages_processed.append(page_num)
        yield ParsedData({"page": page_num, "url": response.url})


class MultipleSpeculativeScraper(BaseScraper[dict]):
    """Scraper that yields multiple speculative requests in sequence."""

    def __init__(self) -> None:
        self.results: list[tuple[str, bool]] = []
        self._params = ScraperParams()

    def get_entry(self) -> Generator[NavigatingRequest, None, None]:
        yield NavigatingRequest(
            request=HTTPRequestParams(
                method=HttpMethod.GET, url="https://example.com/"
            ),
            continuation="parse_main",
        )

    @step(speculative=True)
    def parse_main(
        self, response: Response, speculative_id: int = 1
    ) -> Generator[ScraperYield, bool | None, None]:
        for i, resource in enumerate(["users", "posts", "comments"]):
            result = yield SpeculativeRequest(
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url=f"https://example.com/{resource}",
                ),
                continuation="parse_resource",
                speculative_id=i,
            )
            self.results.append(
                (resource, result if result is not None else False)
            )

    @step
    def parse_resource(
        self, response: Response
    ) -> Generator[ScraperYield, bool | None, None]:
        yield ParsedData({"resource": response.url})


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def mock_client() -> MagicMock:
    """Create a mock httpx client."""
    mock = MagicMock()
    return mock


def create_mock_response(
    status_code: int, url: str = "https://example.com/"
) -> MagicMock:
    """Create a mock HTTP response."""
    response = MagicMock()
    response.status_code = status_code
    response.headers = {}
    response.content = b""
    response.text = ""
    return response


# =============================================================================
# Tests
# =============================================================================


class TestSpeculativeRequestBasics:
    """Test basic speculative request functionality."""

    def test_200_response_returns_true_and_calls_continuation(self):
        """2xx responses should return True and call the continuation."""
        scraper = SimpleSpeculativeScraper()
        collected_data: list[dict] = []

        def collect(data: dict) -> None:
            collected_data.append(data)

        # Mock all requests to return 200
        responses = {
            "https://example.com/start": create_mock_response(200),
            "https://example.com/page/1": create_mock_response(200),
            "https://example.com/page/2": create_mock_response(200),
            "https://example.com/page/3": create_mock_response(200),
            "https://example.com/page/4": create_mock_response(200),
            "https://example.com/page/5": create_mock_response(200),
        }

        driver = SyncDriver(scraper, on_data=collect)
        driver.request_manager._client = MagicMock()
        driver.request_manager._client.request.side_effect = (
            lambda **kwargs: responses.get(
                kwargs["url"], create_mock_response(404)
            )
        )

        driver.run()

        # All speculative requests should return True
        assert scraper.speculative_results == [True, True, True, True, True]
        # All pages should be processed
        assert scraper.pages_processed == [1, 2, 3, 4, 5]
        # Data should be collected for each page
        assert len(collected_data) == 5

    def test_404_response_without_callback_returns_false(self):
        """Non-2xx without callback should return False and not call continuation."""
        scraper = SimpleSpeculativeScraper()
        collected_data: list[dict] = []

        def collect(data: dict) -> None:
            collected_data.append(data)

        # First page returns 200, second returns 404
        responses = {
            "https://example.com/start": create_mock_response(200),
            "https://example.com/page/1": create_mock_response(200),
            "https://example.com/page/2": create_mock_response(404),
        }

        driver = SyncDriver(scraper, on_data=collect)
        driver.request_manager._client = MagicMock()
        driver.request_manager._client.request.side_effect = (
            lambda **kwargs: responses.get(
                kwargs["url"], create_mock_response(404)
            )
        )

        driver.run()

        # First speculative: True (200), Second: False (404)
        assert scraper.speculative_results == [True, False]
        # Only first page processed
        assert scraper.pages_processed == [1]
        assert len(collected_data) == 1

    def test_404_response_with_callback_returning_true(self):
        """Non-2xx with callback returning True should return True but not call continuation."""
        scraper = SimpleSpeculativeScraper()
        collected_data: list[dict] = []
        callback_calls: list[tuple[int, str]] = []

        def collect(data: dict) -> None:
            collected_data.append(data)

        def speculation_callback(
            response: Response, continuation_name: str
        ) -> bool:
            callback_calls.append((response.status_code, continuation_name))
            return True  # Always say continue

        responses = {
            "https://example.com/start": create_mock_response(200),
            "https://example.com/page/1": create_mock_response(
                404
            ),  # 404 but callback says continue
            "https://example.com/page/2": create_mock_response(200),
            "https://example.com/page/3": create_mock_response(404),
            "https://example.com/page/4": create_mock_response(200),
            "https://example.com/page/5": create_mock_response(200),
        }

        driver = SyncDriver(
            scraper,
            on_data=collect,
            on_speculation_response=speculation_callback,
        )
        driver.request_manager._client = MagicMock()
        driver.request_manager._client.request.side_effect = (
            lambda **kwargs: responses.get(
                kwargs["url"], create_mock_response(404)
            )
        )

        driver.run()

        # All should return True (callback always returns True)
        assert scraper.speculative_results == [True, True, True, True, True]
        # Only 200 pages should be processed (continuation only called for 2xx)
        assert scraper.pages_processed == [2, 4, 5]
        # Callback called for 404s
        assert len(callback_calls) == 2
        assert callback_calls[0] == (404, "parse_page")
        assert callback_calls[1] == (404, "parse_page")

    def test_callback_returning_false_stops_speculation(self):
        """Callback returning False should stop the speculative loop."""
        scraper = SimpleSpeculativeScraper()
        call_count = 0

        def speculation_callback(
            response: Response, continuation_name: str
        ) -> bool:
            nonlocal call_count
            call_count += 1
            return False  # Always say stop

        responses = {
            "https://example.com/start": create_mock_response(200),
            "https://example.com/page/1": create_mock_response(404),
        }

        driver = SyncDriver(
            scraper,
            on_speculation_response=speculation_callback,
        )
        driver.request_manager._client = MagicMock()
        driver.request_manager._client.request.side_effect = (
            lambda **kwargs: responses.get(
                kwargs["url"], create_mock_response(404)
            )
        )

        driver.run()

        # Should stop after first speculative (callback returns False)
        assert scraper.speculative_results == [False]
        assert scraper.pages_processed == []
        assert call_count == 1

    def test_various_2xx_status_codes(self):
        """All 2xx status codes should return True."""
        for status in [200, 201, 204, 206]:
            scraper = SimpleSpeculativeScraper()
            responses = {
                "https://example.com/start": create_mock_response(200),
                "https://example.com/page/1": create_mock_response(status),
                "https://example.com/page/2": create_mock_response(404),
            }

            driver = SyncDriver(scraper)
            driver.request_manager._client = MagicMock()
            driver.request_manager._client.request.side_effect = (
                lambda responses=responses, **kwargs: responses.get(
                    kwargs["url"], create_mock_response(404)
                )
            )

            driver.run()

            assert scraper.speculative_results[0] is True, (
                f"Status {status} should return True"
            )

    def test_various_non_2xx_status_codes_without_callback(self):
        """All non-2xx status codes without callback should return False."""
        # Note: 5xx would raise TransientException, so we skip those here
        for status in [301, 302, 400, 401, 403, 404]:
            scraper = SimpleSpeculativeScraper()
            responses = {
                "https://example.com/start": create_mock_response(200),
                "https://example.com/page/1": create_mock_response(status),
            }

            driver = SyncDriver(scraper)
            driver.request_manager._client = MagicMock()
            driver.request_manager._client.request.side_effect = (
                lambda responses=responses, **kwargs: responses.get(
                    kwargs["url"], create_mock_response(404)
                )
            )

            driver.run()

            assert scraper.speculative_results[0] is False, (
                f"Status {status} should return False"
            )


class TestSpeculativeRequestDeduplication:
    """Test deduplication of speculative requests."""

    def test_deduplicated_request_returns_false(self):
        """Deduplicated speculative requests should return False."""
        seen_urls: set[str] = set()

        def duplicate_check(key: str) -> bool:
            if key in seen_urls:
                return False  # Already seen
            seen_urls.add(key)
            return True

        # All requests return 200, but we'll try same page twice
        responses = {
            "https://example.com/start": create_mock_response(200),
            "https://example.com/page/1": create_mock_response(200),
        }

        # Custom scraper that tries same page twice
        class DuplicateScraper(BaseScraper[dict]):
            def __init__(self) -> None:
                self.results: list[bool] = []
                self._params = ScraperParams()

            def get_entry(self) -> Generator[NavigatingRequest, None, None]:
                yield NavigatingRequest(
                    request=HTTPRequestParams(
                        method=HttpMethod.GET, url="https://example.com/start"
                    ),
                    continuation="parse_start",
                )

            @step(speculative=True)
            def parse_start(
                self, response: Response, speculative_id: int = 1
            ) -> Generator[ScraperYield, bool | None, None]:
                # First request
                result1 = yield SpeculativeRequest(
                    request=HTTPRequestParams(
                        method=HttpMethod.GET, url="https://example.com/page/1"
                    ),
                    continuation="parse_page",
                    speculative_id=1,
                )
                self.results.append(result1 if result1 is not None else False)

                # Same URL again - should be deduplicated
                result2 = yield SpeculativeRequest(
                    request=HTTPRequestParams(
                        method=HttpMethod.GET, url="https://example.com/page/1"
                    ),
                    continuation="parse_page",
                    speculative_id=2,
                )
                self.results.append(result2 if result2 is not None else False)

            @step
            def parse_page(
                self, response: Response
            ) -> Generator[ScraperYield, bool | None, None]:
                yield ParsedData({"url": response.url})

        dup_scraper = DuplicateScraper()
        driver = SyncDriver(dup_scraper, duplicate_check=duplicate_check)
        driver.request_manager._client = MagicMock()
        driver.request_manager._client.request.side_effect = (
            lambda **kwargs: responses.get(
                kwargs["url"], create_mock_response(404)
            )
        )

        driver.run()

        # First should succeed (True), second should be deduplicated (False)
        assert dup_scraper.results == [True, False]


class TestMultipleSpeculativeYields:
    """Test multiple sequential speculative yields."""

    def test_multiple_speculative_yields_in_sequence(self):
        """Multiple speculative yields should each be processed correctly."""
        scraper = MultipleSpeculativeScraper()

        responses = {
            "https://example.com/": create_mock_response(200),
            "https://example.com/users": create_mock_response(200),
            "https://example.com/posts": create_mock_response(404),
            "https://example.com/comments": create_mock_response(200),
        }

        callback_results: dict[str, bool] = {
            "posts": True,  # 404 but callback says continue
        }

        def speculation_callback(
            response: Response, continuation_name: str
        ) -> bool:
            resource = response.url.split("/")[-1] if response.url else ""
            return callback_results.get(resource, False)

        driver = SyncDriver(
            scraper,
            on_speculation_response=speculation_callback,
        )
        driver.request_manager._client = MagicMock()
        driver.request_manager._client.request.side_effect = (
            lambda **kwargs: responses.get(
                kwargs["url"], create_mock_response(404)
            )
        )

        driver.run()

        # users: True (200), posts: True (callback), comments: True (200)
        assert scraper.results == [
            ("users", True),
            ("posts", True),
            ("comments", True),
        ]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
