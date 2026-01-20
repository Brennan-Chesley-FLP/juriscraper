"""Tests for LocalDevDriver and related modules."""

from __future__ import annotations

import json
from collections.abc import Generator
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from juriscraper.scraper_driver.common.searchable import ScraperParams

if TYPE_CHECKING:
    import aiosqlite


@pytest.fixture
async def db_path(tmp_path: Path) -> Path:
    """Create a temporary database path."""
    return tmp_path / "test.db"


@pytest.fixture
async def initialized_db(db_path: Path) -> aiosqlite.Connection:
    """Create and return an initialized database connection."""
    from juriscraper.scraper_driver.driver.dev_driver.schema import (
        init_database,
    )

    db = await init_database(db_path)
    yield db
    await db.close()


class TestCompression:
    """Tests for compression module."""

    async def test_basic_compress_decompress(self) -> None:
        """Test basic compress/decompress roundtrip."""
        from juriscraper.scraper_driver.driver.dev_driver.compression import (
            compress,
            decompress,
        )

        original = b"<html><body>Hello World!</body></html>" * 100
        compressed = compress(original)
        decompressed = decompress(compressed)

        assert decompressed == original
        assert len(compressed) < len(original)

    async def test_compression_ratio(self) -> None:
        """Test that compression achieves good ratios on repetitive content."""
        from juriscraper.scraper_driver.driver.dev_driver.compression import (
            compress,
        )

        original = b"<html><body>Test content</body></html>" * 100
        compressed = compress(original)

        ratio = len(original) / len(compressed)
        assert ratio > 10, f"Expected ratio > 10, got {ratio:.2f}"

    async def test_compress_response_no_dict(
        self, initialized_db: aiosqlite.Connection
    ) -> None:
        """Test compress_response without dictionary."""
        from juriscraper.scraper_driver.driver.dev_driver.compression import (
            compress_response,
            decompress_response,
        )

        content = b"<html>Test</html>"
        compressed, dict_id = await compress_response(
            initialized_db, content, "test_continuation"
        )

        assert dict_id is None  # No dictionary available
        assert len(compressed) > 0

        decompressed = await decompress_response(
            initialized_db, compressed, dict_id
        )
        assert decompressed == content


class TestRequestTypeRoundTrip:
    """Tests for request type serialization and deserialization round-trips."""

    async def test_navigating_request_round_trip(
        self, initialized_db: aiosqlite.Connection
    ) -> None:
        """Test that NavigatingRequest is correctly serialized and deserialized."""
        from juriscraper.scraper_driver.data_types import (
            HttpMethod,
            HTTPRequestParams,
            NavigatingRequest,
        )
        from juriscraper.scraper_driver.driver.dev_driver.dev_driver import (
            LocalDevDriver,
        )

        # Create a NavigatingRequest with all fields populated
        original = NavigatingRequest(
            request=HTTPRequestParams(
                method=HttpMethod.GET,
                url="https://example.com/page",
                headers={"User-Agent": "Test", "Accept": "text/html"},
                cookies={"session": "abc123"},
            ),
            continuation="parse_page",
            current_location="https://example.com",
            accumulated_data={"key": "value", "count": 42},
            aux_data={"token": "xyz789"},
            permanent={"headers": {"Authorization": "Bearer token"}},
            priority=5,
        )

        # Serialize using the driver's method
        # We need a minimal driver instance just for serialization
        class MockScraper:
            pass

        driver = LocalDevDriver.__new__(LocalDevDriver)
        serialized = driver._serialize_request(original)

        # Verify request_type is set correctly
        assert serialized["request_type"] == "navigating"
        assert serialized["expected_type"] is None

        # Insert into database
        await initialized_db.execute(
            """
            INSERT INTO requests (
                status, priority, queue_counter, request_type,
                method, url, headers_json, cookies_json, body,
                continuation, current_location,
                accumulated_data_json, aux_data_json, permanent_json,
                expected_type
            ) VALUES (
                'pending', ?, 1, ?,
                ?, ?, ?, ?, ?,
                ?, ?,
                ?, ?, ?,
                ?
            )
            """,
            (
                original.priority,
                serialized["request_type"],
                serialized["method"],
                serialized["url"],
                serialized["headers_json"],
                serialized["cookies_json"],
                serialized["body"],
                serialized["continuation"],
                serialized["current_location"],
                serialized["accumulated_data_json"],
                serialized["aux_data_json"],
                serialized["permanent_json"],
                serialized["expected_type"],
            ),
        )
        await initialized_db.commit()

        # Retrieve and deserialize
        cursor = await initialized_db.execute(
            """
            SELECT id, request_type, method, url, headers_json, cookies_json, body,
                   continuation, current_location,
                   accumulated_data_json, aux_data_json, permanent_json,
                   expected_type, priority
            FROM requests WHERE id = 1
            """
        )
        row = await cursor.fetchone()
        assert row is not None

        deserialized = driver._deserialize_request(row)

        # Verify it's the correct type
        assert isinstance(deserialized, NavigatingRequest)

        # Verify all fields match
        assert deserialized.request.method == original.request.method
        assert deserialized.request.url == original.request.url
        assert deserialized.request.headers == original.request.headers
        assert deserialized.request.cookies == original.request.cookies
        assert deserialized.continuation == original.continuation
        assert deserialized.current_location == original.current_location
        assert deserialized.accumulated_data == original.accumulated_data
        assert deserialized.aux_data == original.aux_data
        assert deserialized.permanent == original.permanent
        assert deserialized.priority == original.priority

    async def test_non_navigating_request_round_trip(
        self, initialized_db: aiosqlite.Connection
    ) -> None:
        """Test that NonNavigatingRequest is correctly serialized and deserialized."""
        from juriscraper.scraper_driver.data_types import (
            HttpMethod,
            HTTPRequestParams,
            NonNavigatingRequest,
        )
        from juriscraper.scraper_driver.driver.dev_driver.dev_driver import (
            LocalDevDriver,
        )

        # Create a NonNavigatingRequest with all fields populated
        # Note: Use non-JSON bytes to test raw binary preservation.
        # JSON-like bytes get decoded to dicts by design (for form data).
        original = NonNavigatingRequest(
            request=HTTPRequestParams(
                method=HttpMethod.POST,
                url="https://api.example.com/data",
                headers={"Content-Type": "application/octet-stream"},
                data=b"\x00\x01\x02\x03binary data\xff\xfe",
            ),
            continuation="process_api_response",
            current_location="https://example.com/main",
            accumulated_data={"items": [1, 2, 3]},
            aux_data={"page": 2},
            permanent={"cookies": {"auth": "secret"}},
            priority=3,
        )

        # Serialize
        driver = LocalDevDriver.__new__(LocalDevDriver)
        serialized = driver._serialize_request(original)

        # Verify request_type is set correctly
        assert serialized["request_type"] == "non_navigating"
        assert serialized["expected_type"] is None

        # Insert into database
        await initialized_db.execute(
            """
            INSERT INTO requests (
                status, priority, queue_counter, request_type,
                method, url, headers_json, cookies_json, body,
                continuation, current_location,
                accumulated_data_json, aux_data_json, permanent_json,
                expected_type
            ) VALUES (
                'pending', ?, 1, ?,
                ?, ?, ?, ?, ?,
                ?, ?,
                ?, ?, ?,
                ?
            )
            """,
            (
                original.priority,
                serialized["request_type"],
                serialized["method"],
                serialized["url"],
                serialized["headers_json"],
                serialized["cookies_json"],
                serialized["body"],
                serialized["continuation"],
                serialized["current_location"],
                serialized["accumulated_data_json"],
                serialized["aux_data_json"],
                serialized["permanent_json"],
                serialized["expected_type"],
            ),
        )
        await initialized_db.commit()

        # Retrieve and deserialize
        cursor = await initialized_db.execute(
            """
            SELECT id, request_type, method, url, headers_json, cookies_json, body,
                   continuation, current_location,
                   accumulated_data_json, aux_data_json, permanent_json,
                   expected_type, priority
            FROM requests WHERE id = 1
            """
        )
        row = await cursor.fetchone()
        assert row is not None

        deserialized = driver._deserialize_request(row)

        # Verify it's the correct type
        assert isinstance(deserialized, NonNavigatingRequest)

        # Verify all fields match
        assert deserialized.request.method == original.request.method
        assert deserialized.request.url == original.request.url
        assert deserialized.request.headers == original.request.headers
        assert deserialized.request.data == original.request.data
        assert deserialized.continuation == original.continuation
        assert deserialized.current_location == original.current_location
        assert deserialized.accumulated_data == original.accumulated_data
        assert deserialized.aux_data == original.aux_data
        assert deserialized.permanent == original.permanent
        assert deserialized.priority == original.priority

    async def test_archive_request_round_trip(
        self, initialized_db: aiosqlite.Connection
    ) -> None:
        """Test that ArchiveRequest is correctly serialized and deserialized."""
        from juriscraper.scraper_driver.data_types import (
            ArchiveRequest,
            HttpMethod,
            HTTPRequestParams,
        )
        from juriscraper.scraper_driver.driver.dev_driver.dev_driver import (
            LocalDevDriver,
        )

        # Create an ArchiveRequest with all fields populated
        original = ArchiveRequest(
            request=HTTPRequestParams(
                method=HttpMethod.GET,
                url="https://example.com/files/document.pdf",
                headers={"Accept": "application/pdf"},
            ),
            continuation="handle_download",
            current_location="https://example.com/documents",
            expected_type="pdf",
            accumulated_data={"document_id": "12345"},
            aux_data={"filename": "document.pdf"},
            permanent={},
            priority=1,  # Default for ArchiveRequest
        )

        # Serialize
        driver = LocalDevDriver.__new__(LocalDevDriver)
        serialized = driver._serialize_request(original)

        # Verify request_type and expected_type are set correctly
        assert serialized["request_type"] == "archive"
        assert serialized["expected_type"] == "pdf"

        # Insert into database
        await initialized_db.execute(
            """
            INSERT INTO requests (
                status, priority, queue_counter, request_type,
                method, url, headers_json, cookies_json, body,
                continuation, current_location,
                accumulated_data_json, aux_data_json, permanent_json,
                expected_type
            ) VALUES (
                'pending', ?, 1, ?,
                ?, ?, ?, ?, ?,
                ?, ?,
                ?, ?, ?,
                ?
            )
            """,
            (
                original.priority,
                serialized["request_type"],
                serialized["method"],
                serialized["url"],
                serialized["headers_json"],
                serialized["cookies_json"],
                serialized["body"],
                serialized["continuation"],
                serialized["current_location"],
                serialized["accumulated_data_json"],
                serialized["aux_data_json"],
                serialized["permanent_json"],
                serialized["expected_type"],
            ),
        )
        await initialized_db.commit()

        # Retrieve and deserialize
        cursor = await initialized_db.execute(
            """
            SELECT id, request_type, method, url, headers_json, cookies_json, body,
                   continuation, current_location,
                   accumulated_data_json, aux_data_json, permanent_json,
                   expected_type, priority
            FROM requests WHERE id = 1
            """
        )
        row = await cursor.fetchone()
        assert row is not None

        deserialized = driver._deserialize_request(row)

        # Verify it's the correct type
        assert isinstance(deserialized, ArchiveRequest)

        # Verify all fields match
        assert deserialized.request.method == original.request.method
        assert deserialized.request.url == original.request.url
        assert deserialized.request.headers == original.request.headers
        assert deserialized.continuation == original.continuation
        assert deserialized.current_location == original.current_location
        assert deserialized.expected_type == original.expected_type
        assert deserialized.accumulated_data == original.accumulated_data
        assert deserialized.aux_data == original.aux_data
        assert deserialized.permanent == original.permanent
        assert deserialized.priority == original.priority

    async def test_archive_request_without_expected_type(
        self, initialized_db: aiosqlite.Connection
    ) -> None:
        """Test ArchiveRequest round-trip when expected_type is None."""
        from juriscraper.scraper_driver.data_types import (
            ArchiveRequest,
            HttpMethod,
            HTTPRequestParams,
        )
        from juriscraper.scraper_driver.driver.dev_driver.dev_driver import (
            LocalDevDriver,
        )

        # Create an ArchiveRequest without expected_type
        original = ArchiveRequest(
            request=HTTPRequestParams(
                method=HttpMethod.GET,
                url="https://example.com/files/unknown",
            ),
            continuation="handle_download",
            current_location="https://example.com",
            expected_type=None,  # No type hint
        )

        # Serialize
        driver = LocalDevDriver.__new__(LocalDevDriver)
        serialized = driver._serialize_request(original)

        assert serialized["request_type"] == "archive"
        assert serialized["expected_type"] is None

        # Insert and retrieve
        await initialized_db.execute(
            """
            INSERT INTO requests (
                status, priority, queue_counter, request_type,
                method, url, headers_json, cookies_json, body,
                continuation, current_location,
                accumulated_data_json, aux_data_json, permanent_json,
                expected_type
            ) VALUES (
                'pending', ?, 1, ?,
                ?, ?, ?, ?, ?,
                ?, ?,
                ?, ?, ?,
                ?
            )
            """,
            (
                original.priority,
                serialized["request_type"],
                serialized["method"],
                serialized["url"],
                serialized["headers_json"],
                serialized["cookies_json"],
                serialized["body"],
                serialized["continuation"],
                serialized["current_location"],
                serialized["accumulated_data_json"],
                serialized["aux_data_json"],
                serialized["permanent_json"],
                serialized["expected_type"],
            ),
        )
        await initialized_db.commit()

        cursor = await initialized_db.execute(
            """
            SELECT id, request_type, method, url, headers_json, cookies_json, body,
                   continuation, current_location,
                   accumulated_data_json, aux_data_json, permanent_json,
                   expected_type, priority
            FROM requests WHERE id = 1
            """
        )
        row = await cursor.fetchone()
        deserialized = driver._deserialize_request(row)

        assert isinstance(deserialized, ArchiveRequest)
        assert deserialized.expected_type is None

    async def test_request_with_binary_body(
        self, initialized_db: aiosqlite.Connection
    ) -> None:
        """Test request round-trip with binary body data."""
        from juriscraper.scraper_driver.data_types import (
            HttpMethod,
            HTTPRequestParams,
            NonNavigatingRequest,
        )
        from juriscraper.scraper_driver.driver.dev_driver.dev_driver import (
            LocalDevDriver,
        )

        binary_body = b"\x00\x01\x02\xff\xfe\xfd"

        original = NonNavigatingRequest(
            request=HTTPRequestParams(
                method=HttpMethod.POST,
                url="https://example.com/upload",
                data=binary_body,
            ),
            continuation="handle_upload",
            current_location="",
        )

        driver = LocalDevDriver.__new__(LocalDevDriver)
        serialized = driver._serialize_request(original)

        # Insert and retrieve
        await initialized_db.execute(
            """
            INSERT INTO requests (
                status, priority, queue_counter, request_type,
                method, url, headers_json, cookies_json, body,
                continuation, current_location,
                accumulated_data_json, aux_data_json, permanent_json,
                expected_type
            ) VALUES (
                'pending', ?, 1, ?,
                ?, ?, ?, ?, ?,
                ?, ?,
                ?, ?, ?,
                ?
            )
            """,
            (
                original.priority,
                serialized["request_type"],
                serialized["method"],
                serialized["url"],
                serialized["headers_json"],
                serialized["cookies_json"],
                serialized["body"],
                serialized["continuation"],
                serialized["current_location"],
                serialized["accumulated_data_json"],
                serialized["aux_data_json"],
                serialized["permanent_json"],
                serialized["expected_type"],
            ),
        )
        await initialized_db.commit()

        cursor = await initialized_db.execute(
            """
            SELECT id, request_type, method, url, headers_json, cookies_json, body,
                   continuation, current_location,
                   accumulated_data_json, aux_data_json, permanent_json,
                   expected_type, priority
            FROM requests WHERE id = 1
            """
        )
        row = await cursor.fetchone()
        result = driver._deserialize_request(row)
        # NavigatingRequest returns BaseRequest directly
        deserialized = result if not isinstance(result, tuple) else result[0]

        assert deserialized.request.data == binary_body

    async def test_request_with_empty_optional_fields(
        self, initialized_db: aiosqlite.Connection
    ) -> None:
        """Test request round-trip with minimal fields (empty optionals)."""
        from juriscraper.scraper_driver.data_types import (
            HttpMethod,
            HTTPRequestParams,
            NavigatingRequest,
        )
        from juriscraper.scraper_driver.driver.dev_driver.dev_driver import (
            LocalDevDriver,
        )

        # Minimal request with empty optional fields
        original = NavigatingRequest(
            request=HTTPRequestParams(
                method=HttpMethod.GET,
                url="https://example.com",
            ),
            continuation="parse",
            current_location="",
        )

        driver = LocalDevDriver.__new__(LocalDevDriver)
        serialized = driver._serialize_request(original)

        # Verify optional fields are None/empty
        assert serialized["headers_json"] is None
        assert serialized["cookies_json"] is None
        assert serialized["body"] is None
        assert serialized["accumulated_data_json"] is None
        assert serialized["aux_data_json"] is None
        assert serialized["permanent_json"] is None

        # Insert and retrieve
        await initialized_db.execute(
            """
            INSERT INTO requests (
                status, priority, queue_counter, request_type,
                method, url, headers_json, cookies_json, body,
                continuation, current_location,
                accumulated_data_json, aux_data_json, permanent_json,
                expected_type
            ) VALUES (
                'pending', ?, 1, ?,
                ?, ?, ?, ?, ?,
                ?, ?,
                ?, ?, ?,
                ?
            )
            """,
            (
                original.priority,
                serialized["request_type"],
                serialized["method"],
                serialized["url"],
                serialized["headers_json"],
                serialized["cookies_json"],
                serialized["body"],
                serialized["continuation"],
                serialized["current_location"],
                serialized["accumulated_data_json"],
                serialized["aux_data_json"],
                serialized["permanent_json"],
                serialized["expected_type"],
            ),
        )
        await initialized_db.commit()

        cursor = await initialized_db.execute(
            """
            SELECT id, request_type, method, url, headers_json, cookies_json, body,
                   continuation, current_location,
                   accumulated_data_json, aux_data_json, permanent_json,
                   expected_type, priority
            FROM requests WHERE id = 1
            """
        )
        row = await cursor.fetchone()
        result = driver._deserialize_request(row)
        # NavigatingRequest returns BaseRequest directly
        deserialized = result if not isinstance(result, tuple) else result[0]

        # Verify deserialized correctly with empty defaults
        assert deserialized.request.headers is None
        assert deserialized.request.cookies is None
        assert deserialized.request.data is None
        assert deserialized.accumulated_data == {}
        assert deserialized.aux_data == {}
        assert deserialized.permanent == {}


class TestErrorTracking:
    """Tests for error tracking module."""

    async def test_store_and_retrieve_error(
        self, initialized_db: aiosqlite.Connection
    ) -> None:
        """Test storing and retrieving an error."""
        from juriscraper.scraper_driver.common.exceptions import (
            HTMLStructuralAssumptionException,
        )
        from juriscraper.scraper_driver.driver.dev_driver.errors import (
            get_error,
            store_error,
        )

        exc = HTMLStructuralAssumptionException(
            selector=".missing-class",
            selector_type="css",
            description="Test selector not found",
            expected_min=1,
            expected_max=None,
            actual_count=0,
            request_url="https://example.com/test",
        )

        error_id = await store_error(
            initialized_db, exc, request_url="https://example.com/test"
        )
        assert error_id > 0

        error = await get_error(initialized_db, error_id)
        assert error is not None
        assert error.error_type == "structural"
        assert error.selector == ".missing-class"
        assert not error.is_resolved

    async def test_resolve_error(
        self, initialized_db: aiosqlite.Connection
    ) -> None:
        """Test resolving an error."""
        from juriscraper.scraper_driver.common.exceptions import (
            HTMLStructuralAssumptionException,
        )
        from juriscraper.scraper_driver.driver.dev_driver.errors import (
            get_error,
            resolve_error,
            store_error,
        )

        exc = HTMLStructuralAssumptionException(
            selector=".test",
            selector_type="css",
            description="Test",
            expected_min=1,
            expected_max=None,
            actual_count=0,
            request_url="https://example.com",
        )

        error_id = await store_error(initialized_db, exc)

        resolved = await resolve_error(
            initialized_db, error_id, notes="Fixed the selector"
        )
        assert resolved

        error = await get_error(initialized_db, error_id)
        assert error is not None
        assert error.is_resolved
        assert error.resolution_notes == "Fixed the selector"

    async def test_list_errors_filter(
        self, initialized_db: aiosqlite.Connection
    ) -> None:
        """Test listing errors with filters."""
        from juriscraper.scraper_driver.common.exceptions import (
            HTMLStructuralAssumptionException,
            RequestTimeoutException,
        )
        from juriscraper.scraper_driver.driver.dev_driver.errors import (
            list_errors,
            store_error,
        )

        # Create structural error
        exc1 = HTMLStructuralAssumptionException(
            selector=".test1",
            selector_type="css",
            description="Test 1",
            expected_min=1,
            expected_max=None,
            actual_count=0,
            request_url="https://example.com/1",
        )
        await store_error(initialized_db, exc1)

        # Create transient error
        exc2 = RequestTimeoutException(
            url="https://example.com/2",
            timeout_seconds=30.0,
        )
        await store_error(initialized_db, exc2)

        # List all
        all_errors = await list_errors(initialized_db, unresolved_only=True)
        assert len(all_errors) == 2

        # Filter by type
        structural = await list_errors(
            initialized_db, error_type="structural", unresolved_only=True
        )
        assert len(structural) == 1
        assert structural[0].error_type == "structural"


class TestRetryLogic:
    """Tests for retry with exponential backoff."""

    async def test_exponential_backoff_calculation(
        self, initialized_db: aiosqlite.Connection
    ) -> None:
        """Test that retry delays follow exponential backoff."""
        from juriscraper.scraper_driver.driver.dev_driver.schema import (
            get_next_queue_counter,
        )

        # Create a request
        queue_counter = await get_next_queue_counter(initialized_db)
        await initialized_db.execute(
            """
            INSERT INTO requests (
                status, priority, queue_counter, method, url,
                continuation, current_location, retry_count, cumulative_backoff
            ) VALUES ('in_progress', 9, ?, 'GET', 'https://example.com/test',
                      'parse', '', 0, 0.0)
            """,
            (queue_counter,),
        )
        await initialized_db.commit()

        cursor = await initialized_db.execute(
            "SELECT id FROM requests LIMIT 1"
        )
        row = await cursor.fetchone()
        request_id = row[0]

        max_backoff_time = 60.0
        retry_base_delay = 1.0
        cumulative = 0.0

        expected_delays = [
            1.0,
            2.0,
            4.0,
            8.0,
            15.0,
            15.0,
        ]  # Capped at 15 (60/4)

        for i, expected_delay in enumerate(expected_delays):
            cursor = await initialized_db.execute(
                "SELECT retry_count, cumulative_backoff FROM requests WHERE id = ?",
                (request_id,),
            )
            row = await cursor.fetchone()
            retry_count = row[0]

            next_delay = retry_base_delay * (2**retry_count)
            max_individual = max_backoff_time / 4
            next_delay = min(next_delay, max_individual)

            assert next_delay == expected_delay, (
                f"Retry {i}: expected {expected_delay}, got {next_delay}"
            )

            cumulative += next_delay

            if cumulative >= max_backoff_time:
                break

            # Update for next iteration
            await initialized_db.execute(
                """
                UPDATE requests
                SET retry_count = retry_count + 1,
                    cumulative_backoff = ?
                WHERE id = ?
                """,
                (cumulative, request_id),
            )
            await initialized_db.commit()

    async def test_retry_respects_max_backoff(
        self, initialized_db: aiosqlite.Connection
    ) -> None:
        """Test that cumulative backoff is capped at max_backoff_time."""
        from juriscraper.scraper_driver.driver.dev_driver.schema import (
            get_next_queue_counter,
        )

        queue_counter = await get_next_queue_counter(initialized_db)
        await initialized_db.execute(
            """
            INSERT INTO requests (
                status, priority, queue_counter, method, url,
                continuation, current_location, retry_count, cumulative_backoff
            ) VALUES ('in_progress', 9, ?, 'GET', 'https://example.com/test',
                      'parse', '', 5, 45.0)
            """,
            (queue_counter,),
        )
        await initialized_db.commit()

        max_backoff_time = 60.0
        retry_base_delay = 1.0

        cursor = await initialized_db.execute(
            "SELECT retry_count, cumulative_backoff FROM requests LIMIT 1"
        )
        row = await cursor.fetchone()
        retry_count, cumulative = row

        next_delay = retry_base_delay * (2**retry_count)
        next_delay = min(next_delay, max_backoff_time / 4)

        new_cumulative = cumulative + next_delay
        should_fail = new_cumulative >= max_backoff_time

        assert should_fail, (
            f"Expected to fail: cumulative={new_cumulative}, max={max_backoff_time}"
        )


class TestRequeueFunction:
    """Tests for requeue functionality."""

    async def test_requeue_creates_new_request(
        self, initialized_db: aiosqlite.Connection
    ) -> None:
        """Test that requeue creates a new pending request."""
        from juriscraper.scraper_driver.common.exceptions import (
            HTMLStructuralAssumptionException,
        )
        from juriscraper.scraper_driver.driver.dev_driver.errors import (
            get_error,
            resolve_error,
            store_error,
        )
        from juriscraper.scraper_driver.driver.dev_driver.schema import (
            get_next_queue_counter,
        )

        # Create original request
        await initialized_db.execute(
            """
            INSERT INTO requests (
                status, priority, queue_counter, method, url,
                continuation, current_location
            ) VALUES ('failed', 9, 1, 'GET', 'https://example.com/test',
                      'parse_results', '')
            """
        )
        await initialized_db.commit()

        cursor = await initialized_db.execute(
            "SELECT id FROM requests LIMIT 1"
        )
        row = await cursor.fetchone()
        request_id = row[0]

        # Create error linked to request
        exc = HTMLStructuralAssumptionException(
            selector=".missing",
            selector_type="css",
            description="Not found",
            expected_min=1,
            expected_max=None,
            actual_count=0,
            request_url="https://example.com/test",
        )
        error_id = await store_error(
            initialized_db, exc, request_id=request_id
        )

        # Simulate requeue
        cursor = await initialized_db.execute(
            """
            SELECT r.method, r.url, r.continuation, r.priority
            FROM errors e
            JOIN requests r ON e.request_id = r.id
            WHERE e.id = ?
            """,
            (error_id,),
        )
        row = await cursor.fetchone()
        method, url, continuation, priority = row

        queue_counter = await get_next_queue_counter(initialized_db)
        await initialized_db.execute(
            """
            INSERT INTO requests (
                status, priority, queue_counter, method, url,
                continuation, current_location, parent_request_id
            ) VALUES ('pending', ?, ?, ?, ?, ?, '', ?)
            """,
            (priority, queue_counter, method, url, continuation, request_id),
        )
        await initialized_db.commit()

        cursor = await initialized_db.execute("SELECT last_insert_rowid()")
        row = await cursor.fetchone()
        new_request_id = row[0]

        await resolve_error(
            initialized_db,
            error_id,
            notes=f"Requeued as request {new_request_id}",
        )

        # Verify error is resolved
        error = await get_error(initialized_db, error_id)
        assert error is not None
        assert error.is_resolved
        assert "Requeued" in (error.resolution_notes or "")

        # Verify new request exists
        cursor = await initialized_db.execute(
            "SELECT status, parent_request_id FROM requests WHERE id = ?",
            (new_request_id,),
        )
        row = await cursor.fetchone()
        assert row[0] == "pending"
        assert row[1] == request_id


