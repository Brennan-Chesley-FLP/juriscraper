Step 12: Rate Limiting Interceptor
====================================

In Step 11, we introduced the interceptor pattern for request/response
transformation. Now we use that pattern to implement **rate limiting** - controlling
how fast we make HTTP requests to avoid overwhelming servers or violating rate limits.

Web scrapers must be good citizens. Making requests too quickly can:

- **Overwhelm servers** - Cause performance degradation for other users
- **Trigger rate limiting** - Receive 429 (Too Many Requests) responses
- **Get blocked** - IP addresses banned for aggressive behavior
- **Violate terms of service** - Many sites specify rate limits in their ToS

This step introduces the **RateLimitInterceptor** to enforce configurable rate
limits with support for adaptive rate reduction when receiving 429 responses.


Overview
--------

In this step, we introduce:

1. **RateLimitInterceptor** - Delays requests to maintain a specified rate limit
2. **Adaptive rate limiting** - Automatically reduces rate when receiving 429 responses
3. **Statistics tracking** - Monitor requests, delays, and rate adjustments
4. **429 handling** - 429 responses pass through to interceptors (not raised by driver)


Rate Limit Interceptor
-----------------------

The RateLimitInterceptor enforces rate limits using the pyrate_limiter library:

.. code-block:: python

    from juriscraper.scraper_driver.common.rate_limit_interceptor import (
        RateLimitInterceptor,
    )

    # Limit to 2 requests per second
    rate_limiter = RateLimitInterceptor(requests_per_second=2.0)

    # Limit to 60 requests per minute
    rate_limiter = RateLimitInterceptor(requests_per_minute=60)

    # With adaptive rate limiting (enabled by default)
    rate_limiter = RateLimitInterceptor(
        requests_per_second=5.0,
        adaptive=True,
        adaptive_increase=0.10,  # Increase interval by 10% on 429
    )

**Key features:**

- **Configurable rate** - Specify requests per second or requests per minute
- **Automatic delay** - Blocks requests until rate limit allows
- **Adaptive** - Reduces rate when receiving 429 responses
- **Thread-safe** - Uses locks for concurrent access
- **Statistics** - Track total requests, wait time, and adaptations


Implementation
--------------

The RateLimitInterceptor uses pyrate_limiter's Limiter class:

.. code-block:: python

    from pyrate_limiter import Duration, Limiter, Rate

    class RateLimitInterceptor:
        def __init__(
            self,
            requests_per_second: float | None = None,
            requests_per_minute: float | None = None,
            adaptive: bool = True,
            adaptive_increase: float = 0.10,
        ) -> None:
            # Validate at least one rate parameter
            if requests_per_second is None and requests_per_minute is None:
                raise ValueError(
                    "Must provide either requests_per_second or requests_per_minute"
                )

            # Convert to rate and duration
            if requests_per_second is not None:
                self.current_rate = requests_per_second
                self.duration = Duration.SECOND
            else:
                self.current_rate = requests_per_minute
                self.duration = Duration.MINUTE

            # Create limiter
            rate = Rate(int(self.current_rate), self.duration)
            self.limiter = Limiter(rate, max_delay=Duration.HOUR)

**Parameters:**

- **requests_per_second** - Maximum requests per second (takes precedence)
- **requests_per_minute** - Maximum requests per minute (used if per_second not provided)
- **adaptive** - Enable adaptive rate reduction on 429 responses (default: True)
- **adaptive_increase** - Factor to increase interval by when adapting (default: 0.10)


Modify Request: Delay
^^^^^^^^^^^^^^^^^^^^^

The ``modify_request`` method delays requests to maintain the rate limit:

.. code-block:: python

    def modify_request(
        self, request: BaseRequest
    ) -> BaseRequest | Response:
        """Delay request if needed to maintain rate limit."""
        start_time = time.time()

        # Acquire rate limit (blocks until allowed)
        with self._lock:
            self.limiter.try_acquire("default")
            self.total_requests += 1

        # Track wait time
        wait_time = time.time() - start_time
        self.total_wait_time += wait_time

        return request

**Behavior:**

- **Blocks until allowed** - ``try_acquire()`` sleeps if rate exceeded
- **Thread-safe** - Uses lock to protect limiter and stats
- **Returns request** - Always returns original request (never short-circuits)


Modify Response: Detect 429
^^^^^^^^^^^^^^^^^^^^^^^^^^^^

The ``modify_response`` method detects 429 responses and adapts the rate:

.. code-block:: python

    def modify_response(
        self, response: Response, request: BaseRequest
    ) -> Response:
        """Detect 429 responses and adapt rate if enabled."""
        if self.adaptive and response.status_code == 429:
            self._reduce_rate()

        return response

    def _reduce_rate(self) -> None:
        """Reduce the current rate limit (adaptive rate limiting)."""
        with self._lock:
            old_rate = self.current_rate
            # Increasing interval by X% means reducing rate by X/(1+X)
            # e.g., 10% interval increase = rate * (1/(1+0.10)) = rate * 0.909
            self.current_rate = self.current_rate / (1.0 + self.adaptive_increase)
            self._create_limiter()
            self.adaptive_reductions += 1

**Behavior:**

- **Detects 429** - Checks response status code
- **Reduces rate** - Increases interval by adaptive_increase (default 10%), which reduces rate to ~91% of original
- **Recreates limiter** - Creates new limiter with reduced rate
- **Tracks adaptations** - Increments adaptive_reductions counter


429 Handling Changes
---------------------

In Step 10, the driver raised ``HTMLResponseAssumptionException`` for 429 responses.
This prevented the rate limiter from seeing them.

In Step 12, we changed the driver to **not raise for 429**:

.. code-block:: python

    # Step 10: Check for server errors (5xx status codes)
    # Step 12: 429 (Too Many Requests) is handled by rate limiter interceptor
    if http_response.status_code >= 500:
        raise HTMLResponseAssumptionException(
            status_code=http_response.status_code,
            expected_codes=[200],
            url=http_params.url,
        )

**Why this change?**

- **429 is not an error** - It's a signal to slow down
- **Interceptors can handle it** - Rate limiter adapts automatically


Statistics Tracking
-------------------

The RateLimitInterceptor tracks statistics about rate limiting:

.. code-block:: python

    rate_limiter = RateLimitInterceptor(requests_per_second=2.0)

    # ... run driver ...

    stats = rate_limiter.get_stats()
    print(f"Total requests: {stats['total_requests']}")
    print(f"Total wait time: {stats['total_wait_time']:.2f}s")
    print(f"Average wait: {stats['average_wait_time']:.2f}s")
    print(f"Current rate: {stats['current_rate']}")
    print(f"Adaptive reductions: {stats['adaptive_reductions']}")

**Stats returned:**

- **total_requests** - Total number of requests processed
- **total_wait_time** - Total seconds spent waiting for rate limit
- **average_wait_time** - Average wait time per request
- **current_rate** - Current rate limit (may be reduced from initial)
- **adaptive_reductions** - Number of times rate was reduced due to 429


Next Steps
----------

In :doc:`13_archive_callback`, we introduce the on_archive callback hook for
customizing file archival behavior. This allows scrapers to control how
downloaded files are saved, enabling custom storage backends and naming
conventions.
