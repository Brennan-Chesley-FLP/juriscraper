"""Tests for Step 11: Interceptor Pattern.

This module tests the interceptor protocol and driver integration.

Key behaviors tested:
- Interceptors receive requests and can modify them
- Interceptors receive responses and can modify them
- modify_request can return Response to short-circuit HTTP
- Interceptor chain is applied in correct order
- Response chain is applied in reverse order
- Short-circuited responses still go through response chain
"""

from pathlib import Path

from juriscraper.scraper_driver.common.example_interceptors import (
    LoggingInterceptor,
    MockInterceptor,
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
from tests.scraper_driver.scraper.example.bug_court import (
    BugCourtScraper,
)
from tests.scraper_driver.utils import collect_results


class TestInterceptorChain:
    """Tests for interceptor chain behavior in SyncDriver."""

    def test_logging_interceptor_receives_requests_and_responses(
        self, server_url: str, tmp_path: Path
    ) -> None:
        """LoggingInterceptor shall receive all requests and responses."""
        logger = LoggingInterceptor(prefix="[TEST] ")
        scraper = BugCourtScraper()
        scraper.BASE_URL = server_url
        callback, results = collect_results()

        driver = SyncDriver(
            scraper=scraper,
            storage_dir=tmp_path,
            interceptors=[logger],
            on_data=callback,
        )

        driver.run()

        # Verify logger saw requests and responses
        assert logger.request_count > 0, "Logger should see requests"
        assert logger.response_count > 0, "Logger should see responses"
        assert logger.request_count == logger.response_count, (
            "Request and response counts should match"
        )

    def test_multiple_interceptors_chain_correctly(
        self, server_url: str, tmp_path: Path
    ) -> None:
        """Multiple interceptors shall be chained in order."""
        logger1 = LoggingInterceptor(prefix="[FIRST] ")
        logger2 = LoggingInterceptor(prefix="[SECOND] ")
        scraper = BugCourtScraper()
        scraper.BASE_URL = server_url
        callback, results = collect_results()

        driver = SyncDriver(
            scraper=scraper,
            storage_dir=tmp_path,
            interceptors=[logger1, logger2],
            on_data=callback,
        )

        driver.run()

        # Both loggers should see requests/responses
        assert logger1.request_count > 0
        assert logger2.request_count > 0
        assert logger1.response_count > 0
        assert logger2.response_count > 0


class TestInterceptorShortCircuit:
    """Tests for request short-circuiting behavior."""

    def test_mock_interceptor_short_circuits_http(
        self, server_url: str, tmp_path: Path
    ) -> None:
        """MockInterceptor shall short-circuit HTTP requests.

        Note: This test uses a simple standalone scraper that doesn't navigate
        to detail pages, avoiding the complexity of mocking the entire scraper flow.
        """
        from collections.abc import Generator

        class SimpleScraper(BaseScraper[dict]):
            """Simple scraper for testing interceptor short-circuit."""

            def get_entry(self) -> NavigatingRequest:
                return NavigatingRequest(
                    request=HTTPRequestParams(
                        method=HttpMethod.GET,
                        url=f"{server_url}/test",
                    ),
                    continuation="parse",
                )

            def parse(
                self, response: Response
            ) -> Generator[ParsedData[dict], None, None]:
                """Parse response and yield a simple dict."""
                yield ParsedData(data={"text": response.text})

        # Create a mock response
        mock_text = "This is mock content"
        mock_response = Response(
            status_code=200,
            headers={},
            content=mock_text.encode("utf-8"),
            text=mock_text,
            url=f"{server_url}/test",
            request=BaseRequest(
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url=f"{server_url}/test",
                ),
                continuation="parse",
            ),
        )

        mock_interceptor = MockInterceptor(
            mock_responses={f"{server_url}/test": mock_response}
        )

        scraper = SimpleScraper()
        callback, results = collect_results()

        driver = SyncDriver(
            scraper=scraper,
            storage_dir=tmp_path,
            interceptors=[mock_interceptor],
            on_data=callback,
        )

        driver.run()

        # Verify mock was used
        assert mock_interceptor.mock_hits == 1, "Mock should have one hit"
        assert mock_interceptor.mock_misses == 0, "Mock should have no misses"

        # Verify we got the mock content
        assert len(results) == 1
        assert results[0]["text"] == "This is mock content"

    def test_short_circuit_skips_remaining_request_interceptors(
        self, server_url: str, tmp_path: Path
    ) -> None:
        """Short-circuit shall skip remaining request interceptors."""
        # Create mock interceptor that always short-circuits
        mock_html = "<html><body><h1>Mock</h1></body></html>"
        mock_response = Response(
            status_code=200,
            headers={},
            content=mock_html.encode("utf-8"),
            text=mock_html,
            url=f"{server_url}/cases",
            request=BaseRequest(
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url=f"{server_url}/cases",
                ),
                continuation="parse_case_list",
            ),
        )

        mock_interceptor = MockInterceptor(
            mock_responses={f"{server_url}/cases": mock_response}
        )

        # Logger after mock should not see request (because short-circuited)
        logger_after = LoggingInterceptor(prefix="[AFTER_MOCK] ")

        scraper = BugCourtScraper()
        scraper.BASE_URL = server_url
        callback, results = collect_results()

        driver = SyncDriver(
            scraper=scraper,
            storage_dir=tmp_path,
            interceptors=[
                mock_interceptor,
                logger_after,
            ],  # mock first, logger second
            on_data=callback,
        )

        driver.run()

        # Logger after mock should not see the request (short-circuited)
        # But it should still see the response (response chain runs in reverse)
        assert logger_after.request_count == 0, (
            "Interceptor after short-circuit should not see request"
        )
        assert logger_after.response_count > 0, (
            "Interceptor after short-circuit should still see response"
        )

    def test_response_chain_applied_to_short_circuited_response(
        self, server_url: str, tmp_path: Path
    ) -> None:
        """Response chain shall be applied to short-circuited responses."""

        class ResponseModifyingInterceptor:
            """Interceptor that modifies response headers."""

            def __init__(self) -> None:
                self.response_modify_count = 0

            def modify_request(
                self, request: BaseRequest
            ) -> BaseRequest | Response:
                return request

            def modify_response(
                self, response: Response, request: BaseRequest
            ) -> Response:
                self.response_modify_count += 1
                # Add a custom header to prove we modified it
                from dataclasses import replace

                modified_headers = {
                    **response.headers,
                    "X-Modified": "true",
                }
                return replace(response, headers=modified_headers)

        # Mock interceptor that short-circuits
        mock_html = "<html><body><h1>Mock</h1></body></html>"
        mock_response = Response(
            status_code=200,
            headers={},
            content=mock_html.encode("utf-8"),
            text=mock_html,
            url=f"{server_url}/cases",
            request=BaseRequest(
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url=f"{server_url}/cases",
                ),
                continuation="parse_case_list",
            ),
        )

        mock_interceptor = MockInterceptor(
            mock_responses={f"{server_url}/cases": mock_response}
        )

        modifier = ResponseModifyingInterceptor()

        scraper = BugCourtScraper()
        scraper.BASE_URL = server_url
        callback, results = collect_results()

        driver = SyncDriver(
            scraper=scraper,
            storage_dir=tmp_path,
            interceptors=[mock_interceptor, modifier],
            on_data=callback,
        )

        driver.run()

        # Modifier should have processed the short-circuited response
        assert modifier.response_modify_count > 0, (
            "Response modifier should process short-circuited responses"
        )


