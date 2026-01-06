Step 11: Interceptor Pattern
==============================

Now with some errors out of the way lets look at **interceptors** - a
middleware pattern that allows transformation of requests before they are sent
and responses after they are received.

Interceptors enable things like caching, rate limiting, logging,
and request mocking without modifying scraper code or subclassing the driver.


Overview
--------

In this step, we introduce:

1. **SyncInterceptor Protocol** - Interface for request/response transformation
2. **Interceptor Chain** - Sequential processing of interceptors
3. **Request Short-Circuiting** - Interceptors can return responses without HTTP
4. **Chain of Responsibility** - Request chain runs forward, response chain reverse

Why Interceptors?
-----------------

Interceptors separate cross-cutting concerns from scraper logic.
They separate out nicely functionality like caching, rate-limiting, mocking, etc.
into small pieces that can be tested separately from the driver.
They are easy to swap in different contexts as the situation calls for.


Interceptor Protocol
--------------------

SyncInterceptor Protocol
^^^^^^^^^^^^^^^^^^^^^^^^^

Interceptors implement two methods:

.. code-block:: python

    from typing import Protocol
    from juriscraper.scraper_driver.data_types import BaseRequest, Response

    class SyncInterceptor(Protocol):
        """Protocol for synchronous interceptors."""

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


Behavior notes
^^^^^^^^^^^^^^

- **modify_request** can return ``BaseRequest`` (continue) or ``Response`` (short-circuit)
- **modify_response** transforms responses after receiving
- **Short-circuiting** skips HTTP and remaining request interceptors
- **Response chain** is still applied to short-circuited responses
- **Interceptor order** matters (cache before rate limiter)


Driver Integration
------------------

The SyncDriver accepts an ``interceptors`` parameter:

.. code-block:: python

    from juriscraper.scraper_driver.driver.sync_driver import SyncDriver
    from juriscraper.scraper_driver.common.example_interceptors import (
        LoggingInterceptor,
        MockInterceptor,
    )

    # Create interceptors
    logger = LoggingInterceptor(prefix="[SCRAPER] ")
    mock = MockInterceptor(mock_responses={...})

    # Pass to driver
    driver = SyncDriver(
        scraper=my_scraper,
        interceptors=[logger, mock],  # Order matters!
        on_data=save_data,
    )

    driver.run()


Request Processing Flow
^^^^^^^^^^^^^^^^^^^^^^^

1. **Apply modify_request chain** (forward order)

   - If any interceptor returns ``Response``, skip to step 4
   - Otherwise, continue with modified request

2. **Make HTTP request** (if not short-circuited)

3. **Create Response object** from HTTP response

4. **Apply modify_response chain** (reverse order)

   - Last interceptor processes response first
   - Allows proper unwinding of request transformations

5. **Pass response to scraper continuation method**


Short-Circuit Behavior
^^^^^^^^^^^^^^^^^^^^^^

When ``modify_request`` returns a ``Response``:

1. **Skip HTTP** - No network request is made
2. **Skip remaining request interceptors** - Chain stops immediately
3. **Still apply response chain** - All interceptors get to transform the response

This enables:

- **Cache hits** return cached responses without network
- **Deduplication** skips duplicate requests
- **Test mocking** returns canned responses

.. code-block:: python

    # Example: Cache interceptor short-circuits on hit
    class CacheInterceptor:
        def __init__(self):
            self.cache = {}

        def modify_request(self, request):
            url = request.request.url
            if url in self.cache:
                # Short-circuit! Return cached response
                return self.cache[url]
            # Cache miss, continue to HTTP
            return request

        def modify_response(self, response, request):
            # Store in cache for future hits
            self.cache[request.request.url] = response
            return response


Example Interceptors
--------------------

LoggingInterceptor
^^^^^^^^^^^^^^^^^^

Logs all requests and responses:

.. code-block:: python

    from juriscraper.scraper_driver.common.example_interceptors import (
        LoggingInterceptor,
    )

    logger = LoggingInterceptor(prefix="[DEBUG] ")
    driver = SyncDriver(scraper, interceptors=[logger])
    driver.run()

    # Output:
    # [DEBUG] Request #1: GET http://example.com/cases
    # [DEBUG] Response #1: 200 from http://example.com/cases
    # [DEBUG] Request #2: GET http://example.com/cases/12345
    # [DEBUG] Response #2: 200 from http://example.com/cases/12345


MockInterceptor
^^^^^^^^^^^^^^^

Returns canned responses for testing:

.. code-block:: python

    from juriscraper.scraper_driver.common.example_interceptors import (
        MockInterceptor,
    )
    from juriscraper.scraper_driver.data_types import Response, BaseRequest

    # Create mock response
    mock_html = "<html><body>Mock Content</body></html>"
    mock_response = Response(
        status_code=200,
        headers={},
        content=mock_html.encode("utf-8"),
        text=mock_html,
        url="http://example.com/test",
        request=BaseRequest(...),
    )

    # Create interceptor
    mock = MockInterceptor(
        mock_responses={"http://example.com/test": mock_response}
    )

    # No HTTP requests will be made to mocked URLs
    driver = SyncDriver(scraper, interceptors=[mock])
    driver.run()


HeaderInterceptor
^^^^^^^^^^^^^^^^^

Adds custom headers to all requests:

.. code-block:: python

    from juriscraper.scraper_driver.common.example_interceptors import (
        HeaderInterceptor,
    )

    # Add custom headers to all requests
    header_interceptor = HeaderInterceptor({
        "User-Agent": "MyBot/1.0",
        "X-Custom-Header": "value",
    })

    driver = SyncDriver(scraper, interceptors=[header_interceptor])
    driver.run()

Summary
-------

Step 14 introduces the interceptor pattern for request/response transformation:

- **SyncInterceptor protocol** with ``modify_request`` and ``modify_response``
- **Interceptor chain** processes requests forward, responses reverse
- **Short-circuiting** allows interceptors to skip HTTP by returning ``Response``
- **Composable middleware** for caching, logging, mocking, rate limiting
- **Clean separation** of cross-cutting concerns from scraper logic

Key benefits:

- Reusable interceptors across scrapers
- Easier testing with MockInterceptor
- No mixing of concerns in scraper code
- Flexible composition via ordering


Next Steps
----------

In :doc:`12_rate_limiting`, we implement a rate limiting interceptor using
this pattern. Rate limiting controls request frequency to avoid overloading
target servers and handles 429 (Too Many Requests) responses with adaptive
backoff.
