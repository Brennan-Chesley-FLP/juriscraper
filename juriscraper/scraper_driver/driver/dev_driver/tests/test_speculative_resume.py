"""Tests for speculative request timeout and retry behavior.

These tests verify that speculative requests properly handle timeouts
and retries, using a real aiohttp server to simulate slow responses.
"""

from __future__ import annotations

import asyncio
from collections.abc import Generator
from pathlib import Path
from typing import Any

import pytest
from aiohttp import web

from juriscraper.scraper_driver.common.decorators import step
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


@pytest.fixture
async def db_path(tmp_path: Path) -> Path:
    """Create a temporary database path."""
    return tmp_path / "test_speculative.db"


class DelayServer:
    """Test server that delays responses based on query parameter."""

    def __init__(self) -> None:
        self.request_log: list[dict[str, Any]] = []
        self.app = web.Application()
        self.app.router.add_get("/{id}", self.handle_request)
        self.runner: web.AppRunner | None = None
        self.site: web.TCPSite | None = None
        self.port: int = 0

    async def handle_request(self, request: web.Request) -> web.Response:
        """Handle request with configurable delay."""
        request_id = request.match_info["id"]
        timeout_str = request.query.get("t", "0")
        timeout = float(timeout_str)

        # Log the request
        self.request_log.append(
            {
                "id": request_id,
                "timeout": timeout,
                "path": str(request.path),
                "query": dict(request.query),
            }
        )

        # Wait for the specified time
        await asyncio.sleep(timeout)

        return web.Response(text="Found", status=200)

    async def start(self) -> str:
        """Start the server and return the base URL."""
        self.runner = web.AppRunner(self.app)
        await self.runner.setup()
        self.site = web.TCPSite(self.runner, "127.0.0.1", 0)
        await self.site.start()

        # Get the actual port
        assert self.site._server is not None
        sockets = self.site._server.sockets
        assert sockets
        self.port = sockets[0].getsockname()[1]

        return f"http://127.0.0.1:{self.port}"

    async def stop(self) -> None:
        """Stop the server."""
        if self.runner:
            await self.runner.cleanup()

    def get_requests_for_id(self, request_id: str) -> list[dict[str, Any]]:
        """Get all requests made for a specific ID."""
        return [r for r in self.request_log if r["id"] == request_id]

    def get_request_count(self) -> int:
        """Get total number of requests."""
        return len(self.request_log)


@pytest.fixture
async def delay_server():
    """Create and manage the delay server."""
    server = DelayServer()
    await server.start()
    yield server
    await server.stop()


class SpeculativeTimeoutScraper(BaseScraper[dict[str, Any]]):
    """Scraper that makes speculative requests with increasing timeouts.

    Makes requests with delays (using short times for fast tests):
    - /1?t=0.1 (entry point, 0.1 second)
    - /2?t=0.2 (speculative, 0.2 seconds)
    - /3?t=0.3 (speculative, 0.3 seconds)
    - /4?t=10 (speculative, 10 seconds - will timeout with 1s configured timeout)
    """

    def __init__(self, base_url: str) -> None:
        super().__init__()
        self.base_url = base_url

    def get_entry(self) -> Generator[NavigatingRequest, None, None]:
        yield NavigatingRequest(
            request=HTTPRequestParams(
                method=HttpMethod.GET,
                url=f"{self.base_url}/1?t=0.1",
            ),
            continuation="parse_with_speculation",
            current_location="",
        )

    @step(speculative=True)
    def parse_with_speculation(
        self, response: Response, speculative_id: int = 2
    ) -> Generator[SpeculativeRequest | ParsedData, bool, None]:
        """Parse and yield speculative requests with increasing timeouts.

        Yields speculative requests for:
        - /2?t=0.2 (speculative_id=2, fast)
        - /3?t=0.3 (speculative_id=3, fast)
        - /4?t=10 (speculative_id=4, will timeout with 5s httpx default)
        """
        # Delay times: fast for first two, then one that times out
        delays = {2: 0.2, 3: 0.3, 4: 10}

        while speculative_id <= 4:
            delay = delays.get(speculative_id, 0.1)
            # Yield a speculative request
            should_continue = yield SpeculativeRequest(
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url=f"{self.base_url}/{speculative_id}?t={delay}",
                ),
                continuation=self.surface_response,
                current_location=response.url,
                speculative_id=speculative_id,
            )

            if not should_continue:
                # If request failed/timed out, stop speculation
                break

            speculative_id += 1

    @step
    def surface_response(
        self, response: Response
    ) -> Generator[ParsedData, None, None]:
        """Check if speculative request found something.

        Returns True if we got a 200 response with "Found" to continue speculation.
        """
        yield ParsedData(
            {"found": response.status_code == 200 and "Found" in response.text}
        )