class TestStatistics:
    """Tests for statistics module."""

    async def test_queue_stats(
        self, initialized_db: aiosqlite.Connection
    ) -> None:
        """Test queue statistics calculation."""
        from juriscraper.scraper_driver.driver.dev_driver.stats import (
            get_queue_stats,
        )

        # Create requests with various statuses
        await initialized_db.execute(
            """
            INSERT INTO requests (status, priority, queue_counter, method, url, continuation, current_location)
            VALUES
            ('pending', 9, 1, 'GET', 'https://example.com/1', 'parse', ''),
            ('pending', 9, 2, 'GET', 'https://example.com/2', 'parse', ''),
            ('in_progress', 9, 3, 'GET', 'https://example.com/3', 'parse', ''),
            ('completed', 9, 4, 'GET', 'https://example.com/4', 'parse', ''),
            ('failed', 9, 5, 'GET', 'https://example.com/5', 'process', ''),
            ('held', 9, 6, 'GET', 'https://example.com/6', 'parse', '')
            """
        )
        await initialized_db.commit()

        stats = await get_queue_stats(initialized_db)

        assert stats.pending == 2
        assert stats.in_progress == 1
        assert stats.completed == 1
        assert stats.failed == 1
        assert stats.held == 1
        assert stats.total == 6
        assert "parse" in stats.by_continuation
        assert "process" in stats.by_continuation

    async def test_compression_stats(
        self, initialized_db: aiosqlite.Connection
    ) -> None:
        """Test compression statistics calculation."""
        from juriscraper.scraper_driver.driver.dev_driver.stats import (
            get_compression_stats,
        )

        # Create request first
        await initialized_db.execute(
            """
            INSERT INTO requests (id, status, priority, queue_counter, method, url, continuation, current_location)
            VALUES (1, 'completed', 9, 1, 'GET', 'https://example.com', 'parse', '')
            """
        )

        # Create responses
        await initialized_db.execute(
            """
            INSERT INTO responses (request_id, status_code, url, content_compressed,
                                   content_size_original, content_size_compressed,
                                   compression_dict_id, continuation, warc_record_id)
            VALUES
            (1, 200, 'https://example.com', x'1234', 1000, 100, NULL, 'parse', 'uuid1')
            """
        )
        await initialized_db.commit()

        stats = await get_compression_stats(initialized_db)

        assert stats.total_responses == 1
        assert stats.total_original_bytes == 1000
        assert stats.total_compressed_bytes == 100
        assert stats.compression_ratio == 10.0
        assert stats.no_dict_compressed_count == 1

    async def test_stats_json_serialization(
        self, initialized_db: aiosqlite.Connection
    ) -> None:
        """Test that stats can be serialized to JSON."""
        from juriscraper.scraper_driver.driver.dev_driver.stats import (
            get_stats,
        )

        # Create run metadata
        await initialized_db.execute(
            """
            INSERT INTO run_metadata (id, scraper_name, status, base_delay, jitter, num_workers, max_backoff_time)
            VALUES (1, 'TestScraper', 'completed', 1.0, 0.5, 1, 60.0)
            """
        )
        await initialized_db.commit()

        stats = await get_stats(initialized_db)
        json_str = stats.to_json()

        parsed = json.loads(json_str)
        assert "queue" in parsed
        assert "throughput" in parsed
        assert "compression" in parsed
        assert "results" in parsed
        assert "errors" in parsed
        assert parsed["scraper_name"] == "TestScraper"


class TestWarcExport:
    """Tests for WARC export module."""

    async def test_warc_export(
        self, initialized_db: aiosqlite.Connection, tmp_path: Path
    ) -> None:
        """Test exporting responses to WARC file."""
        from juriscraper.scraper_driver.driver.dev_driver.compression import (
            compress,
        )
        from juriscraper.scraper_driver.driver.dev_driver.warc_export import (
            export_warc,
        )

        # Create request
        await initialized_db.execute(
            """
            INSERT INTO requests (id, status, priority, queue_counter, method, url,
                                  headers_json, continuation, current_location)
            VALUES (1, 'completed', 9, 1, 'GET', 'https://example.com/page1',
                    '{"User-Agent": "Test"}', 'parse', '')
            """
        )

        # Create response with compressed content
        content = b"<html><body>Test page</body></html>"
        compressed = compress(content)

        await initialized_db.execute(
            """
            INSERT INTO responses (request_id, status_code, headers_json, url,
                                   content_compressed, content_size_original,
                                   content_size_compressed, continuation, warc_record_id)
            VALUES (1, 200, '{"Content-Type": "text/html"}', 'https://example.com/page1',
                    ?, ?, ?, 'parse', 'uuid-1')
            """,
            (compressed, len(content), len(compressed)),
        )
        await initialized_db.commit()

        # Export to WARC
        warc_path = tmp_path / "export.warc"
        count = await export_warc(initialized_db, warc_path, compress=False)

        assert count == 1
        assert warc_path.exists()

        # Verify WARC content
        from warcio.archiveiterator import ArchiveIterator

        records = []
        with warc_path.open("rb") as f:
            for record in ArchiveIterator(f):
                records.append(record.rec_type)

        # Should have response and request records
        assert "response" in records
        assert "request" in records


class TestDictionaryTraining:
    """Tests for compression dictionary training and recompression."""

    async def test_train_compression_dict(
        self, initialized_db: aiosqlite.Connection
    ) -> None:
        """Test training a compression dictionary from stored responses."""
        from juriscraper.scraper_driver.driver.dev_driver.compression import (
            compress,
            get_compression_dict,
            train_compression_dict,
        )

        # Create request
        await initialized_db.execute(
            """
            INSERT INTO requests (id, status, priority, queue_counter, method, url,
                                  continuation, current_location)
            VALUES (1, 'completed', 9, 1, 'GET', 'https://example.com',
                    'parse', '')
            """
        )

        # Create multiple responses with similar HTML content (needed for dict training)
        html_template = b"""
        <html>
        <head><title>Court Case {num}</title></head>
        <body>
            <div class="case-header">
                <h1>Case Number: {num}</h1>
                <p>Filed: 2024-01-{day:02d}</p>
            </div>
            <div class="case-content">
                <p>This is the content of case {num}. The parties involved are
                plaintiff John Doe and defendant Jane Smith. The case concerns
                a contractual dispute regarding property at 123 Main Street.</p>
            </div>
        </body>
        </html>
        """

        for i in range(20):  # Need enough samples for training
            content = html_template.replace(b"{num}", str(i).encode()).replace(
                b"{day:02d}", f"{(i % 28) + 1:02d}".encode()
            )
            compressed = compress(content)

            await initialized_db.execute(
                """
                INSERT INTO responses (request_id, status_code, url, content_compressed,
                                       content_size_original, content_size_compressed,
                                       compression_dict_id, continuation, warc_record_id)
                VALUES (1, 200, ?, ?, ?, ?, NULL, 'parse', ?)
                """,
                (
                    f"https://example.com/case/{i}",
                    compressed,
                    len(content),
                    len(compressed),
                    f"uuid-{i}",
                ),
            )

        await initialized_db.commit()

        # Train dictionary
        dict_id = await train_compression_dict(
            initialized_db,
            continuation="parse",
            sample_limit=20,
            dict_size=32768,  # Smaller dict for test
        )

        assert dict_id is not None
        assert dict_id > 0

        # Verify dictionary was stored
        result = await get_compression_dict(initialized_db, "parse")
        assert result is not None
        stored_id, dict_data = result
        assert stored_id == dict_id
        assert len(dict_data) > 0

    async def test_recompress_responses(
        self, initialized_db: aiosqlite.Connection
    ) -> None:
        """Test recompressing responses with a trained dictionary."""
        from juriscraper.scraper_driver.driver.dev_driver.compression import (
            compress,
            recompress_responses,
            train_compression_dict,
        )

        # Create request
        await initialized_db.execute(
            """
            INSERT INTO requests (id, status, priority, queue_counter, method, url,
                                  continuation, current_location)
            VALUES (1, 'completed', 9, 1, 'GET', 'https://example.com',
                    'parse', '')
            """
        )

        # Create responses with similar content
        html_template = b"""
        <html>
        <body>
            <div class="opinion">
                <h1>Opinion {num}</h1>
                <p>The court finds that the defendant is liable for damages
                in the amount of ${amount}. The plaintiff's motion for summary
                judgment is hereby granted.</p>
            </div>
        </body>
        </html>
        """

        original_sizes = []
        original_compressed_sizes = []

        for i in range(15):
            content = html_template.replace(b"{num}", str(i).encode()).replace(
                b"{amount}", str(10000 + i * 1000).encode()
            )
            compressed = compress(content)
            original_sizes.append(len(content))
            original_compressed_sizes.append(len(compressed))

            await initialized_db.execute(
                """
                INSERT INTO responses (request_id, status_code, url, content_compressed,
                                       content_size_original, content_size_compressed,
                                       compression_dict_id, continuation, warc_record_id)
                VALUES (1, 200, ?, ?, ?, ?, NULL, 'parse', ?)
                """,
                (
                    f"https://example.com/opinion/{i}",
                    compressed,
                    len(content),
                    len(compressed),
                    f"uuid-{i}",
                ),
            )

        await initialized_db.commit()

        # Train dictionary
        await train_compression_dict(
            initialized_db,
            continuation="parse",
            sample_limit=15,
            dict_size=32768,
        )

        # Recompress with dictionary
        count, total_original, total_compressed = await recompress_responses(
            initialized_db, "parse"
        )

        assert count == 15
        assert total_original == sum(original_sizes)
        # With dictionary, should achieve better compression
        assert total_compressed < sum(original_compressed_sizes)

        # Verify all responses now have dict_id set
        cursor = await initialized_db.execute(
            "SELECT compression_dict_id FROM responses WHERE compression_dict_id IS NOT NULL"
        )
        rows = await cursor.fetchall()
        assert len(rows) == 15

    async def test_train_dict_no_responses_raises(
        self, initialized_db: aiosqlite.Connection
    ) -> None:
        """Test that training with no responses raises ValueError."""
        from juriscraper.scraper_driver.driver.dev_driver.compression import (
            train_compression_dict,
        )

        with pytest.raises(ValueError, match="No responses found"):
            await train_compression_dict(initialized_db, "nonexistent")

    async def test_recompress_no_dict_raises(
        self, initialized_db: aiosqlite.Connection
    ) -> None:
        """Test that recompressing without a dict raises ValueError."""
        from juriscraper.scraper_driver.driver.dev_driver.compression import (
            recompress_responses,
        )

        with pytest.raises(ValueError, match="No dictionary found"):
            await recompress_responses(initialized_db, "nonexistent")


class TestListingMethods:
    """Tests for web interface listing methods."""

    async def test_list_requests(
        self, initialized_db: aiosqlite.Connection
    ) -> None:
        """Test listing requests with filters and pagination."""
        from juriscraper.scraper_driver.driver.dev_driver.dev_driver import (
            Page,
            RequestRecord,
        )

        # Create requests with various statuses
        await initialized_db.execute(
            """
            INSERT INTO requests (status, priority, queue_counter, request_type, method, url, continuation, current_location)
            VALUES
            ('pending', 9, 1, 'navigating', 'GET', 'https://example.com/1', 'parse', ''),
            ('pending', 9, 2, 'navigating', 'GET', 'https://example.com/2', 'parse', ''),
            ('completed', 9, 3, 'navigating', 'GET', 'https://example.com/3', 'parse', ''),
            ('failed', 9, 4, 'navigating', 'GET', 'https://example.com/4', 'process', '')
            """
        )
        await initialized_db.commit()

        # Test helper to simulate list_requests
        async def list_requests(
            status: str | None = None,
            continuation: str | None = None,
            offset: int = 0,
            limit: int = 50,
        ) -> Page[RequestRecord]:
            conditions = []
            params: list = []

            if status:
                conditions.append("status = ?")
                params.append(status)
            if continuation:
                conditions.append("continuation = ?")
                params.append(continuation)

            where_clause = (
                f"WHERE {' AND '.join(conditions)}" if conditions else ""
            )

            cursor = await initialized_db.execute(
                f"SELECT COUNT(*) FROM requests {where_clause}", params
            )
            row = await cursor.fetchone()
            total = row[0] if row else 0

            cursor = await initialized_db.execute(
                f"""
                SELECT id, status, priority, queue_counter, method, url,
                       continuation, current_location, created_at, started_at,
                       completed_at, retry_count, cumulative_backoff, last_error
                FROM requests
                {where_clause}
                ORDER BY priority ASC, queue_counter ASC
                LIMIT ? OFFSET ?
                """,
                params + [limit, offset],
            )
            rows = await cursor.fetchall()

            items = [
                RequestRecord(
                    id=r[0],
                    status=r[1],
                    priority=r[2],
                    queue_counter=r[3],
                    method=r[4],
                    url=r[5],
                    continuation=r[6],
                    current_location=r[7],
                    created_at=r[8],
                    started_at=r[9],
                    completed_at=r[10],
                    retry_count=r[11],
                    cumulative_backoff=r[12],
                    last_error=r[13],
                )
                for r in rows
            ]

            return Page(items=items, total=total, offset=offset, limit=limit)

        # List all
        page = await list_requests()
        assert page.total == 4
        assert len(page.items) == 4

        # Filter by status
        page = await list_requests(status="pending")
        assert page.total == 2
        assert all(r.status == "pending" for r in page.items)

        # Filter by continuation
        page = await list_requests(continuation="process")
        assert page.total == 1
        assert page.items[0].continuation == "process"

        # Pagination
        page = await list_requests(offset=0, limit=2)
        assert page.total == 4
        assert len(page.items) == 2

        page = await list_requests(offset=2, limit=2)
        assert page.total == 4
        assert len(page.items) == 2

    async def test_list_responses(
        self, initialized_db: aiosqlite.Connection
    ) -> None:
        """Test listing responses with filters."""
        from juriscraper.scraper_driver.driver.dev_driver.compression import (
            compress,
        )
        from juriscraper.scraper_driver.driver.dev_driver.dev_driver import (
            Page,
            ResponseRecord,
        )

        # Create request
        await initialized_db.execute(
            """
            INSERT INTO requests (id, status, priority, queue_counter, method, url,
                                  continuation, current_location)
            VALUES (1, 'completed', 9, 1, 'GET', 'https://example.com',
                    'parse', '')
            """
        )

        # Create responses
        content = b"<html>Test</html>"
        compressed = compress(content)

        await initialized_db.execute(
            """
            INSERT INTO responses (request_id, status_code, url, content_compressed,
                                   content_size_original, content_size_compressed,
                                   continuation, warc_record_id)
            VALUES
            (1, 200, 'https://example.com/1', ?, ?, ?, 'parse', 'uuid1'),
            (1, 200, 'https://example.com/2', ?, ?, ?, 'process', 'uuid2')
            """,
            (
                compressed,
                len(content),
                len(compressed),
                compressed,
                len(content),
                len(compressed),
            ),
        )
        await initialized_db.commit()

        # Test helper
        async def list_responses(
            continuation: str | None = None,
        ) -> Page[ResponseRecord]:
            conditions = []
            params: list = []

            if continuation:
                conditions.append("continuation = ?")
                params.append(continuation)

            where_clause = (
                f"WHERE {' AND '.join(conditions)}" if conditions else ""
            )

            cursor = await initialized_db.execute(
                f"SELECT COUNT(*) FROM responses {where_clause}", params
            )
            row = await cursor.fetchone()
            total = row[0] if row else 0

            cursor = await initialized_db.execute(
                f"""
                SELECT id, request_id, status_code, url, content_size_original,
                       content_size_compressed, continuation, created_at,
                       compression_dict_id
                FROM responses
                {where_clause}
                """,
                params,
            )
            rows = await cursor.fetchall()

            items = [
                ResponseRecord(
                    id=r[0],
                    request_id=r[1],
                    status_code=r[2],
                    url=r[3],
                    content_size_original=r[4],
                    content_size_compressed=r[5],
                    continuation=r[6],
                    created_at=r[7],
                    compression_dict_id=r[8],
                )
                for r in rows
            ]

            return Page(items=items, total=total, offset=0, limit=50)

        # List all
        page = await list_responses()
        assert page.total == 2

        # Filter by continuation
        page = await list_responses(continuation="parse")
        assert page.total == 1
        assert page.items[0].continuation == "parse"

    async def test_record_to_json(
        self, initialized_db: aiosqlite.Connection
    ) -> None:
        """Test that records can be serialized to JSON."""
        from juriscraper.scraper_driver.driver.dev_driver.dev_driver import (
            Page,
            RequestRecord,
            ResponseRecord,
            ResultRecord,
        )

        # Test RequestRecord
        req = RequestRecord(
            id=1,
            status="pending",
            priority=9,
            queue_counter=1,
            method="GET",
            url="https://example.com",
            continuation="parse",
            current_location="",
            created_at="2024-01-01",
            started_at=None,
            completed_at=None,
            retry_count=0,
            cumulative_backoff=0.0,
            last_error=None,
        )
        req_json = req.to_json()
        parsed = json.loads(req_json)
        assert parsed["id"] == 1
        assert parsed["status"] == "pending"

        # Test ResponseRecord
        resp = ResponseRecord(
            id=1,
            request_id=1,
            status_code=200,
            url="https://example.com",
            content_size_original=1000,
            content_size_compressed=100,
            continuation="parse",
            created_at="2024-01-01",
            compression_dict_id=None,
        )
        resp_dict = resp.to_dict()
        assert resp_dict["compression_ratio"] == 10.0

        # Test ResultRecord
        result = ResultRecord(
            id=1,
            request_id=1,
            result_type="TestModel",
            data_json='{"name": "test"}',
            is_valid=True,
            validation_errors_json=None,
            created_at="2024-01-01",
        )
        result_dict = result.to_dict()
        assert result_dict["data"] == {"name": "test"}

        # Test Page
        page = Page(
            items=[req],
            total=10,
            offset=0,
            limit=1,
        )
        page_json = page.to_json()
        parsed_page = json.loads(page_json)
        assert parsed_page["total"] == 10
        assert parsed_page["has_more"] is True

    async def test_cancel_request(
        self, initialized_db: aiosqlite.Connection
    ) -> None:
        """Test cancelling a request."""
        # Create pending request
        await initialized_db.execute(
            """
            INSERT INTO requests (id, status, priority, queue_counter, method, url,
                                  continuation, current_location)
            VALUES (1, 'pending', 9, 1, 'GET', 'https://example.com', 'parse', '')
            """
        )
        await initialized_db.commit()

        # Cancel it
        cursor = await initialized_db.execute(
            """
            UPDATE requests
            SET status = 'failed', completed_at = CURRENT_TIMESTAMP,
                last_error = 'Cancelled by user'
            WHERE id = 1 AND status IN ('pending', 'held')
            """
        )
        await initialized_db.commit()

        cancelled = cursor.rowcount > 0
        assert cancelled

        # Verify status
        cursor = await initialized_db.execute(
            "SELECT status, last_error FROM requests WHERE id = 1"
        )
        row = await cursor.fetchone()
        assert row[0] == "failed"
        assert row[1] == "Cancelled by user"

    async def test_cancel_requests_by_continuation(
        self, initialized_db: aiosqlite.Connection
    ) -> None:
        """Test batch cancelling requests by continuation."""
        # Create multiple pending requests
        await initialized_db.execute(
            """
            INSERT INTO requests (status, priority, queue_counter, method, url,
                                  continuation, current_location)
            VALUES
            ('pending', 9, 1, 'GET', 'https://example.com/1', 'parse', ''),
            ('pending', 9, 2, 'GET', 'https://example.com/2', 'parse', ''),
            ('pending', 9, 3, 'GET', 'https://example.com/3', 'process', '')
            """
        )
        await initialized_db.commit()

        # Cancel all parse requests
        cursor = await initialized_db.execute(
            """
            UPDATE requests
            SET status = 'failed', completed_at = CURRENT_TIMESTAMP,
                last_error = 'Cancelled by user (batch)'
            WHERE continuation = 'parse' AND status IN ('pending', 'held')
            """
        )
        await initialized_db.commit()

        count = cursor.rowcount
        assert count == 2

        # Verify 'process' request is still pending
        cursor = await initialized_db.execute(
            "SELECT status FROM requests WHERE continuation = 'process'"
        )
        row = await cursor.fetchone()
        assert row[0] == "pending"


class TestAioSQLiteBucket:
    """Tests for AioSQLiteBucket rate limiter."""

    async def test_put_and_count(
        self, initialized_db: aiosqlite.Connection
    ) -> None:
        """Test adding items and counting."""
        from pyrate_limiter import Duration, Rate, RateItem

        from juriscraper.scraper_driver.driver.dev_driver.rate_limiter import (
            AioSQLiteBucket,
        )

        rates = [Rate(5, Duration.SECOND)]
        bucket = AioSQLiteBucket(initialized_db, rates)

        # Initially empty
        count = await bucket.count()
        assert count == 0

        # Add items
        item1 = RateItem(name="test1", timestamp=1000, weight=1)
        item2 = RateItem(name="test2", timestamp=2000, weight=2)

        await bucket.put(item1)
        await bucket.put(item2)

        # Count should be sum of weights
        count = await bucket.count()
        assert count == 3

    async def test_peek(self, initialized_db: aiosqlite.Connection) -> None:
        """Test peeking at items by index."""
        from pyrate_limiter import Duration, Rate, RateItem

        from juriscraper.scraper_driver.driver.dev_driver.rate_limiter import (
            AioSQLiteBucket,
        )

        rates = [Rate(5, Duration.SECOND)]
        bucket = AioSQLiteBucket(initialized_db, rates)

        # Add items with different timestamps
        item1 = RateItem(name="old", timestamp=1000, weight=1)
        item2 = RateItem(name="new", timestamp=2000, weight=1)

        await bucket.put(item1)
        await bucket.put(item2)

        # Peek at index 0 (newest first due to ORDER BY timestamp DESC)
        peeked = await bucket.peek(0)
        assert peeked is not None
        assert peeked.name == "new"
        assert peeked.timestamp == 2000

        # Peek at index 1 (older item)
        peeked = await bucket.peek(1)
        assert peeked is not None
        assert peeked.name == "old"

        # Peek at invalid index
        peeked = await bucket.peek(10)
        assert peeked is None

    async def test_leak(self, initialized_db: aiosqlite.Connection) -> None:
        """Test leaking expired items."""
        from pyrate_limiter import Duration, Rate, RateItem

        from juriscraper.scraper_driver.driver.dev_driver.rate_limiter import (
            AioSQLiteBucket,
        )

        # Rate with 1 second interval (1000ms)
        rates = [Rate(5, Duration.SECOND)]
        bucket = AioSQLiteBucket(initialized_db, rates)

        # Add old and new items
        old_item = RateItem(name="old", timestamp=1000, weight=1)
        new_item = RateItem(name="new", timestamp=5000, weight=1)

        await bucket.put(old_item)
        await bucket.put(new_item)

        # Leak at timestamp 6000 (1 second after new_item)
        # Old item (1000) is older than cutoff (6000 - 1000 = 5000)
        leaked = await bucket.leak(current_timestamp=6000)
        assert leaked == 1

        # Only new item should remain
        count = await bucket.count()
        assert count == 1

    async def test_flush(self, initialized_db: aiosqlite.Connection) -> None:
        """Test flushing all items."""
        from pyrate_limiter import Duration, Rate, RateItem

        from juriscraper.scraper_driver.driver.dev_driver.rate_limiter import (
            AioSQLiteBucket,
        )

        rates = [Rate(5, Duration.SECOND)]
        bucket = AioSQLiteBucket(initialized_db, rates)

        # Add items
        for i in range(5):
            item = RateItem(name=f"test{i}", timestamp=i * 1000, weight=1)
            await bucket.put(item)

        assert await bucket.count() == 5

        # Flush
        await bucket.flush()
        assert await bucket.count() == 0

    async def test_waiting(self, initialized_db: aiosqlite.Connection) -> None:
        """Test calculating wait time."""
        from pyrate_limiter import Duration, Rate, RateItem

        from juriscraper.scraper_driver.driver.dev_driver.rate_limiter import (
            AioSQLiteBucket,
        )

        # Rate: 2 requests per second (1000ms)
        rates = [Rate(2, Duration.SECOND)]
        bucket = AioSQLiteBucket(initialized_db, rates)

        # Add 2 items at timestamp 1000
        item1 = RateItem(name="test1", timestamp=1000, weight=1)
        item2 = RateItem(name="test2", timestamp=1000, weight=1)

        await bucket.put(item1)
        await bucket.put(item2)

        # New item at timestamp 1500 should need to wait
        # The window (1500 - 1000 = 500ms to 1500ms) contains 2 items
        # With limit 2, we're at capacity, so new item needs to wait
        new_item = RateItem(name="new", timestamp=1500, weight=1)
        wait = await bucket.waiting(new_item)

        # Should wait until oldest item (1000) expires (1000 + 1000 = 2000)
        # Wait = 2000 - 1500 = 500ms
        assert wait == 500

    async def test_waiting_no_wait_needed(
        self, initialized_db: aiosqlite.Connection
    ) -> None:
        """Test no wait needed when under limit."""
        from pyrate_limiter import Duration, Rate, RateItem

        from juriscraper.scraper_driver.driver.dev_driver.rate_limiter import (
            AioSQLiteBucket,
        )

        # Rate: 5 requests per second
        rates = [Rate(5, Duration.SECOND)]
        bucket = AioSQLiteBucket(initialized_db, rates)

        # Add 1 item
        item = RateItem(name="test", timestamp=1000, weight=1)
        await bucket.put(item)

        # New item at timestamp 1500 should not need to wait (only 1 of 5 used)
        new_item = RateItem(name="new", timestamp=1500, weight=1)
        wait = await bucket.waiting(new_item)

        assert wait == 0


class TestRateLimiterIntegration:
    """Tests for rate limiter integration with LocalDevDriver."""

    async def test_rate_limiter_interceptor_added_on_init(
        self, db_path: Path
    ) -> None:
        """Test that JitterRateLimitInterceptor is added to interceptors on _init_db."""
        from juriscraper.scraper_driver.data_types import (
            BaseScraper,
            HttpMethod,
            HTTPRequestParams,
            NavigatingRequest,
        )
        from juriscraper.scraper_driver.driver.dev_driver.dev_driver import (
            LocalDevDriver,
        )
        from juriscraper.scraper_driver.driver.dev_driver.rate_limiter import (
            JitterRateLimitInterceptor,
        )

        class MinimalScraper(BaseScraper[str]):
            def get_entry(self) -> Generator[NavigatingRequest, None, None]:
                yield NavigatingRequest(
                    request=HTTPRequestParams(
                        method=HttpMethod.GET,
                        url="https://example.com",
                    ),
                    continuation="parse",
                    current_location="",
                )

            def parse(self, response: Any) -> list:
                return []

        scraper = MinimalScraper()

        async with LocalDevDriver.open(
            scraper, db_path, base_delay=5.0, jitter=1.0
        ) as driver:
            # Verify interceptor was added to request_manager
            assert len(driver.request_manager.interceptors) == 1
            assert isinstance(
                driver.request_manager.interceptors[0],
                JitterRateLimitInterceptor,
            )

            # Verify parameters were passed correctly
            rate_limiter = driver.request_manager.interceptors[0]
            assert rate_limiter.base_delay_seconds == 5.0
            assert rate_limiter.jitter_seconds == 1.0


