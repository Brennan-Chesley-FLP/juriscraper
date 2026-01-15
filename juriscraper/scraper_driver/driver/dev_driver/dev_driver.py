"""LocalDevDriver - SQLite-backed async driver for local development.

This driver extends AsyncDriver with persistent storage for:
- Request queue with resumability
- Response archival with compression
- Error tracking with requeue capability
- Progress events for web interface integration
"""

from __future__ import annotations

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Generic, Literal, TypeVar

import aiosqlite

from juriscraper.scraper_driver.data_types import (
    ArchiveRequest,
    BaseRequest,
    BaseScraper,
    HttpMethod,
    HTTPRequestParams,
    NavigatingRequest,
    NonNavigatingRequest,
    Response,
    ScraperYield,
    SpeculationContext,
    SpeculativeRequest,
)
from juriscraper.scraper_driver.driver.async_driver import AsyncDriver
from juriscraper.scraper_driver.driver.dev_driver.schema import (
    get_next_queue_counter,
    init_database,
)
from juriscraper.scraper_driver.driver.dev_driver.sql_queries import SQL
from juriscraper.scraper_driver.driver.dev_driver.stats import DevDriverStats

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable, Callable, Generator

    # Type alias for speculation response callback (async version)
    # Called when a SpeculativeRequest receives a non-2xx response
    # Returns True to continue (and optionally process continuation), False to stop
    OnSpeculationResponseAsync = Callable[[Response, str], Awaitable[bool]]

logger = logging.getLogger(__name__)

ScraperReturnDatatype = TypeVar("ScraperReturnDatatype")


@dataclass
class ProgressEvent:
    """Event emitted during driver execution for real-time updates.

    Attributes:
        event_type: Type of event (request_started, request_completed, etc.)
        timestamp: When the event occurred.
        data: Event-specific data.
    """

    event_type: str
    timestamp: datetime
    data: dict[str, Any]

    def to_json(self) -> str:
        """Serialize to JSON for WebSocket transport."""
        return json.dumps(
            {
                "event_type": self.event_type,
                "timestamp": self.timestamp.isoformat(),
                "data": self.data,
            }
        )


@dataclass
class DiagnoseResult:
    """Result of running diagnose() on a response.

    Contains the yields produced by re-running a continuation,
    XPath observation data, and any errors that occurred.

    Attributes:
        response_id: The database ID of the response that was diagnosed.
        continuation: The continuation method name that was run.
        yields: List of yielded items with type and key attributes.
        simple_tree: Human-readable XPath observation tree.
        observer_json: JSON for UI highlighting.
        error: Error message if continuation raised an exception.
    """

    response_id: int
    continuation: str
    yields: list[dict[str, Any]]
    simple_tree: str
    observer_json: list[dict[str, Any]]
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "response_id": self.response_id,
            "continuation": self.continuation,
            "yields": self.yields,
            "simple_tree": self.simple_tree,
            "observer_json": self.observer_json,
            "error": self.error,
        }

    def to_json(self) -> str:
        """Serialize to JSON for API transport."""
        return json.dumps(self.to_dict())


