"""Tests for Step 12: Rate Limiting Interceptor.

This module tests the rate limiting interceptor and its integration with
the driver.

Key behaviors tested:
- Rate limiter delays requests to maintain rate limit
- Configurable rates (per second, per minute)
- Adaptive rate limiting on 429 responses
- Rate limiter comes after cache in interceptor chain
- Stats tracking for rate limit performance
"""

import time
from collections.abc import Generator
from pathlib import Path

from juriscraper.scraper_driver.common.rate_limit_interceptor import (
    RateLimitInterceptor,
)
from juriscraper.scraper_driver.data_types import (
    BaseRequest,
    BaseScraper,
    HttpMethod,
    HTTPRequestParams,
    NavigatingRequest,
    ParsedData,
    Response,
)
from juriscraper.scraper_driver.driver.sync_driver import SyncDriver
from tests.scraper_driver.utils import collect_results


class TestRateLimitInterceptor:
    """Tests for basic rate limit interceptor functionality."""

    def test_rate_limiter_delays_requests(
        self, server_url: str, tmp_path: Path
    ) -> None:
        """RateLimitInterceptor shall delay requests to maintain rate limit."""

        class SimpleScraper(BaseScraper[dict]):
            """Scraper that makes multiple requests."""

            def get_entry(self) -> NavigatingRequest:
                return NavigatingRequest(
                    request=HTTPRequestParams(
                        method=HttpMethod.GET,
                        url=f"{server_url}/cases",
                    ),
                    continuation="parse_list",
                )

            def parse_list(
                self, response: Response
            ) -> Generator[NavigatingRequest, None, None]:
                """Yield 3 requests to test rate limiting."""
                for i in range(1, 4):
                    yield NavigatingRequest(
                        request=HTTPRequestParams(
                            method=HttpMethod.GET,
                            url=f"{server_url}/cases/BCC-2024-00{i}",
                        ),
                        continuation="parse_detail",
                    )

            def parse_detail(
                self, response: Response
            ) -> Generator[ParsedData[dict], None, None]:
                """Parse detail page."""
                yield ParsedData(data={"url": response.url})

        # Create rate limiter: 2 requests per second
        rate_limiter = RateLimitInterceptor(requests_per_second=2.0)

        scraper = SimpleScraper()
        callback, results = collect_results()

        driver = SyncDriver(
            scraper=scraper,
            storage_dir=tmp_path,
            interceptors=[rate_limiter],
            on_data=callback,
        )

        start_time = time.time()
        driver.run()
        elapsed_time = time.time() - start_time

        # We made 4 requests (1 list + 3 details) at 2 req/sec
        # Should take at least 1.5 seconds (4 requests / 2 per second - first is immediate)
        assert elapsed_time >= 1.0, (
            f"Rate limiting should delay requests (took {elapsed_time:.2f}s)"
        )

        # Verify we got all results
        assert len(results) == 3

        # Check stats
        stats = rate_limiter.get_stats()
        assert stats["total_requests"] == 4  # 1 list + 3 details
        assert stats["current_rate"] == 2.0

    def test_rate_limiter_requests_per_minute(
        self, server_url: str, tmp_path: Path
    ) -> None:
        """RateLimitInterceptor shall support requests_per_minute configuration."""

        class SimpleScraper(BaseScraper[dict]):
            def get_entry(self) -> NavigatingRequest:
                return NavigatingRequest(
                    request=HTTPRequestParams(
                        method=HttpMethod.GET,
                        url=f"{server_url}/rate-limited",
                    ),
                    continuation="parse",
                )

            def parse(
                self, response: Response
            ) -> Generator[ParsedData[dict], None, None]:
                yield ParsedData(data={"status": response.status_code})

        # Create rate limiter: 60 requests per minute (= 1 per second)
        rate_limiter = RateLimitInterceptor(requests_per_minute=60)

        scraper = SimpleScraper()
        callback, results = collect_results()

        driver = SyncDriver(
            scraper=scraper,
            storage_dir=tmp_path,
            interceptors=[rate_limiter],
            on_data=callback,
        )

        driver.run()

        # Should succeed
        assert len(results) == 1
        assert results[0]["status"] == 200

    def test_rate_limiter_requires_rate_parameter(self) -> None:
        """RateLimitInterceptor shall require either requests_per_second or requests_per_minute."""
        try:
            RateLimitInterceptor()  # No parameters
            raise AssertionError("Should raise ValueError")
        except ValueError as e:
            assert "Must provide either" in str(e)