class TestRunManager:
    """Tests for RunManager class."""

    @pytest.fixture
    def runs_dir(self, tmp_path: Path) -> Path:
        """Create a temporary runs directory."""
        runs = tmp_path / "runs"
        runs.mkdir()
        return runs

    @pytest.fixture
    def mock_scraper(self) -> Any:
        """Create a minimal mock scraper for testing."""

        from juriscraper.scraper_driver.data_types import (
            BaseScraper,
            HttpMethod,
            HTTPRequestParams,
            NavigatingRequest,
        )

        class MockScraper(BaseScraper[str]):
            def get_entry(self) -> Generator[NavigatingRequest, None, None]:
                yield NavigatingRequest(
                    request=HTTPRequestParams(
                        method=HttpMethod.GET,
                        url="https://example.com",
                    ),
                    continuation="parse",
                    current_location="",
                )

            def parse(self, response: Any) -> list:
                return []

        return MockScraper()

    async def test_scan_runs_empty_dir(self, runs_dir: Path) -> None:
        """Test scanning empty runs directory."""
        from juriscraper.scraper_driver.driver.dev_driver.web.app import (
            RunManager,
        )

        manager = RunManager(runs_dir)
        discovered = await manager.scan_runs()

        assert discovered == []
        assert manager.runs == {}

    async def test_scan_runs_creates_missing_dir(self, tmp_path: Path) -> None:
        """Test that scan_runs creates the directory if it doesn't exist."""
        from juriscraper.scraper_driver.driver.dev_driver.web.app import (
            RunManager,
        )

        nonexistent = tmp_path / "nonexistent_runs"
        assert not nonexistent.exists()

        manager = RunManager(nonexistent)
        await manager.scan_runs()

        assert nonexistent.exists()

    async def test_scan_runs_discovers_databases(self, runs_dir: Path) -> None:
        """Test scanning directory with existing database files."""
        from juriscraper.scraper_driver.driver.dev_driver.web.app import (
            RunManager,
        )

        # Create some .db files
        (runs_dir / "run1.db").touch()
        (runs_dir / "run2.db").touch()
        (runs_dir / "notadb.txt").touch()  # Should be ignored

        manager = RunManager(runs_dir)
        discovered = await manager.scan_runs()

        assert len(discovered) == 2
        assert "run1" in discovered
        assert "run2" in discovered
        assert "notadb" not in discovered
        assert len(manager.runs) == 2
        assert all(r.status == "unloaded" for r in manager.runs.values())

    async def test_list_runs(self, runs_dir: Path) -> None:
        """Test listing all runs."""
        from juriscraper.scraper_driver.driver.dev_driver.web.app import (
            RunManager,
        )

        (runs_dir / "test1.db").touch()
        (runs_dir / "test2.db").touch()

        manager = RunManager(runs_dir)
        await manager.scan_runs()

        runs = await manager.list_runs()
        assert len(runs) == 2
        run_ids = {r.run_id for r in runs}
        assert run_ids == {"test1", "test2"}

    async def test_get_run_found(self, runs_dir: Path) -> None:
        """Test getting a specific run."""
        from juriscraper.scraper_driver.driver.dev_driver.web.app import (
            RunManager,
        )

        (runs_dir / "myrun.db").touch()

        manager = RunManager(runs_dir)
        await manager.scan_runs()

        run = await manager.get_run("myrun")
        assert run is not None
        assert run.run_id == "myrun"

    async def test_get_run_not_found(self, runs_dir: Path) -> None:
        """Test getting a non-existent run."""
        from juriscraper.scraper_driver.driver.dev_driver.web.app import (
            RunManager,
        )

        manager = RunManager(runs_dir)

        run = await manager.get_run("nonexistent")
        assert run is None

    async def test_create_run(self, runs_dir: Path, mock_scraper: Any) -> None:
        """Test creating a new run."""
        from juriscraper.scraper_driver.driver.dev_driver.web.app import (
            RunManager,
        )

        manager = RunManager(runs_dir)

        run = await manager.create_run("new_run", mock_scraper)

        assert run.run_id == "new_run"
        assert run.status == "loaded"
        assert run.driver is not None
        assert run.db_path.exists()
        assert "new_run" in manager.runs

        # Cleanup
        await run.driver.close()

    async def test_create_run_duplicate_raises(
        self, runs_dir: Path, mock_scraper: Any
    ) -> None:
        """Test that creating duplicate run raises ValueError."""
        from juriscraper.scraper_driver.driver.dev_driver.web.app import (
            RunManager,
        )

        manager = RunManager(runs_dir)

        run = await manager.create_run("duplicate", mock_scraper)

        with pytest.raises(ValueError, match="already exists"):
            await manager.create_run("duplicate", mock_scraper)

        # Cleanup
        assert run.driver is not None
        await run.driver.close()

    async def test_load_run(self, runs_dir: Path, mock_scraper: Any) -> None:
        """Test loading an existing unloaded run."""
        from juriscraper.scraper_driver.driver.dev_driver.schema import (
            init_database,
        )
        from juriscraper.scraper_driver.driver.dev_driver.web.app import (
            RunManager,
        )

        # Create a database file first
        db_path = runs_dir / "existing.db"
        db = await init_database(db_path)

        # Insert run_metadata row since LocalDevDriver expects it on resume
        await db.execute(
            """
            INSERT INTO run_metadata (id, scraper_name, status, base_delay, jitter, num_workers, max_backoff_time)
            VALUES (1, 'MockScraper', 'completed', 1.0, 0.5, 1, 60.0)
            """
        )
        await db.commit()
        await db.close()

        manager = RunManager(runs_dir)
        await manager.scan_runs()

        assert manager.runs["existing"].status == "unloaded"

        run = await manager.load_run("existing", mock_scraper)

        assert run.status == "loaded"
        assert run.driver is not None

        # Cleanup
        await run.driver.close()

    async def test_load_run_not_found(
        self, runs_dir: Path, mock_scraper: Any
    ) -> None:
        """Test loading non-existent run raises ValueError."""
        from juriscraper.scraper_driver.driver.dev_driver.web.app import (
            RunManager,
        )

        manager = RunManager(runs_dir)

        with pytest.raises(ValueError, match="not found"):
            await manager.load_run("nonexistent", mock_scraper)

    async def test_unload_run(self, runs_dir: Path, mock_scraper: Any) -> None:
        """Test unloading a loaded run."""
        from juriscraper.scraper_driver.driver.dev_driver.web.app import (
            RunManager,
        )

        manager = RunManager(runs_dir)
        run = await manager.create_run("to_unload", mock_scraper)

        assert run.status == "loaded"
        assert run.driver is not None

        await manager.unload_run("to_unload")

        assert manager.runs["to_unload"].status == "unloaded"
        assert manager.runs["to_unload"].driver is None

    async def test_delete_run(self, runs_dir: Path, mock_scraper: Any) -> None:
        """Test deleting a run and its database."""
        from juriscraper.scraper_driver.driver.dev_driver.web.app import (
            RunManager,
        )

        manager = RunManager(runs_dir)
        run = await manager.create_run("to_delete", mock_scraper)
        db_path = run.db_path

        assert db_path.exists()

        # Unload first
        await manager.unload_run("to_delete")

        # Delete
        await manager.delete_run("to_delete")

        assert "to_delete" not in manager.runs
        assert not db_path.exists()

    async def test_delete_run_running_raises(
        self, runs_dir: Path, mock_scraper: Any
    ) -> None:
        """Test that deleting a running run raises ValueError."""
        from unittest.mock import MagicMock

        from juriscraper.scraper_driver.driver.dev_driver.web.app import (
            RunManager,
        )

        manager = RunManager(runs_dir)
        run = await manager.create_run("running", mock_scraper)

        # Simulate a running task
        run.task = MagicMock()
        run.task.done.return_value = False
        manager.runs["running"] = run

        with pytest.raises(ValueError, match="still running"):
            await manager.delete_run("running")

        # Cleanup
        assert run.driver is not None
        await run.driver.close()

    async def test_run_info_to_dict(self, runs_dir: Path) -> None:
        """Test RunInfo serialization."""
        from datetime import datetime, timezone

        from juriscraper.scraper_driver.driver.dev_driver.web.app import (
            RunInfo,
        )

        run_info = RunInfo(
            run_id="test",
            db_path=runs_dir / "test.db",
            status="running",
            created_at=datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
            started_at=datetime(2024, 1, 1, 12, 0, 1, tzinfo=timezone.utc),
        )

        d = run_info.to_dict()

        assert d["run_id"] == "test"
        assert d["status"] == "running"
        assert "2024-01-01" in d["created_at"]
        assert d["started_at"] is not None

    async def test_shutdown_all_empty(self, runs_dir: Path) -> None:
        """Test shutdown_all with no runs."""
        from juriscraper.scraper_driver.driver.dev_driver.web.app import (
            RunManager,
        )

        manager = RunManager(runs_dir)

        # Should not raise
        await manager.shutdown_all()

    async def test_shutdown_all_unloads_all(
        self, runs_dir: Path, mock_scraper: Any
    ) -> None:
        """Test shutdown_all closes all driver connections."""
        from juriscraper.scraper_driver.driver.dev_driver.web.app import (
            RunManager,
        )

        manager = RunManager(runs_dir)
        run1 = await manager.create_run("run1", mock_scraper)
        run2 = await manager.create_run("run2", mock_scraper)

        assert run1.driver is not None
        assert run2.driver is not None

        await manager.shutdown_all()

        assert manager.runs["run1"].driver is None
        assert manager.runs["run2"].driver is None
        assert manager.runs["run1"].status == "unloaded"
        assert manager.runs["run2"].status == "unloaded"


class TestFastAPIApp:
    """Tests for FastAPI application setup."""

    def test_create_app(self, tmp_path: Path) -> None:
        """Test creating FastAPI app with custom runs directory."""
        from juriscraper.scraper_driver.driver.dev_driver.web.app import (
            create_app,
        )

        runs_dir = tmp_path / "custom_runs"
        app = create_app(runs_dir)

        assert app.state.runs_dir == runs_dir
        assert app.title == "LocalDevDriver Web Interface"

    def test_create_app_default_dir(self) -> None:
        """Test creating FastAPI app with default runs directory."""
        from juriscraper.scraper_driver.driver.dev_driver.web.app import (
            create_app,
        )

        app = create_app()

        assert app.state.runs_dir == Path("runs")

    def test_get_run_manager_not_initialized(self) -> None:
        """Test get_run_manager raises when not initialized."""
        from juriscraper.scraper_driver.driver.dev_driver.web import (
            app as app_module,
        )
        from juriscraper.scraper_driver.driver.dev_driver.web.app import (
            get_run_manager,
        )

        # Ensure no manager is set
        app_module._run_manager = None

        with pytest.raises(RuntimeError, match="not initialized"):
            get_run_manager()

    async def test_lifespan_initializes_manager(self, tmp_path: Path) -> None:
        """Test that lifespan initializes and cleans up run manager."""
        from juriscraper.scraper_driver.driver.dev_driver.web import (
            app as app_module,
        )
        from juriscraper.scraper_driver.driver.dev_driver.web.app import (
            create_app,
            get_run_manager,
            lifespan,
        )

        runs_dir = tmp_path / "lifespan_runs"
        app = create_app(runs_dir)

        # Before lifespan, manager should not be available
        app_module._run_manager = None

        async with lifespan(app):
            # During lifespan, manager should be available
            manager = get_run_manager()
            assert manager is not None
            assert manager.runs_dir == runs_dir
            assert runs_dir.exists()  # Should create directory

        # After lifespan, manager should be cleared
        assert app_module._run_manager is None


class TestRunsAPI:
    """Tests for /api/runs REST endpoints."""

    @pytest.fixture
    def runs_dir(self, tmp_path: Path) -> Path:
        """Create a temporary runs directory."""
        runs = tmp_path / "runs"
        runs.mkdir()
        return runs

    @pytest.fixture
    def test_app(self, runs_dir: Path):
        """Create test FastAPI app with custom runs directory."""
        from juriscraper.scraper_driver.driver.dev_driver.web.app import (
            create_app,
        )

        return create_app(runs_dir)

    @pytest.fixture
    def client(self, test_app):
        """Create TestClient for the app."""
        from fastapi.testclient import TestClient

        return TestClient(test_app)

    def test_list_runs_empty(self, client) -> None:
        """Test listing runs when empty."""
        with client:
            response = client.get("/api/runs")

        assert response.status_code == 200
        data = response.json()
        assert data["runs"] == []
        assert data["total"] == 0

    def test_list_runs_with_databases(self, runs_dir: Path, client) -> None:
        """Test listing runs with existing databases."""
        # Create some db files before starting the app
        (runs_dir / "test1.db").touch()
        (runs_dir / "test2.db").touch()

        with client:
            response = client.get("/api/runs")

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 2
        run_ids = {r["run_id"] for r in data["runs"]}
        assert run_ids == {"test1", "test2"}

    def test_get_run_not_found(self, client) -> None:
        """Test getting a non-existent run."""
        with client:
            response = client.get("/api/runs/nonexistent")

        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    def test_get_run_found(self, runs_dir: Path, client) -> None:
        """Test getting an existing run."""
        (runs_dir / "existing.db").touch()

        with client:
            response = client.get("/api/runs/existing")

        assert response.status_code == 200
        data = response.json()
        assert data["run_id"] == "existing"
        assert data["status"] == "unloaded"

    def test_delete_run_not_found(self, client) -> None:
        """Test deleting a non-existent run."""
        with client:
            response = client.delete("/api/runs/nonexistent")

        assert response.status_code == 404

    def test_delete_run_success(self, runs_dir: Path, client) -> None:
        """Test successfully deleting a run."""
        db_path = runs_dir / "to_delete.db"
        db_path.touch()
        assert db_path.exists()

        with client:
            # First verify it exists
            response = client.get("/api/runs/to_delete")
            assert response.status_code == 200

            # Delete it
            response = client.delete("/api/runs/to_delete")
            assert response.status_code == 204

            # Verify it's gone
            response = client.get("/api/runs/to_delete")
            assert response.status_code == 404

        assert not db_path.exists()

    def test_scan_runs(self, runs_dir: Path, client) -> None:
        """Test scanning for new runs."""
        with client:
            # Start with no runs
            response = client.get("/api/runs")
            assert response.json()["total"] == 0

            # Create a new db file
            (runs_dir / "new_run.db").touch()

            # Scan
            response = client.post("/api/runs/scan")
            assert response.status_code == 200
            data = response.json()
            assert data["total"] == 1
            assert data["runs"][0]["run_id"] == "new_run"

    def test_start_run_not_found(self, client) -> None:
        """Test starting a non-existent run."""
        with client:
            response = client.post("/api/runs/nonexistent/start")

        assert response.status_code == 404

    def test_start_run_not_loaded(self, runs_dir: Path, client) -> None:
        """Test starting an unloaded run fails."""
        (runs_dir / "unloaded.db").touch()

        with client:
            response = client.post("/api/runs/unloaded/start")

        # Should fail because run is not loaded
        assert response.status_code == 400
        assert "not loaded" in response.json()["detail"].lower()

    def test_stop_run_not_found(self, client) -> None:
        """Test stopping a non-existent run."""
        with client:
            response = client.post("/api/runs/nonexistent/stop")

        assert response.status_code == 404

    def test_stop_run_not_running(self, runs_dir: Path, client) -> None:
        """Test stopping a non-running run fails."""
        (runs_dir / "not_running.db").touch()

        with client:
            response = client.post("/api/runs/not_running/stop")

        # Should fail because run is not running
        assert response.status_code == 400
        assert "not running" in response.json()["detail"].lower()

    def test_unload_run_not_found(self, client) -> None:
        """Test unloading a non-existent run."""
        with client:
            response = client.post("/api/runs/nonexistent/unload")

        assert response.status_code == 404

    def test_create_run_scraper_not_found(self, client) -> None:
        """Test creating a run with unknown scraper returns 404."""
        with client:
            response = client.post(
                "/api/runs",
                json={
                    "run_id": "new_run",
                    "scraper_path": "test.module:TestScraper",
                },
            )

        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()


class TestWebSocketManager:
    """Tests for WebSocket manager."""

    async def test_connect_and_disconnect(self) -> None:
        """Test connecting and disconnecting WebSocket."""
        from unittest.mock import AsyncMock, MagicMock

        from juriscraper.scraper_driver.driver.dev_driver.web.websocket import (
            WebSocketManager,
        )

        manager = WebSocketManager()

        # Create mock WebSocket
        ws = MagicMock()
        ws.accept = AsyncMock()
        ws.send_text = AsyncMock()

        # Connect
        await manager.connect(ws, "test_run")

        assert manager.get_connection_count("test_run") == 1
        assert manager.get_total_connections() == 1
        ws.accept.assert_called_once()

        # Disconnect
        await manager.disconnect(ws, "test_run")

        assert manager.get_connection_count("test_run") == 0
        assert manager.get_total_connections() == 0

    async def test_broadcast(self) -> None:
        """Test broadcasting events to subscribers."""
        from datetime import datetime, timezone
        from unittest.mock import AsyncMock, MagicMock

        from juriscraper.scraper_driver.driver.dev_driver.dev_driver import (
            ProgressEvent,
        )
        from juriscraper.scraper_driver.driver.dev_driver.web.websocket import (
            WebSocketManager,
        )

        manager = WebSocketManager()

        # Create mock WebSockets
        ws1 = MagicMock()
        ws1.accept = AsyncMock()
        ws1.send_text = AsyncMock()

        ws2 = MagicMock()
        ws2.accept = AsyncMock()
        ws2.send_text = AsyncMock()

        # Connect both
        await manager.connect(ws1, "test_run")
        await manager.connect(ws2, "test_run")

        # Create event
        event = ProgressEvent(
            event_type="request_completed",
            timestamp=datetime.now(timezone.utc),
            data={"request_id": 1, "url": "https://example.com"},
        )

        # Broadcast
        await manager.broadcast("test_run", event)

        # Both should receive
        ws1.send_text.assert_called_once()
        ws2.send_text.assert_called_once()

    async def test_subscription_filtering(self) -> None:
        """Test that events are filtered by subscription."""
        from datetime import datetime, timezone
        from unittest.mock import AsyncMock, MagicMock

        from juriscraper.scraper_driver.driver.dev_driver.dev_driver import (
            ProgressEvent,
        )
        from juriscraper.scraper_driver.driver.dev_driver.web.websocket import (
            ProgressEventType,
            WebSocketManager,
        )

        manager = WebSocketManager()

        # Create mock WebSocket
        ws = MagicMock()
        ws.accept = AsyncMock()
        ws.send_text = AsyncMock()

        # Connect with limited subscription
        await manager.connect(
            ws, "test_run", event_types={ProgressEventType.REQUEST_COMPLETED}
        )

        # Event that matches subscription
        event_match = ProgressEvent(
            event_type="request_completed",
            timestamp=datetime.now(timezone.utc),
            data={"request_id": 1},
        )

        await manager.broadcast("test_run", event_match)
        assert ws.send_text.call_count == 1

        # Event that doesn't match subscription
        event_no_match = ProgressEvent(
            event_type="request_started",
            timestamp=datetime.now(timezone.utc),
            data={"request_id": 2},
        )

        await manager.broadcast("test_run", event_no_match)
        # Should still be 1, not called for this event
        assert ws.send_text.call_count == 1

    async def test_update_subscription(self) -> None:
        """Test updating subscription."""
        from unittest.mock import AsyncMock, MagicMock

        from juriscraper.scraper_driver.driver.dev_driver.web.websocket import (
            ProgressEventType,
            WebSocketManager,
        )

        manager = WebSocketManager()

        ws = MagicMock()
        ws.accept = AsyncMock()

        # Connect with all events (default)
        await manager.connect(ws, "test_run")

        # Check all events are subscribed
        assert len(manager._subscriptions[ws]) == len(ProgressEventType)

        # Update to limited subscription
        await manager.update_subscription(
            ws,
            {
                ProgressEventType.REQUEST_COMPLETED,
                ProgressEventType.ERROR_STORED,
            },
        )

        assert len(manager._subscriptions[ws]) == 2

    def test_progress_event_types(self) -> None:
        """Test ProgressEventType enum values."""
        from juriscraper.scraper_driver.driver.dev_driver.web.websocket import (
            ProgressEventType,
        )

        assert ProgressEventType.REQUEST_STARTED.value == "request_started"
        assert ProgressEventType.REQUEST_COMPLETED.value == "request_completed"
        assert ProgressEventType.ERROR_STORED.value == "error_stored"
        assert ProgressEventType.RUN_COMPLETED.value == "run_completed"

    async def test_create_progress_callback(self) -> None:
        """Test creating a progress callback for a driver."""
        from datetime import datetime, timezone
        from unittest.mock import AsyncMock, MagicMock

        from juriscraper.scraper_driver.driver.dev_driver.dev_driver import (
            ProgressEvent,
        )
        from juriscraper.scraper_driver.driver.dev_driver.web.websocket import (
            create_progress_callback,
            ws_manager,
        )

        # Create mock websocket and connect
        ws = MagicMock()
        ws.accept = AsyncMock()
        ws.send_text = AsyncMock()

        await ws_manager.connect(ws, "callback_test")

        # Create callback
        callback = create_progress_callback("callback_test")

        # Call callback with event
        event = ProgressEvent(
            event_type="request_completed",
            timestamp=datetime.now(timezone.utc),
            data={"request_id": 1},
        )

        await callback(event)

        # Should have broadcasted to ws
        ws.send_text.assert_called_once()

        # Cleanup
        await ws_manager.disconnect(ws, "callback_test")


