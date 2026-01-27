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
- Attaching encoding, xsd, and json_model metadata for drivers to optionally use
- Auto-resolving Callable continuations to string names
- Automatic yielding from wrapped generators
"""

import inspect
import json
from collections.abc import Callable, Generator
from datetime import date
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
        xsd: Optional path to XSD schema file for structural validation hints.
        json_model: Optional dotted path to Pydantic model for JSON response validation.
    """

    def __init__(
        self,
        priority: int = 9,
        encoding: str = "utf-8",
        xsd: str | None = None,
        json_model: str | None = None,
    ):
        self.priority = priority
        self.encoding = encoding
        self.xsd = xsd
        self.json_model = json_model


class SpeculateMetadata:
    """Metadata attached to scraper methods by @speculate decorator.

    Attributes:
        observation_date: Date when metadata was last updated (e.g., when gap was observed).
        highest_observed: The highest ID observed to exist.
        largest_observed_gap: The largest gap observed in the sequence.
    """

    def __init__(
        self,
        observation_date: date | None = None,
        highest_observed: int = 1,
        largest_observed_gap: int = 10,
    ):
        self.observation_date = observation_date
        self.highest_observed = highest_observed
        self.largest_observed_gap = largest_observed_gap


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

    Passes raw bytes to lxml so it can auto-detect encoding from the HTML
    meta charset tag (e.g., <meta charset="windows-1252">). This handles
    pages that declare non-UTF-8 encodings correctly.

    Args:
        response: The HTTP response.
        encoding: Fallback encoding if lxml can't detect one (default utf-8).

    Returns:
        CheckedHtmlElement parsed from response content.

    Raises:
        ScraperAssumptionException: If HTML parsing fails.
    """
    try:
        # Pass raw bytes to lxml - it will detect encoding from:
        # 1. BOM
        # 2. XML declaration
        # 3. <meta charset="..."> or <meta http-equiv="Content-Type" content="...">
        # 4. Falls back to default if nothing found
        return CheckedHtmlElement(
            lxml_html.fromstring(response.content), response.url
        )
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
    func: Callable[..., Generator[ScraperYield, Any, None]] | None = None,
    *,
    priority: int = 9,
    encoding: str = "utf-8",
    xsd: str | None = None,
    json_model: str | None = None,
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

    Example::

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

        @step(xsd="schemas/court_page.xsd")
        def parse_court_page(self, lxml_tree: CheckedHtmlElement):
            # XSD reference available via get_step_metadata() for drivers
            # to optionally use when evaluating structural errors
            ...

        @step(json_model="api.publications.PublicationsResponse")
        def parse_api_response(self, json_content: dict):
            # JSON model reference available via get_step_metadata() for drivers
            # to optionally use for post-hoc validation
            ...

    Args:
        func: The scraper step method to decorate (when used without parens).
        priority: Priority hint for queue ordering (lower = higher priority).
        encoding: Character encoding for text/HTML decoding.
        xsd: Optional path to XSD schema file. Drivers may use this hint
            when evaluating structural assumption errors.
        json_model: Optional dotted path to Pydantic model (e.g.,
            "api.publications.PublicationsResponse"). Resolved relative to
            scraper package. Drivers may use this for post-hoc validation.

    Returns:
        Decorated function with automatic argument injection.

    Raises:
        ScraperAssumptionException: If content parsing fails.
    """

    def decorator(
        fn: Callable[..., Generator[ScraperYield, Any, None]],
    ) -> Callable[..., Generator[ScraperYield, bool | None, None]]:
        # Inspect the function signature to determine what to inject
        sig = inspect.signature(fn)
        param_names = [p.name for p in sig.parameters.values()]

        # Create metadata
        metadata = StepMetadata(
            priority=priority,
            encoding=encoding,
            xsd=xsd,
            json_model=json_model,
        )

        @wraps(fn)
        def wrapper(
            scraper_self: Any,
            response: Response,
            *args: Any,
            **kwargs: Any,
        ) -> Generator[ScraperYield, bool | None, None]:
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


def speculate(
    func: Callable[[Any, int], BaseRequest] | None = None,
    *,
    observation_date: date | None = None,
    highest_observed: int = 1,
    largest_observed_gap: int = 10,
) -> Any:
    """Decorator for functions that generate speculative requests from sequential IDs.

    The @speculate decorator marks functions that generate speculative requests.
    These functions accept a single integer parameter (the ID) and return a
    NavigatingRequest with is_speculative=True.

    Drivers use these functions to seed their initial queues and track which
    IDs have been successfully fetched.

    Example::

        @speculate(highest_observed=500, largest_observed_gap=20)
        def fetch_case(self, case_id: int) -> NavigatingRequest:
            return NavigatingRequest(
                url=f"/case/{case_id}",
                continuation=self.parse_case
            )

    Args:
        func: The function to decorate (when used without parens).
        observation_date: Date when metadata was last updated.
        highest_observed: The highest ID observed to exist (defaults to 1).
        largest_observed_gap: The largest gap observed in the sequence (defaults to 10).

    Returns:
        Decorated function with SpeculateMetadata attached.
    """

    def decorator(
        fn: Callable[[Any, int], BaseRequest],
    ) -> Callable[[Any, int], BaseRequest]:
        # Inspect the function signature
        sig = inspect.signature(fn)
        params = list(sig.parameters.values())

        # Validate: function should have exactly one parameter (besides self)
        # The first parameter should be 'self' for instance methods
        if len(params) < 1:
            raise TypeError(
                f"Speculate function '{fn.__name__}' must accept at least one parameter "
                f"(the ID). Signature: {sig}"
            )

        # For instance methods, we expect (self, id)
        # For standalone functions, we expect (id,)
        if len(params) == 1:
            # Standalone function - single ID parameter
            pass
        elif len(params) == 2:
            # Instance method - self + ID parameter
            pass
        else:
            raise TypeError(
                f"Speculate function '{fn.__name__}' must accept exactly one parameter "
                f"(the ID) in addition to self. Got {len(params) - 1} parameters. "
                f"Signature: {sig}"
            )

        # Create metadata
        metadata = SpeculateMetadata(
            observation_date=observation_date,
            highest_observed=highest_observed,
            largest_observed_gap=largest_observed_gap,
        )

        @wraps(fn)
        def wrapper(scraper_self: Any, id_value: int) -> BaseRequest:
            # Call the original function
            request = fn(scraper_self, id_value)

            # Ensure the returned value is a BaseRequest
            if not isinstance(request, BaseRequest):
                raise TypeError(
                    f"Speculate function '{fn.__name__}' must return a BaseRequest, "
                    f"got {type(request).__name__}"
                )

            # Use the speculative() method to create a copy with speculation fields set
            # This sets is_speculative=True and speculation_id=(func_name, id_value)
            return request.speculative(fn.__name__, id_value)

        # Attach metadata to the wrapper
        wrapper._speculate_metadata = metadata  # type: ignore[attr-defined]
        return wrapper

    # Support both @speculate and @speculate(...) syntax
    if func is not None:
        return decorator(func)
    return decorator


def get_speculate_metadata(
    func: Callable[..., Any],
) -> SpeculateMetadata | None:
    """Get speculate metadata from a decorated function.

    Args:
        func: A potentially decorated speculate function.

    Returns:
        SpeculateMetadata if the function is decorated, None otherwise.
    """
    return getattr(func, "_speculate_metadata", None)


def is_speculate(func: Callable[..., Any]) -> bool:
    """Check if a method is a decorated speculate function.

    Args:
        func: A method to check.

    Returns:
        True if the method has speculate decorator metadata.
    """
    return get_speculate_metadata(func) is not None