@pytest.mark.slow
class TestSpeculativeTimeoutRetry:
    """Tests for speculative request timeout behavior.

    Note: Speculative requests do NOT retry on transient errors. Instead, when a
    speculative request times out:
    1. The on_transient_exception callback is called
    2. If it returns True (continue), the generator is resumed with False
    3. The request is marked completed (not failed)

    This differs from regular requests which retry with exponential backoff.
    """

    async def test_speculative_requests_with_timeouts(
        self, db_path: Path, delay_server: DelayServer
    ) -> None:
        """Test that speculative requests handle timeouts correctly.

        This test verifies:
        1. Entry request /1?t=0.1 completes successfully (0.1s delay)
        2. Speculative requests /2?t=0.2 and /3?t=0.3 complete (fast)
        3. Speculative request /4?t=10 times out (10s > 1s configured timeout)
        4. The timeout triggers on_transient_exception callback
        5. Speculation stops (no retry) and scraper completes gracefully
        """
        from juriscraper.scraper_driver.common.exceptions import (
            TransientException,
        )

        base_url = f"http://127.0.0.1:{delay_server.port}"
        scraper = SpeculativeTimeoutScraper(base_url)

        # Track transient exceptions observed
        transient_errors: list[TransientException] = []

        async def on_transient_handler(e: TransientException) -> bool:
            """Handle transient exceptions - continue scraping."""
            transient_errors.append(e)
            return True  # Continue scraping (stop speculation gracefully)

        # Use timeout=1.0 so that requests taking >1s will timeout
        async with LocalDevDriver.open(
            scraper,
            db_path,
            max_backoff_time=10.0,
            initial_rate=100.0,
            timeout=1.0,  # 1 second timeout
            enable_monitor=False,
        ) as driver:
            driver.on_transient_exception = on_transient_handler
            await driver.run()

            assert driver.db.db is not None

            # Verify requests were made to the server
            # Entry point /1?t=0.1
            entry_requests = delay_server.get_requests_for_id("1")
            assert len(entry_requests) >= 1, (
                "Should have at least 1 entry request"
            )

            # Speculative /2?t=0.2 (should succeed, fast)
            spec_2_requests = delay_server.get_requests_for_id("2")
            assert len(spec_2_requests) >= 1, "Should have made request to /2"

            # Speculative /3?t=0.3 (should succeed, fast)
            spec_3_requests = delay_server.get_requests_for_id("3")
            assert len(spec_3_requests) >= 1, "Should have made request to /3"

            # Speculative /4?t=10 (should timeout, NO retries for speculative)
            spec_4_requests = delay_server.get_requests_for_id("4")
            # Speculative requests don't retry - they stop speculation on transient errors
            assert len(spec_4_requests) == 1, (
                f"Speculative request should NOT retry, expected 1 attempt, "
                f"got {len(spec_4_requests)}"
            )

            # Verify transient exception was observed
            assert len(transient_errors) >= 1, (
                "Should have observed at least one transient exception"
            )

            # Verify database state
            cursor = await driver.db.db.execute(
                """
                SELECT url, status, retry_count, cumulative_backoff
                FROM requests
                WHERE url LIKE '%/4?t=10%'
                """
            )
            rows = await cursor.fetchall()

            # Should have exactly one request record for /4
            assert len(rows) == 1, (
                "Should have exactly one request record for /4"
            )

            url, status, retry_count, cumulative_backoff = rows[0]

            # For speculative requests, transient errors mark as completed (not failed)
            # because the speculation was handled gracefully
            assert status == "completed", (
                f"Speculative request with handled transient error should be "
                f"completed, got {status}"
            )

            # No retries for speculative requests
            assert retry_count == 0, (
                f"Speculative request should have 0 retries, got {retry_count}"
            )

            # Log summary for debugging
            print("\nServer request log:")
            for req in delay_server.request_log:
                print(f"  {req}")

            print("\nDatabase request for /4:")
            print(f"  url={url}, status={status}, retries={retry_count}")

            print(
                f"\nTotal server requests: {delay_server.get_request_count()}"
            )
            print(f"Transient errors observed: {len(transient_errors)}")

    async def test_speculative_timeout_respects_max_backoff(
        self, db_path: Path, delay_server: DelayServer
    ) -> None:
        """Test that speculative requests respect max_backoff_time limit.

        With a lower max_backoff_time, retries should stop sooner.
        """
        base_url = f"http://127.0.0.1:{delay_server.port}"

        # Simple scraper that just makes one request that will timeout
        class SingleTimeoutScraper(BaseScraper[dict[str, Any]]):
            def get_entry(self) -> Generator[NavigatingRequest, None, None]:
                yield NavigatingRequest(
                    request=HTTPRequestParams(
                        method=HttpMethod.GET,
                        url=f"{base_url}/timeout?t=10",  # 10s > 1s timeout
                    ),
                    continuation="parse",
                    current_location="",
                )

            @step
            def parse(self, response: Response):
                yield ParsedData({"found": True})

        scraper = SingleTimeoutScraper()

        # Use a very short max_backoff_time so we fail quickly
        # Use timeout=1.0 so requests taking >1s will timeout
        async with LocalDevDriver.open(
            scraper,
            db_path,
            max_backoff_time=5.0,  # Only 5 seconds of total backoff allowed
            initial_rate=100.0,
            timeout=1.0,  # 1 second timeout
            enable_monitor=False,
        ) as driver:
            await driver.run()

            assert driver.db.db is not None

            # Check the request was marked as failed
            cursor = await driver.db.db.execute(
                """
                SELECT status, retry_count, cumulative_backoff
                FROM requests
                WHERE url LIKE '%/timeout%'
                """
            )
            row = await cursor.fetchone()

            assert row is not None, "Should have request record"
            status, retry_count, cumulative_backoff = row

            assert status == "failed", f"Expected failed status, got {status}"
            # With max_backoff_time=5, we should have limited retries
            # Backoff is 1s, 2s = 3s (under 5), then 4s would push to 7s (over 5)
            # So we get 2 retries before exceeding max, but the 3rd retry is attempted
            # and then fails because cumulative would exceed. Can be up to 4 retries
            # depending on timing.
            assert retry_count <= 5, (
                f"Should have limited retries with max_backoff=5, got {retry_count}"
            )

            # Verify server received the expected number of attempts
            timeout_requests = delay_server.get_requests_for_id("timeout")
            # Initial attempt + retries
            expected_min = retry_count + 1
            assert len(timeout_requests) >= expected_min, (
                f"Server should have received at least {expected_min} requests, "
                f"got {len(timeout_requests)}"
            )


