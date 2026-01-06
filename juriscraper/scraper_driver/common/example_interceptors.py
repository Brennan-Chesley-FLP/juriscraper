"""Example interceptor implementations.

These interceptors demonstrate the interceptor pattern and can be used
for testing, debugging, and as templates for custom interceptors.

Step 11: Interceptor Pattern
"""

from juriscraper.scraper_driver.data_types import BaseRequest, Response


class LoggingInterceptor:
    """Example interceptor that logs requests and responses.

    This interceptor demonstrates basic request/response transformation
    without modifying the data. Useful for debugging and monitoring.
    """

    def __init__(self, prefix: str = "") -> None:
        """Initialize the logging interceptor.

        Args:
            prefix: Optional prefix for log messages.
        """
        self.prefix = prefix
        self.request_count = 0
        self.response_count = 0

    def modify_request(self, request: BaseRequest) -> BaseRequest | Response:
        """Log the request and return it unchanged.

        Args:
            request: The request to log.

        Returns:
            The unmodified request.
        """
        self.request_count += 1
        url = request.request.url
        method = request.request.method.value
        print(f"{self.prefix}Request #{self.request_count}: {method} {url}")
        return request

    def modify_response(
        self, response: Response, request: BaseRequest
    ) -> Response:
        """Log the response and return it unchanged.

        Args:
            response: The response to log.
            request: The original request.

        Returns:
            The unmodified response.
        """
        self.response_count += 1
        print(
            f"{self.prefix}Response #{self.response_count}: "
            f"{response.status_code} from {response.url}"
        )
        return response


class MockInterceptor:
    """Example interceptor that returns mock responses.

    This interceptor demonstrates request short-circuiting by returning
    canned responses instead of making HTTP requests. Useful for testing.
    """

    def __init__(self, mock_responses: dict[str, Response]) -> None:
        """Initialize the mock interceptor.

        Args:
            mock_responses: Map of URLs to mock Response objects.
        """
        self.mock_responses = mock_responses
        self.mock_hits = 0
        self.mock_misses = 0

    def modify_request(self, request: BaseRequest) -> BaseRequest | Response:
        """Return mock response if URL matches, otherwise pass through.

        Args:
            request: The request to potentially mock.

        Returns:
            Mock Response if URL matches, otherwise the original request.
        """
        url = request.request.url
        if url in self.mock_responses:
            self.mock_hits += 1
            return self.mock_responses[url]
        else:
            self.mock_misses += 1
            return request

    def modify_response(
        self, response: Response, request: BaseRequest
    ) -> Response:
        """Pass through response unchanged.

        Args:
            response: The response to pass through.
            request: The original request.

        Returns:
            The unmodified response.
        """
        return response


class HeaderInterceptor:
    """Example interceptor that adds headers to requests.

    This interceptor demonstrates request modification by adding custom
    headers to all requests.
    """

    def __init__(self, headers: dict[str, str]) -> None:
        """Initialize the header interceptor.

        Args:
            headers: Headers to add to all requests.
        """
        self.headers = headers

    def modify_request(self, request: BaseRequest) -> BaseRequest | Response:
        """Add headers to the request.

        Args:
            request: The request to modify.

        Returns:
            Request with added headers.
        """
        # Create a copy of the request with updated headers
        existing_headers = request.request.headers or {}
        updated_headers = {**existing_headers, **self.headers}

        # Replace the headers in the request
        from dataclasses import replace

        updated_http_request = replace(
            request.request, headers=updated_headers
        )
        updated_request = replace(request, request=updated_http_request)

        return updated_request

    def modify_response(
        self, response: Response, request: BaseRequest
    ) -> Response:
        """Pass through response unchanged.

        Args:
            response: The response to pass through.
            request: The original request.

        Returns:
            The unmodified response.
        """
        return response
