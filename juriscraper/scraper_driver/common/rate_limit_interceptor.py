"""Rate limiting interceptor for controlling request rates.

This interceptor uses pyrate_limiter to enforce rate limits on HTTP requests.
It supports adaptive rate limiting that automatically reduces the rate when
receiving 429 (Too Many Requests) responses.

Step 12: Rate Limiting Interceptor
"""

import time
from threading import Lock

from pyrate_limiter import Duration, Limiter, Rate

from juriscraper.scraper_driver.data_types import BaseRequest, Response


class RateLimitInterceptor:
    """Interceptor that enforces rate limits on HTTP requests.

    This interceptor delays requests to maintain a specified rate limit.
    It also implements adaptive rate limiting by increasing the interval
    (reducing the rate) when receiving 429 responses from the server.

    By default, each 429 response increases the interval by 10%, which
    reduces the rate to approximately 91% of the previous rate.

    Example:
        # Limit to 1 request per second
        rate_limiter = RateLimitInterceptor(requests_per_second=1.0)

        # Limit to 10 requests per minute
        rate_limiter = RateLimitInterceptor(requests_per_minute=10)

        # With adaptive rate limiting (default)
        rate_limiter = RateLimitInterceptor(
            requests_per_second=5.0,
            adaptive=True,
            adaptive_increase=0.10,  # Increase interval by 10% on 429
        )

        driver = SyncDriver(
            scraper,
            interceptors=[cache, rate_limiter],  # cache before rate limiter
        )
    """

    def __init__(
        self,
        requests_per_second: float | None = None,
        requests_per_minute: float | None = None,
        adaptive: bool = True,
        adaptive_increase: float = 0.10,
    ) -> None:
        """Initialize the rate limit interceptor.

        Args:
            requests_per_second: Maximum requests per second. Takes precedence
                over requests_per_minute if both are provided.
            requests_per_minute: Maximum requests per minute. Only used if
                requests_per_second is not provided.
            adaptive: Whether to automatically reduce rate on 429 responses.
            adaptive_increase: Factor to increase interval by when adapting (0.10 = 10% slower).

        Raises:
            ValueError: If neither requests_per_second nor requests_per_minute is provided.
        """
        if requests_per_second is None and requests_per_minute is None:
            raise ValueError(
                "Must provide either requests_per_second or requests_per_minute"
            )

        # Convert to requests per second
        if requests_per_second is not None:
            self.current_rate: float = requests_per_second
            self.duration = Duration.SECOND
        else:
            self.current_rate = requests_per_minute  # type: ignore[assignment]
            self.duration = Duration.MINUTE

        self.adaptive = adaptive
        self.adaptive_increase = adaptive_increase
        self._lock = Lock()

        # Create limiter
        self._create_limiter()

        # Track stats
        self.total_requests = 0
        self.total_wait_time = 0.0
        self.adaptive_reductions = 0

    def _create_limiter(self) -> None:
        """Create a new limiter with the current rate."""
        rate = Rate(int(self.current_rate), self.duration)
        # max_delay allows the limiter to sleep/delay instead of raising exception
        # Set to 1 hour max delay (very generous)
        self.limiter = Limiter(rate, max_delay=Duration.HOUR)

    def modify_request(self, request: BaseRequest) -> BaseRequest | Response:
        """Delay request if needed to maintain rate limit.

        Args:
            request: The request to potentially delay.

        Returns:
            The original request (after any necessary delay).
        """
        start_time = time.time()

        # Acquire rate limit (blocks until allowed)
        with self._lock:
            self.limiter.try_acquire("default")
            self.total_requests += 1

        # Track wait time
        wait_time = time.time() - start_time
        self.total_wait_time += wait_time

        return request

    def modify_response(
        self, response: Response, request: BaseRequest
    ) -> Response:
        """Detect 429 responses and adapt rate if enabled.

        Args:
            response: The response to check.
            request: The original request.

        Returns:
            The unmodified response.
        """
        if self.adaptive and response.status_code == 429:
            self._reduce_rate()

        return response

    def _reduce_rate(self) -> None:
        """Reduce the current rate limit (adaptive rate limiting).

        Increases the interval by adaptive_increase (default 10%), which
        effectively slows down the request rate. For example, with a 10%
        increase in interval, the rate becomes ~91% of the original.
        """
        with self._lock:
            old_rate = self.current_rate
            # Increasing interval by X% means reducing rate by X/(1+X)
            # e.g., 10% interval increase = rate * (1/(1+0.10)) = rate * 0.909
            self.current_rate = self.current_rate / (
                1.0 + self.adaptive_increase
            )  # type: ignore[operator]
            self._create_limiter()
            self.adaptive_reductions += 1

            # Log the reduction (could be replaced with proper logging)
            print(
                f"Rate limit reduced from {old_rate:.2f} to "
                f"{self.current_rate:.2f} requests per "
                f"{'second' if self.duration == Duration.SECOND else 'minute'}"
            )

    def get_stats(self) -> dict[str, int | float]:
        """Get statistics about rate limiting.

        Returns:
            Dictionary with stats about requests, wait time, and adaptations.
        """
        with self._lock:
            avg_wait = (
                self.total_wait_time / self.total_requests
                if self.total_requests > 0
                else 0.0
            )
            return {
                "total_requests": self.total_requests,
                "total_wait_time": self.total_wait_time,
                "average_wait_time": avg_wait,
                "current_rate": self.current_rate,
                "adaptive_reductions": self.adaptive_reductions,
            }
