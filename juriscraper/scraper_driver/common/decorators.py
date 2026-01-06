"""Step decorators for scraper methods using argument inspection.

Step 19 introduces a flexible @step decorator that uses argument inspection
to determine what to inject into scraper methods. Instead of having separate
decorators for each content type (lxml, json, text, etc.), a single decorator
inspects the function signature and injects values based on parameter names.

Supported parameter names:
- response: The Response object
- request: The current BaseRequest
- previous_request: The parent request from the chain
- accumulated_data: Data collected across the request chain (from request)
- aux_data: Navigation metadata like tokens, session data (from request)
- json_content: Response content parsed as JSON
- lxml_tree: Response content parsed as CheckedHtmlElement
- text: Response content as string
- local_filepath: Local file path from ArchiveResponse (None if not archive)

The decorator also handles:
- Attaching priority metadata to functions
- Auto-resolving Callable continuations to string names
- Automatic yielding from wrapped generators
"""

import inspect
import json
from collections.abc import Callable, Generator
from functools import wraps
from typing import Any, TypeVar

from lxml import html as lxml_html

from juriscraper.scraper_driver.common.checked_html import CheckedHtmlElement
from juriscraper.scraper_driver.common.exceptions import (
    ScraperAssumptionException,
)
from juriscraper.scraper_driver.data_types import (
    ArchiveResponse,
    BaseRequest,
    Response,
    ScraperYield,
)

T = TypeVar("T")


class StepMetadata:
    """Metadata attached to scraper step methods by @step decorator.

    Attributes:
        priority: Priority hint for queue ordering (lower = higher priority).
        encoding: Character encoding for text/HTML decoding.
    """

    def __init__(self, priority: int = 9, encoding: str = "utf-8"):
        self.priority = priority
        self.encoding = encoding


def _parse_json(response: Response) -> Any:
    """Parse JSON from response content.

    Args:
        response: The HTTP response.

    Returns:
        Parsed JSON data (dict, list, or other JSON types).

    Raises:
        ScraperAssumptionException: If JSON parsing fails.
    """
    try:
        text = response.text or response.content.decode("utf-8")
        return json.loads(text)
    except Exception as e:
        raise ScraperAssumptionException(
            f"Failed to parse JSON: {e}",
            request_url=response.url,
            context={"error": str(e)},
        ) from e


def _parse_html(
    response: Response, encoding: str = "utf-8"
) -> CheckedHtmlElement:
    """Parse HTML from response content.

    Args:
        response: The HTTP response.
        encoding: Character encoding for decoding.

    Returns:
        CheckedHtmlElement parsed from response content.

    Raises:
        ScraperAssumptionException: If HTML parsing fails.
    """
    try:
        content = response.content.decode(encoding)
        return CheckedHtmlElement(lxml_html.fromstring(content), response.url)
    except ValueError as e:
        # If decoding fails (e.g., XML with encoding declaration),
        # try passing bytes directly to lxml
        if "encoding declaration" in str(e):
            try:
                return CheckedHtmlElement(
                    lxml_html.fromstring(response.content), response.url
                )
            except Exception as e2:
                raise ScraperAssumptionException(
                    f"Failed to parse HTML/XML: {e2}",
                    request_url=response.url,
                    context={"encoding": encoding, "error": str(e2)},
                ) from e2
        else:
            raise ScraperAssumptionException(
                f"Failed to parse HTML: {e}",
                request_url=response.url,
                context={"encoding": encoding, "error": str(e)},
            ) from e
    except Exception as e:
        raise ScraperAssumptionException(
            f"Failed to parse HTML: {e}",
            request_url=response.url,
            context={"encoding": encoding, "error": str(e)},
        ) from e


def _get_text(response: Response, encoding: str = "utf-8") -> str:
    """Get text content from response.

    Args:
        response: The HTTP response.
        encoding: Character encoding for decoding.

    Returns:
        Response text as string.
    """
    if response.text is not None:
        return response.text
    return response.content.decode(encoding)


def _process_yielded_request(yielded: Any) -> Any:
    """Process a yielded BaseRequest to resolve Callable continuations.

    When a decorated function yields a BaseRequest with a Callable continuation,
    this resolves it to the function name and attaches the target step's priority.

    Args:
        yielded: The value yielded by the step.

    Returns:
        The processed yield value.
    """
    if (
        isinstance(yielded, BaseRequest)
        and callable(yielded.continuation)
        and not isinstance(yielded.continuation, str)
    ):
        # Get the target function's step metadata (if decorated with @step)
        target_metadata = get_step_metadata(yielded.continuation)

        # Resolve Callable to function name
        func_name = yielded.continuation.__name__
        # Note: We use object.__setattr__ because dataclasses are frozen
        object.__setattr__(yielded, "continuation", func_name)

        # If the yielded request doesn't have a priority set,
        # inherit from the target step's metadata
        if yielded.priority == 9 and target_metadata is not None:
            object.__setattr__(yielded, "priority", target_metadata.priority)

    return yielded


