"""Adaptive Token Bucket (ATB) Rate Limiter.

This module implements an adaptive rate limiter based on the ATB algorithm
from the paper. It dynamically adjusts the request rate based on server
responses:
- On success (2xx): increase rate using multiplicative factors
- On rate limiting (429/5xx): halve the rate and record congestion level

The rate limiter persists its state to SQLite for suspend/resume capability.

Key features:
- Token bucket for burst control
- Adaptive rate based on server feedback
- Uniform jitter for timing unpredictability
- SQL persistence for state recovery
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from juriscraper.scraper_driver.common.interceptors import AsyncInterceptor
from juriscraper.scraper_driver.data_types import BaseRequest, Response

if TYPE_CHECKING:
    from juriscraper.scraper_driver.driver.dev_driver.sql_manager import (
        SQLManager,
    )

logger = logging.getLogger(__name__)


@dataclass
class ATBConfig:
    """Configuration for Adaptive Token Bucket rate limiter.

    Attributes:
        bucket_size: Maximum tokens in the bucket. Default: 4.0
        initial_tokens: Starting token count. Default: 1.0
        initial_rate: Initial rate in tokens/second. Default: 0.1 (6 req/min)
        initial_congestion: Initial congestion rate. Default: 1.0
        first_step: Aggressive rate increase multiplier (below congestion). Default: 1.5
        second_step: Conservative rate increase multiplier (above congestion). Default: 1.2
        min_rate: Minimum allowed rate. Default: 0.01
        jitter: Uniform jitter ±seconds after token acquisition. Default: 2.0
    """

    bucket_size: float = 4.0
    initial_tokens: float = 1.0
    initial_rate: float = 0.1
    initial_congestion: float = 1.0
    first_step: float = 1.5
    second_step: float = 1.2
    min_rate: float = 0.01
    jitter: float = 2.0


class ATBAsyncInterceptor(AsyncInterceptor):
    """Adaptive Token Bucket rate limiter as an async interceptor.

    This interceptor:
    1. Waits for token availability before allowing requests (modify_request)
    2. Adjusts rate based on response status code (modify_response)

    The token bucket generates tokens at the current rate. When a request
    needs to be made, the interceptor waits until a token is available.

    Rate adjustment:
    - Success (2xx): Rate increases using first_step (aggressive) or
      second_step (conservative) based on whether we're below or above
      the last congestion rate.
    - Rate limited (429) or server error (5xx): Rate halves and current
      rate is recorded as the new congestion rate.

    Example:
        config = ATBConfig(initial_rate=0.1, jitter=2.0)
        interceptor = ATBAsyncInterceptor(config, sql_manager)
        await interceptor.initialize()

        # In interceptor chain:
        request = await interceptor.modify_request(request)  # waits for token
        response = await interceptor.modify_response(response, request)  # adjusts rate
    """

    def __init__(self, config: ATBConfig, sql_manager: SQLManager) -> None:
        """Initialize the ATB interceptor.

        Args:
            config: ATB configuration parameters.
            sql_manager: SQLManager for persisting state.
        """
        self.config = config
        self.sql_manager = sql_manager

        # In-memory state (loaded from/persisted to DB)
        self._tokens = config.initial_tokens
        self._rate = config.initial_rate
        self._bucket_size = config.bucket_size
        self._last_congestion_rate = config.initial_congestion
        self._jitter = config.jitter
        self._last_used = time.time()

        # Lock for thread-safe token operations
        self._lock = asyncio.Lock()

        # Statistics (also persisted)
        self._total_requests = 0
        self._total_successes = 0
        self._total_rate_limited = 0

    async def initialize(self) -> None:
        """Initialize the rate limiter from database or config.

        Loads existing state from database if available, otherwise
        initializes with config defaults and persists to database.
        """
        state = await self.sql_manager.get_rate_limiter_state()

        if state is not None:
            # Restore from database
            self._tokens = state["tokens"]
            self._rate = state["rate"]
            self._bucket_size = state["bucket_size"]
            self._last_congestion_rate = state["last_congestion_rate"]
            self._jitter = state["jitter"]
            self._last_used = state["last_used_at"]
            self._total_requests = state["total_requests"]
            self._total_successes = state["total_successes"]
            self._total_rate_limited = state["total_rate_limited"]

            # Regenerate tokens based on time elapsed since last_used
            elapsed = time.time() - self._last_used
            self._tokens = min(
                self._bucket_size, self._tokens + elapsed * self._rate
            )

            logger.info(
                f"ATB rate limiter restored: rate={self._rate:.4f}/s "
                f"({self._rate * 60:.2f}/min), tokens={self._tokens:.2f}, "
                f"congestion_rate={self._last_congestion_rate:.4f}"
            )
        else:
            # Initialize with config defaults
            self._tokens = self.config.initial_tokens
            self._rate = self.config.initial_rate
            self._bucket_size = self.config.bucket_size
            self._last_congestion_rate = self.config.initial_congestion
            self._jitter = self.config.jitter
            self._last_used = time.time()

            await self._persist_state()

            logger.info(
                f"ATB rate limiter initialized: rate={self._rate:.4f}/s "
                f"({self._rate * 60:.2f}/min), bucket_size={self._bucket_size}"
            )

    async def _persist_state(self) -> None:
        """Persist current state to database."""
        await self.sql_manager.upsert_rate_limiter_state(
            tokens=self._tokens,
            rate=self._rate,
            bucket_size=self._bucket_size,
            last_congestion_rate=self._last_congestion_rate,
            jitter=self._jitter,
            last_used_at=self._last_used,
            total_requests=self._total_requests,
            total_successes=self._total_successes,
            total_rate_limited=self._total_rate_limited,
        )

    async def _acquire_token(self) -> None:
        """Acquire a token from the bucket, waiting if necessary.

        Generates tokens based on time elapsed, then either:
        - Returns immediately if a token is available
        - Waits for enough time to generate a token
        """
        async with self._lock:
            now = time.time()

            # Generate tokens based on elapsed time
            elapsed = now - self._last_used
            self._tokens = min(
                self._bucket_size, self._tokens + elapsed * self._rate
            )

            if self._tokens >= 1.0:
                # Token available - consume it
                self._tokens -= 1.0
                self._last_used = now
            else:
                # Need to wait for token generation
                wait_time = (1.0 - self._tokens) / self._rate
                self._tokens = 0.0  # Will be consumed after wait
                self._last_used = now + wait_time

                # Release lock while waiting
                self._lock.release()
                try:
                    await asyncio.sleep(wait_time)
                finally:
                    await self._lock.acquire()

            # Apply uniform jitter after token acquisition
            if self._jitter > 0:
                jitter_delay = random.uniform(-self._jitter, self._jitter)
                if jitter_delay > 0:
                    # Release lock while sleeping for jitter
                    self._lock.release()
                    try:
                        await asyncio.sleep(jitter_delay)
                    finally:
                        await self._lock.acquire()

    def _increase_rate(self) -> float:
        """Increase rate based on success.

        Uses first_step (aggressive) if below congestion rate,
        second_step (conservative) if at or above.

        Returns:
            New rate after increase.
        """
        min_increase = 0.01

        if self._rate < self._last_congestion_rate:
            # Below congestion - aggressive increase
            new_rate = max(
                self._rate + min_increase, self._rate * self.config.first_step
            )
            step = "aggressive"
        else:
            # At or above congestion - conservative increase
            new_rate = max(
                self._rate + min_increase, self._rate * self.config.second_step
            )
            step = "conservative"

        old_rate = self._rate
        self._rate = round(new_rate, 4)

        logger.debug(
            f"ATB rate increased ({step}): {old_rate:.4f} -> {self._rate:.4f}/s "
            f"({self._rate * 60:.2f}/min)"
        )

        return self._rate

    def _decrease_rate(self) -> float:
        """Decrease rate upon congestion (429/5xx).

        Halves the rate, records current rate as congestion rate,
        and empties the token bucket.

        Returns:
            New rate after decrease.
        """
        old_rate = self._rate
        self._last_congestion_rate = self._rate
        self._rate = max(self.config.min_rate, round(self._rate / 2.0, 4))
        self._tokens = 0.0

        logger.info(
            f"ATB rate decreased (congestion): {old_rate:.4f} -> {self._rate:.4f}/s "
            f"({self._rate * 60:.2f}/min), congestion_rate={self._last_congestion_rate:.4f}"
        )

        return self._rate

    async def modify_request(
        self, request: BaseRequest
    ) -> BaseRequest | Response:
        """Wait for token availability before allowing the request.

        Args:
            request: The request to be made.

        Returns:
            The unmodified request (after waiting for a token).
        """
        await self._acquire_token()
        return request

    async def modify_response(
        self, response: Response, original_request: BaseRequest
    ) -> Response:
        """Adjust rate based on response status code.

        Args:
            response: The response received.
            original_request: The original request.

        Returns:
            The unmodified response.
        """
        status_code = response.status_code

        if 200 <= status_code < 300:
            # Success - increase rate
            self._total_requests += 1
            self._total_successes += 1
            new_rate = self._increase_rate()
            await self.sql_manager.update_rate_limiter_rate_increase(new_rate)

        elif status_code in (429, 408, 425, 500, 502, 503, 504):
            # Rate limited or server error - decrease rate
            self._total_requests += 1
            self._total_rate_limited += 1
            new_rate = self._decrease_rate()
            await self.sql_manager.update_rate_limiter_rate_decrease(
                new_rate, self._last_congestion_rate
            )

        else:
            # Other status codes - track but don't adjust rate
            self._total_requests += 1
            # Update tokens state in DB
            await self.sql_manager.update_rate_limiter_tokens(
                self._tokens, self._last_used
            )

        return response

    @property
    def state(self) -> dict[str, Any]:
        """Get current rate limiter state for monitoring.

        Returns:
            Dictionary with current state information.
        """
        return {
            "tokens": self._tokens,
            "rate": self._rate,
            "bucket_size": self._bucket_size,
            "last_congestion_rate": self._last_congestion_rate,
            "jitter": self._jitter,
            "last_used_at": self._last_used,
            "total_requests": self._total_requests,
            "total_successes": self._total_successes,
            "total_rate_limited": self._total_rate_limited,
            "approximate_requests_per_minute": self._rate * 60,
            "success_rate": (
                self._total_successes / self._total_requests * 100
                if self._total_requests > 0
                else 100.0
            ),
            "status": self._compute_status(),
        }

    def _compute_status(self) -> str:
        """Compute human-readable status.

        Returns:
            One of: "healthy", "throttled", "recovering"
        """
        if self._total_rate_limited == 0:
            return "healthy"
        elif self._rate < self._last_congestion_rate:
            return "recovering"
        else:
            return "throttled"
