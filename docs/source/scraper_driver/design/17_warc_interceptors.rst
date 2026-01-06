Step 17: WARC Interceptors
============================

One way we can use the interceptor pattern to enable a better dev experience is through WARC caching.
WARCs archive requests and responses in a more general format than just saving html for gets,
allowing us to locally cache POST (and more) responses for local dev.


Overview
--------

In this step, we introduce:

1. **WarcCaptureInterceptor** - Records responses to WARC files
2. **WarcCacheInterceptor** - Replays responses from WARC cache
3. **WARC file format** - Web ARChive format for HTTP archival
4. **Deterministic testing** - Record once, replay many times


Why WARC?
---------

**Network Dependency**

Without recording, every test run requires:
- Active network connection
- Remote servers to be available
- Servers to return consistent data
- Time to wait for network round-trips

This makes tests:
- Slow (network latency)
- Fragile (server downtime)
- Non-deterministic (data changes)
- Difficult to run offline

**WARC Solution**

With WARC recording:
- Record real HTTP traffic once
- Replay from cache forever
- Tests run offline
- Tests are deterministic
- Tests are fast (no network)


What is WARC?
-------------

WARC (Web ARChive) is an ISO standard format for archiving web content. It
stores HTTP requests and responses, including:

- Request URL and method
- Response status and headers
- Response body
- Metadata and timestamps

The format is used by web archives like the Internet Archive's Wayback Machine.


WarcCaptureInterceptor
----------------------

The capture interceptor records responses to a WARC file:

.. code-block:: python

    class WarcCaptureInterceptor:
        def __init__(self, warc_path: Path) -> None:
            self.warc_path = warc_path
            self._writer = None

        def modify_request(self, request: BaseRequest) -> BaseRequest:
            return request  # No-op

        def modify_response(
            self, response: Response, request: BaseRequest
        ) -> Response:
            # Write response to WARC file
            writer = self._get_writer()

            http_headers = StatusAndHeaders(
                statusline=f"{response.status_code} OK",
                headers=[],
                protocol="HTTP/1.1",
            )

            payload_stream = BytesIO(response.content)
            record = writer.create_warc_record(
                uri=response.url,
                record_type="response",
                payload=payload_stream,
                http_headers=http_headers,
                warc_headers_dict={
                    "X-HTTP-Method": request.request.method.value,
                },
            )

            writer.write_record(record)
            return response

        def close(self) -> None:
            if self._file:
                self._file.close()


WarcCacheInterceptor
--------------------

The cache interceptor replays responses from a WARC file:

.. code-block:: python

    class WarcCacheInterceptor:
        def __init__(self, warc_path: Path) -> None:
            self.warc_path = warc_path
            self._cache: dict[str, Response] = {}
            if warc_path.exists():
                self._load_warc()

        def _load_warc(self) -> None:
            with self.warc_path.open("rb") as stream:
                for record in ArchiveIterator(stream):
                    if record.rec_type == "response":
                        url = record.rec_headers.get_header("WARC-Target-URI")
                        method = record.rec_headers.get_header("X-HTTP-Method") or "GET"
                        content = record.content_stream().read()

                        # Build cache key: hash(method + url + body)
                        cache_key = hashlib.sha256(
                            f"{method}|{url}|".encode("utf-8")
                        ).hexdigest()

                        # Decode text
                        text = content.decode("utf-8")

                        # Create Response
                        response = Response(
                            url=url,
                            status_code=200,
                            content=content,
                            text=text,
                            headers={},
                            request=None,
                        )

                        self._cache[cache_key] = response

        def modify_request(self, request: BaseRequest) -> BaseRequest | Response:
            cache_key = self._get_cache_key(request)
            if cache_key in self._cache:
                # Short-circuit with cached response
                cached_response = self._cache[cache_key]
                return Response(
                    url=cached_response.url,
                    status_code=cached_response.status_code,
                    content=cached_response.content,
                    text=cached_response.text,
                    headers=cached_response.headers,
                    request=request,
                )
            return request

        def modify_response(
            self, response: Response, request: BaseRequest
        ) -> Response:
            return response  # No-op


Cache Key Generation
--------------------

The cache key is a SHA256 hash of:

1. **HTTP method** (GET, POST, etc.)
2. **URL** (full URL including query parameters)
3. **Request body** (if present)

This ensures:
- Same request = same key = cache hit
- Different method = different key
- Different URL = different key
- Different body = different key

.. code-block:: python

    def _get_cache_key(self, request: BaseRequest) -> str:
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
                body = str(request.request.data).encode("utf-8")

        # Hash method + url + body
        combined = f"{method}|{url}|".encode("utf-8") + body
        return hashlib.sha256(combined).hexdigest()


Usage Pattern
-------------

Record Once, Replay Forever
^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: python

    from pathlib import Path
    from juriscraper.scraper_driver.common.warc_interceptors import (
        WarcCaptureInterceptor,
        WarcCacheInterceptor,
    )

    warc_path = Path("scrape.warc.gz")

    # First run: record real HTTP traffic
    capture = WarcCaptureInterceptor(warc_path)
    driver = SyncDriver(
        scraper=scraper,
        storage_dir=tmp_path,
        interceptors=[rate_limiter, capture],
    )
    driver.run()
    capture.close()

    # Subsequent runs: replay from cache
    cache = WarcCacheInterceptor(warc_path)
    driver = SyncDriver(
        scraper=scraper,
        storage_dir=tmp_path,
        interceptors=[cache],  # No rate limiter needed!
    )
    driver.run()  # Fast, deterministic, offline

Next Steps
----------

In :doc:`18_permanent_data`, we introduce permanent request data - headers
and cookies that persist across the entire request chain. This simplifies
authentication workflows where session cookies or auth tokens must flow
through all requests.
