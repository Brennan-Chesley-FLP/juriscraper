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

import json
import logging
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Generic, Literal, TypeVar

import aiosqlite

from juriscraper.scraper_driver.driver.dev_driver.schema import (
    get_next_queue_counter,
    init_database,
)
from juriscraper.scraper_driver.driver.dev_driver.sql_queries import SQL

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

logger = logging.getLogger(__name__)


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

    Example:
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

        Example:
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
        base_delay: float,
        jitter: float,
        num_workers: int,
        max_backoff_time: float,
        speculation_config: dict[str, dict[str, int]] | None = None,
    ) -> None:
        """Initialize run metadata in database.

        Only creates a new entry if one doesn't exist.

        Args:
            scraper_name: Name of the scraper class.
            scraper_version: Version string if available.
            base_delay: Base rate limit delay in seconds.
            jitter: Rate limit jitter in seconds.
            num_workers: Number of concurrent workers.
            max_backoff_time: Maximum total backoff time before failure.
            speculation_config: Optional dict mapping continuation name to
                {"threshold": int, "speculation": int} for speculative handling.
        """
        cursor = await self._db.execute(SQL.SELECT_RUN_METADATA_BY_ID)
        row = await cursor.fetchone()

        speculation_config_json = (
            json.dumps(speculation_config) if speculation_config else None
        )

        if row is None:
            await self._db.execute(
                SQL.INSERT_RUN_METADATA,
                (
                    scraper_name,
                    scraper_version,
                    base_delay,
                    jitter,
                    num_workers,
                    max_backoff_time,
                    speculation_config_json,
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
        await self._db.execute(SQL.RESET_IN_PROGRESS_TO_PENDING)
        await self._db.commit()

        cursor = await self._db.execute(SQL.COUNT_PENDING_REQUESTS)
        row = await cursor.fetchone()
        return row[0] if row else 0

    async def close_run(self) -> None:
        """Clean up database state on driver close.

        Resets in_progress requests to pending and updates run status.
        """
        try:
            await self._db.execute(SQL.RESET_IN_PROGRESS_TO_PENDING)
            await self._db.execute(SQL.UPDATE_RUN_STATUS_ON_CLOSE)
            await self._db.commit()
        except Exception as e:
            logger.warning(f"Failed to update state on close: {e}")

    async def update_run_status_running(self) -> None:
        """Mark run as running."""
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
        await self._db.execute(SQL.UPDATE_RUN_STATUS_FINAL, (status, error))
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
        cursor = await self._db.execute("SELECT COUNT(*) FROM requests")
        row = await cursor.fetchone()
        return (row[0] if row else 0) > 0

    async def get_run_metadata(self) -> dict[str, Any] | None:
        """Get run metadata from database.

        Returns:
            Dict with run metadata or None if not found.
        """
        cursor = await self._db.execute(
            """
            SELECT scraper_name, scraper_version, status, created_at, started_at,
                   ended_at, error_message, base_delay, jitter, num_workers,
                   max_backoff_time, speculation_config_json
            FROM run_metadata WHERE id = 1
            """
        )
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

        Returns:
            The ID of the newly inserted request.
        """
        queue_counter = await get_next_queue_counter(self._db)
        created_at_ns = time.monotonic_ns()

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
        cursor = await self._db.execute(SQL.COUNT_PENDING_REQUESTS)
        row = await cursor.fetchone()
        return row[0] if row else 0

    async def count_active_requests(self) -> int:
        """Count pending and in_progress requests."""
        cursor = await self._db.execute(SQL.COUNT_ACTIVE_REQUESTS)
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
        cursor = await self._db.execute(SQL.UPDATE_PAUSE_STEP, (continuation,))
        await self._db.commit()
        return cursor.rowcount

    async def resume_step(self, continuation: str) -> int:
        """Resume processing of held requests.

        Args:
            continuation: The continuation method name.

        Returns:
            Number of requests restored to pending.
        """
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

        Returns:
            The ID of the newly inserted request.
        """
        queue_counter = await get_next_queue_counter(self._db)
        created_at_ns = time.monotonic_ns()

        cursor = await self._db.execute(
            SQL.INSERT_REQUEUE_REQUEST,
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

    async def requeue_error(self, error_id: int) -> int | None:
        """Requeue a single error by creating a new pending request.

        Args:
            error_id: The database ID of the error.

        Returns:
            The new request ID, or None if error not found or already resolved.
        """
        # Get error and request data
        row = await self.get_error_with_request(error_id)
        if row is None:
            return None

        # Unpack row: id, request_id, is_resolved, method, url, headers_json,
        #            cookies_json, body, continuation, current_location,
        #            accumulated_data_json, aux_data_json, permanent_json, priority
        (
            _error_id,
            request_id,
            is_resolved,
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
            priority,
        ) = row

        if is_resolved:
            return None
        if request_id is None:
            return None

        # Create new request
        new_request_id = await self.insert_requeue_request(
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
            original_request_id=request_id,
        )

        # Mark error as resolved
        await self._db.execute(
            SQL.UPDATE_RESOLVE_ERROR,
            (f"Requeued as request {new_request_id}", error_id),
        )
        await self._db.commit()

        return new_request_id

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
            #            accumulated_data_json, aux_data_json, permanent_json, priority
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
            )
            new_request_ids.append(new_request_id)
            error_ids.append(error_id)

        # Mark all errors as resolved
        if error_ids:
            placeholders = ",".join("?" * len(error_ids))
            await self._db.execute(
                f"""
                UPDATE errors
                SET is_resolved = 1, resolved_at = CURRENT_TIMESTAMP,
                    resolution_notes = 'Batch requeued'
                WHERE id IN ({placeholders})
                """,
                error_ids,
            )
            await self._db.commit()

        return new_request_ids

    # --- Speculative Progress ---

    async def update_speculative_progress(
        self, step_name: str, speculative_id: int
    ) -> None:
        """Update the latest speculative_id for a step.

        Uses MAX to ensure we only track forward progress.

        Args:
            step_name: The name of the speculative step method.
            speculative_id: The speculative_id that was just processed.
        """
        await self._db.execute(
            SQL.UPSERT_SPECULATIVE_PROGRESS, (step_name, speculative_id)
        )
        await self._db.commit()

    async def get_speculative_progress(self, step_name: str) -> int | None:
        """Get the latest speculative_id for a step.

        Args:
            step_name: The name of the speculative step method.

        Returns:
            The latest speculative_id, or None if no progress recorded.
        """
        cursor = await self._db.execute(
            SQL.SELECT_SPECULATIVE_PROGRESS, (step_name,)
        )
        row = await cursor.fetchone()
        return row[0] if row else None

    async def get_all_speculative_progress(self) -> dict[str, int]:
        """Get all speculative progress entries.

        Returns:
            Dict mapping step names to their latest speculative_id.
        """
        cursor = await self._db.execute(SQL.SELECT_ALL_SPECULATIVE_PROGRESS)
        rows = await cursor.fetchall()
        return {row[0]: row[1] for row in rows}

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
        await self._db.execute(SQL.DELETE_SPECULATIVE_START_ID, (step_name,))
        await self._db.commit()

    async def clear_all_speculative_start_ids(self) -> None:
        """Clear all speculative starting IDs.

        Called after the driver has applied all starting IDs.
        """
        await self._db.execute(SQL.DELETE_ALL_SPECULATIVE_START_IDS)
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
        completed_at_ns = time.monotonic_ns()
        cursor = await self._db.execute(
            SQL.UPDATE_CANCEL_BY_CONTINUATION, (completed_at_ns, continuation)
        )
        await self._db.commit()
        return cursor.rowcount

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
                is_valid=row[4],
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
            is_valid=row[4],
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
            "SELECT permanent_json FROM requests WHERE id = ?", (request_id,)
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
        await self._db.execute(
            SQL.UPDATE_RATE_LIMITER_RATE_DECREASE, (new_rate, congestion_rate)
        )
        await self._db.commit()

    async def increment_rate_limiter_success(self) -> None:
        """Increment success counter without changing rate.

        Used when response succeeds but rate doesn't change.
        """
        await self._db.execute(SQL.UPDATE_RATE_LIMITER_SUCCESS)
        await self._db.commit()

    async def increment_rate_limiter_rate_limited(self) -> None:
        """Increment rate-limited counter without changing rate.

        Used when response is rate-limited but rate doesn't change.
        """
        await self._db.execute(SQL.UPDATE_RATE_LIMITER_RATE_LIMITED)
        await self._db.commit()
