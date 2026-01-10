"""Rate limiting with jitter for LocalDevDriver.

This module provides a rate limiting interceptor that adds randomized delays
between requests to avoid detection and reduce server load during development.

Also provides AioSQLiteBucket for pyrate_limiter integration with persistent
storage in SQLite.
"""

from __future__ import annotations

import asyncio
import random
import time
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from pyrate_limiter import AbstractBucket, Rate, RateItem

from juriscraper.scraper_driver.data_types import BaseRequest, Response
from juriscraper.scraper_driver.driver.dev_driver.sql_queries import SQL

if TYPE_CHECKING:
    import aiosqlite


class JitterRateLimitInterceptor:
    """Rate limiter with randomized jitter for natural request patterns.

    Implements the AsyncInterceptor protocol, adding a delay before each
    request with randomized jitter to simulate human browsing patterns.

    The actual delay for each request will be:
        base_delay + random.uniform(-jitter, +jitter)

    Example with defaults (base_delay=10.0, jitter=2.0):
        Delays will range from 8.0 to 12.0 seconds

    Attributes:
        base_delay_seconds: Base delay between requests.
        jitter_seconds: Maximum jitter to add/subtract from base delay.
        last_request_time: Timestamp of last request (for tracking).
    """

    def __init__(
        self,
        base_delay_seconds: float = 10.0,
        jitter_seconds: float = 2.0,
    ) -> None:
        """Initialize the rate limiter.

        Args:
            base_delay_seconds: Base delay between requests in seconds.
                Default is 10.0 seconds.
            jitter_seconds: Maximum jitter to add/subtract from base delay.
                Default is 2.0 seconds (so delays range from 8.0 to 12.0).

        Raises:
            ValueError: If base_delay_seconds < jitter_seconds (would allow negative delays).
        """
        if base_delay_seconds < jitter_seconds:
            raise ValueError(
                f"base_delay_seconds ({base_delay_seconds}) must be >= "
                f"jitter_seconds ({jitter_seconds}) to avoid negative delays"
            )

        self.base_delay_seconds = base_delay_seconds
        self.jitter_seconds = jitter_seconds
        self.last_request_time: datetime | None = None
        self._lock = asyncio.Lock()

    def _calculate_delay(self) -> float:
        """Calculate the delay with jitter for the next request.

        Returns:
            Delay in seconds (always positive due to validation in __init__).
        """
        jitter = random.uniform(-self.jitter_seconds, self.jitter_seconds)
        return self.base_delay_seconds + jitter

    async def modify_request(self, request: BaseRequest) -> BaseRequest:
        """Apply jittered delay before allowing the request to proceed.

        This method is called before each HTTP request. It calculates a
        randomized delay and sleeps for that duration.

        Args:
            request: The request about to be sent.

        Returns:
            The unmodified request (rate limiting doesn't change the request).
        """
        async with self._lock:
            # Calculate delay with jitter
            delay = self._calculate_delay()

            # Sleep for the calculated delay
            await asyncio.sleep(delay)

            # Track when this request was made
            self.last_request_time = datetime.now(timezone.utc)

        return request

    async def modify_response(
        self, response: Response, request: BaseRequest
    ) -> Response:
        """Pass-through for responses (no modification needed).

        Rate limiting only affects outgoing requests, not responses.

        Args:
            response: The response received.
            request: The original request.

        Returns:
            The unmodified response.
        """
        return response


class AioSQLiteBucket(AbstractBucket):
    """Async SQLite-backed bucket for pyrate_limiter.

    Implements the AbstractBucket interface using aiosqlite for persistent
    rate limiting state that survives process restarts.

    The bucket stores rate items in the rate_items table, allowing the
    rate limiter to track request timestamps across restarts.

    Note: This is an async bucket - all methods return awaitables.

    Example:
        rates = [Rate(5, Duration.SECOND)]  # 5 requests per second
        bucket = AioSQLiteBucket(db, rates)
        limiter = Limiter(bucket)
    """

    def __init__(
        self,
        db: aiosqlite.Connection,
        rates: list[Rate],
    ) -> None:
        """Initialize the bucket.

        Args:
            db: Database connection (should be same as LocalDevDriver's).
            rates: List of Rate objects defining rate limits.
        """
        self._db = db
        self._rates = rates
        self._lock = asyncio.Lock()

    @property
    def rates(self) -> list[Rate]:
        """Get the rate limits for this bucket."""
        return self._rates

    def limiter_lock(self) -> asyncio.Lock:
        """Get the lock for thread-safe operations."""
        return self._lock

    async def put(self, item: RateItem) -> bool:
        """Add a rate item to the bucket.

        Args:
            item: The rate item to add.

        Returns:
            True if item was added successfully.
        """
        await self._db.execute(
            SQL.INSERT_RATE_ITEM,
            (item.name, item.timestamp, item.weight),
        )
        await self._db.commit()
        return True

    async def leak(self, current_timestamp: int | None = None) -> int:
        """Remove expired items from the bucket.

        Items older than the longest rate interval are removed.

        Args:
            current_timestamp: Current timestamp in milliseconds. If None,
                uses the current time.

        Returns:
            Number of items removed.
        """
        if current_timestamp is None:
            current_timestamp = int(time.time() * 1000)

        # Find the longest interval from all rates
        max_interval = max(rate.interval for rate in self._rates)

        # Remove items older than the longest interval
        cutoff = current_timestamp - max_interval

        cursor = await self._db.execute(
            SQL.DELETE_EXPIRED_RATE_ITEMS, (cutoff,)
        )
        await self._db.commit()

        return cursor.rowcount

    async def flush(self) -> None:
        """Remove all items from the bucket."""
        await self._db.execute(SQL.DELETE_ALL_RATE_ITEMS)
        await self._db.commit()

    async def count(self) -> int:
        """Get the total weight of items in the bucket.

        Returns:
            Sum of weights of all items.
        """
        cursor = await self._db.execute(SQL.SELECT_RATE_ITEMS_SUM_WEIGHT)
        row = await cursor.fetchone()
        return row[0] if row else 0

    async def peek(self, index: int) -> RateItem | None:
        """Get an item at a specific index without removing it.

        Args:
            index: Zero-based index (ordered by timestamp DESC).

        Returns:
            RateItem at the index, or None if not found.
        """
        cursor = await self._db.execute(
            SQL.SELECT_RATE_ITEM_AT_INDEX, (index,)
        )
        row = await cursor.fetchone()

        if row is None:
            return None

        return RateItem(name=row[0], timestamp=row[1], weight=row[2])

    async def waiting(self, item: RateItem) -> int:
        """Calculate how long to wait before the item can be processed.

        Checks all rate limits and returns the maximum wait time needed.

        Args:
            item: The item wanting to be processed.

        Returns:
            Wait time in milliseconds (0 if no wait needed).
        """
        current_timestamp = item.timestamp
        max_wait = 0

        for rate in self._rates:
            # Count items in the rate window
            window_start = current_timestamp - rate.interval

            cursor = await self._db.execute(
                SQL.SELECT_RATE_WINDOW_STATS, (window_start,)
            )
            row = await cursor.fetchone()
            current_count = row[0] if row else 0
            oldest_timestamp = row[1] if row and row[1] else current_timestamp

            # Check if we've exceeded the rate limit
            if current_count + item.weight > rate.limit:
                # Calculate wait time until oldest item expires
                wait_until = oldest_timestamp + rate.interval
                wait_time = wait_until - current_timestamp
                max_wait = max(max_wait, wait_time)

        return max(0, max_wait)
