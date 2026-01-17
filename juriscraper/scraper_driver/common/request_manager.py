"""Request managers for handling HTTP requests with interceptor chains.

This module provides SyncRequestManager and AsyncRequestManager classes that
encapsulate the HTTP client, interceptor chain, and request resolution logic.

The request manager is responsible for:
- Maintaining the HTTP client (httpx.Client or httpx.AsyncClient)
- Applying interceptor chains to requests and responses
- Handling short-circuit responses from interceptors
- Converting HTTP responses to Response objects

This separation allows drivers to focus on queue management and scraper
orchestration while delegating HTTP concerns to the request manager.
"""

from __future__ import annotations

import ssl
from typing import TYPE_CHECKING, Any, cast

import httpx

from juriscraper.scraper_driver.common.exceptions import (
    HTMLResponseAssumptionException,
    RequestTimeoutException,
)
from juriscraper.scraper_driver.common.interceptors import (
    AsyncInterceptor,
    SyncInterceptor,
)
from juriscraper.scraper_driver.data_types import BaseRequest, Response

if TYPE_CHECKING:
    pass


class SyncRequestManager:
    """Manages HTTP requests with interceptor support for synchronous drivers.

    This class encapsulates:
    - httpx.Client lifecycle
    - Interceptor chain application
    - Request resolution (URL fetching)
    - Response transformation

    Example:
        manager = SyncRequestManager(
            interceptors=[cache, rate_limiter],
            ssl_context=scraper.get_ssl_context(),
            timeout=30.0,
        )
        response = manager.resolve_request(request)
    """

    def __init__(
        self,
        interceptors: list[SyncInterceptor] | None = None,
        ssl_context: ssl.SSLContext | None = None,
        timeout: float | None = None,
    ) -> None:
        """Initialize the request manager.

        Args:
            interceptors: List of interceptors to apply to requests and responses.
                Interceptors are applied in order for requests, and in reverse
                order for responses. Order matters - cache should come before
                rate limiter.
            ssl_context: Optional SSL context for HTTPS connections. Use this
                for servers requiring specific cipher suites.
            timeout: Request timeout in seconds. None means no timeout (default).
        """
        self.interceptors = interceptors or []
        self.timeout = timeout

        # Initialize httpx client
        if ssl_context:
            self._client = httpx.Client(verify=ssl_context, timeout=timeout)
        else:
            self._client = httpx.Client(timeout=timeout)

    def close(self) -> None:
        """Close the HTTP client and release resources."""
        self._client.close()

    def __enter__(self) -> SyncRequestManager:
        """Context manager entry."""
        return self

    def __exit__(self, *args: Any) -> None:
        """Context manager exit - closes the client."""
        self.close()

    def resolve_request(self, request: BaseRequest) -> Response:
        """Fetch a BaseRequest and return the Response.

        Applies the interceptor chain, makes the HTTP request (unless
        short-circuited), and transforms the response.

        Args:
            request: The BaseRequest to fetch. URL should be absolute.

        Returns:
            Response containing the HTTP response data.

        Raises:
            HTMLResponseAssumptionException: If server returns 5xx status code.
            httpx.TimeoutException: If request times out (for retry handling).
        """
        # Apply modify_request interceptor chain
        modified_request = request
        for interceptor in self.interceptors:
            result = interceptor.modify_request(modified_request)
            if isinstance(result, Response):
                # Short-circuit! Skip HTTP and remaining request interceptors
                response = result
                # Still apply modify_response chain to short-circuited response
                for resp_interceptor in reversed(self.interceptors):
                    response = resp_interceptor.modify_response(
                        response, request
                    )
                return response
            modified_request = result

        # Use the modified request for HTTP
        http_params = modified_request.request

        try:
            http_response = self._client.request(
                method=http_params.method.value,
                url=http_params.url,
                headers=http_params.headers,
                cookies=http_params.cookies,
                content=http_params.data
                if isinstance(http_params.data, bytes)
                else None,
                data=http_params.data  # type: ignore[arg-type]
                if isinstance(http_params.data, dict)
                else None,
            )
        except httpx.TimeoutException:
            raise RequestTimeoutException(
                url=http_params.url, timeout_seconds=30
            )

        # Check for server errors (5xx status codes)
        # 429 (Too Many Requests) is handled by rate limiter interceptor
        if http_response.status_code >= 500:
            raise HTMLResponseAssumptionException(
                status_code=http_response.status_code,
                expected_codes=[200],
                url=http_params.url,
            )

        response = Response(
            status_code=http_response.status_code,
            headers=dict(http_response.headers),
            content=http_response.content,
            text=http_response.text,
            url=http_params.url,
            request=modified_request,
        )

        # Apply modify_response interceptor chain (in reverse order)
        for interceptor in reversed(self.interceptors):
            response = interceptor.modify_response(response, request)

        return response