class FastServer:
    """Test server that responds immediately with status based on path."""

    def __init__(self) -> None:
        self.request_log: list[dict[str, Any]] = []
        self.app = web.Application()
        self.app.router.add_get("/{id}", self.handle_request)
        self.runner: web.AppRunner | None = None
        self.site: web.TCPSite | None = None
        self.port: int = 0

    async def handle_request(self, request: web.Request) -> web.Response:
        """Handle request - always succeeds immediately."""
        request_id = request.match_info["id"]

        # Log the request
        self.request_log.append(
            {
                "id": request_id,
                "path": str(request.path),
                "query": dict(request.query),
            }
        )

        return web.Response(text=f"Found {request_id}", status=200)

    async def start(self) -> str:
        """Start the server and return the base URL."""
        self.runner = web.AppRunner(self.app)
        await self.runner.setup()
        self.site = web.TCPSite(self.runner, "127.0.0.1", 0)
        await self.site.start()

        # Get the actual port
        assert self.site._server is not None
        sockets = self.site._server.sockets
        assert sockets
        self.port = sockets[0].getsockname()[1]

        return f"http://127.0.0.1:{self.port}"

    async def stop(self) -> None:
        """Stop the server."""
        if self.runner:
            await self.runner.cleanup()

    def get_requests_for_id(self, request_id: str) -> list[dict[str, Any]]:
        """Get all requests made for a specific ID."""
        return [r for r in self.request_log if r["id"] == request_id]

    def get_request_count(self) -> int:
        """Get total number of requests."""
        return len(self.request_log)

    def clear_log(self) -> None:
        """Clear the request log."""
        self.request_log.clear()


