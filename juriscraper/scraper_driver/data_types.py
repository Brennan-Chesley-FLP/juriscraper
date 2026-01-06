"""Data types for the scraper-driver architecture.

This module defines the core data types used for communication between
scrapers and drivers. These types are designed to be:

1. Exhaustive - Using Python 3.10's match statement to ensure all cases are handled
2. Serializable - Continuations are strings, not function references
3. Immutable - Dataclasses with frozen=True where appropriate

Step 1 introduces ParsedData.
Step 2 adds NavigatingRequest and Response.
Step 3 introduces BaseRequest, NonNavigatingRequest, and current_location tracking.
Step 4 adds ArchiveRequest and ArchiveResponse for file downloads.
Step 5 adds accumulated_data to BaseRequest with deep copy semantics.
Step 6 adds aux_data to BaseRequest for navigation metadata (tokens, session data).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Generator
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from http.cookiejar import CookieJar
from typing import (
    TYPE_CHECKING,
    Any,
    BinaryIO,
    ClassVar,
    Generic,
    TypeVar,
    cast,
)
from urllib.parse import quote, unquote, urljoin, urlparse, urlunparse

if TYPE_CHECKING:
    from juriscraper.scraper_driver.common.searchable import ScraperParams

# =============================================================================
# Step 1: ParsedData
# =============================================================================

T = TypeVar("T")
ScraperReturnType = TypeVar("ScraperReturnType")
ScraperParamType = TypeVar("ScraperParamType")


class ScraperStatus(Enum):
    """Status of a scraper's development lifecycle.

    Used for documentation and registry filtering.

    Values:
        IN_DEVELOPMENT: Scraper is being built, not ready for production.
        ACTIVE: Scraper is working and maintained.
        RETIRED: Scraper is no longer maintained (court changed, etc.).
    """

    IN_DEVELOPMENT = "in_development"
    ACTIVE = "active"
    RETIRED = "retired"


class BaseScraper(Generic[ScraperReturnType]):
    """Base class for all scrapers.

    Scrapers are generic over their return type, allowing drivers to
    be type-safe about what data they collect.

    Example:
        class MyScraper(BaseScraper[MyDataModel]):
            def parse_page(self, response: Response) -> Generator[ScraperYield, None, None]:
                yield ParsedData(MyDataModel(...))

    Class Attributes:
        court_ids: Set of court IDs this scraper covers (references courts.toml).
        court_url: The primary URL/origin for this scraper's court system.
        data_types: Set of data types this scraper produces (opinions, dockets, etc.).
        status: Development lifecycle status (IN_DEVELOPMENT, ACTIVE, RETIRED).
        version: Version string for this scraper (e.g., "2025-01-03").
        last_verified: Date when scraper was last verified working.
        oldest_record: Earliest date for which records are available.
        requires_auth: Whether authentication is required.
        msec_per_request_rate_limit: Minimum milliseconds between requests.
    """

    # === METADATA FOR AUTODOC ===
    # These ClassVars are used by the registry builder to generate documentation.

    court_ids: ClassVar[set[str]] = set()

    # Primary URL/origin for this scraper
    court_url: ClassVar[str] = ""

    # Data types produced by this scraper (e.g., {"opinions", "dockets"})
    data_types: ClassVar[set[str]] = set()

    # Scraper lifecycle status
    status: ClassVar[ScraperStatus] = ScraperStatus.IN_DEVELOPMENT

    # Version tracking
    version: ClassVar[str] = ""
    last_verified: ClassVar[str] = ""

    # Data availability
    oldest_record: ClassVar[date | None] = None

    # Optional metadata
    requires_auth: ClassVar[bool] = False
    msec_per_request_rate_limit: ClassVar[int | None] = None

    def get_entry(self) -> NavigatingRequest:
        """Create the initial request to start scraping.

        Subclasses should override this method to specify their entry
        point and initial continuation method.

        Args:
            url: The entry URL to start scraping from.

        Returns:
            A NavigatingRequest for the entry page.

        Raises:
            NotImplementedError: If the subclass doesn't override this method.
        """
        raise NotImplementedError(
            f"{self.__class__.__name__} must implement get_entry()"
        )

    def get_continuation(
        self, name: str
    ) -> Callable[
        [Response], Generator[ScraperYield[ScraperReturnType], None, None]
    ]:
        """Resolve a continuation name to the actual method.

        This method looks up a continuation by name and returns the
        bound method. It provides a single point for continuation
        resolution, making it easy to add validation or caching later.

        Args:
            name: The name of the continuation method.

        Returns:
            The bound method that can be called with a Response.

        Raises:
            AttributeError: If the continuation method doesn't exist.
        """
        method = getattr(self, name)
        return cast(
            Callable[
                [Response],
                Generator[ScraperYield[ScraperReturnType], None, None],
            ],
            method,
        )

    @classmethod
    def params(cls) -> ScraperParams:
        """Build a params object for configuring scraper filters.

        Introspects the scraper's generic type parameter(s) to find data
        models, then creates a params container with filter proxies for
        each model's searchable fields.

        Searchable fields are annotated in Pydantic models using
        typing.Annotated with DateRange, SetFilter, or UniqueMatch markers.

        Example:
            from typing import Annotated

            class CaseData(ScrapedData):
                date_filed: Annotated[date, DateRange()]
                case_type: Annotated[str, SetFilter()]

            class MyScraper(BaseScraper[CaseData]):
                ...

            # Build params and set filters
            params = MyScraper.params()
            params.CaseData.date_filed.gte = date(2024, 1, 1)
            params.CaseData.case_type.values = {"civil", "criminal"}

            # Disable a data type entirely
            params.CaseData = None

        Returns:
            A ScraperParams instance with model proxies for each data type.
        """
        from juriscraper.scraper_driver.common.searchable import (
            build_params_for_scraper,
        )

        return build_params_for_scraper(cls)


@dataclass(frozen=True)
class ParsedData(Generic[T]):
    """Data yielded by a scraper after parsing a page.

    This is a simple wrapper around a bit of returned data to enable exhaustive pattern
    matching in the driver. When a scraper yields data, it should wrap
    it in ParsedData so the driver can distinguish it from other yield
    types (like NavigatingRequest).

    Example:
        yield ParsedData({"docket": "BCC-2024-001", "case_name": "..."})
    """

    data: T
    __match_args__ = ("data",)

    def unwrap(self) -> T:
        return self.data


# =============================================================================
# Step 2: NavigatingRequest and Response
# =============================================================================
# Step 3: BaseRequest, NonNavigatingRequest, and current_location tracking
# Step 4: ArchiveRequest and ArchiveResponse for file downloads
# Step 5: accumulated_data with deep copy semantics


class HttpMethod(Enum):
    """HTTP methods supported by scrapers."""

    GET = "GET"
    OPTIONS = "OPTIONS"
    POST = "POST"
    PUT = "PUT"
    DELETE = "DELETE"
    PATCH = "PATCH"
    HEAD = "HEAD"


# Type aliases for complex parameter types
QueryParams = dict[str, Any] | list[tuple[str, Any]] | bytes | None
RequestData = dict[str, Any] | list[tuple[str, Any]] | bytes | BinaryIO | None
HeadersType = dict[str, str] | None
CookiesType = dict[str, str] | CookieJar | None
FileTuple = (
    tuple[str, BinaryIO]
    | tuple[str, BinaryIO, str]
    | tuple[str, BinaryIO, str, dict[str, str]]
)
FilesType = dict[str, BinaryIO | FileTuple] | None
AuthType = tuple[str, str] | None
TimeoutType = float | tuple[float, float] | None
ProxiesType = dict[str, str] | None
VerifyType = bool | str
CertType = str | tuple[str, str] | None


@dataclass(frozen=True)
class HTTPRequestParams:
    """Parameters for an HTTP request, mirroring the requests library interface.

    :param method: HTTP method for the request: ``GET``, ``OPTIONS``, ``HEAD``,
        ``POST``, ``PUT``, ``PATCH``, or ``DELETE``.
    :param url: URL for the request.
    :param params: (optional) Dictionary, list of tuples or bytes to send
        in the query string for the request.
    :param data: (optional) Dictionary, list of tuples, bytes, or file-like
        object to send in the body of the request.
    :param json: (optional) A JSON serializable Python object to send in the
        body of the request.
    :param headers: (optional) Dictionary of HTTP Headers to send with the request.
    :param cookies: (optional) Dict or CookieJar object to send with the request.
    :param files: (optional) Dictionary of ``'name': file-like-objects``
        (or ``{'name': file-tuple}``) for multipart encoding upload.
        ``file-tuple`` can be a 2-tuple ``('filename', fileobj)``,
        3-tuple ``('filename', fileobj, 'content_type')``
        or a 4-tuple ``('filename', fileobj, 'content_type', custom_headers)``,
        where ``'content_type'`` is a string defining the content type of the
        given file and ``custom_headers`` a dict-like object containing
        additional headers to add for the file.
    :param auth: (optional) Auth tuple to enable Basic/Digest/Custom HTTP Auth.
    :param timeout: (optional) How many seconds to wait for the server to send
        data before giving up, as a float, or a (connect timeout, read timeout) tuple.
    :param allow_redirects: (optional) Boolean. Enable/disable
        GET/OPTIONS/POST/PUT/PATCH/DELETE/HEAD redirection. Defaults to ``True``.
    :param proxies: (optional) Dictionary mapping protocol to the URL of the proxy.
    :param verify: (optional) Either a boolean, in which case it controls whether
        we verify the server's TLS certificate, or a string, in which case it
        must be a path to a CA bundle to use. Defaults to ``True``.
    :param stream: (optional) if ``False``, the response content will be
        immediately downloaded.
    :param cert: (optional) if String, path to ssl client cert file (.pem).
        If Tuple, ('cert', 'key') pair.
    """

    method: HttpMethod
    url: str
    params: QueryParams = None
    data: RequestData = None
    json: Any = None
    headers: HeadersType = None
    cookies: CookiesType = None
    files: FilesType = None
    auth: AuthType = None
    timeout: TimeoutType = None
    allow_redirects: bool = True
    proxies: ProxiesType = None
    verify: VerifyType = True
    stream: bool = False
    cert: CertType = None


def _generate_deduplication_key(request_params: HTTPRequestParams) -> str:
    """Generate a deduplication key from HTTPRequestParams.

    Step 16: Default deduplication key is a SHA256 hash of:
    - Full URL with parameters
    - Request data (sorted if dict/list of tuples)

    Args:
        request_params: The HTTP request parameters.

    Returns:
        A SHA256 hex digest string for deduplication.
    """
    # Start with the full URL
    url_str = request_params.url

    # Add query parameters if present
    if request_params.params:
        # Sort params for consistent hashing
        if isinstance(request_params.params, dict):
            sorted_params = sorted(request_params.params.items())
            params_str = str(sorted_params)
        elif isinstance(request_params.params, list | tuple):
            # List of tuples
            sorted_params = sorted(request_params.params)  # type: ignore
            params_str = str(sorted_params)
        else:
            # bytes or other type - use as-is
            params_str = str(request_params.params)
        url_str = f"{url_str}?{params_str}"

    # Add request data if present
    data_str = ""
    if request_params.data:
        if isinstance(request_params.data, dict):
            # Sort dict by key
            sorted_data = sorted(request_params.data.items())
            data_str = str(sorted_data)
        elif isinstance(request_params.data, list):
            # Assume list of tuples, sort by first element
            sorted_data = sorted(
                request_params.data,
                key=lambda x: x[0] if isinstance(x, tuple) else x,
            )
            data_str = str(sorted_data)
        else:
            data_str = str(request_params.data)

    # Add JSON data if present
    if request_params.json is not None:
        if isinstance(request_params.json, dict):
            # Sort dict by key for consistent hashing
            json_str = json.dumps(request_params.json, sort_keys=True)
        else:
            json_str = json.dumps(request_params.json)
        data_str = f"{data_str}|{json_str}"

    # Combine URL and data, then hash
    combined = f"{url_str}|{data_str}"
    return hashlib.sha256(combined.encode("utf-8")).hexdigest()


class SkipDeduplicationCheck:
    """Skip deduplication checks."""

    pass


@dataclass(frozen=True)
class BaseRequest:
    """Base class for all request types.

    Provides common functionality for URL resolution and HTTP parameters.
    Each request tracks its current_location and request ancestry.

    Attributes:
        request: HTTP request parameters (URL, method, headers, etc.).
        continuation: The method name to call with the Response, or a Callable.
                     When a Callable is provided, the @step decorator will automatically
                     resolve it to the function's name.
        current_location: The URL context for resolving relative URLs.
        previous_requests: Chain of requests that led to this one.
        accumulated_data: Data collected across the request chain.
        aux_data: Navigation metadata (tokens, session data) needed for requests.
        priority: Priority for request queue ordering (lower = higher priority).
        deduplication_key: Key for deduplication (defaults to hash of URL and data).
        permanent: Persistent data (cookies, headers) that flows through the request chain.
    """

    request: HTTPRequestParams
    continuation: str | Callable[..., Any]
    current_location: str = ""
    previous_requests: list[BaseRequest] = field(default_factory=list)
    accumulated_data: dict[str, Any] = field(default_factory=dict)
    aux_data: dict[str, Any] = field(default_factory=dict)
    priority: int = 9
    deduplication_key: str | None | SkipDeduplicationCheck = None
    permanent: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Deep copy accumulated_data, aux_data, and permanent to prevent unintended sharing.

        Step 16: Also generates default deduplication_key if not provided.
        Step 18: Also deep copies permanent dict and merges permanent headers/cookies
                 into the HTTPRequestParams.

        When a scraper yields multiple requests from the same method, they might
        share the same accumulated_data or aux_data dicts. Without deep copy,
        mutations in one branch would affect sibling branches. This is critical
        for correctness.

        Example problem without deep copy:
            shared_data = {"case_name": "Ant v. Bee"}
            shared_aux = {"session_token": "abc123"}
            yield NavigatingRequest(url="/detail/1", accumulated_data=shared_data, aux_data=shared_aux)
            yield NavigatingRequest(url="/detail/2", accumulated_data=shared_data, aux_data=shared_aux)
            # If detail/1 mutates the dicts, detail/2 sees the mutation - BUG!

        The deep copy ensures each request gets its own independent copy of the data.
        """
        # Since the dataclass is frozen, we need to use object.__setattr__
        object.__setattr__(
            self, "accumulated_data", deepcopy(self.accumulated_data)
        )
        object.__setattr__(self, "aux_data", deepcopy(self.aux_data))
        object.__setattr__(self, "permanent", deepcopy(self.permanent))

        # Step 18: Merge permanent headers and cookies into HTTPRequestParams
        if self.permanent:
            new_request = self._merge_permanent_into_request()
            object.__setattr__(self, "request", new_request)

        # Step 16: Generate default deduplication key if not provided
        if self.deduplication_key is None:
            object.__setattr__(
                self,
                "deduplication_key",
                _generate_deduplication_key(self.request),
            )

    def _merge_permanent_into_request(self) -> HTTPRequestParams:
        """Merge permanent headers and cookies into the HTTPRequestParams.

        Returns:
            A new HTTPRequestParams with permanent data merged in.
        """
        req = self.request
        merged_headers: dict[str, str] | None = None
        # Merge headers
        if "headers" in self.permanent:
            merged_headers = dict(req.headers) if req.headers else {}
            merged_headers.update(self.permanent["headers"])
        else:
            merged_headers = req.headers

        # Merge cookies (only if both are dicts)
        if "cookies" in self.permanent:
            if req.cookies is None:
                merged_cookies: CookiesType = dict(self.permanent["cookies"])
            elif isinstance(req.cookies, dict):
                merged_cookies = dict(req.cookies)
                merged_cookies.update(self.permanent["cookies"])
            else:
                # CookieJar - can't merge, keep original
                merged_cookies = req.cookies
        else:
            merged_cookies = req.cookies

        return HTTPRequestParams(
            method=req.method,
            url=req.url,
            params=req.params,
            data=req.data,
            json=req.json,
            headers=merged_headers,
            cookies=merged_cookies,
            files=req.files,
            auth=req.auth,
            timeout=req.timeout,
            allow_redirects=req.allow_redirects,
            proxies=req.proxies,
            verify=req.verify,
            stream=req.stream,
            cert=req.cert,
        )

    def resolve_url(self, current_location: str) -> str:
        """Resolve the URL against the current location.

        Uses urllib.parse.urljoin to handle both relative and absolute URLs:
        - Absolute URLs (http://..., https://...) are returned unchanged
        - Relative URLs are resolved against current_location

        Args:
            current_location: The current page URL.

        Returns:
            The absolute URL.
        """
        # Normalize URL encoding
        parsed = urlparse(self.request.url)

        # Decode then encode to normalize (prevents double-encoding)
        # safe='/:?&=' preserves URL structure while encoding special chars
        decoded_path = unquote(parsed.path)
        encoded_path = quote(decoded_path, safe="/")

        decoded_query = unquote(parsed.query)
        encoded_query = quote(decoded_query, safe="=&")

        reencoded_url = urlunparse(
            (
                parsed.scheme,
                parsed.netloc,
                encoded_path,
                parsed.params,
                encoded_query,
                parsed.fragment,
            )
        )
        return urljoin(current_location, reencoded_url)

    def resolve_from(
        self, context: Response | NonNavigatingRequest
    ) -> BaseRequest:
        """Create a new request with URL resolved from a Response or NonNavigatingRequest.

        This method is overridden in NavigatingRequest and NonNavigatingRequest
        to provide specific behavior for each request type.

        Args:
            context: Response from a previous request or the originating NonNavigatingRequest.

        Returns:
            A new request with resolved URL and updated context.

        Raises:
            NotImplementedError: If called on BaseRequest directly.
        """
        raise NotImplementedError(
            "resolve_from must be implemented by subclasses"
        )

    def resolve_request_from(self, context: Response | BaseRequest):
        match context:
            case Response():
                # Response from a NavigatingRequest - use its URL
                resolved_location = context.url
                parent_request = context.request
            case BaseRequest():
                # NonNavigatingRequest - use its current_location
                resolved_location = context.current_location
                parent_request = context

        return [
            HTTPRequestParams(
                url=self.resolve_url(resolved_location),
                method=self.request.method,
                headers=self.request.headers,
                data=self.request.data,
            ),
            resolved_location,
            parent_request,
        ]


