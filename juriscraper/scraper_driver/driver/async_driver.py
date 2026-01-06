"""Asynchronous driver implementation.

This module contains the async driver that processes scraper generators
using multiple concurrent workers.

The AsyncDriver closely mirrors SyncDriver with three key differences:
1. Factors out the main run loop to a worker method for concurrency
2. Uses an async-compatible priority queue (asyncio.PriorityQueue)
3. Takes num_workers argument to control concurrency
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable, Generator
from pathlib import Path
from tempfile import gettempdir
from typing import Any, Generic, TypeVar, cast
from urllib.parse import urlparse

import httpx
from typing_extensions import assert_never

from juriscraper.scraper_driver.common.deferred_validation import (
    DeferredValidation,
)
from juriscraper.scraper_driver.common.exceptions import (
    DataFormatAssumptionException,
    HTMLResponseAssumptionException,
    HTMLStructuralAssumptionException,
    RequestTimeoutException,
    TransientException,
)
from juriscraper.scraper_driver.common.interceptors import AsyncInterceptor
from juriscraper.scraper_driver.data_types import (
    ArchiveRequest,
    ArchiveResponse,
    BaseRequest,
    BaseScraper,
    NavigatingRequest,
    NonNavigatingRequest,
    ParsedData,
    Response,
    ScraperYield,
    SkipDeduplicationCheck,
)

logger = logging.getLogger(__name__)

ScraperReturnDatatype = TypeVar("ScraperReturnDatatype")


def log_and_validate_invalid_data(data: DeferredValidation) -> None:
    """Default callback for invalid data that logs validation errors.

    This callback attempts to validate the data to get detailed error information,
    then logs the validation failure at the error level.

    Args:
        data: DeferredValidation instance containing invalid data.
    """
    try:
        # Attempt validation to get detailed error information
        data.confirm()
    except DataFormatAssumptionException as e:
        # Log the validation failure with full context
        error_summary = ", ".join(
            f"{err['loc'][0]}: {err['msg']}" for err in e.errors
        )
        logger.error(
            f"Data validation failed for model '{e.model_name}': {error_summary}",
            extra={
                "model_name": e.model_name,
                "request_url": e.request_url,
                "error_count": len(e.errors),
                "errors": e.errors,
                "failed_doc": e.failed_doc,
            },
        )


async def default_archive_callback(
    content: bytes, url: str, expected_type: str | None, storage_dir: Path
) -> str:
    """Default async callback for archiving downloaded files.

    This callback extracts a filename from the URL or generates one based on
    the expected file type, then saves the file to the storage directory.

    Args:
        content: The binary file content.
        url: The URL the file was downloaded from.
        expected_type: Optional hint about the file type.
        storage_dir: Directory where files should be saved.

    Returns:
        The local file path where the file was saved.
    """
    # Extract filename from URL or generate one
    parsed_url = urlparse(url)
    path_parts = Path(parsed_url.path).parts
    # Filter out empty strings, '.', and '/' from path parts
    valid_parts = [p for p in path_parts if p and p not in (".", "/")]

    if valid_parts:
        filename = valid_parts[-1]
    else:
        # Generate a filename based on expected_type
        ext = {"pdf": ".pdf", "audio": ".mp3"}.get(expected_type or "", "")
        filename = f"download_{hash(url)}{ext}"

    file_path = storage_dir / filename
    file_path.write_bytes(content)
    return str(file_path)


class AsyncDriver(Generic[ScraperReturnDatatype]):
    """Asynchronous driver for running scrapers with multiple workers.

    This driver closely mirrors SyncDriver with three key differences:
    - Uses asyncio.PriorityQueue for async-compatible priority queue
    - Factors out the main loop to _worker() for concurrent execution
    - Takes num_workers to control the number of concurrent workers

    Example usage:
        from tests.scraper_driver.utils import collect_results

        callback, results = collect_results()
        driver = AsyncDriver(scraper, on_data=callback, num_workers=4)
        await driver.run()
        # Results are now in the results list
    """

    def __init__(
        self,
        scraper: BaseScraper[ScraperReturnDatatype],
        storage_dir: Path | None = None,
        interceptors: list["AsyncInterceptor"] | None = None,
        on_data: Callable[
            [ScraperReturnDatatype],
            Awaitable[None],
        ]
        | None = None,
        on_structural_error: Callable[
            ["HTMLStructuralAssumptionException"], Awaitable[bool]
        ]
        | None = None,
        on_invalid_data: Callable[[DeferredValidation], Awaitable[None]]
        | None = None,
        on_transient_exception: Callable[
            ["TransientException"], Awaitable[bool]
        ]
        | None = None,
        on_archive: Callable[[bytes, str, str | None, Path], Awaitable[str]]
        | None = None,
        on_run_start: Callable[[str], Awaitable[None]] | None = None,
        on_run_complete: Callable[
            [str, str, Exception | None], Awaitable[None]
        ]
        | None = None,
        duplicate_check: Callable[[str], Awaitable[bool]] | None = None,
        stop_event: asyncio.Event | None = None,
        num_workers: int = 1,
    ) -> None:
        """Initialize the driver.

        Args:
            scraper: Scraper instance with continuation methods.
            storage_dir: Directory for storing downloaded files. If None, uses system temp directory.
            interceptors: List of async interceptors to apply to requests and responses. Interceptors
                are applied in order for requests, and in reverse order for responses.
                Order matters - for example, cache should come before rate limiter.
            on_data: Optional async callback invoked when ParsedData is yielded and validated. Useful
                for persistence, logging, or other side effects. The callback receives the
                unwrapped data from ParsedData.
            on_structural_error: Optional async callback invoked when HTMLStructuralAssumptionException
                is raised during scraping. The callback receives the exception and should return
                True to continue scraping or False to stop. If not provided, exceptions propagate
                normally and stop the scraper.
            on_invalid_data: Optional async callback invoked when data fails validation. If not
                provided, invalid data is sent to on_data callback (if present), otherwise validation
                exceptions propagate normally.
            on_transient_exception: Optional async callback invoked when TransientException is raised
                during HTTP requests. The callback receives the exception and should return True
                to continue scraping or False to stop. If not provided, exceptions propagate
                normally and stop the scraper.
            on_archive: Optional async callback invoked when files are archived. Receives content
                (bytes), url (str), expected_type (str | None), and storage_dir (Path). Should return
                the local file path where the file was saved. If not provided, uses default_archive_callback.
            on_run_start: Optional async callback invoked when the scraper run starts. Receives
                scraper_name (str).
            on_run_complete: Optional async callback invoked when the scraper run completes. Receives
                scraper_name (str), status ("completed" | "error")
                and error (Exception | None).
            duplicate_check: Optional async callback invoked before enqueuing a request. Receives the
                deduplication_key (str) and should return True to enqueue the request or False to
                skip it. If not provided, all requests are enqueued (no deduplication).
            stop_event: Optional asyncio.Event for graceful shutdown. When set, workers
                will stop processing after completing their current request.
            num_workers: Number of concurrent workers to process requests. Defaults to 1.
        """
        self.scraper = scraper
        # Use asyncio.PriorityQueue for async-compatible priority queue
        # Each entry is (priority, counter, request) for stable FIFO ordering
        self.request_queue: asyncio.PriorityQueue[
            tuple[int, int, BaseRequest]
        ] = asyncio.PriorityQueue()
        self._queue_counter = 0  # For FIFO tie-breaking within same priority
        self._queue_lock = asyncio.Lock()  # Protect counter increments
        self.storage_dir = (
            storage_dir or Path(gettempdir()) / "juriscraper_files"
        )
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.interceptors = interceptors or []
        self.on_data = on_data
        self.on_structural_error = on_structural_error
        self.on_invalid_data = on_invalid_data
        self.on_transient_exception = on_transient_exception
        self.on_archive = on_archive or default_archive_callback
        self.on_run_start = on_run_start
        self.on_run_complete = on_run_complete
        self.duplicate_check = duplicate_check
        self.stop_event = stop_event
        self.num_workers = num_workers

        # Initialize httpx async client for reuse across requests
        self._client = httpx.AsyncClient()

    async def run(self) -> None:
        """Run the scraper starting from the scraper's entry point.

        Data is passed to the on_data callback as it is yielded. If you need to
        collect results, use a callback that appends to a list (see
        tests/design/utils.py::collect_results for a helper function).
        """

        # Fire on_run_start callback
        scraper_name = self.scraper.__class__.__name__
        if self.on_run_start:
            await self.on_run_start(scraper_name)

        status = "completed"
        error: Exception | None = None

        try:
            # Check for early stop before doing any work
            if self.stop_event and self.stop_event.is_set():
                return

            entry_request = self.scraper.get_entry()
            # Initialize priority queue with entry request
            self.request_queue = asyncio.PriorityQueue()
            self._queue_counter = 0
            await self.request_queue.put(
                (entry_request.priority, self._queue_counter, entry_request)
            )
            self._queue_counter += 1

            # Start workers
            workers = [
                asyncio.create_task(self._worker(i))
                for i in range(self.num_workers)
            ]

            # Wait for all items in the queue to be processed
            # Use wait_for with periodic checks for stop_event
            while True:
                if self.stop_event and self.stop_event.is_set():
                    # Stop requested - cancel workers and drain queue
                    for worker in workers:
                        worker.cancel()
                    # Drain the queue to prevent join() from blocking
                    while not self.request_queue.empty():
                        try:
                            self.request_queue.get_nowait()
                            self.request_queue.task_done()
                        except asyncio.QueueEmpty:
                            break
                    break

                try:
                    await asyncio.wait_for(
                        asyncio.shield(self.request_queue.join()), timeout=0.1
                    )
                    # join() completed - all work is done
                    break
                except TimeoutError:
                    # Check stop_event and continue waiting
                    continue

            # Cancel workers (they're waiting on the queue)
            for worker in workers:
                worker.cancel()

            # Wait for workers to finish cancellation
            await asyncio.gather(*workers, return_exceptions=True)

        except Exception as e:
            # Capture error for on_run_complete
            status = "error"
            error = e
            raise
        finally:
            # Fire on_run_complete callback
            if self.on_run_complete:
                await self.on_run_complete(
                    scraper_name,
                    status,
                    error,
                )

    async def _worker(self, worker_id: int) -> None:
        """Worker coroutine that processes requests from the queue.

        Args:
            worker_id: Identifier for this worker (for debugging).
        """
        while True:
            # Check for graceful shutdown before getting next request
            if self.stop_event and self.stop_event.is_set():
                break

            # Get next request from queue (blocks until available)
            try:
                _priority, _counter, request = await self.request_queue.get()
            except asyncio.CancelledError:
                # Worker was cancelled (normal shutdown)
                break

            try:
                # Wrap request resolution to catch transient exceptions
                try:
                    response: Response = (
                        await self.resolve_archive_request(request)
                        if isinstance(request, ArchiveRequest)
                        else await self.resolve_request(request)
                    )
                except TransientException as e:
                    # Handle transient errors via callback
                    if self.on_transient_exception:
                        # Invoke callback - if it returns False, stop this worker
                        should_continue = await self.on_transient_exception(e)
                        if not should_continue:
                            break
                        # If callback returns True, continue processing next request
                        continue
                    else:
                        # No callback provided - propagate exception normally
                        raise

                # Handle Callable continuations (convert to string)
                continuation_name = (
                    request.continuation
                    if isinstance(request.continuation, str)
                    else getattr(
                        request.continuation,
                        "__name__",
                        str(request.continuation),
                    )
                )

                continuation_method: Callable[
                    [Response],
                    Generator[ScraperYield[ScraperReturnDatatype], None, None],
                ] = self.scraper.get_continuation(continuation_name)

                # Wrap continuation execution to catch structural errors
                try:
                    for item in continuation_method(response):
                        match item:
                            case ParsedData():
                                data = item.unwrap()
                                await self.handle_data(data)
                            case NavigatingRequest():
                                await self.enqueue_request(item, response)
                            case NonNavigatingRequest() | ArchiveRequest():
                                await self.enqueue_request(item, request)
                            case None:
                                pass
                            case _:
                                # This should never happen if ScraperYield type is correct,
                                # but provides a safety net during development
                                assert_never(item)
                except HTMLStructuralAssumptionException as e:
                    # Handle structural errors via callback
                    if self.on_structural_error:
                        # Invoke callback - if it returns False, stop this worker
                        should_continue = await self.on_structural_error(e)
                        if not should_continue:
                            break
                        # If callback returns True, continue processing next request
                    else:
                        # No callback provided - propagate exception normally
                        raise
            finally:
                # Always mark task as done to allow join() to complete
                self.request_queue.task_done()

    async def enqueue_request(
        self, new_request: BaseRequest, context: Response | BaseRequest
    ) -> None:
        """Enqueue a new request, resolving it from the given context.

        Check for duplicates using duplicate_check callback before enqueuing.

        For NavigatingRequest yields: context is the Response
        For NonNavigatingRequest yields: context is the originating request
        For ArchiveRequest yields: context is the Response

        Args:
            new_request: The new request to enqueue.
            context: Response or originating request for URL resolution.
        """
        # Use the request's resolve_from method with the appropriate context
        resolved_request = new_request.resolve_from(context)  # type: ignore

        # Check for duplicates before enqueuing
        dedup_key = resolved_request.deduplication_key
        match dedup_key:
            case None:
                pass
            case SkipDeduplicationCheck():
                pass
            case str():
                if self.duplicate_check and not await self.duplicate_check(
                    dedup_key
                ):
                    return

        # Push onto queue with priority and counter for stable ordering
        async with self._queue_lock:
            await self.request_queue.put(
                (
                    resolved_request.priority,
                    self._queue_counter,
                    resolved_request,
                )
            )
            self._queue_counter += 1

    async def resolve_request(self, request: BaseRequest) -> Response:
        """Fetch a BaseRequest and return the Response.

        The request's URL should already be absolute (resolved by
        enqueue_request or provided as an absolute URL in get_entry).

        Args:
            request: The BaseRequest to fetch.

        Returns:
            Response containing the HTTP response data.

        Raises:
            HTMLResponseAssumptionException: If server returns 5xx status code.
            RequestTimeoutException: If request times out.
        """

        # Apply modify_request interceptor chain
        modified_request = request
        for interceptor in self.interceptors:
            result = await interceptor.modify_request(modified_request)
            if isinstance(result, Response):
                # Short-circuit! Skip HTTP and remaining request interceptors
                response = result
                # Still apply modify_response chain to short-circuited response
                for resp_interceptor in reversed(self.interceptors):
                    response = await resp_interceptor.modify_response(
                        response, request
                    )
                return response
            modified_request = result

        # Use the modified request for HTTP
        # Note: Permanent headers/cookies are already merged into request.headers
        # and request.cookies by BaseRequest.__post_init__
        http_params = modified_request.request

        # Prepare content and data parameters for httpx
        # httpx uses 'content' for raw bytes and 'data' for form data (dict)
        request_data = http_params.data
        content_param: bytes | None = (
            request_data if isinstance(request_data, bytes) else None
        )
        data_param: dict[str, Any] | None = (
            cast(dict[str, Any], request_data)
            if isinstance(request_data, dict)
            else None
        )

        # Catch httpx timeout exceptions and convert to RequestTimeoutException
        try:
            http_response = await self._client.request(
                method=http_params.method.value,
                url=http_params.url,
                headers=http_params.headers,
                cookies=http_params.cookies,
                content=content_param,
                data=data_param,
            )
        except httpx.TimeoutException as e:
            # Convert httpx timeout to our RequestTimeoutException
            # Extract timeout value from exception or use default
            timeout_seconds = 30.0  # Default timeout
            raise RequestTimeoutException(
                url=http_params.url,
                timeout_seconds=timeout_seconds,
            ) from e

        # Check for server errors (5xx status codes)
        # 429 (Too Many Requests) is handled by rate limiter interceptor
        if http_response.status_code >= 500:
            raise HTMLResponseAssumptionException(
                status_code=http_response.status_code,
                expected_codes=[200],
                url=http_params.url,
            )

        response = Response(
            status_code=http_response.status_code,
            headers=dict(http_response.headers),
            content=http_response.content,
            text=http_response.text,
            url=http_params.url,
            request=modified_request,
        )

        # Apply modify_response interceptor chain (in reverse order)
        for interceptor in reversed(self.interceptors):
            response = await interceptor.modify_response(response, request)

        return response

    async def resolve_archive_request(
        self, request: ArchiveRequest
    ) -> ArchiveResponse:
        """Fetch an ArchiveRequest, download the file, and return an ArchiveResponse.

        This method fetches the file, calls the on_archive callback to save it
        to local storage, and returns an ArchiveResponse with the file_url field
        populated.

        Args:
            request: The ArchiveRequest to fetch.

        Returns:
            ArchiveResponse containing the HTTP response data and local file path.
        """
        http_response = await self.resolve_request(request)

        # Use on_archive callback to save the file
        file_url = await self.on_archive(
            http_response.content,
            request.request.url,
            request.expected_type,
            self.storage_dir,
        )

        return ArchiveResponse(
            status_code=http_response.status_code,
            headers=dict(http_response.headers),
            content=http_response.content,
            text=http_response.text,
            url=request.request.url,
            request=request,
            file_url=file_url,
        )

    async def handle_data(self, data: ScraperReturnDatatype) -> None:
        # Validate deferred data if present
        if isinstance(data, DeferredValidation):
            try:
                validated_data: ScraperReturnDatatype = (
                    data.confirm()
                )  # ty: ignore[invalid-assignment]
                # Increment data counter on successful validation
                # Validation succeeded - send to on_data callback
                if self.on_data:
                    await self.on_data(validated_data)
            except DataFormatAssumptionException:
                # Validation failed - use callback hierarchy
                if self.on_invalid_data:
                    await self.on_invalid_data(data)
                else:
                    # No callbacks - re-raise the exception
                    raise
        else:
            # Increment data counter for non-validated data
            # Not deferred validation - invoke callback if provided
            if self.on_data:
                await self.on_data(data)
