"""Tests for the SpeculativeRequest early-continue optimization.

These tests verify that when on_speculation_response returns FlowControl.CONTINUE,
the generator is immediately resumed without waiting for the HTTP response.
This allows all SpeculativeRequests to be enqueued upfront before any HTTP
requests are made.

Key behaviors tested:
1. CONTINUE: Generator resumed immediately with True, HTTP request enqueued
2. STOP: Generator resumed immediately with False, NO HTTP request made
3. AWAIT_MORE_INFO: Generator parked, callback called again after HTTP response
"""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

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
from juriscraper.scraper_driver.driver.dev_driver.dev_driver import (
    LocalDevDriver,
)
from juriscraper.scraper_driver.driver.dev_driver.speculation import (
    FlowControl,
)


class EarlyContinueScraper(BaseScraper[dict[str, Any]]):
    """Scraper to test early-continue optimization.

    Flow: get_entry() -> generate_speculation() -> blow_up()

    generate_speculation() yields 3 SpeculativeRequests with speculative_ids 1, 2, 3.
    The on_speculation_response handler returns CONTINUE for id <= 3, STOP otherwise.
    blow_up() raises an Exception("Blown up").

    This tests that all 3 SpeculativeRequests are enqueued before the Exception is raised.
    """

    def __init__(self) -> None:
        super().__init__()
        self._params = ScraperParams()
        self.requests_yielded: list[int] = []
        self.blow_up_called = False

    def get_entry(self) -> Generator[NavigatingRequest, None, None]:
        yield NavigatingRequest(
            request=HTTPRequestParams(
                method=HttpMethod.GET,
                url="https://example.com/entry",
            ),
            continuation="generate_speculation",
        )

    @step(speculative=True)
    def generate_speculation(
        self, response: Response, speculative_id: int = 1
    ) -> Generator[ScraperYield, bool | None, None]:
        """Generate 3 SpeculativeRequests with ids 1, 2, 3."""
        for spec_id in range(1, 4):
            self.requests_yielded.append(spec_id)
            should_continue = yield SpeculativeRequest(
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url=f"https://example.com/spec/{spec_id}",
                ),
                continuation="blow_up",
                speculative_id=spec_id,
            )
            if not should_continue:
                break

    @step
    def blow_up(
        self, response: Response
    ) -> Generator[ScraperYield, None, None]:
        """Continuation that raises an exception."""
        self.blow_up_called = True
        raise Exception("Blown up")
        yield  # Never reached, but needed for generator


@pytest.fixture
async def db_path(tmp_path: Path) -> Path:
    """Create a temporary database path."""
    return tmp_path / "test_early_continue.db"