@dataclass(frozen=True)
class NavigatingRequest(BaseRequest):
    """A request to navigate to a new page.

    When a scraper yields a NavigatingRequest, the driver will:
    1. Fetch the URL (resolving relative URLs against current_location)
    2. Update current_location to the new URL
    3. Call the continuation method with the Response

    The continuation is specified as a string (method name) rather than
    a function reference, making requests fully serializable for persistence.

    This differs from NonNavigatingRequest which fetches data without
    updating current_location (useful for API calls).
    """

    def resolve_from(
        self, context: Response | NonNavigatingRequest
    ) -> NavigatingRequest:
        """Create a new request with URL resolved from a Response or NonNavigatingRequest.

        For NavigatingRequest:
        - If context is a Response, use the response's URL as current_location
        - If context is a NonNavigatingRequest, use its current_location
        - accumulated_data and aux_data are carried forward from the new request (self)

        Args:
            context: Response from a NavigatingRequest or the originating NonNavigatingRequest.

        Returns:
            A new NavigatingRequest with resolved URL and updated context.
        """
        request, location, parent = self.resolve_request_from(context)
        # Step 18: Merge permanent data - parent's permanent + this request's permanent
        merged_permanent = {**parent.permanent, **self.permanent}
        return NavigatingRequest(
            request=request,
            continuation=self.continuation,
            current_location=location,
            previous_requests=parent.previous_requests + [parent],
            accumulated_data=self.accumulated_data,
            aux_data=self.aux_data,
            priority=self.priority,
            deduplication_key=self.deduplication_key,
            permanent=merged_permanent,
        )


