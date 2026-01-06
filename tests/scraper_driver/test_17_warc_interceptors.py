"""Tests for Step 17: WARC Interceptors.

This module tests the WARC interceptors for recording and replaying
HTTP traffic to enable deterministic testing.

Key behaviors tested:
- WarcCaptureInterceptor records responses to WARC file
- WarcCacheInterceptor replays from WARC file
- Cache interceptor short-circuits on cache hit
- Supports compressed WARC (.warc.gz)
- Deterministic replay produces same results
- Cache key generation is consistent
"""

from pathlib import Path

from juriscraper.scraper_driver.common.warc_interceptors import (
    WarcCacheInterceptor,
    WarcCaptureInterceptor,
)
from juriscraper.scraper_driver.data_types import (
    BaseScraper,
    HttpMethod,
    HTTPRequestParams,
    NavigatingRequest,
    ParsedData,
    Response,
)
from juriscraper.scraper_driver.driver.sync_driver import SyncDriver
from tests.scraper_driver.utils import collect_results


class TestWarcCapture:
    """Tests for WarcCaptureInterceptor recording."""

    def test_capture_records_to_warc_file(
        self, server_url: str, tmp_path: Path
    ) -> None:
        """The WarcCaptureInterceptor shall record responses to WARC file."""

        class SimpleScraper(BaseScraper[dict]):
            def get_entry(self) -> NavigatingRequest:
                return NavigatingRequest(
                    request=HTTPRequestParams(
                        method=HttpMethod.GET,
                        url=f"{server_url}/test",
                    ),
                    continuation="parse",
                )

            def parse(self, response: Response):
                yield ParsedData(data={"text": response.text})

        warc_path = tmp_path / "test.warc.gz"
        capture = WarcCaptureInterceptor(warc_path)

        scraper = SimpleScraper()
        callback, results = collect_results()

        driver = SyncDriver(
            scraper=scraper,
            storage_dir=tmp_path,
            on_data=callback,
            interceptors=[capture],
        )

        driver.run()

        # Ensure file is closed
        capture.close()

        # Verify WARC file was created and has content
        assert warc_path.exists()
        assert warc_path.stat().st_size > 0

    def test_capture_supports_compressed_warc(
        self, server_url: str, tmp_path: Path
    ) -> None:
        """The WarcCaptureInterceptor shall support .warc.gz compressed format."""

        class SimpleScraper(BaseScraper[dict]):
            def get_entry(self) -> NavigatingRequest:
                return NavigatingRequest(
                    request=HTTPRequestParams(
                        method=HttpMethod.GET,
                        url=f"{server_url}/test",
                    ),
                    continuation="parse",
                )

            def parse(self, response: Response):
                yield ParsedData(data={"text": response.text})

        warc_path = tmp_path / "compressed.warc.gz"
        capture = WarcCaptureInterceptor(warc_path)

        scraper = SimpleScraper()
        callback, results = collect_results()

        driver = SyncDriver(
            scraper=scraper,
            storage_dir=tmp_path,
            on_data=callback,
            interceptors=[capture],
        )

        driver.run()
        capture.close()

        # Verify compressed file was created
        assert warc_path.exists()
        # Compressed files should have gzip magic bytes
        with warc_path.open("rb") as f:
            magic = f.read(2)
            assert magic == b"\x1f\x8b"  # gzip magic bytes

    def test_capture_records_multiple_requests(
        self, server_url: str, tmp_path: Path
    ) -> None:
        """The WarcCaptureInterceptor shall record multiple responses to same file."""

        class MultiRequestScraper(BaseScraper[dict]):
            def get_entry(self) -> NavigatingRequest:
                return NavigatingRequest(
                    request=HTTPRequestParams(
                        method=HttpMethod.GET,
                        url=f"{server_url}/test",
                    ),
                    continuation="parse",
                )

            def parse(self, response: Response):
                # Yield multiple requests
                for i in range(1, 4):
                    yield NavigatingRequest(
                        request=HTTPRequestParams(
                            method=HttpMethod.GET,
                            url=f"{server_url}/page{i}",
                        ),
                        continuation="parse_page",
                    )

            def parse_page(self, response: Response):
                yield ParsedData(data={"url": response.url})

        warc_path = tmp_path / "multi.warc.gz"
        capture = WarcCaptureInterceptor(warc_path)

        scraper = MultiRequestScraper()
        callback, results = collect_results()

        driver = SyncDriver(
            scraper=scraper,
            storage_dir=tmp_path,
            on_data=callback,
            interceptors=[capture],
        )

        driver.run()
        capture.close()

        # Verify file exists and has reasonable size
        assert warc_path.exists()
        # Should have 4 responses (1 entry + 3 pages)
        assert warc_path.stat().st_size > 100


