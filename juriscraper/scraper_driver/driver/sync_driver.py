"""Synchronous driver implementation.

This module contains the sync driver that processes scraper generators.
It evolves across the 29 steps of the design documentation.

Step 1: A simple function that runs a scraper generator and collects results.
Step 2: A class-based driver that handles NavigatingRequest, fetches pages,
        and calls continuation methods by name.
Step 3: Tracks current_location and handles NonNavigatingRequest.
Step 4: Handles ArchiveRequest to download and save files locally.
Step 5: No driver changes - accumulated_data flows through requests automatically.
Step 6: No driver changes - aux_data flows through requests automatically.
Step 7: Adds on_data callback for side effects (persistence, logging) when data yielded.
Step 9: Adds on_invalid_data callback for handling validation failures.
Step 10: Adds on_transient_exception callback for handling transient errors.
Step 11: Adds interceptors for request/response transformation with short-circuit support.
Step 12: Adds rate limiting interceptor with adaptive rate reduction.
Step 13: Adds on_archive callback for customizing file archival behavior.
Step 14: Adds on_run_start and on_run_complete lifecycle hooks for tracking scraper runs.
Step 15: Replaces list queue with heapq priority queue for memory optimization.
Step 16: Adds deduplication_key field to requests and duplicate_check callback for preventing duplicate requests.
"""

import heapq
import logging
import threading
from collections.abc import Callable, Generator
from pathlib import Path
from tempfile import gettempdir
from typing import Generic, TypeVar
from urllib.parse import urlparse

import httpx
from typing_extensions import assert_never

from juriscraper.scraper_driver.common.deferred_validation import (
    DeferredValidation,
)
from juriscraper.scraper_driver.common.exceptions import (
    DataFormatAssumptionException,
    HTMLResponseAssumptionException,
    RequestTimeoutException,
    ScraperAssumptionException,
    TransientException,
)
from juriscraper.scraper_driver.common.interceptors import SyncInterceptor
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

# =============================================================================
# Step 2: Class-based Driver with HTTP Support
# =============================================================================
# Step 3: current_location tracking and NonNavigatingRequest support
# Step 4: ArchiveRequest handling for file downloads
# Step 9: Data validation with on_invalid_data callback


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