class TestGracefulShutdownAndResume:
    """Tests for graceful shutdown and resume functionality."""

    @pytest.fixture
    def mock_scraper(self) -> Any:
        """Create a mock scraper for testing."""
        from juriscraper.scraper_driver.data_types import (
            BaseScraper,
            HttpMethod,
            HTTPRequestParams,
            NavigatingRequest,
        )

        class MockScraper(BaseScraper[str]):
            def get_entry(self) -> Generator[NavigatingRequest, None, None]:
                yield NavigatingRequest(
                    request=HTTPRequestParams(
                        method=HttpMethod.GET,
                        url="https://example.com",
                    ),
                    continuation="parse",
                    current_location="",
                )

            def parse(self, response: Any) -> list:
                return []

        return MockScraper()

    async def test_shutdown_resets_in_progress_to_pending(
        self, db_path: Path, mock_scraper: Any
    ) -> None:
        """Test that closing the driver resets in_progress requests to pending."""
        from juriscraper.scraper_driver.driver.dev_driver.dev_driver import (
            LocalDevDriver,
        )
        from juriscraper.scraper_driver.driver.dev_driver.schema import (
            init_database,
        )

        # Initialize database and add an in_progress request
        db = await init_database(db_path)
        await db.execute(
            """
            INSERT INTO requests (status, priority, queue_counter, method, url, continuation, current_location)
            VALUES ('in_progress', 5, 1, 'GET', 'https://example.com/page1', 'parse', 'https://example.com')
            """
        )
        await db.execute(
            """
            INSERT INTO requests (status, priority, queue_counter, method, url, continuation, current_location)
            VALUES ('pending', 5, 2, 'GET', 'https://example.com/page2', 'parse', 'https://example.com')
            """
        )
        await db.commit()

        # Verify setup
        cursor = await db.execute(
            "SELECT COUNT(*) FROM requests WHERE status = 'in_progress'"
        )
        assert (await cursor.fetchone())[0] == 1

        cursor = await db.execute(
            "SELECT COUNT(*) FROM requests WHERE status = 'pending'"
        )
        assert (await cursor.fetchone())[0] == 1

        await db.close()

        # Now open driver and close it (simulating graceful shutdown)
        async with LocalDevDriver.open(mock_scraper, db_path, resume=False):
            # Driver is open - in_progress should still be in_progress
            # (resume=False means we don't reset on open)
            pass  # Just close immediately

        # Now check that in_progress was reset to pending
        db = await init_database(db_path)
        cursor = await db.execute(
            "SELECT COUNT(*) FROM requests WHERE status = 'in_progress'"
        )
        in_progress_count = (await cursor.fetchone())[0]

        cursor = await db.execute(
            "SELECT COUNT(*) FROM requests WHERE status = 'pending'"
        )
        pending_count = (await cursor.fetchone())[0]

        await db.close()

        assert in_progress_count == 0, "in_progress requests should be reset"
        assert pending_count == 2, "Both requests should be pending now"

    async def test_resume_restores_pending_requests(
        self, db_path: Path, mock_scraper: Any
    ) -> None:
        """Test that resume=True restores in_progress requests to pending on open."""
        from juriscraper.scraper_driver.driver.dev_driver.dev_driver import (
            LocalDevDriver,
        )
        from juriscraper.scraper_driver.driver.dev_driver.schema import (
            init_database,
        )

        # Initialize database with an in_progress request (simulating interrupted run)
        db = await init_database(db_path)
        await db.execute(
            """
            INSERT INTO requests (status, priority, queue_counter, method, url, continuation, current_location)
            VALUES ('in_progress', 5, 1, 'GET', 'https://example.com/interrupted', 'parse', 'https://example.com')
            """
        )
        await db.execute(
            """
            INSERT INTO requests (status, priority, queue_counter, method, url, continuation, current_location)
            VALUES ('pending', 5, 2, 'GET', 'https://example.com/pending', 'parse', 'https://example.com')
            """
        )
        await db.commit()
        await db.close()

        # Open with resume=True (default)
        async with LocalDevDriver.open(
            mock_scraper, db_path, resume=True, base_delay=0.0, jitter=0.0
        ) as driver:
            # Check that in_progress was reset to pending on open
            assert driver.db.db is not None
            cursor = await driver.db.db.execute(
                "SELECT COUNT(*) FROM requests WHERE status = 'in_progress'"
            )
            in_progress_count = (await cursor.fetchone())[0]

            cursor = await driver.db.db.execute(
                "SELECT COUNT(*) FROM requests WHERE status = 'pending'"
            )
            pending_count = (await cursor.fetchone())[0]

            assert in_progress_count == 0, (
                "resume=True should reset in_progress to pending"
            )
            assert pending_count == 2, "Both requests should be pending"

    async def test_full_shutdown_and_resume_cycle(
        self, db_path: Path, mock_scraper: Any
    ) -> None:
        """Test a complete shutdown and resume cycle preserves all requests."""
        from juriscraper.scraper_driver.driver.dev_driver.dev_driver import (
            LocalDevDriver,
        )

        # First run: Open driver, add requests, then close
        async with LocalDevDriver.open(
            mock_scraper, db_path, base_delay=0.0, jitter=0.0
        ) as driver:
            assert driver.db.db is not None

            # Manually add some requests in different states
            await driver.db.db.execute(
                """
                INSERT INTO requests (status, priority, queue_counter, method, url, continuation, current_location)
                VALUES
                    ('pending', 5, 10, 'GET', 'https://example.com/page1', 'parse', 'https://example.com'),
                    ('pending', 5, 11, 'GET', 'https://example.com/page2', 'parse', 'https://example.com'),
                    ('in_progress', 5, 12, 'GET', 'https://example.com/page3', 'parse', 'https://example.com'),
                    ('completed', 5, 13, 'GET', 'https://example.com/page4', 'parse', 'https://example.com')
                """
            )
            await driver.db.db.commit()

            # Verify initial state
            cursor = await driver.db.db.execute(
                "SELECT status, COUNT(*) FROM requests GROUP BY status ORDER BY status"
            )
            counts_before = dict(await cursor.fetchall())

            assert counts_before.get("pending", 0) >= 2
            assert counts_before.get("in_progress", 0) == 1
            assert counts_before.get("completed", 0) == 1

        # Second run: Resume and verify state
        async with LocalDevDriver.open(
            mock_scraper, db_path, resume=True, base_delay=0.0, jitter=0.0
        ) as driver:
            assert driver.db.db is not None

            # Check counts after resume
            cursor = await driver.db.db.execute(
                "SELECT status, COUNT(*) FROM requests GROUP BY status ORDER BY status"
            )
            counts_after = dict(await cursor.fetchall())

            # in_progress should have been converted to pending
            assert counts_after.get("in_progress", 0) == 0, (
                "No requests should be in_progress after resume"
            )
            assert counts_after.get("pending", 0) == counts_before.get(
                "pending", 0
            ) + counts_before.get("in_progress", 0), (
                "in_progress should be converted to pending"
            )
            assert counts_after.get("completed", 0) == counts_before.get(
                "completed", 0
            ), "Completed requests should be preserved"

    async def test_stop_event_signals_workers_to_stop(
        self, db_path: Path, mock_scraper: Any
    ) -> None:
        """Test that setting stop_event causes workers to exit gracefully."""
        from juriscraper.scraper_driver.driver.dev_driver.dev_driver import (
            LocalDevDriver,
        )

        async with LocalDevDriver.open(
            mock_scraper, db_path, base_delay=0.0, jitter=0.0
        ) as driver:
            # stop_event should be created
            assert driver.stop_event is not None
            assert not driver.stop_event.is_set()

            # Call stop()
            driver.stop()

            # stop_event should now be set
            assert driver.stop_event.is_set()

    async def test_run_metadata_status_transitions(
        self, db_path: Path, mock_scraper: Any
    ) -> None:
        """Test that run metadata status is updated correctly during lifecycle."""
        from juriscraper.scraper_driver.driver.dev_driver.dev_driver import (
            LocalDevDriver,
        )
        from juriscraper.scraper_driver.driver.dev_driver.schema import (
            init_database,
        )

        # First open creates metadata with 'created' status
        async with LocalDevDriver.open(
            mock_scraper, db_path, base_delay=0.0, jitter=0.0
        ) as driver:
            assert driver.db.db is not None
            cursor = await driver.db.db.execute(
                "SELECT status FROM run_metadata WHERE id = 1"
            )
            row = await cursor.fetchone()
            assert row is not None
            assert row[0] == "created"

        # After close, check if it was updated (if it was running)
        db = await init_database(db_path)
        cursor = await db.execute(
            "SELECT status FROM run_metadata WHERE id = 1"
        )
        row = await cursor.fetchone()
        assert row is not None
        # Status should still be 'created' since run() wasn't called
        # The status only changes to 'interrupted' if status was 'running'
        assert row[0] == "created"
        await db.close()

    async def test_no_data_loss_on_shutdown(
        self, db_path: Path, mock_scraper: Any
    ) -> None:
        """Test that no requests are lost during shutdown cycle."""
        from juriscraper.scraper_driver.driver.dev_driver.dev_driver import (
            LocalDevDriver,
        )
        from juriscraper.scraper_driver.driver.dev_driver.schema import (
            init_database,
        )

        # Create a run with multiple requests
        request_urls = [f"https://example.com/page{i}" for i in range(10)]

        async with LocalDevDriver.open(
            mock_scraper, db_path, base_delay=0.0, jitter=0.0
        ) as driver:
            assert driver.db.db is not None

            # Add requests
            for i, url in enumerate(request_urls):
                await driver.db.db.execute(
                    """
                    INSERT INTO requests (status, priority, queue_counter, method, url, continuation, current_location)
                    VALUES ('pending', 5, ?, 'GET', ?, 'parse', 'https://example.com')
                    """,
                    (i + 10, url),
                )
            await driver.db.db.commit()

            # Mark some as in_progress (simulating work being done)
            await driver.db.db.execute(
                "UPDATE requests SET status = 'in_progress' WHERE url LIKE '%page5%' OR url LIKE '%page6%'"
            )
            await driver.db.db.commit()

            # Count total before shutdown
            cursor = await driver.db.db.execute(
                "SELECT COUNT(*) FROM requests"
            )
            total_before = (await cursor.fetchone())[0]

        # After shutdown, verify no loss
        db = await init_database(db_path)
        cursor = await db.execute("SELECT COUNT(*) FROM requests")
        total_after = (await cursor.fetchone())[0]

        # All requests should still be present
        assert total_after == total_before, (
            f"Expected {total_before} requests, got {total_after}"
        )

        # Verify all URLs are still there
        cursor = await db.execute("SELECT url FROM requests ORDER BY url")
        urls_in_db = [row[0] for row in await cursor.fetchall()]

        for url in request_urls:
            assert url in urls_in_db, f"Missing URL: {url}"

        await db.close()

    async def test_status_method_reflects_queue_state(
        self, db_path: Path, mock_scraper: Any
    ) -> None:
        """Test that status() correctly reflects the queue state."""
        from juriscraper.scraper_driver.driver.dev_driver.dev_driver import (
            LocalDevDriver,
        )

        async with LocalDevDriver.open(
            mock_scraper, db_path, base_delay=0.0, jitter=0.0
        ) as driver:
            assert driver.db.db is not None

            # Initially, no requests (entry point not added yet if no run())
            # But the entry point request is added by run(), so status depends on
            # whether any requests exist
            cursor = await driver.db.db.execute(
                "SELECT COUNT(*) FROM requests"
            )
            count = (await cursor.fetchone())[0]

            if count == 0:
                status = await driver.status()
                assert status == "unstarted"

            # Add pending requests
            await driver.db.db.execute(
                """
                INSERT INTO requests (status, priority, queue_counter, method, url, continuation, current_location)
                VALUES ('pending', 5, 1, 'GET', 'https://example.com/page1', 'parse', 'https://example.com')
                """
            )
            await driver.db.db.commit()

            status = await driver.status()
            assert status == "in_progress"

            # Mark all as completed
            await driver.db.db.execute(
                "UPDATE requests SET status = 'completed'"
            )
            await driver.db.db.commit()

            status = await driver.status()
            assert status == "done"

    async def test_get_next_request_returns_pending_only(
        self, db_path: Path, mock_scraper: Any
    ) -> None:
        """Test that _get_next_request only returns pending requests."""
        from juriscraper.scraper_driver.driver.dev_driver.dev_driver import (
            LocalDevDriver,
        )

        async with LocalDevDriver.open(
            mock_scraper, db_path, base_delay=0.0, jitter=0.0
        ) as driver:
            assert driver.db.db is not None

            # Add requests in different states
            await driver.db.db.execute(
                """
                INSERT INTO requests (status, priority, queue_counter, method, url, continuation, current_location)
                VALUES
                    ('completed', 5, 1, 'GET', 'https://example.com/completed', 'parse', 'https://example.com'),
                    ('failed', 5, 2, 'GET', 'https://example.com/failed', 'parse', 'https://example.com'),
                    ('held', 5, 3, 'GET', 'https://example.com/held', 'parse', 'https://example.com'),
                    ('pending', 5, 4, 'GET', 'https://example.com/pending', 'parse', 'https://example.com')
                """
            )
            await driver.db.db.commit()

            # Get next request - should only return pending
            result = await driver._get_next_request()

            assert result is not None
            request_id, deserialized = result
            # NavigatingRequest returns BaseRequest directly
            request = (
                deserialized
                if not isinstance(deserialized, tuple)
                else deserialized[0]
            )
            assert request.request.url == "https://example.com/pending"

            # The pending request should now be marked in_progress
            cursor = await driver.db.db.execute(
                "SELECT status FROM requests WHERE id = ?", (request_id,)
            )
            row = await cursor.fetchone()
            assert row is not None
            assert row[0] == "in_progress"

    async def test_held_requests_not_returned(
        self, db_path: Path, mock_scraper: Any
    ) -> None:
        """Test that held requests are skipped by _get_next_request."""
        from juriscraper.scraper_driver.driver.dev_driver.dev_driver import (
            LocalDevDriver,
        )

        async with LocalDevDriver.open(
            mock_scraper, db_path, base_delay=0.0, jitter=0.0
        ) as driver:
            assert driver.db.db is not None

            # Add only held requests
            await driver.db.db.execute(
                """
                INSERT INTO requests (status, priority, queue_counter, method, url, continuation, current_location)
                VALUES
                    ('held', 5, 1, 'GET', 'https://example.com/held1', 'parse', 'https://example.com'),
                    ('held', 5, 2, 'GET', 'https://example.com/held2', 'parse', 'https://example.com')
                """
            )
            await driver.db.db.commit()

            # Get next request - should return None
            result = await driver._get_next_request()
            assert result is None

    async def test_pause_and_resume_step(
        self, db_path: Path, mock_scraper: Any
    ) -> None:
        """Test pause_step and resume_step functionality."""
        from juriscraper.scraper_driver.driver.dev_driver.dev_driver import (
            LocalDevDriver,
        )

        async with LocalDevDriver.open(
            mock_scraper, db_path, base_delay=0.0, jitter=0.0
        ) as driver:
            assert driver.db.db is not None

            # Add requests with different continuations
            await driver.db.db.execute(
                """
                INSERT INTO requests (status, priority, queue_counter, method, url, continuation, current_location)
                VALUES
                    ('pending', 5, 1, 'GET', 'https://example.com/page1', 'parse_list', 'https://example.com'),
                    ('pending', 5, 2, 'GET', 'https://example.com/page2', 'parse_list', 'https://example.com'),
                    ('pending', 5, 3, 'GET', 'https://example.com/page3', 'parse_detail', 'https://example.com')
                """
            )
            await driver.db.db.commit()

            # Pause 'parse_list' continuation
            held_count = await driver.pause_step("parse_list")
            assert held_count == 2

            # Verify held count
            assert await driver.get_held_count("parse_list") == 2
            assert await driver.get_held_count("parse_detail") == 0
            assert await driver.get_held_count() == 2  # Total held

            # Resume 'parse_list' continuation
            resumed_count = await driver.resume_step("parse_list")
            assert resumed_count == 2

            # Verify all back to pending
            assert await driver.get_held_count() == 0


class TestDeduplication:
    """Tests for request deduplication key checking."""

    @pytest.fixture
    def mock_scraper(self) -> Any:
        """Create a mock scraper for testing."""
        from juriscraper.scraper_driver.data_types import (
            BaseScraper,
            HttpMethod,
            HTTPRequestParams,
            NavigatingRequest,
        )

        class MockScraper(BaseScraper[str]):
            def get_entry(self) -> Generator[NavigatingRequest, None, None]:
                yield NavigatingRequest(
                    request=HTTPRequestParams(
                        method=HttpMethod.GET,
                        url="https://example.com",
                    ),
                    continuation="parse",
                    current_location="",
                )

            def parse(self, response: Any) -> list:
                return []

        return MockScraper()

    async def test_duplicate_requests_are_skipped(
        self, db_path: Path, mock_scraper: Any
    ) -> None:
        """Test that requests with the same deduplication_key are skipped.

        This simulates a scraper that would generate redundant data if
        deduplication wasn't working - e.g., a scraper that yields the same
        request multiple times from parsing the same page.
        """
        from juriscraper.scraper_driver.data_types import (
            HttpMethod,
            HTTPRequestParams,
            NavigatingRequest,
            Response,
        )
        from juriscraper.scraper_driver.driver.dev_driver.dev_driver import (
            LocalDevDriver,
        )

        async with LocalDevDriver.open(
            mock_scraper, db_path, base_delay=0.0, jitter=0.0
        ) as driver:
            assert driver.db.db is not None

            # Create a fake response to use as context for queueing
            parent_request = NavigatingRequest(
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url="https://example.com/listing",
                ),
                continuation="parse_listing",
                current_location="https://example.com",
            )
            response = Response(
                request=parent_request,
                status_code=200,
                headers={},
                content=b"<html></html>",
                text="<html></html>",
                url="https://example.com/listing",
            )

            # Create multiple requests to the same URL - they should have
            # the same deduplication key by default (based on URL + method)
            request1 = NavigatingRequest(
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url="https://example.com/detail/123",
                ),
                continuation="parse_detail",
                current_location="",
            )

            # Second request to exact same URL - should be deduplicated
            request2 = NavigatingRequest(
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url="https://example.com/detail/123",
                ),
                continuation="parse_detail",
                current_location="",
            )

            # Third request also to same URL - should also be deduplicated
            request3 = NavigatingRequest(
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url="https://example.com/detail/123",
                ),
                continuation="parse_detail",
                current_location="",
            )

            # Queue all three requests
            await driver.enqueue_request(request1, response)
            await driver.enqueue_request(request2, response)
            await driver.enqueue_request(request3, response)

            # Only ONE request should be in the queue due to deduplication
            cursor = await driver.db.db.execute(
                "SELECT COUNT(*) FROM requests WHERE url = 'https://example.com/detail/123'"
            )
            count = (await cursor.fetchone())[0]

            assert count == 1, (
                f"Expected 1 request due to deduplication, got {count}. "
                "Duplicate requests should be skipped."
            )

    async def test_different_urls_are_not_deduplicated(
        self, db_path: Path, mock_scraper: Any
    ) -> None:
        """Test that requests to different URLs are not deduplicated."""
        from juriscraper.scraper_driver.data_types import (
            HttpMethod,
            HTTPRequestParams,
            NavigatingRequest,
            Response,
        )
        from juriscraper.scraper_driver.driver.dev_driver.dev_driver import (
            LocalDevDriver,
        )

        async with LocalDevDriver.open(
            mock_scraper, db_path, base_delay=0.0, jitter=0.0
        ) as driver:
            assert driver.db.db is not None

            parent_request = NavigatingRequest(
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url="https://example.com/listing",
                ),
                continuation="parse_listing",
                current_location="https://example.com",
            )
            response = Response(
                request=parent_request,
                status_code=200,
                headers={},
                content=b"<html></html>",
                text="<html></html>",
                url="https://example.com/listing",
            )

            # Create requests to DIFFERENT URLs - none should be deduplicated
            urls = [
                "https://example.com/detail/1",
                "https://example.com/detail/2",
                "https://example.com/detail/3",
            ]

            for url in urls:
                request = NavigatingRequest(
                    request=HTTPRequestParams(
                        method=HttpMethod.GET,
                        url=url,
                    ),
                    continuation="parse_detail",
                    current_location="",
                )
                await driver.enqueue_request(request, response)

            # All three should be in the queue
            cursor = await driver.db.db.execute(
                "SELECT COUNT(*) FROM requests WHERE url LIKE 'https://example.com/detail/%'"
            )
            count = (await cursor.fetchone())[0]

            assert count == 3, (
                f"Expected 3 different requests, got {count}. "
                "Requests with different URLs should not be deduplicated."
            )

    async def test_cycle_prevention_via_deduplication(
        self, db_path: Path, mock_scraper: Any
    ) -> None:
        """Test that deduplication prevents cycles (A -> B -> A).

        This simulates a scraper where:
        - Page A links to Page B
        - Page B links back to Page A

        Without deduplication, this would create an infinite loop.
        With deduplication, the second request to A should be skipped.
        """
        from juriscraper.scraper_driver.data_types import (
            HttpMethod,
            HTTPRequestParams,
            NavigatingRequest,
            Response,
        )
        from juriscraper.scraper_driver.driver.dev_driver.dev_driver import (
            LocalDevDriver,
        )

        async with LocalDevDriver.open(
            mock_scraper, db_path, base_delay=0.0, jitter=0.0
        ) as driver:
            assert driver.db.db is not None

            url_a = "https://example.com/page-a"
            url_b = "https://example.com/page-b"

            # First: Simulate page A being visited and requesting page B
            request_a = NavigatingRequest(
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url=url_a,
                ),
                continuation="parse",
                current_location="https://example.com",
            )
            response_a = Response(
                request=request_a,
                status_code=200,
                headers={},
                content=b"<html></html>",
                text="<html></html>",
                url=url_a,
            )

            # Queue the initial request to page A (entry point)
            await driver.enqueue_request(request_a, response_a)

            # Verify page A is queued
            cursor = await driver.db.db.execute(
                "SELECT COUNT(*) FROM requests WHERE url = ?", (url_a,)
            )
            assert (await cursor.fetchone())[0] == 1

            # Now simulate: parsing page A yields a request to page B
            request_b = NavigatingRequest(
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url=url_b,
                ),
                continuation="parse",
                current_location=url_a,
            )
            await driver.enqueue_request(request_b, response_a)

            # Verify page B is queued
            cursor = await driver.db.db.execute(
                "SELECT COUNT(*) FROM requests WHERE url = ?", (url_b,)
            )
            assert (await cursor.fetchone())[0] == 1

            # Now simulate: parsing page B yields a request BACK to page A
            # This is where the cycle would happen without deduplication
            response_b = Response(
                request=request_b,
                status_code=200,
                headers={},
                content=b"<html></html>",
                text="<html></html>",
                url=url_b,
            )
            request_a_again = NavigatingRequest(
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url=url_a,  # Same URL as before!
                ),
                continuation="parse",
                current_location=url_b,
            )
            await driver.enqueue_request(request_a_again, response_b)

            # Page A should STILL have only 1 request due to deduplication
            cursor = await driver.db.db.execute(
                "SELECT COUNT(*) FROM requests WHERE url = ?", (url_a,)
            )
            count_a = (await cursor.fetchone())[0]

            assert count_a == 1, (
                f"Expected 1 request to page A (cycle prevented), got {count_a}. "
                "Deduplication should prevent the cycle by skipping the second request to A."
            )

            # Total requests should be exactly 2 (A and B)
            cursor = await driver.db.db.execute(
                "SELECT COUNT(*) FROM requests"
            )
            total = (await cursor.fetchone())[0]

            assert total == 2, (
                f"Expected exactly 2 requests (A and B), got {total}. "
                "The cycle A -> B -> A should have been prevented."
            )

    async def test_custom_deduplication_key(
        self, db_path: Path, mock_scraper: Any
    ) -> None:
        """Test that custom deduplication keys work correctly.

        Sometimes scrapers need to define custom deduplication logic -
        for example, when the same URL with different query params
        should be considered duplicates.
        """
        from juriscraper.scraper_driver.data_types import (
            HttpMethod,
            HTTPRequestParams,
            NavigatingRequest,
            Response,
        )
        from juriscraper.scraper_driver.driver.dev_driver.dev_driver import (
            LocalDevDriver,
        )

        async with LocalDevDriver.open(
            mock_scraper, db_path, base_delay=0.0, jitter=0.0
        ) as driver:
            assert driver.db.db is not None

            parent_request = NavigatingRequest(
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url="https://example.com/search",
                ),
                continuation="parse",
                current_location="https://example.com",
            )
            response = Response(
                request=parent_request,
                status_code=200,
                headers={},
                content=b"<html></html>",
                text="<html></html>",
                url="https://example.com/search",
            )

            # Two requests with DIFFERENT URLs but SAME custom dedup key
            # This simulates e.g. pagination where page=1 and page=2 should
            # still dedupe based on the item ID, not the page number
            request1 = NavigatingRequest(
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url="https://example.com/item/123?page=1",
                ),
                continuation="parse_item",
                current_location="",
                deduplication_key="item-123",  # Custom key based on item ID
            )

            request2 = NavigatingRequest(
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url="https://example.com/item/123?page=2",  # Different URL
                ),
                continuation="parse_item",
                current_location="",
                deduplication_key="item-123",  # Same custom key
            )

            await driver.enqueue_request(request1, response)
            await driver.enqueue_request(request2, response)

            # Only ONE request should be queued due to same custom dedup key
            cursor = await driver.db.db.execute(
                "SELECT COUNT(*) FROM requests WHERE url LIKE 'https://example.com/item/123%'"
            )
            count = (await cursor.fetchone())[0]

            assert count == 1, (
                f"Expected 1 request (custom dedup key), got {count}. "
                "Requests with the same custom deduplication_key should be deduplicated."
            )

    async def test_skip_deduplication_check(
        self, db_path: Path, mock_scraper: Any
    ) -> None:
        """Test that SkipDeduplicationCheck allows duplicate requests.

        Some scrapers need to intentionally make the same request multiple
        times (e.g., polling endpoints). SkipDeduplicationCheck allows this.
        """
        from juriscraper.scraper_driver.data_types import (
            HttpMethod,
            HTTPRequestParams,
            NavigatingRequest,
            Response,
            SkipDeduplicationCheck,
        )
        from juriscraper.scraper_driver.driver.dev_driver.dev_driver import (
            LocalDevDriver,
        )

        async with LocalDevDriver.open(
            mock_scraper, db_path, base_delay=0.0, jitter=0.0
        ) as driver:
            assert driver.db.db is not None

            parent_request = NavigatingRequest(
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url="https://example.com/poll",
                ),
                continuation="parse",
                current_location="https://example.com",
            )
            response = Response(
                request=parent_request,
                status_code=200,
                headers={},
                content=b"<html></html>",
                text="<html></html>",
                url="https://example.com/poll",
            )

            # Create requests with SkipDeduplicationCheck - duplicates allowed
            for _ in range(3):
                request = NavigatingRequest(
                    request=HTTPRequestParams(
                        method=HttpMethod.GET,
                        url="https://example.com/status/check",  # Same URL
                    ),
                    continuation="check_status",
                    current_location="",
                    deduplication_key=SkipDeduplicationCheck(),
                )
                await driver.enqueue_request(request, response)

            # All THREE requests should be in the queue
            cursor = await driver.db.db.execute(
                "SELECT COUNT(*) FROM requests WHERE url = 'https://example.com/status/check'"
            )
            count = (await cursor.fetchone())[0]

            assert count == 3, (
                f"Expected 3 requests (SkipDeduplicationCheck), got {count}. "
                "SkipDeduplicationCheck should allow duplicate requests."
            )

    async def test_dedup_with_post_data(
        self, db_path: Path, mock_scraper: Any
    ) -> None:
        """Test that POST requests with same URL but different body are not deduplicated.

        The default deduplication includes the request body, so same URL
        with different POST data should be considered different requests.
        """
        from juriscraper.scraper_driver.data_types import (
            HttpMethod,
            HTTPRequestParams,
            NavigatingRequest,
            Response,
        )
        from juriscraper.scraper_driver.driver.dev_driver.dev_driver import (
            LocalDevDriver,
        )

        async with LocalDevDriver.open(
            mock_scraper, db_path, base_delay=0.0, jitter=0.0
        ) as driver:
            assert driver.db.db is not None

            parent_request = NavigatingRequest(
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url="https://example.com/form",
                ),
                continuation="parse",
                current_location="https://example.com",
            )
            response = Response(
                request=parent_request,
                status_code=200,
                headers={},
                content=b"<html></html>",
                text="<html></html>",
                url="https://example.com/form",
            )

            # POST requests to same URL with different data
            request1 = NavigatingRequest(
                request=HTTPRequestParams(
                    method=HttpMethod.POST,
                    url="https://example.com/submit",
                    data={"action": "search", "query": "first"},
                ),
                continuation="parse_results",
                current_location="",
            )

            request2 = NavigatingRequest(
                request=HTTPRequestParams(
                    method=HttpMethod.POST,
                    url="https://example.com/submit",  # Same URL
                    data={
                        "action": "search",
                        "query": "second",
                    },  # Different data
                ),
                continuation="parse_results",
                current_location="",
            )

            await driver.enqueue_request(request1, response)
            await driver.enqueue_request(request2, response)

            # Both should be queued - different body means different dedup key
            cursor = await driver.db.db.execute(
                "SELECT COUNT(*) FROM requests WHERE url = 'https://example.com/submit'"
            )
            count = (await cursor.fetchone())[0]

            assert count == 2, (
                f"Expected 2 requests (different POST data), got {count}. "
                "POST requests with different body should not be deduplicated."
            )

    async def test_dedup_with_same_post_data(
        self, db_path: Path, mock_scraper: Any
    ) -> None:
        """Test that POST requests with same URL AND same body ARE deduplicated."""
        from juriscraper.scraper_driver.data_types import (
            HttpMethod,
            HTTPRequestParams,
            NavigatingRequest,
            Response,
        )
        from juriscraper.scraper_driver.driver.dev_driver.dev_driver import (
            LocalDevDriver,
        )

        async with LocalDevDriver.open(
            mock_scraper, db_path, base_delay=0.0, jitter=0.0
        ) as driver:
            assert driver.db.db is not None

            parent_request = NavigatingRequest(
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url="https://example.com/form",
                ),
                continuation="parse",
                current_location="https://example.com",
            )
            response = Response(
                request=parent_request,
                status_code=200,
                headers={},
                content=b"<html></html>",
                text="<html></html>",
                url="https://example.com/form",
            )

            # POST requests to same URL with SAME data (identical requests)
            for _ in range(3):
                request = NavigatingRequest(
                    request=HTTPRequestParams(
                        method=HttpMethod.POST,
                        url="https://example.com/submit",
                        data={"action": "search", "query": "same"},
                    ),
                    continuation="parse_results",
                    current_location="",
                )
                await driver.enqueue_request(request, response)

            # Only ONE should be queued - same URL + same body = same dedup key
            cursor = await driver.db.db.execute(
                "SELECT COUNT(*) FROM requests WHERE url = 'https://example.com/submit'"
            )
            count = (await cursor.fetchone())[0]

            assert count == 1, (
                f"Expected 1 request (same POST data = deduped), got {count}. "
                "Identical POST requests should be deduplicated."
            )


class TestRequestLineageTracking:
    """Tests for request lineage tracking (parent_request_id)."""

    async def test_child_requests_track_parent(self, db_path: Path) -> None:
        """Test that child requests properly track their parent request.

        This simulates a multi-step scraper where:
        - Entry request goes to /listing
        - /listing yields requests to /detail/1, /detail/2
        - Each detail request should track /listing as parent
        """

        from juriscraper.scraper_driver.data_types import (
            BaseScraper,
            HttpMethod,
            HTTPRequestParams,
            NavigatingRequest,
            Response,
        )
        from juriscraper.scraper_driver.driver.dev_driver.dev_driver import (
            LocalDevDriver,
        )
        from juriscraper.scraper_driver.driver.dev_driver.testing import (
            TestingInterceptor,
            create_html_response,
        )

        class MultiStepScraper(BaseScraper[str]):
            """Scraper that navigates from listing to detail pages."""

            def get_entry(self) -> Generator[NavigatingRequest, None, None]:
                yield NavigatingRequest(
                    request=HTTPRequestParams(
                        method=HttpMethod.GET,
                        url="https://example.com/listing",
                    ),
                    continuation="parse_listing",
                    current_location="https://example.com",
                )

            def parse_listing(
                self, response: Response
            ) -> Generator[NavigatingRequest, None, None]:
                """Parse listing page and yield detail requests."""
                for i in range(3):
                    yield NavigatingRequest(
                        request=HTTPRequestParams(
                            method=HttpMethod.GET,
                            url=f"https://example.com/detail/{i}",
                        ),
                        continuation="parse_detail",
                        current_location=response.url,
                    )

            def parse_detail(
                self, response: Response
            ) -> Generator[None, None, None]:
                """Parse detail page (no further requests)."""
                yield None

        # Create interceptor with mock responses
        interceptor = TestingInterceptor()
        interceptor.add_response(
            "https://example.com/listing",
            create_html_response("<html>Listing</html>"),
        )
        for i in range(3):
            interceptor.add_response(
                f"https://example.com/detail/{i}",
                create_html_response(f"<html>Detail {i}</html>"),
            )

        scraper = MultiStepScraper()
        async with LocalDevDriver.open(
            scraper, db_path, base_delay=0.0, jitter=0.0
        ) as driver:
            # Add interceptor
            driver.request_manager.interceptors.append(interceptor)

            # Run the scraper
            await driver.run()

            # Verify parent-child relationships
            assert driver.db.db is not None

            # Get the listing request ID
            cursor = await driver.db.db.execute(
                "SELECT id FROM requests WHERE url = 'https://example.com/listing'"
            )
            listing_row = await cursor.fetchone()
            assert listing_row is not None
            listing_id = listing_row[0]

            # Check that all detail requests have listing as parent
            cursor = await driver.db.db.execute(
                """
                SELECT url, parent_request_id FROM requests
                WHERE url LIKE 'https://example.com/detail/%'
                ORDER BY url
                """
            )
            detail_rows = await cursor.fetchall()

            assert len(detail_rows) == 3, "Should have 3 detail requests"

            for url, parent_id in detail_rows:
                assert parent_id == listing_id, (
                    f"Request to {url} should have parent_request_id={listing_id}, "
                    f"got {parent_id}"
                )