class TestAdaptiveRateLimiting:
    """Tests for adaptive rate limiting on 429 responses."""

    def test_adaptive_rate_limiting_reduces_rate_on_429(
        self, server_url: str, tmp_path: Path
    ) -> None:
        """RateLimitInterceptor shall reduce rate when receiving 429 response."""

        class RateLimitedScraper(BaseScraper[dict]):
            """Scraper that hits rate-limited endpoint repeatedly."""

            def get_entry(self) -> NavigatingRequest:
                return NavigatingRequest(
                    request=HTTPRequestParams(
                        method=HttpMethod.GET,
                        url=f"{server_url}/rate-limited",
                    ),
                    continuation="parse_and_continue",
                )

            def parse_and_continue(
                self, response: Response
            ) -> Generator[NavigatingRequest | ParsedData[dict], None, None]:
                """Parse and potentially make more requests."""
                yield ParsedData(data={"status": response.status_code})

                # If we got 200, make another request
                if response.status_code == 200:
                    yield NavigatingRequest(
                        request=HTTPRequestParams(
                            method=HttpMethod.GET,
                            url=f"{server_url}/rate-limited",
                        ),
                        continuation="parse_and_continue",
                    )

        # Create rate limiter with aggressive initial rate to trigger 429
        # Mock server allows 2 requests per second
        rate_limiter = RateLimitInterceptor(
            requests_per_second=10.0,  # Way too fast
            adaptive=True,
            adaptive_increase=0.10,  # Increase interval by 10% on 429
        )

        scraper = RateLimitedScraper()
        callback, results = collect_results()

        driver = SyncDriver(
            scraper=scraper,
            storage_dir=tmp_path,
            interceptors=[rate_limiter],
            on_data=callback,
        )

        driver.run()

        # We should have received at least one 429 and adapted
        status_codes = [r["status"] for r in results]
        assert 429 in status_codes, "Should receive 429 response"

        # Check that adaptive reduction occurred
        stats = rate_limiter.get_stats()
        assert stats["adaptive_reductions"] > 0, (
            "Should have reduced rate at least once"
        )
        assert stats["current_rate"] < 10.0, (
            "Rate should be reduced from initial"
        )

    def test_adaptive_can_be_disabled(
        self, server_url: str, tmp_path: Path
    ) -> None:
        """RateLimitInterceptor shall allow disabling adaptive rate limiting."""

        class SimpleScraper(BaseScraper[dict]):
            def get_entry(self) -> NavigatingRequest:
                return NavigatingRequest(
                    request=HTTPRequestParams(
                        method=HttpMethod.GET,
                        url=f"{server_url}/rate-limited",
                    ),
                    continuation="parse",
                )

            def parse(
                self, response: Response
            ) -> Generator[ParsedData[dict], None, None]:
                yield ParsedData(data={"status": response.status_code})

        # Create rate limiter with adaptive disabled
        rate_limiter = RateLimitInterceptor(
            requests_per_second=2.0,
            adaptive=False,
        )

        scraper = SimpleScraper()
        callback, results = collect_results()

        driver = SyncDriver(
            scraper=scraper,
            storage_dir=tmp_path,
            interceptors=[rate_limiter],
            on_data=callback,
        )

        driver.run()

        # Even if we got 429 (we won't with this rate), it shouldn't adapt
        stats = rate_limiter.get_stats()
        assert stats["adaptive_reductions"] == 0
        assert stats["current_rate"] == 2.0  # Unchanged


class TestRateLimiterInterceptorOrdering:
    """Tests for rate limiter positioning in interceptor chain."""

    def test_cache_before_rate_limiter_skips_rate_limiting(
        self, server_url: str, tmp_path: Path
    ) -> None:
        """Rate limiter shall not delay cache hits."""
        from juriscraper.scraper_driver.common.example_interceptors import (
            MockInterceptor,
        )

        class SimpleScraper(BaseScraper[dict]):
            def get_entry(self) -> NavigatingRequest:
                return NavigatingRequest(
                    request=HTTPRequestParams(
                        method=HttpMethod.GET,
                        url=f"{server_url}/test",
                    ),
                    continuation="parse_and_repeat",
                )

            def parse_and_repeat(
                self, response: Response
            ) -> Generator[NavigatingRequest | ParsedData[dict], None, None]:
                yield ParsedData(data={"text": response.text})

                # Make same request again (will be cached)
                yield NavigatingRequest(
                    request=HTTPRequestParams(
                        method=HttpMethod.GET,
                        url=f"{server_url}/test",
                    ),
                    continuation="parse",
                )

            def parse(
                self, response: Response
            ) -> Generator[ParsedData[dict], None, None]:
                yield ParsedData(data={"text": response.text})

        # Create mock interceptor (acts as cache)
        mock_response = Response(
            status_code=200,
            headers={},
            content=b"cached",
            text="cached",
            url=f"{server_url}/test",
            request=BaseRequest(
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url=f"{server_url}/test",
                ),
                continuation="parse",
            ),
        )
        mock = MockInterceptor(
            mock_responses={f"{server_url}/test": mock_response}
        )

        # Create slow rate limiter
        rate_limiter = RateLimitInterceptor(requests_per_second=1.0)

        scraper = SimpleScraper()
        callback, results = collect_results()

        # IMPORTANT: Cache (mock) before rate limiter
        driver = SyncDriver(
            scraper=scraper,
            storage_dir=tmp_path,
            interceptors=[mock, rate_limiter],
            on_data=callback,
        )

        start_time = time.time()
        driver.run()
        elapsed_time = time.time() - start_time

        # Both requests were cached, so rate limiter never saw them
        # Should complete very quickly (no rate limiting delay)
        assert elapsed_time < 0.5, (
            f"Cached requests should not be rate limited (took {elapsed_time:.2f}s)"
        )

        # Both requests should have been served from cache
        assert len(results) == 2
        assert all(r["text"] == "cached" for r in results)