@pytest.fixture
async def fast_server():
    """Create and manage the fast server."""
    server = FastServer()
    await server.start()
    yield server
    await server.stop()


class ResumableScraper(BaseScraper[dict[str, Any]]):
    """Scraper that makes speculative requests and can be resumed.

    Makes requests to /entry, then speculative requests to /10, /20, /30, /40.
    """

    def __init__(self, base_url: str, params: Any | None = None) -> None:
        super().__init__(params=params)
        self.base_url = base_url
        self.data_emitted: list[dict[str, Any]] = []

    def get_entry(self) -> Generator[NavigatingRequest, None, None]:
        yield NavigatingRequest(
            request=HTTPRequestParams(
                method=HttpMethod.GET,
                url=f"{self.base_url}/entry",
            ),
            continuation="parse_with_speculation",
            current_location="",
        )

    @step(speculative=True)
    def parse_with_speculation(
        self, response: Response, speculative_id: int
    ) -> Generator[ScraperYield, bool | None, None]:
        """Parse and yield speculative requests.

        Yields speculative requests for /10, /20, /30, /40.
        If speculative_id > 10, starts from that ID instead.
        """
        # Start from the provided speculative_id or default to 10
        current_id = max(speculative_id, 10)

        while current_id <= 40:
            # Yield a speculative request
            found = yield SpeculativeRequest(
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url=f"{self.base_url}/{current_id}",
                ),
                continuation="check_speculative",
                current_location=response.url,
                speculative_id=current_id,
            )

            if not found:
                break

            current_id += 10

        # Yield final result
        yield ParsedData(
            {"last_speculative_id": current_id - 10, "completed": True}
        )

    def check_speculative(
        self, response: Response
    ) -> Generator[ParsedData, None, None]:
        """Check speculative request and emit data."""
        spec_id = int(response.url.split("/")[-1])
        data = {"speculative_id": spec_id, "found": "Found" in response.text}
        self.data_emitted.append(data)
        yield ParsedData(data)