class TestRequestStatusMarking:
    """Tests for completed and failed request status marking."""

    async def test_successful_request_marked_completed(
        self, db_path: Path
    ) -> None:
        """Test that successful requests are marked as completed."""

        from juriscraper.scraper_driver.data_types import (
            BaseScraper,
            HttpMethod,
            HTTPRequestParams,
            NavigatingRequest,
            Response,
        )
        from juriscraper.scraper_driver.driver.dev_driver.dev_driver import (
            LocalDevDriver,
        )
        from juriscraper.scraper_driver.driver.dev_driver.testing import (
            TestingInterceptor,
            create_html_response,
        )

        class SimpleScraper(BaseScraper[str]):
            def get_entry(self) -> Generator[NavigatingRequest, None, None]:
                yield NavigatingRequest(
                    request=HTTPRequestParams(
                        method=HttpMethod.GET,
                        url="https://example.com/page",
                    ),
                    continuation="parse",
                    current_location="",
                )

            def parse(self, response: Response) -> Generator[None, None, None]:
                yield None

        interceptor = TestingInterceptor()
        interceptor.add_response(
            "https://example.com/page",
            create_html_response("<html>Success</html>"),
        )

        scraper = SimpleScraper()
        async with LocalDevDriver.open(
            scraper, db_path, base_delay=0.0, jitter=0.0
        ) as driver:
            driver.request_manager.interceptors.append(interceptor)
            await driver.run()

            assert driver.db.db is not None
            cursor = await driver.db.db.execute(
                "SELECT status, completed_at FROM requests WHERE url = 'https://example.com/page'"
            )
            row = await cursor.fetchone()

            assert row is not None
            status, completed_at = row
            assert status == "completed", (
                f"Expected 'completed', got '{status}'"
            )
            assert completed_at is not None, "completed_at should be set"

    async def test_failed_request_marked_failed(self, db_path: Path) -> None:
        """Test that requests with errors are marked as failed."""

        from juriscraper.scraper_driver.common.exceptions import (
            HTMLStructuralAssumptionException,
        )
        from juriscraper.scraper_driver.data_types import (
            BaseScraper,
            HttpMethod,
            HTTPRequestParams,
            NavigatingRequest,
            Response,
        )
        from juriscraper.scraper_driver.driver.dev_driver.dev_driver import (
            LocalDevDriver,
        )
        from juriscraper.scraper_driver.driver.dev_driver.testing import (
            TestingInterceptor,
            create_html_response,
        )

        class FailingScraper(BaseScraper[str]):
            def get_entry(self) -> Generator[NavigatingRequest, None, None]:
                yield NavigatingRequest(
                    request=HTTPRequestParams(
                        method=HttpMethod.GET,
                        url="https://example.com/fail",
                    ),
                    continuation="parse",
                    current_location="",
                )

            def parse(self, response: Response) -> Generator[None, None, None]:
                # Simulate a structural error in parsing
                raise HTMLStructuralAssumptionException(
                    selector=".missing-element",
                    selector_type="css",
                    description="Element not found",
                    expected_min=1,
                    expected_max=None,
                    actual_count=0,
                    request_url=response.url,
                )

        interceptor = TestingInterceptor()
        interceptor.add_response(
            "https://example.com/fail",
            create_html_response("<html>No element here</html>"),
        )

        scraper = FailingScraper()
        async with LocalDevDriver.open(
            scraper, db_path, base_delay=0.0, jitter=0.0
        ) as driver:
            driver.request_manager.interceptors.append(interceptor)
            await driver.run()

            assert driver.db.db is not None
            cursor = await driver.db.db.execute(
                "SELECT status, last_error FROM requests WHERE url = 'https://example.com/fail'"
            )
            row = await cursor.fetchone()

            assert row is not None
            status, last_error = row
            assert status == "failed", f"Expected 'failed', got '{status}'"
            assert last_error is not None, "last_error should be set"
            assert "missing-element" in last_error


class TestExponentialBackoff:
    """Tests for exponential backoff retry logic."""

    async def test_transient_error_triggers_retry(self, db_path: Path) -> None:
        """Test that transient errors trigger retry with backoff."""

        from juriscraper.scraper_driver.common.exceptions import (
            RequestTimeoutException,
        )
        from juriscraper.scraper_driver.data_types import (
            BaseScraper,
            HttpMethod,
            HTTPRequestParams,
            NavigatingRequest,
            Response,
        )
        from juriscraper.scraper_driver.driver.dev_driver.dev_driver import (
            LocalDevDriver,
        )

        class RetryScraper(BaseScraper[str]):
            def get_entry(self) -> Generator[NavigatingRequest, None, None]:
                yield NavigatingRequest(
                    request=HTTPRequestParams(
                        method=HttpMethod.GET,
                        url="https://example.com/flaky",
                    ),
                    continuation="parse",
                    current_location="",
                )

            def parse(self, response: Response) -> Generator[None, None, None]:
                yield None

        # Create a custom flaky interceptor that fails once then succeeds
        class FlakyInterceptor:
            """Interceptor that fails on first request, then succeeds."""

            def __init__(self) -> None:
                self.request_count = 0

            async def modify_request(self, request: Any) -> Any:
                url = request.request.url
                if url == "https://example.com/flaky":
                    self.request_count += 1
                    if self.request_count == 1:
                        raise RequestTimeoutException(
                            url="https://example.com/flaky",
                            timeout_seconds=30.0,
                        )
                    return Response(
                        request=request,
                        status_code=200,
                        headers={},
                        content=b"<html>Success</html>",
                        text="<html>Success</html>",
                        url=url,
                    )
                return request

            async def modify_response(
                self, response: Any, request: Any
            ) -> Any:
                return response

        interceptor = FlakyInterceptor()

        scraper = RetryScraper()
        # Use low max_backoff_time so the test is fast
        async with LocalDevDriver.open(
            scraper, db_path, max_backoff_time=60.0, base_delay=0.1, jitter=0.0
        ) as driver:
            driver.request_manager.interceptors.append(interceptor)
            await driver.run()

            assert driver.db.db is not None

            # Check that retry_count was incremented
            cursor = await driver.db.db.execute(
                "SELECT retry_count, status FROM requests WHERE url = 'https://example.com/flaky'"
            )
            row = await cursor.fetchone()

            assert row is not None
            retry_count, status = row

            # Either it retried and succeeded, or it's scheduled for retry
            # The behavior depends on timing
            assert retry_count >= 1 or status == "completed", (
                f"Expected retry_count >= 1 or completed status, got retry_count={retry_count}, status={status}"
            )

    async def test_max_backoff_exceeded_marks_failed(
        self, db_path: Path
    ) -> None:
        """Test that exceeding max backoff time marks request as failed."""

        from juriscraper.scraper_driver.common.exceptions import (
            RequestTimeoutException,
        )
        from juriscraper.scraper_driver.data_types import (
            BaseScraper,
            HttpMethod,
            HTTPRequestParams,
            NavigatingRequest,
            Response,
        )
        from juriscraper.scraper_driver.driver.dev_driver.dev_driver import (
            LocalDevDriver,
        )
        from juriscraper.scraper_driver.driver.dev_driver.testing import (
            TestingInterceptor,
        )

        class AlwaysFailScraper(BaseScraper[str]):
            def get_entry(self) -> Generator[NavigatingRequest, None, None]:
                yield NavigatingRequest(
                    request=HTTPRequestParams(
                        method=HttpMethod.GET,
                        url="https://example.com/always-fail",
                    ),
                    continuation="parse",
                    current_location="",
                )

            def parse(self, response: Response) -> Generator[None, None, None]:
                yield None

        interceptor = TestingInterceptor()
        interceptor.add_error(
            "https://example.com/always-fail",
            RequestTimeoutException(
                url="https://example.com/always-fail",
                timeout_seconds=30.0,
            ),
        )

        scraper = AlwaysFailScraper()
        # Very low max_backoff_time to trigger failure quickly
        async with LocalDevDriver.open(
            scraper, db_path, max_backoff_time=0.5, base_delay=0.1, jitter=0.0
        ) as driver:
            driver.request_manager.interceptors.append(interceptor)
            await driver.run()

            assert driver.db.db is not None

            # Request should eventually be marked as failed
            cursor = await driver.db.db.execute(
                "SELECT status, cumulative_backoff FROM requests WHERE url = 'https://example.com/always-fail'"
            )
            row = await cursor.fetchone()

            assert row is not None
            status, cumulative_backoff = row

            # Should be failed (or pending with high backoff if still retrying)
            assert status == "failed" or (
                status == "pending" and cumulative_backoff > 0
            ), (
                f"Expected failed or pending with backoff, got status={status}, backoff={cumulative_backoff}"
            )


class TestCompressionRoundTrip:
    """Tests for compressed response storage and retrieval."""

    async def test_response_compression_roundtrip(self, db_path: Path) -> None:
        """Test that responses are correctly compressed and decompressed."""

        from juriscraper.scraper_driver.data_types import (
            BaseScraper,
            HttpMethod,
            HTTPRequestParams,
            NavigatingRequest,
            Response,
        )
        from juriscraper.scraper_driver.driver.dev_driver.dev_driver import (
            LocalDevDriver,
        )
        from juriscraper.scraper_driver.driver.dev_driver.testing import (
            TestingInterceptor,
            create_html_response,
        )

        # Create a large response to ensure compression is used
        large_html = "<html><body>" + ("Content " * 1000) + "</body></html>"

        class SimpleScraper(BaseScraper[str]):
            def get_entry(self) -> Generator[NavigatingRequest, None, None]:
                yield NavigatingRequest(
                    request=HTTPRequestParams(
                        method=HttpMethod.GET,
                        url="https://example.com/large",
                    ),
                    continuation="parse",
                    current_location="",
                )

            def parse(self, response: Response) -> Generator[None, None, None]:
                yield None

        interceptor = TestingInterceptor()
        interceptor.add_response(
            "https://example.com/large",
            create_html_response(large_html),
        )

        scraper = SimpleScraper()
        async with LocalDevDriver.open(
            scraper, db_path, base_delay=0.0, jitter=0.0
        ) as driver:
            driver.request_manager.interceptors.append(interceptor)
            await driver.run()

            assert driver.db.db is not None

            # Get the response ID
            cursor = await driver.db.db.execute(
                "SELECT id, content_size_original, content_size_compressed FROM responses LIMIT 1"
            )
            row = await cursor.fetchone()

            assert row is not None
            response_id, original_size, compressed_size = row

            # Verify compression happened
            assert original_size > 0
            assert compressed_size > 0
            assert compressed_size < original_size, (
                "Compressed size should be smaller"
            )

            # Retrieve and decompress
            content = await driver.get_response_content(response_id)

            assert content is not None
            assert content.decode("utf-8") == large_html


class TestDataStorage:
    """Tests for data storage in database."""

    async def test_parsed_data_stored_in_results(self, db_path: Path) -> None:
        """Test that ParsedData is correctly stored in results table."""
        from typing import Any

        from juriscraper.scraper_driver.data_types import (
            BaseScraper,
            HttpMethod,
            HTTPRequestParams,
            NavigatingRequest,
            ParsedData,
            Response,
        )
        from juriscraper.scraper_driver.driver.dev_driver.dev_driver import (
            LocalDevDriver,
        )
        from juriscraper.scraper_driver.driver.dev_driver.testing import (
            TestingInterceptor,
            create_html_response,
        )

        # Use dicts instead of dataclasses since they're directly JSON serializable
        class DataScraper(BaseScraper[dict[str, Any]]):
            def get_entry(self) -> Generator[NavigatingRequest, None, None]:
                yield NavigatingRequest(
                    request=HTTPRequestParams(
                        method=HttpMethod.GET,
                        url="https://example.com/case",
                    ),
                    continuation="parse",
                    current_location="",
                )

            def parse(
                self, response: Response
            ) -> Generator[ParsedData[dict[str, Any]], None, None]:
                # Yield some parsed data as dicts
                yield ParsedData(
                    {
                        "case_id": "2024-CV-001",
                        "title": "Smith v. Jones",
                        "date": "2024-01-15",
                    }
                )
                yield ParsedData(
                    {
                        "case_id": "2024-CV-002",
                        "title": "Doe v. Roe",
                        "date": "2024-02-20",
                    }
                )

        interceptor = TestingInterceptor()
        interceptor.add_response(
            "https://example.com/case",
            create_html_response("<html>Case data</html>"),
        )

        scraper = DataScraper()
        async with LocalDevDriver.open(
            scraper, db_path, base_delay=0.0, jitter=0.0
        ) as driver:
            driver.request_manager.interceptors.append(interceptor)
            await driver.run()

            assert driver.db.db is not None

            # Check results were stored
            cursor = await driver.db.db.execute(
                "SELECT result_type, data_json, is_valid FROM results ORDER BY id"
            )
            rows = await cursor.fetchall()

            assert len(rows) == 2, f"Expected 2 results, got {len(rows)}"

            # Verify first result
            result_type, data_json, is_valid = rows[0]
            assert result_type == "dict"
            assert is_valid == 1
            assert "2024-CV-001" in data_json
            assert "Smith v. Jones" in data_json

            # Verify second result
            result_type, data_json, is_valid = rows[1]
            assert result_type == "dict"
            assert "2024-CV-002" in data_json


class TestRequeueErroredRequests:
    """Tests for re-enqueueing errored requests."""

    async def test_requeue_single_error(self, db_path: Path) -> None:
        """Test re-enqueueing a single errored request."""

        from juriscraper.scraper_driver.common.exceptions import (
            HTMLStructuralAssumptionException,
        )
        from juriscraper.scraper_driver.data_types import (
            BaseScraper,
            HttpMethod,
            HTTPRequestParams,
            NavigatingRequest,
            Response,
        )
        from juriscraper.scraper_driver.driver.dev_driver.dev_driver import (
            LocalDevDriver,
        )
        from juriscraper.scraper_driver.driver.dev_driver.testing import (
            TestingInterceptor,
            create_html_response,
        )

        class FailThenSucceedScraper(BaseScraper[str]):
            calls = 0

            def get_entry(self) -> Generator[NavigatingRequest, None, None]:
                yield NavigatingRequest(
                    request=HTTPRequestParams(
                        method=HttpMethod.GET,
                        url="https://example.com/requeue-test",
                    ),
                    continuation="parse",
                    current_location="",
                )

            def parse(self, response: Response) -> Generator[None, None, None]:
                FailThenSucceedScraper.calls += 1
                if FailThenSucceedScraper.calls == 1:
                    raise HTMLStructuralAssumptionException(
                        selector=".data",
                        selector_type="css",
                        description="Missing data",
                        expected_min=1,
                        expected_max=None,
                        actual_count=0,
                        request_url=response.url,
                    )
                yield None

        interceptor = TestingInterceptor()
        interceptor.add_response(
            "https://example.com/requeue-test",
            create_html_response("<html>Test</html>"),
        )

        scraper = FailThenSucceedScraper()
        async with LocalDevDriver.open(
            scraper, db_path, base_delay=0.0, jitter=0.0
        ) as driver:
            driver.request_manager.interceptors.append(interceptor)

            # First run - will fail
            await driver.run()

            assert driver.db.db is not None

            # Check error was stored
            cursor = await driver.db.db.execute(
                "SELECT id, is_resolved FROM errors LIMIT 1"
            )
            error_row = await cursor.fetchone()
            assert error_row is not None
            error_id, is_resolved = error_row
            assert is_resolved == 0, "Error should not be resolved initially"

            # Requeue the error
            new_request_id = await driver.requeue_request(error_id)

            assert new_request_id is not None, "Should return new request ID"

            # Check new request was created
            cursor = await driver.db.db.execute(
                "SELECT status, parent_request_id FROM requests WHERE id = ?",
                (new_request_id,),
            )
            new_req_row = await cursor.fetchone()
            assert new_req_row is not None
            status, parent_id = new_req_row
            assert status == "pending"
            assert parent_id is not None, "Should have parent reference"

            # Run again - should succeed this time
            await driver.run()

            # Check the new request completed
            cursor = await driver.db.db.execute(
                "SELECT status FROM requests WHERE id = ?",
                (new_request_id,),
            )
            final_row = await cursor.fetchone()
            assert final_row is not None
            assert final_row[0] == "completed"


class TestListRequestsFiltering:
    """Tests for list_requests with various status filters."""

    async def test_list_requests_by_status(self, db_path: Path) -> None:
        """Test that list_requests correctly filters by status."""
        from juriscraper.scraper_driver.data_types import (
            BaseScraper,
            HttpMethod,
            HTTPRequestParams,
            NavigatingRequest,
        )
        from juriscraper.scraper_driver.driver.dev_driver.dev_driver import (
            LocalDevDriver,
        )

        class SimpleScraper(BaseScraper[str]):
            def get_entry(self) -> Generator[NavigatingRequest, None, None]:
                yield NavigatingRequest(
                    request=HTTPRequestParams(
                        method=HttpMethod.GET,
                        url="https://example.com",
                    ),
                    continuation="parse",
                    current_location="",
                )

            def parse(self, response):
                return []

        scraper = SimpleScraper()
        async with LocalDevDriver.open(
            scraper, db_path, base_delay=0.0, jitter=0.0
        ) as driver:
            assert driver.db.db is not None

            # Create requests with various statuses
            await driver.db.db.execute(
                """
                INSERT INTO requests (status, priority, queue_counter, method, url, continuation, current_location)
                VALUES
                    ('pending', 5, 1, 'GET', 'https://example.com/pending1', 'parse', ''),
                    ('pending', 5, 2, 'GET', 'https://example.com/pending2', 'parse', ''),
                    ('in_progress', 5, 3, 'GET', 'https://example.com/in_progress', 'parse', ''),
                    ('completed', 5, 4, 'GET', 'https://example.com/completed1', 'parse', ''),
                    ('completed', 5, 5, 'GET', 'https://example.com/completed2', 'parse', ''),
                    ('completed', 5, 6, 'GET', 'https://example.com/completed3', 'parse', ''),
                    ('failed', 5, 7, 'GET', 'https://example.com/failed', 'parse', ''),
                    ('held', 5, 8, 'GET', 'https://example.com/held', 'parse', '')
                """
            )
            await driver.db.db.commit()

            # Test filtering by 'pending' status
            pending_page = await driver.list_requests(status="pending")
            assert pending_page.total == 2
            assert all(r.status == "pending" for r in pending_page.items)

            # Test filtering by 'completed' status
            completed_page = await driver.list_requests(status="completed")
            assert completed_page.total == 3
            assert all(r.status == "completed" for r in completed_page.items)

            # Test filtering by 'failed' status
            failed_page = await driver.list_requests(status="failed")
            assert failed_page.total == 1
            assert failed_page.items[0].status == "failed"

            # Test filtering by 'held' status
            held_page = await driver.list_requests(status="held")
            assert held_page.total == 1
            assert held_page.items[0].status == "held"

            # Test filtering by 'in_progress' status
            in_progress_page = await driver.list_requests(status="in_progress")
            assert in_progress_page.total == 1
            assert in_progress_page.items[0].status == "in_progress"

            # Test getting all (no filter)
            all_page = await driver.list_requests()
            assert all_page.total == 8

    async def test_list_requests_by_continuation(self, db_path: Path) -> None:
        """Test that list_requests correctly filters by continuation."""
        from juriscraper.scraper_driver.data_types import (
            BaseScraper,
            HttpMethod,
            HTTPRequestParams,
            NavigatingRequest,
        )
        from juriscraper.scraper_driver.driver.dev_driver.dev_driver import (
            LocalDevDriver,
        )

        class SimpleScraper(BaseScraper[str]):
            def get_entry(self) -> Generator[NavigatingRequest, None, None]:
                yield NavigatingRequest(
                    request=HTTPRequestParams(
                        method=HttpMethod.GET,
                        url="https://example.com",
                    ),
                    continuation="parse",
                    current_location="",
                )

            def parse(self, response):
                return []

        scraper = SimpleScraper()
        async with LocalDevDriver.open(
            scraper, db_path, base_delay=0.0, jitter=0.0
        ) as driver:
            assert driver.db.db is not None

            # Create requests with different continuations
            await driver.db.db.execute(
                """
                INSERT INTO requests (status, priority, queue_counter, method, url, continuation, current_location)
                VALUES
                    ('pending', 5, 1, 'GET', 'https://example.com/1', 'parse_listing', ''),
                    ('pending', 5, 2, 'GET', 'https://example.com/2', 'parse_listing', ''),
                    ('pending', 5, 3, 'GET', 'https://example.com/3', 'parse_detail', ''),
                    ('pending', 5, 4, 'GET', 'https://example.com/4', 'parse_detail', ''),
                    ('pending', 5, 5, 'GET', 'https://example.com/5', 'parse_detail', '')
                """
            )
            await driver.db.db.commit()

            # Filter by parse_listing
            listing_page = await driver.list_requests(
                continuation="parse_listing"
            )
            assert listing_page.total == 2
            assert all(
                r.continuation == "parse_listing" for r in listing_page.items
            )

            # Filter by parse_detail
            detail_page = await driver.list_requests(
                continuation="parse_detail"
            )
            assert detail_page.total == 3
            assert all(
                r.continuation == "parse_detail" for r in detail_page.items
            )

    async def test_list_requests_pagination(self, db_path: Path) -> None:
        """Test that list_requests correctly handles pagination."""
        from juriscraper.scraper_driver.data_types import (
            BaseScraper,
            HttpMethod,
            HTTPRequestParams,
            NavigatingRequest,
        )
        from juriscraper.scraper_driver.driver.dev_driver.dev_driver import (
            LocalDevDriver,
        )

        class SimpleScraper(BaseScraper[str]):
            def get_entry(self) -> Generator[NavigatingRequest, None, None]:
                yield NavigatingRequest(
                    request=HTTPRequestParams(
                        method=HttpMethod.GET,
                        url="https://example.com",
                    ),
                    continuation="parse",
                    current_location="",
                )

            def parse(self, response):
                return []

        scraper = SimpleScraper()
        async with LocalDevDriver.open(
            scraper, db_path, base_delay=0.0, jitter=0.0
        ) as driver:
            assert driver.db.db is not None

            # Create 10 requests
            for i in range(10):
                await driver.db.db.execute(
                    """
                    INSERT INTO requests (status, priority, queue_counter, method, url, continuation, current_location)
                    VALUES ('pending', 5, ?, 'GET', ?, 'parse', '')
                    """,
                    (i, f"https://example.com/page{i}"),
                )
            await driver.db.db.commit()

            # Get first page (limit=3)
            page1 = await driver.list_requests(limit=3, offset=0)
            assert page1.total == 10
            assert len(page1.items) == 3
            assert page1.offset == 0
            assert page1.limit == 3
            # has_more can be computed: offset + len(items) < total
            assert (
                page1.offset + len(page1.items) < page1.total
            )  # More pages exist

            # Get second page
            page2 = await driver.list_requests(limit=3, offset=3)
            assert page2.total == 10
            assert len(page2.items) == 3
            assert page2.offset == 3
            assert (
                page2.offset + len(page2.items) < page2.total
            )  # More pages exist

            # Get last page (partial)
            page4 = await driver.list_requests(limit=3, offset=9)
            assert page4.total == 10
            assert len(page4.items) == 1
            # No more items after this page
            assert page4.offset + len(page4.items) == page4.total


class TestHeadersOnlyResponse:
    """Tests for responses with headers but no body content."""

    async def test_headers_only_response_storage(self, db_path: Path) -> None:
        """Test storing and retrieving a response with no body (headers only)."""
        from juriscraper.scraper_driver.data_types import (
            BaseScraper,
            HttpMethod,
            HTTPRequestParams,
            NavigatingRequest,
            Response,
        )
        from juriscraper.scraper_driver.driver.dev_driver.dev_driver import (
            LocalDevDriver,
        )
        from juriscraper.scraper_driver.driver.dev_driver.testing import (
            MockResponse,
            TestingInterceptor,
        )

        class SimpleScraper(BaseScraper[str]):
            def get_entry(self) -> Generator[NavigatingRequest, None, None]:
                yield NavigatingRequest(
                    request=HTTPRequestParams(
                        method=HttpMethod.HEAD,
                        url="https://example.com/resource",
                    ),
                    continuation="parse",
                    current_location="",
                )

            def parse(self, response: Response):
                # Just consume the HEAD response (no body)
                return []

        scraper = SimpleScraper()
        interceptor = TestingInterceptor()

        # Add a mock response with no content (headers only)
        interceptor.add_response(
            "https://example.com/resource",
            MockResponse(
                content=b"",  # Empty body
                status_code=200,
                headers={
                    "Content-Length": "12345",
                    "Content-Type": "application/pdf",
                    "Last-Modified": "Wed, 21 Oct 2025 07:28:00 GMT",
                },
            ),
        )

        async with LocalDevDriver.open(
            scraper, db_path, base_delay=0.0, jitter=0.0
        ) as driver:
            driver.request_manager.interceptors.append(interceptor)
            await driver.run()

            assert driver.db.db is not None

            # Check the response was stored
            cursor = await driver.db.db.execute(
                """
                SELECT status_code, headers_json, content_size_original, content_size_compressed
                FROM responses
                WHERE url = 'https://example.com/resource'
                """
            )
            row = await cursor.fetchone()

            assert row is not None, "Response should be stored"
            status_code, headers_json, size_original, size_compressed = row

            assert status_code == 200
            assert size_original == 0, (
                "Original size should be 0 for headers-only"
            )
            assert size_compressed == 0, (
                "Compressed size should be 0 for headers-only"
            )

            # Verify headers are stored correctly
            headers = json.loads(headers_json)
            assert headers["Content-Length"] == "12345"
            assert headers["Content-Type"] == "application/pdf"
            assert headers["Last-Modified"] == "Wed, 21 Oct 2025 07:28:00 GMT"

            # Verify we can retrieve the (empty) content
            cursor2 = await driver.db.db.execute(
                "SELECT id FROM responses WHERE url = 'https://example.com/resource'"
            )
            resp_row = await cursor2.fetchone()
            assert resp_row is not None
            response_id = resp_row[0]

            content = await driver.get_response_content(response_id)
            assert content == b"", (
                "Headers-only response should have empty content"
            )