class TestEarlyContinueOptimization:
    """Tests for the early-continue optimization in SpeculativeRequest handling."""

    async def test_all_speculative_requests_enqueued_before_exception(
        self, db_path: Path
    ) -> None:
        """Test that all SpeculativeRequests are enqueued before blow_up() is called.

        This verifies the early-continue optimization:
        1. Entry request to /entry completes
        2. generate_speculation() yields 3 SpeculativeRequests
        3. on_speculation_response(None, ...) returns CONTINUE for each (ids 1, 2, 3)
        4. All 3 requests should be enqueued BEFORE any HTTP requests are made
        5. When the HTTP responses arrive, blow_up() is called and raises Exception

        The key assertion is that requests_yielded contains [1, 2, 3] even though
        blow_up() will raise an exception when the first speculative request completes.
        """
        scraper = EarlyContinueScraper()
        exception_raised = False
        callback_calls: list[tuple[int, bool]] = []  # (spec_id, has_response)

        async def speculation_callback(
            response: Response | None,
            continuation_name: str,
            speculative_id: int,
        ) -> FlowControl:
            """Return CONTINUE for ids <= 3, STOP otherwise."""
            callback_calls.append((speculative_id, response is not None))
            if speculative_id <= 3:
                return FlowControl.CONTINUE
            return FlowControl.STOP

        async with LocalDevDriver.open(
            scraper,
            db_path,
            on_speculation_response=speculation_callback,
            base_delay=0.0,
            jitter=0.0,
            num_workers=1,
        ) as driver:
            call_count = 0

            def make_response(**kwargs):
                nonlocal call_count
                call_count += 1
                mock = MagicMock()
                mock.status_code = 200
                mock.headers = {}
                mock.content = b"test content"
                mock.text = "test content"
                return mock

            driver.request_manager._client = MagicMock()
            driver.request_manager._client.request = AsyncMock(
                side_effect=make_response
            )

            # Run and expect the exception from blow_up()
            try:
                await driver.run()
            except Exception as e:
                if "Blown up" in str(e):
                    exception_raised = True
                else:
                    raise

        # Key assertion: all 3 speculative requests were yielded
        # This proves early-continue worked - the generator continued
        # yielding all requests without waiting for HTTP responses
        assert scraper.requests_yielded == [1, 2, 3], (
            f"Expected all 3 speculative requests to be yielded, got {scraper.requests_yielded}"
        )

        # Verify callbacks were called with response=None (early check)
        # All 3 should be called BEFORE any HTTP requests
        early_calls = [
            (id, has_resp) for id, has_resp in callback_calls if not has_resp
        ]
        assert len(early_calls) == 3, (
            f"Expected 3 early callback calls (response=None), got {len(early_calls)}"
        )

        # Verify blow_up was called (exception was raised from the continuation)
        assert exception_raised or scraper.blow_up_called, (
            "Expected blow_up() to be called and raise an exception"
        )

    async def test_early_continue_with_stop_at_threshold(
        self, db_path: Path
    ) -> None:
        """Test that STOP halts iteration immediately without HTTP request.

        When on_speculation_response returns STOP for a speculative_id,
        the generator should receive False and stop yielding more requests.
        No HTTP request should be made for the STOP'd request.
        """
        scraper = EarlyContinueScraper()
        http_urls: list[str] = []

        async def speculation_callback(
            response: Response | None,
            continuation_name: str,
            speculative_id: int,
        ) -> FlowControl:
            """Return CONTINUE for id=1, STOP for id=2+."""
            if speculative_id <= 1:
                return FlowControl.CONTINUE
            return FlowControl.STOP

        async with LocalDevDriver.open(
            scraper,
            db_path,
            on_speculation_response=speculation_callback,
            base_delay=0.0,
            jitter=0.0,
            num_workers=1,
        ) as driver:

            async def make_response(method, url, **kwargs):
                http_urls.append(url)
                mock = MagicMock()
                mock.status_code = 200
                mock.headers = {}
                mock.content = b"test content"
                mock.text = "test content"
                return mock

            driver.request_manager._client = MagicMock()
            driver.request_manager._client.request = AsyncMock(
                side_effect=make_response
            )

            try:
                await driver.run()
            except Exception:
                pass  # Exception from blow_up is expected

        # Only requests 1 and 2 should be yielded
        # Request 1 gets CONTINUE, request 2 gets STOP
        # Generator receives False for id=2 and breaks
        assert scraper.requests_yielded == [1, 2], (
            f"Expected requests [1, 2] to be yielded (2 triggers STOP), got {scraper.requests_yielded}"
        )

        # Verify NO HTTP request was made for spec/2 (STOP means no HTTP)
        spec_urls = [u for u in http_urls if "spec/" in u]
        assert len(spec_urls) == 1, (
            f"Expected only 1 speculative HTTP request (for id=1), got {len(spec_urls)}: {spec_urls}"
        )
        assert "spec/1" in spec_urls[0], (
            f"Expected HTTP request for spec/1, got {spec_urls}"
        )

    async def test_await_more_info_parks_generator(
        self, db_path: Path
    ) -> None:
        """Test that AWAIT_MORE_INFO parks the generator until response arrives.

        When on_speculation_response returns AWAIT_MORE_INFO, the generator
        should be parked and only resumed after the HTTP response is received.

        For 2xx responses, the callback is NOT called again - the driver
        automatically continues. The callback is only called twice (early + response)
        for non-2xx responses.
        """

        class AwaitInfoScraper(BaseScraper[dict[str, Any]]):
            """Scraper that tracks when yields happen vs responses."""

            def __init__(self) -> None:
                super().__init__()
                self._params = ScraperParams()
                self.event_log: list[str] = []

            def get_entry(self) -> Generator[NavigatingRequest, None, None]:
                yield NavigatingRequest(
                    request=HTTPRequestParams(
                        method=HttpMethod.GET,
                        url="https://example.com/entry",
                    ),
                    continuation="generate_speculation",
                )

            @step(speculative=True)
            def generate_speculation(
                self, response: Response, speculative_id: int = 1
            ) -> Generator[ScraperYield, bool | None, None]:
                for spec_id in range(1, 3):
                    self.event_log.append(f"yield_{spec_id}")
                    should_continue = yield SpeculativeRequest(
                        request=HTTPRequestParams(
                            method=HttpMethod.GET,
                            url=f"https://example.com/spec/{spec_id}",
                        ),
                        continuation="process",
                        speculative_id=spec_id,
                    )
                    self.event_log.append(
                        f"resumed_{spec_id}_{should_continue}"
                    )
                    if not should_continue:
                        break

            @step
            def process(
                self, response: Response
            ) -> Generator[ScraperYield, None, None]:
                self.event_log.append(f"process_{response.url}")
                yield ParsedData({"url": response.url})

        scraper = AwaitInfoScraper()
        callback_sequence: list[str] = []

        async def speculation_callback(
            response: Response | None,
            continuation_name: str,
            speculative_id: int,
        ) -> FlowControl:
            """Always return AWAIT_MORE_INFO to test parking."""
            callback_sequence.append(
                f"callback_{speculative_id}_{'with_response' if response else 'no_response'}"
            )
            if response is None:
                return FlowControl.AWAIT_MORE_INFO
            # With response, continue
            return FlowControl.CONTINUE

        async with LocalDevDriver.open(
            scraper,
            db_path,
            on_speculation_response=speculation_callback,
            base_delay=0.0,
            jitter=0.0,
            num_workers=1,
        ) as driver:

            def make_response(**kwargs):
                mock = MagicMock()
                mock.status_code = (
                    200  # 2xx response - callback NOT called again
                )
                mock.headers = {}
                mock.content = b"test content"
                mock.text = "test content"
                return mock

            driver.request_manager._client = MagicMock()
            driver.request_manager._client.request = AsyncMock(
                side_effect=make_response
            )

            await driver.run()

        # With AWAIT_MORE_INFO and 2xx response:
        # - Callback is called with response=None (early check) -> returns AWAIT_MORE_INFO
        # - Generator is parked, HTTP request is made
        # - HTTP returns 2xx -> driver automatically continues (callback NOT called again)
        assert "callback_1_no_response" in callback_sequence, (
            "Should have early check for id=1"
        )
        # For 2xx responses, callback is NOT called again
        assert "callback_1_with_response" not in callback_sequence, (
            "For 2xx responses, callback should NOT be called again"
        )

        # Event log should show yield -> resumed pattern
        # The generator was parked, then resumed after HTTP response
        assert "yield_1" in scraper.event_log
        assert "resumed_1_True" in scraper.event_log

    async def test_await_more_info_with_non_2xx_calls_callback_again(
        self, db_path: Path
    ) -> None:
        """Test that AWAIT_MORE_INFO with non-2xx response calls callback twice.

        For non-2xx responses, the callback is called:
        1. First with response=None (early check) -> AWAIT_MORE_INFO
        2. Second with actual response (to decide continue/stop)
        """

        class NonSuccessScraper(BaseScraper[dict[str, Any]]):
            """Scraper for testing non-2xx response handling."""

            def __init__(self) -> None:
                super().__init__()
                self._params = ScraperParams()
                self.event_log: list[str] = []

            def get_entry(self) -> Generator[NavigatingRequest, None, None]:
                yield NavigatingRequest(
                    request=HTTPRequestParams(
                        method=HttpMethod.GET,
                        url="https://example.com/entry",
                    ),
                    continuation="generate_speculation",
                )

            @step(speculative=True)
            def generate_speculation(
                self, response: Response, speculative_id: int = 1
            ) -> Generator[ScraperYield, bool | None, None]:
                self.event_log.append("yield_1")
                should_continue = yield SpeculativeRequest(
                    request=HTTPRequestParams(
                        method=HttpMethod.GET,
                        url="https://example.com/spec/1",
                    ),
                    continuation="process",
                    speculative_id=1,
                )
                self.event_log.append(f"resumed_1_{should_continue}")

            @step
            def process(
                self, response: Response
            ) -> Generator[ScraperYield, None, None]:
                self.event_log.append("process")
                yield ParsedData({"status": response.status_code})

        scraper = NonSuccessScraper()
        callback_sequence: list[str] = []

        async def speculation_callback(
            response: Response | None,
            continuation_name: str,
            speculative_id: int,
        ) -> FlowControl:
            """Return AWAIT_MORE_INFO early, then CONTINUE with response."""
            callback_sequence.append(
                f"callback_{speculative_id}_{'with_response' if response else 'no_response'}"
            )
            if response is None:
                return FlowControl.AWAIT_MORE_INFO
            return FlowControl.CONTINUE

        async with LocalDevDriver.open(
            scraper,
            db_path,
            on_speculation_response=speculation_callback,
            base_delay=0.0,
            jitter=0.0,
            num_workers=1,
        ) as driver:

            def make_response(**kwargs):
                mock = MagicMock()
                mock.status_code = 404  # Non-2xx response
                mock.headers = {}
                mock.content = b"Not found"
                mock.text = "Not found"
                return mock

            driver.request_manager._client = MagicMock()
            driver.request_manager._client.request = AsyncMock(
                side_effect=make_response
            )

            await driver.run()

        # For non-2xx responses with AWAIT_MORE_INFO:
        # Callback is called twice: once early, once with response
        assert "callback_1_no_response" in callback_sequence, (
            "Should have early check for id=1"
        )
        assert "callback_1_with_response" in callback_sequence, (
            "Should have response check for id=1 (non-2xx)"
        )

        # Generator should have been resumed
        assert "resumed_1_True" in scraper.event_log, (
            "Generator should have been resumed with True"
        )

    async def test_early_continue_all_requests_enqueued_before_http(
        self, db_path: Path
    ) -> None:
        """Test that with CONTINUE, all requests are enqueued before HTTP requests execute.

        This is the core optimization test: with early-continue, the generator
        should yield all 3 requests before any of them start making HTTP calls.
        """

        class TrackingScraper(BaseScraper[dict[str, Any]]):
            """Scraper that tracks the order of operations."""

            def __init__(self) -> None:
                super().__init__()
                self._params = ScraperParams()
                self.event_log: list[str] = []

            def get_entry(self) -> Generator[NavigatingRequest, None, None]:
                yield NavigatingRequest(
                    request=HTTPRequestParams(
                        method=HttpMethod.GET,
                        url="https://example.com/entry",
                    ),
                    continuation="generate_speculation",
                )

            @step(speculative=True)
            def generate_speculation(
                self, response: Response, speculative_id: int = 1
            ) -> Generator[ScraperYield, bool | None, None]:
                for spec_id in range(1, 4):
                    self.event_log.append(f"yield_{spec_id}")
                    should_continue = yield SpeculativeRequest(
                        request=HTTPRequestParams(
                            method=HttpMethod.GET,
                            url=f"https://example.com/spec/{spec_id}",
                        ),
                        continuation="process",
                        speculative_id=spec_id,
                    )
                    if not should_continue:
                        break

            @step
            def process(
                self, response: Response
            ) -> Generator[ScraperYield, None, None]:
                # Extract spec_id from URL
                spec_id = response.url.split("/")[-1]
                self.event_log.append(f"process_{spec_id}")
                yield ParsedData({"id": spec_id})

        scraper = TrackingScraper()

        async def speculation_callback(
            response: Response | None,
            continuation_name: str,
            speculative_id: int,
        ) -> FlowControl:
            """Always return CONTINUE for early optimization."""
            return FlowControl.CONTINUE

        async with LocalDevDriver.open(
            scraper,
            db_path,
            on_speculation_response=speculation_callback,
            base_delay=0.0,
            jitter=0.0,
            num_workers=1,
        ) as driver:

            async def make_response_async(method, url, **kwargs):
                scraper.event_log.append(f"http_{url.split('/')[-1]}")
                mock = MagicMock()
                mock.status_code = 200
                mock.headers = {}
                mock.content = b"test content"
                mock.text = "test content"
                return mock

            driver.request_manager._client = MagicMock()
            driver.request_manager._client.request = AsyncMock(
                side_effect=make_response_async
            )

            await driver.run()

        # All 3 speculative requests should have been yielded
        yield_events = [e for e in scraper.event_log if e.startswith("yield_")]
        assert yield_events == ["yield_1", "yield_2", "yield_3"], (
            f"Expected all yields in order, got {yield_events}"
        )

        # Find when yields happened vs HTTP requests
        # Entry HTTP happens first, then all yields should happen before speculative HTTPs
        entry_http_idx = scraper.event_log.index("http_entry")
        yield_1_idx = scraper.event_log.index("yield_1")
        yield_2_idx = scraper.event_log.index("yield_2")
        yield_3_idx = scraper.event_log.index("yield_3")

        # All yields should happen after entry HTTP
        assert yield_1_idx > entry_http_idx, (
            "yield_1 should be after entry HTTP"
        )
        assert yield_2_idx > entry_http_idx, (
            "yield_2 should be after entry HTTP"
        )
        assert yield_3_idx > entry_http_idx, (
            "yield_3 should be after entry HTTP"
        )

        # Yields should be consecutive (early-continue means no HTTP between them)
        assert yield_2_idx == yield_1_idx + 1, (
            f"yield_2 should immediately follow yield_1, got event_log: {scraper.event_log}"
        )
        assert yield_3_idx == yield_2_idx + 1, (
            f"yield_3 should immediately follow yield_2, got event_log: {scraper.event_log}"
        )
