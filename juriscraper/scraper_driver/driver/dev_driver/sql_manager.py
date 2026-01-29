"""SQLManager - Database operations for LocalDevDriver.

This module provides a standalone class for all SQLite database operations,
enabling independent testing and programmatic inspection of the database
without requiring a full driver instance.

The SQLManager handles:
- Request queue operations (enqueue, dequeue, status updates)
- Response storage with compression
- Result storage with validation tracking
- Error requeue operations
- Run metadata management
- Speculative progress tracking
- Statistics and listing operations
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Generic, Literal, TypeVar

import aiosqlite
from pydantic import BaseModel

from juriscraper.scraper_driver.driver.dev_driver.schema import (
    get_next_queue_counter,
    init_database,
)
from juriscraper.scraper_driver.driver.dev_driver.sql_queries import SQL

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

logger = logging.getLogger(__name__)


def compute_cache_key(
    method: str,
    url: str,
    body: bytes | None = None,
    headers_json: str | None = None,
) -> str:
    """Compute a cache key for response caching.

    The cache key is a SHA256 hash of the request parameters that affect
    the response: method, URL, body, and headers.

    Args:
        method: HTTP method (GET, POST, etc.).
        url: Request URL.
        body: Request body bytes (for POST/PUT requests).
        headers_json: JSON-encoded headers (optional).

    Returns:
        Hex-encoded SHA256 hash string.
    """
    hasher = hashlib.sha256()
    hasher.update(method.encode("utf-8"))
    hasher.update(b"\x00")
    hasher.update(url.encode("utf-8"))
    hasher.update(b"\x00")
    if body:
        hasher.update(body)
    hasher.update(b"\x00")
    if headers_json:
        hasher.update(headers_json.encode("utf-8"))
    return hasher.hexdigest()


T = TypeVar("T")


@dataclass
class Page(Generic[T]):
    """Paginated result set.

    Attributes:
        items: List of items for this page.
        total: Total number of items matching the query.
        offset: Number of items skipped.
        limit: Maximum items per page.
    """

    items: list[T]
    total: int
    offset: int
    limit: int

    @property
    def has_more(self) -> bool:
        """Check if there are more items after this page."""
        return self.offset + len(self.items) < self.total

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "items": [
                item.to_dict() if hasattr(item, "to_dict") else str(item)
                for item in self.items
            ],
            "total": self.total,
            "offset": self.offset,
            "limit": self.limit,
            "has_more": self.has_more,
        }

    def to_json(self) -> str:
        """Serialize to JSON."""
        return json.dumps(self.to_dict())


class RequeueResult(BaseModel):
    """Result of a requeue operation.

    Reports what was affected by a requeue operation including created
    requests, cleared responses, downstream artifacts, and resolved errors.

    Attributes:
        requeued_request_ids: List of new request IDs created.
        cleared_response_ids: List of response IDs deleted.
        cleared_downstream_request_ids: List of downstream request IDs deleted.
        cleared_result_ids: List of result IDs deleted.
        cleared_error_ids: List of error IDs deleted.
        resolved_error_ids: List of error IDs marked as resolved.
        dry_run: Boolean indicating if this was a dry run.
    """

    requeued_request_ids: list[int] = []
    cleared_response_ids: list[int] = []
    cleared_downstream_request_ids: list[int] = []
    cleared_result_ids: list[int] = []
    cleared_error_ids: list[int] = []
    resolved_error_ids: list[int] = []
    dry_run: bool = False


@dataclass
class RequestRecord:
    """Request record from database.

    Represents a row from the requests table with essential fields
    for display and inspection.
    """

    id: int
    status: str
    priority: int
    queue_counter: int
    method: str
    url: str
    continuation: str
    current_location: str
    created_at: str | None
    started_at: str | None
    completed_at: str | None
    retry_count: int
    cumulative_backoff: float | None
    last_error: str | None
    # High-precision monotonic timestamps (nanoseconds from time.monotonic_ns())
    created_at_ns: int | None = None
    started_at_ns: int | None = None
    completed_at_ns: int | None = None

    @property
    def duration_ns(self) -> int | None:
        """Calculate request duration in nanoseconds (from started to completed)."""
        if self.started_at_ns is not None and self.completed_at_ns is not None:
            return self.completed_at_ns - self.started_at_ns
        return None

    @property
    def duration_ms(self) -> float | None:
        """Calculate request duration in milliseconds."""
        duration = self.duration_ns
        if duration is not None:
            return duration / 1_000_000
        return None

    @property
    def queue_time_ns(self) -> int | None:
        """Calculate time spent in queue in nanoseconds (from created to started)."""
        if self.created_at_ns is not None and self.started_at_ns is not None:
            return self.started_at_ns - self.created_at_ns
        return None

    @property
    def queue_time_ms(self) -> float | None:
        """Calculate time spent in queue in milliseconds."""
        queue_time = self.queue_time_ns
        if queue_time is not None:
            return queue_time / 1_000_000
        return None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "id": self.id,
            "status": self.status,
            "priority": self.priority,
            "queue_counter": self.queue_counter,
            "method": self.method,
            "url": self.url,
            "continuation": self.continuation,
            "current_location": self.current_location,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "retry_count": self.retry_count,
            "cumulative_backoff": self.cumulative_backoff,
            "last_error": self.last_error,
            "created_at_ns": self.created_at_ns,
            "started_at_ns": self.started_at_ns,
            "completed_at_ns": self.completed_at_ns,
            "duration_ms": self.duration_ms,
            "queue_time_ms": self.queue_time_ms,
        }

    def to_json(self) -> str:
        """Serialize to JSON."""
        return json.dumps(self.to_dict())


@dataclass
class ResponseRecord:
    """Response record from database.

    Represents a row from the responses table with essential fields
    for display. Does not include compressed content.
    """

    id: int
    request_id: int
    status_code: int
    url: str
    content_size_original: int | None
    content_size_compressed: int | None
    continuation: str
    created_at: str | None
    compression_dict_id: int | None
    speculation_outcome: str | None = None

    @property
    def compression_ratio(self) -> float | None:
        """Calculate compression ratio if sizes are available."""
        if self.content_size_original and self.content_size_compressed:
            return round(
                self.content_size_original / self.content_size_compressed, 2
            )
        return None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "id": self.id,
            "request_id": self.request_id,
            "status_code": self.status_code,
            "url": self.url,
            "content_size_original": self.content_size_original,
            "content_size_compressed": self.content_size_compressed,
            "compression_ratio": self.compression_ratio,
            "continuation": self.continuation,
            "created_at": self.created_at,
            "compression_dict_id": self.compression_dict_id,
            "speculation_outcome": self.speculation_outcome,
        }

    def to_json(self) -> str:
        """Serialize to JSON."""
        return json.dumps(self.to_dict())


@dataclass
class ResultRecord:
    """Result record from database.

    Represents a row from the results table with essential fields
    for display.
    """

    id: int
    request_id: int | None
    result_type: str
    data_json: str
    is_valid: bool
    validation_errors_json: str | None
    created_at: str | None

    @property
    def data(self) -> dict[str, Any] | None:
        """Parse and return the data as a dictionary."""
        if self.data_json:
            return json.loads(self.data_json)
        return None

    @property
    def validation_errors(self) -> list[str] | None:
        """Parse and return validation errors as a list."""
        if self.validation_errors_json:
            return json.loads(self.validation_errors_json)
        return None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "id": self.id,
            "request_id": self.request_id,
            "result_type": self.result_type,
            "data": json.loads(self.data_json) if self.data_json else None,
            "is_valid": self.is_valid,
            "validation_errors": (
                json.loads(self.validation_errors_json)
                if self.validation_errors_json
                else None
            ),
            "created_at": self.created_at,
        }

    def to_json(self) -> str:
        """Serialize to JSON."""
        return json.dumps(self.to_dict())


class SQLManager:
    """Database manager for LocalDevDriver operations.

    Provides all database operations needed by the LocalDevDriver in a
    standalone class that can be used independently for testing, inspection,
    and programmatic access to the SQLite database.

    Example::

        # Standalone usage for inspection
        async with SQLManager.open(db_path) as manager:
            stats = await manager.get_stats()
            requests = await manager.list_requests(status="pending")

        # With existing connection (for driver integration)
        manager = SQLManager(db)
        await manager.store_response(request_id, response, continuation)
    """

    def __init__(self, db: aiosqlite.Connection) -> None:
        """Initialize with an existing database connection.

        Args:
            db: An open aiosqlite connection.
        """
        self._db = db
        # Lock to serialize database operations - aiosqlite uses a single
        # connection and concurrent operations can cause "cannot commit
        # transaction - SQL statements in progress" errors
        self._lock = asyncio.Lock()

    @classmethod
    @asynccontextmanager
    async def open(cls, db_path: Path) -> AsyncIterator[SQLManager]:
        """Open a database and create a SQLManager.

        This is the preferred way to create a SQLManager for standalone usage.
        Ensures proper initialization and cleanup.

        Args:
            db_path: Path to the SQLite database file.

        Yields:
            SQLManager instance.

        Example::

            async with SQLManager.open(db_path) as manager:
                stats = await manager.get_stats()
        """
        db = await init_database(db_path)
        try:
            yield cls(db)
        finally:
            await db.close()

    @property
    def db(self) -> aiosqlite.Connection:
        """Get the underlying database connection."""
        return self._db

    # --- Run Metadata ---

    async def init_run_metadata(
        self,
        scraper_name: str,
        scraper_version: str | None,
        num_workers: int,
        max_backoff_time: float,
        speculation_config: dict[str, dict[str, int]] | None = None,
        browser_config: dict[str, Any] | None = None,
    ) -> None:
        """Initialize run metadata in database.

        Only creates a new entry if one doesn't exist.

        Args:
            scraper_name: Name of the scraper class.
            scraper_version: Version string if available.
            num_workers: Number of concurrent workers.
            max_backoff_time: Maximum total backoff time before failure.
            speculation_config: Optional dict mapping continuation name to
                {"threshold": int, "speculation": int} for speculative handling.
            browser_config: Optional dict with browser configuration for Playwright
                driver (browser_type, headless, viewport, user_agent, etc.).
        """
        async with self._lock:
            cursor = await self._db.execute(SQL.SELECT_RUN_METADATA_BY_ID)
            row = await cursor.fetchone()

            speculation_config_json = (
                json.dumps(speculation_config) if speculation_config else None
            )
            browser_config_json = (
                json.dumps(browser_config) if browser_config else None
            )

            if row is None:
                # base_delay and jitter kept for schema compatibility but not used
                await self._db.execute(
                    SQL.INSERT_RUN_METADATA,
                    (
                        scraper_name,
                        scraper_version,
                        0.0,  # base_delay (deprecated)
                        0.0,  # jitter (deprecated)
                        num_workers,
                        max_backoff_time,
                        speculation_config_json,
                        browser_config_json,
                    ),
                )
                await self._db.commit()

    async def get_speculation_config(self) -> dict[str, dict[str, int]] | None:
        """Get the speculation configuration from run metadata.

        Returns:
            Dict mapping continuation name to {"threshold": int, "speculation": int},
            or None if not configured.
        """
        cursor = await self._db.execute(SQL.SELECT_SPECULATION_CONFIG)
        row = await cursor.fetchone()
        if row and row[0]:
            return json.loads(row[0])
        return None

    async def update_speculation_config(
        self, config: dict[str, dict[str, int]]
    ) -> None:
        """Update the speculation configuration in run metadata.

        Args:
            config: Dict mapping continuation name to {"threshold": int, "speculation": int}.
        """
        async with self._lock:
            await self._db.execute(
                SQL.UPDATE_SPECULATION_CONFIG, (json.dumps(config),)
            )
            await self._db.commit()

    async def restore_queue(self) -> int:
        """Restore pending requests from database on startup.

        Resets any in_progress requests to pending (they were interrupted).

        Returns:
            Number of pending requests after restoration.
        """
        async with self._lock:
            await self._db.execute(SQL.RESET_IN_PROGRESS_TO_PENDING)
            await self._db.commit()

            cursor = await self._db.execute(SQL.COUNT_PENDING_REQUESTS)
            row = await cursor.fetchone()
            return row[0] if row else 0

    async def close_run(self) -> None:
        """Clean up database state on driver close.

        Resets in_progress requests to pending and updates run status.
        """
        async with self._lock:
            try:
                await self._db.execute(SQL.RESET_IN_PROGRESS_TO_PENDING)
                await self._db.execute(SQL.UPDATE_RUN_STATUS_ON_CLOSE)
                await self._db.commit()
            except Exception as e:
                logger.warning(f"Failed to update state on close: {e}")

    async def update_run_status_running(self) -> None:
        """Mark run as running."""
        async with self._lock:
            await self._db.execute(SQL.UPDATE_RUN_STATUS_RUNNING)
            await self._db.commit()

    async def update_run_status_final(
        self, status: str, error: str | None
    ) -> None:
        """Update run status to final state.

        Args:
            status: Final status (completed, error, interrupted).
            error: Error message if status is error.
        """
        async with self._lock:
            await self._db.execute(
                SQL.UPDATE_RUN_STATUS_FINAL, (status, error)
            )
            await self._db.commit()

    async def update_run_status(self, status: str) -> None:
        """Update run status.

        Args:
            status: New status (running, completed, error, interrupted).
        """
        if status == "running":
            await self.update_run_status_running()
        else:
            await self.update_run_status_final(status, None)

    async def finalize_run(self, status: str, error: str | None) -> None:
        """Finalize run with status and optional error.

        Args:
            status: Final status (completed, error, interrupted).
            error: Error message if status is error.
        """
        await self.update_run_status_final(status, error)

    async def has_any_requests(self) -> bool:
        """Check if there are any requests in the database.

        Returns:
            True if there are any requests, False otherwise.
        """
        cursor = await self._db.execute(SQL.COUNT_ALL_REQUESTS)
        row = await cursor.fetchone()
        return (row[0] if row else 0) > 0

    async def get_run_metadata(self) -> dict[str, Any] | None:
        """Get run metadata from database.

        Returns:
            Dict with run metadata or None if not found.
        """
        cursor = await self._db.execute(SQL.SELECT_RUN_METADATA_FULL)
        row = await cursor.fetchone()
        if row is None:
            return None

        return {
            "scraper_name": row[0],
            "scraper_version": row[1],
            "status": row[2],
            "created_at": row[3],
            "started_at": row[4],
            "ended_at": row[5],
            "error_message": row[6],
            "base_delay": row[7],
            "jitter": row[8],
            "num_workers": row[9],
            "max_backoff_time": row[10],
            "speculation_config": json.loads(row[11]) if row[11] else None,
            "browser_config": json.loads(row[12]) if row[12] else None,
        }

    # --- Request Queue Operations ---

    async def check_dedup_key_exists(self, dedup_key: str) -> bool:
        """Check if a deduplication key already exists.

        Args:
            dedup_key: The deduplication key to check.

        Returns:
            True if the key exists, False otherwise.
        """
        cursor = await self._db.execute(
            SQL.SELECT_REQUEST_BY_DEDUP_KEY, (dedup_key,)
        )
        return await cursor.fetchone() is not None

    async def find_parent_request_id(self, url: str) -> int | None:
        """Find the request ID for a given URL.

        Used to link child requests to their parent.

        Args:
            url: The URL of the parent request.

        Returns:
            Request ID if found, None otherwise.
        """
        cursor = await self._db.execute(SQL.SELECT_PARENT_REQUEST_ID, (url,))
        row = await cursor.fetchone()
        return row[0] if row else None

    async def insert_request(
        self,
        priority: int,
        request_type: str,
        method: str,
        url: str,
        headers_json: str | None,
        cookies_json: str | None,
        body: bytes | None,
        continuation: str,
        current_location: str,
        accumulated_data_json: str | None,
        aux_data_json: str | None,
        permanent_json: str | None,
        expected_type: str | None,
        dedup_key: str | None,
        parent_id: int | None,
        is_speculative: bool = False,
        speculation_id: str | None = None,
    ) -> int:
        """Insert a new request into the queue.

        Args:
            priority: Request priority (lower = higher priority).
            request_type: Type of request (navigating, non_navigating, etc.).
            method: HTTP method.
            url: Request URL.
            headers_json: JSON-encoded headers.
            cookies_json: JSON-encoded cookies.
            body: Request body bytes.
            continuation: Continuation method name.
            current_location: Current navigation location.
            accumulated_data_json: JSON-encoded accumulated data.
            aux_data_json: JSON-encoded aux data.
            permanent_json: JSON-encoded permanent data.
            expected_type: Expected type for archive requests.
            dedup_key: Deduplication key.
            parent_id: Parent request ID.
            is_speculative: Whether this is a speculative request.
            speculation_id: JSON tuple ["func_name", spec_id] for speculative requests.

        Returns:
            The ID of the newly inserted request.
        """
        async with self._lock:
            queue_counter = await get_next_queue_counter(self._db)
            created_at_ns = time.monotonic_ns()

            # Compute cache key for response caching
            cache_key = compute_cache_key(method, url, body, headers_json)

            cursor = await self._db.execute(
                SQL.INSERT_REQUEST,
                (
                    priority,
                    queue_counter,
                    request_type,
                    method,
                    url,
                    headers_json,
                    cookies_json,
                    body,
                    continuation,
                    current_location,
                    accumulated_data_json,
                    aux_data_json,
                    permanent_json,
                    expected_type,
                    dedup_key,
                    parent_id,
                    created_at_ns,
                    cache_key,
                    is_speculative,
                    speculation_id,
                ),
            )
            await self._db.commit()
            return cursor.lastrowid or 0

    async def insert_entry_request(
        self,
        priority: int,
        method: str,
        url: str,
        headers_json: str | None,
        cookies_json: str | None,
        body: bytes | None,
        continuation: str,
        current_location: str,
        accumulated_data_json: str | None,
        aux_data_json: str | None,
        permanent_json: str | None,
        dedup_key: str | None,
    ) -> int:
        """Insert an entry point request.

        Args:
            priority: Request priority.
            method: HTTP method.
            url: Request URL.
            headers_json: JSON-encoded headers.
            cookies_json: JSON-encoded cookies.
            body: Request body bytes.
            continuation: Continuation method name.
            current_location: Current location.
            accumulated_data_json: JSON-encoded accumulated data.
            aux_data_json: JSON-encoded aux data.
            permanent_json: JSON-encoded permanent data.
            dedup_key: Deduplication key.

        Returns:
            The ID of the newly inserted request.
        """
        async with self._lock:
            queue_counter = await get_next_queue_counter(self._db)
            created_at_ns = time.monotonic_ns()

            cursor = await self._db.execute(
                SQL.INSERT_ENTRY_REQUEST,
                (
                    priority,
                    queue_counter,
                    method,
                    url,
                    headers_json,
                    cookies_json,
                    body,
                    continuation,
                    current_location,
                    accumulated_data_json,
                    aux_data_json,
                    permanent_json,
                    dedup_key,
                    created_at_ns,
                ),
            )
            await self._db.commit()
            return cursor.lastrowid or 0

    async def get_next_pending_request(self) -> tuple[Any, ...] | None:
        """Get the next pending request from the queue.

        Selects the highest priority request that is not held and not
        in retry backoff.

        Returns:
            Row tuple or None if queue is empty.

        Note: This method is deprecated for multi-worker scenarios.
        Use dequeue_next_request() instead for atomic dequeue.
        """
        cursor = await self._db.execute(SQL.SELECT_NEXT_PENDING_REQUEST)
        return await cursor.fetchone()

    async def dequeue_next_request(self) -> tuple[Any, ...] | None:
        """Atomically dequeue the next pending request.

        This method atomically selects and marks a request as 'in_progress'
        in a single database operation using UPDATE ... RETURNING. This
        prevents race conditions where multiple workers could select the
        same request.

        Returns:
            Row tuple (same columns as get_next_pending_request) or None
            if the queue is empty.
        """
        async with self._lock:
            started_at_ns = time.monotonic_ns()
            cursor = await self._db.execute(
                SQL.DEQUEUE_NEXT_REQUEST, (started_at_ns,)
            )
            row = await cursor.fetchone()
            await self._db.commit()
            return row

    async def mark_request_in_progress(self, request_id: int) -> None:
        """Mark a request as in progress.

        Args:
            request_id: The database ID of the request.

        Note: This method is deprecated for multi-worker scenarios.
        Use dequeue_next_request() instead for atomic dequeue.
        """
        async with self._lock:
            started_at_ns = time.monotonic_ns()
            await self._db.execute(
                SQL.UPDATE_REQUEST_IN_PROGRESS, (started_at_ns, request_id)
            )
            await self._db.commit()

    async def mark_request_completed(self, request_id: int) -> None:
        """Mark a request as completed.

        Args:
            request_id: The database ID of the request.
        """
        async with self._lock:
            completed_at_ns = time.monotonic_ns()
            await self._db.execute(
                SQL.UPDATE_REQUEST_COMPLETED, (completed_at_ns, request_id)
            )
            await self._db.commit()

    async def mark_request_failed(
        self, request_id: int, error_message: str
    ) -> None:
        """Mark a request as failed.

        Args:
            request_id: The database ID of the request.
            error_message: Error message describing the failure.
        """
        async with self._lock:
            completed_at_ns = time.monotonic_ns()
            await self._db.execute(
                SQL.UPDATE_REQUEST_FAILED,
                (completed_at_ns, error_message, request_id),
            )
            await self._db.commit()

    async def get_retry_state(
        self, request_id: int
    ) -> tuple[int, float] | None:
        """Get retry state for a request.

        Args:
            request_id: The database ID of the request.

        Returns:
            Tuple of (retry_count, cumulative_backoff) or None if not found.
        """
        cursor = await self._db.execute(SQL.SELECT_RETRY_STATE, (request_id,))
        row = await cursor.fetchone()
        if row is None:
            return None
        return (row[0], row[1] or 0.0)

    async def schedule_retry(
        self,
        request_id: int,
        new_cumulative_backoff: float,
        next_retry_delay: float,
        error: str,
    ) -> None:
        """Schedule a request for retry with backoff.

        Args:
            request_id: The database ID of the request.
            new_cumulative_backoff: Updated cumulative backoff time.
            next_retry_delay: Delay before next retry.
            error: Error message from the current attempt.
        """
        async with self._lock:
            await self._db.execute(
                SQL.UPDATE_REQUEST_FOR_RETRY,
                (
                    new_cumulative_backoff,
                    next_retry_delay,
                    error,
                    int(next_retry_delay),
                    request_id,
                ),
            )
            await self._db.commit()

    async def count_pending_requests(self) -> int:
        """Count pending requests in the queue."""
        async with self._lock:
            cursor = await self._db.execute(SQL.COUNT_PENDING_REQUESTS)
            row = await cursor.fetchone()
            return row[0] if row else 0

    async def count_active_requests(self) -> int:
        """Count pending and in_progress requests."""
        async with self._lock:
            cursor = await self._db.execute(SQL.COUNT_ACTIVE_REQUESTS)
            row = await cursor.fetchone()
            return row[0] if row else 0

    async def count_in_progress(self) -> int:
        """Count in_progress requests (being processed by workers)."""
        async with self._lock:
            cursor = await self._db.execute(SQL.COUNT_IN_PROGRESS_REQUESTS)
            row = await cursor.fetchone()
            return row[0] if row else 0

    async def count_all_requests(self) -> int:
        """Count all requests in the database."""
        cursor = await self._db.execute(SQL.COUNT_ALL_REQUESTS)
        row = await cursor.fetchone()
        return row[0] if row else 0

    async def get_next_scheduled_retry_delay(self) -> float | None:
        """Get seconds until the next scheduled retry is ready.

        Returns:
            Seconds until the next pending request becomes available,
            or None if there are no scheduled retries.
        """
        cursor = await self._db.execute(SQL.SELECT_NEXT_SCHEDULED_RETRY_DELAY)
        row = await cursor.fetchone()
        return row[0] if row and row[0] is not None else None

    async def count_scheduled_retries(self) -> int:
        """Count pending requests that are scheduled for later."""
        cursor = await self._db.execute(SQL.COUNT_SCHEDULED_RETRIES)
        row = await cursor.fetchone()
        return row[0] if row else 0

    # --- Response Storage ---

    async def store_response(
        self,
        request_id: int,
        status_code: int,
        headers_json: str | None,
        url: str,
        compressed_content: bytes | None,
        content_size_original: int,
        content_size_compressed: int,
        dict_id: int | None,
        continuation: str,
        warc_record_id: str,
        speculation_outcome: str | None = None,
    ) -> int:
        """Store an HTTP response in the database.

        Args:
            request_id: The database ID of the associated request.
            status_code: HTTP status code.
            headers_json: JSON-encoded headers.
            url: Final URL after redirects.
            compressed_content: Compressed content bytes.
            content_size_original: Original content size.
            content_size_compressed: Compressed content size.
            dict_id: Compression dictionary ID if used.
            continuation: Continuation method name.
            warc_record_id: UUID for WARC export.
            speculation_outcome: For speculative requests: 'success', 'stopped', 'skipped'.

        Returns:
            The database ID of the stored response.
        """
        async with self._lock:
            cursor = await self._db.execute(
                SQL.INSERT_RESPONSE,
                (
                    request_id,
                    status_code,
                    headers_json,
                    url,
                    compressed_content,
                    content_size_original,
                    content_size_compressed,
                    dict_id,
                    continuation,
                    warc_record_id,
                    speculation_outcome,
                ),
            )
            await self._db.commit()
            return cursor.lastrowid or 0

    async def store_archived_file(
        self,
        request_id: int,
        file_path: str,
        original_url: str,
        expected_type: str | None,
        file_size: int,
        content_hash: str | None,
    ) -> int:
        """Store archived file metadata.

        Args:
            request_id: The database ID of the associated request.
            file_path: Local file system path.
            original_url: URL the file was downloaded from.
            expected_type: Expected file type.
            file_size: File size in bytes.
            content_hash: SHA256 hash of content.

        Returns:
            The database ID of the archived file record.
        """
        async with self._lock:
            cursor = await self._db.execute(
                SQL.INSERT_ARCHIVED_FILE,
                (
                    request_id,
                    file_path,
                    original_url,
                    expected_type,
                    file_size,
                    content_hash,
                ),
            )
            await self._db.commit()
            return cursor.lastrowid or 0

    # --- Incidental Requests (Playwright driver) ---

    async def insert_incidental_request(
        self,
        parent_request_id: int,
        resource_type: str,
        method: str,
        url: str,
        headers_json: str | None = None,
        body: bytes | None = None,
        status_code: int | None = None,
        response_headers_json: str | None = None,
        content_compressed: bytes | None = None,
        content_size_original: int | None = None,
        content_size_compressed: int | None = None,
        compression_dict_id: int | None = None,
        started_at_ns: int | None = None,
        completed_at_ns: int | None = None,
        from_cache: bool = False,
        failure_reason: str | None = None,
    ) -> int:
        """Store an incidental browser request (Playwright driver).

        Incidental requests are browser-initiated network requests that are not
        directly initiated by BaseRequest subclasses (e.g., images, scripts, XHR).

        Args:
            parent_request_id: ID of the primary request that triggered this navigation.
            resource_type: Resource type (document, stylesheet, image, script, etc.).
            method: HTTP method.
            url: Request URL.
            headers_json: JSON-encoded request headers.
            body: Request body (if any).
            status_code: HTTP status code (None if request failed).
            response_headers_json: JSON-encoded response headers.
            content_compressed: Zstd-compressed response body.
            content_size_original: Original response size.
            content_size_compressed: Compressed response size.
            compression_dict_id: Compression dictionary ID if used.
            started_at_ns: Nanosecond timestamp when request started.
            completed_at_ns: Nanosecond timestamp when request completed.
            from_cache: Whether browser served from cache.
            failure_reason: Reason if request failed (timeout, aborted, etc.).

        Returns:
            The database ID of the stored incidental request.
        """
        async with self._lock:
            cursor = await self._db.execute(
                SQL.INSERT_INCIDENTAL_REQUEST,
                (
                    parent_request_id,
                    resource_type,
                    method,
                    url,
                    headers_json,
                    body,
                    status_code,
                    response_headers_json,
                    content_compressed,
                    content_size_original,
                    content_size_compressed,
                    compression_dict_id,
                    started_at_ns,
                    completed_at_ns,
                    from_cache,
                    failure_reason,
                ),
            )
            await self._db.commit()
            return cursor.lastrowid or 0

    async def get_incidental_requests(
        self, parent_request_id: int
    ) -> list[dict[str, Any]]:
        """Get all incidental requests for a parent request.

        Args:
            parent_request_id: ID of the parent request.

        Returns:
            List of incidental request records as dicts.
        """
        cursor = await self._db.execute(
            SQL.SELECT_INCIDENTAL_REQUESTS_BY_PARENT, (parent_request_id,)
        )
        rows = await cursor.fetchall()
        return [
            {
                "id": row[0],
                "parent_request_id": row[1],
                "resource_type": row[2],
                "method": row[3],
                "url": row[4],
                "headers_json": row[5],
                "body": row[6],
                "status_code": row[7],
                "response_headers_json": row[8],
                "content_compressed": row[9],
                "content_size_original": row[10],
                "content_size_compressed": row[11],
                "compression_dict_id": row[12],
                "started_at_ns": row[13],
                "completed_at_ns": row[14],
                "from_cache": row[15],
                "failure_reason": row[16],
                "created_at": row[17],
            }
            for row in rows
        ]

    async def get_incidental_request_by_id(
        self, incidental_id: int
    ) -> dict[str, Any] | None:
        """Get a single incidental request by ID.

        Args:
            incidental_id: ID of the incidental request.

        Returns:
            Incidental request record as dict, or None if not found.
        """
        cursor = await self._db.execute(
            SQL.SELECT_INCIDENTAL_REQUEST_BY_ID, (incidental_id,)
        )
        row = await cursor.fetchone()
        if not row:
            return None
        return {
            "id": row[0],
            "parent_request_id": row[1],
            "resource_type": row[2],
            "method": row[3],
            "url": row[4],
            "headers_json": row[5],
            "body": row[6],
            "status_code": row[7],
            "response_headers_json": row[8],
            "content_compressed": row[9],
            "content_size_original": row[10],
            "content_size_compressed": row[11],
            "compression_dict_id": row[12],
            "started_at_ns": row[13],
            "completed_at_ns": row[14],
            "from_cache": row[15],
            "failure_reason": row[16],
            "created_at": row[17],
        }

    async def get_response_compressed(
        self, response_id: int
    ) -> tuple[bytes | None, int | None] | None:
        """Get compressed response content and dict ID.

        Args:
            response_id: The database ID of the response.

        Returns:
            Tuple of (compressed_content, dict_id) or None if not found.
        """
        cursor = await self._db.execute(
            SQL.SELECT_RESPONSE_COMPRESSED, (response_id,)
        )
        return await cursor.fetchone()

    async def get_cached_response(
        self, cache_key: str
    ) -> dict[str, Any] | None:
        """Look up a cached response by cache key.

        Returns the most recent successful (2xx) response for the given
        cache key, if one exists.

        Args:
            cache_key: The cache key (hash of method+url+body+headers).

        Returns:
            Dictionary with response data if found, None otherwise.
            Contains keys: id, request_id, status_code, headers_json, url,
            content_compressed, compression_dict_id, created_at, method.
        """
        cursor = await self._db.execute(
            SQL.SELECT_CACHED_RESPONSE_BY_KEY, (cache_key,)
        )
        row = await cursor.fetchone()
        if row is None:
            return None

        return {
            "id": row[0],
            "request_id": row[1],
            "status_code": row[2],
            "headers_json": row[3],
            "url": row[4],
            "content_compressed": row[5],
            "compression_dict_id": row[6],
            "created_at": row[7],
            "method": row[8],
        }

    async def get_compression_dict(self, dict_id: int) -> bytes | None:
        """Get compression dictionary data by ID.

        Args:
            dict_id: The database ID of the compression dictionary.

        Returns:
            Dictionary bytes if found, None otherwise.
        """
        cursor = await self._db.execute(
            SQL.SELECT_COMPRESSION_DICT_DATA_BY_ID,
            (dict_id,),
        )
        row = await cursor.fetchone()
        return row[0] if row else None

    # --- Result Storage ---

    async def store_result(
        self,
        request_id: int,
        result_type: str,
        data_json: str,
        is_valid: bool = True,
        validation_errors_json: str | None = None,
    ) -> int:
        """Store a scraped result.

        Args:
            request_id: The database ID of the request that produced this.
            result_type: Pydantic model class name.
            data_json: JSON-encoded result data.
            is_valid: Whether the data passed validation.
            validation_errors_json: JSON-encoded validation errors if invalid.

        Returns:
            The database ID of the stored result.
        """
        async with self._lock:
            cursor = await self._db.execute(
                SQL.INSERT_RESULT,
                (
                    request_id,
                    result_type,
                    data_json,
                    is_valid,
                    validation_errors_json,
                ),
            )
            await self._db.commit()
            return cursor.lastrowid or 0

    # --- Step Control ---

    async def pause_step(self, continuation: str) -> int:
        """Pause processing of requests for a continuation.

        Marks all pending requests as 'held'.

        Args:
            continuation: The continuation method name.

        Returns:
            Number of requests marked as held.
        """
        async with self._lock:
            cursor = await self._db.execute(
                SQL.UPDATE_PAUSE_STEP, (continuation,)
            )
            await self._db.commit()
            return cursor.rowcount

    async def resume_step(self, continuation: str) -> int:
        """Resume processing of held requests.

        Args:
            continuation: The continuation method name.

        Returns:
            Number of requests restored to pending.
        """
        async with self._lock:
            cursor = await self._db.execute(
                SQL.UPDATE_RESUME_STEP, (continuation,)
            )
            await self._db.commit()
            return cursor.rowcount

    async def get_held_count(self, continuation: str | None = None) -> int:
        """Get count of held requests.

        Args:
            continuation: Optional continuation name filter.

        Returns:
            Count of held requests.
        """
        if continuation:
            cursor = await self._db.execute(
                SQL.COUNT_HELD_BY_CONTINUATION, (continuation,)
            )
        else:
            cursor = await self._db.execute(SQL.COUNT_ALL_HELD)
        row = await cursor.fetchone()
        return row[0] if row else 0

    # --- Error Requeue ---

    async def get_error_with_request(
        self, error_id: int
    ) -> tuple[Any, ...] | None:
        """Get error and associated request data for requeue.

        Args:
            error_id: The database ID of the error.

        Returns:
            Row tuple with error and request data, or None.
        """
        cursor = await self._db.execute(
            SQL.SELECT_ERROR_WITH_REQUEST, (error_id,)
        )
        return await cursor.fetchone()

    async def insert_requeue_request(
        self,
        priority: int,
        method: str,
        url: str,
        headers_json: str | None,
        cookies_json: str | None,
        body: bytes | None,
        continuation: str,
        current_location: str,
        accumulated_data_json: str | None,
        aux_data_json: str | None,
        permanent_json: str | None,
        original_request_id: int,
        request_type: str = "navigating",
        expected_type: str | None = None,
    ) -> int:
        """Insert a requeued request.

        Args:
            priority: Request priority.
            method: HTTP method.
            url: Request URL.
            headers_json: JSON-encoded headers.
            cookies_json: JSON-encoded cookies.
            body: Request body bytes.
            continuation: Continuation method name.
            current_location: Current location.
            accumulated_data_json: JSON-encoded accumulated data.
            aux_data_json: JSON-encoded aux data.
            permanent_json: JSON-encoded permanent data.
            original_request_id: ID of the original failed request.
            request_type: Request type (default: "navigating").
            expected_type: Expected response type (optional).

        Returns:
            The ID of the newly inserted request.
        """
        async with self._lock:
            return await self._insert_requeue_request_unlocked(
                priority=priority,
                method=method,
                url=url,
                headers_json=headers_json,
                cookies_json=cookies_json,
                body=body,
                continuation=continuation,
                current_location=current_location,
                accumulated_data_json=accumulated_data_json,
                aux_data_json=aux_data_json,
                permanent_json=permanent_json,
                original_request_id=original_request_id,
                request_type=request_type,
                expected_type=expected_type,
            )

    async def _insert_requeue_request_unlocked(
        self,
        priority: int,
        method: str,
        url: str,
        headers_json: str | None,
        cookies_json: str | None,
        body: bytes | None,
        continuation: str,
        current_location: str,
        accumulated_data_json: str | None,
        aux_data_json: str | None,
        permanent_json: str | None,
        original_request_id: int,
        request_type: str = "navigating",
        expected_type: str | None = None,
    ) -> int:
        """Internal unlocked version of insert_requeue_request.

        Must be called while holding self._lock.
        """
        queue_counter = await get_next_queue_counter(self._db)
        created_at_ns = time.monotonic_ns()

        cursor = await self._db.execute(
            SQL.INSERT_REQUEUE_REQUEST,
            (
                priority,
                queue_counter,
                request_type,
                expected_type,
                method,
                url,
                headers_json,
                cookies_json,
                body,
                continuation,
                current_location,
                accumulated_data_json,
                aux_data_json,
                permanent_json,
                original_request_id,
                created_at_ns,
            ),
        )
        await self._db.commit()
        return cursor.lastrowid or 0

    async def insert_resume_request(
        self,
        priority: int,
        continuation: str,
        resume_id: str,
        predicate_result: bool,
    ) -> int:
        """Insert a resume request to resume a parked generator.

        Resume requests are special control flow markers that trigger
        resumption of a parked generator with a predicate result.

        Args:
            priority: Request priority.
            continuation: Continuation method name for reference.
            resume_id: ID linking to the parked generator.
            predicate_result: Value to send to the generator (True/False).

        Returns:
            The ID of the newly inserted request.
        """
        import json

        async with self._lock:
            queue_counter = await get_next_queue_counter(self._db)
            created_at_ns = time.monotonic_ns()

            cursor = await self._db.execute(
                SQL.INSERT_REQUEST,
                (
                    priority,
                    queue_counter,
                    "resume",  # Special request type
                    "GET",  # Dummy method
                    "",  # Empty URL
                    None,  # No headers
                    None,  # No cookies
                    None,  # No body
                    continuation,  # Store continuation for reference
                    "",  # No current_location
                    None,  # No accumulated_data
                    None,  # No aux_data
                    json.dumps(
                        {"predicate_result": predicate_result}
                    ),  # Store result in permanent_json
                    resume_id,  # Store resume_id in expected_type
                    None,  # No dedup_key
                    None,  # No parent_id
                    created_at_ns,  # Nanosecond timestamp
                    None,  # No cache_key for resume requests
                ),
            )
            await self._db.commit()
            return cursor.lastrowid or 0

    async def get_errors_for_requeue(
        self,
        error_type: str | None = None,
        continuation: str | None = None,
    ) -> list[tuple[Any, ...]]:
        """Get unresolved errors for batch requeue.

        Args:
            error_type: Optional error type filter.
            continuation: Optional continuation filter.

        Returns:
            List of row tuples with error and request data.
        """
        conditions = ["e.is_resolved = 0", "e.request_id IS NOT NULL"]
        params: list[Any] = []

        if error_type:
            conditions.append("e.error_type = ?")
            params.append(error_type)
        if continuation:
            conditions.append("r.continuation = ?")
            params.append(continuation)

        where_clause = " AND ".join(conditions)
        cursor = await self._db.execute(
            SQL.SELECT_ERRORS_FOR_REQUEUE.format(where_clause=where_clause),
            params,
        )
        return await cursor.fetchall()

    async def get_error_info_for_progress(self, error_id: int) -> dict | None:
        """Get error info for progress events.

        Args:
            error_id: The database ID of the error.

        Returns:
            Dict with url and continuation, or None if not found.
        """
        row = await self.get_error_with_request(error_id)
        if row is None:
            return None

        # Row indices based on SELECT_ERROR_WITH_REQUEST
        url = row[4]  # url
        continuation = row[8]  # continuation
        return {"url": url, "continuation": continuation}

    async def batch_requeue_errors(
        self,
        error_type: str | None = None,
        continuation: str | None = None,
    ) -> list[int]:
        """Batch requeue errors matching the given filters.

        Args:
            error_type: Optional error type filter.
            continuation: Optional continuation filter.

        Returns:
            List of new request IDs created.
        """
        rows = await self.get_errors_for_requeue(error_type, continuation)
        if not rows:
            return []

        new_request_ids = []
        error_ids = []

        for row in rows:
            # Unpack row: id, request_id, method, url, headers_json,
            #            cookies_json, body, continuation, current_location,
            #            accumulated_data_json, aux_data_json, permanent_json, priority,
            #            request_type, expected_type
            (
                error_id,
                request_id,
                method,
                url,
                headers_json,
                cookies_json,
                body,
                row_continuation,
                current_location,
                accumulated_data_json,
                aux_data_json,
                permanent_json,
                priority,
                request_type,
                expected_type,
            ) = row

            new_request_id = await self.insert_requeue_request(
                priority=priority or 0,
                method=method,
                url=url,
                headers_json=headers_json,
                cookies_json=cookies_json,
                body=body,
                continuation=row_continuation,
                current_location=current_location,
                accumulated_data_json=accumulated_data_json,
                aux_data_json=aux_data_json,
                permanent_json=permanent_json,
                original_request_id=request_id,
                request_type=request_type or "navigating",
                expected_type=expected_type,
            )
            new_request_ids.append(new_request_id)
            error_ids.append(error_id)

        # Mark all errors as resolved
        if error_ids:
            async with self._lock:
                placeholders = ",".join("?" * len(error_ids))
                await self._db.execute(
                    SQL.BATCH_MARK_ERRORS_RESOLVED.format(
                        placeholders=placeholders
                    ),
                    error_ids,
                )
                await self._db.commit()

        return new_request_ids

    # --- Speculative Start IDs (for restart-speculative feature) ---

    async def set_speculative_start_id(
        self, step_name: str, starting_id: int
    ) -> None:
        """Set a speculative starting ID for a step.

        This is used by the restart-speculative feature to persist starting IDs
        that will be picked up when the driver next starts.

        Args:
            step_name: The name of the speculative step method.
            starting_id: The speculative_id to start from.
        """
        async with self._lock:
            await self._db.execute(
                SQL.UPSERT_SPECULATIVE_START_ID, (step_name, starting_id)
            )
            await self._db.commit()

    async def get_speculative_start_ids(self) -> dict[str, int]:
        """Get all speculative starting IDs.

        Returns:
            Dict mapping step names to their starting_id.
        """
        cursor = await self._db.execute(SQL.SELECT_SPECULATIVE_START_IDS)
        rows = await cursor.fetchall()
        return {row[0]: row[1] for row in rows}

    async def clear_speculative_start_id(self, step_name: str) -> None:
        """Clear a speculative starting ID for a step.

        Called after the driver has applied the starting ID to the params.

        Args:
            step_name: The name of the speculative step method.
        """
        async with self._lock:
            await self._db.execute(
                SQL.DELETE_SPECULATIVE_START_ID, (step_name,)
            )
            await self._db.commit()

    async def clear_all_speculative_start_ids(self) -> None:
        """Clear all speculative starting IDs.

        Called after the driver has applied all starting IDs.
        """
        async with self._lock:
            await self._db.execute(SQL.DELETE_ALL_SPECULATIVE_START_IDS)
            await self._db.commit()

    # --- Speculation Tracking (new @speculate pattern) ---

    async def save_speculation_state(
        self,
        func_name: str,
        highest_successful_id: int,
        consecutive_failures: int,
        current_ceiling: int,
        stopped: bool,
    ) -> None:
        """Save or update speculation tracking state for a @speculate function.

        This is used to persist speculation state for run resumption.

        Args:
            func_name: Name of the @speculate decorated function.
            highest_successful_id: Highest ID that returned 2xx.
            consecutive_failures: Count of failures beyond highest_successful_id.
            current_ceiling: Current upper bound of seeded IDs.
            stopped: Whether speculation has stopped for this function.
        """
        async with self._lock:
            await self._db.execute(
                SQL.UPSERT_SPECULATION_TRACKING,
                (
                    func_name,
                    highest_successful_id,
                    consecutive_failures,
                    current_ceiling,
                    stopped,
                ),
            )
            await self._db.commit()

    async def load_speculation_state(
        self, func_name: str
    ) -> dict[str, int | bool] | None:
        """Load speculation tracking state for a @speculate function.

        Args:
            func_name: Name of the @speculate decorated function.

        Returns:
            Dict with keys: highest_successful_id, consecutive_failures,
            current_ceiling, stopped. Returns None if no state exists.
        """
        cursor = await self._db.execute(
            SQL.SELECT_SPECULATION_TRACKING, (func_name,)
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        return {
            "func_name": row[0],
            "highest_successful_id": row[1],
            "consecutive_failures": row[2],
            "current_ceiling": row[3],
            "stopped": bool(row[4]),
        }

    async def load_all_speculation_states(
        self,
    ) -> dict[str, dict[str, int | bool]]:
        """Load all speculation tracking states.

        Returns:
            Dict mapping func_name to their state dict with keys:
            highest_successful_id, consecutive_failures, current_ceiling, stopped.
        """
        cursor = await self._db.execute(SQL.SELECT_ALL_SPECULATION_TRACKING)
        rows = await cursor.fetchall()
        return {
            row[0]: {
                "highest_successful_id": row[1],
                "consecutive_failures": row[2],
                "current_ceiling": row[3],
                "stopped": bool(row[4]),
            }
            for row in rows
        }

    async def get_all_speculation_progress(self) -> dict[str, int]:
        """Get highest_successful_id for all speculation tracking entries.

        This is a convenience method that returns just the highest_successful_id
        for each @speculate function, suitable for UI progress display.

        Returns:
            Dict mapping func_name to their highest_successful_id.
        """
        states = await self.load_all_speculation_states()
        return {
            func_name: state["highest_successful_id"]
            for func_name, state in states.items()
        }

    async def clear_speculation_state(self, func_name: str) -> None:
        """Clear speculation tracking state for a @speculate function.

        Args:
            func_name: Name of the @speculate decorated function.
        """
        async with self._lock:
            await self._db.execute(
                SQL.DELETE_SPECULATION_TRACKING, (func_name,)
            )
            await self._db.commit()

    async def clear_all_speculation_states(self) -> None:
        """Clear all speculation tracking states."""
        async with self._lock:
            await self._db.execute(SQL.DELETE_ALL_SPECULATION_TRACKING)
            await self._db.commit()

    # --- Request Cancellation ---

    async def cancel_request(self, request_id: int) -> bool:
        """Cancel a pending request.

        Only pending or held requests can be cancelled.

        Args:
            request_id: The database ID of the request.

        Returns:
            True if cancelled, False if not found or not cancellable.
        """
        async with self._lock:
            completed_at_ns = time.monotonic_ns()
            cursor = await self._db.execute(
                SQL.UPDATE_CANCEL_REQUEST, (completed_at_ns, request_id)
            )
            await self._db.commit()
            return cursor.rowcount > 0

    async def cancel_requests_by_continuation(self, continuation: str) -> int:
        """Cancel all pending/held requests for a continuation.

        Args:
            continuation: The continuation method name.

        Returns:
            Number of requests cancelled.
        """
        async with self._lock:
            completed_at_ns = time.monotonic_ns()
            cursor = await self._db.execute(
                SQL.UPDATE_CANCEL_BY_CONTINUATION,
                (completed_at_ns, continuation),
            )
            await self._db.commit()
            return cursor.rowcount

    async def requeue_requests_by_continuation(
        self, continuation: str, status: str
    ) -> int:
        """Requeue all requests matching continuation and status.

        Creates new pending requests with the same parameters as the
        original requests.

        Args:
            continuation: The continuation method name to filter by.
            status: The status to filter by (e.g., 'failed', 'completed').

        Returns:
            Number of requests requeued.
        """
        # Get all matching requests
        cursor = await self._db.execute(
            SQL.SELECT_REQUESTS_FOR_BATCH_REQUEUE, (continuation, status)
        )
        rows = await cursor.fetchall()

        if not rows:
            return 0

        requeued_count = 0
        for row in rows:
            # row: id, method, url, continuation, priority,
            #      headers_json, cookies_json, body,
            #      current_location, accumulated_data_json, aux_data_json,
            #      permanent_json, request_type, expected_type
            await self.insert_requeue_request(
                priority=row[4],
                method=row[1],
                url=row[2],
                headers_json=row[5],
                cookies_json=row[6],
                body=row[7],
                continuation=row[3],
                current_location=row[8],
                accumulated_data_json=row[9],
                aux_data_json=row[10],
                permanent_json=row[11],
                original_request_id=row[0],
                request_type=row[12] or "navigating",
                expected_type=row[13],
            )
            requeued_count += 1

        return requeued_count

    # --- Status ---

    async def get_run_status(
        self,
    ) -> Literal["unstarted", "in_progress", "done"]:
        """Check the current state of the scraper run.

        Returns:
            "unstarted": No requests in DB
            "in_progress": Pending or in_progress requests exist
            "done": No pending/in_progress but completed requests exist
        """
        active_count = await self.count_active_requests()
        if active_count > 0:
            return "in_progress"

        total_count = await self.count_all_requests()
        if total_count == 0:
            return "unstarted"

        return "done"

    # --- Listing Operations ---

    async def list_requests(
        self,
        status: str | None = None,
        continuation: str | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> Page[RequestRecord]:
        """List requests with optional filters and pagination.

        Args:
            status: Filter by status.
            continuation: Filter by continuation method name.
            offset: Number of records to skip.
            limit: Maximum number of records to return.

        Returns:
            Page of RequestRecord instances.
        """
        conditions = []
        params: list[Any] = []

        if status:
            conditions.append("status = ?")
            params.append(status)
        if continuation:
            conditions.append("continuation = ?")
            params.append(continuation)

        where_clause = (
            f"WHERE {' AND '.join(conditions)}" if conditions else ""
        )

        # Get total count
        cursor = await self._db.execute(
            SQL.count_table(
                "requests", " AND ".join(conditions) if conditions else ""
            ),
            params,
        )
        row = await cursor.fetchone()
        total = row[0] if row else 0

        # Get page of records
        cursor = await self._db.execute(
            SQL.SELECT_REQUESTS_PAGE.format(where_clause=where_clause),
            params + [limit, offset],
        )
        rows = await cursor.fetchall()

        items = [
            RequestRecord(
                id=row[0],
                status=row[1],
                priority=row[2],
                queue_counter=row[3],
                method=row[4],
                url=row[5],
                continuation=row[6],
                current_location=row[7],
                created_at=row[8],
                started_at=row[9],
                completed_at=row[10],
                retry_count=row[11],
                cumulative_backoff=row[12],
                last_error=row[13],
                created_at_ns=row[14] if len(row) > 14 else None,
                started_at_ns=row[15] if len(row) > 15 else None,
                completed_at_ns=row[16] if len(row) > 16 else None,
            )
            for row in rows
        ]

        return Page(items=items, total=total, offset=offset, limit=limit)

    async def list_responses(
        self,
        continuation: str | None = None,
        request_id: int | None = None,
        speculation_outcome: str | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> Page[ResponseRecord]:
        """List responses with optional filters and pagination.

        Args:
            continuation: Filter by continuation method name.
            request_id: Filter by request ID.
            speculation_outcome: Filter by speculation outcome.
            offset: Number of records to skip.
            limit: Maximum number of records to return.

        Returns:
            Page of ResponseRecord instances.
        """
        conditions = []
        params: list[Any] = []

        if continuation:
            conditions.append("continuation = ?")
            params.append(continuation)
        if request_id:
            conditions.append("request_id = ?")
            params.append(request_id)
        if speculation_outcome:
            conditions.append("speculation_outcome = ?")
            params.append(speculation_outcome)

        where_clause = (
            f"WHERE {' AND '.join(conditions)}" if conditions else ""
        )

        # Get total count
        cursor = await self._db.execute(
            SQL.count_table(
                "responses", " AND ".join(conditions) if conditions else ""
            ),
            params,
        )
        row = await cursor.fetchone()
        total = row[0] if row else 0

        # Get page of records
        cursor = await self._db.execute(
            SQL.SELECT_RESPONSES_PAGE.format(where_clause=where_clause),
            params + [limit, offset],
        )
        rows = await cursor.fetchall()

        items = [
            ResponseRecord(
                id=row[0],
                request_id=row[1],
                status_code=row[2],
                url=row[3],
                content_size_original=row[4],
                content_size_compressed=row[5],
                continuation=row[6],
                created_at=row[7],
                compression_dict_id=row[8],
                speculation_outcome=row[9] if len(row) > 9 else None,
            )
            for row in rows
        ]

        return Page(items=items, total=total, offset=offset, limit=limit)

    async def list_results(
        self,
        result_type: str | None = None,
        is_valid: bool | None = None,
        request_id: int | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> Page[ResultRecord]:
        """List results with optional filters and pagination.

        Args:
            result_type: Filter by result type.
            is_valid: Filter by validation status.
            request_id: Filter by request ID.
            offset: Number of records to skip.
            limit: Maximum number of records to return.

        Returns:
            Page of ResultRecord instances.
        """
        conditions = []
        params: list[Any] = []

        if result_type:
            conditions.append("result_type = ?")
            params.append(result_type)
        if is_valid is not None:
            conditions.append("is_valid = ?")
            params.append(is_valid)
        if request_id:
            conditions.append("request_id = ?")
            params.append(request_id)

        where_clause = (
            f"WHERE {' AND '.join(conditions)}" if conditions else ""
        )

        # Get total count
        cursor = await self._db.execute(
            SQL.count_table(
                "results", " AND ".join(conditions) if conditions else ""
            ),
            params,
        )
        row = await cursor.fetchone()
        total = row[0] if row else 0

        # Get page of records
        cursor = await self._db.execute(
            SQL.SELECT_RESULTS_PAGE.format(where_clause=where_clause),
            params + [limit, offset],
        )
        rows = await cursor.fetchall()

        items = [
            ResultRecord(
                id=row[0],
                request_id=row[1],
                result_type=row[2],
                data_json=row[3],
                is_valid=bool(row[4]),  # Convert SQLite 1/0 to bool
                validation_errors_json=row[5],
                created_at=row[6],
            )
            for row in rows
        ]

        return Page(items=items, total=total, offset=offset, limit=limit)

    async def get_request(self, request_id: int) -> RequestRecord | None:
        """Get a single request by ID.

        Args:
            request_id: The database ID of the request.

        Returns:
            RequestRecord or None if not found.
        """
        cursor = await self._db.execute(
            SQL.SELECT_REQUEST_BY_ID, (request_id,)
        )
        row = await cursor.fetchone()

        if row is None:
            return None

        return RequestRecord(
            id=row[0],
            status=row[1],
            priority=row[2],
            queue_counter=row[3],
            method=row[4],
            url=row[5],
            continuation=row[6],
            current_location=row[7],
            created_at=row[8],
            started_at=row[9],
            completed_at=row[10],
            retry_count=row[11],
            cumulative_backoff=row[12],
            last_error=row[13],
            created_at_ns=row[14] if len(row) > 14 else None,
            started_at_ns=row[15] if len(row) > 15 else None,
            completed_at_ns=row[16] if len(row) > 16 else None,
        )

    async def get_response(self, response_id: int) -> ResponseRecord | None:
        """Get a single response by ID.

        Args:
            response_id: The database ID of the response.

        Returns:
            ResponseRecord or None if not found.
        """
        cursor = await self._db.execute(
            SQL.SELECT_RESPONSE_BY_ID, (response_id,)
        )
        row = await cursor.fetchone()

        if row is None:
            return None

        return ResponseRecord(
            id=row[0],
            request_id=row[1],
            status_code=row[2],
            url=row[3],
            content_size_original=row[4],
            content_size_compressed=row[5],
            continuation=row[6],
            created_at=row[7],
            compression_dict_id=row[8],
            speculation_outcome=row[9] if len(row) > 9 else None,
        )

    async def get_result(self, result_id: int) -> ResultRecord | None:
        """Get a single result by ID.

        Args:
            result_id: The database ID of the result.

        Returns:
            ResultRecord or None if not found.
        """
        cursor = await self._db.execute(SQL.SELECT_RESULT_BY_ID, (result_id,))
        row = await cursor.fetchone()

        if row is None:
            return None

        return ResultRecord(
            id=row[0],
            request_id=row[1],
            result_type=row[2],
            data_json=row[3],
            is_valid=bool(row[4]),  # Convert SQLite 1/0 to bool
            validation_errors_json=row[5],
            created_at=row[6],
        )

    # --- Resume Request Operations ---

    async def get_permanent_json(self, request_id: int) -> str | None:
        """Get permanent_json field for a request.

        Used for resume step to get predicate_result.

        Args:
            request_id: The database ID of the request.

        Returns:
            The permanent_json string or None.
        """
        cursor = await self._db.execute(
            SQL.SELECT_PERMANENT_JSON_BY_REQUEST_ID, (request_id,)
        )
        row = await cursor.fetchone()
        return row[0] if row else None

    async def get_predicate_result(self, request_id: int) -> bool:
        """Get predicate_result from a resume request's permanent_json.

        Args:
            request_id: The database ID of the resume request.

        Returns:
            The predicate_result boolean value.
        """
        import json

        permanent_json = await self.get_permanent_json(request_id)
        if permanent_json:
            data = json.loads(permanent_json)
            return data.get("predicate_result", False)
        return False

    # --- Statistics ---

    async def get_stats(self) -> Any:
        """Get comprehensive statistics about the driver state.

        Returns:
            DevDriverStats instance.
        """
        from juriscraper.scraper_driver.driver.dev_driver.stats import (
            get_stats,
        )

        return await get_stats(self._db)

    # --- Response Content Access ---

    async def get_response_content(self, response_id: int) -> bytes | None:
        """Get decompressed response content by response ID.

        Args:
            response_id: The database ID of the response.

        Returns:
            Decompressed content bytes, or None if response not found.
        """
        from juriscraper.scraper_driver.driver.dev_driver.compression import (
            decompress_response,
        )

        result = await self.get_response_compressed(response_id)
        if result is None:
            return None

        compressed, dict_id = result
        if not compressed:
            return b""

        return await decompress_response(self._db, compressed, dict_id)

    async def get_response_content_with_headers(
        self, response_id: int
    ) -> tuple[bytes, str | None] | None:
        """Get decompressed response content and headers.

        Args:
            response_id: The database ID of the response.

        Returns:
            Tuple of (decompressed_content, headers_json) or None if not found.
        """
        from juriscraper.scraper_driver.driver.dev_driver.compression import (
            decompress_response,
        )

        cursor = await self._db.execute(
            SQL.SELECT_RESPONSE_CONTENT_FOR_WEB, (response_id,)
        )
        row = await cursor.fetchone()

        if row is None:
            return None

        compressed_content, dict_id, headers_json = row

        if compressed_content is None:
            return (b"", headers_json)

        content = await decompress_response(
            self._db, compressed_content, dict_id
        )
        return (content, headers_json)

    # =========================================================================
    # Rate Limiter State Methods
    # =========================================================================

    async def get_rate_limiter_state(self) -> dict[str, Any] | None:
        """Get the current rate limiter state.

        Returns:
            Dictionary with rate limiter state, or None if not initialized.
        """
        cursor = await self._db.execute(SQL.SELECT_RATE_LIMITER_STATE)
        row = await cursor.fetchone()

        if row is None:
            return None

        return {
            "tokens": row[0],
            "rate": row[1],
            "bucket_size": row[2],
            "last_congestion_rate": row[3],
            "jitter": row[4],
            "last_used_at": row[5],
            "total_requests": row[6],
            "total_successes": row[7],
            "total_rate_limited": row[8],
            "created_at": row[9],
            "updated_at": row[10],
        }

    async def upsert_rate_limiter_state(
        self,
        tokens: float,
        rate: float,
        bucket_size: float,
        last_congestion_rate: float,
        jitter: float,
        last_used_at: float,
        total_requests: int = 0,
        total_successes: int = 0,
        total_rate_limited: int = 0,
    ) -> None:
        """Create or update the rate limiter state.

        Args:
            tokens: Current token count.
            rate: Current rate (tokens per second).
            bucket_size: Maximum tokens.
            last_congestion_rate: Rate at last congestion event.
            jitter: Uniform jitter ±seconds.
            last_used_at: Unix timestamp of last token acquisition.
            total_requests: Total requests made.
            total_successes: Total successful requests.
            total_rate_limited: Total rate-limited requests.
        """
        async with self._lock:
            await self._db.execute(
                SQL.UPSERT_RATE_LIMITER_STATE,
                (
                    tokens,
                    rate,
                    bucket_size,
                    last_congestion_rate,
                    jitter,
                    last_used_at,
                    total_requests,
                    total_successes,
                    total_rate_limited,
                ),
            )
            await self._db.commit()

    async def update_rate_limiter_tokens(
        self, tokens: float, last_used_at: float
    ) -> None:
        """Update just the tokens and last_used_at.

        Used when acquiring tokens without changing the rate.

        Args:
            tokens: New token count.
            last_used_at: Unix timestamp of token acquisition.
        """
        async with self._lock:
            await self._db.execute(
                SQL.UPDATE_RATE_LIMITER_TOKENS, (tokens, last_used_at)
            )
            await self._db.commit()

    async def update_rate_limiter_rate_increase(self, new_rate: float) -> None:
        """Update rate after a successful request (rate increase).

        Increments total_requests and total_successes.

        Args:
            new_rate: The new rate after increase.
        """
        async with self._lock:
            await self._db.execute(
                SQL.UPDATE_RATE_LIMITER_RATE_INCREASE, (new_rate,)
            )
            await self._db.commit()

    async def update_rate_limiter_rate_decrease(
        self, new_rate: float, congestion_rate: float
    ) -> None:
        """Update rate after a rate-limited response (rate decrease).

        Sets tokens to 0, records congestion rate, increments total_requests
        and total_rate_limited.

        Args:
            new_rate: The new rate after decrease.
            congestion_rate: The rate at which congestion occurred.
        """
        async with self._lock:
            await self._db.execute(
                SQL.UPDATE_RATE_LIMITER_RATE_DECREASE,
                (new_rate, congestion_rate),
            )
            await self._db.commit()

    async def increment_rate_limiter_success(self) -> None:
        """Increment success counter without changing rate.

        Used when response succeeds but rate doesn't change.
        """
        async with self._lock:
            await self._db.execute(SQL.UPDATE_RATE_LIMITER_SUCCESS)
            await self._db.commit()

    async def increment_rate_limiter_rate_limited(self) -> None:
        """Increment rate-limited counter without changing rate.

        Used when response is rate-limited but rate doesn't change.
        """
        async with self._lock:
            await self._db.execute(SQL.UPDATE_RATE_LIMITER_RATE_LIMITED)
            await self._db.commit()

    # --- JSON Response Validation ---

    async def validate_json_responses(
        self,
        continuation: str,
        model: type[BaseModel],
    ) -> list[int]:
        """Validate stored JSON responses against a Pydantic model.

        This diagnostic function retrieves all stored responses for a continuation,
        decompresses them, parses as JSON, and validates against the provided model.

        Args:
            continuation: The continuation method name to filter responses.
            model: Pydantic BaseModel class to validate against.

        Returns:
            List of request_id values for responses that failed validation.
            Empty list if all responses are valid or if no responses exist.

        Example::

            from myapi.models import PublicationsResponse
            async with SQLManager.open(db_path) as manager:
                invalid_ids = await manager.validate_json_responses(
                    "parse_publications",
                    PublicationsResponse
                )
                if invalid_ids:
                    print(f"Invalid responses: {invalid_ids}")
        """
        from juriscraper.scraper_driver.driver.dev_driver.compression import (
            decompress_response,
        )

        # Get all responses for this continuation
        cursor = await self._db.execute(
            SQL.SELECT_RESPONSES_FOR_JSON_VALIDATION,
            (continuation,),
        )
        rows = await cursor.fetchall()

        if not rows:
            return []

        invalid_request_ids = []

        for row in rows:
            response_id, request_id, compressed_content, dict_id = row

            # Skip empty responses
            if compressed_content is None:
                continue

            try:
                # Decompress the response
                content = await decompress_response(
                    self._db, compressed_content, dict_id
                )

                # Parse as JSON
                content_str = content.decode("utf-8")
                data = json.loads(content_str)

                # Validate against the model
                model.model_validate(data)

            except Exception:
                # Any error (decompression, JSON parse, validation) means invalid
                invalid_request_ids.append(request_id)

        return invalid_request_ids

    # --- Enhanced Requeue Operations ---

    async def requeue_requests(
        self,
        request_ids: list[int],
        *,
        clear_responses: bool = False,
        clear_downstream: bool = False,
        dry_run: bool = False,
    ) -> RequeueResult:
        """Requeue a list of requests with configurable cleanup behavior.

        Creates new pending requests with the same parameters as the originals.
        Optionally clears responses (forcing re-fetch) and/or downstream artifacts
        (child requests, results, errors).

        Args:
            request_ids: List of request IDs to requeue.
            clear_responses: If True, delete responses for the requeued requests
                (and downstream if clear_downstream=True).
            clear_downstream: If True, recursively delete child requests and all
                their artifacts (results, errors, responses if clear_responses=True).
            dry_run: If True, report what would happen without making changes.

        Returns:
            RequeueResult with lists of affected IDs and dry_run flag.

        Example::

            # Basic requeue (keep all data)
            result = await manager.requeue_requests([1, 2, 3])

            # Requeue and force re-fetch
            result = await manager.requeue_requests([1], clear_responses=True)

            # Requeue and clear entire downstream tree
            result = await manager.requeue_requests(
                [1], clear_responses=True, clear_downstream=True
            )

            # Preview what would be affected
            result = await manager.requeue_requests(
                [1], clear_downstream=True, dry_run=True
            )
        """
        result = RequeueResult(dry_run=dry_run)

        if not request_ids:
            return result

        # Get original request data for all request_ids
        placeholders = ",".join("?" * len(request_ids))
        cursor = await self._db.execute(
            SQL.SELECT_REQUESTS_FOR_REQUEUE_BY_IDS.format(
                placeholders=placeholders
            ),
            request_ids,
        )
        rows = await cursor.fetchall()

        if not rows:
            return result

        # Build set of all request IDs to affect (including downstream if requested)
        all_affected_request_ids = set(request_ids)

        if clear_downstream:
            # For each original request, find all downstream requests recursively
            for request_id in request_ids:
                downstream_cursor = await self._db.execute(
                    SQL.SELECT_DOWNSTREAM_REQUEST_IDS, (request_id,)
                )
                downstream_rows = await downstream_cursor.fetchall()
                downstream_ids = [row[0] for row in downstream_rows]
                all_affected_request_ids.update(downstream_ids)

        # Track what we'll clear
        affected_list = list(all_affected_request_ids)

        if clear_responses and affected_list:
            # Find response IDs to delete
            placeholders = ",".join("?" * len(affected_list))
            cursor = await self._db.execute(
                SQL.SELECT_RESPONSE_IDS_BY_REQUEST_IDS.format(
                    placeholders=placeholders
                ),
                affected_list,
            )
            response_rows = await cursor.fetchall()
            result.cleared_response_ids = [row[0] for row in response_rows]

        if clear_downstream:
            # Find downstream request IDs (excluding original request_ids)
            downstream_request_ids = [
                rid
                for rid in all_affected_request_ids
                if rid not in request_ids
            ]
            result.cleared_downstream_request_ids = downstream_request_ids

            # Find result IDs to delete (from all affected requests)
            if affected_list:
                placeholders = ",".join("?" * len(affected_list))
                cursor = await self._db.execute(
                    SQL.SELECT_RESULT_IDS_BY_REQUEST_IDS.format(
                        placeholders=placeholders
                    ),
                    affected_list,
                )
                result_rows = await cursor.fetchall()
                result.cleared_result_ids = [row[0] for row in result_rows]

                # Find error IDs to delete (from all affected requests)
                cursor = await self._db.execute(
                    SQL.SELECT_ERROR_IDS_BY_REQUEST_IDS.format(
                        placeholders=placeholders
                    ),
                    affected_list,
                )
                error_rows = await cursor.fetchall()
                result.cleared_error_ids = [row[0] for row in error_rows]

        if dry_run:
            # Don't make any changes, just return what would be affected
            # Still need to calculate requeued_request_ids
            result.requeued_request_ids = list(
                range(1, len(rows) + 1)
            )  # Placeholder IDs
            return result

        # Execute the requeue and cleanup operations
        async with self._lock:
            # Create new pending requests
            new_request_ids = []
            for row in rows:
                (
                    original_id,
                    method,
                    url,
                    continuation,
                    priority,
                    headers_json,
                    cookies_json,
                    body,
                    current_location,
                    accumulated_data_json,
                    aux_data_json,
                    permanent_json,
                    request_type,
                    expected_type,
                ) = row

                new_request_id = await self._insert_requeue_request_unlocked(
                    priority=priority or 0,
                    method=method,
                    url=url,
                    headers_json=headers_json,
                    cookies_json=cookies_json,
                    body=body,
                    continuation=continuation,
                    current_location=current_location,
                    accumulated_data_json=accumulated_data_json,
                    aux_data_json=aux_data_json,
                    permanent_json=permanent_json,
                    original_request_id=original_id,
                    request_type=request_type or "navigating",
                    expected_type=expected_type,
                )
                new_request_ids.append(new_request_id)

            result.requeued_request_ids = new_request_ids

            # Clear responses if requested
            if clear_responses and result.cleared_response_ids:
                placeholders = ",".join("?" * len(result.cleared_response_ids))
                await self._db.execute(
                    SQL.DELETE_RESPONSES_BY_IDS.format(
                        placeholders=placeholders
                    ),
                    result.cleared_response_ids,
                )

                # Also delete incidental requests associated with these parent requests
                if affected_list:
                    placeholders = ",".join("?" * len(affected_list))
                    await self._db.execute(
                        SQL.DELETE_INCIDENTAL_REQUESTS_BY_PARENT_IDS.format(
                            placeholders=placeholders
                        ),
                        affected_list,
                    )

            # Clear downstream artifacts if requested
            if clear_downstream:
                # Delete results
                if result.cleared_result_ids:
                    placeholders = ",".join(
                        "?" * len(result.cleared_result_ids)
                    )
                    await self._db.execute(
                        SQL.DELETE_RESULTS_BY_IDS.format(
                            placeholders=placeholders
                        ),
                        result.cleared_result_ids,
                    )

                # Delete errors
                if result.cleared_error_ids:
                    placeholders = ",".join(
                        "?" * len(result.cleared_error_ids)
                    )
                    await self._db.execute(
                        SQL.DELETE_ERRORS_BY_IDS.format(
                            placeholders=placeholders
                        ),
                        result.cleared_error_ids,
                    )

                # Delete downstream requests
                if result.cleared_downstream_request_ids:
                    placeholders = ",".join(
                        "?" * len(result.cleared_downstream_request_ids)
                    )
                    await self._db.execute(
                        SQL.DELETE_REQUESTS_BY_IDS.format(
                            placeholders=placeholders
                        ),
                        result.cleared_downstream_request_ids,
                    )

            await self._db.commit()

        return result

    async def requeue_response(
        self,
        response_id: int,
        *,
        clear_responses: bool = False,
        clear_downstream: bool = False,
        dry_run: bool = False,
    ) -> RequeueResult:
        """Requeue the request associated with a response.

        Convenience helper that looks up the request_id from a response_id
        and delegates to requeue_requests().

        Args:
            response_id: The database ID of the response.
            clear_responses: If True, delete responses for the requeued request.
            clear_downstream: If True, recursively delete downstream artifacts.
            dry_run: If True, report what would happen without making changes.

        Returns:
            RequeueResult with lists of affected IDs and dry_run flag.
            Returns empty result if response not found.

        Example::

            # Requeue from a response
            result = await manager.requeue_response(42)

            # Requeue and clear to force re-fetch
            result = await manager.requeue_response(
                42, clear_responses=True
            )
        """
        # Look up request_id from response_id
        cursor = await self._db.execute(
            SQL.SELECT_REQUEST_ID_BY_RESPONSE, (response_id,)
        )
        row = await cursor.fetchone()

        if row is None:
            return RequeueResult(dry_run=dry_run)

        request_id = row[0]
        return await self.requeue_requests(
            [request_id],
            clear_responses=clear_responses,
            clear_downstream=clear_downstream,
            dry_run=dry_run,
        )

    async def requeue_error(
        self,
        error_id: int,
        *,
        mark_resolved: bool = True,
        clear_responses: bool = False,
        clear_downstream: bool = False,
        dry_run: bool = False,
    ) -> RequeueResult:
        """Requeue from an error with optional resolution marking.

        Looks up the request associated with an error and requeues it.
        By default, marks the error as resolved with a note indicating it was requeued.

        Args:
            error_id: The database ID of the error.
            mark_resolved: If True, mark error as resolved after requeuing.
            clear_responses: If True, delete responses for the requeued request.
            clear_downstream: If True, recursively delete downstream artifacts.
            dry_run: If True, report what would happen without making changes.

        Returns:
            RequeueResult with lists of affected IDs and dry_run flag.
            Returns empty result if error not found or has no associated request.

        Example::

            # Requeue from error and mark resolved
            result = await manager.requeue_error(5)

            # Requeue but keep error unresolved
            result = await manager.requeue_error(5, mark_resolved=False)
        """
        # Get error and associated request_id
        cursor = await self._db.execute(
            SQL.SELECT_ERROR_ID_AND_REQUEST_ID, (error_id,)
        )
        row = await cursor.fetchone()

        if row is None:
            return RequeueResult(dry_run=dry_run)

        _, request_id = row

        if request_id is None:
            return RequeueResult(dry_run=dry_run)

        # Requeue the request
        result = await self.requeue_requests(
            [request_id],
            clear_responses=clear_responses,
            clear_downstream=clear_downstream,
            dry_run=dry_run,
        )

        # Mark error as resolved if requested and not a dry run
        if mark_resolved and not dry_run and result.requeued_request_ids:
            async with self._lock:
                new_request_id = result.requeued_request_ids[0]
                await self._db.execute(
                    SQL.UPDATE_RESOLVE_ERROR,
                    (f"Requeued as request {new_request_id}", error_id),
                )
                await self._db.commit()
                result.resolved_error_ids = [error_id]

        return result

    async def requeue_continuation(
        self,
        continuation: str,
        *,
        error_type: str | None = None,
        traceback_contains: str | None = None,
        clear_responses: bool = False,
        clear_downstream: bool = False,
        dry_run: bool = False,
    ) -> RequeueResult:
        """Bulk requeue requests by continuation with optional error filtering.

        Requeues all completed requests for a continuation, optionally filtering
        to only those with specific types of errors.

        Args:
            continuation: The continuation method name to filter by.
            error_type: Optional error type filter (e.g., "structural", "validation").
            traceback_contains: Optional substring to match in error tracebacks.
            clear_responses: If True, delete responses for the requeued requests.
            clear_downstream: If True, recursively delete downstream artifacts.
            dry_run: If True, report what would happen without making changes.

        Returns:
            RequeueResult with lists of affected IDs and dry_run flag.

        Example::

            # Requeue all completed requests for a continuation
            result = await manager.requeue_continuation("parse_results")

            # Requeue only requests with structural errors
            result = await manager.requeue_continuation(
                "parse_results", error_type="structural"
            )

            # Requeue requests with KeyError in traceback
            result = await manager.requeue_continuation(
                "parse_results", traceback_contains="KeyError"
            )

            # Combined filters
            result = await manager.requeue_continuation(
                "parse_results",
                error_type="validation",
                traceback_contains="expected str"
            )
        """
        # Build query based on filters
        if error_type or traceback_contains:
            # Filter by errors
            conditions = ["e.is_resolved = 0", "r.continuation = ?"]
            params: list[Any] = [continuation]

            if error_type:
                conditions.append("e.error_type = ?")
                params.append(error_type)

            if traceback_contains:
                conditions.append("e.traceback LIKE ?")
                params.append(f"%{traceback_contains}%")

            where_clause = " AND ".join(conditions)
            query = SQL.SELECT_REQUEST_IDS_WITH_ERROR_FILTER.format(
                where_clause=where_clause
            )
        else:
            # No error filtering, get all completed requests for continuation
            query = SQL.SELECT_REQUEST_IDS_BY_CONTINUATION_COMPLETED
            params = [continuation]

        cursor = await self._db.execute(query, params)
        rows = await cursor.fetchall()
        request_ids = [row[0] for row in rows]

        if not request_ids:
            return RequeueResult(dry_run=dry_run)

        # Delegate to requeue_requests
        result = await self.requeue_requests(
            request_ids,
            clear_responses=clear_responses,
            clear_downstream=clear_downstream,
            dry_run=dry_run,
        )

        # If we filtered by errors and not a dry run, mark those errors as resolved
        if (error_type or traceback_contains) and not dry_run and request_ids:
            # Get error IDs for the requeued requests
            placeholders = ",".join("?" * len(request_ids))
            cursor = await self._db.execute(
                SQL.SELECT_UNRESOLVED_ERROR_IDS_BY_REQUEST_IDS.format(
                    placeholders=placeholders
                ),
                request_ids,
            )
            error_rows = await cursor.fetchall()
            error_ids = [row[0] for row in error_rows]

            if error_ids:
                async with self._lock:
                    placeholders = ",".join("?" * len(error_ids))
                    await self._db.execute(
                        SQL.BULK_RESOLVE_ERRORS.format(
                            placeholders=placeholders
                        ),
                        ["Bulk requeued via continuation"] + error_ids,
                    )
                    await self._db.commit()
                    result.resolved_error_ids = error_ids

        return result
