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

from juriscraper.scraper_driver.common.decorators import (
    get_speculate_metadata,
)
from juriscraper.scraper_driver.common.exceptions import (
    RequestFailedHalt,
    RequestFailedSkip,
    TransientException,
)
from juriscraper.scraper_driver.common.searchable import (
    SpeculateFunctionConfig,
)
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
)
from juriscraper.scraper_driver.driver.async_driver import AsyncDriver
from juriscraper.scraper_driver.driver.dev_driver.schema import (
    init_database,
)
from juriscraper.scraper_driver.driver.dev_driver.sql_manager import (
    Page,
    RequestRecord,
    ResponseRecord,
    ResultRecord,
    SQLManager,
)
from juriscraper.scraper_driver.driver.sync_driver import SpeculationState

# Re-export for public API
__all__ = [
    "LocalDevDriver",
    "ProgressEvent",
    "DiagnoseResult",
    "Page",
    "RequestRecord",
    "ResponseRecord",
    "ResultRecord",
    "SQLManager",
]
from juriscraper.scraper_driver.driver.dev_driver.stats import DevDriverStats

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable, Callable, Generator

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
    - Adaptive Token Bucket (ATB) rate limiting

    Args:
        scraper: The scraper instance to run.
        db_path: Path to SQLite database file.
        storage_dir: Directory for downloaded files.
        initial_rate: Initial rate limit in requests/second (default: 0.1 = 6 req/min).
        bucket_size: Maximum tokens in the rate limiter bucket (default: 4.0).
        num_workers: Number of initial concurrent workers (default: 1).
        max_workers: Maximum workers for dynamic scaling (default: 10).
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
        db: SQLManager,
        storage_dir: Path | None = None,
        num_workers: int = 1,
        max_workers: int = 10,
        resume: bool = True,
        max_backoff_time: float = 3600.0,
        request_manager: Any | None = None,
        enable_monitor: bool = True,
    ) -> None:
        """Initialize the driver.

        Note: Use LocalDevDriver.open() for proper async initialization.

        Args:
            scraper: The scraper instance to run.
            db: SQLManager for database operations.
            storage_dir: Directory for downloaded files.
            num_workers: Number of initial concurrent workers.
            max_workers: Maximum workers for dynamic scaling.
            resume: If True, resume from existing queue state.
            max_backoff_time: Maximum total backoff time before marking failed.
            request_manager: AsyncRequestManager for handling HTTP requests.
            enable_monitor: If True (default), start the worker monitor for dynamic scaling.
                Set to False for tests that need the driver to exit quickly.
        """
        # Initialize parent with the request manager
        super().__init__(
            scraper=scraper,
            storage_dir=storage_dir,
            num_workers=num_workers,
            request_manager=request_manager,
        )

        self.resume = resume
        self.max_backoff_time = max_backoff_time
        self.max_workers = max_workers
        self.enable_monitor = enable_monitor

        self.db = db
        # Progress callback for web interface
        self.on_progress: Callable[[ProgressEvent], Awaitable[None]] | None = (
            None
        )

        # Stop event for graceful shutdown (always set, not optional like in parent)
        self.stop_event: asyncio.Event = asyncio.Event()

        # Worker management for dynamic scaling
        self._worker_tasks: dict[int, asyncio.Task[None]] = {}
        self._next_worker_id: int = 0
        self._monitor_task: asyncio.Task[None] | None = None

        # Speculation state - populated by _discover_speculate_functions (new @speculate pattern)
        self._speculation_state: dict[str, SpeculationState] = {}
        # Lock for speculation state updates from concurrent workers
        self._speculation_lock = asyncio.Lock()

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
        # Extract driver-specific kwargs for SQLManager initialization
        initial_rate = kwargs.pop("initial_rate", 0.1)
        bucket_size = kwargs.pop("bucket_size", 4.0)
        num_workers = kwargs.pop("num_workers", 1)
        max_workers = kwargs.pop("max_workers", 10)
        max_backoff_time = kwargs.pop("max_backoff_time", 3600.0)
        resume = kwargs.pop("resume", True)
        timeout = kwargs.pop("timeout", None)  # Request timeout in seconds
        custom_request_manager = kwargs.pop("request_manager", None)

        # Initialize database and SQLManager
        aiosqlite_db = await init_database(db_path)
        sql_manager = SQLManager(aiosqlite_db)

        # Initialize run metadata
        # Store full path as module:class_name format for registry lookup
        # e.g., "juriscraper.sd.state.connecticut.jud_ct_gov.scraper:ConnScraper"
        scraper_name = (
            f"{scraper.__class__.__module__}:{scraper.__class__.__name__}"
        )
        scraper_version = getattr(scraper, "__version__", None)
        await sql_manager.init_run_metadata(
            scraper_name=scraper_name,
            scraper_version=scraper_version,
            num_workers=num_workers,
            max_backoff_time=max_backoff_time,
        )

        # Restore queue if resuming
        if resume:
            pending_count = await sql_manager.restore_queue()
            if pending_count > 0:
                logger.info(
                    f"Restored {pending_count} pending requests from database"
                )

        # Use custom request manager if provided (e.g., for testing)
        # Otherwise, set up ATB rate limiter request manager
        if custom_request_manager is not None:
            request_manager = custom_request_manager
        else:
            from juriscraper.scraper_driver.driver.dev_driver.atb_rate_limiter import (
                ATBAsyncRequestManager,
                ATBConfig,
            )

            atb_config = ATBConfig(
                bucket_size=bucket_size,
                initial_rate=initial_rate,
            )
            request_manager = ATBAsyncRequestManager(
                config=atb_config,
                sql_manager=sql_manager,
                ssl_context=scraper.get_ssl_context(),
                timeout=timeout,
            )
            await request_manager.initialize()

        driver = cls(
            scraper,
            sql_manager,
            request_manager=request_manager,
            num_workers=num_workers,
            max_workers=max_workers,
            max_backoff_time=max_backoff_time,
            resume=resume,
            **kwargs,
        )

        try:
            yield driver
        finally:
            await driver.close()

    async def close(self) -> None:
        """Close DB connections and clean up resources.

        On close, if there are any in_progress requests, reset them to pending
        so they can be resumed on next startup. Also mark run as interrupted
        if it was running.
        """
        # Persist speculation state before closing
        for func_name, spec_state in self._speculation_state.items():
            await self.db.save_speculation_state(
                func_name=func_name,
                highest_successful_id=spec_state.highest_successful_id,
                consecutive_failures=spec_state.consecutive_failures,
                current_ceiling=spec_state.current_ceiling,
                stopped=spec_state.stopped,
            )

        if self.db:
            await self.db.close_run()
            await self.db.db.close()

    # --- Speculation Support (new @speculate pattern) ---

    def _discover_speculate_functions(self) -> dict[str, SpeculationState]:
        """Discover @speculate functions on the scraper and initialize tracking state.

        Returns:
            Dictionary mapping function names to their SpeculationState.
        """
        from juriscraper.scraper_driver.common.searchable import (
            SpeculativeFunctionsProxy,
        )

        state: dict[str, SpeculationState] = {}
        params = self.scraper.get_params()

        for name in dir(self.scraper):
            if name.startswith("_"):
                continue
            func = getattr(self.scraper, name, None)
            if func is None:
                continue
            metadata = get_speculate_metadata(func)
            if metadata is None:
                continue

            # Get config from params (or use empty config)
            config = SpeculateFunctionConfig()
            if params is not None:
                try:
                    if isinstance(
                        params.speculative, SpeculativeFunctionsProxy
                    ):
                        proxy = getattr(params.speculative, name, None)
                        if proxy is not None:
                            config = proxy.get_config()
                except AttributeError:
                    pass

            state[name] = SpeculationState(
                func_name=name,
                metadata=metadata,
                config=config,
            )

        return state

    async def _load_speculation_state_from_db(self) -> None:
        """Load persisted speculation state from DB for resumption.

        Updates self._speculation_state with any persisted state.
        """
        saved_states = await self.db.load_all_speculation_states()

        for func_name, saved in saved_states.items():
            if func_name in self._speculation_state:
                spec_state = self._speculation_state[func_name]
                spec_state.highest_successful_id = saved[
                    "highest_successful_id"
                ]
                spec_state.consecutive_failures = saved["consecutive_failures"]
                spec_state.current_ceiling = saved["current_ceiling"]
                spec_state.stopped = bool(saved["stopped"])

    async def _seed_speculative_queue(self) -> None:
        """Seed the queue with initial speculative requests based on params config.

        For each @speculate function:
        - If definite_range is configured, use that range
        - Otherwise, use (1, highest_observed) from decorator metadata
        - Enqueue requests for all IDs in the range

        When resuming, skips IDs that have already been processed (based on
        current_ceiling from persisted state).
        """
        for func_name, spec_state in self._speculation_state.items():
            if spec_state.stopped:
                # Speculation was stopped in previous run, skip
                continue

            # Get the speculate function
            func = getattr(self.scraper, func_name)

            # Determine the range
            if spec_state.config.definite_range is not None:
                start, end = spec_state.config.definite_range
            else:
                # Use defaults from decorator metadata
                start = 1
                end = spec_state.metadata.highest_observed

            # If resuming, start from current_ceiling + 1
            if spec_state.current_ceiling > 0:
                start = max(start, spec_state.current_ceiling + 1)
                if start > end:
                    # Already processed all IDs in range
                    continue

            # Seed the queue
            for id_value in range(start, end + 1):
                # The @speculate decorator sets is_speculative=True and
                # speculation_id=(func_name, id_value) automatically
                request = func(id_value)

                # Serialize and enqueue via DB
                request_data = self._serialize_request(request)
                await self.db.insert_request(
                    priority=request.priority,
                    request_type=request_data["request_type"],
                    method=request_data["method"],
                    url=request_data["url"],
                    headers_json=request_data["headers_json"],
                    cookies_json=request_data["cookies_json"],
                    body=request_data["body"],
                    continuation=request_data["continuation"],
                    current_location=request_data["current_location"],
                    accumulated_data_json=request_data[
                        "accumulated_data_json"
                    ],
                    aux_data_json=request_data["aux_data_json"],
                    permanent_json=request_data["permanent_json"],
                    expected_type=request_data["expected_type"],
                    dedup_key=None,
                    parent_id=None,
                    is_speculative=request_data["is_speculative"],
                    speculation_id=request_data["speculation_id"],
                )

            # Update current_ceiling to the highest seeded ID
            spec_state.current_ceiling = end

    async def _extend_speculation(self, func_name: str) -> None:
        """Extend speculation for a function when approaching the ceiling.

        Called when a speculative request succeeds. If highest_successful_id
        approaches current_ceiling and we haven't hit plus consecutive failures,
        seed additional IDs.

        Args:
            func_name: Name of the @speculate function to extend.
        """
        spec_state = self._speculation_state.get(func_name)
        if spec_state is None or spec_state.stopped:
            return

        # Determine plus threshold
        if spec_state.config.plus is not None:
            plus = spec_state.config.plus
        else:
            plus = spec_state.metadata.largest_observed_gap

        # If consecutive failures >= plus, stop extending
        if spec_state.consecutive_failures >= plus:
            spec_state.stopped = True
            return

        # Extend if highest_successful_id is near the ceiling
        # We extend when within 'plus' of the ceiling
        if (
            spec_state.highest_successful_id
            >= spec_state.current_ceiling - plus
        ):
            # Get the speculate function
            func = getattr(self.scraper, func_name)

            # Seed additional IDs up to ceiling + plus
            new_ceiling = spec_state.current_ceiling + plus
            for id_value in range(
                spec_state.current_ceiling + 1, new_ceiling + 1
            ):
                # The @speculate decorator sets is_speculative=True and
                # speculation_id=(func_name, id_value) automatically
                request = func(id_value)

                # Serialize and enqueue via DB
                request_data = self._serialize_request(request)
                await self.db.insert_request(
                    priority=request.priority,
                    request_type=request_data["request_type"],
                    method=request_data["method"],
                    url=request_data["url"],
                    headers_json=request_data["headers_json"],
                    cookies_json=request_data["cookies_json"],
                    body=request_data["body"],
                    continuation=request_data["continuation"],
                    current_location=request_data["current_location"],
                    accumulated_data_json=request_data[
                        "accumulated_data_json"
                    ],
                    aux_data_json=request_data["aux_data_json"],
                    permanent_json=request_data["permanent_json"],
                    expected_type=request_data["expected_type"],
                    dedup_key=None,
                    parent_id=None,
                    is_speculative=request_data["is_speculative"],
                    speculation_id=request_data["speculation_id"],
                )

            spec_state.current_ceiling = new_ceiling

    async def _track_speculation_outcome(
        self, request: BaseRequest, response: Response
    ) -> None:
        """Track the outcome of a speculative request.

        Updates highest_successful_id and consecutive_failures based on response.
        Persists state to DB after update.

        Args:
            request: The speculative request.
            response: The HTTP response.
        """
        if not request.is_speculative or request.speculation_id is None:
            return

        # Extract function name and ID from speculation_id tuple
        func_name, speculative_id = request.speculation_id

        # Find the spec_state for this function
        spec_state = self._speculation_state.get(func_name)
        if spec_state is None:
            return

        is_success = 200 <= response.status_code < 300
        if is_success and not self.scraper.fails_successfully(response):
            # Soft 404 - treat as failure
            is_success = False

        async with self._speculation_lock:
            if is_success:
                # Success - update highest_successful_id and reset failures
                if speculative_id > spec_state.highest_successful_id:
                    spec_state.highest_successful_id = speculative_id
                spec_state.consecutive_failures = 0
                # Extend speculation if needed
                await self._extend_speculation(spec_state.func_name)
            else:
                # Failure - increment consecutive_failures if beyond highest_successful_id
                if speculative_id > spec_state.highest_successful_id:
                    spec_state.consecutive_failures += 1
                    # Check if we should stop
                    plus = (
                        spec_state.config.plus
                        if spec_state.config.plus is not None
                        else spec_state.metadata.largest_observed_gap
                    )
                    if spec_state.consecutive_failures >= plus:
                        spec_state.stopped = True

            # Persist state to DB
            await self.db.save_speculation_state(
                func_name=spec_state.func_name,
                highest_successful_id=spec_state.highest_successful_id,
                consecutive_failures=spec_state.consecutive_failures,
                current_ceiling=spec_state.current_ceiling,
                stopped=spec_state.stopped,
            )

    # --- Queue Operations (DB-backed) ---

    async def enqueue_request(
        self,
        new_request: BaseRequest,
        context: Response | BaseRequest,
        parent_request_id: int | None = None,
    ) -> None:
        """Enqueue a new request to the database.

        Overrides AsyncDriver.enqueue_request to persist to SQLite.

        Args:
            new_request: The new request to enqueue.
            context: Response or originating request for URL resolution.
            parent_request_id: Optional parent request ID for tracking request relationships.
        """
        # Resolve the request from context
        resolved_request = new_request.resolve_from(context)  # type: ignore

        # Check for duplicates before inserting
        dedup_key = resolved_request.deduplication_key
        if dedup_key is not None and not isinstance(dedup_key, str):
            # SkipDeduplicationCheck - allow the request
            dedup_key = None

        # Check if this dedup_key already exists
        if dedup_key and await self.db.check_dedup_key_exists(dedup_key):
            # Duplicate found - skip
            return

        # Serialize request data
        request_data = self._serialize_request(resolved_request)

        # Use provided parent_request_id, or look up from context if not provided
        parent_id: int | None = parent_request_id
        if (
            parent_id is None
            and isinstance(context, Response)
            and context.request
        ):
            parent_id = await self.db.find_parent_request_id(
                context.request.request.url
            )

        # Insert the request
        await self.db.insert_request(
            priority=resolved_request.priority,
            request_type=request_data["request_type"],
            method=request_data["method"],
            url=request_data["url"],
            headers_json=request_data["headers_json"],
            cookies_json=request_data["cookies_json"],
            body=request_data["body"],
            continuation=request_data["continuation"],
            current_location=request_data["current_location"],
            accumulated_data_json=request_data["accumulated_data_json"],
            aux_data_json=request_data["aux_data_json"],
            permanent_json=request_data["permanent_json"],
            expected_type=request_data["expected_type"],
            dedup_key=dedup_key,
            parent_id=parent_id,
            is_speculative=request_data["is_speculative"],
            speculation_id=request_data["speculation_id"],
        )

        # Emit progress event
        await self._emit_progress(
            "request_enqueued",
            {
                "url": request_data["url"],
                "continuation": request_data["continuation"],
                "priority": resolved_request.priority,
            },
        )

    def _serialize_request(
        self,
        request: BaseRequest,
    ) -> dict[str, Any]:
        """Serialize a BaseRequest to dictionary for DB storage.

        Args:
            request: The request to serialize.

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
        elif isinstance(request, NonNavigatingRequest):
            request_type = "non_navigating"
            expected_type = None
        else:
            request_type = "navigating"
            expected_type = None

        # Build permanent data
        permanent_data = dict(request.permanent) if request.permanent else {}

        # Serialize speculation_id as JSON tuple ["func_name", spec_id]
        speculation_id_json = None
        if request.speculation_id is not None:
            speculation_id_json = json.dumps(list(request.speculation_id))

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
            "permanent_json": json.dumps(permanent_data)
            if permanent_data
            else None,
            "expected_type": expected_type,
            "is_speculative": request.is_speculative,
            "speculation_id": speculation_id_json,
        }

    async def _get_next_request(self) -> tuple[int, BaseRequest] | None:
        """Get the next pending request from the database.

        Returns:
            Tuple of (request_id, request) or None if queue is empty.

        Notes:
            - Skips 'held' status requests
            - Skips requests in retry backoff (started_at > current time)
        """
        # Atomically dequeue the next pending request.
        # Uses UPDATE ... RETURNING to prevent race conditions where multiple
        # workers could select the same request.
        # Skip 'held' status requests
        # Skip requests in retry backoff (started_at is used to track retry-after time)
        row = await self.db.dequeue_next_request()

        if row is None:
            return None

        request_id = row[0]

        # Deserialize and return (already marked as in_progress by dequeue)
        request = self._deserialize_request(row)
        return (request_id, request)

    def _deserialize_request(self, row: tuple[Any, ...]) -> BaseRequest:
        """Deserialize a database row to a BaseRequest.

        Args:
            row: Database row tuple from requests table.

        Returns:
            Reconstructed BaseRequest (NavigatingRequest, NonNavigatingRequest,
            or ArchiveRequest depending on request_type).
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
            is_speculative,
            speculation_id_json,
        ) = row

        # Parse JSON fields
        headers = json.loads(headers_json) if headers_json else None
        cookies = json.loads(cookies_json) if cookies_json else None
        accumulated_data = (
            json.loads(accumulated_data_json) if accumulated_data_json else {}
        )
        aux_data = json.loads(aux_data_json) if aux_data_json else {}
        permanent = json.loads(permanent_json) if permanent_json else {}

        # Parse speculation_id from JSON tuple ["func_name", spec_id]
        speculation_id: tuple[str, int] | None = None
        if speculation_id_json:
            parsed = json.loads(speculation_id_json)
            speculation_id = (parsed[0], parsed[1])

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
                is_speculative=bool(is_speculative),
                speculation_id=speculation_id,
            )

    async def _mark_request_completed(self, request_id: int) -> None:
        """Mark a request as completed in the database.

        Args:
            request_id: The database ID of the request.
        """
        await self.db.mark_request_completed(request_id)

    async def _mark_request_failed(
        self, request_id: int, error_message: str
    ) -> None:
        """Mark a request as failed in the database.

        Args:
            request_id: The database ID of the request.
            error_message: Error message describing the failure.
        """
        await self.db.mark_request_failed(request_id, error_message)

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
        # Get current retry state
        retry_state = await self.db.get_retry_state(request_id)
        if retry_state is None:
            return False

        retry_count, cumulative_backoff = retry_state

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
        await self.db.schedule_retry(
            request_id, new_cumulative_backoff, next_retry_delay, str(error)
        )

        logger.info(
            f"Request {request_id} scheduled for retry #{retry_count + 1} "
            f"(delay: {next_retry_delay:.1f}s, cumulative: {new_cumulative_backoff:.1f}s)"
        )

        return True

    async def _store_response(
        self,
        request_id: int,
        response: Response,
        continuation: str,
        speculation_outcome: str | None = None,
    ) -> int:
        """Store an HTTP response in the database.

        For regular responses, content is compressed and stored in the responses table.
        For ArchiveResponse, content is NOT stored (it's already on disk); instead,
        file metadata is stored in the archived_files table.

        Args:
            request_id: The database ID of the associated request.
            response: The Response object to store.
            continuation: The continuation method that will process this response.
            speculation_outcome: For speculative requests: 'success', 'stopped', or 'skipped'.
                None for non-speculative requests.

        Returns:
            The database ID of the stored response.
        """
        import uuid

        from juriscraper.scraper_driver.data_types import (
            ArchiveRequest,
            ArchiveResponse,
        )
        from juriscraper.scraper_driver.driver.dev_driver.compression import (
            compress_response,
        )

        # Serialize headers
        headers_json = (
            json.dumps(response.headers) if response.headers else None
        )

        # Check if this is an ArchiveResponse - file is already on disk
        is_archive = isinstance(response, ArchiveResponse)

        if is_archive:
            # For archived files, don't store content in database (it's on disk)
            # Store NULL for content to save space
            compressed = None
            content_size_original = (
                len(response.content) if response.content else 0
            )
            content_size_compressed = 0
            dict_id = None
        else:
            # Regular response - compress and store content
            content = response.content or b""
            content_size_original = len(content)

            if content_size_original > 0:
                compressed, dict_id = await compress_response(
                    self.db.db, content, continuation
                )
                content_size_compressed = len(compressed)
            else:
                compressed = b""
                dict_id = None
                content_size_compressed = 0

        # Generate WARC record ID for later export
        warc_record_id = str(uuid.uuid4())

        response_id = await self.db.store_response(
            request_id=request_id,
            status_code=response.status_code,
            headers_json=headers_json,
            url=response.url,
            compressed_content=compressed,
            content_size_original=content_size_original,
            content_size_compressed=content_size_compressed,
            dict_id=dict_id,
            continuation=continuation,
            warc_record_id=warc_record_id,
            speculation_outcome=speculation_outcome,
        )

        # For ArchiveResponse, also store file metadata in archived_files
        if isinstance(response, ArchiveResponse) and response.file_url:
            # Get expected_type from the request if it's an ArchiveRequest
            expected_type: str | None = None
            if isinstance(response.request, ArchiveRequest):
                expected_type = response.request.expected_type

            await self._store_archived_file(
                request_id=request_id,
                file_path=response.file_url,
                original_url=response.url,
                expected_type=expected_type,
                content=response.content,
            )

        return response_id

    async def _store_archived_file(
        self,
        request_id: int,
        file_path: str,
        original_url: str,
        expected_type: str | None,
        content: bytes | None,
    ) -> int:
        """Store archived file metadata in the database.

        Args:
            request_id: The database ID of the associated request.
            file_path: Local file system path where the file is stored.
            original_url: The URL the file was downloaded from.
            expected_type: Expected file type (pdf, audio, etc.).
            content: File content for computing hash and size.

        Returns:
            The database ID of the archived file record.
        """
        import hashlib

        # Compute file size and content hash
        file_size = len(content) if content else 0
        content_hash = hashlib.sha256(content).hexdigest() if content else None

        return await self.db.store_archived_file(
            request_id=request_id,
            file_path=file_path,
            original_url=original_url,
            expected_type=expected_type,
            file_size=file_size,
            content_hash=content_hash,
        )

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

        return await self.db.store_result(
            request_id=request_id,
            result_type=result_type,
            data_json=data_json,
            is_valid=is_valid,
            validation_errors_json=validation_errors_json,
        )

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

    async def _apply_speculative_start_ids(self) -> None:
        """Apply speculative start IDs from database to scraper params.

        This is used by the restart-speculative feature. When the user sets
        speculative start IDs via the web UI (stored in the speculative_start_ids
        table), those values are applied to the scraper's params when the driver
        starts running.

        After applying, the start IDs are cleared from the database to ensure
        they only take effect once.
        """
        # Get start IDs from database
        start_ids = await self.db.get_speculative_start_ids()
        if not start_ids:
            return

        # Ensure scraper has params
        if (
            not hasattr(self.scraper, "_params")
            or self.scraper._params is None
        ):
            # Initialize params using the class method
            self.scraper._params = self.scraper.__class__.params()

        # Apply start IDs to speculative proxy
        for step_name, starting_id in start_ids.items():
            try:
                setattr(
                    self.scraper._params.speculative, step_name, starting_id
                )
                logger.info(
                    f"Applied speculative start ID: {step_name} = {starting_id}"
                )
            except AttributeError:
                logger.warning(
                    f"Unknown speculative step: {step_name}, skipping"
                )

        # Clear the start IDs after applying (one-time use)
        await self.db.clear_all_speculative_start_ids()

    # --- Run Override ---

    async def run(self, setup_signal_handlers: bool = True) -> None:
        """Run the scraper, using DB-backed queue.

        Overrides AsyncDriver.run() to use database queue operations.

        Args:
            setup_signal_handlers: If True, register SIGINT/SIGTERM handlers
                for graceful shutdown. Set to False when running in a context
                that manages its own signal handling (e.g., FastAPI).
        """
        if setup_signal_handlers:
            self._setup_signal_handlers()

        # Update run status to running
        await self.db.update_run_status("running")

        # Apply any speculative start IDs from the database to the scraper params
        # This is used by the restart-speculative feature
        await self._apply_speculative_start_ids()

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
            has_requests = await self.db.has_any_requests()

            if not has_requests:
                # Seed queue with entry points from get_entry generator
                for entry_request in self.scraper.get_entry():
                    request_data = self._serialize_request(entry_request)
                    dedup_key = (
                        entry_request.deduplication_key
                        if isinstance(entry_request.deduplication_key, str)
                        else None
                    )

                    await self.db.insert_entry_request(
                        priority=entry_request.priority,
                        method=request_data["method"],
                        url=request_data["url"],
                        headers_json=request_data["headers_json"],
                        cookies_json=request_data["cookies_json"],
                        body=request_data["body"],
                        continuation=request_data["continuation"],
                        current_location=request_data["current_location"],
                        accumulated_data_json=request_data[
                            "accumulated_data_json"
                        ],
                        aux_data_json=request_data["aux_data_json"],
                        permanent_json=request_data["permanent_json"],
                        dedup_key=dedup_key,
                    )

            # Discover @speculate functions and seed the queue
            self._speculation_state = self._discover_speculate_functions()
            if self._speculation_state:
                # Load any persisted state from previous run
                await self._load_speculation_state_from_db()
                # Seed the queue with speculative requests
                await self._seed_speculative_queue()

            # Start initial workers
            logger.info(
                f"Starting {self.num_workers} initial workers (max: {self.max_workers})"
            )
            for _ in range(self.num_workers):
                self._spawn_worker()

            # Start the worker monitor for dynamic scaling (if enabled)
            if self.enable_monitor:
                self._monitor_task = asyncio.create_task(
                    self._worker_monitor()
                )

            # Wait for all workers and monitor to complete
            # Workers exit when queue is empty or stop_event is set
            # Monitor exits when no workers remain and no pending work
            while self._worker_tasks or (
                self._monitor_task and not self._monitor_task.done()
            ):
                # Gather current tasks (workers + monitor if still running)
                tasks_to_wait: list[asyncio.Task[None]] = list(
                    self._worker_tasks.values()
                )
                if self._monitor_task and not self._monitor_task.done():
                    tasks_to_wait.append(self._monitor_task)

                if not tasks_to_wait:
                    break

                # Wait for any task to complete
                done, _ = await asyncio.wait(
                    tasks_to_wait,
                    return_when=asyncio.FIRST_COMPLETED,
                )

                # Check for exceptions in completed tasks
                for task in done:
                    if (
                        task.exception() is not None
                        and task is not self._monitor_task
                    ):
                        # Re-raise worker exceptions
                        raise task.exception()  # type: ignore[misc]

        except Exception as e:
            status = "error"
            error = e
            raise
        finally:
            # Cancel monitor if still running
            if self._monitor_task and not self._monitor_task.done():
                self._monitor_task.cancel()
                try:
                    await self._monitor_task
                except asyncio.CancelledError:
                    pass

            # Restore signal handlers if we set them up
            if setup_signal_handlers:
                self._restore_signal_handlers()

            # Update run metadata
            final_status = (
                "interrupted" if self.stop_event.is_set() else status
            )
            await self.db.finalize_run(
                final_status, str(error) if error else None
            )

            await self._emit_progress(
                "run_completed",
                {
                    "scraper_name": self.scraper.__class__.__name__,
                    "status": final_status,
                    "error": str(error) if error else None,
                },
            )

    # --- Worker Management ---

    @property
    def active_worker_count(self) -> int:
        """Number of currently active workers."""
        return sum(1 for t in self._worker_tasks.values() if not t.done())

    def _spawn_worker(self) -> int:
        """Spawn a new worker and return its ID.

        Returns:
            The worker ID of the newly spawned worker.
        """
        worker_id = self._next_worker_id
        self._next_worker_id += 1
        task = asyncio.create_task(self._db_worker(worker_id))
        self._worker_tasks[worker_id] = task

        # Clean up when worker exits
        def on_worker_done(
            _: asyncio.Task[None], wid: int = worker_id
        ) -> None:
            self._worker_tasks.pop(wid, None)

        task.add_done_callback(on_worker_done)

        logger.info(
            f"Spawned worker {worker_id}, total active: {self.active_worker_count}"
        )
        return worker_id

    async def _worker_monitor(self) -> None:
        """Monitor task that dynamically scales workers based on conditions.

        Adds a worker if:
        - There are pending requests
        - The rate limit > 2 * active_worker_count
        - active_worker_count < max_workers

        Exits when:
        - stop_event is set, OR
        - active_worker_count == 0 and no pending requests
        """
        logger.info(
            f"Worker monitor started (max_workers={self.max_workers}, "
            f"poll_interval=60s)"
        )

        while not self.stop_event.is_set():
            # Wait 60 seconds between checks
            try:
                await asyncio.wait_for(self.stop_event.wait(), timeout=60.0)
                # If we get here, stop_event was set
                break
            except asyncio.TimeoutError:
                # Normal timeout - proceed with check
                pass

            # Check exit condition: no workers and no pending work
            active_count = self.active_worker_count
            pending_count = await self.db.count_pending_requests()

            if active_count == 0 and pending_count == 0:
                logger.info(
                    "Worker monitor exiting: no workers and no pending requests"
                )
                break

            # Check scaling conditions
            if pending_count == 0:
                logger.debug(
                    f"Worker monitor: no pending requests "
                    f"(active_workers={active_count})"
                )
                continue

            if active_count >= self.max_workers:
                logger.debug(
                    f"Worker monitor: at max workers "
                    f"({active_count}/{self.max_workers})"
                )
                continue

            # Get current rate from the ATB rate limiter
            current_rate = getattr(self.request_manager, "_rate", 0.0)

            # Scale if rate > 2 * active_workers
            if current_rate > 2 * active_count:
                new_worker_id = self._spawn_worker()
                logger.info(
                    f"Worker monitor: scaled up to {self.active_worker_count} workers "
                    f"(rate={current_rate:.2f}/s, pending={pending_count})"
                )

                await self._emit_progress(
                    "worker_scaled",
                    {
                        "worker_id": new_worker_id,
                        "active_workers": self.active_worker_count,
                        "current_rate": current_rate,
                        "pending_requests": pending_count,
                    },
                )
            else:
                logger.debug(
                    f"Worker monitor: rate ({current_rate:.2f}/s) <= "
                    f"2 * workers ({2 * active_count}), no scale-up"
                )

        logger.info("Worker monitor stopped")

    async def _db_worker(self, worker_id: int) -> None:
        """Worker that processes requests from the database queue.

        Handles regular requests (NavigatingRequest, NonNavigatingRequest, ArchiveRequest).
        Speculative requests are handled via the new @speculate decorator pattern.

        Args:
            worker_id: Identifier for this worker.
        """
        import time as time_module

        logger.info(f"[W{worker_id}] Worker started")
        requests_processed = 0

        while True:
            loop_start = time_module.time()

            # Check for graceful shutdown
            if self.stop_event.is_set():
                logger.info(
                    f"[W{worker_id}] Exiting: stop_event set (processed {requests_processed} requests)"
                )
                break

            # Get next request from DB
            result = await self._get_next_request()

            if result is None:
                # No immediately available requests - check for scheduled retries
                retry_delay = await self.db.get_next_scheduled_retry_delay()

                if retry_delay is not None and retry_delay > 0:
                    # There are scheduled retries - wait for the next one
                    # Add a small buffer and cap at a reasonable max wait
                    wait_time = min(retry_delay + 0.1, 60.0)
                    logger.info(
                        f"[W{worker_id}] Waiting {wait_time:.1f}s for scheduled retry"
                    )
                    await asyncio.sleep(wait_time)

                    # Check for shutdown after waiting
                    if self.stop_event.is_set():
                        break

                    # Try again after waiting
                    result = await self._get_next_request()
                    if result is None:
                        # Still nothing - continue loop to check again
                        continue
                else:
                    # No scheduled retries - poll for new work
                    # Other workers may still be processing and generating new requests
                    # Poll at moderate rate (100ms) to balance responsiveness and DB load
                    consecutive_empty = 0
                    max_polls = 100  # 10 seconds max polling

                    for poll_attempt in range(max_polls):
                        # Wait before retry (100ms gives good balance)
                        await asyncio.sleep(0.1)

                        # Check for shutdown
                        if self.stop_event.is_set():
                            logger.info(
                                f"[W{worker_id}] Stop event during polling"
                            )
                            break

                        # Try to get work - this is the only DB call per iteration
                        result = await self._get_next_request()
                        if result is not None:
                            logger.info(
                                f"[W{worker_id}] Found work after {poll_attempt + 1} polls"
                            )
                            break

                        # Check exit condition periodically (every 0.5s)
                        if poll_attempt % 5 == 4:
                            in_progress_count = (
                                await self.db.count_in_progress()
                            )
                            pending_count = (
                                await self.db.count_pending_requests()
                            )

                            if in_progress_count == 0 and pending_count == 0:
                                consecutive_empty += 1
                                if (
                                    consecutive_empty >= 6
                                ):  # ~3 seconds of true idle
                                    logger.info(
                                        f"[W{worker_id}] Exiting: idle (processed {requests_processed})"
                                    )
                                    break
                            else:
                                consecutive_empty = 0

                            if poll_attempt % 20 == 19:
                                logger.info(
                                    f"[W{worker_id}] Polling... in_progress={in_progress_count}, pending={pending_count}"
                                )

                    if result is None:
                        logger.info(
                            f"[W{worker_id}] Exiting: queue empty after polling (processed {requests_processed} requests)"
                        )
                        break

            request_id, request = result
            logger.debug(f"[W{worker_id}] Dequeued request {request_id}")

            try:
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

                # Process the request
                req_start = time_module.time()
                await self._process_regular_request(
                    request_id, request, continuation_name
                )
                req_time = time_module.time() - req_start
                loop_time = time_module.time() - loop_start
                requests_processed += 1
                logger.info(
                    f"[W{worker_id}] Completed request {request_id} in {req_time * 1000:.1f}ms (loop={loop_time * 1000:.1f}ms, total={requests_processed})"
                )

            except RequestFailedHalt:
                # User callback requested halt - propagate up
                raise

            except RequestFailedSkip:
                # User callback requested skip - mark as failed and continue
                await self._mark_request_failed(
                    request_id, "Skipped by on_transient_exception callback"
                )
                await self._emit_progress(
                    "request_skipped",
                    {
                        "request_id": request_id,
                        "url": request.request.url,
                        "reason": "callback_requested_skip",
                    },
                )
                continue

            except TransientException as e:
                should_retry = await self._handle_retry(request_id, e)
                if should_retry:
                    # Log at warning level without full traceback for transient errors
                    logger.warning(
                        f"Worker {worker_id} transient error on request "
                        f"{request_id}: {type(e).__name__}: {e}"
                    )
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
                else:
                    # Max backoff exceeded - log the full traceback and mark failed
                    logger.exception(
                        f"Worker {worker_id} transient error exceeded max "
                        f"backoff for request {request_id}"
                    )

                    # Mark as failed and store error
                    await self._mark_request_failed(request_id, str(e))

                    from juriscraper.scraper_driver.driver.dev_driver.errors import (
                        store_error,
                    )

                    await store_error(
                        self.db.db,
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
                            "reason": "max_backoff_exceeded",
                        },
                    )

            except Exception as e:
                # Non-transient error - log full traceback
                logger.exception(
                    f"Worker {worker_id} error processing request {request_id}"
                )

                # Non-transient error or max backoff exceeded - mark as failed
                await self._mark_request_failed(request_id, str(e))

                # Store error in database for tracking and requeue
                from juriscraper.scraper_driver.driver.dev_driver.errors import (
                    store_error,
                )

                await store_error(
                    self.db.db,
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

        logger.info(f"Request {request_id}: starting HTTP fetch")
        response: Response = (
            await self.resolve_archive_request(request)
            if isinstance(request, ArchiveRequest)
            else await self.resolve_request(request)
        )
        logger.info(
            f"Request {request_id}: HTTP fetch complete, status={response.status_code}"
        )

        # Track speculation outcome for @speculate requests
        if request.is_speculative and self._speculation_state:
            await self._track_speculation_outcome(request, response)

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
        """Process generator with DB storage.

        Uses simple iteration (for item in gen).

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
                        await self.enqueue_request(item, response, request_id)

                    case NonNavigatingRequest() | ArchiveRequest():
                        await self.enqueue_request(
                            item, parent_request, request_id
                        )

                    case None:
                        pass

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
        return await self.db.get_run_status()

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
        count = await self.db.pause_step(continuation)
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
        count = await self.db.resume_step(continuation)
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
        return await self.db.get_held_count(continuation)

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
        new_request_id = await self.db.requeue_error(error_id)

        if new_request_id is not None:
            # Get URL and continuation for progress event
            error_info = await self.db.get_error_info_for_progress(error_id)
            if error_info:
                await self._emit_progress(
                    "error_requeued",
                    {
                        "error_id": error_id,
                        "new_request_id": new_request_id,
                        "url": error_info.get("url", ""),
                        "continuation": error_info.get("continuation", ""),
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
        new_request_ids = await self.db.batch_requeue_errors(
            error_type=error_type, continuation=continuation
        )

        if new_request_ids:
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
        return await self.db.get_response_content(response_id)

    # --- Speculative Progress Tracking ---

    async def get_speculative_progress(self, step_name: str) -> int | None:
        """Get the highest_successful_id for a speculative step.

        Args:
            step_name: The name of the speculative step method.

        Returns:
            The highest_successful_id, or None if no progress recorded.
        """
        state = await self.db.load_speculation_state(step_name)
        if state is None:
            return None
        return state["highest_successful_id"]

    async def get_all_speculative_progress(self) -> dict[str, int]:
        """Get all speculative progress entries.

        Returns:
            Dict mapping step names to their highest_successful_id.
        """
        return await self.db.get_all_speculation_progress()

    async def _recover_speculative_step(
        self,
        request_id: int,
        step_name: str,
        current_speculative_id: int,
    ) -> None:
        """Recover a speculative step by re-invoking it from the latest ID.

        Called when a speculative request is processed but its generator context
        has been lost (e.g., after server restart). This re-invokes the original
        step with the latest speculative_id from the progress table.

        Args:
            request_id: The database ID of the request being processed.
            step_name: The name of the speculative step method.
            current_speculative_id: The speculative_id from the current request.
        """
        # Get the latest progress for this step from speculation_tracking
        latest_id = await self.get_speculative_progress(step_name)

        # Use the maximum of current request ID and stored progress
        # This handles cases where progress wasn't stored yet
        recovery_id = max(current_speculative_id, latest_id or 0)

        # Progress is tracked via save_speculation_state in _track_speculation_outcome

        logger.info(
            f"Recovering speculative step '{step_name}': "
            f"processed ID {current_speculative_id}, "
            f"will restart from {recovery_id + 1}"
        )

        # Get the step continuation and re-invoke it with the recovery ID
        # We need to build a fake Response to start the step
        # The step will be called via get_entry which starts fresh
        try:
            # Set the speculative starting ID in params for recovery
            if self.scraper._params is not None:
                try:
                    setattr(
                        self.scraper._params.speculative,
                        step_name,
                        recovery_id + 1,
                    )
                    logger.info(
                        f"Set params.speculative.{step_name} = {recovery_id + 1} "
                        f"for recovery"
                    )
                except AttributeError:
                    logger.warning(
                        f"Could not set speculative starting ID for {step_name} - "
                        f"step may not be configured in params"
                    )

            # Re-invoke the entry point to restart the speculative flow
            # This will call get_entry() which should yield the NavigatingRequest
            # that triggers the speculative step
            await self._emit_progress(
                "speculative_recovery_initiated",
                {
                    "step_name": step_name,
                    "processed_id": current_speculative_id,
                    "recovery_id": recovery_id + 1,
                },
            )

        except Exception as e:
            logger.exception(
                f"Failed to recover speculative step {step_name}: {e}"
            )

        # Mark the original request as completed (we've initiated recovery)
        await self._mark_request_completed(request_id)

    # --- Statistics ---

    async def get_stats(self) -> DevDriverStats:
        """Get comprehensive statistics about the driver state.

        Returns:
            DevDriverStats instance with queue, throughput, compression,
            result, and error statistics.
        """
        from juriscraper.scraper_driver.driver.dev_driver.stats import (
            get_stats,
        )

        return await get_stats(self.db.db)

    # --- Debugging / Diagnosis ---

    async def diagnose(
        self,
        response_id: int,
        speculation_cap: int = 3,  # Deprecated, kept for backwards compatibility
    ) -> DiagnoseResult:
        """Re-run a continuation against a stored response with XPath observation.

        This method retrieves a stored response, decompresses it, reconstructs
        the Response object, and re-runs the continuation method with an
        XPathObserver active to capture all XPath/CSS queries.

        Useful for debugging "zero results" issues where the HTML structure
        may have changed or XPath queries are incorrect.

        Args:
            response_id: The database ID of the response to diagnose.
            speculation_cap: Deprecated, no longer used.

        Returns:
            DiagnoseResult with yields, observation tree, and any errors.

        Raises:
            ValueError: If response_id not found.
        """
        from juriscraper.scraper_driver.common.xpath_observer import (
            XPathObserver,
        )

        # Get response and request data
        cursor = await self.db.db.execute(
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

                for item in gen:
                    yield_info = self._describe_yield(item)
                    yields.append(yield_info)

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
    # These delegate to SQLManager for the actual database operations

    async def list_requests(
        self,
        status: str | None = None,
        continuation: str | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> Page[RequestRecord]:
        """List requests with optional filters and pagination."""
        return await self.db.list_requests(
            status=status,
            continuation=continuation,
            offset=offset,
            limit=limit,
        )

    async def list_responses(
        self,
        continuation: str | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> Page[ResponseRecord]:
        """List responses with optional filters and pagination."""
        return await self.db.list_responses(
            continuation=continuation, offset=offset, limit=limit
        )

    async def list_results(
        self,
        result_type: str | None = None,
        is_valid: bool | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> Page[ResultRecord]:
        """List results with optional filters and pagination."""
        return await self.db.list_results(
            result_type=result_type,
            is_valid=is_valid,
            offset=offset,
            limit=limit,
        )

    async def get_request(self, request_id: int) -> RequestRecord | None:
        """Get a single request by ID."""
        return await self.db.get_request(request_id)

    async def get_response(self, response_id: int) -> ResponseRecord | None:
        """Get a single response by ID."""
        return await self.db.get_response(response_id)

    async def get_result(self, result_id: int) -> ResultRecord | None:
        """Get a single result by ID."""
        return await self.db.get_result(result_id)

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
        cancelled = await self.db.cancel_request(request_id)
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
        count = await self.db.cancel_requests_by_continuation(continuation)
        if count > 0:
            await self._emit_progress(
                "requests_batch_cancelled",
                {
                    "continuation": continuation,
                    "count": count,
                },
            )
        return count