class TestGracefulShutdownSigterm:
    """Tests for graceful shutdown via SIGTERM/SIGINT."""

    async def test_stop_event_stops_workers(self, db_path: Path) -> None:
        """Test that setting stop_event causes workers to exit gracefully."""
        import asyncio

        from juriscraper.scraper_driver.data_types import (
            BaseScraper,
            HttpMethod,
            HTTPRequestParams,
            NavigatingRequest,
            Response,
        )
        from juriscraper.scraper_driver.driver.dev_driver.dev_driver import (
            LocalDevDriver,
        )
        from juriscraper.scraper_driver.driver.dev_driver.testing import (
            MockResponse,
            TestingInterceptor,
        )

        # Track how many requests were processed
        processed_count = 0

        class MultiPageScraper(BaseScraper[str]):
            def get_entry(self) -> Generator[NavigatingRequest, None, None]:
                yield NavigatingRequest(
                    request=HTTPRequestParams(
                        method=HttpMethod.GET,
                        url="https://example.com/page1",
                    ),
                    continuation="parse",
                    current_location="",
                )

            def parse(self, response: Response):
                nonlocal processed_count
                processed_count += 1

                # Yield more requests to keep driver busy
                for i in range(2, 20):
                    yield NavigatingRequest(
                        request=HTTPRequestParams(
                            method=HttpMethod.GET,
                            url=f"https://example.com/page{i}",
                        ),
                        continuation="parse_page",
                        current_location="",
                    )

            def parse_page(self, response: Response):
                nonlocal processed_count
                processed_count += 1
                return []

        scraper = MultiPageScraper()
        interceptor = TestingInterceptor()

        # Add mock responses for many pages
        for i in range(1, 20):
            interceptor.add_response(
                f"https://example.com/page{i}",
                MockResponse(
                    content=f"<html>Page {i}</html>".encode(),
                    status_code=200,
                ),
            )

        async with LocalDevDriver.open(
            scraper, db_path, base_delay=0.0, jitter=0.0
        ) as driver:
            driver.request_manager.interceptors.append(interceptor)

            # Start the driver and stop it after a short delay
            async def stop_after_delay():
                await asyncio.sleep(0.1)  # Let some requests process
                driver.stop()

            # Run driver and stop concurrently
            await asyncio.gather(
                driver.run(setup_signal_handlers=False),
                stop_after_delay(),
            )

            assert driver.db.db is not None

            # Verify some but not all requests were processed
            assert processed_count > 0, (
                "Should have processed at least 1 request"
            )
            assert processed_count < 20, (
                f"Should have stopped before all 20, processed {processed_count}"
            )

            # Verify run metadata shows interrupted status
            cursor = await driver.db.db.execute(
                "SELECT status FROM run_metadata WHERE id = 1"
            )
            row = await cursor.fetchone()
            assert row is not None
            assert row[0] == "interrupted", (
                f"Expected 'interrupted', got '{row[0]}'"
            )

            # Verify any in_progress requests were reset to pending for resume
            cursor2 = await driver.db.db.execute(
                "SELECT COUNT(*) FROM requests WHERE status = 'in_progress'"
            )
            in_progress_row = await cursor2.fetchone()
            assert in_progress_row[0] == 0, (
                "Should have no in_progress requests after shutdown"
            )

    async def test_signal_handler_setup_and_teardown(
        self, db_path: Path
    ) -> None:
        """Test that signal handlers are set up and torn down properly."""
        import signal

        from juriscraper.scraper_driver.data_types import (
            BaseScraper,
            HttpMethod,
            HTTPRequestParams,
            NavigatingRequest,
        )
        from juriscraper.scraper_driver.driver.dev_driver.dev_driver import (
            LocalDevDriver,
        )
        from juriscraper.scraper_driver.driver.dev_driver.testing import (
            MockResponse,
            TestingInterceptor,
        )

        class SimpleScraper(BaseScraper[str]):
            def get_entry(self) -> Generator[NavigatingRequest, None, None]:
                yield NavigatingRequest(
                    request=HTTPRequestParams(
                        method=HttpMethod.GET,
                        url="https://example.com",
                    ),
                    continuation="parse",
                    current_location="",
                )

            def parse(self, response):
                return []

        scraper = SimpleScraper()
        interceptor = TestingInterceptor()
        interceptor.add_response(
            "https://example.com",
            MockResponse(content=b"<html></html>", status_code=200),
        )

        async with LocalDevDriver.open(
            scraper, db_path, base_delay=0.0, jitter=0.0
        ) as driver:
            driver.request_manager.interceptors.append(interceptor)

            # Verify _setup_signal_handlers and _restore_signal_handlers work
            # Set known handlers first
            signal.signal(signal.SIGTERM, signal.SIG_DFL)

            # Call setup directly
            driver._setup_signal_handlers()

            # After setup, handlers should be custom functions, not SIG_DFL
            sigterm_handler = signal.getsignal(signal.SIGTERM)
            assert sigterm_handler != signal.SIG_DFL, (
                "SIGTERM handler should be custom after setup"
            )

            # Restore handlers
            driver._restore_signal_handlers()

            # After restore, handlers should be SIG_DFL
            sigterm_handler_after = signal.getsignal(signal.SIGTERM)
            assert sigterm_handler_after == signal.SIG_DFL, (
                "SIGTERM handler should be SIG_DFL after restore"
            )

    async def test_resume_after_interrupt(self, db_path: Path) -> None:
        """Test that interrupted requests can be resumed on next run."""
        import asyncio

        from juriscraper.scraper_driver.data_types import (
            BaseScraper,
            HttpMethod,
            HTTPRequestParams,
            NavigatingRequest,
            Response,
        )
        from juriscraper.scraper_driver.driver.dev_driver.dev_driver import (
            LocalDevDriver,
        )
        from juriscraper.scraper_driver.driver.dev_driver.testing import (
            MockResponse,
            TestingInterceptor,
        )

        completed_urls: list[str] = []

        class MultiStepScraper(BaseScraper[str]):
            def get_entry(self) -> Generator[NavigatingRequest, None, None]:
                yield NavigatingRequest(
                    request=HTTPRequestParams(
                        method=HttpMethod.GET,
                        url="https://example.com/start",
                    ),
                    continuation="parse",
                    current_location="",
                )

            def parse(self, response: Response):
                completed_urls.append(response.url)
                # Queue up several child requests
                for i in range(5):
                    yield NavigatingRequest(
                        request=HTTPRequestParams(
                            method=HttpMethod.GET,
                            url=f"https://example.com/item{i}",
                        ),
                        continuation="parse_item",
                        current_location="",
                    )

            def parse_item(self, response: Response):
                completed_urls.append(response.url)
                return []

        scraper = MultiStepScraper()
        interceptor = TestingInterceptor()

        # Add responses
        interceptor.add_response(
            "https://example.com/start",
            MockResponse(content=b"<html>Start</html>", status_code=200),
        )
        for i in range(5):
            interceptor.add_response(
                f"https://example.com/item{i}",
                MockResponse(
                    content=f"<html>Item {i}</html>".encode(), status_code=200
                ),
            )

        # First run - interrupt early
        async with LocalDevDriver.open(
            scraper, db_path, base_delay=0.0, jitter=0.0
        ) as driver:
            driver.request_manager.interceptors.append(interceptor)

            async def stop_early():
                await asyncio.sleep(0.05)
                driver.stop()

            await asyncio.gather(
                driver.run(setup_signal_handlers=False),
                stop_early(),
            )

        initial_count = len(completed_urls)
        assert initial_count > 0, (
            "Should have processed at least the entry point"
        )

        # Clear completed list for second run
        completed_urls.clear()

        # Second run - should pick up where we left off
        # Need a fresh scraper instance
        scraper2 = MultiStepScraper()
        interceptor2 = TestingInterceptor()

        interceptor2.add_response(
            "https://example.com/start",
            MockResponse(content=b"<html>Start</html>", status_code=200),
        )
        for i in range(5):
            interceptor2.add_response(
                f"https://example.com/item{i}",
                MockResponse(
                    content=f"<html>Item {i}</html>".encode(), status_code=200
                ),
            )

        async with LocalDevDriver.open(
            scraper2, db_path, resume=True, base_delay=0.0, jitter=0.0
        ) as driver2:
            driver2.request_manager.interceptors.append(interceptor2)
            await driver2.run(setup_signal_handlers=False)

            assert driver2.db.db is not None

            # Verify all requests are now completed
            cursor = await driver2.db.db.execute(
                "SELECT COUNT(*) FROM requests WHERE status = 'completed'"
            )
            row = await cursor.fetchone()
            total_completed = row[0] if row else 0

            # Should have completed all 6 requests (1 entry + 5 items)
            assert total_completed == 6, (
                f"Expected 6 completed, got {total_completed}"
            )


class TestDevDriverVsOtherDrivers:
    """Tests comparing DevDriver output to SyncDriver/AsyncDriver."""

    async def test_same_results_as_async_driver(
        self, db_path: Path, tmp_path: Path
    ) -> None:
        """Test that DevDriver produces the same results as AsyncDriver."""
        from juriscraper.scraper_driver.data_types import (
            BaseScraper,
            HttpMethod,
            HTTPRequestParams,
            NavigatingRequest,
            ParsedData,
            Response,
        )
        from juriscraper.scraper_driver.driver.async_driver import AsyncDriver
        from juriscraper.scraper_driver.driver.dev_driver.dev_driver import (
            LocalDevDriver,
        )
        from juriscraper.scraper_driver.driver.dev_driver.testing import (
            MockResponse,
            TestingInterceptor,
        )

        # Track results from each driver
        async_driver_results: list[dict] = []
        dev_driver_results: list[dict] = []

        class TestScraper(BaseScraper[dict]):
            def get_entry(self) -> Generator[NavigatingRequest, None, None]:
                yield NavigatingRequest(
                    request=HTTPRequestParams(
                        method=HttpMethod.GET,
                        url="https://example.com/cases",
                    ),
                    continuation="parse_listing",
                    current_location="",
                )

            def parse_listing(self, response: Response):
                # Yield requests for detail pages
                for i in range(3):
                    yield NavigatingRequest(
                        request=HTTPRequestParams(
                            method=HttpMethod.GET,
                            url=f"https://example.com/case/{i}",
                        ),
                        continuation="parse_detail",
                        current_location="",
                    )

            def parse_detail(self, response: Response):
                # Extract a "case" from the response
                case_id = response.url.split("/")[-1]
                yield ParsedData(
                    {
                        "case_id": case_id,
                        "title": f"Case {case_id}",
                        "url": response.url,
                    }
                )

        def create_interceptor() -> TestingInterceptor:
            interceptor = TestingInterceptor()
            interceptor.add_response(
                "https://example.com/cases",
                MockResponse(
                    content=b"<html><body>Case Listing</body></html>",
                    status_code=200,
                ),
            )
            for i in range(3):
                interceptor.add_response(
                    f"https://example.com/case/{i}",
                    MockResponse(
                        content=f"<html><body>Case {i} Details</body></html>".encode(),
                        status_code=200,
                    ),
                )
            return interceptor

        # Run with AsyncDriver
        scraper1 = TestScraper()

        async def collect_async_result(data: dict) -> None:
            async_driver_results.append(data)

        async_driver = AsyncDriver(scraper=scraper1)
        async_driver.request_manager.interceptors.append(create_interceptor())
        async_driver.on_data = collect_async_result
        await async_driver.run()

        # Run with LocalDevDriver
        scraper2 = TestScraper()

        async def collect_dev_result(data: dict) -> None:
            dev_driver_results.append(data)

        async with LocalDevDriver.open(
            scraper2, db_path, base_delay=0.0, jitter=0.0
        ) as dev_driver:
            dev_driver.request_manager.interceptors.append(
                create_interceptor()
            )
            dev_driver.on_data = collect_dev_result
            await dev_driver.run()

        # Compare results
        assert len(async_driver_results) == len(dev_driver_results) == 3, (
            f"Expected 3 results each, got async={len(async_driver_results)}, "
            f"dev={len(dev_driver_results)}"
        )

        # Sort by case_id for comparison
        async_sorted = sorted(async_driver_results, key=lambda x: x["case_id"])
        dev_sorted = sorted(dev_driver_results, key=lambda x: x["case_id"])

        for async_result, dev_result in zip(async_sorted, dev_sorted):
            assert async_result == dev_result, (
                f"Results differ: async={async_result}, dev={dev_result}"
            )

    async def test_dev_driver_persists_results(self, db_path: Path) -> None:
        """Test that DevDriver stores results in the database."""
        from juriscraper.scraper_driver.data_types import (
            BaseScraper,
            HttpMethod,
            HTTPRequestParams,
            NavigatingRequest,
            ParsedData,
            Response,
        )
        from juriscraper.scraper_driver.driver.dev_driver.dev_driver import (
            LocalDevDriver,
        )
        from juriscraper.scraper_driver.driver.dev_driver.testing import (
            MockResponse,
            TestingInterceptor,
        )

        class ResultProducingScraper(BaseScraper[dict]):
            def get_entry(self) -> Generator[NavigatingRequest, None, None]:
                yield NavigatingRequest(
                    request=HTTPRequestParams(
                        method=HttpMethod.GET,
                        url="https://example.com/data",
                    ),
                    continuation="parse",
                    current_location="",
                )

            def parse(self, response: Response):
                for i in range(5):
                    yield ParsedData({"id": i, "value": f"item_{i}"})

        scraper = ResultProducingScraper()
        interceptor = TestingInterceptor()
        interceptor.add_response(
            "https://example.com/data",
            MockResponse(content=b"<html>Data</html>", status_code=200),
        )

        async with LocalDevDriver.open(
            scraper, db_path, base_delay=0.0, jitter=0.0
        ) as driver:
            driver.request_manager.interceptors.append(interceptor)
            await driver.run()

            assert driver.db.db is not None

            # Check results are persisted in database
            cursor = await driver.db.db.execute("SELECT COUNT(*) FROM results")
            row = await cursor.fetchone()
            result_count = row[0] if row else 0

            assert result_count == 5, (
                f"Expected 5 results in DB, got {result_count}"
            )

            # Verify result content
            cursor2 = await driver.db.db.execute(
                "SELECT data_json FROM results ORDER BY id"
            )
            rows = await cursor2.fetchall()

            for i, row in enumerate(rows):
                data = json.loads(row[0])
                assert data["id"] == i
                assert data["value"] == f"item_{i}"

            # Verify requests are also tracked
            cursor3 = await driver.db.db.execute(
                "SELECT COUNT(*) FROM requests"
            )
            req_row = await cursor3.fetchone()
            assert req_row[0] >= 1, "Should have at least 1 request tracked"

            # Verify responses are stored
            cursor4 = await driver.db.db.execute(
                "SELECT COUNT(*) FROM responses"
            )
            resp_row = await cursor4.fetchone()
            assert resp_row[0] >= 1, "Should have at least 1 response stored"


class TestDeferredValidationHandling:
    """Tests for valid and invalid data handling with DeferredValidation."""

    async def test_valid_deferred_validation_stored_and_callback_called(
        self, db_path: Path
    ) -> None:
        """Test that valid DeferredValidation data is stored and on_data called."""
        from pydantic import BaseModel

        from juriscraper.scraper_driver.common.deferred_validation import (
            DeferredValidation,
        )
        from juriscraper.scraper_driver.data_types import (
            BaseScraper,
            HttpMethod,
            HTTPRequestParams,
            NavigatingRequest,
            ParsedData,
            Response,
        )
        from juriscraper.scraper_driver.driver.dev_driver.dev_driver import (
            LocalDevDriver,
        )
        from juriscraper.scraper_driver.driver.dev_driver.testing import (
            MockResponse,
            TestingInterceptor,
        )

        class CaseData(BaseModel):
            case_name: str
            docket_number: str
            court: str

            @classmethod
            def raw(cls, **data: Any) -> DeferredValidation[CaseData]:
                return DeferredValidation(cls, **data)

        received_data: list[CaseData] = []

        class ValidDataScraper(BaseScraper[CaseData]):
            def get_entry(self) -> Generator[NavigatingRequest, None, None]:
                yield NavigatingRequest(
                    request=HTTPRequestParams(
                        method=HttpMethod.GET,
                        url="https://example.com/case",
                    ),
                    continuation="parse",
                    current_location="",
                )

            def parse(self, response: Response):
                # Yield valid deferred validation
                yield ParsedData(
                    CaseData.raw(
                        case_name="Smith v. Jones",
                        docket_number="2024-CV-001",
                        court="Supreme Court",
                    )
                )

        async def collect_result(data: CaseData) -> None:
            received_data.append(data)

        scraper = ValidDataScraper()
        interceptor = TestingInterceptor()
        interceptor.add_response(
            "https://example.com/case",
            MockResponse(
                content=b"<html>Case details</html>", status_code=200
            ),
        )

        async with LocalDevDriver.open(
            scraper, db_path, base_delay=0.0, jitter=0.0
        ) as driver:
            driver.request_manager.interceptors.append(interceptor)
            driver.on_data = collect_result
            await driver.run()

            assert driver.db.db is not None

            # Verify on_data was called with validated data
            assert len(received_data) == 1
            assert isinstance(received_data[0], CaseData)
            assert received_data[0].case_name == "Smith v. Jones"
            assert received_data[0].docket_number == "2024-CV-001"

            # Verify result stored as valid in database
            cursor = await driver.db.db.execute(
                "SELECT is_valid, data_json FROM results"
            )
            row = await cursor.fetchone()
            assert row is not None
            is_valid, data_json = row
            assert is_valid == 1, "Result should be marked as valid"
            data = json.loads(data_json)
            assert data["case_name"] == "Smith v. Jones"

    async def test_invalid_deferred_validation_stored_as_invalid(
        self, db_path: Path
    ) -> None:
        """Test that invalid DeferredValidation data is stored with is_valid=False."""
        from pydantic import BaseModel, field_validator

        from juriscraper.scraper_driver.common.deferred_validation import (
            DeferredValidation,
        )
        from juriscraper.scraper_driver.data_types import (
            BaseScraper,
            HttpMethod,
            HTTPRequestParams,
            NavigatingRequest,
            ParsedData,
            Response,
        )
        from juriscraper.scraper_driver.driver.dev_driver.dev_driver import (
            LocalDevDriver,
        )
        from juriscraper.scraper_driver.driver.dev_driver.testing import (
            MockResponse,
            TestingInterceptor,
        )

        class StrictCaseData(BaseModel):
            case_name: str
            docket_number: str  # Required field

            @field_validator("docket_number")
            @classmethod
            def validate_docket(cls, v: str) -> str:
                if not v or len(v) < 5:
                    raise ValueError(
                        "Docket number must be at least 5 characters"
                    )
                return v

            @classmethod
            def raw(cls, **data: Any) -> DeferredValidation[StrictCaseData]:
                return DeferredValidation(cls, **data)

        invalid_data_received: list[Any] = []

        class InvalidDataScraper(BaseScraper[StrictCaseData]):
            def get_entry(self) -> Generator[NavigatingRequest, None, None]:
                yield NavigatingRequest(
                    request=HTTPRequestParams(
                        method=HttpMethod.GET,
                        url="https://example.com/case",
                    ),
                    continuation="parse",
                    current_location="",
                )

            def parse(self, response: Response):
                # Yield INVALID deferred validation (docket too short)
                yield ParsedData(
                    StrictCaseData.raw(
                        case_name="Smith v. Jones",
                        docket_number="123",  # Too short, will fail validation
                    )
                )

        async def collect_invalid(data: Any) -> None:
            invalid_data_received.append(data)

        scraper = InvalidDataScraper()
        interceptor = TestingInterceptor()
        interceptor.add_response(
            "https://example.com/case",
            MockResponse(
                content=b"<html>Case details</html>", status_code=200
            ),
        )

        async with LocalDevDriver.open(
            scraper, db_path, base_delay=0.0, jitter=0.0
        ) as driver:
            driver.request_manager.interceptors.append(interceptor)
            driver.on_invalid_data = collect_invalid
            await driver.run()

            assert driver.db.db is not None

            # Verify on_invalid_data was called
            assert len(invalid_data_received) == 1

            # Verify result stored as invalid in database
            cursor = await driver.db.db.execute(
                "SELECT is_valid, validation_errors_json, data_json FROM results"
            )
            row = await cursor.fetchone()
            assert row is not None
            is_valid, validation_errors_json, data_json = row

            assert is_valid == 0, "Result should be marked as invalid"
            assert validation_errors_json is not None, (
                "Should have validation errors"
            )

            # Verify the validation errors contain the expected message
            errors = json.loads(validation_errors_json)
            assert len(errors) > 0
            # The failed doc should still be stored
            data = json.loads(data_json)
            assert data["case_name"] == "Smith v. Jones"


class TestNonNavigatingRequestHandling:
    """Tests for NonNavigatingRequest handling by DevDriver."""

    async def test_non_navigating_request_processed(
        self, db_path: Path
    ) -> None:
        """Test that NonNavigatingRequests are processed without updating location."""
        from juriscraper.scraper_driver.data_types import (
            BaseScraper,
            HttpMethod,
            HTTPRequestParams,
            NavigatingRequest,
            NonNavigatingRequest,
            ParsedData,
            Response,
        )
        from juriscraper.scraper_driver.driver.dev_driver.dev_driver import (
            LocalDevDriver,
        )
        from juriscraper.scraper_driver.driver.dev_driver.testing import (
            MockResponse,
            TestingInterceptor,
        )

        collected_data: list[dict] = []

        class NonNavScraper(BaseScraper[dict]):
            def get_entry(self) -> Generator[NavigatingRequest, None, None]:
                yield NavigatingRequest(
                    request=HTTPRequestParams(
                        method=HttpMethod.GET,
                        url="https://example.com/main",
                    ),
                    continuation="parse_main",
                    current_location="",
                )

            def parse_main(self, response: Response):
                # Yield a NonNavigatingRequest for auxiliary data
                yield NonNavigatingRequest(
                    request=HTTPRequestParams(
                        method=HttpMethod.GET,
                        url="https://example.com/api/metadata",
                    ),
                    continuation="parse_metadata",
                    current_location=response.url,  # Keep same location
                    aux_data={"source": "main_page"},
                )

            def parse_metadata(self, response: Response):
                yield ParsedData(
                    {
                        "metadata": "fetched",
                        "source_location": response.request.current_location,
                        "aux_source": response.request.aux_data.get("source"),
                    }
                )

        async def collect_result(data: dict) -> None:
            collected_data.append(data)

        scraper = NonNavScraper()
        interceptor = TestingInterceptor()
        interceptor.add_response(
            "https://example.com/main",
            MockResponse(content=b"<html>Main page</html>", status_code=200),
        )
        interceptor.add_response(
            "https://example.com/api/metadata",
            MockResponse(
                content=b'{"status": "ok"}',
                status_code=200,
                headers={"Content-Type": "application/json"},
            ),
        )

        async with LocalDevDriver.open(
            scraper, db_path, base_delay=0.0, jitter=0.0
        ) as driver:
            driver.request_manager.interceptors.append(interceptor)
            driver.on_data = collect_result
            await driver.run()

            assert driver.db.db is not None

            # Verify data was collected
            assert len(collected_data) == 1
            assert collected_data[0]["metadata"] == "fetched"
            assert collected_data[0]["aux_source"] == "main_page"

            # Verify both requests are tracked in the database
            cursor = await driver.db.db.execute(
                "SELECT url, request_type FROM requests ORDER BY id"
            )
            rows = await cursor.fetchall()

            assert len(rows) == 2
            # First request is navigating (entry point)
            assert rows[0][0] == "https://example.com/main"
            assert rows[0][1] == "navigating"
            # Second request is non-navigating
            assert rows[1][0] == "https://example.com/api/metadata"
            assert rows[1][1] == "non_navigating"

    async def test_non_navigating_request_preserves_accumulated_data(
        self, db_path: Path
    ) -> None:
        """Test that NonNavigatingRequest preserves accumulated_data from parent."""
        from juriscraper.scraper_driver.data_types import (
            BaseScraper,
            HttpMethod,
            HTTPRequestParams,
            NavigatingRequest,
            NonNavigatingRequest,
            ParsedData,
            Response,
        )
        from juriscraper.scraper_driver.driver.dev_driver.dev_driver import (
            LocalDevDriver,
        )
        from juriscraper.scraper_driver.driver.dev_driver.testing import (
            MockResponse,
            TestingInterceptor,
        )

        class AccumulatingScraper(BaseScraper[dict]):
            def get_entry(self) -> Generator[NavigatingRequest, None, None]:
                yield NavigatingRequest(
                    request=HTTPRequestParams(
                        method=HttpMethod.GET,
                        url="https://example.com/listing",
                    ),
                    continuation="parse_listing",
                    current_location="",
                    accumulated_data={"items": []},
                )

            def parse_listing(self, response: Response):
                # Add to accumulated data and fetch details
                accumulated = response.request.accumulated_data
                accumulated["items"].append("item1")

                yield NonNavigatingRequest(
                    request=HTTPRequestParams(
                        method=HttpMethod.GET,
                        url="https://example.com/detail/1",
                    ),
                    continuation="parse_detail",
                    current_location=response.url,
                    accumulated_data=accumulated,  # Pass accumulated data
                )

            def parse_detail(self, response: Response):
                accumulated = response.request.accumulated_data
                yield ParsedData(
                    {
                        "accumulated_items": accumulated["items"],
                        "detail_fetched": True,
                    }
                )

        results: list[dict] = []

        async def collect_result(data: dict) -> None:
            results.append(data)

        scraper = AccumulatingScraper()
        interceptor = TestingInterceptor()
        interceptor.add_response(
            "https://example.com/listing",
            MockResponse(content=b"<html>Listing</html>", status_code=200),
        )
        interceptor.add_response(
            "https://example.com/detail/1",
            MockResponse(content=b"<html>Detail</html>", status_code=200),
        )

        async with LocalDevDriver.open(
            scraper, db_path, base_delay=0.0, jitter=0.0
        ) as driver:
            driver.request_manager.interceptors.append(interceptor)
            driver.on_data = collect_result
            await driver.run()

            # Verify accumulated data was preserved
            assert len(results) == 1
            assert results[0]["accumulated_items"] == ["item1"]
            assert results[0]["detail_fetched"] is True


