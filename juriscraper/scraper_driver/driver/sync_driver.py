"""Synchronous driver implementation.

This module contains the sync driver that processes scraper generators.
It evolves across the 29 steps of the design documentation.

- Step 1: A simple function that runs a scraper generator and collects results.
- Step 2: A class-based driver that handles NavigatingRequest, fetches pages,
  and calls continuation methods by name.
- Step 3: Tracks current_location and handles NonNavigatingRequest.
- Step 4: Handles ArchiveRequest to download and save files locally.
- Step 5: No driver changes - accumulated_data flows through requests automatically.
- Step 6: No driver changes - aux_data flows through requests automatically.
- Step 7: Adds on_data callback for side effects (persistence, logging) when data yielded.
- Step 9: Adds on_invalid_data callback for handling validation failures.
- Step 10: Adds on_transient_exception callback for handling transient errors.
- Step 11: Adds interceptors for request/response transformation with short-circuit support.
- Step 12: Adds rate limiting interceptor with adaptive rate reduction.
- Step 13: Adds on_archive callback for customizing file archival behavior.
- Step 14: Adds on_run_start and on_run_complete lifecycle hooks for tracking scraper runs.
- Step 15: Replaces list queue with heapq priority queue for memory optimization.
- Step 16: Adds deduplication_key field to requests and duplicate_check callback for preventing duplicate requests.
"""

from __future__ import annotations

import heapq
import logging
import threading
from collections.abc import Callable, Generator
from pathlib import Path
from tempfile import gettempdir
from typing import TYPE_CHECKING, Generic, TypeVar
from urllib.parse import urlparse

from typing_extensions import assert_never

from juriscraper.scraper_driver.common.deferred_validation import (
    DeferredValidation,
)
from juriscraper.scraper_driver.common.exceptions import (
    DataFormatAssumptionException,
    ScraperAssumptionException,
    TransientException,
)
from juriscraper.scraper_driver.common.request_manager import (
    SyncRequestManager,
)
from juriscraper.scraper_driver.data_types import (
    ArchiveRequest,
    ArchiveResponse,
    BaseRequest,
    BaseScraper,
    FlowControl,
    HTTPRequestParams,
    NavigatingRequest,
    NonNavigatingRequest,
    ParsedData,
    Response,
    ResumeStep,
    ScraperYield,
    SkipDeduplicationCheck,
    SpeculationContext,
    SpeculativeRequest,
)

if TYPE_CHECKING:
    from juriscraper.scraper_driver.common.interceptors import SyncInterceptor

# =============================================================================
# Step 2: Class-based Driver with HTTP Support
# =============================================================================
# Step 3: current_location tracking and NonNavigatingRequest support
# Step 4: ArchiveRequest handling for file downloads
# Step 9: Data validation with on_invalid_data callback
# Step 19: SpeculativeRequest support with on_speculation_response callback


logger = logging.getLogger(__name__)

