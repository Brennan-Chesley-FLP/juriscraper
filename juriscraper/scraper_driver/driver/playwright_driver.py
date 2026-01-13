"""Playwright-based driver implementation.

This module contains the Playwright driver that processes scraper generators
using a real browser. It mirrors AsyncDriver but executes requests via
Playwright instead of httpx.

Key differences from AsyncDriver:
- Uses Playwright Page objects instead of httpx client
- Manages tab lifecycle with reference counting
- Executes JavaScript and renders pages
- POST requests use form injection + click
- TransientException only on browser/page crashes
"""

import asyncio
import logging
import uuid
from collections.abc import Awaitable, Callable, Generator
from dataclasses import dataclass
from pathlib import Path
from tempfile import gettempdir
from typing import Any, Generic, Literal, TypeVar
from urllib.parse import urlparse

from playwright.async_api import (
    Browser,
    BrowserContext,
    Page,
    Playwright,
    async_playwright,
)
from playwright.async_api import (
    Error as PlaywrightError,
)
from playwright.async_api import (
    Response as PlaywrightResponse,
)
from typing_extensions import assert_never

from juriscraper.scraper_driver.common.deferred_validation import (
    DeferredValidation,
)
from juriscraper.scraper_driver.common.exceptions import (
    DataFormatAssumptionException,
    HTMLStructuralAssumptionException,
    TransientException,
)
from juriscraper.scraper_driver.common.interceptors import AsyncInterceptor
from juriscraper.scraper_driver.data_types import (
    ArchiveRequest,
    ArchiveResponse,
    BaseRequest,
    BaseScraper,
    HttpMethod,
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

logger = logging.getLogger(__name__)

# Type alias for speculation response callback (async version)
OnSpeculationResponseAsync = Callable[[Response, str], Awaitable[bool]]

ScraperReturnDatatype = TypeVar("ScraperReturnDatatype")

# Key used in accumulated_data to track tab origin
_TAB_KEY = "_playwright_tab_key"


@dataclass
class TabState:
    """State for a browser tab managed by the driver."""

    page: Page
    url: str
    ref_count: int  # Number of pending child requests
    response_headers: dict[str, str]  # Captured from last navigation
    response_status: int  # HTTP status code


async def default_archive_callback(
    content: bytes, url: str, expected_type: str | None, storage_dir: Path
) -> str:
    """Default async callback for archiving downloaded files."""
    parsed_url = urlparse(url)
    path_parts = Path(parsed_url.path).parts
    valid_parts = [p for p in path_parts if p and p not in (".", "/")]

    if valid_parts:
        filename = valid_parts[-1]
    else:
        ext = {"pdf": ".pdf", "audio": ".mp3"}.get(expected_type or "", "")
        filename = f"download_{hash(url)}{ext}"

    file_path = storage_dir / filename
    file_path.write_bytes(content)
    return str(file_path)


class PlaywrightDriver(Generic[ScraperReturnDatatype]):
    """Playwright-based driver for running scrapers in a real browser.

    This driver mirrors AsyncDriver but uses Playwright for HTTP execution,
    enabling JavaScript rendering and browser-based interactions.

    Example usage:
        async with PlaywrightDriver(scraper, on_data=callback) as driver:
            await driver.run()
    """

    def __init__(
        self,
        scraper: BaseScraper[ScraperReturnDatatype],
        # Playwright-specific options
        browser_type: Literal["chromium", "firefox", "webkit"] = "chromium",
        channel: str | None = None,
        headless: bool = True,
        user_agent: str | None = None,
        viewport: dict[str, int] | None = None,
        # Standard driver options
        storage_dir: Path | None = None,
        interceptors: list[AsyncInterceptor] | None = None,
        on_data: Callable[[ScraperReturnDatatype], Awaitable[None]]
        | None = None,
        on_structural_error: Callable[
            [HTMLStructuralAssumptionException], Awaitable[bool]
        ]
        | None = None,
        on_invalid_data: Callable[[DeferredValidation], Awaitable[None]]
        | None = None,
        on_transient_exception: Callable[[TransientException], Awaitable[bool]]
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
        on_speculation_response: OnSpeculationResponseAsync | None = None,
    ) -> None:
        """Initialize the PlaywrightDriver.

        Args:
            scraper: Scraper instance with continuation methods.
            browser_type: Browser engine to use (chromium, firefox, webkit).
            channel: Browser channel (e.g., "chrome", "msedge" for native browsers).
            headless: Whether to run browser in headless mode.
            user_agent: Custom user agent string.
            viewport: Browser viewport size {"width": int, "height": int}.
            storage_dir: Directory for storing downloaded files.
            interceptors: List of async interceptors (limited support in Playwright).
            on_data: Async callback for parsed data.
            on_structural_error: Async callback for structural errors.
            on_invalid_data: Async callback for validation failures.
            on_transient_exception: Async callback for transient errors.
            on_archive: Async callback for file archival.
            on_run_start: Async callback when run starts.
            on_run_complete: Async callback when run completes.
            duplicate_check: Async callback for deduplication.
            stop_event: Event for graceful shutdown.
            on_speculation_response: Async callback for speculation decisions.
        """
        self.scraper = scraper
        self.browser_type = browser_type
        self.channel = channel
        self.headless = headless
        self.user_agent = user_agent
        self.viewport = viewport

        # Request queue (same as AsyncDriver)
        self.request_queue: asyncio.PriorityQueue[
            tuple[int, int, BaseRequest]
        ] = asyncio.PriorityQueue()
        self._queue_counter = 0
        self._queue_lock = asyncio.Lock()

        # Storage
        self.storage_dir = (
            storage_dir or Path(gettempdir()) / "juriscraper_files"
        )
        self.storage_dir.mkdir(parents=True, exist_ok=True)

        # Callbacks
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
        self.on_speculation_response = on_speculation_response

        # Playwright state (initialized in start())
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None

        # Tab management
        self._tab_registry: dict[str, TabState] = {}

    # =========================================================================
    # Lifecycle Management
    # =========================================================================

    async def start(self) -> None:
        """Launch browser and create context."""
        self._playwright = await async_playwright().start()

        launcher = getattr(self._playwright, self.browser_type)
        self._browser = await launcher.launch(
            headless=self.headless,
            channel=self.channel,
        )

        context_options: dict[str, Any] = {}
        if self.user_agent:
            context_options["user_agent"] = self.user_agent
        if self.viewport:
            context_options["viewport"] = self.viewport

        self._context = await self._browser.new_context(**context_options)

    async def stop(self) -> None:
        """Close browser and cleanup."""
        # Close all tracked tabs
        for tab_state in list(self._tab_registry.values()):
            try:
                await tab_state.page.close()
            except PlaywrightError:
                pass  # Page may already be closed
        self._tab_registry.clear()

        if self._context:
            try:
                await self._context.close()
            except PlaywrightError:
                pass
            self._context = None

        if self._browser:
            try:
                await self._browser.close()
            except PlaywrightError:
                pass
            self._browser = None

        if self._playwright:
            try:
                await self._playwright.stop()
            except PlaywrightError:
                pass
            self._playwright = None

    async def __aenter__(self) -> "PlaywrightDriver[ScraperReturnDatatype]":
        """Context manager entry - launch browser."""
        await self.start()
        return self

    async def __aexit__(self, *args: Any) -> None:
        """Context manager exit - close browser."""
        await self.stop()

    # =========================================================================
    # Main Run Loop
    # =========================================================================

    async def run(self) -> None:
        """Run the scraper starting from the scraper's entry point."""
        if not self._context:
            raise RuntimeError(
                "Browser not started. Use 'async with driver:' or call start() first."
            )

        scraper_name = self.scraper.__class__.__name__
        if self.on_run_start:
            await self.on_run_start(scraper_name)

        status = "completed"
        error: Exception | None = None

        try:
            if self.stop_event and self.stop_event.is_set():
                return

            entry_request = self.scraper.get_entry()
            self.request_queue = asyncio.PriorityQueue()
            self._queue_counter = 0
            await self.request_queue.put(
                (entry_request.priority, self._queue_counter, entry_request)
            )
            self._queue_counter += 1

            # Process queue (single worker for now - tabs provide concurrency)
            while True:
                if self.stop_event and self.stop_event.is_set():
                    break

                try:
                    _priority, _counter, request = (
                        self.request_queue.get_nowait()
                    )
                except asyncio.QueueEmpty:
                    break

                try:
                    await self._process_request(request)
                finally:
                    self.request_queue.task_done()

        except Exception as e:
            status = "error"
            error = e
            raise
        finally:
            if self.on_run_complete:
                await self.on_run_complete(scraper_name, status, error)

    async def _process_request(self, request: BaseRequest) -> None:
        """Process a single request from the queue."""
        match request:
            case ResumeStep():
                await self._execute_resume(request)

            case SpeculativeRequest() if request.speculation_context:
                await self._resolve_speculative(request)

            case NavigatingRequest():
                await self._process_navigating_request(request)

            case NonNavigatingRequest():
                await self._process_non_navigating_request(request)

            case ArchiveRequest():
                await self._process_archive_request(request)

            case SpeculativeRequest():
                # SpeculativeRequest without context - treat as NavigatingRequest
                await self._process_navigating_request(request)

            case _:
                assert_never(request)  # type: ignore[arg-type]

    # =========================================================================
    # Tab Management
    # =========================================================================

    def _get_parent_tab_key(self, request: BaseRequest) -> str | None:
        """Get the tab key of the request's parent."""
        return request.accumulated_data.get(_TAB_KEY)

    async def _create_tab(
        self, request: BaseRequest, parent_key: str | None
    ) -> tuple[Page, str]:
        """Create a new tab for this request.

        Returns:
            Tuple of (page, tab_key)
        """
        assert self._context is not None

        page = await self._context.new_page()
        tab_key = str(uuid.uuid4())

        # Increment parent ref_count
        if parent_key and parent_key in self._tab_registry:
            self._tab_registry[parent_key].ref_count += 1

        return page, tab_key

    async def _release_tab(self, tab_key: str, parent_key: str | None) -> None:
        """Release a tab and potentially close parent."""
        # Close this tab
        if tab_key in self._tab_registry:
            tab_state = self._tab_registry.pop(tab_key)
            try:
                await tab_state.page.close()
            except PlaywrightError:
                pass

        # Decrement parent ref_count
        if parent_key and parent_key in self._tab_registry:
            parent_state = self._tab_registry[parent_key]
            parent_state.ref_count -= 1

            # Close parent if no more children
            if parent_state.ref_count == 0:
                self._tab_registry.pop(parent_key)
                try:
                    await parent_state.page.close()
                except PlaywrightError:
                    pass

    # =========================================================================
    # Request Resolution
    # =========================================================================

    def _is_crash_error(self, error: PlaywrightError) -> bool:
        """Check if error indicates browser/page crash."""
        crash_indicators = [
            "Target closed",
            "crashed",
            "Browser closed",
            "Context closed",
            "Page closed",
            "Connection closed",
        ]
        error_str = str(error)
        return any(indicator in error_str for indicator in crash_indicators)

    async def _navigate_and_capture(
        self, page: Page, url: str
    ) -> tuple[str, dict[str, str], int]:
        """Navigate to URL and capture response metadata.

        Returns:
            Tuple of (final_url, headers, status_code)
        """
        captured_headers: dict[str, str] = {}
        captured_status: int = 200

        async def capture_response(response: PlaywrightResponse) -> None:
            nonlocal captured_headers, captured_status
            if response.request.is_navigation_request():
                captured_headers = dict(response.headers)
                captured_status = response.status

        page.on("response", capture_response)

        try:
            await page.goto(url, wait_until="load")
        except PlaywrightError as e:
            if self._is_crash_error(e):
                raise TransientException(
                    f"Browser crashed during navigation to {url}: {e}"
                ) from e
            # Log non-crash errors but continue
            logger.warning(f"Navigation issue for {url}: {e}")
        finally:
            page.remove_listener("response", capture_response)

        return page.url, captured_headers, captured_status

    async def _post_and_capture(
        self, page: Page, url: str, data: dict[str, Any]
    ) -> tuple[str, dict[str, str], int]:
        """Navigate via POST using form injection + click.

        Returns:
            Tuple of (final_url, headers, status_code)
        """
        captured_headers: dict[str, str] = {}
        captured_status: int = 200

        async def capture_response(response: PlaywrightResponse) -> None:
            nonlocal captured_headers, captured_status
            if response.request.is_navigation_request():
                captured_headers = dict(response.headers)
                captured_status = response.status

        page.on("response", capture_response)

        try:
            # Inject form with hidden fields and submit button
            await page.evaluate(
                """
                ([url, fields]) => {
                    const form = document.createElement('form');
                    form.method = 'POST';
                    form.action = url;
                    form.id = '__playwright_post_form__';

                    for (const [key, value] of Object.entries(fields)) {
                        const input = document.createElement('input');
                        input.type = 'hidden';
                        input.name = key;
                        input.value = String(value);
                        form.appendChild(input);
                    }

                    const submit = document.createElement('button');
                    submit.type = 'submit';
                    submit.id = '__playwright_post_submit__';
                    submit.style.position = 'absolute';
                    submit.style.left = '-9999px';
                    form.appendChild(submit);

                    document.body.appendChild(form);
                }
                """,
                [url, data],
            )

            # Click submit to trigger navigation
            await page.click("#__playwright_post_submit__")
            await page.wait_for_load_state("load")

        except PlaywrightError as e:
            if self._is_crash_error(e):
                raise TransientException(
                    f"Browser crashed during POST to {url}: {e}"
                ) from e
            logger.warning(f"POST navigation issue for {url}: {e}")
        finally:
            page.remove_listener("response", capture_response)

        return page.url, captured_headers, captured_status

    async def _process_navigating_request(
        self, request: NavigatingRequest | SpeculativeRequest
    ) -> None:
        """Process a NavigatingRequest via browser navigation."""
        parent_key = self._get_parent_tab_key(request)
        page, tab_key = await self._create_tab(request, parent_key)
        http_params = request.request

        try:
            # POST requires form injection
            if http_params.method == HttpMethod.POST:
                # Need page context - navigate to parent URL first
                if parent_key and parent_key in self._tab_registry:
                    parent_url = self._tab_registry[parent_key].url
                    await page.goto(parent_url, wait_until="load")

                data = (
                    http_params.data
                    if isinstance(http_params.data, dict)
                    else {}
                )
                final_url, headers, status_code = await self._post_and_capture(
                    page, http_params.url, data
                )
            else:
                (
                    final_url,
                    headers,
                    status_code,
                ) = await self._navigate_and_capture(page, http_params.url)

            # Get rendered content
            content = await page.content()

            # Store tab state
            self._tab_registry[tab_key] = TabState(
                page=page,
                url=final_url,
                ref_count=0,
                response_headers=headers,
                response_status=status_code,
            )

            response = Response(
                status_code=status_code,
                headers=headers,
                content=content.encode("utf-8"),
                text=content,
                url=final_url,
                request=request,
            )

            # Get continuation
            continuation_name = self._get_continuation_name(request)
            continuation = self.scraper.get_continuation(continuation_name)
            gen = continuation(response)

            # Process generator with tab context
            await self._process_generator(
                gen, response, request, continuation_name, tab_key
            )

        except TransientException:
            await page.close()
            raise
        except Exception:
            await page.close()
            raise
        finally:
            # Release tab after processing
            await self._release_tab(tab_key, parent_key)

    async def _process_non_navigating_request(
        self, request: NonNavigatingRequest
    ) -> None:
        """Process a NonNavigatingRequest via Playwright's API context."""
        assert self._context is not None

        http_params = request.request
        method = http_params.method.value.lower()

        try:
            api_response = await self._context.request.fetch(
                http_params.url,
                method=method,
                headers=http_params.headers or {},
                data=http_params.data
                if isinstance(http_params.data, dict)
                else None,
            )
        except PlaywrightError as e:
            if self._is_crash_error(e):
                raise TransientException(
                    f"Browser crashed during fetch of {http_params.url}: {e}"
                ) from e
            raise

        body = await api_response.body()

        response = Response(
            status_code=api_response.status,
            headers=dict(api_response.headers),
            content=body,
            text=body.decode("utf-8", errors="replace"),
            url=http_params.url,
            request=request,
        )

        # Get parent tab key for context
        parent_key = self._get_parent_tab_key(request)

        continuation_name = self._get_continuation_name(request)
        continuation = self.scraper.get_continuation(continuation_name)
        gen = continuation(response)

        await self._process_generator(
            gen, response, request, continuation_name, parent_key
        )

    async def _process_archive_request(self, request: ArchiveRequest) -> None:
        """Process an ArchiveRequest - download file."""
        assert self._context is not None

        try:
            api_response = await self._context.request.get(request.request.url)
            content = await api_response.body()
        except PlaywrightError as e:
            if self._is_crash_error(e):
                raise TransientException(
                    f"Browser crashed during download of {request.request.url}: {e}"
                ) from e
            raise

        file_url = await self.on_archive(
            content,
            request.request.url,
            request.expected_type,
            self.storage_dir,
        )

        response = ArchiveResponse(
            status_code=api_response.status,
            headers=dict(api_response.headers),
            content=content,
            text="",
            url=request.request.url,
            request=request,
            file_url=file_url,
        )

        parent_key = self._get_parent_tab_key(request)
        continuation_name = self._get_continuation_name(request)
        continuation = self.scraper.get_continuation(continuation_name)
        gen = continuation(response)

        await self._process_generator(
            gen, response, request, continuation_name, parent_key
        )

    # =========================================================================
    # Generator Processing
    # =========================================================================

    def _get_continuation_name(self, request: BaseRequest) -> str:
        """Get continuation name from request."""
        if isinstance(request.continuation, str):
            return request.continuation
        return getattr(
            request.continuation, "__name__", str(request.continuation)
        )

    async def _process_generator(
        self,
        gen: Generator[ScraperYield, bool | None, None],
        response: Response,
        parent_request: BaseRequest,
        continuation_name: str,
        tab_key: str | None,
    ) -> None:
        """Process generator, parking on SpeculativeRequest."""
        try:
            for item in gen:
                match item:
                    case SpeculativeRequest():
                        ctx = SpeculationContext(
                            parked_generator=gen,
                            parent_request=parent_request,
                            original_response=response,
                            originating_continuation=continuation_name,
                        )
                        await self.enqueue_request(
                            item.with_context(ctx), response, tab_key
                        )
                        return

                    case ParsedData():
                        await self.handle_data(item.unwrap())

                    case NavigatingRequest():
                        await self.enqueue_request(item, response, tab_key)

                    case NonNavigatingRequest() | ArchiveRequest():
                        await self.enqueue_request(
                            item, parent_request, tab_key
                        )

                    case None:
                        pass

                    case _:
                        assert_never(item)

        except HTMLStructuralAssumptionException as e:
            if self.on_structural_error:
                should_continue = await self.on_structural_error(e)
                if not should_continue:
                    return
            else:
                raise

    async def enqueue_request(
        self,
        new_request: BaseRequest,
        context: Response | BaseRequest,
        tab_key: str | None,
    ) -> None:
        """Enqueue a new request with tab context."""
        import dataclasses

        resolved_request = new_request.resolve_from(context)  # type: ignore

        # Add tab key to accumulated_data
        if tab_key:
            resolved_request = dataclasses.replace(
                resolved_request,
                accumulated_data={
                    **resolved_request.accumulated_data,
                    _TAB_KEY: tab_key,
                },
            )

        # Check for duplicates
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
                    if (
                        isinstance(resolved_request, SpeculativeRequest)
                        and resolved_request.speculation_context
                    ):
                        await self._enqueue_resume_step(
                            resolved_request.speculation_context, False
                        )
                    return

        async with self._queue_lock:
            await self.request_queue.put(
                (
                    resolved_request.priority,
                    self._queue_counter,
                    resolved_request,
                )
            )
            self._queue_counter += 1

    async def handle_data(self, data: ScraperReturnDatatype) -> None:
        """Handle parsed data."""
        if isinstance(data, DeferredValidation):
            try:
                validated_data: ScraperReturnDatatype = data.confirm()  # type: ignore
                if self.on_data:
                    await self.on_data(validated_data)
            except DataFormatAssumptionException:
                if self.on_invalid_data:
                    await self.on_invalid_data(data)
                else:
                    raise
        else:
            if self.on_data:
                await self.on_data(data)

    # =========================================================================
    # Speculative Request Support
    # =========================================================================

    async def _resolve_speculative(self, request: SpeculativeRequest) -> None:
        """Execute speculative request and determine success."""
        ctx = request.speculation_context
        assert ctx is not None

        parent_key = self._get_parent_tab_key(request)
        page, tab_key = await self._create_tab(request, parent_key)
        http_params = request.request

        try:
            if http_params.method == HttpMethod.POST:
                if parent_key and parent_key in self._tab_registry:
                    parent_url = self._tab_registry[parent_key].url
                    await page.goto(parent_url, wait_until="load")

                data = (
                    http_params.data
                    if isinstance(http_params.data, dict)
                    else {}
                )
                final_url, headers, status_code = await self._post_and_capture(
                    page, http_params.url, data
                )
            else:
                (
                    final_url,
                    headers,
                    status_code,
                ) = await self._navigate_and_capture(page, http_params.url)

            content = await page.content()

            self._tab_registry[tab_key] = TabState(
                page=page,
                url=final_url,
                ref_count=0,
                response_headers=headers,
                response_status=status_code,
            )

            response = Response(
                status_code=status_code,
                headers=headers,
                content=content.encode("utf-8"),
                text=content,
                url=final_url,
                request=request,
            )

        except TransientException as e:
            await page.close()
            if self.on_transient_exception:
                should_continue = await self.on_transient_exception(e)
                if not should_continue:
                    return
                await self._enqueue_resume_step(ctx, False)
                return
            else:
                raise

        continuation_name = self._get_continuation_name(request)
        is_success = 200 <= status_code < 300

        if is_success:
            should_continue = True
        elif self.on_speculation_response:
            should_continue = await self.on_speculation_response(
                response, continuation_name
            )
        else:
            should_continue = False

        await self._enqueue_resume_step(ctx, should_continue)

        if should_continue and is_success:
            continuation = self.scraper.get_continuation(continuation_name)
            gen = continuation(response)
            await self._process_generator(
                gen, response, request, continuation_name, tab_key
            )

        await self._release_tab(tab_key, parent_key)

    async def _enqueue_resume_step(
        self, ctx: SpeculationContext, predicate_result: bool
    ) -> None:
        """Enqueue a ResumeStep to resume a parked generator."""
        resume_step = ResumeStep(
            request=HTTPRequestParams(method=HttpMethod.GET, url=""),
            continuation=ctx.originating_continuation,
            priority=ctx.parent_request.priority,
            speculation_context=ctx,
            predicate_result=predicate_result,
        )
        async with self._queue_lock:
            await self.request_queue.put(
                (resume_step.priority, self._queue_counter, resume_step)
            )
            self._queue_counter += 1

    async def _execute_resume(self, resume_step: ResumeStep) -> None:
        """Execute a ResumeStep: resume the parked generator."""
        ctx = resume_step.speculation_context
        assert ctx is not None

        gen = ctx.parked_generator
        response = ctx.original_response
        parent_request = ctx.parent_request
        continuation_name = ctx.originating_continuation
        parent_key = self._get_parent_tab_key(parent_request)

        try:
            item = gen.send(resume_step.predicate_result)
        except StopIteration:
            return

        await self._handle_yield_and_continue(
            gen, item, response, parent_request, continuation_name, parent_key
        )

    async def _handle_yield_and_continue(
        self,
        gen: Generator[ScraperYield, bool | None, None],
        item: ScraperYield,
        response: Response,
        parent_request: BaseRequest,
        continuation_name: str,
        tab_key: str | None,
    ) -> None:
        """Handle a yield and continue processing the generator."""
        try:
            while True:
                match item:
                    case SpeculativeRequest():
                        ctx = SpeculationContext(
                            parked_generator=gen,
                            parent_request=parent_request,
                            original_response=response,
                            originating_continuation=continuation_name,
                        )
                        await self.enqueue_request(
                            item.with_context(ctx), response, tab_key
                        )
                        return

                    case ParsedData():
                        await self.handle_data(item.unwrap())

                    case NavigatingRequest():
                        await self.enqueue_request(item, response, tab_key)

                    case NonNavigatingRequest() | ArchiveRequest():
                        await self.enqueue_request(
                            item, parent_request, tab_key
                        )

                    case None:
                        pass

                    case _:
                        assert_never(item)

                try:
                    item = next(gen)
                except StopIteration:
                    break

        except HTMLStructuralAssumptionException as e:
            if self.on_structural_error:
                should_continue = await self.on_structural_error(e)
                if not should_continue:
                    return
            else:
                raise