class TestWarcCache:
    """Tests for WarcCacheInterceptor replay."""

    def test_cache_replays_from_warc_file(
        self, server_url: str, tmp_path: Path
    ) -> None:
        """The WarcCacheInterceptor shall replay responses from WARC file."""

        class SimpleScraper(BaseScraper[dict]):
            def get_entry(self) -> NavigatingRequest:
                return NavigatingRequest(
                    request=HTTPRequestParams(
                        method=HttpMethod.GET,
                        url=f"{server_url}/test",
                    ),
                    continuation="parse",
                )

            def parse(self, response: Response):
                yield ParsedData(data={"text": response.text})

        warc_path = tmp_path / "replay.warc.gz"

        # First run: record
        capture = WarcCaptureInterceptor(warc_path)
        scraper = SimpleScraper()
        callback1, results1 = collect_results()

        driver1 = SyncDriver(
            scraper=scraper,
            storage_dir=tmp_path,
            on_data=callback1,
            interceptors=[capture],
        )

        driver1.run()
        capture.close()

        # Second run: replay from cache
        cache = WarcCacheInterceptor(warc_path)
        scraper2 = SimpleScraper()
        callback2, results2 = collect_results()

        driver2 = SyncDriver(
            scraper=scraper2,
            storage_dir=tmp_path,
            on_data=callback2,
            interceptors=[cache],
        )

        driver2.run()

        # Results should be identical
        assert len(results1) == len(results2)
        assert results1[0]["text"] == results2[0]["text"]

    def test_cache_short_circuits_on_hit(
        self, server_url: str, tmp_path: Path
    ) -> None:
        """The WarcCacheInterceptor shall short-circuit requests on cache hit."""

        class SimpleScraper(BaseScraper[dict]):
            def get_entry(self) -> NavigatingRequest:
                return NavigatingRequest(
                    request=HTTPRequestParams(
                        method=HttpMethod.GET,
                        url=f"{server_url}/test",
                    ),
                    continuation="parse",
                )

            def parse(self, response: Response):
                yield ParsedData(data={"text": response.text})

        warc_path = tmp_path / "shortcircuit.warc.gz"

        # Record
        capture = WarcCaptureInterceptor(warc_path)
        scraper = SimpleScraper()
        callback1, results1 = collect_results()

        driver1 = SyncDriver(
            scraper=scraper,
            storage_dir=tmp_path,
            on_data=callback1,
            interceptors=[capture],
        )

        driver1.run()
        capture.close()

        # Replay - cache should short-circuit before HTTP
        cache = WarcCacheInterceptor(warc_path)

        # Track if modify_request was called
        original_modify = cache.modify_request
        modify_called = {"count": 0}

        def tracking_modify(request):
            modify_called["count"] += 1
            result = original_modify(request)
            # Should return Response (short-circuit), not BaseRequest
            assert isinstance(result, Response)
            return result

        cache.modify_request = tracking_modify  # type: ignore

        scraper2 = SimpleScraper()
        callback2, results2 = collect_results()

        driver2 = SyncDriver(
            scraper=scraper2,
            storage_dir=tmp_path,
            on_data=callback2,
            interceptors=[cache],
        )

        driver2.run()

        # Verify modify_request was called and returned Response
        assert modify_called["count"] == 1

    def test_cache_handles_missing_warc_file(
        self, server_url: str, tmp_path: Path
    ) -> None:
        """The WarcCacheInterceptor shall handle missing WARC file gracefully."""

        warc_path = tmp_path / "nonexistent.warc.gz"

        # Should not raise, just log warning
        cache = WarcCacheInterceptor(warc_path)

        # Cache should be empty
        assert len(cache._cache) == 0