@dataclass(frozen=True)
class NonNavigatingRequest(BaseRequest):
    """A request that fetches data without changing the current location.

    When a scraper yields a NonNavigatingRequest, the driver will:
    1. Fetch the URL (resolving relative URLs against current_location)
    2. Keep current_location unchanged
    3. Call the continuation method with the Response

    This is useful for API calls that provide supplementary data without
    navigating away from the current page. For example, fetching JSON
    metadata from an API while staying on an HTML detail page.

    The continuation is specified as a string (method name) for serializability.
    """

    def resolve_from(
        self, context: Response | NonNavigatingRequest
    ) -> NonNavigatingRequest:
        """Create a new request with URL resolved from a Response or NonNavigatingRequest.

        For NonNavigatingRequest:
        - If context is a Response, use the response's URL as current_location
        - If context is a NonNavigatingRequest, use its current_location
        - current_location stays unchanged (inherited from parent)
        - accumulated_data and aux_data are carried forward from the new request (self)

        Args:
            context: Response from a NavigatingRequest or the originating NonNavigatingRequest.

        Returns:
            A new NonNavigatingRequest with resolved URL and preserved current_location.
        """
        request, location, parent = self.resolve_request_from(context)
        # Step 18: Merge permanent data - parent's permanent + this request's permanent
        merged_permanent = {**parent.permanent, **self.permanent}
        return NonNavigatingRequest(
            request=request,
            continuation=self.continuation,
            current_location=location,
            previous_requests=parent.previous_requests + [parent],
            accumulated_data=self.accumulated_data,
            aux_data=self.aux_data,
            priority=self.priority,
            deduplication_key=self.deduplication_key,
            permanent=merged_permanent,
        )


