"""Tests for LocalDevDriver with a forked scraper and speculation handling.

This test creates an HTTP echo server and a scraper that follows two forked paths:
1. get_entry -> landing -> letters -> letter
2. get_entry -> landing -> numbers -> number

The numbers path uses SpeculativeRequest with the standard speculation handler.
The test verifies that speculation correctly limits how many 404s are tolerated.

The echo server returns 404 for numbers where (ii // 10) > (ii % 10):
- 1-9: 200 (tens digit 0 is not > ones digit)
- 10: 404 (1 > 0)
- 11-19: 200 (1 is not > 1-9)
- 20-21: 404 (2 > 0, 2 > 1)
- 22-29: 200 (2 is not > 2-9)
- 30-32: 404 (3 > 0, 3 > 1, 3 > 2)
- etc.

This creates "gaps" of consecutive 404s that require speculation to cross.
"""

from __future__ import annotations

from asyncio.log import logger
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
from juriscraper.scraper_driver.driver.dev_driver.speculation import (
    create_speculation_handler,
)


class EchoServer:
    """Test server that echoes the path and returns 404 based on number logic.

    For any path /{echo}:
    - Returns the echo value as the response body
    - If echo is an integer ii, returns 404 if (ii // 10) > (ii % 10)

    This creates a predictable pattern of 404s:
    - 10 is a 404 (1 > 0)
    - 20, 21 are 404s (2 > 0, 2 > 1)
    - 30, 31, 32 are 404s (3 > 0, 3 > 1, 3 > 2)
    - etc.
    """

    def __init__(self) -> None:
        self.request_log: list[dict[str, Any]] = []
        self.app = web.Application()
        self.app.router.add_get("/{echo}", self.handle_request)
        self.runner: web.AppRunner | None = None
        self.site: web.TCPSite | None = None
        self.port: int = 0

    async def handle_request(self, request: web.Request) -> web.Response:
        """Handle request - echo the path segment.

        For numeric paths, return 404 if (ii // 10) > (ii % 10).
        """
        echo = request.match_info["echo"]

        # Log the request
        self.request_log.append({"echo": echo, "path": str(request.path)})

        # Check if it's a number
        try:
            ii = int(echo)
            # Return 404 if (ii // 10) > (ii % 10)
            if (ii // 10) > (ii % 10):
                return web.Response(text=echo, status=404)
        except ValueError:
            pass  # Not a number, just echo it

        return web.Response(text=echo, status=200)

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

    def get_requests_for_echo(self, echo: str) -> list[dict[str, Any]]:
        """Get all requests made for a specific echo value."""
        return [r for r in self.request_log if r["echo"] == echo]

    def get_request_count(self) -> int:
        """Get total number of requests."""
        return len(self.request_log)

    def clear_log(self) -> None:
        """Clear the request log."""
        self.request_log.clear()

    def get_request_counts_by_endpoint(self) -> dict[str, int]:
        """Get a count of requests per endpoint (echo value)."""
        counts: dict[str, int] = {}
        for r in self.request_log:
            echo = r["echo"]
            counts[echo] = counts.get(echo, 0) + 1
        return counts


@pytest.fixture
async def echo_server():
    """Create and manage the echo server."""
    server = EchoServer()
    await server.start()
    yield server
    await server.stop()


class ForkedScraper(BaseScraper[dict[str, Any]]):
    """Scraper with two forked paths: letters and numbers.

    Flow:
    - get_entry yields /landing
    - landing yields /letters and /numbers
    - letters yields /a through /j
    - letter yields ParsedData(letter=...)
    - numbers yields SpeculativeRequest for /1 through /99
    - number yields ParsedData(number=...)

    The numbers path uses speculative requests that can be controlled
    by the speculation handler.
    """

    def __init__(self, base_url: str) -> None:
        super().__init__()
        self.base_url = base_url
        self.letters_collected: list[str] = []
        self.numbers_collected: list[int] = []

    def get_entry(self) -> Generator[NavigatingRequest, None, None]:
        """Entry point - navigate to landing page."""
        yield NavigatingRequest(
            request=HTTPRequestParams(
                method=HttpMethod.GET,
                url=f"{self.base_url}/landing",
            ),
            continuation="landing",
        )

    @step
    def landing(
        self, response: Response
    ) -> Generator[ScraperYield[dict[str, Any]], None, None]:
        """Landing page - fork into letters and numbers paths."""
        # Yield request for letters path
        yield NavigatingRequest(
            request=HTTPRequestParams(
                method=HttpMethod.GET,
                url=f"{self.base_url}/letters",
            ),
            continuation="letters",
        )

        # Yield request for numbers path
        yield NavigatingRequest(
            request=HTTPRequestParams(
                method=HttpMethod.GET,
                url=f"{self.base_url}/numbers",
            ),
            continuation="numbers",
        )

    @step
    def letters(
        self, response: Response
    ) -> Generator[ScraperYield[dict[str, Any]], None, None]:
        """Letters page - yield requests for a through j."""
        for letter in "abcdefghij":
            yield NavigatingRequest(
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url=f"{self.base_url}/{letter}",
                ),
                continuation="letter",
            )

    @step
    def letter(
        self, response: Response
    ) -> Generator[ScraperYield[dict[str, Any]], None, None]:
        """Parse a single letter."""
        letter = response.text.strip()
        self.letters_collected.append(letter)
        yield ParsedData({"letter": letter})

    @step(speculative=True)
    def numbers(
        self, response: Response, speculative_id: int = 1
    ) -> Generator[ScraperYield[dict[str, Any]], bool | None, None]:
        """Numbers page - yield speculative requests for 1 through 99."""
        current_id = max(speculative_id, 1)

        while current_id <= 99:
            should_continue = yield SpeculativeRequest(
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url=f"{self.base_url}/{current_id}",
                ),
                continuation="number",
                speculative_id=current_id,
            )

            if not should_continue:
                break

            current_id += 1

    @step
    def number(
        self,
        response: Response,
    ) -> Generator[ScraperYield[dict[str, Any]], None, None]:
        """Parse a single number."""
        number = int(response.text.strip())
        self.numbers_collected.append(number)
        logger.debug(
            f"Collected a number: {number} from {response.url} ({response.status_code})"
        )
        yield ParsedData({"number": number})