# Type alias for speculation response callback
# Called when a SpeculativeRequest is yielded (first with response=None for early check)
# or after receiving an HTTP response.
# Returns FlowControl to indicate how to proceed:
# - CONTINUE: Continue speculation (send True to generator)
# - STOP: Stop speculation (send False to generator)
# - AWAIT_MORE_INFO: Need response to decide (park generator, make HTTP request)
OnSpeculationResponse = Callable[[Response | None, str, int], FlowControl]

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
        request_manager: SyncRequestManager | None = None,
        interceptors: list[SyncInterceptor] | None = None,
        on_data: Callable[
            [ScraperReturnDatatype],
            None,
        ]
        | None = None,
        on_structural_error: Callable[[ScraperAssumptionException], bool]
        | None = None,
        on_invalid_data: Callable[[DeferredValidation], None] | None = None,
        on_transient_exception: Callable[[TransientException], bool]
        | None = None,
        on_archive: Callable[[bytes, str, str | None, Path], str]
        | None = None,
        on_run_start: Callable[[str], None] | None = None,
        on_run_complete: Callable[[str, str, Exception | None], None]
        | None = None,
        duplicate_check: Callable[[str], bool] | None = None,
        stop_event: threading.Event | None = None,
        on_speculation_response: OnSpeculationResponse | None = None,
    ) -> None:
        """Initialize the driver.

        Args:
            scraper: Scraper instance with continuation methods.
            storage_dir: Directory for storing downloaded files. If None, uses system temp directory.
            request_manager: SyncRequestManager for handling HTTP requests. If provided,
                interceptors parameter is ignored. If None, a default manager is created
                using the interceptors parameter.
            interceptors: List of interceptors to apply to requests and responses.
                Only used if request_manager is None. Interceptors are applied in order
                for requests, and in reverse order for responses.
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
            on_speculation_response: Optional callback invoked when a SpeculativeRequest receives
                a non-2xx response. Receives (response, continuation_name) and should return True
                to resume the generator with True (continue speculation) or False to resume with
                False (stop speculation). Not called for 2xx responses (which always continue).
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

        # Set up request manager - either use provided one or create default
        if request_manager is not None:
            self.request_manager = request_manager
            self._owns_request_manager = False
        else:
            # Create default request manager with interceptors
            self.request_manager = SyncRequestManager(
                interceptors=interceptors,
                ssl_context=scraper.get_ssl_context(),
            )
            self._owns_request_manager = True

        self.on_data = on_data
        self.on_structural_error = on_structural_error
        self.on_invalid_data = on_invalid_data
        self.on_transient_exception = on_transient_exception
        self.on_archive = on_archive or default_archive_callback
        self.on_run_start = on_run_start
        self.on_run_complete = on_run_complete
        self.duplicate_check = duplicate_check
        self.stop_event = stop_event
        self.on_speculation_response = on_speculation_response

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
            # Initialize priority queue with entry requests from get_entry generator
            self.request_queue = []
            for entry_request in self.scraper.get_entry():
                heapq.heappush(
                    self.request_queue,
                    (
                        entry_request.priority,
                        self._queue_counter,
                        entry_request,
                    ),
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

                # Step 19: Use match/case for exhaustive request type handling
                match request:
                    case ResumeStep():
                        # Resume a parked generator (no HTTP)
                        self._execute_resume(request)

                    case SpeculativeRequest() if request.speculation_context:
                        # Speculative request with context: resolve and enqueue resume
                        self._resolve_speculative(request)

                    case (
                        NavigatingRequest()
                        | NonNavigatingRequest()
                        | ArchiveRequest()
                        | SpeculativeRequest()
                    ):
                        # Normal request flow (includes SpeculativeRequest without context)
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
                                should_continue = self.on_transient_exception(
                                    e
                                )
                                if not should_continue:
                                    return
                                continue
                            else:
                                raise

                        # Step 19: Handle Callable continuations (convert to string)
                        continuation_name = (
                            request.continuation
                            if isinstance(request.continuation, str)
                            else request.continuation.__name__
                        )

                        continuation_method = self.scraper.get_continuation(
                            continuation_name
                        )

                        # Process the generator
                        gen = continuation_method(response)
                        self._process_generator(
                            gen, response, request, continuation_name
                        )

                    case _:
                        # Exhaustive match - should never reach here
                        assert_never(request)  # type: ignore[arg-type]

        except Exception as e:
            # Step 14: Capture error for on_run_complete
            status = "error"
            error = e
            raise
        finally:
            # Close request manager if we own it
            if self._owns_request_manager:
                self.request_manager.close()

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
                    # Step 19: If this is a SpeculativeRequest with context,
                    # we still need to resume the parked generator with False
                    if (
                        isinstance(resolved_request, SpeculativeRequest)
                        and resolved_request.speculation_context
                    ):
                        self._enqueue_resume_step(
                            resolved_request.speculation_context, False
                        )
                    return

        # Step 15: Push onto heap with priority and counter for stable ordering
        heapq.heappush(
            self.request_queue,
            (resolved_request.priority, self._queue_counter, resolved_request),
        )
        self._queue_counter += 1

    def resolve_request(self, request: BaseRequest) -> Response:
        """Fetch a BaseRequest and return the Response.

        Delegates to the request manager for HTTP handling.

        Args:
            request: The BaseRequest to fetch.

        Returns:
            Response containing the HTTP response data.

        Raises:
            HTMLResponseAssumptionException: If server returns 5xx status code.
            httpx.TimeoutException: If request times out (for retry handling).
        """
        return self.request_manager.resolve_request(request)

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

    # =========================================================================
    # Step 19: Speculative Request Support
    # =========================================================================

    def _process_generator(
        self,
        gen: Generator[ScraperYield, bool | None, None],
        response: Response,
        parent_request: BaseRequest,
        continuation_name: str,
    ) -> None:
        """Process generator, parking on SpeculativeRequest.

        Uses simple iteration (for item in gen). Values are only sent to
        generators via _execute_resume() when processing a ResumeStep.

        For SpeculativeRequests, uses early-continue optimization:
        - First calls on_speculation_response with response=None
        - If CONTINUE: enqueue request and immediately resume generator with True
        - If AWAIT_MORE_INFO: park generator, enqueue request with context
        - If STOP: immediately resume generator with False (no HTTP request)

        Args:
            gen: The generator from the continuation method.
            response: The Response that triggered this continuation.
            parent_request: The request that initiated this continuation.
            continuation_name: Name of the continuation method (for context tracking).
        """
        try:
            for item in gen:
                match item:
                    case SpeculativeRequest():
                        # Early-continue optimization: check if we can decide without HTTP
                        if self.on_speculation_response:
                            flow = self.on_speculation_response(
                                None, continuation_name, item.speculative_id
                            )
                            if flow == FlowControl.CONTINUE:
                                # Can continue without waiting for response
                                # Enqueue the underlying request
                                self.enqueue_request(item, response)
                                # Immediately resume generator with True
                                try:
                                    next_item = gen.send(True)
                                    # Continue processing with the new item
                                    self._handle_yield_and_continue(
                                        gen,
                                        next_item,
                                        response,
                                        parent_request,
                                        continuation_name,
                                    )
                                except StopIteration:
                                    pass
                                return
                            elif flow == FlowControl.STOP:
                                # Stop speculation without HTTP request
                                try:
                                    next_item = gen.send(False)
                                    self._handle_yield_and_continue(
                                        gen,
                                        next_item,
                                        response,
                                        parent_request,
                                        continuation_name,
                                    )
                                except StopIteration:
                                    pass
                                return
                            # AWAIT_MORE_INFO: fall through to park generator

                        # Park the generator and enqueue with context
                        ctx = SpeculationContext(
                            parked_generator=gen,
                            parent_request=parent_request,
                            original_response=response,
                            originating_continuation=continuation_name,
                        )
                        self.enqueue_request(item.with_context(ctx), response)
                        return  # Generator parked - stop processing

                    case ParsedData():
                        self.handle_data(item.unwrap())
                    case NavigatingRequest():
                        self.enqueue_request(item, response)
                    case NonNavigatingRequest() | ArchiveRequest():
                        self.enqueue_request(item, parent_request)
                    case None:
                        pass
                    case _:
                        assert_never(item)
        except ScraperAssumptionException as e:
            # Step 8: Handle structural errors via callback
            if self.on_structural_error:
                should_continue = self.on_structural_error(e)
                if not should_continue:
                    return
            else:
                raise

    def _resolve_speculative(self, request: SpeculativeRequest) -> None:
        """Execute speculative request, determine success, enqueue resume, process continuation.

        This is called when a SpeculativeRequest has been parked (AWAIT_MORE_INFO).
        Now we have the HTTP response and need to make the final decision.

        Flow:
        - 2xx response: always success (True), call continuation
        - Non-2xx response: call on_speculation_response callback to decide

        Args:
            request: The SpeculativeRequest with speculation_context attached.
        """
        ctx = request.speculation_context
        assert ctx is not None  # Guaranteed by match guard in run()

        # Step 10: Wrap request resolution to catch transient exceptions
        try:
            response = self.resolve_request(request)
        except TransientException as e:
            if self.on_transient_exception:
                should_continue = self.on_transient_exception(e)
                if not should_continue:
                    return
                # Enqueue resume with False - transient error means don't continue
                self._enqueue_resume_step(ctx, False)
                return
            else:
                raise

        # Get continuation name
        continuation_name = (
            request.continuation
            if isinstance(request.continuation, str)
            else request.continuation.__name__
        )

        # Check for hidden failures in successful responses
        # If fails_successfully returns False, treat as status 555
        if (
            200 <= response.status_code < 300
            and not self.scraper.fails_successfully(response)
        ):
            response.status_code = 555

        # Determine success based on status code
        is_success_status = 200 <= response.status_code < 300

        if is_success_status:
            # 2xx response: always continue
            should_continue = True
        elif self.on_speculation_response:
            # Non-2xx: let callback decide with the actual response
            # Use originating_continuation (the @step(speculative=True) method) not continuation_name
            # This matches the config keys which are named after the speculative step method
            flow = self.on_speculation_response(
                response, ctx.originating_continuation, request.speculative_id
            )
            should_continue = flow == FlowControl.CONTINUE
        else:
            # Non-2xx with no callback: don't continue
            should_continue = False

        # Enqueue ResumeStep FIRST (before processing continuation)
        # Priority inherited from parent request to maintain traversal order
        self._enqueue_resume_step(ctx, should_continue)

        # THEN process continuation if approved AND response was successful
        if should_continue and is_success_status:
            continuation = self.scraper.get_continuation(continuation_name)
            gen = continuation(response)
            self._process_generator(gen, response, request, continuation_name)

    def _enqueue_resume_step(
        self, ctx: SpeculationContext, predicate_result: bool
    ) -> None:
        """Enqueue a ResumeStep to resume a parked generator.

        Args:
            ctx: The speculation context containing the parked generator.
            predicate_result: The value to send to the generator (True/False).
        """
        from juriscraper.scraper_driver.data_types import HttpMethod

        resume_step = ResumeStep(
            request=HTTPRequestParams(
                method=HttpMethod.GET, url=""
            ),  # Dummy, not used
            continuation=ctx.originating_continuation,
            priority=ctx.parent_request.priority,  # Inherit from original
            speculation_context=ctx,
            predicate_result=predicate_result,
        )
        heapq.heappush(
            self.request_queue,
            (resume_step.priority, self._queue_counter, resume_step),
        )
        self._queue_counter += 1

    def _execute_resume(self, resume_step: ResumeStep) -> None:
        """Execute a ResumeStep: resume the parked generator with the result.

        Args:
            resume_step: The ResumeStep containing the context and result.
        """
        ctx = resume_step.speculation_context
        assert ctx is not None  # ResumeStep always has speculation_context
        send_value = resume_step.predicate_result

        gen = ctx.parked_generator
        response = ctx.original_response
        parent_request = ctx.parent_request
        continuation_name = ctx.originating_continuation

        # Send the value and continue processing remaining yields
        try:
            item = gen.send(send_value)
        except StopIteration:
            return

        # Handle the first item after resume, then loop for rest
        self._handle_yield_and_continue(
            gen, item, response, parent_request, continuation_name
        )

    def _handle_yield_and_continue(
        self,
        gen: Generator[ScraperYield, bool | None, None],
        item: ScraperYield,
        response: Response,
        parent_request: BaseRequest,
        continuation_name: str,
    ) -> None:
        """Handle a yield and continue processing the generator.

        Called after _execute_resume sends a value. Processes the first yielded
        item, then continues with simple iteration for remaining items.

        Args:
            gen: The generator to continue processing.
            item: The first item yielded after send().
            response: The original response for context.
            parent_request: The parent request for context.
            continuation_name: The continuation name for context.
        """
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
                        self.enqueue_request(item.with_context(ctx), response)
                        return
                    case ParsedData():
                        self.handle_data(item.unwrap())
                    case NavigatingRequest():
                        self.enqueue_request(item, response)
                    case NonNavigatingRequest() | ArchiveRequest():
                        self.enqueue_request(item, parent_request)
                    case None:
                        pass
                    case _:
                        assert_never(item)

                try:
                    item = next(gen)  # Simple iteration after the initial send
                except StopIteration:
                    break
        except ScraperAssumptionException as e:
            if self.on_structural_error:
                should_continue = self.on_structural_error(e)
                if not should_continue:
                    return
            else:
                raise