@dataclass(frozen=True)
class ArchiveRequest(NonNavigatingRequest):
    """A request to download and archive a file.

    When a scraper yields an ArchiveRequest, the driver will:
    1. Fetch the URL (resolving relative URLs against current_location)
    2. Download the file content
    3. Save it to local storage
    4. Call the continuation method with an ArchiveResponse

    This is useful for downloading binary files like PDFs, MP3s, images, etc.
    The ArchiveResponse includes a file_url field with the local storage path.

    Like NonNavigatingRequest, ArchiveRequest preserves current_location -
    downloading a file doesn't change where you are in the scraper's navigation.

    Attributes:
        expected_type: Optional hint about the file type ("pdf", "audio", etc.).
        priority: Priority for request queue ordering (default 1, higher priority than regular requests).
    """

    expected_type: str | None = None
    priority: int = 1

    def resolve_from(
        self, context: Response | NonNavigatingRequest
    ) -> ArchiveRequest:
        """Create a new request with URL resolved from a Response or NonNavigatingRequest.

        For ArchiveRequest (like NonNavigatingRequest):
        - If context is a Response, use the response's URL as current_location
        - If context is a NonNavigatingRequest, use its current_location
        - current_location stays unchanged (inherited from parent)
        - accumulated_data and aux_data are carried forward from the new request (self)

        Args:
            context: Response from a NavigatingRequest or the originating NonNavigatingRequest.

        Returns:
            A new ArchiveRequest with resolved URL and preserved current_location.
        """
        request, location, parent = self.resolve_request_from(context)
        # Step 18: Merge permanent data - parent's permanent + this request's permanent
        merged_permanent = {**parent.permanent, **self.permanent}
        return ArchiveRequest(
            request=request,
            continuation=self.continuation,
            current_location=location,
            previous_requests=parent.previous_requests + [parent],
            expected_type=self.expected_type,
            accumulated_data=self.accumulated_data,
            aux_data=self.aux_data,
            priority=self.priority,
            deduplication_key=self.deduplication_key,
            permanent=merged_permanent,
        )