def step(
    func: Callable[..., Generator[ScraperYield, None, None]] | None = None,
    *,
    priority: int = 9,
    encoding: str = "utf-8",
) -> Any:
    """Decorator for scraper step methods with automatic argument injection.

    This decorator inspects the function signature and injects values based on
    parameter names:

    - response: The Response object
    - request: The current BaseRequest
    - previous_request: The parent request from the chain (if available)
    - accumulated_data: Data collected across the request chain (from request)
    - aux_data: Navigation metadata like tokens, session data (from request)
    - json_content: Response content parsed as JSON
    - lxml_tree: Response content parsed as CheckedHtmlElement
    - text: Response content as string
    - local_filepath: Local file path from ArchiveResponse (None otherwise)

    Example:
        @step
        def parse_page(self, lxml_tree: CheckedHtmlElement, response: Response):
            # lxml_tree and response are automatically injected
            cases = lxml_tree.checked_xpath("//div[@class='case']", "cases")
            for case in cases:
                yield ParsedData(...)

        @step(priority=5)
        def parse_api(self, json_content: dict, response: Response):
            # json_content and response are automatically injected
            for item in json_content['items']:
                yield ParsedData(...)

        @step
        def parse_with_callable(self, text: str):
            # Can yield requests with Callable continuations
            yield NavigatingRequest(
                url="/next",
                continuation=self.parse_next_page  # Callable!
            )

    Args:
        func: The scraper step method to decorate (when used without parens).
        priority: Priority hint for queue ordering (lower = higher priority).
        encoding: Character encoding for text/HTML decoding.

    Returns:
        Decorated function with automatic argument injection.

    Raises:
        ScraperAssumptionException: If content parsing fails.
    """

    def decorator(
        fn: Callable[..., Generator[ScraperYield, None, None]],
    ) -> Callable[..., Generator[ScraperYield, None, None]]:
        # Inspect the function signature to determine what to inject
        sig = inspect.signature(fn)
        param_names = [p.name for p in sig.parameters.values()]

        # Create metadata
        metadata = StepMetadata(priority=priority, encoding=encoding)

        @wraps(fn)
        def wrapper(
            scraper_self: Any,
            response: Response,
            *args: Any,
            **kwargs: Any,
        ) -> Generator[ScraperYield, None, None]:
            # Build kwargs for injection based on parameter names
            injected_kwargs: dict[str, Any] = {}

            if "response" in param_names:
                injected_kwargs["response"] = response

            if "request" in param_names:
                injected_kwargs["request"] = response.request

            if "previous_request" in param_names:
                # Get the previous request from the chain
                if response.request.previous_requests:
                    injected_kwargs["previous_request"] = (
                        response.request.previous_requests[-1]
                    )
                else:
                    injected_kwargs["previous_request"] = None

            if "accumulated_data" in param_names:
                injected_kwargs["accumulated_data"] = (
                    response.request.accumulated_data
                )

            if "aux_data" in param_names:
                injected_kwargs["aux_data"] = response.request.aux_data

            # Content transformations (lazy - only parse if requested)
            if "json_content" in param_names:
                injected_kwargs["json_content"] = _parse_json(response)

            if "lxml_tree" in param_names:
                injected_kwargs["lxml_tree"] = _parse_html(response, encoding)

            if "text" in param_names:
                injected_kwargs["text"] = _get_text(response, encoding)

            if "local_filepath" in param_names:
                if isinstance(response, ArchiveResponse):
                    injected_kwargs["local_filepath"] = response.file_url
                else:
                    injected_kwargs["local_filepath"] = None

            # Call the original function with injected kwargs
            gen = fn(scraper_self, *args, **injected_kwargs, **kwargs)

            # Yield from the generator, processing requests to resolve Callables
            for yielded in gen:
                processed = _process_yielded_request(yielded)
                yield processed

        # Attach metadata to the wrapper
        wrapper._step_metadata = metadata  # type: ignore[attr-defined]
        return wrapper

    # Support both @step and @step(priority=5) syntax
    if func is not None:
        return decorator(func)
    return decorator


def get_step_metadata(func: Callable[..., Any]) -> StepMetadata | None:
    """Get step metadata from a decorated method.

    Args:
        func: A potentially decorated scraper step method.

    Returns:
        StepMetadata if the method is decorated, None otherwise.
    """
    return getattr(func, "_step_metadata", None)


def is_step(func: Callable[..., Any]) -> bool:
    """Check if a method is a decorated step.

    Args:
        func: A method to check.

    Returns:
        True if the method has step decorator metadata.
    """
    return get_step_metadata(func) is not None
