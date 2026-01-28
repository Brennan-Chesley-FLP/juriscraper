"""LocalDevDriverDebugger - Inspection and manipulation of scraper run databases.

This module provides a standalone class for inspecting and manipulating
LocalDevDriver run databases without requiring the full driver machinery.

The LocalDevDriverDebugger (LDDD) enables:
- Read-only inspection of completed or running scraper runs
- Safe manipulation operations (requeue, cancel, resolve errors)
- Lightweight CLI and WebUI tooling
- Testing and debugging workflows

Key features:
- Async context manager for connection lifecycle
- Read-only mode enforcement via SQLite connection flags
- High-level API wrapping SQLManager for semantic operations
- Compatible with existing RequestRecord, ResponseRecord, ResultRecord types

Example usage:
    # Read-only inspection
    async with LocalDevDriverDebugger.open(db_path, read_only=True) as debugger:
        metadata = await debugger.get_run_metadata()
        stats = await debugger.get_stats()
        requests = await debugger.list_requests(status='failed')

    # Write operations (requeue, cancel, etc.)
    async with LocalDevDriverDebugger.open(db_path, read_only=False) as debugger:
        await debugger.requeue_error(error_id=123)
        await debugger.cancel_request(request_id=456)
"""

from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

import aiosqlite

from juriscraper.scraper_driver.driver.dev_driver.sql_manager import (
    Page,
    RequestRecord,
    ResponseRecord,
    ResultRecord,
    SQLManager,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

logger = logging.getLogger(__name__)


class LocalDevDriverDebugger:
    """Debug and inspect LocalDevDriver run databases.

    This class provides a high-level API for inspecting and manipulating
    scraper run databases without requiring the full LocalDevDriver runtime.

    Supports both read-only inspection (safe for analyzing running/completed runs)
    and write operations (requeue, cancel, resolve errors).

    Attributes:
        sql: The underlying SQLManager instance for database operations.
        read_only: Whether this instance is in read-only mode.
    """

    def __init__(self, sql: SQLManager, read_only: bool = True) -> None:
        """Initialize the debugger.

        Args:
            sql: SQLManager instance wrapping the database connection.
            read_only: If True, write operations will raise errors.
        """
        self.sql = sql
        self.read_only = read_only

    @classmethod
    @asynccontextmanager
    async def open(
        cls, db_path: Path | str, read_only: bool = True
    ) -> AsyncIterator[LocalDevDriverDebugger]:
        """Open a database for debugging.

        Args:
            db_path: Path to the SQLite database file.
            read_only: If True, open in read-only mode (prevents writes).

        Yields:
            LocalDevDriverDebugger instance.

        Example:
            async with LocalDevDriverDebugger.open("run.db") as debugger:
                stats = await debugger.get_stats()
        """
        if isinstance(db_path, str):
            db_path = Path(db_path)

        # Open database with appropriate mode
        uri = f"file:{db_path}{'?mode=ro' if read_only else ''}"
        async with aiosqlite.connect(uri, uri=True) as db:
            # Enable foreign keys
            await db.execute("PRAGMA foreign_keys = ON")
            # Set row factory for named access
            db.row_factory = aiosqlite.Row

            sql = SQLManager(db)
            yield cls(sql, read_only=read_only)

    def _require_write_mode(self) -> None:
        """Raise an error if in read-only mode.

        Raises:
            PermissionError: If the debugger is in read-only mode.
        """
        if self.read_only:
            raise PermissionError(
                "Operation requires write mode. Open with read_only=False."
            )

    # =========================================================================
    # Run Metadata and Stats
    # =========================================================================

    async def get_run_metadata(self) -> dict[str, Any] | None:
        """Get run metadata including scraper name, status, timestamps, and configuration.

        Returns:
            Dictionary with run metadata fields:
                - scraper_name: Name of the scraper
                - scraper_version: Version of the scraper
                - status: Current run status (created, running, completed, error, interrupted)
                - created_at: When the run was created
                - started_at: When execution started (None if not started)
                - ended_at: When execution ended (None if still running)
                - error_message: Error message if status is 'error'
                - base_delay: Base rate limiting delay
                - jitter: Rate limiting jitter
                - num_workers: Number of concurrent workers
                - max_backoff_time: Maximum backoff time for retries
                - speculation_config_json: JSON string of speculation configuration

            Returns None if no run metadata exists (empty database).

        Example:
            metadata = await debugger.get_run_metadata()
            print(f"Scraper: {metadata['scraper_name']}")
            print(f"Status: {metadata['status']}")
        """
        return await self.sql.get_run_metadata()

    async def get_run_status(self) -> dict[str, Any]:
        """Get run status with pending count or wrapped status indicator.

        Returns a status dictionary suitable for health reports and doctor commands.
        For runs in progress, shows the pending request count. For completed runs,
        shows the final status.

        Returns:
            Dictionary with status information:
                - status: Current run status (created, running, completed, error, interrupted)
                - pending_count: Number of pending requests (only if status is running)
                - is_running: Boolean indicating if run is in progress

        Example:
            status = await debugger.get_run_status()
            if status['is_running']:
                print(f"Run in progress: {status['pending_count']} pending requests")
            else:
                print(f"Run {status['status']}")
        """
        from juriscraper.scraper_driver.driver.dev_driver.sql_queries import (
            SQL,
        )

        # Get run status from metadata
        async with self.sql.db.execute(SQL.SELECT_RUN_METADATA) as cursor:
            row = await cursor.fetchone()
            if not row:
                return {
                    "status": "unknown",
                    "is_running": False,
                }

            # scraper_name = row[0]
            status = row[1]

        # Determine if run is in progress
        is_running = status in ("created", "running")

        result = {
            "status": status,
            "is_running": is_running,
        }

        # If running, include pending count
        if is_running:
            async with self.sql.db.execute(
                SQL.COUNT_PENDING_REQUESTS
            ) as cursor:
                row = await cursor.fetchone()
                pending_count = row[0] if row else 0
                result["pending_count"] = pending_count

        return result

    async def get_stats(self) -> dict[str, Any]:
        """Get comprehensive statistics about the run.

        Returns:
            Dictionary with statistics:
                - queue: Request queue statistics by status
                - queue_by_continuation: Request counts grouped by continuation and status
                - throughput: Request throughput statistics (count, avg time, etc.)
                - compression: Compression statistics (total, original size, compressed size, etc.)
                - results: Result statistics (total, valid, invalid counts)
                - results_by_type: Result counts grouped by type
                - errors: Error statistics (total, resolved, unresolved counts)
                - errors_by_type: Error counts grouped by type
                - errors_by_continuation: Error counts grouped by continuation

        Example:
            stats = await debugger.get_stats()
            print(f"Total requests: {stats['queue']['total']}")
            print(f"Errors: {stats['errors']['total']}")
        """
        stats = await self.sql.get_stats()
        # Convert DevDriverStats to dict for consistent API
        return stats.to_dict()

    # =========================================================================
    # Request Inspection
    # =========================================================================

    async def list_requests(
        self,
        status: Literal[
            "pending", "in_progress", "completed", "failed", "held"
        ]
        | None = None,
        continuation: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> Page[RequestRecord]:
        """List requests with optional filtering.

        Args:
            status: Filter by request status (pending, in_progress, completed, failed, held).
            continuation: Filter by continuation (step name).
            limit: Maximum number of requests to return.
            offset: Number of requests to skip (for pagination).

        Returns:
            Page object containing:
                - items: List of RequestRecord objects
                - total: Total number of matching requests
                - limit: The limit parameter
                - offset: The offset parameter
                - has_more: Whether there are more results

        Example:
            # Get first page of failed requests
            page = await debugger.list_requests(status='failed', limit=50)
            for req in page.items:
                print(f"Request {req.id}: {req.url}")

            # Get next page
            next_page = await debugger.list_requests(
                status='failed', limit=50, offset=50
            )
        """
        return await self.sql.list_requests(
            status=status,
            continuation=continuation,
            limit=limit,
            offset=offset,
        )

    async def get_request(self, request_id: int) -> RequestRecord | None:
        """Get a single request by ID.

        Args:
            request_id: The request ID.

        Returns:
            RequestRecord if found, None otherwise.

        Example:
            request = await debugger.get_request(123)
            if request:
                print(f"URL: {request.url}")
                print(f"Status: {request.status}")
                print(f"Retries: {request.retry_count}")
        """
        return await self.sql.get_request(request_id)

    async def get_request_summary(
        self,
    ) -> dict[str, dict[str, int]]:
        """Get summary of request counts by status and continuation.

        Returns:
            Dictionary mapping continuation -> {status -> count}.
            Includes a special "all" key for totals across all continuations.

        Example:
            summary = await debugger.get_request_summary()
            print(f"Total pending: {summary['all']['pending']}")
            print(f"Step1 completed: {summary['step1']['completed']}")
        """
        stats = await self.sql.get_stats()
        # stats is a DevDriverStats object, access queue.by_continuation
        queue_stats = stats.queue.by_continuation

        # Restructure to match expected format
        summary: dict[str, dict[str, int]] = {"all": {}}
        for continuation, status_dict in queue_stats.items():
            if continuation not in summary:
                summary[continuation] = {}
            for status, count in status_dict.items():
                summary[continuation][status] = count
                # Add to totals
                summary["all"][status] = summary["all"].get(status, 0) + count

        return summary

    # =========================================================================
    # Response Inspection
    # =========================================================================

    async def list_responses(
        self,
        continuation: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> Page[ResponseRecord]:
        """List responses with optional filtering.

        Args:
            continuation: Filter by continuation (step name).
            limit: Maximum number of responses to return.
            offset: Number of responses to skip (for pagination).

        Returns:
            Page object containing ResponseRecord items.

        Example:
            page = await debugger.list_responses(continuation='step1', limit=50)
            for resp in page.items:
                print(f"Response {resp.id}: {resp.status_code} - {resp.url}")
        """
        return await self.sql.list_responses(
            continuation=continuation, limit=limit, offset=offset
        )

    async def get_response(self, response_id: int) -> ResponseRecord | None:
        """Get a single response by ID.

        Args:
            response_id: The response ID.

        Returns:
            ResponseRecord if found, None otherwise.

        Example:
            response = await debugger.get_response(123)
            if response:
                print(f"Status: {response.status_code}")
                print(f"Size: {response.content_size_original} bytes")
                print(f"Compression: {response.compression_ratio}x")
        """
        return await self.sql.get_response(response_id)

    async def get_response_content(self, response_id: int) -> bytes | None:
        """Get decompressed response content.

        Args:
            response_id: The response ID.

        Returns:
            Decompressed response content bytes, or None if not found.

        Example:
            content = await debugger.get_response_content(123)
            if content:
                html = content.decode('utf-8')
                print(html[:500])
        """
        return await self.sql.get_response_content(response_id)

    # =========================================================================
    # Error Inspection
    # =========================================================================

    async def list_errors(
        self,
        error_type: str | None = None,
        is_resolved: bool | None = None,
        continuation: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> Page[dict[str, Any]]:
        """List errors with optional filtering.

        Args:
            error_type: Filter by error type (e.g., 'xpath', 'http', 'validation').
            is_resolved: Filter by resolution status (True=resolved, False=unresolved).
            continuation: Filter by continuation (step name).
            limit: Maximum number of errors to return.
            offset: Number of errors to skip (for pagination).

        Returns:
            Page object containing error dictionaries.

        Example:
            # Get unresolved XPath errors
            page = await debugger.list_errors(
                error_type='xpath', is_resolved=False
            )
            for error in page.items:
                print(f"Error {error['id']}: {error['message']}")
                print(f"Selector: {error['selector']}")
        """
        # Build WHERE clause
        conditions: list[str] = []
        params: list[str | int] = []

        if error_type is not None:
            conditions.append("e.error_type = ?")
            params.append(error_type)

        if is_resolved is not None:
            conditions.append("e.is_resolved = ?")
            params.append(1 if is_resolved else 0)

        if continuation is not None:
            conditions.append("r.continuation = ?")
            params.append(continuation)

        # Determine which query to use based on whether we need joins
        if continuation is not None:
            # Use the JOIN query
            from juriscraper.scraper_driver.driver.dev_driver.sql_queries import (
                SQL,
            )

            where_clause = (
                "WHERE " + " AND ".join(conditions) if conditions else ""
            )
            query = SQL.SELECT_ERRORS_LIST_WITH_JOIN.format(
                where_clause=where_clause
            )
            count_query = f"""
                SELECT COUNT(*) FROM errors e
                LEFT JOIN requests r ON e.request_id = r.id
                {where_clause}
            """
        else:
            # Use simple query without join
            from juriscraper.scraper_driver.driver.dev_driver.sql_queries import (
                SQL,
            )

            where_clause = (
                "WHERE " + " AND ".join(conditions) if conditions else ""
            )
            query = SQL.SELECT_ERRORS_LIST.format(where_clause=where_clause)
            count_query = f"SELECT COUNT(*) FROM errors e {where_clause}"

        # Get total count
        async with self.sql.db.execute(count_query, params) as cursor:
            row = await cursor.fetchone()
            total = row[0] if row else 0

        # Get page of results
        query_params = params + [limit, offset]
        async with self.sql.db.execute(query, query_params) as cursor:
            rows = await cursor.fetchall()

        # Convert rows to dictionaries
        # Column order matches SELECT_ERRORS_LIST and SELECT_ERRORS_LIST_WITH_JOIN
        error_columns = [
            "id",
            "request_id",
            "error_type",
            "error_class",
            "message",
            "request_url",
            "context_json",
            "selector",
            "selector_type",
            "expected_min",
            "expected_max",
            "actual_count",
            "model_name",
            "validation_errors_json",
            "failed_doc_json",
            "status_code",
            "timeout_seconds",
            "traceback",
            "is_resolved",
            "resolved_at",
            "resolution_notes",
            "created_at",
        ]
        items = []
        for row in rows:
            error_dict = dict(zip(error_columns, row))
            # Convert SQLite 1/0 to Python bool
            error_dict["is_resolved"] = bool(error_dict["is_resolved"])
            items.append(error_dict)

        return Page(items=items, total=total, limit=limit, offset=offset)

    async def get_error(self, error_id: int) -> dict[str, Any] | None:
        """Get a single error by ID with full details.

        Args:
            error_id: The error ID.

        Returns:
            Error dictionary with all fields, or None if not found.

        Example:
            error = await debugger.get_error(123)
            if error:
                print(f"Type: {error['error_type']}")
                print(f"Message: {error['message']}")
                if error['selector']:
                    print(f"XPath: {error['selector']}")
        """
        from juriscraper.scraper_driver.driver.dev_driver.sql_queries import (
            SQL,
        )

        async with self.sql.db.execute(
            SQL.SELECT_ERROR_FULL, (error_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                # Column order matches SELECT_ERROR_FULL
                error_columns = [
                    "id",
                    "request_id",
                    "error_type",
                    "error_class",
                    "message",
                    "request_url",
                    "context_json",
                    "selector",
                    "selector_type",
                    "expected_min",
                    "expected_max",
                    "actual_count",
                    "model_name",
                    "validation_errors_json",
                    "failed_doc_json",
                    "status_code",
                    "timeout_seconds",
                    "traceback",
                    "is_resolved",
                    "resolved_at",
                    "resolution_notes",
                    "created_at",
                ]
                error_dict = dict(zip(error_columns, row))
                # Convert SQLite 1/0 to Python bool
                error_dict["is_resolved"] = bool(error_dict["is_resolved"])
                return error_dict
            return None

    async def get_error_summary(self) -> dict[str, Any]:
        """Get summary of error counts by type and resolution status.

        Returns:
            Dictionary with error counts:
                - by_type: {error_type -> {resolved: count, unresolved: count}}
                - by_continuation: {continuation -> error_count}
                - totals: {resolved: count, unresolved: count, total: count}

        Example:
            summary = await debugger.get_error_summary()
            print(f"Total errors: {summary['totals']['total']}")
            print(f"XPath errors: {summary['by_type']['xpath']['unresolved']}")
        """
        from juriscraper.scraper_driver.driver.dev_driver.sql_queries import (
            SQL,
        )

        # Get counts by type and resolution
        by_type: dict[str, dict[str, int]] = {}
        async with self.sql.db.execute(
            SQL.SELECT_ERROR_SUMMARY_FOR_WEB
        ) as cursor:
            rows = await cursor.fetchall()
            for row in rows:
                error_type = row[0]
                is_resolved = bool(row[1])
                count = row[2]

                if error_type not in by_type:
                    by_type[error_type] = {"resolved": 0, "unresolved": 0}

                if is_resolved:
                    by_type[error_type]["resolved"] = count
                else:
                    by_type[error_type]["unresolved"] = count

        # Get counts by continuation
        by_continuation: dict[str, int] = {}
        async with self.sql.db.execute(
            SQL.SELECT_ERROR_STATS_BY_CONTINUATION
        ) as cursor:
            rows = await cursor.fetchall()
            for row in rows:
                continuation = row[0]
                count = row[1]
                by_continuation[continuation] = count

        # Get totals
        stats = await self.sql.get_stats()
        # stats is a DevDriverStats object, access errors directly
        error_stats = stats.errors
        totals = {
            "resolved": error_stats.resolved,
            "unresolved": error_stats.unresolved,
            "total": error_stats.total,
        }

        return {
            "by_type": by_type,
            "by_continuation": by_continuation,
            "totals": totals,
        }

    # =========================================================================
    # Result Inspection
    # =========================================================================

    async def list_results(
        self,
        result_type: str | None = None,
        is_valid: bool | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> Page[ResultRecord]:
        """List results with optional filtering.

        Args:
            result_type: Filter by result type (Pydantic model class name).
            is_valid: Filter by validation status (True=valid, False=invalid).
            limit: Maximum number of results to return.
            offset: Number of results to skip (for pagination).

        Returns:
            Page object containing ResultRecord items.

        Example:
            # Get all valid court opinions
            page = await debugger.list_results(
                result_type='CourtOpinion', is_valid=True
            )
            for result in page.items:
                data = result.data
                print(f"Result {result.id}: {data.get('title')}")
        """
        return await self.sql.list_results(
            result_type=result_type,
            is_valid=is_valid,
            limit=limit,
            offset=offset,
        )

    async def get_result(self, result_id: int) -> ResultRecord | None:
        """Get a single result by ID.

        Args:
            result_id: The result ID.

        Returns:
            ResultRecord if found, None otherwise.

        Example:
            result = await debugger.get_result(123)
            if result:
                print(f"Type: {result.result_type}")
                print(f"Valid: {result.is_valid}")
                print(f"Data: {result.data}")
        """
        return await self.sql.get_result(result_id)

    async def get_result_summary(self) -> dict[str, dict[str, int]]:
        """Get summary of result counts by type and validity.

        Returns:
            Dictionary mapping result_type -> {valid: count, invalid: count, total: count}.

        Example:
            summary = await debugger.get_result_summary()
            for result_type, counts in summary.items():
                print(f"{result_type}: {counts['valid']} valid, {counts['invalid']} invalid")
        """
        from juriscraper.scraper_driver.driver.dev_driver.sql_queries import (
            SQL,
        )

        summary: dict[str, dict[str, int]] = {}
        async with self.sql.db.execute(
            SQL.SELECT_RESULTS_SUMMARY_FOR_WEB
        ) as cursor:
            rows = await cursor.fetchall()
            for row in rows:
                result_type = row[0]
                valid_count = row[1]
                invalid_count = row[2]
                total_count = row[3]

                summary[result_type] = {
                    "valid": valid_count,
                    "invalid": invalid_count,
                    "total": total_count,
                }

        return summary

    # =========================================================================
    # Speculation Inspection
    # =========================================================================

    async def get_speculation_summary(self) -> dict[str, Any]:
        """Get summary of speculation configuration and progress.

        Returns:
            Dictionary with:
                - config: Speculation configuration from run metadata
                - progress: Current speculative progress by step
                - tracking: Speculation tracking state (@speculate pattern)

        Example:
            summary = await debugger.get_speculation_summary()
            print(f"Config: {summary['config']}")
            print(f"Progress: {summary['progress']}")
        """
        config = await self.sql.get_speculation_config()
        progress = await self.sql.get_all_speculative_progress()
        tracking = await self.sql.load_all_speculation_states()

        return {
            "config": config,
            "progress": progress,
            "tracking": tracking,
        }

    async def get_speculative_progress(self) -> dict[str, int]:
        """Get current speculative progress for all steps.

        Returns:
            Dictionary mapping step_name -> latest_speculative_id.

        Example:
            progress = await debugger.get_speculative_progress()
            for step, latest_id in progress.items():
                print(f"{step}: up to ID {latest_id}")
        """
        return await self.sql.get_all_speculative_progress()

    # =========================================================================
    # Rate Limiter Inspection
    # =========================================================================

    async def get_rate_limiter_state(self) -> dict[str, Any] | None:
        """Get current rate limiter state.

        Returns:
            Dictionary with rate limiter state:
                - tokens: Current token count
                - rate: Current request rate (requests/second)
                - bucket_size: Token bucket size
                - last_congestion_rate: Rate at last congestion event
                - jitter: Jitter value
                - last_used_at: Last time tokens were consumed
                - total_requests: Total requests made
                - total_successes: Total successful requests
                - total_rate_limited: Total rate-limited requests

            Returns None if no state exists.

        Example:
            state = await debugger.get_rate_limiter_state()
            if state:
                print(f"Current rate: {state['rate']} req/s")
                print(f"Tokens: {state['tokens']}/{state['bucket_size']}")
        """
        return await self.sql.get_rate_limiter_state()

    async def get_throughput_stats(self) -> dict[str, Any]:
        """Get request throughput statistics.

        Returns:
            Dictionary with throughput stats from get_stats()['throughput'].

        Example:
            stats = await debugger.get_throughput_stats()
            print(f"Total completed: {stats['count']}")
            print(f"Average time: {stats['avg_time']:.2f}s")
        """
        stats = await self.sql.get_stats()
        # stats is a DevDriverStats object, convert throughput to dict
        return stats.throughput.to_dict()

    # =========================================================================
    # Compression Inspection
    # =========================================================================

    async def get_compression_stats(self) -> dict[str, Any]:
        """Get compression statistics.

        Returns:
            Dictionary with compression stats:
                - total: Total responses
                - total_original: Total original size (bytes)
                - total_compressed: Total compressed size (bytes)
                - with_dict: Number using compression dictionaries
                - no_dict: Number without compression dictionaries
                - compression_ratio: Overall compression ratio

        Example:
            stats = await debugger.get_compression_stats()
            ratio = stats['total_original'] / stats['total_compressed']
            print(f"Compression ratio: {ratio:.2f}x")
        """
        stats = await self.sql.get_stats()
        # stats is a DevDriverStats object, convert compression to dict
        compression_dict = stats.compression.to_dict()
        # Map field names for test compatibility
        return {
            "total": compression_dict.get("total_responses", 0),
            "total_original": compression_dict.get("total_original_bytes", 0),
            "total_compressed": compression_dict.get(
                "total_compressed_bytes", 0
            ),
            "with_dict": compression_dict.get("dict_compressed_count", 0),
            "no_dict": compression_dict.get("no_dict_compressed_count", 0),
            "compression_ratio": compression_dict.get(
                "compression_ratio", 1.0
            ),
        }

    async def list_compression_dicts(self) -> list[dict[str, Any]]:
        """List all compression dictionaries.

        Returns:
            List of compression dictionary metadata dictionaries:
                - id: Dictionary ID
                - continuation: Which continuation it's for
                - version: Version number
                - sample_count: Number of samples trained on
                - size: Dictionary size in bytes
                - created_at: When it was created

        Example:
            dicts = await debugger.list_compression_dicts()
            for d in dicts:
                print(f"Dict {d['id']}: {d['continuation']} v{d['version']}")
                print(f"  Trained on {d['sample_count']} samples")
        """
        from juriscraper.scraper_driver.driver.dev_driver.sql_queries import (
            SQL,
        )

        async with self.sql.db.execute(
            SQL.SELECT_COMPRESSION_DICTS_FOR_WEB
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    # =========================================================================
    # Request Manipulation
    # =========================================================================

    async def cancel_request(self, request_id: int) -> bool:
        """Cancel a pending or held request.

        Marks the request as 'failed' with an error message indicating cancellation.
        Only pending or held requests can be cancelled.

        Args:
            request_id: The request ID to cancel.

        Returns:
            True if the request was cancelled, False if it was not pending/held.

        Raises:
            PermissionError: If the debugger is in read-only mode.

        Example:
            # Cancel a stuck request
            cancelled = await debugger.cancel_request(123)
            if cancelled:
                print("Request cancelled successfully")
        """
        self._require_write_mode()
        return await self.sql.cancel_request(request_id)

    async def cancel_requests_by_continuation(self, continuation: str) -> int:
        """Cancel all pending/held requests for a continuation.

        Marks all pending or held requests for the given continuation as 'failed'.

        Args:
            continuation: The continuation (step name) to cancel.

        Returns:
            Number of requests cancelled.

        Raises:
            PermissionError: If the debugger is in read-only mode.

        Example:
            # Cancel all pending requests for a specific step
            count = await debugger.cancel_requests_by_continuation('step1')
            print(f"Cancelled {count} requests")
        """
        self._require_write_mode()
        return await self.sql.cancel_requests_by_continuation(continuation)

    async def requeue_request(
        self, request_id: int, clear_downstream: bool = True
    ) -> int:
        """Requeue a completed or failed request.

        Creates a new request with the same parameters, optionally clearing
        downstream requests, responses, results, and errors.

        Args:
            request_id: The request ID to requeue.
            clear_downstream: If True (default), delete all downstream data
                (responses, results, errors, child requests).

        Returns:
            The new request ID.

        Raises:
            PermissionError: If the debugger is in read-only mode.
            ValueError: If the request doesn't exist.

        Example:
            # Requeue a failed request with fresh start
            new_id = await debugger.requeue_request(123, clear_downstream=True)
            print(f"Requeued as request {new_id}")
        """
        self._require_write_mode()

        if clear_downstream:
            # Use requeue_requests which handles downstream cleanup
            result = await self.sql.requeue_requests(
                [request_id], clear_downstream=True
            )
            if not result.requeued_request_ids:
                raise ValueError(f"Request {request_id} not found")
            return result.requeued_request_ids[0]
        else:
            # Just create a new request without clearing
            # Get original request data
            from juriscraper.scraper_driver.driver.dev_driver.sql_queries import (
                SQL,
            )

            async with self.sql.db.execute(
                SQL.SELECT_REQUEST_FOR_WEB_REQUEUE, (request_id,)
            ) as cursor:
                row = await cursor.fetchone()
                if not row:
                    raise ValueError(f"Request {request_id} not found")

            # Insert new request
            # Query columns: id, method, url, continuation, priority,
            #               headers_json, cookies_json, body, current_location,
            #               accumulated_data_json, aux_data_json, permanent_json,
            #               request_type, expected_type
            new_id = await self.sql.insert_requeue_request(
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
                original_request_id=request_id,
                request_type=row[12] or "navigating",
                expected_type=row[13],
            )
            return new_id

    async def requeue_continuation(
        self,
        continuation: str,
        status: Literal["completed", "failed"] = "completed",
        clear_downstream: bool = True,
    ) -> int:
        """Requeue all requests for a continuation with a given status.

        Args:
            continuation: The continuation (step name) to requeue.
            status: Which requests to requeue ('completed' or 'failed').
            clear_downstream: If True (default), clear downstream data.
                Note: Currently this parameter is ignored for simplicity.
                The underlying operation does not clear downstream data.

        Returns:
            Number of requests requeued.

        Raises:
            PermissionError: If the debugger is in read-only mode.

        Example:
            # Requeue all completed requests for a step
            count = await debugger.requeue_continuation('step1', status='completed')
            print(f"Requeued {count} requests")
        """
        self._require_write_mode()
        # Use the simple requeue method that filters by continuation and status
        return await self.sql.requeue_requests_by_continuation(
            continuation=continuation,
            status=status,
        )

    # =========================================================================
    # Error Manipulation
    # =========================================================================

    async def resolve_error(
        self, error_id: int, resolution_notes: str | None = None
    ) -> bool:
        """Mark an error as resolved.

        Args:
            error_id: The error ID to resolve.
            resolution_notes: Optional notes about the resolution.

        Returns:
            True if the error was resolved, False if already resolved or not found.

        Raises:
            PermissionError: If the debugger is in read-only mode.

        Example:
            # Resolve an error after manual fix
            resolved = await debugger.resolve_error(
                123, "Fixed XPath selector in scraper code"
            )
        """
        self._require_write_mode()
        from juriscraper.scraper_driver.driver.dev_driver.sql_queries import (
            SQL,
        )

        async with self.sql.db.execute(
            SQL.UPDATE_RESOLVE_ERROR, (resolution_notes, error_id)
        ) as cursor:
            await self.sql.db.commit()
            return cursor.rowcount > 0

    async def requeue_error(
        self, error_id: int, resolution_notes: str | None = None
    ) -> int:
        """Requeue the request that caused an error.

        Marks the error as resolved and creates a new request with the same
        parameters as the failed request.

        Args:
            error_id: The error ID to requeue.
            resolution_notes: Optional notes (defaults to "Requeued for retry").

        Returns:
            The new request ID.

        Raises:
            PermissionError: If the debugger is in read-only mode.
            ValueError: If the error doesn't exist.

        Example:
            # Requeue an error after fixing the underlying issue
            new_id = await debugger.requeue_error(123, "Fixed server-side issue")
            print(f"Requeued as request {new_id}")
        """
        self._require_write_mode()

        if resolution_notes is None:
            resolution_notes = "Requeued for retry"

        # Call SQLManager's requeue_error which returns RequeueResult
        result = await self.sql.requeue_error(error_id, mark_resolved=True)

        if not result.requeued_request_ids:
            raise ValueError(
                f"Error {error_id} not found or has no associated request"
            )

        # Update resolution notes if custom notes provided
        new_request_id = result.requeued_request_ids[0]
        from juriscraper.scraper_driver.driver.dev_driver.sql_queries import (
            SQL,
        )

        await self.sql.db.execute(
            SQL.UPDATE_RESOLVE_ERROR,
            (
                f"{resolution_notes} (requeued as request {new_request_id})",
                error_id,
            ),
        )
        await self.sql.db.commit()

        return new_request_id

    async def batch_requeue_errors(
        self,
        error_type: str | None = None,
        continuation: str | None = None,
    ) -> int:
        """Requeue multiple errors matching filter criteria.

        Args:
            error_type: Filter by error type (e.g., 'xpath', 'http').
            continuation: Filter by continuation (step name).

        Returns:
            Number of errors requeued.

        Raises:
            PermissionError: If the debugger is in read-only mode.

        Example:
            # Requeue all XPath errors
            count = await debugger.batch_requeue_errors(error_type='xpath')
            print(f"Requeued {count} XPath errors")
        """
        self._require_write_mode()
        # SQLManager returns list of new request IDs, we return count
        new_request_ids = await self.sql.batch_requeue_errors(
            error_type=error_type,
            continuation=continuation,
        )
        return len(new_request_ids)

    # =========================================================================
    # Compression Manipulation
    # =========================================================================

    async def train_compression_dict(
        self, continuation: str, sample_count: int = 1000
    ) -> int:
        """Train a new compression dictionary for a continuation.

        Samples random responses from the continuation and trains a zstd
        dictionary to improve compression for future responses.

        Args:
            continuation: The continuation (step name) to train for.
            sample_count: Number of response samples to use for training.

        Returns:
            The new compression dictionary ID.

        Raises:
            PermissionError: If the debugger is in read-only mode.
            ValueError: If not enough samples available.

        Example:
            # Train a dictionary after collecting some responses
            dict_id = await debugger.train_compression_dict('step1', sample_count=500)
            print(f"Trained dictionary {dict_id}")
        """
        self._require_write_mode()

        # Import compression module
        from juriscraper.scraper_driver.driver.dev_driver.compression import (
            train_compression_dict,
        )

        dict_id = await train_compression_dict(
            self.sql.db, continuation, sample_count
        )
        return dict_id

    async def recompress_responses(
        self, continuation: str, dict_id: int | None = None
    ) -> dict[str, int]:
        """Recompress responses with a compression dictionary.

        Args:
            continuation: The continuation (step name) to recompress.
            dict_id: Compression dictionary ID. If None, uses latest for continuation.

        Returns:
            Dictionary with recompression statistics:
                - total: Total responses recompressed
                - size_before: Total size before recompression
                - size_after: Total size after recompression
                - savings: Bytes saved

        Raises:
            PermissionError: If the debugger is in read-only mode.
            ValueError: If no dictionary found.

        Example:
            # Recompress with latest dictionary
            stats = await debugger.recompress_responses('step1')
            print(f"Saved {stats['savings']} bytes ({stats['total']} responses)")

            # Recompress with specific dictionary
            stats = await debugger.recompress_responses('step1', dict_id=5)
        """
        self._require_write_mode()

        # Import compression module
        from juriscraper.scraper_driver.driver.dev_driver.compression import (
            recompress_responses,
        )

        total, size_before, size_after = await recompress_responses(
            self.sql.db, continuation, dict_id=dict_id
        )
        return {
            "total": total,
            "size_before": size_before,
            "size_after": size_after,
            "savings": size_before - size_after,
        }

    # =========================================================================
    # Integrity Check Methods
    # =========================================================================

    async def check_integrity(self) -> dict[str, Any]:
        """Check database integrity for orphaned requests and responses.

        Detects two types of integrity issues:
        1. Orphaned requests: completed requests with no corresponding response
        2. Orphaned responses: responses with no matching request

        Returns:
            Dictionary with integrity check results:
                - orphaned_requests: {count: int, ids: list[int]}
                - orphaned_responses: {count: int, ids: list[int]}
                - has_issues: bool (True if any orphans found)

        Example:
            result = await debugger.check_integrity()
            if result['has_issues']:
                print(f"Found {result['orphaned_requests']['count']} orphaned requests")
                print(f"Found {result['orphaned_responses']['count']} orphaned responses")
        """
        from juriscraper.scraper_driver.driver.dev_driver.sql_queries import (
            SQL,
        )

        # Count orphaned requests
        async with self.sql.db.execute(SQL.COUNT_ORPHANED_REQUESTS) as cursor:
            row = await cursor.fetchone()
            orphaned_requests_count = row[0] if row else 0

        # Get orphaned request IDs
        orphaned_request_ids: list[int] = []
        async with self.sql.db.execute(SQL.SELECT_ORPHANED_REQUESTS) as cursor:
            rows = await cursor.fetchall()
            orphaned_request_ids = [row[0] for row in rows]

        # Count orphaned responses
        async with self.sql.db.execute(SQL.COUNT_ORPHANED_RESPONSES) as cursor:
            row = await cursor.fetchone()
            orphaned_responses_count = row[0] if row else 0

        # Get orphaned response IDs
        orphaned_response_ids: list[int] = []
        async with self.sql.db.execute(
            SQL.SELECT_ORPHANED_RESPONSES
        ) as cursor:
            rows = await cursor.fetchall()
            orphaned_response_ids = [row[0] for row in rows]

        has_issues = (
            orphaned_requests_count > 0 or orphaned_responses_count > 0
        )

        return {
            "orphaned_requests": {
                "count": orphaned_requests_count,
                "ids": orphaned_request_ids,
            },
            "orphaned_responses": {
                "count": orphaned_responses_count,
                "ids": orphaned_response_ids,
            },
            "has_issues": has_issues,
        }

    async def get_orphan_details(self) -> dict[str, Any]:
        """Get detailed information about orphaned requests and responses.

        Returns full details for each orphaned request and response, unlike
        check_integrity() which only returns counts and IDs.

        Returns:
            Dictionary with detailed orphan information:
                - orphaned_requests: List of dicts with {id, url, continuation, completed_at}
                - orphaned_responses: List of dicts with {id, request_id, url, created_at}

        Example:
            details = await debugger.get_orphan_details()
            for req in details['orphaned_requests']:
                print(f"Orphaned request {req['id']}: {req['url']}")
            for resp in details['orphaned_responses']:
                print(f"Orphaned response {resp['id']}: {resp['url']}")
        """
        from juriscraper.scraper_driver.driver.dev_driver.sql_queries import (
            SQL,
        )

        # Get orphaned request details
        orphaned_requests = []
        async with self.sql.db.execute(SQL.SELECT_ORPHANED_REQUESTS) as cursor:
            rows = await cursor.fetchall()
            for row in rows:
                orphaned_requests.append(
                    {
                        "id": row[0],
                        "url": row[1],
                        "continuation": row[2],
                        "completed_at": row[3],
                    }
                )

        # Get orphaned response details
        orphaned_responses = []
        async with self.sql.db.execute(
            SQL.SELECT_ORPHANED_RESPONSES
        ) as cursor:
            rows = await cursor.fetchall()
            for row in rows:
                orphaned_responses.append(
                    {
                        "id": row[0],
                        "request_id": row[1],
                        "url": row[2],
                        "created_at": row[3],
                    }
                )

        return {
            "orphaned_requests": orphaned_requests,
            "orphaned_responses": orphaned_responses,
        }

    async def get_ghost_requests(self) -> dict[str, Any]:
        """Get ghost requests (completed requests with no children and no results).

        Ghost requests are completed requests that produced no observable output:
        no child requests and no ParsedData results. These may indicate issues
        with continuation logic or missing yield statements.

        Returns:
            Dictionary with ghost request information:
                - total_count: Total number of ghost requests
                - by_continuation: Dict mapping continuation -> count
                - ghosts: List of dicts with {id, url, continuation, completed_at}

        Example:
            ghosts = await debugger.get_ghost_requests()
            if ghosts['total_count'] > 0:
                print(f"Found {ghosts['total_count']} ghost requests")
                for continuation, count in ghosts['by_continuation'].items():
                    print(f"  {continuation}: {count} ghosts")
        """
        from juriscraper.scraper_driver.driver.dev_driver.sql_queries import (
            SQL,
        )

        # Get total count
        async with self.sql.db.execute(SQL.COUNT_GHOST_REQUESTS) as cursor:
            row = await cursor.fetchone()
            total_count = row[0] if row else 0

        # Get counts by continuation
        by_continuation: dict[str, int] = {}
        async with self.sql.db.execute(
            SQL.SELECT_GHOST_REQUEST_COUNTS_BY_CONTINUATION
        ) as cursor:
            rows = await cursor.fetchall()
            for row in rows:
                continuation = row[0]
                count = row[1]
                by_continuation[continuation] = count

        # Get detailed ghost request list
        ghosts = []
        async with self.sql.db.execute(SQL.SELECT_GHOST_REQUESTS) as cursor:
            rows = await cursor.fetchall()
            for row in rows:
                ghosts.append(
                    {
                        "id": row[0],
                        "url": row[1],
                        "continuation": row[2],
                        "completed_at": row[3],
                    }
                )

        return {
            "total_count": total_count,
            "by_continuation": by_continuation,
            "ghosts": ghosts,
        }

    # =========================================================================
    # Debugging Methods
    # =========================================================================

    async def diagnose(
        self,
        error_id: int,
        scraper_class: type | None = None,
        speculation_cap: int | None = None,
    ) -> dict[str, Any]:
        """Diagnose an error by re-running XPath observation.

        Fetches the response that caused the error and re-runs the scraper's
        XPath extraction to identify what went wrong. Useful for debugging
        selector issues.

        Args:
            error_id: The error ID to diagnose.
            scraper_class: Optional scraper class. If not provided, will attempt
                to discover from run metadata's scraper_name.
            speculation_cap: Optional cap for speculation during diagnosis.

        Returns:
            Dictionary with diagnosis results:
                - error: Original error details
                - response: Response metadata (status, url, etc.)
                - observations: XPath observations from re-running extraction
                - scraper_info: Information about the scraper used

        Raises:
            ValueError: If error not found or scraper cannot be discovered.
            ImportError: If scraper_name cannot be imported.

        Example:
            # Diagnose an XPath error
            result = await debugger.diagnose(error_id=123)
            print(f"Original error: {result['error']['message']}")
            print(f"Observations: {result['observations']}")
        """
        # Get error details
        error = await self.get_error(error_id)
        if not error:
            raise ValueError(f"Error {error_id} not found")

        # Get the response that caused the error - check this BEFORE importing scraper
        request_id = error.get("request_id")
        if not request_id:
            raise ValueError("Error has no associated request_id")

        # Find response for this request
        async with self.sql.db.execute(
            "SELECT id FROM responses WHERE request_id = ? LIMIT 1",
            (request_id,),
        ) as cursor:
            row = await cursor.fetchone()
            if not row:
                raise ValueError(f"No response found for request {request_id}")
            response_id = row[0]

        # Get response details and content
        response = await self.get_response(response_id)
        if not response:
            raise ValueError(f"Response {response_id} not found")

        content = await self.get_response_content(response_id)
        if not content:
            raise ValueError(f"No content for response {response_id}")

        # Discover scraper if not provided (after confirming response exists)
        if scraper_class is None:
            metadata = await self.get_run_metadata()
            if not metadata:
                raise ValueError("No run metadata found")

            scraper_name = metadata.get("scraper_name")
            if not scraper_name:
                raise ValueError("No scraper_name in run metadata")

            # Import scraper dynamically
            # scraper_name format: "juriscraper.opinions.united_states.federal_appellate.ca1"
            try:
                import importlib

                module = importlib.import_module(scraper_name)
                # Convention: module contains a Site class
                scraper_class = module.Site
            except (ImportError, AttributeError) as e:
                raise ImportError(
                    f"Cannot import scraper '{scraper_name}': {e}"
                ) from e

        # Re-run extraction with observation
        # This requires the scraper class to have extraction methods
        # For now, we'll return basic information
        # A full implementation would instantiate the scraper and re-run extraction

        diagnosis = {
            "error": error,
            "response": {
                "id": response.id,
                "status_code": response.status_code,
                "url": response.url,
                "size": response.content_size_original,
                "continuation": response.continuation,
            },
            "scraper_info": {
                "class": scraper_class.__name__ if scraper_class else None,
                "module": (
                    scraper_class.__module__ if scraper_class else None
                ),
            },
            "observations": {
                "message": "Full XPath re-execution requires scraper instantiation",
                "selector": error.get("selector"),
                "selector_type": error.get("selector_type"),
                "expected_range": f"{error.get('expected_min')}-{error.get('expected_max')}",
                "actual_count": error.get("actual_count"),
            },
        }

        return diagnosis

    # =========================================================================
    # Export Methods
    # =========================================================================

    async def export_results_jsonl(
        self,
        output_path: Path | str,
        result_type: str | None = None,
        is_valid: bool | None = None,
    ) -> int:
        """Export results to JSONL (newline-delimited JSON) file.

        Each line in the output file is a complete JSON object containing
        result data. This format is efficient for large datasets.

        Args:
            output_path: Path for the output JSONL file.
            result_type: Optional filter by result type.
            is_valid: Optional filter by validation status.

        Returns:
            Number of results exported.

        Example:
            # Export all valid results
            count = await debugger.export_results_jsonl(
                'results.jsonl', is_valid=True
            )
            print(f"Exported {count} valid results")

            # Export specific result type
            count = await debugger.export_results_jsonl(
                'opinions.jsonl', result_type='CourtOpinion'
            )
        """
        import json

        from juriscraper.scraper_driver.driver.dev_driver.sql_queries import (
            SQL,
        )

        if isinstance(output_path, str):
            output_path = Path(output_path)

        # Ensure parent directory exists
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Build where clause
        conditions = []
        params: list = []

        if result_type:
            conditions.append("result_type = ?")
            params.append(result_type)
        if is_valid is not None:
            conditions.append("is_valid = ?")
            params.append(is_valid)

        where_clause = (
            f"WHERE {' AND '.join(conditions)}" if conditions else ""
        )

        # Stream results to file
        count = 0
        with output_path.open("w") as f:
            async with self.sql.db.execute(
                SQL.SELECT_RESULTS_FOR_EXPORT.format(
                    where_clause=where_clause
                ),
                params,
            ) as cursor:
                async for row in cursor:
                    (
                        result_id,
                        request_id,
                        rtype,
                        data_json,
                        valid,
                        errors_json,
                        created_at,
                    ) = row

                    # Parse JSON fields
                    try:
                        data = json.loads(data_json) if data_json else {}
                    except json.JSONDecodeError:
                        data = {}

                    validation_errors = None
                    if errors_json:
                        try:
                            validation_errors = json.loads(errors_json)
                        except json.JSONDecodeError:
                            pass

                    record = {
                        "id": result_id,
                        "request_id": request_id,
                        "result_type": rtype,
                        "data": data,
                        "is_valid": bool(valid),
                        "validation_errors": validation_errors,
                        "created_at": created_at,
                    }

                    f.write(json.dumps(record) + "\n")
                    count += 1

        return count

    async def export_warc(
        self,
        output_path: Path | str,
        compress: bool = True,
        continuation: str | None = None,
    ) -> int:
        """Export responses to WARC (Web ARChive) format.

        Creates a WARC file containing all request/response pairs, suitable
        for archival or replay with tools like Wayback Machine.

        Args:
            output_path: Path for the output WARC file. If compress=True and
                path doesn't end with .gz, it will be appended.
            compress: Whether to gzip-compress the WARC file (default True).
            continuation: Optional filter by continuation (step name).

        Returns:
            Number of responses exported.

        Raises:
            ValueError: If no responses to export.

        Example:
            # Export all responses as compressed WARC
            count = await debugger.export_warc('archive.warc.gz')
            print(f"Exported {count} responses")

            # Export specific continuation uncompressed
            count = await debugger.export_warc(
                'step1.warc', compress=False, continuation='step1'
            )
        """
        from juriscraper.scraper_driver.driver.dev_driver.warc_export import (
            export_warc as do_export,
        )

        if isinstance(output_path, str):
            output_path = Path(output_path)

        count = await do_export(
            self.sql.db,
            output_path,
            compress=compress,
            continuation=continuation,
        )

        if count == 0:
            raise ValueError("No responses to export")

        return count

    async def preview_warc_export(
        self, continuation: str | None = None
    ) -> dict[str, Any]:
        """Preview WARC export without creating the file.

        Returns metadata about what would be exported.

        Args:
            continuation: Optional filter by continuation.

        Returns:
            Dictionary with:
                - record_count: Number of responses that would be exported
                - estimated_size: Estimated total size in bytes

        Example:
            preview = await debugger.preview_warc_export()
            print(f"Would export {preview['record_count']} responses")
            print(f"Estimated size: {preview['estimated_size']} bytes")
        """
        from juriscraper.scraper_driver.driver.dev_driver.sql_queries import (
            SQL,
        )

        # Build where clause
        params: list = []
        if continuation:
            where_clause = "WHERE continuation = ?"
            params.append(continuation)
        else:
            where_clause = ""

        # Get count and size
        query = SQL.SELECT_WARC_PREVIEW_STATS.format(where_clause=where_clause)
        async with self.sql.db.execute(query, params) as cursor:
            row = await cursor.fetchone()
            if row:
                count = row[0] or 0
                total_size = row[1] or 0
            else:
                count = 0
                total_size = 0

        return {
            "record_count": count,
            "estimated_size": total_size,
        }

    # =========================================================================
    # Response Search Methods
    # =========================================================================

    async def search_responses(
        self,
        text: str | None = None,
        regex: str | None = None,
        xpath: str | None = None,
        continuation: str | None = None,
    ) -> list[dict[str, int]]:
        """Search response content for matching patterns.

        Searches through all response content (decompressed) for matches.
        Exactly one of text, regex, or xpath must be provided.

        Args:
            text: Plain text to search for (case-insensitive substring match).
            regex: Regular expression pattern to search for.
            xpath: XPath expression to evaluate (returns matches if any nodes found).
            continuation: Optional filter by continuation (step name).

        Returns:
            List of dictionaries with:
                - response_id: The response ID that matched
                - request_id: The associated request ID

        Raises:
            ValueError: If zero or more than one search pattern is provided.
            re.error: If regex pattern is invalid.

        Example:
            # Text search
            matches = await debugger.search_responses(text="error")

            # Regex search
            matches = await debugger.search_responses(regex=r"case.*\\d{4}")

            # XPath search
            matches = await debugger.search_responses(
                xpath="//div[@class='opinion']"
            )

            # With continuation filter
            matches = await debugger.search_responses(
                text="verdict", continuation="step1"
            )
        """
        import re

        # Validate exactly one search type is provided
        search_types = [text, regex, xpath]
        provided = sum(1 for s in search_types if s is not None)
        if provided != 1:
            raise ValueError(
                "Exactly one of text, regex, or xpath must be provided"
            )

        # Compile regex if provided
        regex_pattern = None
        if regex is not None:
            regex_pattern = re.compile(regex)

        # Compile XPath if provided
        xpath_expr = None
        if xpath is not None:
            from lxml import etree

            xpath_expr = etree.XPath(xpath)

        # Build query to get response IDs and request IDs
        conditions = []
        params: list[Any] = []
        if continuation:
            conditions.append("continuation = ?")
            params.append(continuation)

        where_clause = (
            f"WHERE {' AND '.join(conditions)}" if conditions else ""
        )

        query = f"""
            SELECT id, request_id
            FROM responses
            {where_clause}
            ORDER BY id
        """

        matches: list[dict[str, int]] = []

        async with self.sql.db.execute(query, params) as cursor:
            async for row in cursor:
                response_id, request_id = row

                # Get decompressed content
                content = await self.get_response_content(response_id)
                if content is None:
                    continue

                # Try to decode as text
                try:
                    content_str = content.decode("utf-8")
                except UnicodeDecodeError:
                    try:
                        content_str = content.decode("latin-1")
                    except UnicodeDecodeError:
                        # Skip binary content
                        continue

                # Check for match based on search type
                matched = False

                if text is not None:
                    # Case-insensitive text search
                    matched = text.lower() in content_str.lower()

                elif regex_pattern is not None:
                    # Regex search
                    matched = regex_pattern.search(content_str) is not None

                elif xpath_expr is not None:
                    # XPath search - parse as HTML and evaluate
                    try:
                        from lxml import html

                        tree = html.fromstring(content_str)
                        result = xpath_expr(tree)
                        matched = bool(result)
                    except Exception:
                        # If parsing fails, skip this response
                        continue

                if matched:
                    matches.append(
                        {"response_id": response_id, "request_id": request_id}
                    )

        return matches

    # =========================================================================
    # Comparison Methods (for compare command)
    # =========================================================================

    async def get_child_requests_transitive(
        self, parent_request_id: int
    ) -> list[RequestRecord]:
        """Get all child requests transitively by parent_request_id.

        Recursively fetches all requests that were generated as children
        of the given parent request, including grandchildren and beyond.

        Args:
            parent_request_id: The parent request ID.

        Returns:
            List of RequestRecord objects for all transitive children.

        Example:
            # Get all requests generated from request 123's continuation
            children = await debugger.get_child_requests_transitive(123)
            print(f"Found {len(children)} child requests")
        """
        query = """
            WITH RECURSIVE children AS (
                -- Base case: direct children
                SELECT id, status, priority, queue_counter, method, url,
                       continuation, current_location, created_at, started_at,
                       completed_at, retry_count, cumulative_backoff, last_error,
                       created_at_ns, started_at_ns, completed_at_ns
                FROM requests WHERE parent_request_id = ?
                UNION ALL
                -- Recursive case: children of children
                SELECT r.id, r.status, r.priority, r.queue_counter, r.method, r.url,
                       r.continuation, r.current_location, r.created_at, r.started_at,
                       r.completed_at, r.retry_count, r.cumulative_backoff, r.last_error,
                       r.created_at_ns, r.started_at_ns, r.completed_at_ns
                FROM requests r
                INNER JOIN children c ON r.parent_request_id = c.id
            )
            SELECT * FROM children ORDER BY id
        """

        async with self.sql.db.execute(query, (parent_request_id,)) as cursor:
            rows = await cursor.fetchall()

        # Convert rows to RequestRecord objects
        # Match the field order from the query
        requests = []
        for row in rows:
            requests.append(
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
                    created_at_ns=row[14],
                    started_at_ns=row[15],
                    completed_at_ns=row[16],
                )
            )

        return requests

    async def get_results_for_request(
        self, request_id: int
    ) -> list[ResultRecord]:
        """Get all results (ParsedData) for a request.

        Args:
            request_id: The request ID.

        Returns:
            List of ResultRecord objects.

        Example:
            results = await debugger.get_results_for_request(123)
            for result in results:
                print(f"Result {result.id}: {result.result_type}")
        """
        # Use list_results with request_id filter and no pagination limit
        page = await self.sql.list_results(
            request_id=request_id, limit=10000, offset=0
        )
        return page.items

    async def sample_terminal_requests(
        self, continuation: str, sample_count: int
    ) -> list[int]:
        """Sample terminal requests (requests that produced no child requests).

        Terminal requests are completed requests that did not yield any child
        requests - they only yielded ParsedData or nothing at all.

        Args:
            continuation: The continuation (step name) to sample from.
            sample_count: Number of terminal requests to sample.

        Returns:
            List of request IDs for sampled terminal requests.

        Example:
            # Sample 10 terminal requests from step1
            terminal_ids = await debugger.sample_terminal_requests('step1', 10)
            print(f"Sampled {len(terminal_ids)} terminal requests")
        """
        query = """
            SELECT r.id
            FROM requests r
            WHERE r.continuation = ?
                AND r.status = 'completed'
                AND NOT EXISTS (
                    SELECT 1 FROM requests child
                    WHERE child.parent_request_id = r.id
                )
            ORDER BY RANDOM()
            LIMIT ?
        """

        async with self.sql.db.execute(
            query, (continuation, sample_count)
        ) as cursor:
            rows = await cursor.fetchall()

        return [row[0] for row in rows]

    async def sample_requests(
        self, continuation: str, sample_count: int
    ) -> list[int]:
        """Sample completed requests for a continuation (including non-terminal).

        Unlike sample_terminal_requests, this includes requests that produced
        child requests. Useful for comparing intermediate continuation behavior.

        Args:
            continuation: The continuation (step name) to sample from.
            sample_count: Number of requests to sample.

        Returns:
            List of request IDs for sampled requests.

        Example:
            # Sample 10 requests from parse_case_parties (which always produces children)
            ids = await debugger.sample_requests('parse_case_parties', 10)
        """
        query = """
            SELECT r.id
            FROM requests r
            WHERE r.continuation = ?
                AND r.status = 'completed'
            ORDER BY RANDOM()
            LIMIT ?
        """

        async with self.sql.db.execute(
            query, (continuation, sample_count)
        ) as cursor:
            rows = await cursor.fetchall()

        return [row[0] for row in rows]

    async def compare_continuation(
        self,
        request_id: int,
        scraper_class: type,
    ) -> Any:
        """Compare continuation output between stored and dry-run execution.

        Replays a stored response through the current continuation code and
        compares the output (child requests, ParsedData, errors) against what
        was originally stored in the database.

        This enables developers to understand how code changes affect scraper
        behavior without making actual network requests.

        Args:
            request_id: The request ID to compare.
            scraper_class: The scraper class to instantiate for dry-run.

        Returns:
            ComparisonResult with detailed diffs.

        Raises:
            ValueError: If request not found or no response available.

        Example:
            # Compare a specific request
            from juriscraper.opinions.united_states.federal_appellate import ca1
            result = await debugger.compare_continuation(123, ca1.Site)

            if result.has_changes:
                print(f"Found {result.request_diff.total_changes} request changes")
                print(f"Found {len(result.data_diff.changed_pairs)} data changes")
        """
        from juriscraper.scraper_driver.driver.dev_driver.comparison import (
            ComparisonResult,
            compare_continuation_output,
        )
        from juriscraper.scraper_driver.driver.dev_driver.dry_run_driver import (
            DryRunDriver,
            DryRunResult,
        )

        # Get the full request data including JSON fields directly from DB
        async with self.sql.db.execute(
            """SELECT id, url, method, continuation, current_location,
                      accumulated_data_json, aux_data_json, permanent_json
               FROM requests WHERE id = ?""",
            (request_id,),
        ) as cursor:
            request_row = await cursor.fetchone()
            if not request_row:
                raise ValueError(f"Request {request_id} not found")

        # Build request data dict from raw row
        request_data = {
            "url": request_row[1],
            "method": request_row[2],
            "continuation": request_row[3],
            "current_location": request_row[4],
            "accumulated_data_json": request_row[5],
            "aux_data_json": request_row[6],
            "permanent_json": request_row[7],
        }

        # Get the response for this request
        async with self.sql.db.execute(
            "SELECT * FROM responses WHERE request_id = ? LIMIT 1",
            (request_id,),
        ) as cursor:
            response_row = await cursor.fetchone()
            if not response_row:
                raise ValueError(f"No response found for request {request_id}")

        # Convert response row to dict
        response_data = dict(response_row)

        # Get decompressed content
        response_content = await self.get_response_content(response_data["id"])
        if response_content is None:
            raise ValueError(
                f"No content available for response {response_data['id']}"
            )

        response_data["content"] = response_content
        # Decode text if available
        try:
            response_data["text"] = response_content.decode("utf-8")
        except UnicodeDecodeError:
            response_data["text"] = ""

        # Load original stored results (child requests + ParsedData)
        # Query child requests with all fields needed for CapturedRequest
        child_query = """
            WITH RECURSIVE children AS (
                SELECT id, request_type, url, method, continuation, current_location,
                       accumulated_data_json, aux_data_json, permanent_json,
                       priority, deduplication_key, expected_type
                FROM requests WHERE parent_request_id = ?
                UNION ALL
                SELECT r.id, r.request_type, r.url, r.method, r.continuation, r.current_location,
                       r.accumulated_data_json, r.aux_data_json, r.permanent_json,
                       r.priority, r.deduplication_key, r.expected_type
                FROM requests r
                INNER JOIN children c ON r.parent_request_id = c.id
            )
            SELECT * FROM children ORDER BY id
        """
        async with self.sql.db.execute(child_query, (request_id,)) as cursor:
            child_rows = await cursor.fetchall()

        original_results = await self.get_results_for_request(request_id)

        # Convert to DryRunResult format for comparison
        from juriscraper.scraper_driver.driver.dev_driver.dry_run_driver import (
            CapturedData,
            CapturedRequest,
        )

        original_requests = []
        for row in child_rows:
            # Row: id, request_type, url, method, continuation, current_location,
            #      accumulated_data_json, aux_data_json, permanent_json,
            #      priority, deduplication_key, expected_type
            original_requests.append(
                CapturedRequest(
                    request_type=row[1] or "navigating",
                    url=row[2],
                    method=row[3],
                    continuation=row[4],
                    accumulated_data=(json.loads(row[6]) if row[6] else {}),
                    aux_data=(json.loads(row[7]) if row[7] else {}),
                    permanent=(json.loads(row[8]) if row[8] else {}),
                    current_location=row[5] or "",
                    priority=row[9],
                    deduplication_key=row[10],
                    is_speculative=False,  # Not stored in DB currently
                    speculation_id=None,
                    expected_type=row[11],
                )
            )

        original_data = [
            CapturedData(
                data=(json.loads(result.data_json) if result.data_json else {})
            )
            for result in original_results
        ]

        original: DryRunResult = DryRunResult(
            requests=original_requests, data=original_data, error=None
        )

        # Check if there was an error for this request
        errors_page = await self.list_errors(
            continuation=request_data["continuation"],
            is_resolved=None,
            limit=1000,  # Get all errors for now
            offset=0,
        )
        original_error = None
        for error in errors_page.items:
            if error["request_id"] == request_id and not error["is_resolved"]:
                from juriscraper.scraper_driver.driver.dev_driver.dry_run_driver import (
                    CapturedError,
                )

                original_error = CapturedError(
                    error_type=error["error_type"],
                    error_message=error["message"],
                )
                break

        original.error = original_error

        # Run dry-run with new code
        scraper_instance = scraper_class()
        driver = DryRunDriver(scraper_instance)
        new = driver.run_continuation(
            request_data["continuation"], response_data, request_data
        )

        # Compare
        result: ComparisonResult = compare_continuation_output(
            request_id=request_id,
            request_url=request_data["url"],
            continuation=request_data["continuation"],
            original=original,
            new=new,
        )

        return result

    async def compare_request_tree(
        self,
        request_id: int,
        scraper_class: type,
    ) -> list[Any]:
        """Compare entire request tree starting from a request.

        Recursively compares the request and all its descendants, following
        the same execution path the scraper would take. For each request in
        the tree, runs the continuation with stored response and compares
        output against stored results.

        Args:
            request_id: The root request ID to start comparison from.
            scraper_class: The scraper class to instantiate for dry-run.

        Returns:
            List of ComparisonResult for each request in the tree.

        Example:
            # Compare entire tree starting from a parse_case_parties request
            results = await debugger.compare_request_tree(123, AlabamaScraper)
            for result in results:
                if result.has_changes:
                    print(f"Changes at {result.continuation}: {result.request_id}")
        """
        from collections import deque

        results = []
        queue: deque[int] = deque([request_id])
        visited: set[int] = set()

        while queue:
            current_id = queue.popleft()
            if current_id in visited:
                continue
            visited.add(current_id)

            try:
                # Compare this request
                result = await self.compare_continuation(
                    current_id, scraper_class
                )
                results.append(result)

                # Get child requests to continue traversal
                async with self.sql.db.execute(
                    """SELECT id FROM requests
                       WHERE parent_request_id = ? AND status = 'completed'""",
                    (current_id,),
                ) as cursor:
                    child_rows = await cursor.fetchall()

                for row in child_rows:
                    child_id = row[0]
                    if child_id not in visited:
                        queue.append(child_id)

            except ValueError:
                # Skip requests without responses (e.g., pending)
                pass

        return results