class TestInterceptorOrdering:
    """Tests for interceptor ordering behavior."""

    def test_request_chain_forward_response_chain_reverse(
        self, server_url: str, tmp_path: Path
    ) -> None:
        """Request chain shall run forward, response chain shall run reverse."""

        class OrderTrackingInterceptor:
            """Interceptor that tracks execution order."""

            def __init__(self, name: str, order_log: list[str]) -> None:
                self.name = name
                self.order_log = order_log

            def modify_request(
                self, request: BaseRequest
            ) -> BaseRequest | Response:
                self.order_log.append(f"request:{self.name}")
                return request

            def modify_response(
                self, response: Response, request: BaseRequest
            ) -> Response:
                self.order_log.append(f"response:{self.name}")
                return response

        order_log: list[str] = []
        interceptor_a = OrderTrackingInterceptor("A", order_log)
        interceptor_b = OrderTrackingInterceptor("B", order_log)
        interceptor_c = OrderTrackingInterceptor("C", order_log)

        scraper = BugCourtScraper()
        scraper.BASE_URL = server_url
        callback, results = collect_results()

        driver = SyncDriver(
            scraper=scraper,
            storage_dir=tmp_path,
            interceptors=[interceptor_a, interceptor_b, interceptor_c],
            on_data=callback,
        )

        driver.run()

        # Find the first request/response cycle
        first_request_idx = order_log.index("request:A")
        # Requests should be A, B, C (forward)
        assert order_log[first_request_idx] == "request:A"
        assert order_log[first_request_idx + 1] == "request:B"
        assert order_log[first_request_idx + 2] == "request:C"

        # Find first response (should be after the request chain)
        first_response_idx = order_log.index("response:C", first_request_idx)
        # Responses should be C, B, A (reverse)
        assert order_log[first_response_idx] == "response:C"
        assert order_log[first_response_idx + 1] == "response:B"
        assert order_log[first_response_idx + 2] == "response:A"