@dataclass
class Response:
    """HTTP response from fetching a page.

    Modeled after httpx.Response to provide a familiar interface.
    The driver creates Response objects and passes them to scraper
    continuation methods.

    Attributes:
        status_code: HTTP status code (200, 404, etc.).
        headers: Response headers.
        content: Raw response bytes.
        text: Decoded response text.
        url: Final URL after any redirects.
        request: The BaseRequest that triggered this response.
    """

    status_code: int
    headers: dict[str, str]
    content: bytes
    text: str
    url: str
    request: BaseRequest


@dataclass
class ArchiveResponse(Response):
    """HTTP response for an archived file.

    Extends Response with a file_url field that contains the local storage
    path where the file was saved. This allows scrapers to include the
    file location in their ParsedData output.

    Attributes:
        file_url: Local file system path where the downloaded file was stored.
    """

    file_url: str = ""


# =============================================================================
# Type Alias for Scraper Yields
# =============================================================================

# A scraper can yield ParsedData, NavigatingRequest, NonNavigatingRequest, or ArchiveRequest.
# This type alias enables exhaustive pattern matching in the driver.
ScraperYield = (
    ParsedData[T]
    | NavigatingRequest
    | NonNavigatingRequest
    | ArchiveRequest
    | None
)

# Type alias for scraper generator - what continuation methods return
ScraperGenerator = Generator[ScraperYield[T], None, None]
