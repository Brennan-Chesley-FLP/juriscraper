"""Interceptor protocol for request/response transformation.

Interceptors implement the middleware pattern, allowing transformation of
requests before they are sent and responses after they are received.

Step 11: Interceptor Pattern introduces:
- SyncInterceptor protocol
- AsyncInterceptor protocol
- Request short-circuiting (modify_request can return Response)
- Chain of responsibility pattern
"""

from collections.abc import Awaitable
from typing import Protocol

from juriscraper.scraper_driver.data_types import BaseRequest, Response


class SyncInterceptor(Protocol):
    """Protocol for synchronous interceptors.

    Interceptors can transform requests before sending and responses after
    receiving. They form a chain of responsibility, processing requests
    and responses in order.

    Key behaviors:
    - modify_request() can return BaseRequest (continue) or Response (short-circuit)
    - modify_response() transforms responses after receiving
    - Short-circuiting skips HTTP and remaining request interceptors
    - Response chain is still applied to short-circuited responses
    - Interceptor order matters (cache before rate limiter)
    """

    def modify_request(self, request: BaseRequest) -> BaseRequest | Response:
        """Modify request before sending, or short-circuit with Response.

        Args:
            request: The request to modify.

        Returns:
            BaseRequest to continue the chain, or Response to short-circuit.

        Short-circuiting use cases:
        - Cache hit: Return cached response, skip HTTP
        - Deduplication: Return duplicate marker, skip HTTP
        - Test mocking: Return canned response, skip HTTP
        """
        return request

    def modify_response(
        self, response: Response, request: BaseRequest
    ) -> Response:
        """Modify response after receiving.

        Args:
            response: The response to modify.
            request: The original request that generated this response.

        Returns:
            Modified response.

        Note: This is called for both real HTTP responses and short-circuited
        responses. The response chain is applied in reverse order (last
        interceptor first) to properly unwind the chain.
        """
        return response


class AsyncInterceptor(Protocol):
    """Protocol for asynchronous interceptors.

    Async interceptors can transform requests before sending and responses after
    receiving. They form a chain of responsibility, processing requests
    and responses in order.

    Key behaviors:
    - modify_request() can return BaseRequest (continue) or Response (short-circuit)
    - modify_response() transforms responses after receiving
    - Short-circuiting skips HTTP and remaining request interceptors
    - Response chain is still applied to short-circuited responses
    - Interceptor order matters (cache before rate limiter)
    """

    def modify_request(
        self, request: BaseRequest
    ) -> Awaitable[BaseRequest | Response]:
        """Modify request before sending, or short-circuit with Response.

        Args:
            request: The request to modify.

        Returns:
            Awaitable of BaseRequest to continue the chain, or Response to short-circuit.

        Short-circuiting use cases:
        - Cache hit: Return cached response, skip HTTP
        - Deduplication: Return duplicate marker, skip HTTP
        - Test mocking: Return canned response, skip HTTP
        """
        ...

    def modify_response(
        self, response: Response, request: BaseRequest
    ) -> Awaitable[Response]:
        """Modify response after receiving.

        Args:
            response: The response to modify.
            request: The original request that generated this response.

        Returns:
            Awaitable of modified response.

        Note: This is called for both real HTTP responses and short-circuited
        responses. The response chain is applied in reverse order (last
        interceptor first) to properly unwind the chain.
        """
        ...