class TestWarcDeterminism:
    """Tests for deterministic replay behavior."""

    def test_replay_is_deterministic(
        self, server_url: str, tmp_path: Path
    ) -> None:
        """The WARC replay shall produce identical results across multiple runs."""

        class SimpleScraper(BaseScraper[dict]):
            def get_entry(self) -> NavigatingRequest:
                return NavigatingRequest(
                    request=HTTPRequestParams(
                        method=HttpMethod.GET,
                        url=f"{server_url}/test",
                    ),
                    continuation="parse",
                )

            def parse(self, response: Response):
                yield ParsedData(data={"text": response.text})

        warc_path = tmp_path / "deterministic.warc.gz"

        # Record
        capture = WarcCaptureInterceptor(warc_path)
        scraper = SimpleScraper()
        callback1, results1 = collect_results()

        driver1 = SyncDriver(
            scraper=scraper,
            storage_dir=tmp_path,
            on_data=callback1,
            interceptors=[capture],
        )

        driver1.run()
        capture.close()

        # Replay multiple times
        cache = WarcCacheInterceptor(warc_path)
        all_results = []

        for _ in range(3):
            scraper_run = SimpleScraper()
            callback_run, results_run = collect_results()

            driver_run = SyncDriver(
                scraper=scraper_run,
                storage_dir=tmp_path,
                on_data=callback_run,
                interceptors=[cache],
            )

            driver_run.run()
            all_results.append(results_run)

        # All runs should produce identical results
        for results in all_results:
            assert results == results1

    def test_capture_and_replay_workflow(
        self, server_url: str, tmp_path: Path
    ) -> None:
        """The WARC workflow shall support record-once, replay-many pattern."""

        class MultiPageScraper(BaseScraper[dict]):
            def get_entry(self) -> NavigatingRequest:
                return NavigatingRequest(
                    request=HTTPRequestParams(
                        method=HttpMethod.GET,
                        url=f"{server_url}/test",
                    ),
                    continuation="parse",
                )

            def parse(self, response: Response):
                for i in range(1, 4):
                    yield NavigatingRequest(
                        request=HTTPRequestParams(
                            method=HttpMethod.GET,
                            url=f"{server_url}/page{i}",
                        ),
                        continuation="parse_page",
                    )

            def parse_page(self, response: Response):
                yield ParsedData(data={"url": response.url})

        warc_path = tmp_path / "workflow.warc.gz"

        # Step 1: Record
        capture = WarcCaptureInterceptor(warc_path)
        scraper = MultiPageScraper()
        callback1, results1 = collect_results()

        driver1 = SyncDriver(
            scraper=scraper,
            storage_dir=tmp_path,
            on_data=callback1,
            interceptors=[capture],
        )

        driver1.run()
        capture.close()

        # Step 2: Replay many times (deterministic)
        for _ in range(3):
            cache = WarcCacheInterceptor(warc_path)
            scraper_run = MultiPageScraper()
            callback_run, results_run = collect_results()

            driver_run = SyncDriver(
                scraper=scraper_run,
                storage_dir=tmp_path,
                on_data=callback_run,
                interceptors=[cache],
            )

            driver_run.run()

            # Each run should produce same results
            assert len(results_run) == len(results1)
            assert results_run == results1


class TestWarcCacheKey:
    """Tests for WARC cache key generation."""

    def test_cache_key_includes_url(
        self, server_url: str, tmp_path: Path
    ) -> None:
        """The cache key shall include the URL."""

        cache = WarcCacheInterceptor(tmp_path / "test.warc.gz")

        req1 = NavigatingRequest(
            request=HTTPRequestParams(
                method=HttpMethod.GET,
                url=f"{server_url}/page1",
            ),
            continuation="parse",
        )

        req2 = NavigatingRequest(
            request=HTTPRequestParams(
                method=HttpMethod.GET,
                url=f"{server_url}/page2",
            ),
            continuation="parse",
        )

        key1 = cache._get_cache_key(req1)
        key2 = cache._get_cache_key(req2)

        # Different URLs should produce different keys
        assert key1 != key2

    def test_cache_key_includes_method(
        self, server_url: str, tmp_path: Path
    ) -> None:
        """The cache key shall include the HTTP method."""

        cache = WarcCacheInterceptor(tmp_path / "test.warc.gz")

        req1 = NavigatingRequest(
            request=HTTPRequestParams(
                method=HttpMethod.GET,
                url=f"{server_url}/page1",
            ),
            continuation="parse",
        )

        req2 = NavigatingRequest(
            request=HTTPRequestParams(
                method=HttpMethod.POST,
                url=f"{server_url}/page1",
            ),
            continuation="parse",
        )

        key1 = cache._get_cache_key(req1)
        key2 = cache._get_cache_key(req2)

        # Different methods should produce different keys
        assert key1 != key2

    def test_cache_key_includes_request_body(
        self, server_url: str, tmp_path: Path
    ) -> None:
        """The cache key shall include the request body."""

        cache = WarcCacheInterceptor(tmp_path / "test.warc.gz")

        req1 = NavigatingRequest(
            request=HTTPRequestParams(
                method=HttpMethod.POST,
                url=f"{server_url}/submit",
                data={"name": "Alice"},
            ),
            continuation="parse",
        )

        req2 = NavigatingRequest(
            request=HTTPRequestParams(
                method=HttpMethod.POST,
                url=f"{server_url}/submit",
                data={"name": "Bob"},
            ),
            continuation="parse",
        )

        key1 = cache._get_cache_key(req1)
        key2 = cache._get_cache_key(req2)

        # Different request bodies should produce different keys
        assert key1 != key2

    def test_cache_key_is_consistent(
        self, server_url: str, tmp_path: Path
    ) -> None:
        """The cache key shall be consistent for identical requests."""

        cache = WarcCacheInterceptor(tmp_path / "test.warc.gz")

        req1 = NavigatingRequest(
            request=HTTPRequestParams(
                method=HttpMethod.GET,
                url=f"{server_url}/page1",
            ),
            continuation="parse",
        )

        req2 = NavigatingRequest(
            request=HTTPRequestParams(
                method=HttpMethod.GET,
                url=f"{server_url}/page1",
            ),
            continuation="parse",
        )

        key1 = cache._get_cache_key(req1)
        key2 = cache._get_cache_key(req2)

        # Identical requests should produce same key
        assert key1 == key2
