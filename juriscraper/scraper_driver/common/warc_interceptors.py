"""WARC interceptors for recording and replaying HTTP traffic.

Step 17: WARC Support introduces:
- WarcCaptureInterceptor for recording responses to WARC files
- WarcCacheInterceptor for replaying from cached WARC files
- Deterministic testing with recorded traffic
- Support for compressed WARC files (.warc.gz)

WARC (Web ARChive) format stores HTTP requests and responses,
enabling deterministic testing by recording real traffic once
and replaying it for subsequent test runs.
"""

import hashlib
import logging
from io import BytesIO
from pathlib import Path
from typing import BinaryIO

from warcio.archiveiterator import ArchiveIterator
from warcio.statusandheaders import StatusAndHeaders
from warcio.warcwriter import WARCWriter

from juriscraper.scraper_driver.data_types import BaseRequest, Response

logger = logging.getLogger(__name__)


class WarcCacheInterceptor:
    """Interceptor that replays HTTP responses from WARC file cache.

    This interceptor short-circuits requests by returning cached responses
    from a WARC file, enabling deterministic testing without network access.

    The cache key is a SHA256 hash of:
    - HTTP method
    - Full URL (including query parameters)
    - Request body (if present)

    This ensures that the same request always gets the same cached response.
    """

    def __init__(self, warc_path: Path) -> None:
        """Initialize cache interceptor.

        Args:
            warc_path: Path to WARC file to read from.
        """
        self.warc_path = warc_path
        self._cache: dict[str, Response] = {}
        if warc_path.exists():
            self._load_warc()
        else:
            logger.warning(
                f"WARC file not found: {warc_path}, cache will be empty"
            )

    def _get_cache_key(self, request: BaseRequest) -> str:
        """Generate cache key from request.

        Args:
            request: The request to generate a key for.

        Returns:
            SHA256 hex digest as cache key.
        """
        # Build consistent key from request components
        method = request.request.method.value
        url = request.request.url

        # Include request body if present
        body = b""
        if request.request.data:
            if isinstance(request.request.data, bytes):
                body = request.request.data
            elif isinstance(request.request.data, str):
                body = request.request.data.encode("utf-8")
            else:
                # dict or list - use str representation
                body = str(request.request.data).encode("utf-8")

        # Hash method + url + body
        combined = f"{method}|{url}|".encode() + body
        return hashlib.sha256(combined).hexdigest()

    def _load_warc(self) -> None:
        """Load WARC file into memory cache."""
        logger.info(f"Loading WARC cache from {self.warc_path}")
        with self.warc_path.open("rb") as stream:
            for record in ArchiveIterator(stream):
                if record.rec_type == "response":
                    # Extract URL from WARC-Target-URI header
                    url = record.rec_headers.get_header("WARC-Target-URI")
                    if not url:
                        continue

                    # Extract method from custom header, default to GET
                    method = record.rec_headers.get_header("X-HTTP-Method")
                    if not method:
                        method = "GET"

                    # Read response body
                    content = record.content_stream().read()

                    # Build cache key from method and URL
                    cache_key = hashlib.sha256(
                        f"{method}|{url}|".encode()
                    ).hexdigest()

                    # Decode text from bytes
                    try:
                        text = content.decode("utf-8")
                    except UnicodeDecodeError:
                        # Fallback to latin-1 if utf-8 fails
                        text = content.decode("latin-1")

                    # Create Response object
                    # Use 200 as default status code and empty headers
                    response = Response(
                        url=url,
                        status_code=200,
                        content=content,
                        text=text,
                        headers={},
                        request=None,  # type: ignore
                    )

                    self._cache[cache_key] = response

        logger.info(f"Loaded {len(self._cache)} responses from WARC cache")

    def modify_request(self, request: BaseRequest) -> BaseRequest | Response:
        """Check cache and short-circuit if hit.

        Args:
            request: The request to check cache for.

        Returns:
            Cached Response if hit, otherwise original BaseRequest.
        """
        cache_key = self._get_cache_key(request)
        if cache_key in self._cache:
            logger.debug(f"WARC cache hit for {request.request.url}")
            cached_response = self._cache[cache_key]
            # Attach the request to the cached response
            return Response(
                url=cached_response.url,
                status_code=cached_response.status_code,
                content=cached_response.content,
                text=cached_response.text,
                headers=cached_response.headers,
                request=request,
            )
        logger.debug(f"WARC cache miss for {request.request.url}")
        return request

    def modify_response(
        self, response: Response, request: BaseRequest
    ) -> Response:
        """No-op for cache interceptor.

        Args:
            response: The response (unused).
            request: The request (unused).

        Returns:
            Unmodified response.
        """
        return response


class WarcCaptureInterceptor:
    """Interceptor that records HTTP responses to WARC file.

    This interceptor writes all responses to a WARC file, enabling
    deterministic testing by recording real traffic for later replay.

    The WARC file can be compressed (.warc.gz) or uncompressed (.warc).
    """

    def __init__(self, warc_path: Path) -> None:
        """Initialize capture interceptor.

        Args:
            warc_path: Path to WARC file to write to.
        """
        self.warc_path = warc_path
        self._file: BinaryIO | None = None
        self._writer: WARCWriter | None = None

        # Create parent directory if needed
        warc_path.parent.mkdir(parents=True, exist_ok=True)

    def _get_writer(self) -> WARCWriter:
        """Get or create WARC writer.

        Returns:
            WARC writer instance.
        """
        if self._writer is None:
            # Determine if we should compress
            gzip = str(self.warc_path).endswith(".gz")
            self._file = self.warc_path.open("wb")
            self._writer = WARCWriter(self._file, gzip=gzip)
            logger.info(f"Opened WARC file for writing: {self.warc_path}")

        return self._writer

    def modify_request(self, request: BaseRequest) -> BaseRequest | Response:
        """No-op for capture interceptor.

        Args:
            request: The request (unused).

        Returns:
            Unmodified request.
        """
        return request

    def modify_response(
        self, response: Response, request: BaseRequest
    ) -> Response:
        """Record response to WARC file.

        Args:
            response: The response to record.
            request: The request that generated this response.

        Returns:
            Unmodified response.
        """
        writer = self._get_writer()

        # Build HTTP headers
        http_headers = StatusAndHeaders(
            statusline=f"{response.status_code} OK",
            headers=[],
            protocol="HTTP/1.1",
        )

        # Create WARC response record
        # warcio expects a file-like object for payload
        payload_stream = BytesIO(response.content)
        record = writer.create_warc_record(
            uri=response.url,  # Just the URL, not METHOD URL
            record_type="response",
            payload=payload_stream,
            http_headers=http_headers,
            warc_headers_dict={
                "X-HTTP-Method": request.request.method.value,
            },
        )

        writer.write_record(record)
        logger.debug(f"Recorded response to WARC: {response.url}")

        return response

    def close(self) -> None:
        """Close WARC file."""
        if self._file:
            self._file.close()
            self._file = None
            self._writer = None
            logger.info(f"Closed WARC file: {self.warc_path}")

    def __del__(self) -> None:
        """Ensure file is closed on deletion."""
        self.close()