@pytest.mark.asyncio
class TestForkedSpeculation:
    """Tests for forked scraper with speculation handling."""

    async def test_speculation_limits_numbers_collected(
        self, tmp_path: Path, echo_server: EchoServer
    ) -> None:
        """Test that speculation handler limits how many numbers are collected.

        With threshold=9 and speculation=1:
        - Numbers 1-9 are at or below threshold, always continue
        - Number 10 returns 404 (1 > 0), attempt=1 <= 1 => CONTINUE (no data)
        - Numbers 11-19 return 200, resets attempts to 0 => data
        - Number 20 returns 404 (2 > 0), attempt=1 <= 1 => CONTINUE (no data)
        - Number 21 returns 404 (2 > 1), attempt=2 > 1 => STOP

        Expected: letters a-j (10 letters), numbers 1-9 + 11-19 (18 numbers)
        """
        base_url = f"http://127.0.0.1:{echo_server.port}"
        db_path = tmp_path / "test_forked.db"

        scraper = ForkedScraper(base_url)

        # Create speculation handler with threshold=9 and speculation=1
        speculation_handler = create_speculation_handler(
            {
                "numbers": {"threshold": 9, "speculation": 1},
            }
        )

        collected_data: list[dict[str, Any]] = []

        async def on_data(data: dict[str, Any]) -> None:
            collected_data.append(data)

        async with LocalDevDriver.open(
            scraper,
            db_path,
            initial_rate=100.0,  # High rate for tests
            on_speculation_response=speculation_handler,
        ) as driver:
            driver.on_data = on_data
            await driver.run()

        # Verify letters collected
        letters = [d["letter"] for d in collected_data if "letter" in d]
        assert sorted(letters) == list("abcdefghij"), (
            f"Expected letters a-j, got {sorted(letters)}"
        )

        # Verify numbers collected
        numbers = sorted(
            [d["number"] for d in collected_data if "number" in d]
        )

        # With threshold=9, speculation=1 (counter resets on success):
        # - 1-9: 200, at/below threshold => data
        # - 10: 404, attempt 1 <= 1 => CONTINUE (no data)
        # - 11-19: 200, resets attempts to 0 => data
        # - 20: 404, attempt 1 <= 1 => CONTINUE (no data)
        # - 21: 404, attempt 2 > 1 => STOP
        expected_numbers = list(range(1, 10)) + list(range(11, 20))
        assert numbers == expected_numbers, (
            f"Expected {expected_numbers}, got {numbers}"
        )

    async def test_higher_speculation_crosses_more_gaps(
        self, tmp_path: Path, echo_server: EchoServer
    ) -> None:
        """Test that higher speculation allows crossing more consecutive 404 gaps.

        The 404 pattern creates gaps of increasing size:
        - Gap 1: 10 (single 404)
        - Gap 2: 20, 21 (two consecutive 404s)
        - Gap 3: 30, 31, 32 (three consecutive 404s)
        - Gap 4: 40, 41, 42, 43 (four consecutive 404s)

        Since successful responses reset the counter:
        - speculation=1: crosses single-404 gaps, stops at 2-consecutive (20-21)
        - speculation=2: crosses 2-consecutive gaps, stops at 3-consecutive (30-32)
        - speculation=3: crosses 3-consecutive gaps, stops at 4-consecutive (40-43)
        - speculation=4: crosses 4-consecutive gaps, stops at 5-consecutive (50-54)
        """
        base_url = f"http://127.0.0.1:{echo_server.port}"

        # --- Test with speculation=2 ---
        db_path_2 = tmp_path / "test_spec_2.db"
        scraper_2 = ForkedScraper(base_url)

        speculation_handler_2 = create_speculation_handler(
            {
                "numbers": {"threshold": 9, "speculation": 2},
            }
        )

        collected_data_2: list[dict[str, Any]] = []

        async def on_data_2(data: dict[str, Any]) -> None:
            collected_data_2.append(data)

        async with LocalDevDriver.open(
            scraper_2,
            db_path_2,
            initial_rate=100.0,  # High rate for tests
            on_speculation_response=speculation_handler_2,
        ) as driver_2:
            driver_2.on_data = on_data_2
            await driver_2.run()

        numbers_2 = sorted(
            [d["number"] for d in collected_data_2 if "number" in d]
        )

        # With threshold=9, speculation=2 (counter resets on success):
        # - 1-9: 200, at/below threshold
        # - 10: 404, attempt 1 <= 2 => CONTINUE
        # - 11-19: 200, resets attempts to 0
        # - 20: 404, attempt 1 < 2 => CONTINUE
        # - 21: 404, attempt 2 < 2 => STOP
        expected_numbers_2 = list(range(1, 10)) + list(range(11, 20))
        assert numbers_2 == expected_numbers_2, (
            f"Expected {expected_numbers_2}, got {numbers_2}"
        )

        echo_server.clear_log()

        # --- Test with speculation=3 ---
        db_path_3 = tmp_path / "test_spec_3.db"
        scraper_3 = ForkedScraper(base_url)

        speculation_handler_3 = create_speculation_handler(
            {
                "numbers": {"threshold": 9, "speculation": 3},
            }
        )

        collected_data_3: list[dict[str, Any]] = []

        async def on_data_3(data: dict[str, Any]) -> None:
            collected_data_3.append(data)

        async with LocalDevDriver.open(
            scraper_3,
            db_path_3,
            initial_rate=100.0,  # High rate for tests
            on_speculation_response=speculation_handler_3,
        ) as driver_3:
            driver_3.on_data = on_data_3
            await driver_3.run()

        numbers_3 = sorted(
            [d["number"] for d in collected_data_3 if "number" in d]
        )

        # With threshold=9, speculation=3 (counter resets on success):
        # - 1-9: 200, at/below threshold
        # - 10: 404, attempt 1 => CONTINUE
        # - 11-19: 200, resets
        # - 20-21: 404, attempts 1-2 => CONTINUE
        # - 22-29: 200, resets
        # - 30-32: 404, attempts 1-2 => CONTINUE
        # - 33: 404, attempt 3 => STOP
        expected_numbers_3 = (
            list(range(1, 10)) + list(range(11, 20)) + list(range(22, 30))
        )
        assert numbers_3 == expected_numbers_3, (
            f"Expected {expected_numbers_3}, got {numbers_3}"
        )

        echo_server.clear_log()

        # --- Test with speculation=4 ---
        # With speculation=4, we can cross the 30-32 gap (3 consecutive 404s)
        # and collect numbers 44-49 in addition to what speculation=3 got
        db_path_4 = tmp_path / "test_spec_4.db"
        scraper_4 = ForkedScraper(base_url)

        speculation_handler_4 = create_speculation_handler(
            {
                "numbers": {"threshold": 29, "speculation": 4},
            }
        )

        collected_data_4: list[dict[str, Any]] = []

        async def on_data_4(data: dict[str, Any]) -> None:
            collected_data_4.append(data)

        async with LocalDevDriver.open(
            scraper_4,
            db_path_4,
            initial_rate=100.0,  # High rate for tests
            on_speculation_response=speculation_handler_4,
        ) as driver_4:
            driver_4.on_data = on_data_4
            await driver_4.run()

        numbers_4 = sorted(
            [d["number"] for d in collected_data_4 if "number" in d]
        )
        letters_4 = sorted(
            [d["letter"] for d in collected_data_4 if "letter" in d]
        )

        # With speculation=4 (counter resets on success):
        # - Crosses all gaps up to 4 consecutive 404s
        expected_numbers_4 = (
            list(range(1, 10))
            + list(range(11, 20))
            + list(range(22, 30))
            + list(range(33, 40))
        )
        assert numbers_4 == expected_numbers_4, (
            f"Expected {expected_numbers_4}, got {numbers_4}"
        )
        # Letters are collected fresh since it's a new database
        assert letters_4 == list("abcdefghij"), (
            f"Expected a-j, got {letters_4}"
        )

        # Verify speculation=4 gets more than speculation=3
        assert len(numbers_4) > len(numbers_3), (
            f"speculation=4 should get more than speculation=3: {len(numbers_4)} vs {len(numbers_3)}"
        )

    async def test_speculation_with_speculative_restart(
        self, tmp_path: Path, echo_server: EchoServer
    ) -> None:
        """Test restarting speculation from a specific ID.

        This tests the speculative restart feature where we can configure
        the scraper to start from a specific speculative_id.

        First run: speculation=1, gets 1-9 and 11-19 (stops at 20-21 gap)
        Second run: new database, starts from speculative_id=20 with speculation=2,
                    gets 22-29 (crosses the 20-21 gap), then 33-39 (crosses 30-32)
        """
        base_url = f"http://127.0.0.1:{echo_server.port}"

        # --- First run with speculation=1 ---
        db_path_1 = tmp_path / "test_restart_1.db"
        scraper_1 = ForkedScraper(base_url)

        speculation_handler_1 = create_speculation_handler(
            {
                "numbers": {"threshold": 9, "speculation": 1},
            }
        )

        collected_data_1: list[dict[str, Any]] = []

        async def on_data_1(data: dict[str, Any]) -> None:
            collected_data_1.append(data)

        async with LocalDevDriver.open(
            scraper_1,
            db_path_1,
            initial_rate=100.0,  # High rate for tests
            on_speculation_response=speculation_handler_1,
        ) as driver_1:
            driver_1.on_data = on_data_1
            await driver_1.run()

            # Check the speculative progress
            progress = await driver_1.get_speculative_progress("numbers")

        numbers_1 = sorted(
            [d["number"] for d in collected_data_1 if "number" in d]
        )
        letters_1 = sorted(
            [d["letter"] for d in collected_data_1 if "letter" in d]
        )

        # First run with speculation=1 (counter resets on success):
        # Stops at 20-21 gap (2 consecutive 404s)
        expected_numbers_1 = list(range(1, 10)) + list(range(11, 20))
        assert numbers_1 == expected_numbers_1, (
            f"First run: expected {expected_numbers_1}, got {numbers_1}"
        )
        assert letters_1 == list("abcdefghij"), (
            f"First run: expected a-j, got {letters_1}"
        )
        # Progress should be at the last processed ID
        assert progress is not None, "Should have speculative progress"

        echo_server.clear_log()

        # --- Second run starting from ID 20 with speculation=2 ---
        db_path_2 = tmp_path / "test_restart_2.db"

        # Configure scraper to start from ID 20
        params = ForkedScraper.params()
        params.speculative.numbers = 20
        scraper_2 = ForkedScraper(base_url)
        scraper_2._params = params

        speculation_handler_2 = create_speculation_handler(
            {
                "numbers": {"threshold": 9, "speculation": 2},
            }
        )

        collected_data_2: list[dict[str, Any]] = []

        async def on_data_2(data: dict[str, Any]) -> None:
            collected_data_2.append(data)

        async with LocalDevDriver.open(
            scraper_2,
            db_path_2,
            initial_rate=100.0,  # High rate for tests
            on_speculation_response=speculation_handler_2,
        ) as driver_2:
            driver_2.on_data = on_data_2
            await driver_2.run()

        numbers_2 = sorted(
            [d["number"] for d in collected_data_2 if "number" in d]
        )
        letters_2 = sorted(
            [d["letter"] for d in collected_data_2 if "letter" in d]
        )

        # Second run starting from ID 20 with speculation=2 (counter resets):
        # - 20: 404, attempt 1 <= 2 => CONTINUE
        # - 21: 404, attempt 2 <= 2 => CONTINUE
        # - 22-29: 200, resets => data
        # - 30: 404, attempt 1 <= 2 => CONTINUE
        # - 31: 404, attempt 2 <= 2 => CONTINUE
        # - 32: 404, attempt 3 > 2 => STOP
        expected_numbers_2 = list(range(22, 30))
        assert numbers_2 == expected_numbers_2, (
            f"Second run: expected {expected_numbers_2}, got {numbers_2}"
        )
        # Letters are collected fresh since it's a new database
        assert letters_2 == list("abcdefghij"), (
            f"Second run: expected a-j, got {letters_2}"
        )

    async def test_no_speculation_handler_stops_on_first_404(
        self, tmp_path: Path, echo_server: EchoServer
    ) -> None:
        """Test that without a speculation handler, 404s stop speculation.

        Without a handler, non-2xx responses default to False (stop).
        """
        base_url = f"http://127.0.0.1:{echo_server.port}"
        db_path = tmp_path / "test_no_handler.db"

        scraper = ForkedScraper(base_url)

        collected_data: list[dict[str, Any]] = []

        async def on_data(data: dict[str, Any]) -> None:
            collected_data.append(data)

        # No speculation handler - use default behavior
        async with LocalDevDriver.open(
            scraper,
            db_path,
            initial_rate=100.0,  # High rate for tests
        ) as driver:
            driver.on_data = on_data
            await driver.run()

        numbers = sorted(
            [d["number"] for d in collected_data if "number" in d]
        )
        letters = sorted(
            [d["letter"] for d in collected_data if "letter" in d]
        )

        # Without handler: stops on first 404 (ID 10)
        expected_numbers = list(range(1, 10))
        assert numbers == expected_numbers, (
            f"Expected {expected_numbers}, got {numbers}"
        )
        assert letters == list("abcdefghij"), f"Expected a-j, got {letters}"

    async def test_concurrency_produces_same_results(
        self, tmp_path: Path, echo_server: EchoServer
    ) -> None:
        """Test that different worker counts produce identical results.

        This test verifies that concurrency doesn't affect correctness:
        - Same data is collected with 1, 2, and 3 workers
        - Same endpoints are hit (no duplicates, no missing requests)
        - Request counts per endpoint should be identical

        The atomic dequeue using UPDATE ... RETURNING prevents race conditions
        where multiple workers could select the same request.
        """
        base_url = f"http://127.0.0.1:{echo_server.port}"

        # Expected results with threshold=9, speculation=2
        # - 1-9: 200, at/below threshold => data
        # - 10: 404, attempt 1 <= 2 => CONTINUE (no data)
        # - 11-19: 200, resets => data
        # - 20: 404, attempt 1 <= 2 => CONTINUE (no data)
        # - 21: 404, attempt 2 <= 2 => CONTINUE (no data)
        # - 22: 404, attempt 3 > 2 => STOP
        expected_numbers = list(range(1, 10)) + list(range(11, 20))
        expected_letters = list("abcdefghij")

        results_by_workers: dict[int, dict[str, Any]] = {}

        def make_collector(
            target: list[dict[str, Any]],
        ) -> Any:
            """Create a data collector bound to a specific list."""

            async def on_data(data: dict[str, Any]) -> None:
                target.append(data)

            return on_data

        for num_workers in [1, 2, 3]:
            echo_server.clear_log()

            db_path = tmp_path / f"test_concurrency_{num_workers}.db"
            scraper = ForkedScraper(base_url)

            speculation_handler = create_speculation_handler(
                {
                    "numbers": {"threshold": 9, "speculation": 2},
                }
            )

            collected_data: list[dict[str, Any]] = []

            async with LocalDevDriver.open(
                scraper,
                db_path,
                initial_rate=100.0,  # High rate for tests
                num_workers=num_workers,
                on_speculation_response=speculation_handler,
            ) as driver:
                driver.on_data = make_collector(collected_data)
                await driver.run()

            numbers = sorted(
                [d["number"] for d in collected_data if "number" in d]
            )
            letters = sorted(
                [d["letter"] for d in collected_data if "letter" in d]
            )
            request_counts = echo_server.get_request_counts_by_endpoint()

            results_by_workers[num_workers] = {
                "numbers": numbers,
                "letters": letters,
                "request_counts": request_counts,
                "total_requests": echo_server.get_request_count(),
            }

        # Verify all worker counts produce the same data
        for num_workers in [1, 2, 3]:
            result = results_by_workers[num_workers]

            assert result["numbers"] == expected_numbers, (
                f"workers={num_workers}: expected numbers {expected_numbers}, "
                f"got {result['numbers']}"
            )
            assert result["letters"] == expected_letters, (
                f"workers={num_workers}: expected letters {expected_letters}, "
                f"got {result['letters']}"
            )

        # Verify request counts are identical across all worker configurations
        baseline_counts = results_by_workers[1]["request_counts"]
        for num_workers in [2, 3]:
            worker_counts = results_by_workers[num_workers]["request_counts"]
            assert worker_counts == baseline_counts, (
                f"workers={num_workers} has different request counts than workers=1.\n"
                f"workers=1: {baseline_counts}\n"
                f"workers={num_workers}: {worker_counts}"
            )

        # Verify each endpoint was hit exactly once (no duplicates)
        for endpoint, count in baseline_counts.items():
            assert count == 1, (
                f"Endpoint '{endpoint}' was hit {count} times, expected 1"
            )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