def default_archive_callback(
    content: bytes, url: str, expected_type: str | None, storage_dir: Path
) -> str:
    """Default callback for archiving downloaded files.

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


class SyncDriver(Generic[ScraperReturnDatatype]):
    """Synchronous driver for running scrapers.

    This Step 4 driver:
    - Maintains a request queue (BaseRequest, not just NavigatingRequest)
    - Fetches URLs using httpx
    - Looks up continuation methods by name
    - Each request carries its own current_location and ancestry
    - Uses exhaustive pattern matching for scraper yields
    - Handles ArchiveRequest to download and save files locally

    Example usage:
        from tests.scraper_driver.utils import collect_results

        callback, results = collect_results()
        driver = SyncDriver(scraper, on_data=callback)
        driver.run()
        # Results are now in the results list
    """

    def __init__(
        self,
        scraper: BaseScraper[ScraperReturnDatatype],
        storage_dir: Path | None = None,
        interceptors: list["SyncInterceptor"] | None = None,
        on_data: Callable[
            [ScraperReturnDatatype],
            None,
        ]
        | None = None,
        on_structural_error: Callable[["ScraperAssumptionException"], bool]
        | None = None,
        on_invalid_data: Callable[[DeferredValidation], None] | None = None,
        on_transient_exception: Callable[["TransientException"], bool]
        | None = None,
        on_archive: Callable[[bytes, str, str | None, Path], str]
        | None = None,
        on_run_start: Callable[[str], None] | None = None,
        on_run_complete: Callable[[str, str, Exception | None], None]
        | None = None,
        duplicate_check: Callable[[str], bool] | None = None,
        stop_event: threading.Event | None = None,
    ) -> None:
        """Initialize the driver.

        Args:
            scraper: Scraper instance with continuation methods.
            storage_dir: Directory for storing downloaded files. If None, uses system temp directory.
            interceptors: List of interceptors to apply to requests and responses. Interceptors
                are applied in order for requests, and in reverse order for responses.
                Order matters - for example, cache should come before rate limiter.
            on_data: Optional callback invoked when ParsedData is yielded and validated. Useful for
                persistence, logging, or other side effects. The callback receives the
                unwrapped data from ParsedData.
            on_structural_error: Optional callback invoked when HTMLStructuralAssumptionException
                is raised during scraping. The callback receives the exception and should return
                True to continue scraping or False to stop. If not provided, exceptions propagate
                normally and stop the scraper.
            on_invalid_data: Optional callback invoked when data fails validation. If not provided,
                invalid data is sent to on_data callback (if present), otherwise validation
                exceptions propagate normally.
            on_transient_exception: Optional callback invoked when TransientException is raised
                during HTTP requests. The callback receives the exception and should return True
                to continue scraping or False to stop. If not provided, exceptions propagate
                normally and stop the scraper.
            on_archive: Optional callback invoked when files are archived. Receives content (bytes),
                url (str), expected_type (str | None), and storage_dir (Path). Should return the
                local file path where the file was saved. If not provided, uses default_archive_callback.
            on_run_start: Optional callback invoked when the scraper run starts. Receives scraper_name (str).
            on_run_complete: Optional callback invoked when the scraper run completes. Receives
                scraper_name (str), status ("completed" | "error"),
                and error (Exception | None).
            duplicate_check: Optional callback invoked before enqueuing a request. Receives the
                deduplication_key (str) and should return True to enqueue the request or False to
                skip it. If not provided, all requests are enqueued (no deduplication).
            stop_event: Optional threading.Event for graceful shutdown. When set, the driver
                will stop processing after completing the current request.
        """
        self.scraper = scraper
        # Step 15: Use heapq for priority queue (min heap)
        # Each entry is (priority, counter, request) for stable FIFO ordering
        self.request_queue: list[tuple[int, int, BaseRequest]] = []
        self._queue_counter = 0  # For FIFO tie-breaking within same priority
        # Step 16: Track seen deduplication keys for default duplicate checking
        self._seen_keys: set[str] = set()
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

        # Initialize httpx client for reuse across requests
        self._client = httpx.Client()

    def run(self) -> None:
        """Run the scraper starting from the scraper's entry point.

        Data is passed to the on_data callback as it is yielded. If you need to
        collect results, use a callback that appends to a list (see
        tests/design/utils.py::collect_results for a helper function).
        """

        # Step 14: Fire on_run_start callback
        scraper_name = self.scraper.__class__.__name__
        if self.on_run_start:
            self.on_run_start(scraper_name)

        status = "completed"
        error: Exception | None = None

        try:
            entry_request = self.scraper.get_entry()
            # Step 15: Initialize priority queue with entry request
            self.request_queue = []
            heapq.heappush(
                self.request_queue,
                (entry_request.priority, self._queue_counter, entry_request),
            )
            self._queue_counter += 1

            while self.request_queue:
                # Check for graceful shutdown before processing next request
                if self.stop_event and self.stop_event.is_set():
                    break

                # Step 15: Pop from heap (lowest priority first)
                _priority, _counter, request = heapq.heappop(
                    self.request_queue
                )

                # Step 10: Wrap request resolution to catch transient exceptions
                try:
                    response: Response = (
                        self.resolve_archive_request(request)
                        if isinstance(request, ArchiveRequest)
                        else self.resolve_request(request)
                    )
                except TransientException as e:
                    # Step 10: Handle transient errors via callback
                    if self.on_transient_exception:
                        # Invoke callback - if it returns False, stop scraping
                        should_continue = self.on_transient_exception(e)
                        if not should_continue:
                            return
                        # If callback returns True, continue processing next request
                        continue
                    else:
                        # No callback provided - propagate exception normally
                        raise

                # Step 19: Handle Callable continuations (convert to string)
                continuation_name = (
                    request.continuation
                    if isinstance(request.continuation, str)
                    else request.continuation.__name__
                )

                continuation_method: Callable[
                    [Response],
                    Generator[ScraperYield[ScraperReturnDatatype], None, None],
                ] = self.scraper.get_continuation(continuation_name)

                # Step 8: Wrap continuation execution to catch structural errors
                try:
                    for item in continuation_method(response):
                        match item:
                            case ParsedData():
                                data = item.unwrap()
                                self.handle_data(data)
                            case NavigatingRequest():
                                self.enqueue_request(item, response)
                            case NonNavigatingRequest() | ArchiveRequest():
                                self.enqueue_request(item, request)
                            case None:
                                pass
                            case _:
                                # This should never happen if ScraperYield type is correct,
                                # but provides a safety net during development
                                assert_never(
                                    item
                                )  # ty: ignore[type-assertion-failure]
                except ScraperAssumptionException as e:
                    # Step 8: Handle structural errors via callback
                    if self.on_structural_error:
                        # Invoke callback - if it returns False, stop scraping
                        should_continue = self.on_structural_error(e)
                        if not should_continue:
                            return
                        # If callback returns True, continue processing next request
                    else:
                        # No callback provided - propagate exception normally
                        raise

        except Exception as e:
            # Step 14: Capture error for on_run_complete
            status = "error"
            error = e
            raise
        finally:
            # Step 14: Fire on_run_complete callback
            if self.on_run_complete:
                self.on_run_complete(
                    scraper_name,
                    status,
                    error,
                )

    def enqueue_request(
        self, new_request: BaseRequest, context: Response | BaseRequest
    ) -> None:
        """Enqueue a new request, resolving it from the given context.

        Step 16: Check for duplicates using duplicate_check callback before enqueuing.

        For NavigatingRequest yields: context is the Response
        For NonNavigatingRequest yields: context is the originating request
        For ArchiveRequest yields: context is the Response

        Args:
            new_request: The new request to enqueue.
            context: Response or originating request for URL resolution.
        """
        # Use the request's resolve_from method with the appropriate context
        resolved_request = new_request.resolve_from(context)  # type: ignore

        # Step 16: Check for duplicates before enqueuing
        dedup_key = resolved_request.deduplication_key

        match dedup_key:
            case None:
                pass
            case SkipDeduplicationCheck():
                pass
            case str():
                if self.duplicate_check and not self.duplicate_check(
                    dedup_key
                ):
                    return

        # Step 15: Push onto heap with priority and counter for stable ordering
        heapq.heappush(
            self.request_queue,
            (resolved_request.priority, self._queue_counter, resolved_request),
        )
        self._queue_counter += 1

    def resolve_request(self, request: BaseRequest) -> Response:
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

        # Step 11: Apply modify_request interceptor chain
        modified_request = request
        for interceptor in self.interceptors:
            result = interceptor.modify_request(modified_request)
            if isinstance(result, Response):
                # Short-circuit! Skip HTTP and remaining request interceptors
                response = result
                # Still apply modify_response chain to short-circuited response
                for resp_interceptor in reversed(self.interceptors):
                    response = resp_interceptor.modify_response(
                        response, request
                    )
                return response
            modified_request = result

        # Use the modified request for HTTP
        # Note: Permanent headers/cookies are already merged into request.headers
        # and request.cookies by BaseRequest.__post_init__
        http_params = modified_request.request

        # Step 10: Catch httpx timeout exceptions and convert to RequestTimeoutException
        try:
            http_response = self._client.request(
                method=http_params.method.value,
                url=http_params.url,
                headers=http_params.headers,
                cookies=http_params.cookies,
                content=http_params.data
                if isinstance(http_params.data, bytes)
                else None,
                data=http_params.data  # ty: ignore[invalid-argument-type]
                if isinstance(http_params.data, dict)
                else None,
            )
        except httpx.TimeoutException as e:
            # Convert httpx timeout to our RequestTimeoutException
            # Extract timeout value from exception or use default
            timeout_seconds = 30.0  # Default timeout
            raise RequestTimeoutException(
                url=http_params.url,
                timeout_seconds=timeout_seconds,
            ) from e

        # Step 10: Check for server errors (5xx status codes)
        # Step 12: 429 (Too Many Requests) is handled by rate limiter interceptor
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

        # Step 11: Apply modify_response interceptor chain (in reverse order)
        for interceptor in reversed(self.interceptors):
            response = interceptor.modify_response(response, request)

        return response

    def resolve_archive_request(
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
        http_response = self.resolve_request(request)

        # Step 13: Use on_archive callback to save the file
        file_url = self.on_archive(
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

    def handle_data(self, data: ScraperReturnDatatype) -> None:
        # Step 9: Validate deferred data if present
        if isinstance(data, DeferredValidation):
            try:
                validated_data: ScraperReturnDatatype = (
                    data.confirm()
                )  # ty: ignore[invalid-assignment]
                # Validation succeeded - send to on_data callback
                if self.on_data:
                    self.on_data(validated_data)
            except DataFormatAssumptionException:
                # Validation failed - use callback hierarchy
                if self.on_invalid_data:
                    self.on_invalid_data(data)
                else:
                    # No callbacks - re-raise the exception
                    raise
        else:
            # Step 7: Not deferred validation - invoke callback if provided
            if self.on_data:
                self.on_data(data)