class LocalDevDriver(
    AsyncDriver[ScraperReturnDatatype], Generic[ScraperReturnDatatype]
):
    """SQLite-backed async driver for local development.

    Extends AsyncDriver with:
    - Persistent request queue in SQLite
    - Response archival with compression
    - Resumability from graceful shutdown
    - Progress events for web interface integration

    Args:
        scraper: The scraper instance to run.
        db_path: Path to SQLite database file.
        storage_dir: Directory for downloaded files.
        base_delay: Base rate limit delay in seconds (default: 10.0).
        jitter: Rate limit jitter in seconds (default: 2.0).
        num_workers: Number of concurrent workers (default: 1).
        resume: If True, resume from existing queue state (default: True).
        max_backoff_time: Maximum total backoff time before marking failed (default: 3600.0).

    Example:
        async with LocalDevDriver.open(scraper, db_path) as driver:
            driver.on_progress = lambda e: print(e.to_json())
            await driver.run()
    """

    def __init__(
        self,
        scraper: BaseScraper[ScraperReturnDatatype],
        db_path: Path,
        storage_dir: Path | None = None,
        base_delay: float = 10.0,
        jitter: float = 2.0,
        num_workers: int = 1,
        resume: bool = True,
        max_backoff_time: float = 3600.0,
        on_speculation_response: OnSpeculationResponseAsync | None = None,
    ) -> None:
        """Initialize the driver.

        Note: Use LocalDevDriver.open() for proper async initialization.

        Args:
            on_speculation_response: Optional async callback invoked when a SpeculativeRequest
                receives a non-2xx response. Receives (response, continuation_name) and should
                return True to resume the generator with True (continue speculation) or False to
                resume with False (stop speculation). Not called for 2xx responses.
        """
        # Initialize parent without interceptors - we'll add them after DB setup
        super().__init__(
            scraper=scraper,
            storage_dir=storage_dir,
            num_workers=num_workers,
        )

        self.db_path = db_path
        self.base_delay = base_delay
        self.jitter = jitter
        self.resume = resume
        self.max_backoff_time = max_backoff_time
        self.on_speculation_response = on_speculation_response

        # Database connection (set by _init_db)
        self._db: aiosqlite.Connection | None = None

        # Progress callback for web interface
        self.on_progress: Callable[[ProgressEvent], Awaitable[None]] | None = (
            None
        )

        # Stop event for graceful shutdown (always set, not optional like in parent)
        self.stop_event: asyncio.Event = asyncio.Event()

        # Parked generator storage for speculative requests
        # Maps unique speculation ID -> SpeculationContext
        # These are stored in memory since generators can't be serialized
        self._parked_generators: dict[str, SpeculationContext] = {}
        self._speculation_counter: int = 0

    @classmethod
    @asynccontextmanager
    async def open(
        cls,
        scraper: BaseScraper[ScraperReturnDatatype],
        db_path: Path,
        **kwargs: Any,
    ) -> AsyncIterator[LocalDevDriver[ScraperReturnDatatype]]:
        """Open driver as async context manager.

        Ensures proper initialization and cleanup of DB connections.

        Args:
            scraper: The scraper instance to run.
            db_path: Path to SQLite database file.
            **kwargs: Additional arguments passed to __init__.

        Yields:
            Initialized LocalDevDriver instance.

        Example:
            async with LocalDevDriver.open(scraper, db_path) as driver:
                await driver.run()
        """
        driver = cls(scraper, db_path, **kwargs)
        await driver._init_db()
        try:
            yield driver
        finally:
            await driver.close()

    async def _init_db(self) -> None:
        """Initialize database connection and schema."""
        self._db = await init_database(self.db_path)

        # Initialize or load run metadata
        await self._init_run_metadata()

        # If resuming, load pending requests from DB
        if self.resume:
            await self._restore_queue_from_db()

    async def _init_run_metadata(self) -> None:
        """Initialize or update run metadata in database."""
        assert self._db is not None

        # Check if run metadata exists
        cursor = await self._db.execute(SQL.SELECT_RUN_METADATA_BY_ID)
        row = await cursor.fetchone()

        if row is None:
            # Create initial run metadata
            scraper_name = self.scraper.__class__.__name__
            scraper_version = getattr(self.scraper, "__version__", None)

            await self._db.execute(
                SQL.INSERT_RUN_METADATA,
                (
                    scraper_name,
                    scraper_version,
                    self.base_delay,
                    self.jitter,
                    self.num_workers,
                    self.max_backoff_time,
                ),
            )
            await self._db.commit()

    async def _restore_queue_from_db(self) -> None:
        """Restore pending and in_progress requests to the queue.

        Called on startup when resume=True. Resets in_progress requests
        to pending status (they were interrupted).
        """
        assert self._db is not None

        # Reset any in_progress requests to pending (they were interrupted)
        await self._db.execute(SQL.RESET_IN_PROGRESS_TO_PENDING)
        await self._db.commit()

        # Count pending requests for logging
        cursor = await self._db.execute(SQL.COUNT_PENDING_REQUESTS)
        row = await cursor.fetchone()
        pending_count = row[0] if row else 0

        if pending_count > 0:
            logger.info(
                f"Restored {pending_count} pending requests from database"
            )

    async def close(self) -> None:
        """Close DB connections and clean up resources.

        On close, if there are any in_progress requests, reset them to pending
        so they can be resumed on next startup. Also mark run as interrupted
        if it was running.
        """
        if self._db:
            try:
                # Reset any in_progress requests to pending for resume
                await self._db.execute(SQL.RESET_IN_PROGRESS_TO_PENDING)

                # Update run status if we were running
                await self._db.execute(SQL.UPDATE_RUN_STATUS_ON_CLOSE)
                await self._db.commit()
            except Exception as e:
                logger.warning(f"Failed to update state on close: {e}")

            await self._db.close()
            self._db = None

    # --- Queue Operations (DB-backed) ---

    async def enqueue_request(
        self, new_request: BaseRequest, context: Response | BaseRequest
    ) -> None:
        """Enqueue a new request to the database.

        Overrides AsyncDriver.enqueue_request to persist to SQLite.

        For SpeculativeRequest with speculation_context:
        - Parks the generator in memory (generators can't be serialized)
        - Stores a speculation_id in the DB to link back to the parked generator
        - If deduplicated, enqueues a ResumeStep with False instead of dropping

        Args:
            new_request: The new request to enqueue.
            context: Response or originating request for URL resolution.
        """
        assert self._db is not None

        # Resolve the request from context
        resolved_request = new_request.resolve_from(context)  # type: ignore

        # Check for duplicates before inserting
        dedup_key = resolved_request.deduplication_key
        if dedup_key is not None and not isinstance(dedup_key, str):
            # SkipDeduplicationCheck - allow the request
            dedup_key = None

        if dedup_key:
            # Check if this dedup_key already exists
            cursor = await self._db.execute(
                SQL.SELECT_REQUEST_BY_DEDUP_KEY, (dedup_key,)
            )
            if await cursor.fetchone():
                # Duplicate found - for SpeculativeRequest, we still need to
                # resume the parked generator with False
                if (
                    isinstance(resolved_request, SpeculativeRequest)
                    and resolved_request.speculation_context
                ):
                    await self._enqueue_resume_step(
                        resolved_request.speculation_context, False
                    )
                return

        # Handle SpeculativeRequest with context - park the generator
        speculation_id: str | None = None
        if (
            isinstance(resolved_request, SpeculativeRequest)
            and resolved_request.speculation_context
        ):
            # Generate unique ID and park the generator
            self._speculation_counter += 1
            speculation_id = f"spec_{self._speculation_counter}"
            self._parked_generators[speculation_id] = (
                resolved_request.speculation_context
            )

        # Get next queue counter for FIFO ordering
        queue_counter = await get_next_queue_counter(self._db)

        # Serialize request data
        request_data = self._serialize_request(
            resolved_request, speculation_id
        )

        # Get parent request ID if context is a Response
        parent_id: int | None = None
        if isinstance(context, Response) and context.request:
            # Try to find the parent request in the DB
            parent_cursor = await self._db.execute(
                SQL.SELECT_PARENT_REQUEST_ID,
                (context.request.request.url,),
            )
            parent_row = await parent_cursor.fetchone()
            if parent_row:
                parent_id = parent_row[0]

        # Insert the request
        await self._db.execute(
            SQL.INSERT_REQUEST,
            (
                resolved_request.priority,
                queue_counter,
                request_data["request_type"],
                request_data["method"],
                request_data["url"],
                request_data["headers_json"],
                request_data["cookies_json"],
                request_data["body"],
                request_data["continuation"],
                request_data["current_location"],
                request_data["accumulated_data_json"],
                request_data["aux_data_json"],
                request_data["permanent_json"],
                request_data["expected_type"],
                dedup_key,
                parent_id,
            ),
        )
        await self._db.commit()

        # Emit progress event
        await self._emit_progress(
            "request_enqueued",
            {
                "url": request_data["url"],
                "continuation": request_data["continuation"],
                "priority": resolved_request.priority,
            },
        )

    async def _enqueue_resume_step(
        self, ctx: SpeculationContext, predicate_result: bool
    ) -> None:
        """Enqueue a ResumeStep to resume a parked generator.

        ResumeStep is an in-memory control flow marker, not a DB request.
        We store it in the parked_generators dict and enqueue a special
        request type that will trigger the resume.

        Args:
            ctx: The speculation context containing the parked generator.
            predicate_result: The value to send to the generator (True/False).
        """
        assert self._db is not None

        # Generate unique ID for this resume
        self._speculation_counter += 1
        resume_id = f"resume_{self._speculation_counter}"

        # Store the context with the result
        # We'll create a modified context that includes the predicate_result
        self._parked_generators[resume_id] = ctx

        # Get next queue counter
        queue_counter = await get_next_queue_counter(self._db)

        # Insert a special "resume" request type
        await self._db.execute(
            SQL.INSERT_REQUEST,
            (
                ctx.parent_request.priority,  # Inherit priority
                queue_counter,
                "resume",  # Special request type
                "GET",  # Dummy method
                "",  # Empty URL
                None,  # No headers
                None,  # No cookies
                None,  # No body
                ctx.originating_continuation,  # Store continuation for reference
                "",  # No current_location
                None,  # No accumulated_data
                None,  # No aux_data
                json.dumps(
                    {"predicate_result": predicate_result}
                ),  # Store result in permanent_json
                resume_id,  # Store resume_id in expected_type
                None,  # No dedup_key
                None,  # No parent_id
            ),
        )
        await self._db.commit()

    def _serialize_request(
        self, request: BaseRequest, speculation_id: str | None = None
    ) -> dict[str, Any]:
        """Serialize a BaseRequest to dictionary for DB storage.

        Args:
            request: The request to serialize.
            speculation_id: Optional ID for tracking parked generator (for SpeculativeRequest).

        Returns:
            Dictionary with serialized request data.
        """
        http_request = request.request

        # Get continuation name
        continuation = request.continuation
        if callable(continuation) and not isinstance(continuation, str):
            continuation = continuation.__name__

        # Determine request type and expected_type
        if isinstance(request, ArchiveRequest):
            request_type = "archive"
            expected_type = request.expected_type
        elif isinstance(request, SpeculativeRequest):
            request_type = "speculative"
            expected_type = (
                speculation_id  # Store speculation_id in expected_type field
            )
        elif isinstance(request, NonNavigatingRequest):
            request_type = "non_navigating"
            expected_type = None
        else:
            request_type = "navigating"
            expected_type = None

        return {
            "request_type": request_type,
            "method": http_request.method.value,
            "url": http_request.url,
            "headers_json": json.dumps(http_request.headers)
            if http_request.headers
            else None,
            "cookies_json": json.dumps(http_request.cookies)
            if http_request.cookies
            else None,
            "body": http_request.data
            if isinstance(http_request.data, bytes)
            else (
                json.dumps(http_request.data).encode()
                if http_request.data
                else None
            ),
            "continuation": continuation,
            "current_location": request.current_location,
            "accumulated_data_json": json.dumps(request.accumulated_data)
            if request.accumulated_data
            else None,
            "aux_data_json": json.dumps(request.aux_data)
            if request.aux_data
            else None,
            "permanent_json": json.dumps(request.permanent)
            if request.permanent
            else None,
            "expected_type": expected_type,
        }

    async def _get_next_request(
        self,
    ) -> tuple[int, BaseRequest | tuple[BaseRequest, str]] | None:
        """Get the next pending request from the database.

        Returns:
            Tuple of (request_id, deserialized) or None if queue is empty.
            deserialized is either a BaseRequest or a tuple of (request, speculation_id)
            for speculative/resume requests.

        Notes:
            - Skips 'held' status requests
            - Skips requests in retry backoff (started_at > current time)
        """
        assert self._db is not None

        # Get next pending request (ordered by priority, then queue_counter)
        # Skip 'held' status requests
        # Skip requests in retry backoff (started_at is used to track retry-after time)
        cursor = await self._db.execute(SQL.SELECT_NEXT_PENDING_REQUEST)
        row = await cursor.fetchone()

        if row is None:
            return None

        request_id = row[0]

        # Mark as in_progress
        await self._db.execute(SQL.UPDATE_REQUEST_IN_PROGRESS, (request_id,))
        await self._db.commit()

        # Deserialize and return
        request = self._deserialize_request(row)
        return (request_id, request)

    def _deserialize_request(
        self, row: tuple[Any, ...]
    ) -> BaseRequest | tuple[BaseRequest, str]:
        """Deserialize a database row to a BaseRequest.

        Args:
            row: Database row tuple from requests table.

        Returns:
            Reconstructed BaseRequest (NavigatingRequest, NonNavigatingRequest,
            ArchiveRequest, or SpeculativeRequest depending on request_type).
            For SpeculativeRequest, returns tuple of (request, speculation_id).
        """
        (
            _id,
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
            priority,
        ) = row

        # Parse JSON fields
        headers = json.loads(headers_json) if headers_json else None
        cookies = json.loads(cookies_json) if cookies_json else None
        accumulated_data = (
            json.loads(accumulated_data_json) if accumulated_data_json else {}
        )
        aux_data = json.loads(aux_data_json) if aux_data_json else {}
        permanent = json.loads(permanent_json) if permanent_json else {}

        # Decode body - if it's bytes that look like JSON, decode to dict
        # This handles form data that was serialized as JSON
        decoded_body: dict[str, Any] | bytes | None = None
        if body:
            if isinstance(body, bytes):
                try:
                    # Try to decode as JSON (form data case)
                    decoded_body = json.loads(body.decode("utf-8"))
                except (json.JSONDecodeError, UnicodeDecodeError):
                    # Keep as bytes (raw body case)
                    decoded_body = body
            else:
                decoded_body = body

        # Create HTTP request params
        http_params = HTTPRequestParams(
            method=HttpMethod(method),
            url=url,
            headers=headers,
            cookies=cookies,
            data=decoded_body,
        )

        # Create the appropriate request type
        if request_type == "archive":
            return ArchiveRequest(
                request=http_params,
                continuation=continuation,
                current_location=current_location,
                accumulated_data=accumulated_data,
                aux_data=aux_data,
                permanent=permanent,
                priority=priority,
                expected_type=expected_type,
            )
        elif request_type == "speculative":
            # expected_type stores the speculation_id
            speculation_id = expected_type
            spec_request = SpeculativeRequest(
                request=http_params,
                continuation=continuation,
                current_location=current_location,
                accumulated_data=accumulated_data,
                aux_data=aux_data,
                permanent=permanent,
                priority=priority,
            )
            return (spec_request, speculation_id)
        elif request_type == "resume":
            # Resume request - expected_type stores the resume_id
            # Return a dummy request with the resume_id
            resume_id = expected_type
            resume_request = NavigatingRequest(
                request=http_params,
                continuation=continuation,
                current_location=current_location,
                accumulated_data=accumulated_data,
                aux_data=aux_data,
                permanent=permanent,
                priority=priority,
            )
            return (resume_request, resume_id)
        elif request_type == "non_navigating":
            return NonNavigatingRequest(
                request=http_params,
                continuation=continuation,
                current_location=current_location,
                accumulated_data=accumulated_data,
                aux_data=aux_data,
                permanent=permanent,
                priority=priority,
            )
        else:  # navigating (default)
            return NavigatingRequest(
                request=http_params,
                continuation=continuation,
                current_location=current_location,
                accumulated_data=accumulated_data,
                aux_data=aux_data,
                permanent=permanent,
                priority=priority,
            )

    async def _mark_request_completed(self, request_id: int) -> None:
        """Mark a request as completed in the database.

        Args:
            request_id: The database ID of the request.
        """
        assert self._db is not None

        await self._db.execute(SQL.UPDATE_REQUEST_COMPLETED, (request_id,))
        await self._db.commit()

    async def _mark_request_failed(
        self, request_id: int, error_message: str
    ) -> None:
        """Mark a request as failed in the database.

        Args:
            request_id: The database ID of the request.
            error_message: Error message describing the failure.
        """
        assert self._db is not None

        await self._db.execute(
            SQL.UPDATE_REQUEST_FAILED, (error_message, request_id)
        )
        await self._db.commit()

    async def _handle_retry(self, request_id: int, error: Exception) -> bool:
        """Handle retry logic for transient errors with exponential backoff.

        Calculates the next retry delay using exponential backoff formula:
            next_retry_delay = base_delay * 2^retry_count

        Adds the delay to cumulative_backoff. If cumulative_backoff exceeds
        max_backoff_time, returns False to indicate the request should be
        marked as failed instead of retried.

        Args:
            request_id: The database ID of the request.
            error: The transient exception that was raised.

        Returns:
            True if the request should be retried, False if it should fail.
        """
        assert self._db is not None

        # Get current retry state
        cursor = await self._db.execute(SQL.SELECT_RETRY_STATE, (request_id,))
        row = await cursor.fetchone()
        if row is None:
            return False

        retry_count, cumulative_backoff = row
        cumulative_backoff = cumulative_backoff or 0.0

        # Calculate next retry delay with exponential backoff
        # Use a reasonable base delay (e.g., 1 second)
        retry_base_delay = 1.0
        next_retry_delay = retry_base_delay * (2**retry_count)

        # Cap individual retry delay at max_backoff_time / 4 to ensure
        # we don't have a single very long delay
        max_individual_delay = self.max_backoff_time / 4
        next_retry_delay = min(next_retry_delay, max_individual_delay)

        # Check if we would exceed max_backoff_time
        new_cumulative_backoff = cumulative_backoff + next_retry_delay
        if new_cumulative_backoff >= self.max_backoff_time:
            logger.warning(
                f"Request {request_id} exceeded max backoff time "
                f"({new_cumulative_backoff:.1f}s >= {self.max_backoff_time:.1f}s)"
            )
            return False

        # Schedule retry by resetting to pending with updated backoff tracking
        # We use started_at to store when the retry should happen
        # (current time + delay) - the worker will skip requests that aren't ready
        await self._db.execute(
            SQL.UPDATE_REQUEST_FOR_RETRY,
            (
                new_cumulative_backoff,
                next_retry_delay,
                str(error),
                int(next_retry_delay),
                request_id,
            ),
        )
        await self._db.commit()

        logger.info(
            f"Request {request_id} scheduled for retry #{retry_count + 1} "
            f"(delay: {next_retry_delay:.1f}s, cumulative: {new_cumulative_backoff:.1f}s)"
        )

        return True

    async def _store_response(
        self, request_id: int, response: Response, continuation: str
    ) -> int:
        """Store an HTTP response in the database with compression.

        Args:
            request_id: The database ID of the associated request.
            response: The Response object to store.
            continuation: The continuation method that will process this response.

        Returns:
            The database ID of the stored response.
        """
        assert self._db is not None
        import uuid

        from juriscraper.scraper_driver.driver.dev_driver.compression import (
            compress_response,
        )

        # Serialize headers
        headers_json = (
            json.dumps(response.headers) if response.headers else None
        )

        # Compress content using zstd (with dictionary if available)
        content = response.content or b""
        content_size_original = len(content)

        if content_size_original > 0:
            compressed, dict_id = await compress_response(
                self._db, content, continuation
            )
            content_size_compressed = len(compressed)
        else:
            compressed = b""
            dict_id = None
            content_size_compressed = 0

        # Generate WARC record ID for later export
        warc_record_id = str(uuid.uuid4())

        cursor = await self._db.execute(
            SQL.INSERT_RESPONSE,
            (
                request_id,
                response.status_code,
                headers_json,
                response.url,
                compressed,
                content_size_original,
                content_size_compressed,
                dict_id,
                continuation,
                warc_record_id,
            ),
        )
        await self._db.commit()

        response_id = cursor.lastrowid
        return response_id if response_id else 0

    async def _store_result(
        self,
        request_id: int,
        data: Any,
        is_valid: bool = True,
        validation_errors: list[dict[str, Any]] | None = None,
    ) -> int:
        """Store a scraped result in the database.

        Args:
            request_id: The database ID of the request that produced this result.
            data: The scraped data to store.
            is_valid: Whether the data passed validation.
            validation_errors: List of validation errors if invalid.

        Returns:
            The database ID of the stored result.
        """
        assert self._db is not None

        # Get the type name
        result_type = type(data).__name__

        # Serialize the data
        if hasattr(data, "model_dump"):
            # Pydantic model - use mode='json' to serialize dates to ISO8601
            data_json = json.dumps(data.model_dump(mode="json"))
        elif hasattr(data, "dict"):
            # Older Pydantic
            data_json = json.dumps(data.dict())
        else:
            # Try direct serialization
            data_json = json.dumps(data)

        # Serialize validation errors, handling non-serializable objects
        validation_errors_json = None
        if validation_errors:

            def make_serializable(obj: Any) -> Any:
                """Convert non-JSON-serializable objects to strings."""
                if isinstance(obj, dict):
                    return {k: make_serializable(v) for k, v in obj.items()}
                if isinstance(obj, list):
                    return [make_serializable(item) for item in obj]
                if isinstance(obj, tuple):
                    return [make_serializable(item) for item in obj]
                if isinstance(obj, Exception):
                    return str(obj)
                try:
                    json.dumps(obj)
                    return obj
                except (TypeError, ValueError):
                    return str(obj)

            validation_errors_json = json.dumps(
                make_serializable(validation_errors)
            )

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

        result_id = cursor.lastrowid
        return result_id if result_id else 0

    # --- Progress Events ---

    async def _emit_progress(
        self, event_type: str, data: dict[str, Any]
    ) -> None:
        """Emit a progress event if callback is registered.

        Args:
            event_type: Type of event.
            data: Event-specific data.
        """
        if self.on_progress:
            event = ProgressEvent(
                event_type=event_type,
                timestamp=datetime.now(timezone.utc),
                data=data,
            )
            await self.on_progress(event)

    # --- Signal Handlers ---

    def _setup_signal_handlers(self) -> None:
        """Register signal handlers for graceful shutdown.

        Registers handlers for SIGINT (Ctrl+C) and SIGTERM that will
        set the stop_event, causing workers to finish their current
        request and exit gracefully.

        Note: Only works on Unix-like systems. On Windows, only SIGINT
        is supported.
        """
        import signal

        def handle_signal(signum: int, frame: Any) -> None:
            sig_name = signal.Signals(signum).name
            logger.info(
                f"Received {sig_name}, initiating graceful shutdown..."
            )
            self.stop()

        # Register handlers
        signal.signal(signal.SIGINT, handle_signal)
        signal.signal(signal.SIGTERM, handle_signal)

    def _restore_signal_handlers(self) -> None:
        """Restore default signal handlers.

        Should be called after run() completes to avoid leaving
        custom handlers in place.
        """
        import signal

        signal.signal(signal.SIGINT, signal.SIG_DFL)
        signal.signal(signal.SIGTERM, signal.SIG_DFL)

    # --- Run Override ---

    async def run(self, setup_signal_handlers: bool = True) -> None:
        """Run the scraper, using DB-backed queue.

        Overrides AsyncDriver.run() to use database queue operations.

        Args:
            setup_signal_handlers: If True, register SIGINT/SIGTERM handlers
                for graceful shutdown. Set to False when running in a context
                that manages its own signal handling (e.g., FastAPI).
        """
        assert self._db is not None

        if setup_signal_handlers:
            self._setup_signal_handlers()

        # Update run status to running
        await self._db.execute(SQL.UPDATE_RUN_STATUS_RUNNING)
        await self._db.commit()

        await self._emit_progress(
            "run_started",
            {
                "scraper_name": self.scraper.__class__.__name__,
            },
        )

        status = "completed"
        error: Exception | None = None

        try:
            # Check for early stop before doing any work
            if self.stop_event.is_set():
                return

            # Check if we need to seed the queue with entry point
            cursor = await self._db.execute(SQL.COUNT_ALL_REQUESTS)
            row = await cursor.fetchone()
            has_requests = row[0] > 0 if row else False

            if not has_requests:
                # Seed queue with entry points from get_entry generator
                for entry_request in self.scraper.get_entry():
                    queue_counter = await get_next_queue_counter(self._db)
                    request_data = self._serialize_request(entry_request)

                    await self._db.execute(
                        SQL.INSERT_ENTRY_REQUEST,
                        (
                            entry_request.priority,
                            queue_counter,
                            request_data["method"],
                            request_data["url"],
                            request_data["headers_json"],
                            request_data["cookies_json"],
                            request_data["body"],
                            request_data["continuation"],
                            request_data["current_location"],
                            request_data["accumulated_data_json"],
                            request_data["aux_data_json"],
                            request_data["permanent_json"],
                            entry_request.deduplication_key
                            if isinstance(entry_request.deduplication_key, str)
                            else None,
                        ),
                    )
                await self._db.commit()

            # Start workers
            workers = [
                asyncio.create_task(self._db_worker(i))
                for i in range(self.num_workers)
            ]

            # Wait for all workers to complete
            # Workers exit when queue is empty or stop_event is set
            await asyncio.gather(*workers, return_exceptions=True)

        except Exception as e:
            status = "error"
            error = e
            raise
        finally:
            # Restore signal handlers if we set them up
            if setup_signal_handlers:
                self._restore_signal_handlers()

            # Update run metadata
            final_status = (
                "interrupted" if self.stop_event.is_set() else status
            )
            await self._db.execute(
                SQL.UPDATE_RUN_STATUS_FINAL,
                (final_status, str(error) if error else None),
            )
            await self._db.commit()

            await self._emit_progress(
                "run_completed",
                {
                    "scraper_name": self.scraper.__class__.__name__,
                    "status": final_status,
                    "error": str(error) if error else None,
                },
            )

    async def _db_worker(self, worker_id: int) -> None:
        """Worker that processes requests from the database queue.

        Handles:
        - Regular requests (NavigatingRequest, NonNavigatingRequest, ArchiveRequest)
        - SpeculativeRequest: execute HTTP, determine success, enqueue resume, call continuation
        - ResumeStep: resume parked generator with True/False

        Args:
            worker_id: Identifier for this worker.
        """
        while True:
            # Check for graceful shutdown
            if self.stop_event.is_set():
                break

            # Get next request from DB
            result = await self._get_next_request()
            if result is None:
                # Queue is empty - check if we should wait or exit
                # Small delay to avoid busy-waiting
                await asyncio.sleep(0.1)

                # Check again - if still empty, exit
                result = await self._get_next_request()
                if result is None:
                    break

            request_id, deserialized = result

            # Handle tuple return for SpeculativeRequest
            speculation_id: str | None = None
            if isinstance(deserialized, tuple):
                request, speculation_id = deserialized
            else:
                request = deserialized

            try:
                # Check for ResumeStep (stored as "resume" request type)
                # This is detected by checking the request type in the DB row
                # Since _deserialize_request returns the row data, we need to check
                # if this is a resume by looking at speculation_id pattern
                if speculation_id and speculation_id.startswith("resume_"):
                    await self._execute_resume_with_storage(
                        request_id, speculation_id
                    )
                    continue

                await self._emit_progress(
                    "request_started",
                    {
                        "request_id": request_id,
                        "url": request.request.url,
                        "continuation": request.continuation,
                    },
                )

                # Get continuation name
                continuation_name = (
                    request.continuation
                    if isinstance(request.continuation, str)
                    else request.continuation.__name__
                )

                # Handle SpeculativeRequest with parked generator
                if speculation_id and speculation_id.startswith("spec_"):
                    await self._resolve_speculative_with_storage(
                        request_id, request, speculation_id, continuation_name
                    )
                    continue

                # Regular request flow
                await self._process_regular_request(
                    request_id, request, continuation_name
                )

            except Exception as e:
                logger.exception(
                    f"Worker {worker_id} error processing request {request_id}"
                )

                # Check if this is a transient error that should be retried
                from juriscraper.scraper_driver.common.exceptions import (
                    TransientException,
                )

                if isinstance(e, TransientException):
                    # Handle retry with exponential backoff
                    should_retry = await self._handle_retry(request_id, e)
                    if should_retry:
                        await self._emit_progress(
                            "request_retry_scheduled",
                            {
                                "request_id": request_id,
                                "url": request.request.url,
                                "error": str(e),
                                "error_type": type(e).__name__,
                            },
                        )
                        continue  # Don't store as error, will be retried

                # Non-transient error or max backoff exceeded - mark as failed
                await self._mark_request_failed(request_id, str(e))

                # Store error in database for tracking and requeue
                from juriscraper.scraper_driver.driver.dev_driver.errors import (
                    store_error,
                )

                await store_error(
                    self._db,
                    e,
                    request_id=request_id,
                    request_url=request.request.url,
                )

                await self._emit_progress(
                    "request_failed",
                    {
                        "request_id": request_id,
                        "url": request.request.url,
                        "error": str(e),
                        "error_type": type(e).__name__,
                    },
                )

    async def _process_regular_request(
        self,
        request_id: int,
        request: BaseRequest,
        continuation_name: str,
    ) -> None:
        """Process a regular (non-speculative, non-resume) request.

        Args:
            request_id: Database ID of the request.
            request: The request to process.
            continuation_name: Name of the continuation method.
        """
        # Process the request using parent class methods
        # For ArchiveRequest, resolve_archive_request returns ArchiveResponse
        # which is a subclass of Response with a file_url field
        from juriscraper.scraper_driver.data_types import ArchiveResponse

        response: Response = (
            await self.resolve_archive_request(request)
            if isinstance(request, ArchiveRequest)
            else await self.resolve_request(request)
        )

        # Verify ArchiveResponse for ArchiveRequest
        if isinstance(request, ArchiveRequest) and not isinstance(
            response, ArchiveResponse
        ):
            logger.error(
                f"Expected ArchiveResponse for ArchiveRequest, got {type(response)}"
            )

        # Store the response in the database
        await self._store_response(request_id, response, continuation_name)

        # Get continuation method and process generator
        continuation_method = self.scraper.get_continuation(continuation_name)
        gen = continuation_method(response)

        await self._process_generator_with_storage(
            gen, response, request, continuation_name, request_id
        )

        # Mark completed
        await self._mark_request_completed(request_id)

        await self._emit_progress(
            "request_completed",
            {
                "request_id": request_id,
                "url": request.request.url,
            },
        )

    async def _process_generator_with_storage(
        self,
        gen: Generator[ScraperYield, bool | None, None],
        response: Response,
        parent_request: BaseRequest,
        continuation_name: str,
        request_id: int,
    ) -> None:
        """Process generator with DB storage, parking on SpeculativeRequest.

        Uses simple iteration (for item in gen). Values are only sent to
        generators via _execute_resume() when processing a ResumeStep.

        Args:
            gen: The generator from the continuation method.
            response: The Response that triggered this continuation.
            parent_request: The request that initiated this continuation.
            continuation_name: Name of the continuation method.
            request_id: Database ID for result storage.
        """
        from juriscraper.scraper_driver.common.deferred_validation import (
            DeferredValidation,
        )
        from juriscraper.scraper_driver.common.exceptions import (
            DataFormatAssumptionException,
            HTMLStructuralAssumptionException,
        )
        from juriscraper.scraper_driver.data_types import ParsedData

        try:
            for item in gen:
                match item:
                    case SpeculativeRequest():
                        # Park the generator and enqueue with context
                        ctx = SpeculationContext(
                            parked_generator=gen,
                            parent_request=parent_request,
                            original_response=response,
                            originating_continuation=continuation_name,
                        )
                        await self.enqueue_request(
                            item.with_context(ctx), response
                        )
                        return  # Generator parked - stop processing

                    case ParsedData():
                        raw_data = item.unwrap()
                        # Handle deferred validation
                        if isinstance(raw_data, DeferredValidation):
                            try:
                                validated_data = raw_data.confirm()
                                await self._store_result(
                                    request_id, validated_data
                                )
                                await self.handle_data(validated_data)
                            except DataFormatAssumptionException as e:
                                await self._store_result(
                                    request_id,
                                    e.failed_doc,
                                    is_valid=False,
                                    validation_errors=e.errors,
                                )
                                if self.on_invalid_data:
                                    await self.on_invalid_data(raw_data)
                        else:
                            await self._store_result(request_id, raw_data)
                            await self.handle_data(raw_data)

                    case NavigatingRequest():
                        await self.enqueue_request(item, response)

                    case NonNavigatingRequest() | ArchiveRequest():
                        await self.enqueue_request(item, parent_request)

                    case None:
                        pass

        except HTMLStructuralAssumptionException as e:
            if self.on_structural_error:
                should_continue = await self.on_structural_error(e)
                if not should_continue:
                    return
            else:
                raise

    async def _resolve_speculative_with_storage(
        self,
        request_id: int,
        request: BaseRequest,
        speculation_id: str,
        continuation_name: str,
    ) -> None:
        """Execute speculative request with DB storage, determine success, enqueue resume.

        Flow:
        - 2xx response: always success (True), call continuation
        - Non-2xx response: call on_speculation_response callback to decide

        Args:
            request_id: Database ID of the request.
            request: The SpeculativeRequest to process.
            speculation_id: ID linking to the parked generator.
            continuation_name: Name of the continuation method.
        """
        from juriscraper.scraper_driver.common.exceptions import (
            TransientException,
        )

        # Get the parked generator context
        ctx = self._parked_generators.get(speculation_id)
        if ctx is None:
            logger.warning(
                f"Speculation context {speculation_id} not found - "
                "generator may have been lost on restart"
            )
            await self._mark_request_completed(request_id)
            return

        # Execute HTTP request
        try:
            response = await self.resolve_request(request)
        except TransientException as e:
            if self.on_transient_exception:
                should_continue = await self.on_transient_exception(e)
                if not should_continue:
                    # Clean up parked generator
                    del self._parked_generators[speculation_id]
                    await self._mark_request_failed(request_id, str(e))
                    return
                # Enqueue resume with False - transient error means don't continue
                await self._enqueue_resume_step(ctx, False)
                del self._parked_generators[speculation_id]
                await self._mark_request_completed(request_id)
                return
            else:
                raise

        # Store response
        await self._store_response(request_id, response, continuation_name)

        # Determine success based on status code
        is_success_status = 200 <= response.status_code < 300

        if is_success_status:
            # 2xx response: always continue
            should_continue = True
        elif self.on_speculation_response:
            # Non-2xx: let callback decide
            should_continue = await self.on_speculation_response(
                response, continuation_name
            )
        else:
            # Non-2xx with no callback: don't continue
            should_continue = False

        # Enqueue ResumeStep FIRST (before processing continuation)
        await self._enqueue_resume_step(ctx, should_continue)

        # Clean up parked generator reference (it's now tracked by resume_id)
        del self._parked_generators[speculation_id]

        # THEN process continuation if approved AND response was successful
        if should_continue and is_success_status:
            continuation = self.scraper.get_continuation(continuation_name)
            gen = continuation(response)
            await self._process_generator_with_storage(
                gen, response, request, continuation_name, request_id
            )

        await self._mark_request_completed(request_id)
        await self._emit_progress(
            "request_completed",
            {
                "request_id": request_id,
                "url": request.request.url,
            },
        )

    async def _execute_resume_with_storage(
        self, request_id: int, resume_id: str
    ) -> None:
        """Execute a ResumeStep: resume the parked generator with the result.

        Args:
            request_id: Database ID of the resume request.
            resume_id: ID linking to the parked generator.
        """
        assert self._db is not None

        # Get the parked generator context
        ctx = self._parked_generators.get(resume_id)
        if ctx is None:
            logger.warning(
                f"Resume context {resume_id} not found - "
                "generator may have been lost on restart"
            )
            await self._mark_request_completed(request_id)
            return

        # Get the predicate_result from the DB (stored in permanent_json)
        cursor = await self._db.execute(
            "SELECT permanent_json FROM requests WHERE id = ?", (request_id,)
        )
        row = await cursor.fetchone()
        if row and row[0]:
            data = json.loads(row[0])
            predicate_result = data.get("predicate_result", False)
        else:
            predicate_result = False

        # Clean up
        del self._parked_generators[resume_id]

        gen = ctx.parked_generator
        response = ctx.original_response
        parent_request = ctx.parent_request
        continuation_name = ctx.originating_continuation

        # Send the value and continue processing remaining yields
        try:
            item = gen.send(predicate_result)
        except StopIteration:
            await self._mark_request_completed(request_id)
            return

        # Handle the first item after resume, then loop for rest
        await self._handle_yield_and_continue_with_storage(
            gen, item, response, parent_request, continuation_name, request_id
        )

        await self._mark_request_completed(request_id)

    async def _handle_yield_and_continue_with_storage(
        self,
        gen: Generator[ScraperYield, bool | None, None],
        item: ScraperYield,
        response: Response,
        parent_request: BaseRequest,
        continuation_name: str,
        request_id: int,
    ) -> None:
        """Handle a yield and continue processing the generator with DB storage.

        Called after _execute_resume_with_storage sends a value. Processes the
        first yielded item, then continues with simple iteration for remaining items.

        Args:
            gen: The generator to continue processing.
            item: The first item yielded after send().
            response: The original response for context.
            parent_request: The parent request for context.
            continuation_name: The continuation name for context.
            request_id: Database ID for result storage.
        """
        from juriscraper.scraper_driver.common.deferred_validation import (
            DeferredValidation,
        )
        from juriscraper.scraper_driver.common.exceptions import (
            DataFormatAssumptionException,
            HTMLStructuralAssumptionException,
        )
        from juriscraper.scraper_driver.data_types import ParsedData

        try:
            while True:
                match item:
                    case SpeculativeRequest():
                        # Park again
                        ctx = SpeculationContext(
                            parked_generator=gen,
                            parent_request=parent_request,
                            original_response=response,
                            originating_continuation=continuation_name,
                        )
                        await self.enqueue_request(
                            item.with_context(ctx), response
                        )
                        return

                    case ParsedData():
                        raw_data = item.unwrap()
                        if isinstance(raw_data, DeferredValidation):
                            try:
                                validated_data = raw_data.confirm()
                                await self._store_result(
                                    request_id, validated_data
                                )
                                await self.handle_data(validated_data)
                            except DataFormatAssumptionException as e:
                                await self._store_result(
                                    request_id,
                                    e.failed_doc,
                                    is_valid=False,
                                    validation_errors=e.errors,
                                )
                                if self.on_invalid_data:
                                    await self.on_invalid_data(raw_data)
                        else:
                            await self._store_result(request_id, raw_data)
                            await self.handle_data(raw_data)

                    case NavigatingRequest():
                        await self.enqueue_request(item, response)

                    case NonNavigatingRequest() | ArchiveRequest():
                        await self.enqueue_request(item, parent_request)

                    case None:
                        pass

                try:
                    item = next(gen)  # Simple iteration after the initial send
                except StopIteration:
                    break

        except HTMLStructuralAssumptionException as e:
            if self.on_structural_error:
                should_continue = await self.on_structural_error(e)
                if not should_continue:
                    return
            else:
                raise

    # --- Status ---

    async def status(self) -> Literal["unstarted", "in_progress", "done"]:
        """Check the current state of the scraper run.

        Returns:
            - "unstarted": No requests in DB
            - "in_progress": Pending or in_progress requests exist
            - "done": No pending/in_progress but completed requests exist
        """
        assert self._db is not None

        # Check for pending/in_progress requests
        cursor = await self._db.execute(SQL.COUNT_ACTIVE_REQUESTS)
        row = await cursor.fetchone()
        active_count = row[0] if row else 0

        if active_count > 0:
            return "in_progress"

        # Check for any requests at all
        cursor = await self._db.execute(SQL.COUNT_ALL_REQUESTS)
        row = await cursor.fetchone()
        total_count = row[0] if row else 0

        if total_count == 0:
            return "unstarted"

        return "done"

    def stop(self) -> None:
        """Signal workers to stop after completing their current request."""
        self.stop_event.set()

    # --- Step Control ---

    async def pause_step(self, continuation: str) -> int:
        """Pause processing of requests for a specific continuation.

        Marks all pending requests for the given continuation as 'held'.
        Held requests are not picked up by workers but remain in the queue
        for later resume. Useful for temporarily stopping a problematic step
        while continuing to process other parts of the scraper.

        Args:
            continuation: The continuation method name to pause.

        Returns:
            Number of requests marked as held.
        """
        assert self._db is not None

        cursor = await self._db.execute(SQL.UPDATE_PAUSE_STEP, (continuation,))
        await self._db.commit()

        count = cursor.rowcount
        if count > 0:
            await self._emit_progress(
                "step_paused",
                {
                    "continuation": continuation,
                    "requests_held": count,
                },
            )

        return count

    async def resume_step(self, continuation: str) -> int:
        """Resume processing of held requests for a specific continuation.

        Marks all held requests for the given continuation as 'pending',
        making them available for workers to process again.

        Args:
            continuation: The continuation method name to resume.

        Returns:
            Number of requests restored to pending.
        """
        assert self._db is not None

        cursor = await self._db.execute(
            SQL.UPDATE_RESUME_STEP, (continuation,)
        )
        await self._db.commit()

        count = cursor.rowcount
        if count > 0:
            await self._emit_progress(
                "step_resumed",
                {
                    "continuation": continuation,
                    "requests_restored": count,
                },
            )

        return count

    async def get_held_count(self, continuation: str | None = None) -> int:
        """Get count of held requests, optionally filtered by continuation.

        Args:
            continuation: Optional continuation name to filter by.

        Returns:
            Count of held requests.
        """
        assert self._db is not None

        if continuation:
            cursor = await self._db.execute(
                SQL.COUNT_HELD_BY_CONTINUATION, (continuation,)
            )
        else:
            cursor = await self._db.execute(SQL.COUNT_ALL_HELD)

        row = await cursor.fetchone()
        return row[0] if row else 0

    # --- Error Requeue Methods ---

    async def requeue_request(self, error_id: int) -> int | None:
        """Recreate a pending request from an error's associated request.

        Finds the original request that caused the error and creates a new
        pending request with the same parameters. The error is marked as
        resolved with a note indicating it was requeued.

        This is useful after fixing scraper code to retry a failed request.

        Args:
            error_id: The database ID of the error to requeue.

        Returns:
            The database ID of the new pending request, or None if the error
            has no associated request or was already resolved.
        """
        assert self._db is not None

        # Get the error and its associated request_id
        cursor = await self._db.execute(
            SQL.SELECT_ERROR_WITH_REQUEST, (error_id,)
        )
        row = await cursor.fetchone()

        if row is None:
            logger.warning(f"Error {error_id} not found")
            return None

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
            logger.warning(f"Error {error_id} is already resolved")
            return None

        if request_id is None:
            logger.warning(f"Error {error_id} has no associated request")
            return None

        # Create a new pending request with the same parameters
        queue_counter = await get_next_queue_counter(self._db)

        cursor = await self._db.execute(
            SQL.INSERT_REQUEUE_REQUEST,
            (
                priority or 9,
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
                request_id,  # Link to original request
            ),
        )

        new_request_id = cursor.lastrowid

        # Mark the error as resolved
        from juriscraper.scraper_driver.driver.dev_driver.errors import (
            resolve_error,
        )

        await resolve_error(
            self._db, error_id, notes=f"Requeued as request {new_request_id}"
        )

        await self._emit_progress(
            "error_requeued",
            {
                "error_id": error_id,
                "new_request_id": new_request_id,
                "url": url,
                "continuation": continuation,
            },
        )

        return new_request_id

    async def requeue_errors_by_type(
        self,
        error_type: str | None = None,
        continuation: str | None = None,
    ) -> list[int]:
        """Batch requeue errors matching the given filters.

        Finds all unresolved errors matching the filters and creates new
        pending requests for each one. All matching errors are marked as
        resolved.

        This is useful after fixing scraper code to retry all errors of
        a particular type or for a specific continuation.

        Args:
            error_type: Filter by error type (structural, validation, transient).
            continuation: Filter by continuation method name.

        Returns:
            List of new request IDs created.
        """
        assert self._db is not None

        # Build query to find matching errors with their requests
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
        rows = await cursor.fetchall()

        if not rows:
            return []

        new_request_ids: list[int] = []
        from juriscraper.scraper_driver.driver.dev_driver.errors import (
            resolve_error,
        )

        for row in rows:
            (
                error_id,
                request_id,
                method,
                url,
                headers_json,
                cookies_json,
                body,
                cont,
                current_location,
                accumulated_data_json,
                aux_data_json,
                permanent_json,
                priority,
            ) = row

            # Create a new pending request
            queue_counter = await get_next_queue_counter(self._db)

            insert_cursor = await self._db.execute(
                SQL.INSERT_REQUEUE_REQUEST,
                (
                    priority or 9,
                    queue_counter,
                    method,
                    url,
                    headers_json,
                    cookies_json,
                    body,
                    cont,
                    current_location,
                    accumulated_data_json,
                    aux_data_json,
                    permanent_json,
                    request_id,
                ),
            )

            new_request_id = insert_cursor.lastrowid
            if new_request_id:
                new_request_ids.append(new_request_id)

                # Mark the error as resolved
                await resolve_error(
                    self._db,
                    error_id,
                    notes=f"Batch requeued as request {new_request_id}",
                )

        await self._db.commit()

        await self._emit_progress(
            "errors_batch_requeued",
            {
                "error_type": error_type,
                "continuation": continuation,
                "count": len(new_request_ids),
                "new_request_ids": new_request_ids,
            },
        )

        return new_request_ids

    # --- Response Content Access ---

    async def get_response_content(self, response_id: int) -> bytes | None:
        """Get decompressed response content by response ID.

        Args:
            response_id: The database ID of the response.

        Returns:
            Decompressed content bytes, or None if response not found.
        """
        assert self._db is not None

        from juriscraper.scraper_driver.driver.dev_driver.compression import (
            decompress_response,
        )

        cursor = await self._db.execute(
            SQL.SELECT_RESPONSE_COMPRESSED, (response_id,)
        )
        row = await cursor.fetchone()

        if row is None:
            return None

        compressed, dict_id = row

        if not compressed:
            return b""

        return await decompress_response(self._db, compressed, dict_id)

    # --- Statistics ---

    async def get_stats(self) -> DevDriverStats:
        """Get comprehensive statistics about the driver state.

        Returns:
            DevDriverStats instance with queue, throughput, compression,
            result, and error statistics.
        """
        assert self._db is not None

        from juriscraper.scraper_driver.driver.dev_driver.stats import (
            get_stats,
        )

        return await get_stats(self._db)

    # --- WARC Export ---

    async def export_warc(
        self,
        output_path: Path,
        compress: bool = True,
        continuation: str | None = None,
    ) -> int:
        """Export stored responses to WARC file.

        Args:
            output_path: Path for output WARC file.
            compress: Whether to gzip-compress the WARC file.
            continuation: If specified, only export responses for this
                continuation method.

        Returns:
            Number of responses exported.
        """
        assert self._db is not None

        from juriscraper.scraper_driver.driver.dev_driver.warc_export import (
            export_warc,
            export_warc_for_continuation,
        )

        if continuation:
            return await export_warc_for_continuation(
                self._db, continuation, output_path, compress
            )
        else:
            return await export_warc(self._db, output_path, compress)

    # --- Debugging / Diagnosis ---

    async def diagnose(
        self,
        response_id: int,
        speculation_cap: int = 3,
    ) -> DiagnoseResult:
        """Re-run a continuation against a stored response with XPath observation.

        This method retrieves a stored response, decompresses it, reconstructs
        the Response object, and re-runs the continuation method with an
        XPathObserver active to capture all XPath/CSS queries.

        Useful for debugging "zero results" issues where the HTML structure
        may have changed or XPath queries are incorrect.

        Args:
            response_id: The database ID of the response to diagnose.
            speculation_cap: Maximum number of SpeculativeRequests to follow
                (prevents infinite loops). Default 3.

        Returns:
            DiagnoseResult with yields, observation tree, and any errors.

        Raises:
            ValueError: If response_id not found.
        """
        assert self._db is not None

        from juriscraper.scraper_driver.common.xpath_observer import (
            XPathObserver,
        )

        # Get response and request data
        cursor = await self._db.execute(
            """
            SELECT
                r.status_code,
                r.url,
                r.headers_json,
                r.continuation,
                req.method,
                req.url as request_url,
                req.accumulated_data_json,
                req.aux_data_json,
                req.permanent_json
            FROM responses r
            JOIN requests req ON r.request_id = req.id
            WHERE r.id = ?
            """,
            (response_id,),
        )
        row = await cursor.fetchone()

        if row is None:
            raise ValueError(f"Response {response_id} not found")

        (
            status_code,
            url,
            headers_json,
            continuation_name,
            method,
            request_url,
            accumulated_data_json,
            aux_data_json,
            permanent_json,
        ) = row

        # Decompress content
        content = await self.get_response_content(response_id)
        if content is None:
            content = b""

        # Reconstruct Response object
        headers = json.loads(headers_json) if headers_json else {}
        accumulated_data = (
            json.loads(accumulated_data_json) if accumulated_data_json else {}
        )
        aux_data = json.loads(aux_data_json) if aux_data_json else {}
        permanent = json.loads(permanent_json) if permanent_json else {}

        http_params = HTTPRequestParams(
            method=HttpMethod(method),
            url=request_url,
        )
        # Create a NavigatingRequest to serve as the request context
        reconstructed_request = NavigatingRequest(
            request=http_params,
            continuation=continuation_name,
            current_location=request_url,
            accumulated_data=accumulated_data,
            aux_data=aux_data,
            permanent=permanent,
        )

        # Decode content to text for the Response
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError:
            text = content.decode("utf-8", errors="replace")

        response = Response(
            status_code=status_code,
            url=url,
            content=content,
            text=text,
            headers=headers,
            request=reconstructed_request,
        )

        # Run continuation with observer
        yields: list[dict[str, Any]] = []
        error: str | None = None

        with XPathObserver() as observer:
            try:
                continuation_method = self.scraper.get_continuation(
                    continuation_name
                )
                gen = continuation_method(response)

                speculation_count = 0
                for item in gen:
                    yield_info = self._describe_yield(item)
                    yields.append(yield_info)

                    # Track speculation count
                    if isinstance(item, SpeculativeRequest):
                        speculation_count += 1
                        if speculation_count >= speculation_cap:
                            yields.append(
                                {
                                    "type": "_speculation_cap_reached",
                                    "message": f"Stopped after {speculation_cap} SpeculativeRequests",
                                }
                            )
                            break

            except Exception as e:
                import traceback

                error = f"{type(e).__name__}: {e}\n{traceback.format_exc()}"

        return DiagnoseResult(
            response_id=response_id,
            continuation=continuation_name,
            yields=yields,
            simple_tree=observer.simple_tree(),
            observer_json=observer.json(),
            error=error,
        )

    def _describe_yield(self, item: Any) -> dict[str, Any]:
        """Create a description of a yielded item for diagnose results."""
        from juriscraper.scraper_driver.data_types import ParsedData

        if isinstance(item, ParsedData):
            data = item.unwrap()
            data_str = str(data)
            return {
                "type": "ParsedData",
                "data_type": type(data).__name__,
                "preview": (
                    data_str[:200] + "..." if len(data_str) > 200 else data_str
                ),
            }
        elif isinstance(item, NavigatingRequest):
            return {
                "type": "NavigatingRequest",
                "url": item.request.url,
                "method": item.request.method.value,
                "continuation": (
                    item.continuation
                    if isinstance(item.continuation, str)
                    else item.continuation.__name__
                ),
            }
        elif isinstance(item, SpeculativeRequest):
            return {
                "type": "SpeculativeRequest",
                "url": item.request.url,
                "method": item.request.method.value,
                "continuation": (
                    item.continuation
                    if isinstance(item.continuation, str)
                    else item.continuation.__name__
                ),
            }
        elif isinstance(item, NonNavigatingRequest):
            return {
                "type": "NonNavigatingRequest",
                "url": item.request.url,
            }
        elif isinstance(item, ArchiveRequest):
            return {
                "type": "ArchiveRequest",
                "url": item.request.url,
                "expected_type": item.expected_type,
            }
        elif item is None:
            return {"type": "None"}
        else:
            return {
                "type": type(item).__name__,
                "repr": repr(item)[:200],
            }

    # --- Web Interface Listing Methods ---

    async def list_requests(
        self,
        status: str | None = None,
        continuation: str | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> Page[RequestRecord]:
        """List requests with optional filters and pagination.

        Args:
            status: Filter by status (pending, in_progress, completed, failed, held).
            continuation: Filter by continuation method name.
            offset: Number of records to skip for pagination.
            limit: Maximum number of records to return.

        Returns:
            Page of RequestRecord instances.
        """
        assert self._db is not None

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
            )
            for row in rows
        ]

        return Page(
            items=items,
            total=total,
            offset=offset,
            limit=limit,
        )

    async def list_responses(
        self,
        continuation: str | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> Page[ResponseRecord]:
        """List responses with optional filters and pagination.

        Args:
            continuation: Filter by continuation method name.
            offset: Number of records to skip for pagination.
            limit: Maximum number of records to return.

        Returns:
            Page of ResponseRecord instances.
        """
        assert self._db is not None

        conditions = []
        params: list[Any] = []

        if continuation:
            conditions.append("continuation = ?")
            params.append(continuation)

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
            )
            for row in rows
        ]

        return Page(
            items=items,
            total=total,
            offset=offset,
            limit=limit,
        )

    async def list_results(
        self,
        result_type: str | None = None,
        is_valid: bool | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> Page[ResultRecord]:
        """List results with optional filters and pagination.

        Args:
            result_type: Filter by result type (Pydantic model class name).
            is_valid: Filter by validation status.
            offset: Number of records to skip for pagination.
            limit: Maximum number of records to return.

        Returns:
            Page of ResultRecord instances.
        """
        assert self._db is not None

        conditions = []
        params: list[Any] = []

        if result_type:
            conditions.append("result_type = ?")
            params.append(result_type)
        if is_valid is not None:
            conditions.append("is_valid = ?")
            params.append(is_valid)

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

        return Page(
            items=items,
            total=total,
            offset=offset,
            limit=limit,
        )

    async def get_request(self, request_id: int) -> RequestRecord | None:
        """Get a single request by ID.

        Args:
            request_id: The database ID of the request.

        Returns:
            RequestRecord or None if not found.
        """
        assert self._db is not None

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
        )

    async def get_response(self, response_id: int) -> ResponseRecord | None:
        """Get a single response by ID.

        Args:
            response_id: The database ID of the response.

        Returns:
            ResponseRecord or None if not found.
        """
        assert self._db is not None

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
        )

    async def get_result(self, result_id: int) -> ResultRecord | None:
        """Get a single result by ID.

        Args:
            result_id: The database ID of the result.

        Returns:
            ResultRecord or None if not found.
        """
        assert self._db is not None

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

    # --- Request Cancellation ---

    async def cancel_request(self, request_id: int) -> bool:
        """Cancel a pending request.

        Only pending or held requests can be cancelled. In-progress requests
        cannot be cancelled as they are already being processed.

        Args:
            request_id: The database ID of the request to cancel.

        Returns:
            True if the request was cancelled, False if not found or not cancellable.
        """
        assert self._db is not None

        cursor = await self._db.execute(
            SQL.UPDATE_CANCEL_REQUEST, (request_id,)
        )
        await self._db.commit()

        cancelled = cursor.rowcount > 0
        if cancelled:
            await self._emit_progress(
                "request_cancelled",
                {
                    "request_id": request_id,
                },
            )

        return cancelled

    async def cancel_requests_by_continuation(self, continuation: str) -> int:
        """Cancel all pending/held requests for a continuation.

        Args:
            continuation: The continuation method name.

        Returns:
            Number of requests cancelled.
        """
        assert self._db is not None

        cursor = await self._db.execute(
            SQL.UPDATE_CANCEL_BY_CONTINUATION, (continuation,)
        )
        await self._db.commit()

        count = cursor.rowcount
        if count > 0:
            await self._emit_progress(
                "requests_batch_cancelled",
                {
                    "continuation": continuation,
                    "count": count,
                },
            )

        return count