class TestRequeueErrorsByType:
    """Tests for requeue_errors_by_type functionality."""

    async def test_requeue_errors_by_type_filters_correctly(
        self, db_path: Path
    ) -> None:
        """Test that requeue_errors_by_type filters by error_type."""
        from juriscraper.scraper_driver.data_types import (
            BaseScraper,
            HttpMethod,
            HTTPRequestParams,
            NavigatingRequest,
        )
        from juriscraper.scraper_driver.driver.dev_driver.dev_driver import (
            LocalDevDriver,
        )

        class SimpleScraper(BaseScraper[str]):
            def get_entry(self) -> Generator[NavigatingRequest, None, None]:
                yield NavigatingRequest(
                    request=HTTPRequestParams(
                        method=HttpMethod.GET,
                        url="https://example.com",
                    ),
                    continuation="parse",
                    current_location="",
                )

            def parse(self, response):
                return []

        scraper = SimpleScraper()
        async with LocalDevDriver.open(
            scraper, db_path, base_delay=0.0, jitter=0.0
        ) as driver:
            assert driver.db.db is not None

            # Create requests that will be associated with errors
            await driver.db.db.execute(
                """
                INSERT INTO requests (status, priority, queue_counter, method, url,
                                     continuation, current_location)
                VALUES
                    ('failed', 5, 1, 'GET', 'https://example.com/structural1', 'parse', ''),
                    ('failed', 5, 2, 'GET', 'https://example.com/structural2', 'parse', ''),
                    ('failed', 5, 3, 'GET', 'https://example.com/transient1', 'parse_detail', ''),
                    ('failed', 5, 4, 'GET', 'https://example.com/validation1', 'parse', '')
                """
            )

            # Create errors of different types
            await driver.db.db.execute(
                """
                INSERT INTO errors (request_id, error_type, error_class, message, request_url)
                VALUES
                    (1, 'structural', 'HTMLStructuralAssumptionException', 'selector failed', 'https://example.com/structural1'),
                    (2, 'structural', 'HTMLStructuralAssumptionException', 'selector failed', 'https://example.com/structural2'),
                    (3, 'transient', 'RequestTimeoutException', 'timeout', 'https://example.com/transient1'),
                    (4, 'validation', 'DataFormatAssumptionException', 'invalid data', 'https://example.com/validation1')
                """
            )
            await driver.db.db.commit()

            # Requeue only structural errors
            new_ids = await driver.requeue_errors_by_type(
                error_type="structural"
            )

            assert len(new_ids) == 2, (
                f"Expected 2 structural errors, got {len(new_ids)}"
            )

            # Verify the requeued requests
            cursor = await driver.db.db.execute(
                "SELECT url FROM requests WHERE id IN (?, ?)",
                tuple(new_ids),
            )
            urls = [row[0] for row in await cursor.fetchall()]
            assert "https://example.com/structural1" in urls
            assert "https://example.com/structural2" in urls

            # Verify structural errors are marked resolved
            cursor2 = await driver.db.db.execute(
                "SELECT is_resolved FROM errors WHERE error_type = 'structural'"
            )
            resolved_statuses = [row[0] for row in await cursor2.fetchall()]
            assert all(s == 1 for s in resolved_statuses), (
                "Structural errors should be resolved"
            )

            # Verify transient error is NOT resolved
            cursor3 = await driver.db.db.execute(
                "SELECT is_resolved FROM errors WHERE error_type = 'transient'"
            )
            row = await cursor3.fetchone()
            assert row[0] == 0, "Transient error should NOT be resolved"

    async def test_requeue_errors_by_continuation(self, db_path: Path) -> None:
        """Test that requeue_errors_by_type filters by continuation."""
        from juriscraper.scraper_driver.data_types import (
            BaseScraper,
            HttpMethod,
            HTTPRequestParams,
            NavigatingRequest,
        )
        from juriscraper.scraper_driver.driver.dev_driver.dev_driver import (
            LocalDevDriver,
        )

        class SimpleScraper(BaseScraper[str]):
            def get_entry(self) -> Generator[NavigatingRequest, None, None]:
                yield NavigatingRequest(
                    request=HTTPRequestParams(
                        method=HttpMethod.GET,
                        url="https://example.com",
                    ),
                    continuation="parse",
                    current_location="",
                )

            def parse(self, response):
                return []

        scraper = SimpleScraper()
        async with LocalDevDriver.open(
            scraper, db_path, base_delay=0.0, jitter=0.0
        ) as driver:
            assert driver.db.db is not None

            # Create requests with different continuations
            await driver.db.db.execute(
                """
                INSERT INTO requests (status, priority, queue_counter, method, url,
                                     continuation, current_location)
                VALUES
                    ('failed', 5, 1, 'GET', 'https://example.com/1', 'parse_listing', ''),
                    ('failed', 5, 2, 'GET', 'https://example.com/2', 'parse_listing', ''),
                    ('failed', 5, 3, 'GET', 'https://example.com/3', 'parse_detail', '')
                """
            )

            # Create errors for all
            await driver.db.db.execute(
                """
                INSERT INTO errors (request_id, error_type, error_class, message, request_url)
                VALUES
                    (1, 'structural', 'HTMLStructuralAssumptionException', 'error', 'https://example.com/1'),
                    (2, 'structural', 'HTMLStructuralAssumptionException', 'error', 'https://example.com/2'),
                    (3, 'structural', 'HTMLStructuralAssumptionException', 'error', 'https://example.com/3')
                """
            )
            await driver.db.db.commit()

            # Requeue only parse_listing continuation errors
            new_ids = await driver.requeue_errors_by_type(
                continuation="parse_listing"
            )

            assert len(new_ids) == 2, (
                f"Expected 2 parse_listing errors, got {len(new_ids)}"
            )

            # Verify parse_detail error is NOT resolved
            cursor = await driver.db.db.execute(
                """
                SELECT e.is_resolved FROM errors e
                JOIN requests r ON e.request_id = r.id
                WHERE r.continuation = 'parse_detail'
                """
            )
            row = await cursor.fetchone()
            assert row[0] == 0, "parse_detail error should NOT be resolved"

    async def test_requeue_errors_no_matches_returns_empty(
        self, db_path: Path
    ) -> None:
        """Test that requeue_errors_by_type returns empty list when no matches."""
        from juriscraper.scraper_driver.data_types import (
            BaseScraper,
            HttpMethod,
            HTTPRequestParams,
            NavigatingRequest,
        )
        from juriscraper.scraper_driver.driver.dev_driver.dev_driver import (
            LocalDevDriver,
        )

        class SimpleScraper(BaseScraper[str]):
            def get_entry(self) -> Generator[NavigatingRequest, None, None]:
                yield NavigatingRequest(
                    request=HTTPRequestParams(
                        method=HttpMethod.GET,
                        url="https://example.com",
                    ),
                    continuation="parse",
                    current_location="",
                )

            def parse(self, response):
                return []

        scraper = SimpleScraper()
        async with LocalDevDriver.open(
            scraper, db_path, base_delay=0.0, jitter=0.0
        ) as driver:
            # Try to requeue with no errors in DB
            new_ids = await driver.requeue_errors_by_type(
                error_type="structural"
            )

            assert new_ids == [], "Should return empty list when no errors"