class AsyncRequestManager:
    """Manages HTTP requests with interceptor support for asynchronous drivers.

    This class encapsulates:
    - httpx.AsyncClient lifecycle
    - Interceptor chain application
    - Request resolution (URL fetching)
    - Response transformation

    Example:
        manager = AsyncRequestManager(
            interceptors=[cache, rate_limiter],
            ssl_context=scraper.get_ssl_context(),
            timeout=30.0,
        )
        response = await manager.resolve_request(request)
    """

    def __init__(
        self,
        interceptors: list[AsyncInterceptor] | None = None,
        ssl_context: ssl.SSLContext | None = None,
        timeout: float | None = None,
    ) -> None:
        """Initialize the request manager.

        Args:
            interceptors: List of async interceptors to apply to requests and
                responses. Interceptors are applied in order for requests, and
                in reverse order for responses. Order matters - cache should
                come before rate limiter.
            ssl_context: Optional SSL context for HTTPS connections. Use this
                for servers requiring specific cipher suites.
            timeout: Request timeout in seconds. None means no timeout (default).
        """
        self.interceptors = interceptors or []
        self.timeout = timeout

        # Initialize httpx async client
        if ssl_context:
            self._client = httpx.AsyncClient(
                verify=ssl_context, timeout=timeout
            )
        else:
            self._client = httpx.AsyncClient(timeout=timeout)

    async def close(self) -> None:
        """Close the HTTP client and release resources."""
        await self._client.aclose()

    async def __aenter__(self) -> AsyncRequestManager:
        """Async context manager entry."""
        return self

    async def __aexit__(self, *args: Any) -> None:
        """Async context manager exit - closes the client."""
        await self.close()

    async def resolve_request(self, request: BaseRequest) -> Response:
        """Fetch a BaseRequest and return the Response.

        Applies the interceptor chain, makes the HTTP request (unless
        short-circuited), and transforms the response.

        Args:
            request: The BaseRequest to fetch. URL should be absolute.

        Returns:
            Response containing the HTTP response data.

        Raises:
            HTMLResponseAssumptionException: If server returns 5xx status code.
            httpx.TimeoutException: If request times out (for retry handling).
        """
        # Apply modify_request interceptor chain
        modified_request = request
        for interceptor in self.interceptors:
            result = await interceptor.modify_request(modified_request)
            if isinstance(result, Response):
                # Short-circuit! Skip HTTP and remaining request interceptors
                response = result
                # Still apply modify_response chain to short-circuited response
                for resp_interceptor in reversed(self.interceptors):
                    response = await resp_interceptor.modify_response(
                        response, request
                    )
                return response
            modified_request = result

        # Use the modified request for HTTP
        http_params = modified_request.request

        # Prepare content and data parameters for httpx
        request_data = http_params.data
        content_param: bytes | None = (
            request_data if isinstance(request_data, bytes) else None
        )
        data_param: dict[str, Any] | None = (
            cast(dict[str, Any], request_data)
            if isinstance(request_data, dict)
            else None
        )

        # Make the HTTP request
        try:
            http_response = await self._client.request(
                method=http_params.method.value,
                url=http_params.url,
                headers=http_params.headers,
                cookies=http_params.cookies,
                content=content_param,
                data=data_param,
            )
        except httpx.TimeoutException:
            raise RequestTimeoutException(
                url=http_params.url,
                timeout_seconds=30,
            )

        # Check for server errors (5xx status codes)
        # 429 (Too Many Requests) is handled by rate limiter interceptor
        if http_response.status_code >= 500:
            raise HTMLResponseAssumptionException(
                status_code=http_response.status_code,
                expected_codes=[200],
                url=http_params.url,
            )

        response = Response(
            status_code=http_response.status_code,
            headers=dict(http_response.headers),
            content=http_response.content,
            text=http_response.text,
            url=http_params.url,
            request=modified_request,
        )

        # Apply modify_response interceptor chain (in reverse order)
        for interceptor in reversed(self.interceptors):
            response = await interceptor.modify_response(response, request)

        return response