# --- Record Dataclasses ---

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

    def to_json(self) -> str:
        """Serialize to JSON for WebSocket transport."""
        return json.dumps(
            {
                "items": [
                    item.to_dict() if hasattr(item, "to_dict") else str(item)
                    for item in self.items
                ],
                "total": self.total,
                "offset": self.offset,
                "limit": self.limit,
                "has_more": self.offset + len(self.items) < self.total,
            }
        )


@dataclass
class RequestRecord:
    """Request record from database.

    Represents a row from the requests table with essential fields
    for web interface display.
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
        }

    def to_json(self) -> str:
        """Serialize to JSON for WebSocket transport."""
        return json.dumps(self.to_dict())


@dataclass
class ResponseRecord:
    """Response record from database.

    Represents a row from the responses table with essential fields
    for web interface display. Does not include compressed content.
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

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        compression_ratio = None
        if self.content_size_original and self.content_size_compressed:
            compression_ratio = round(
                self.content_size_original / self.content_size_compressed, 2
            )

        return {
            "id": self.id,
            "request_id": self.request_id,
            "status_code": self.status_code,
            "url": self.url,
            "content_size_original": self.content_size_original,
            "content_size_compressed": self.content_size_compressed,
            "compression_ratio": compression_ratio,
            "continuation": self.continuation,
            "created_at": self.created_at,
            "compression_dict_id": self.compression_dict_id,
        }

    def to_json(self) -> str:
        """Serialize to JSON for WebSocket transport."""
        return json.dumps(self.to_dict())


@dataclass
class ResultRecord:
    """Result record from database.

    Represents a row from the results table with essential fields
    for web interface display.
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
        """Serialize to JSON for WebSocket transport."""
        return json.dumps(self.to_dict())