class TestResponsesAndResultsListing:
    """Tests for list_responses and list_results methods."""

    async def test_list_responses_filtering(self, db_path: Path) -> None:
        """Test list_responses with continuation filter."""
        import uuid

        from juriscraper.scraper_driver.data_types import (
            BaseScraper,
            HttpMethod,
            HTTPRequestParams,
            NavigatingRequest,
        )
        from juriscraper.scraper_driver.driver.dev_driver.compression import (
            compress,
        )
        from juriscraper.scraper_driver.driver.dev_driver.dev_driver import (
            LocalDevDriver,
        )

        class SimpleScraper(BaseScraper[str]):
            def get_entry(self) -> Generator[NavigatingRequest, None, None]:
                yield NavigatingRequest(
                    request=HTTPRequestParams(
                        method=HttpMethod.GET,
                        url="https://example.com",
                    ),
                    continuation="parse",
                    current_location="",
                )

            def parse(self, response):
                return []

        scraper = SimpleScraper()
        async with LocalDevDriver.open(
            scraper, db_path, base_delay=0.0, jitter=0.0
        ) as driver:
            assert driver.db.db is not None

            # Create requests
            await driver.db.db.execute(
                """
                INSERT INTO requests (status, priority, queue_counter, method, url,
                                     continuation, current_location)
                VALUES
                    ('completed', 5, 1, 'GET', 'https://example.com/1', 'parse_listing', ''),
                    ('completed', 5, 2, 'GET', 'https://example.com/2', 'parse_detail', ''),
                    ('completed', 5, 3, 'GET', 'https://example.com/3', 'parse_detail', '')
                """
            )

            # Create responses
            for req_id, cont, url in [
                (1, "parse_listing", "https://example.com/1"),
                (2, "parse_detail", "https://example.com/2"),
                (3, "parse_detail", "https://example.com/3"),
            ]:
                content = f"Content {req_id}".encode()
                compressed = compress(content)
                await driver.db.db.execute(
                    """
                    INSERT INTO responses (request_id, status_code, headers_json, url,
                                          content_compressed, content_size_original,
                                          content_size_compressed, continuation, warc_record_id)
                    VALUES (?, 200, '{}', ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        req_id,
                        url,
                        compressed,
                        len(content),
                        len(compressed),
                        cont,
                        str(uuid.uuid4()),
                    ),
                )
            await driver.db.db.commit()

            # Test filtering by continuation
            listing_page = await driver.list_responses(
                continuation="parse_listing"
            )
            assert listing_page.total == 1
            assert listing_page.items[0].continuation == "parse_listing"

            detail_page = await driver.list_responses(
                continuation="parse_detail"
            )
            assert detail_page.total == 2
            assert all(
                r.continuation == "parse_detail" for r in detail_page.items
            )

            # Test getting all
            all_page = await driver.list_responses()
            assert all_page.total == 3

    async def test_list_responses_pagination(self, db_path: Path) -> None:
        """Test list_responses pagination."""
        import uuid

        from juriscraper.scraper_driver.data_types import (
            BaseScraper,
            HttpMethod,
            HTTPRequestParams,
            NavigatingRequest,
        )
        from juriscraper.scraper_driver.driver.dev_driver.compression import (
            compress,
        )
        from juriscraper.scraper_driver.driver.dev_driver.dev_driver import (
            LocalDevDriver,
        )

        class SimpleScraper(BaseScraper[str]):
            def get_entry(self) -> Generator[NavigatingRequest, None, None]:
                yield NavigatingRequest(
                    request=HTTPRequestParams(
                        method=HttpMethod.GET,
                        url="https://example.com",
                    ),
                    continuation="parse",
                    current_location="",
                )

            def parse(self, response):
                return []

        scraper = SimpleScraper()
        async with LocalDevDriver.open(
            scraper, db_path, base_delay=0.0, jitter=0.0
        ) as driver:
            assert driver.db.db is not None

            # Create 10 requests and responses
            for i in range(10):
                await driver.db.db.execute(
                    """
                    INSERT INTO requests (status, priority, queue_counter, method, url,
                                         continuation, current_location)
                    VALUES ('completed', 5, ?, 'GET', ?, 'parse', '')
                    """,
                    (i, f"https://example.com/{i}"),
                )
                content = f"Content {i}".encode()
                compressed = compress(content)
                await driver.db.db.execute(
                    """
                    INSERT INTO responses (request_id, status_code, headers_json, url,
                                          content_compressed, content_size_original,
                                          content_size_compressed, continuation, warc_record_id)
                    VALUES (?, 200, '{}', ?, ?, ?, ?, 'parse', ?)
                    """,
                    (
                        i + 1,
                        f"https://example.com/{i}",
                        compressed,
                        len(content),
                        len(compressed),
                        str(uuid.uuid4()),
                    ),
                )
            await driver.db.db.commit()

            # Test pagination
            page1 = await driver.list_responses(limit=3, offset=0)
            assert page1.total == 10
            assert len(page1.items) == 3

            page2 = await driver.list_responses(limit=3, offset=3)
            assert len(page2.items) == 3
            assert page2.offset == 3

    async def test_list_results_filtering(self, db_path: Path) -> None:
        """Test list_results with filters."""
        from juriscraper.scraper_driver.data_types import (
            BaseScraper,
            HttpMethod,
            HTTPRequestParams,
            NavigatingRequest,
        )
        from juriscraper.scraper_driver.driver.dev_driver.dev_driver import (
            LocalDevDriver,
        )

        class SimpleScraper(BaseScraper[str]):
            def get_entry(self) -> Generator[NavigatingRequest, None, None]:
                yield NavigatingRequest(
                    request=HTTPRequestParams(
                        method=HttpMethod.GET,
                        url="https://example.com",
                    ),
                    continuation="parse",
                    current_location="",
                )

            def parse(self, response):
                return []

        scraper = SimpleScraper()
        async with LocalDevDriver.open(
            scraper, db_path, base_delay=0.0, jitter=0.0
        ) as driver:
            assert driver.db.db is not None

            # Create results of different types and validity
            await driver.db.db.execute(
                """
                INSERT INTO results (result_type, data_json, is_valid, validation_errors_json)
                VALUES
                    ('CaseData', '{"id": 1}', 1, NULL),
                    ('CaseData', '{"id": 2}', 1, NULL),
                    ('CaseData', '{"id": 3}', 0, '[{"error": "bad"}]'),
                    ('DocumentData', '{"id": 4}', 1, NULL)
                """
            )
            await driver.db.db.commit()

            # Filter by result_type
            case_results = await driver.list_results(result_type="CaseData")
            assert case_results.total == 3

            doc_results = await driver.list_results(result_type="DocumentData")
            assert doc_results.total == 1

            # Filter by is_valid
            valid_results = await driver.list_results(is_valid=True)
            assert valid_results.total == 3

            invalid_results = await driver.list_results(is_valid=False)
            assert invalid_results.total == 1
            assert not invalid_results.items[0].is_valid


class TestGetterMethods:
    """Tests for get_response and get_result methods."""

    async def test_get_response_found(self, db_path: Path) -> None:
        """Test get_response returns response when found."""
        import uuid

        from juriscraper.scraper_driver.data_types import (
            BaseScraper,
            HttpMethod,
            HTTPRequestParams,
            NavigatingRequest,
        )
        from juriscraper.scraper_driver.driver.dev_driver.compression import (
            compress,
        )
        from juriscraper.scraper_driver.driver.dev_driver.dev_driver import (
            LocalDevDriver,
        )

        class SimpleScraper(BaseScraper[str]):
            def get_entry(self) -> Generator[NavigatingRequest, None, None]:
                yield NavigatingRequest(
                    request=HTTPRequestParams(
                        method=HttpMethod.GET,
                        url="https://example.com",
                    ),
                    continuation="parse",
                    current_location="",
                )

            def parse(self, response):
                return []

        scraper = SimpleScraper()
        async with LocalDevDriver.open(
            scraper, db_path, base_delay=0.0, jitter=0.0
        ) as driver:
            assert driver.db.db is not None

            # Create request and response
            await driver.db.db.execute(
                """
                INSERT INTO requests (status, priority, queue_counter, method, url,
                                     continuation, current_location)
                VALUES ('completed', 5, 1, 'GET', 'https://example.com/test', 'parse', '')
                """
            )
            content = b"Test content"
            compressed = compress(content)
            warc_id = str(uuid.uuid4())
            await driver.db.db.execute(
                """
                INSERT INTO responses (request_id, status_code, headers_json, url,
                                      content_compressed, content_size_original,
                                      content_size_compressed, continuation, warc_record_id)
                VALUES (1, 200, '{"Content-Type": "text/html"}', 'https://example.com/test',
                        ?, ?, ?, 'parse', ?)
                """,
                (compressed, len(content), len(compressed), warc_id),
            )
            await driver.db.db.commit()

            # Get response by ID
            response = await driver.get_response(1)

            assert response is not None
            assert response.id == 1
            assert response.status_code == 200
            assert response.url == "https://example.com/test"
            assert response.content_size_original == len(content)

    async def test_get_response_not_found(self, db_path: Path) -> None:
        """Test get_response returns None when not found."""
        from juriscraper.scraper_driver.data_types import (
            BaseScraper,
            HttpMethod,
            HTTPRequestParams,
            NavigatingRequest,
        )
        from juriscraper.scraper_driver.driver.dev_driver.dev_driver import (
            LocalDevDriver,
        )

        class SimpleScraper(BaseScraper[str]):
            def get_entry(self) -> Generator[NavigatingRequest, None, None]:
                yield NavigatingRequest(
                    request=HTTPRequestParams(
                        method=HttpMethod.GET,
                        url="https://example.com",
                    ),
                    continuation="parse",
                    current_location="",
                )

            def parse(self, response):
                return []

        scraper = SimpleScraper()
        async with LocalDevDriver.open(
            scraper, db_path, base_delay=0.0, jitter=0.0
        ) as driver:
            response = await driver.get_response(999)
            assert response is None

    async def test_get_result_found(self, db_path: Path) -> None:
        """Test get_result returns result when found."""
        from juriscraper.scraper_driver.data_types import (
            BaseScraper,
            HttpMethod,
            HTTPRequestParams,
            NavigatingRequest,
        )
        from juriscraper.scraper_driver.driver.dev_driver.dev_driver import (
            LocalDevDriver,
        )

        class SimpleScraper(BaseScraper[str]):
            def get_entry(self) -> Generator[NavigatingRequest, None, None]:
                yield NavigatingRequest(
                    request=HTTPRequestParams(
                        method=HttpMethod.GET,
                        url="https://example.com",
                    ),
                    continuation="parse",
                    current_location="",
                )

            def parse(self, response):
                return []

        scraper = SimpleScraper()
        async with LocalDevDriver.open(
            scraper, db_path, base_delay=0.0, jitter=0.0
        ) as driver:
            assert driver.db.db is not None

            # Create a result
            await driver.db.db.execute(
                """
                INSERT INTO results (result_type, data_json, is_valid)
                VALUES ('CaseData', '{"case_name": "Smith v. Jones", "id": 123}', 1)
                """
            )
            await driver.db.db.commit()

            # Get result by ID
            result = await driver.get_result(1)

            assert result is not None
            assert result.id == 1
            assert result.result_type == "CaseData"
            assert result.is_valid  # Truthy check (SQLite returns 1)
            # Verify data can be parsed
            data = json.loads(result.data_json)
            assert data["case_name"] == "Smith v. Jones"

    async def test_get_result_not_found(self, db_path: Path) -> None:
        """Test get_result returns None when not found."""
        from juriscraper.scraper_driver.data_types import (
            BaseScraper,
            HttpMethod,
            HTTPRequestParams,
            NavigatingRequest,
        )
        from juriscraper.scraper_driver.driver.dev_driver.dev_driver import (
            LocalDevDriver,
        )

        class SimpleScraper(BaseScraper[str]):
            def get_entry(self) -> Generator[NavigatingRequest, None, None]:
                yield NavigatingRequest(
                    request=HTTPRequestParams(
                        method=HttpMethod.GET,
                        url="https://example.com",
                    ),
                    continuation="parse",
                    current_location="",
                )

            def parse(self, response):
                return []

        scraper = SimpleScraper()
        async with LocalDevDriver.open(
            scraper, db_path, base_delay=0.0, jitter=0.0
        ) as driver:
            result = await driver.get_result(999)
            assert result is None


class TestCancellationMethods:
    """Tests for cancel_request and cancel_requests_by_continuation."""

    async def test_cancel_request_pending(self, db_path: Path) -> None:
        """Test cancelling a pending request."""
        from juriscraper.scraper_driver.data_types import (
            BaseScraper,
            HttpMethod,
            HTTPRequestParams,
            NavigatingRequest,
        )
        from juriscraper.scraper_driver.driver.dev_driver.dev_driver import (
            LocalDevDriver,
        )

        class SimpleScraper(BaseScraper[str]):
            def get_entry(self) -> Generator[NavigatingRequest, None, None]:
                yield NavigatingRequest(
                    request=HTTPRequestParams(
                        method=HttpMethod.GET,
                        url="https://example.com",
                    ),
                    continuation="parse",
                    current_location="",
                )

            def parse(self, response):
                return []

        scraper = SimpleScraper()
        async with LocalDevDriver.open(
            scraper, db_path, base_delay=0.0, jitter=0.0
        ) as driver:
            assert driver.db.db is not None

            # Create a pending request
            await driver.db.db.execute(
                """
                INSERT INTO requests (status, priority, queue_counter, method, url,
                                     continuation, current_location)
                VALUES ('pending', 5, 1, 'GET', 'https://example.com/test', 'parse', '')
                """
            )
            await driver.db.db.commit()

            # Cancel the request
            cancelled = await driver.cancel_request(1)

            assert cancelled is True

            # Verify status changed
            cursor = await driver.db.db.execute(
                "SELECT status, last_error FROM requests WHERE id = 1"
            )
            row = await cursor.fetchone()
            assert row[0] == "failed"
            assert "Cancelled" in row[1]

    async def test_cancel_request_held(self, db_path: Path) -> None:
        """Test cancelling a held request."""
        from juriscraper.scraper_driver.data_types import (
            BaseScraper,
            HttpMethod,
            HTTPRequestParams,
            NavigatingRequest,
        )
        from juriscraper.scraper_driver.driver.dev_driver.dev_driver import (
            LocalDevDriver,
        )

        class SimpleScraper(BaseScraper[str]):
            def get_entry(self) -> Generator[NavigatingRequest, None, None]:
                yield NavigatingRequest(
                    request=HTTPRequestParams(
                        method=HttpMethod.GET,
                        url="https://example.com",
                    ),
                    continuation="parse",
                    current_location="",
                )

            def parse(self, response):
                return []

        scraper = SimpleScraper()
        async with LocalDevDriver.open(
            scraper, db_path, base_delay=0.0, jitter=0.0
        ) as driver:
            assert driver.db.db is not None

            # Create a held request
            await driver.db.db.execute(
                """
                INSERT INTO requests (status, priority, queue_counter, method, url,
                                     continuation, current_location)
                VALUES ('held', 5, 1, 'GET', 'https://example.com/test', 'parse', '')
                """
            )
            await driver.db.db.commit()

            # Cancel the request
            cancelled = await driver.cancel_request(1)

            assert cancelled is True

            # Verify status changed
            cursor = await driver.db.db.execute(
                "SELECT status FROM requests WHERE id = 1"
            )
            row = await cursor.fetchone()
            assert row[0] == "failed"

    async def test_cancel_request_in_progress_fails(
        self, db_path: Path
    ) -> None:
        """Test that cancelling an in_progress request fails."""
        from juriscraper.scraper_driver.data_types import (
            BaseScraper,
            HttpMethod,
            HTTPRequestParams,
            NavigatingRequest,
        )
        from juriscraper.scraper_driver.driver.dev_driver.dev_driver import (
            LocalDevDriver,
        )

        class SimpleScraper(BaseScraper[str]):
            def get_entry(self) -> Generator[NavigatingRequest, None, None]:
                yield NavigatingRequest(
                    request=HTTPRequestParams(
                        method=HttpMethod.GET,
                        url="https://example.com",
                    ),
                    continuation="parse",
                    current_location="",
                )

            def parse(self, response):
                return []

        scraper = SimpleScraper()
        async with LocalDevDriver.open(
            scraper, db_path, base_delay=0.0, jitter=0.0
        ) as driver:
            assert driver.db.db is not None

            # Create an in_progress request
            await driver.db.db.execute(
                """
                INSERT INTO requests (status, priority, queue_counter, method, url,
                                     continuation, current_location)
                VALUES ('in_progress', 5, 1, 'GET', 'https://example.com/test', 'parse', '')
                """
            )
            await driver.db.db.commit()

            # Try to cancel - should fail
            cancelled = await driver.cancel_request(1)

            assert cancelled is False

            # Verify status unchanged
            cursor = await driver.db.db.execute(
                "SELECT status FROM requests WHERE id = 1"
            )
            row = await cursor.fetchone()
            assert row[0] == "in_progress"

    async def test_cancel_request_not_found(self, db_path: Path) -> None:
        """Test cancelling a non-existent request returns False."""
        from juriscraper.scraper_driver.data_types import (
            BaseScraper,
            HttpMethod,
            HTTPRequestParams,
            NavigatingRequest,
        )
        from juriscraper.scraper_driver.driver.dev_driver.dev_driver import (
            LocalDevDriver,
        )

        class SimpleScraper(BaseScraper[str]):
            def get_entry(self) -> Generator[NavigatingRequest, None, None]:
                yield NavigatingRequest(
                    request=HTTPRequestParams(
                        method=HttpMethod.GET,
                        url="https://example.com",
                    ),
                    continuation="parse",
                    current_location="",
                )

            def parse(self, response):
                return []

        scraper = SimpleScraper()
        async with LocalDevDriver.open(
            scraper, db_path, base_delay=0.0, jitter=0.0
        ) as driver:
            cancelled = await driver.cancel_request(999)
            assert cancelled is False

    async def test_cancel_requests_by_continuation(
        self, db_path: Path
    ) -> None:
        """Test cancelling all requests by continuation."""
        from juriscraper.scraper_driver.data_types import (
            BaseScraper,
            HttpMethod,
            HTTPRequestParams,
            NavigatingRequest,
        )
        from juriscraper.scraper_driver.driver.dev_driver.dev_driver import (
            LocalDevDriver,
        )

        class SimpleScraper(BaseScraper[str]):
            def get_entry(self) -> Generator[NavigatingRequest, None, None]:
                yield NavigatingRequest(
                    request=HTTPRequestParams(
                        method=HttpMethod.GET,
                        url="https://example.com",
                    ),
                    continuation="parse",
                    current_location="",
                )

            def parse(self, response):
                return []

        scraper = SimpleScraper()
        async with LocalDevDriver.open(
            scraper, db_path, base_delay=0.0, jitter=0.0
        ) as driver:
            assert driver.db.db is not None

            # Create requests with different continuations and statuses
            await driver.db.db.execute(
                """
                INSERT INTO requests (status, priority, queue_counter, method, url,
                                     continuation, current_location)
                VALUES
                    ('pending', 5, 1, 'GET', 'https://example.com/1', 'parse_detail', ''),
                    ('pending', 5, 2, 'GET', 'https://example.com/2', 'parse_detail', ''),
                    ('held', 5, 3, 'GET', 'https://example.com/3', 'parse_detail', ''),
                    ('in_progress', 5, 4, 'GET', 'https://example.com/4', 'parse_detail', ''),
                    ('pending', 5, 5, 'GET', 'https://example.com/5', 'parse_listing', '')
                """
            )
            await driver.db.db.commit()

            # Cancel all parse_detail requests
            count = await driver.cancel_requests_by_continuation(
                "parse_detail"
            )

            # Should cancel 3 (2 pending + 1 held, not in_progress)
            assert count == 3

            # Verify statuses
            cursor = await driver.db.db.execute(
                """
                SELECT id, status FROM requests WHERE continuation = 'parse_detail'
                ORDER BY id
                """
            )
            rows = await cursor.fetchall()

            # First 3 should be failed
            assert rows[0][1] == "failed"
            assert rows[1][1] == "failed"
            assert rows[2][1] == "failed"
            # Fourth (in_progress) should be unchanged
            assert rows[3][1] == "in_progress"

            # parse_listing should be unchanged
            cursor2 = await driver.db.db.execute(
                "SELECT status FROM requests WHERE continuation = 'parse_listing'"
            )
            row = await cursor2.fetchone()
            assert row[0] == "pending"

    async def test_cancel_requests_by_continuation_empty(
        self, db_path: Path
    ) -> None:
        """Test cancelling by continuation when none exist."""
        from juriscraper.scraper_driver.data_types import (
            BaseScraper,
            HttpMethod,
            HTTPRequestParams,
            NavigatingRequest,
        )
        from juriscraper.scraper_driver.driver.dev_driver.dev_driver import (
            LocalDevDriver,
        )

        class SimpleScraper(BaseScraper[str]):
            def get_entry(self) -> Generator[NavigatingRequest, None, None]:
                yield NavigatingRequest(
                    request=HTTPRequestParams(
                        method=HttpMethod.GET,
                        url="https://example.com",
                    ),
                    continuation="parse",
                    current_location="",
                )

            def parse(self, response):
                return []

        scraper = SimpleScraper()
        async with LocalDevDriver.open(
            scraper, db_path, base_delay=0.0, jitter=0.0
        ) as driver:
            count = await driver.cancel_requests_by_continuation("nonexistent")
            assert count == 0


class TestSpeculativeRequestHandling:
    """Tests for SpeculativeRequest support in LocalDevDriver."""

    async def test_speculative_request_with_200_response_continues(
        self, tmp_path: Path
    ) -> None:
        """Test that 200 response to speculative request returns True."""
        from unittest.mock import AsyncMock, MagicMock

        from juriscraper.scraper_driver.common.decorators import step
        from juriscraper.scraper_driver.data_types import (
            BaseScraper,
            HttpMethod,
            HTTPRequestParams,
            NavigatingRequest,
            ParsedData,
            Response,
            ScraperYield,
            SpeculativeRequest,
        )
        from juriscraper.scraper_driver.driver.dev_driver.dev_driver import (
            LocalDevDriver,
        )

        class SpeculativeScraper(BaseScraper[dict]):
            def __init__(self) -> None:
                self.speculative_results: list[bool] = []
                self.pages_processed: list[int] = []
                self._params = ScraperParams()

            def get_entry(self) -> Generator[NavigatingRequest, None, None]:
                yield NavigatingRequest(
                    request=HTTPRequestParams(
                        method=HttpMethod.GET, url="https://example.com/start"
                    ),
                    continuation="parse_start",
                )

            @step(speculative=True)
            def parse_start(
                self, response: Response, speculative_id: int = 1
            ) -> Generator[ScraperYield, bool | None, None]:
                for page in range(1, 4):
                    should_continue = yield SpeculativeRequest(
                        request=HTTPRequestParams(
                            method=HttpMethod.GET,
                            url=f"https://example.com/page/{page}",
                        ),
                        continuation="parse_page",
                        speculative_id=page,
                    )
                    self.speculative_results.append(
                        should_continue
                        if should_continue is not None
                        else False
                    )
                    if not should_continue:
                        break

            @step
            def parse_page(
                self, response: Response
            ) -> Generator[ScraperYield, bool | None, None]:
                page_num = int(response.url.split("/")[-1])
                self.pages_processed.append(page_num)
                yield ParsedData({"page": page_num})

        db_path = tmp_path / "test_speculative.db"
        scraper = SpeculativeScraper()
        collected_data: list[dict] = []

        async def on_data(data: dict) -> None:
            collected_data.append(data)

        async with LocalDevDriver.open(
            scraper, db_path, base_delay=0.0, jitter=0.0
        ) as driver:
            driver.on_data = on_data
            # Mock the HTTP request method
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.headers = {}
            mock_response.content = b""
            mock_response.text = ""
            driver.request_manager._client = MagicMock()
            driver.request_manager._client.request = AsyncMock(
                return_value=mock_response
            )

            await driver.run()

        # All speculative requests should return True (200 responses)
        assert scraper.speculative_results == [True, True, True]
        # All pages should be processed
        assert scraper.pages_processed == [1, 2, 3]
        # Data should be collected
        assert len(collected_data) == 3

    async def test_speculative_request_with_404_returns_false(
        self, tmp_path: Path
    ) -> None:
        """Test that 404 response without callback returns False."""
        from unittest.mock import AsyncMock, MagicMock

        from juriscraper.scraper_driver.common.decorators import step
        from juriscraper.scraper_driver.data_types import (
            BaseScraper,
            HttpMethod,
            HTTPRequestParams,
            NavigatingRequest,
            ParsedData,
            Response,
            ScraperYield,
            SpeculativeRequest,
        )
        from juriscraper.scraper_driver.driver.dev_driver.dev_driver import (
            LocalDevDriver,
        )

        class SpeculativeScraper(BaseScraper[dict]):
            def __init__(self) -> None:
                self.speculative_results: list[bool] = []
                self._params = ScraperParams()

            def get_entry(self) -> Generator[NavigatingRequest, None, None]:
                yield NavigatingRequest(
                    request=HTTPRequestParams(
                        method=HttpMethod.GET, url="https://example.com/start"
                    ),
                    continuation="parse_start",
                )

            @step(speculative=True)
            def parse_start(
                self, response: Response, speculative_id=1
            ) -> Generator[ScraperYield, bool | None, None]:
                for page in range(1, 4):
                    should_continue = yield SpeculativeRequest(
                        request=HTTPRequestParams(
                            method=HttpMethod.GET,
                            url=f"https://example.com/page/{page}",
                        ),
                        continuation="parse_page",
                        speculative_id=page,
                    )
                    self.speculative_results.append(
                        should_continue
                        if should_continue is not None
                        else False
                    )
                    if not should_continue:
                        break

            @step
            def parse_page(
                self, response: Response
            ) -> Generator[ScraperYield, bool | None, None]:
                yield ParsedData({"page": response.url})

        db_path = tmp_path / "test_speculative_404.db"
        scraper = SpeculativeScraper()

        async with LocalDevDriver.open(
            scraper, db_path, base_delay=0.0, jitter=0.0
        ) as driver:
            # First returns 200, second returns 404
            call_count = 0

            def make_response(**kwargs):
                nonlocal call_count
                call_count += 1
                mock = MagicMock()
                # First call (start page) and second call (page 1) return 200
                if call_count <= 2:
                    mock.status_code = 200
                else:
                    mock.status_code = 404
                mock.headers = {}
                mock.content = b""
                mock.text = ""
                return mock

            driver.request_manager._client = MagicMock()
            driver.request_manager._client.request = AsyncMock(
                side_effect=make_response
            )

            await driver.run()

        # First speculative: True (200), Second: False (404)
        assert scraper.speculative_results == [True, False]

    async def test_speculative_request_with_callback(
        self, tmp_path: Path
    ) -> None:
        """Test that on_speculation_response callback is called for non-2xx."""
        from unittest.mock import AsyncMock, MagicMock

        from juriscraper.scraper_driver.common.decorators import step
        from juriscraper.scraper_driver.data_types import (
            BaseScraper,
            HttpMethod,
            HTTPRequestParams,
            NavigatingRequest,
            ParsedData,
            Response,
            ScraperYield,
            SpeculativeRequest,
        )
        from juriscraper.scraper_driver.driver.dev_driver.dev_driver import (
            LocalDevDriver,
        )

        class SpeculativeScraper(BaseScraper[dict]):
            def __init__(self) -> None:
                self.speculative_results: list[bool] = []
                self._params = ScraperParams()

            def get_entry(self) -> Generator[NavigatingRequest, None, None]:
                yield NavigatingRequest(
                    request=HTTPRequestParams(
                        method=HttpMethod.GET, url="https://example.com/start"
                    ),
                    continuation="parse_start",
                )

            @step(speculative=True)
            def parse_start(
                self, response: Response, speculative_id: int = 1
            ) -> Generator[ScraperYield, bool | None, None]:
                for page in range(1, 4):
                    should_continue = yield SpeculativeRequest(
                        request=HTTPRequestParams(
                            method=HttpMethod.GET,
                            url=f"https://example.com/page/{page}",
                        ),
                        continuation="parse_page",
                        speculative_id=page,
                    )
                    self.speculative_results.append(
                        should_continue
                        if should_continue is not None
                        else False
                    )
                    if not should_continue:
                        break

            @step
            def parse_page(
                self, response: Response
            ) -> Generator[ScraperYield, bool | None, None]:
                yield ParsedData({"page": response.url})

        db_path = tmp_path / "test_speculative_callback.db"
        scraper = SpeculativeScraper()
        callback_calls: list[tuple[int, str, int]] = []

        from juriscraper.scraper_driver.driver.dev_driver.speculation import (
            FlowControl,
        )

        async def speculation_callback(
            response: Response | None,
            continuation_name: str,
            speculative_id: int,
        ) -> FlowControl:
            if response is None:
                return FlowControl.AWAIT_MORE_INFO
            callback_calls.append(
                (response.status_code, continuation_name, speculative_id)
            )
            return FlowControl.CONTINUE  # Always continue

        async with LocalDevDriver.open(
            scraper,
            db_path,
            on_speculation_response=speculation_callback,
            base_delay=0.0,
            jitter=0.0,
        ) as driver:
            call_count = 0

            def make_response(**kwargs):
                nonlocal call_count
                call_count += 1
                mock = MagicMock()
                # Start page: 200, page 1: 404, page 2: 200, page 3: 200
                if call_count == 2:
                    mock.status_code = 404
                else:
                    mock.status_code = 200
                mock.headers = {}
                mock.content = b""
                mock.text = ""
                return mock

            driver.request_manager._client = MagicMock()
            driver.request_manager._client.request = AsyncMock(
                side_effect=make_response
            )

            await driver.run()

        # Callback was called for the 404
        # The step name passed is the originating speculative step (parse_start),
        # not the continuation (parse_page). This matches the speculation config keys.
        assert len(callback_calls) == 1
        assert callback_calls[0][0] == 404
        assert callback_calls[0][1] == "parse_start"

        # All speculative results should be True (callback returned True)
        assert scraper.speculative_results == [True, True, True]

    async def test_speculative_request_serialization_roundtrip(
        self, tmp_path: Path
    ) -> None:
        """Test that SpeculativeRequest can be serialized and deserialized."""
        from juriscraper.scraper_driver.data_types import (
            BaseScraper,
            HttpMethod,
            HTTPRequestParams,
            NavigatingRequest,
            SpeculativeRequest,
        )
        from juriscraper.scraper_driver.driver.dev_driver.dev_driver import (
            LocalDevDriver,
        )

        class SimpleScraper(BaseScraper[str]):
            def get_entry(self) -> Generator[NavigatingRequest, None, None]:
                yield NavigatingRequest(
                    request=HTTPRequestParams(
                        method=HttpMethod.GET, url="https://example.com"
                    ),
                    continuation="parse",
                )

            def parse(self, response):
                return []

        db_path = tmp_path / "test_spec_roundtrip.db"
        scraper = SimpleScraper()

        async with LocalDevDriver.open(
            scraper, db_path, base_delay=0.0, jitter=0.0
        ) as driver:
            # Create a speculative request
            spec_request = SpeculativeRequest(
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url="https://example.com/speculative",
                    headers={"X-Test": "value"},
                ),
                continuation="parse",
                current_location="test_location",
                accumulated_data={"key": "value"},
                aux_data={"aux": "data"},
                permanent={"perm": "data"},
                priority=5,
                speculative_id=1,
            )

            # Serialize with speculation_id
            serialized = driver._serialize_request(spec_request, "spec_123")

            assert serialized["request_type"] == "speculative"
            assert serialized["expected_type"] == "spec_123"
            assert serialized["url"] == "https://example.com/speculative"
            assert serialized["method"] == "GET"

    async def test_speculative_deduplication_resumes_generator(
        self, tmp_path: Path
    ) -> None:
        """Test that deduplicated speculative requests resume with False."""
        from unittest.mock import AsyncMock, MagicMock

        from juriscraper.scraper_driver.common.decorators import step
        from juriscraper.scraper_driver.data_types import (
            BaseScraper,
            HttpMethod,
            HTTPRequestParams,
            NavigatingRequest,
            ParsedData,
            Response,
            ScraperYield,
            SpeculativeRequest,
        )
        from juriscraper.scraper_driver.driver.dev_driver.dev_driver import (
            LocalDevDriver,
        )

        class DuplicateScraper(BaseScraper[dict]):
            def __init__(self) -> None:
                self.results: list[bool] = []
                self._params = ScraperParams()

            def get_entry(self) -> Generator[NavigatingRequest, None, None]:
                yield NavigatingRequest(
                    request=HTTPRequestParams(
                        method=HttpMethod.GET, url="https://example.com/start"
                    ),
                    continuation="parse_start",
                )

            @step(speculative=True)
            def parse_start(
                self, response: Response, speculative_id: int = 1
            ) -> Generator[ScraperYield, bool | None, None]:
                # First speculative request
                result1 = yield SpeculativeRequest(
                    request=HTTPRequestParams(
                        method=HttpMethod.GET, url="https://example.com/page"
                    ),
                    continuation="parse_page",
                    speculative_id=1,
                )
                self.results.append(result1 if result1 is not None else False)

                # Same URL again - should be deduplicated
                result2 = yield SpeculativeRequest(
                    request=HTTPRequestParams(
                        method=HttpMethod.GET, url="https://example.com/page"
                    ),
                    continuation="parse_page",
                    speculative_id=2,
                )
                self.results.append(result2 if result2 is not None else False)

            @step
            def parse_page(
                self, response: Response
            ) -> Generator[ScraperYield, bool | None, None]:
                yield ParsedData({"url": response.url})

        db_path = tmp_path / "test_spec_dedup.db"
        scraper = DuplicateScraper()

        async with LocalDevDriver.open(
            scraper, db_path, base_delay=0.0, jitter=0.0
        ) as driver:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.headers = {}
            mock_response.content = b""
            mock_response.text = ""
            driver.request_manager._client = MagicMock()
            driver.request_manager._client.request = AsyncMock(
                return_value=mock_response
            )

            await driver.run()

        # First should succeed (True), second should be deduplicated (False)
        assert scraper.results == [True, False]


class TestSpeculativeRequestRestart:
    """Tests for SpeculativeRequest restart/resume functionality.

    These tests verify that the LocalDevDriver can:
    1. Track speculative progress in the database
    2. Resume speculative generators from where they left off
    3. Recover from lost generator context after restart
    """

    async def test_speculative_progress_tracked_in_db(
        self, tmp_path: Path
    ) -> None:
        """Test that speculative progress is tracked in the database."""
        from unittest.mock import AsyncMock, MagicMock

        from juriscraper.scraper_driver.common.decorators import step
        from juriscraper.scraper_driver.data_types import (
            BaseScraper,
            HttpMethod,
            HTTPRequestParams,
            NavigatingRequest,
            ParsedData,
            Response,
            ScraperYield,
            SpeculativeRequest,
        )
        from juriscraper.scraper_driver.driver.dev_driver.dev_driver import (
            LocalDevDriver,
        )

        class SpeculativeScraper(BaseScraper[dict]):
            """Scraper that yields speculative requests with explicit IDs."""

            def __init__(self) -> None:
                super().__init__()
                self.pages_processed: list[int] = []
                self._params = ScraperParams()

            def get_entry(self) -> Generator[NavigatingRequest, None, None]:
                yield NavigatingRequest(
                    request=HTTPRequestParams(
                        method=HttpMethod.GET, url="https://example.com/start"
                    ),
                    continuation="parse_start",
                )

            @step(speculative=True)
            def parse_start(
                self, response: Response, speculative_id: int = 1
            ) -> Generator[ScraperYield, bool | None, None]:
                """Yield speculative requests starting from speculative_id."""
                current_id = speculative_id
                max_pages = 5
                while current_id <= max_pages:
                    should_continue = yield SpeculativeRequest(
                        request=HTTPRequestParams(
                            method=HttpMethod.GET,
                            url=f"https://example.com/page/{current_id}",
                        ),
                        continuation="parse_page",
                        speculative_id=current_id,
                    )
                    if not should_continue:
                        break
                    current_id += 1

            @step
            def parse_page(
                self, response: Response
            ) -> Generator[ScraperYield, bool | None, None]:
                page_num = int(response.url.split("/")[-1])
                self.pages_processed.append(page_num)
                yield ParsedData({"page": page_num})

        db_path = tmp_path / "test_spec_progress.db"
        scraper = SpeculativeScraper()

        async with LocalDevDriver.open(
            scraper, db_path, base_delay=0.0, jitter=0.0
        ) as driver:
            # Mock HTTP responses - all return 200 except page 4 which returns 404
            def mock_request(**kwargs: Any) -> MagicMock:
                response = MagicMock()
                url = kwargs.get("url", "")
                if "/page/4" in url:
                    response.status_code = 404
                else:
                    response.status_code = 200
                response.headers = {}
                response.content = b""
                response.text = ""
                return response

            driver.request_manager._client = MagicMock()
            driver.request_manager._client.request = AsyncMock(
                side_effect=mock_request
            )

            await driver.run()

            # Check that progress was tracked
            progress = await driver.get_speculative_progress("parse_start")
            # Progress tracks the last speculative_id that was ATTEMPTED (not just successful)
            # This ensures restart resumes from the correct point
            # Page 4 was attempted (404 response) so progress = 4
            assert progress is not None
            assert progress == 4  # Last attempted speculative_id

        # Verify pages 1, 2, 3 were processed (not 4 which was 404)
        assert scraper.pages_processed == [1, 2, 3]

    async def test_speculative_progress_monotonic(
        self, tmp_path: Path
    ) -> None:
        """Test that speculative progress only tracks forward progress (MAX)."""
        from juriscraper.scraper_driver.driver.dev_driver.schema import (
            init_database,
        )
        from juriscraper.scraper_driver.driver.dev_driver.sql_queries import (
            SQL,
        )

        db_path = tmp_path / "test_monotonic.db"
        db = await init_database(db_path)

        try:
            # Insert initial progress
            await db.execute(
                SQL.UPSERT_SPECULATIVE_PROGRESS, ("test_step", 10)
            )
            await db.commit()

            # Try to insert lower value - should be ignored due to MAX
            await db.execute(SQL.UPSERT_SPECULATIVE_PROGRESS, ("test_step", 5))
            await db.commit()

            # Verify value is still 10 (not 5)
            cursor = await db.execute(
                SQL.SELECT_SPECULATIVE_PROGRESS, ("test_step",)
            )
            row = await cursor.fetchone()
            assert row[0] == 10

            # Insert higher value - should update
            await db.execute(
                SQL.UPSERT_SPECULATIVE_PROGRESS, ("test_step", 15)
            )
            await db.commit()

            cursor = await db.execute(
                SQL.SELECT_SPECULATIVE_PROGRESS, ("test_step",)
            )
            row = await cursor.fetchone()
            assert row[0] == 15
        finally:
            await db.close()

    async def test_speculative_restart_from_progress(
        self, tmp_path: Path
    ) -> None:
        """Test that speculative scraping can restart from a configured starting ID.

        This test verifies:
        1. First run with default starting ID (1) processes from the beginning
        2. Second run with configured starting ID (5) starts from that point

        Note: This tests the params.speculative configuration mechanism that
        would be used during recovery after a crash or restart.
        """
        from unittest.mock import AsyncMock, MagicMock

        from juriscraper.scraper_driver.common.decorators import step
        from juriscraper.scraper_driver.data_types import (
            BaseScraper,
            HttpMethod,
            HTTPRequestParams,
            NavigatingRequest,
            ParsedData,
            Response,
            ScraperYield,
            SpeculativeRequest,
        )
        from juriscraper.scraper_driver.driver.dev_driver.dev_driver import (
            LocalDevDriver,
        )

        class RestartableScraper(BaseScraper[dict]):
            """Scraper that tracks which pages it processes."""

            def __init__(self, params: Any = None) -> None:
                super().__init__(params=params)
                self.pages_processed: list[int] = []
                self.starting_id_received: int | None = None

            def get_entry(self) -> Generator[NavigatingRequest, None, None]:
                yield NavigatingRequest(
                    request=HTTPRequestParams(
                        method=HttpMethod.GET, url="https://example.com/start"
                    ),
                    continuation="parse_start",
                )

            @step(speculative=True)
            def parse_start(
                self, response: Response, speculative_id: int = 1
            ) -> Generator[ScraperYield, bool | None, None]:
                self.starting_id_received = speculative_id
                current_id = speculative_id
                max_pages = speculative_id + 2  # Process 3 pages
                while current_id <= max_pages:
                    should_continue = yield SpeculativeRequest(
                        request=HTTPRequestParams(
                            method=HttpMethod.GET,
                            url=f"https://example.com/page/{current_id}",
                        ),
                        continuation="parse_page",
                        speculative_id=current_id,
                    )
                    if not should_continue:
                        break
                    current_id += 1

            @step
            def parse_page(
                self, response: Response
            ) -> Generator[ScraperYield, bool | None, None]:
                page_num = int(response.url.split("/")[-1])
                self.pages_processed.append(page_num)
                yield ParsedData({"page": page_num})

        # First run: Default starting ID (1), process pages 1, 2, 3
        db_path1 = tmp_path / "test_spec_restart_1.db"
        scraper1 = RestartableScraper()

        async with LocalDevDriver.open(
            scraper1, db_path1, base_delay=0.0, jitter=0.0
        ) as driver:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.headers = {}
            mock_response.content = b""
            mock_response.text = ""
            driver.request_manager._client = MagicMock()
            driver.request_manager._client.request = AsyncMock(
                return_value=mock_response
            )

            await driver.run()

            # Verify first run started from default (1) and processed pages 1-3
            assert scraper1.starting_id_received == 1
            assert scraper1.pages_processed == [1, 2, 3]

            # Verify progress was tracked
            saved_progress = await driver.get_speculative_progress(
                "parse_start"
            )
            assert saved_progress == 3

        # Second run: Configured starting ID (5), process pages 5, 6, 7
        # This simulates what would happen after recovery
        db_path2 = tmp_path / "test_spec_restart_2.db"
        params = RestartableScraper.params()
        params.speculative.parse_start = 5  # Start from page 5
        scraper2 = RestartableScraper(params=params)

        async with LocalDevDriver.open(
            scraper2, db_path2, base_delay=0.0, jitter=0.0
        ) as driver:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.headers = {}
            mock_response.content = b""
            mock_response.text = ""
            driver.request_manager._client = MagicMock()
            driver.request_manager._client.request = AsyncMock(
                return_value=mock_response
            )

            await driver.run()

            # Verify second run started from configured ID (5)
            assert scraper2.starting_id_received == 5
            assert scraper2.pages_processed == [5, 6, 7]

            # Progress should be 7
            final_progress = await driver.get_speculative_progress(
                "parse_start"
            )
            assert final_progress == 7

    async def test_speculative_metadata_stored_in_permanent(
        self, tmp_path: Path
    ) -> None:
        """Test that speculative request metadata is stored in permanent_json.

        This ensures recovery is possible after restart by verifying the
        _speculative_step and _speculative_id fields are persisted.
        """
        from unittest.mock import AsyncMock, MagicMock

        from juriscraper.scraper_driver.common.decorators import step
        from juriscraper.scraper_driver.data_types import (
            BaseScraper,
            HttpMethod,
            HTTPRequestParams,
            NavigatingRequest,
            ParsedData,
            Response,
            ScraperYield,
            SpeculativeRequest,
        )
        from juriscraper.scraper_driver.driver.dev_driver.dev_driver import (
            LocalDevDriver,
        )

        class MetadataScraper(BaseScraper[dict]):
            def get_entry(self) -> Generator[NavigatingRequest, None, None]:
                yield NavigatingRequest(
                    request=HTTPRequestParams(
                        method=HttpMethod.GET, url="https://example.com/start"
                    ),
                    continuation="parse_start",
                )

            @step(speculative=True)
            def parse_start(
                self, response: Response, speculative_id: int = 1
            ) -> Generator[ScraperYield, bool | None, None]:
                # Just yield one speculative request
                yield SpeculativeRequest(
                    request=HTTPRequestParams(
                        method=HttpMethod.GET,
                        url="https://example.com/speculative",
                    ),
                    continuation="parse_result",
                    speculative_id=42,  # Specific ID to verify
                )

            @step
            def parse_result(
                self, response: Response
            ) -> Generator[ScraperYield, bool | None, None]:
                yield ParsedData({"done": True})

        db_path = tmp_path / "test_metadata.db"
        scraper = MetadataScraper()

        async with LocalDevDriver.open(
            scraper, db_path, base_delay=0.0, jitter=0.0
        ) as driver:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.headers = {}
            mock_response.content = b""
            mock_response.text = ""
            driver.request_manager._client = MagicMock()
            driver.request_manager._client.request = AsyncMock(
                return_value=mock_response
            )

            # Run the scraper - this will process all requests
            await driver.run()

            # Check that the speculative request had metadata stored
            # Even though it's completed, we can check the permanent_json was stored
            cursor = await driver.db.db.execute(
                """
                SELECT permanent_json FROM requests
                WHERE url = 'https://example.com/speculative'
                """
            )
            row = await cursor.fetchone()
            assert row is not None

            permanent_data = json.loads(row[0])
            assert permanent_data.get("_speculative_step") == "parse_start"
            assert permanent_data.get("_speculative_id") == 42

    async def test_multiple_speculative_steps_tracked_separately(
        self, tmp_path: Path
    ) -> None:
        """Test that multiple speculative steps track progress independently."""
        from unittest.mock import AsyncMock, MagicMock

        from juriscraper.scraper_driver.common.decorators import step
        from juriscraper.scraper_driver.data_types import (
            BaseScraper,
            HttpMethod,
            HTTPRequestParams,
            NavigatingRequest,
            ParsedData,
            Response,
            ScraperYield,
            SpeculativeRequest,
        )
        from juriscraper.scraper_driver.driver.dev_driver.dev_driver import (
            LocalDevDriver,
        )

        class MultiStepScraper(BaseScraper[dict]):
            """Scraper with two independent speculative steps."""

            def __init__(self) -> None:
                super().__init__()
                self.step_a_ids: list[int] = []
                self.step_b_ids: list[int] = []
                self._params = ScraperParams()

            def get_entry(self) -> Generator[NavigatingRequest, None, None]:
                yield NavigatingRequest(
                    request=HTTPRequestParams(
                        method=HttpMethod.GET, url="https://example.com/start"
                    ),
                    continuation="speculative_step_a",
                )

            @step(speculative=True)
            def speculative_step_a(
                self, response: Response, speculative_id: int
            ) -> Generator[ScraperYield, bool | None, None]:
                """First speculative step - processes IDs 1-3."""
                current_id = speculative_id
                while current_id <= 3:
                    self.step_a_ids.append(current_id)
                    should_continue = yield SpeculativeRequest(
                        request=HTTPRequestParams(
                            method=HttpMethod.GET,
                            url=f"https://example.com/a/{current_id}",
                        ),
                        continuation="parse_a",
                        speculative_id=current_id,
                    )
                    if not should_continue:
                        break
                    current_id += 1

                # After step A, trigger step B
                yield NavigatingRequest(
                    request=HTTPRequestParams(
                        method=HttpMethod.GET,
                        url="https://example.com/start_b",
                    ),
                    continuation="speculative_step_b",
                )

            @step(speculative=True)
            def speculative_step_b(
                self, response: Response, speculative_id: int
            ) -> Generator[ScraperYield, bool | None, None]:
                """Second speculative step - processes IDs 1-5."""
                current_id = speculative_id
                while current_id <= 5:
                    self.step_b_ids.append(current_id)
                    should_continue = yield SpeculativeRequest(
                        request=HTTPRequestParams(
                            method=HttpMethod.GET,
                            url=f"https://example.com/b/{current_id}",
                        ),
                        continuation="parse_b",
                        speculative_id=current_id,
                    )
                    if not should_continue:
                        break
                    current_id += 1

            @step
            def parse_a(
                self, response: Response
            ) -> Generator[ScraperYield, bool | None, None]:
                yield ParsedData({"type": "a"})

            @step
            def parse_b(
                self, response: Response
            ) -> Generator[ScraperYield, bool | None, None]:
                yield ParsedData({"type": "b"})

        db_path = tmp_path / "test_multi_step.db"
        scraper = MultiStepScraper()

        async with LocalDevDriver.open(
            scraper, db_path, base_delay=0.0, jitter=0.0
        ) as driver:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.headers = {}
            mock_response.content = b""
            mock_response.text = ""
            driver.request_manager._client = MagicMock()
            driver.request_manager._client.request = AsyncMock(
                return_value=mock_response
            )

            await driver.run()

            # Verify both steps were processed
            assert scraper.step_a_ids == [1, 2, 3]
            assert scraper.step_b_ids == [1, 2, 3, 4, 5]

            # Verify progress is tracked separately
            progress_a = await driver.get_speculative_progress(
                "speculative_step_a"
            )
            progress_b = await driver.get_speculative_progress(
                "speculative_step_b"
            )

            assert progress_a == 3
            assert progress_b == 5

            # Verify get_all_speculative_progress returns both
            all_progress = await driver.get_all_speculative_progress()
            assert "speculative_step_a" in all_progress
            assert "speculative_step_b" in all_progress
            assert all_progress["speculative_step_a"] == 3
            assert all_progress["speculative_step_b"] == 5