@pytest.mark.slow
class TestSpeculativeResume:
    """Tests for speculative request stop and resume behavior."""

    async def test_speculative_stop_and_resume(
        self, tmp_path: Path, fast_server: FastServer
    ) -> None:
        """Test stopping the driver after data emission and resuming.

        This test verifies:
        1. First run starts from entry, makes speculative requests to /10, /20
        2. After receiving data for /20, we stop the driver
        3. Second run starts with speculative_id=20, continues with /30, /40
        4. All expected requests are made across both runs

        Note: This test uses separate databases for each run since generator
        state cannot be serialized across process restarts. The speculative_id
        parameter mechanism is used to resume from the correct position.
        """
        base_url = f"http://127.0.0.1:{fast_server.port}"

        # Track data emissions and last speculative_id
        data_received: list[dict[str, Any]] = []
        last_speculative_id: int | None = None
        stop_after_id = 20  # Stop after receiving data for this ID
        driver_ref: list[
            LocalDevDriver
        ] = []  # Reference to driver for stopping

        async def on_data_callback(data: dict[str, Any]) -> None:
            nonlocal last_speculative_id
            data_received.append(data)
            if "speculative_id" in data:
                last_speculative_id = data["speculative_id"]
                # Stop when we hit target
                if (
                    last_speculative_id
                    and last_speculative_id >= stop_after_id
                    and driver_ref
                ):
                    driver_ref[0].stop()

        # --- First run: Start fresh, stop after speculative_id=20 ---
        db_path1 = tmp_path / "test_resume_1.db"
        scraper1 = ResumableScraper(base_url)

        async with LocalDevDriver.open(
            scraper1,
            db_path1,
            initial_rate=100.0,
            enable_monitor=False,
        ) as driver1:
            driver_ref.append(driver1)
            driver1.on_data = on_data_callback

            await driver1.run()

            # Verify first run state
            progress = await driver1.get_speculative_progress(
                "parse_with_speculation"
            )
            print(f"\nFirst run progress: {progress}")
            print(f"First run data received: {data_received}")
            print(f"First run server requests: {fast_server.request_log}")

        # Verify first run made expected requests
        assert len(fast_server.get_requests_for_id("entry")) >= 1, (
            "Should have made entry request"
        )
        assert len(fast_server.get_requests_for_id("10")) >= 1, (
            "Should have made request to /10"
        )
        assert len(fast_server.get_requests_for_id("20")) >= 1, (
            "Should have made request to /20"
        )

        # Record first run request count
        first_run_requests = fast_server.get_request_count()
        print(f"First run total requests: {first_run_requests}")

        # Clear request log for second run
        fast_server.clear_log()
        data_received.clear()
        driver_ref.clear()

        # --- Second run: Start from saved speculative_id ---
        assert last_speculative_id is not None, (
            "Should have received speculative_id"
        )

        # Create new scraper with starting point configured
        # Use a new database - we're simulating a restart
        db_path2 = tmp_path / "test_resume_2.db"
        params = ResumableScraper.params()
        params.speculative.parse_with_speculation = last_speculative_id
        scraper2 = ResumableScraper(base_url, params=params)

        # Reset callback to not stop
        async def on_data_callback_no_stop(data: dict[str, Any]) -> None:
            data_received.append(data)

        async with LocalDevDriver.open(
            scraper2,
            db_path2,
            initial_rate=100.0,
            enable_monitor=False,
        ) as driver2:
            driver2.on_data = on_data_callback_no_stop
            await driver2.run()

            final_progress = await driver2.get_speculative_progress(
                "parse_with_speculation"
            )
            print(f"\nSecond run progress: {final_progress}")
            print(f"Second run data received: {data_received}")
            print(f"Second run server requests: {fast_server.request_log}")

        # Verify second run made remaining requests
        # Entry is called to trigger the speculative step
        assert len(fast_server.get_requests_for_id("entry")) >= 1, (
            "Should have made entry request on resume"
        )

        # Should have continued from where we left off
        # The speculative step starts from last_speculative_id (20)
        # Since 20 is max(20, 10) = 20, it will process 20, 30, 40
        # The first request is for 20 again (which is fine for this test)
        assert len(fast_server.get_requests_for_id("30")) >= 1, (
            "Should have made request to /30 after resume"
        )
        assert len(fast_server.get_requests_for_id("40")) >= 1, (
            "Should have made request to /40 after resume"
        )

        # Final progress should be 40
        assert final_progress == 40, (
            f"Expected final progress to be 40, got {final_progress}"
        )

        # Verify we got data for expected IDs in second run
        second_run_spec_ids = [
            d["speculative_id"]
            for d in scraper2.data_emitted
            if "speculative_id" in d
        ]
        print(f"Second run speculative IDs: {second_run_spec_ids}")

        # Second run should have 20 (starting point), 30, 40
        assert 30 in second_run_spec_ids, (
            "Should have data for /30 in second run"
        )
        assert 40 in second_run_spec_ids, (
            "Should have data for /40 in second run"
        )

        # Verify first run had correct IDs
        first_run_spec_ids = [
            d["speculative_id"]
            for d in scraper1.data_emitted
            if "speculative_id" in d
        ]
        print(f"First run speculative IDs: {first_run_spec_ids}")

        assert 10 in first_run_spec_ids, (
            "Should have data for /10 in first run"
        )
        # Note: 20 might not be in first run if stopped before data callback completed
        # but should have the progress saved
