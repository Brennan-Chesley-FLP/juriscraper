"""Tests for LocalDevDriverDebugger.

These tests verify the LocalDevDriverDebugger class which provides standalone
inspection and manipulation of scraper run databases.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import aiosqlite
import pytest

from juriscraper.scraper_driver.driver.dev_driver.compression import compress
from juriscraper.scraper_driver.driver.dev_driver.debugger import (
    LocalDevDriverDebugger,
)
from juriscraper.scraper_driver.driver.dev_driver.schema import init_database
from juriscraper.scraper_driver.driver.dev_driver.sql_manager import SQLManager


@pytest.fixture
async def db_path(tmp_path: Path) -> Path:
    """Create a temporary database path."""
    return tmp_path / "test.db"


@pytest.fixture
async def initialized_db(db_path: Path) -> aiosqlite.Connection:
    """Create an initialized database connection."""
    db = await init_database(db_path)
    yield db
    await db.close()


@pytest.fixture
async def populated_db(
    initialized_db: aiosqlite.Connection,
) -> aiosqlite.Connection:
    """Create a populated database with sample data for testing.

    This fixture creates:
    - Run metadata for a test scraper
    - Multiple requests with various statuses
    - Responses with content
    - Results (both valid and invalid)
    - Errors (both resolved and unresolved)
    - Rate limiter state
    - Compression dictionaries
    """
    db = initialized_db
    sql_manager = SQLManager(db)

    # Insert run metadata directly (since we need fields not in init_run_metadata)
    await db.execute(
        """
        INSERT INTO run_metadata (
            scraper_name, scraper_version, status, created_at,
            base_delay, jitter, num_workers, max_backoff_time, speculation_config_json
        ) VALUES (?, ?, ?, datetime('now'), ?, ?, ?, ?, ?)
        """,
        (
            "test.scraper",
            "1.0.0",
            "running",
            0.5,
            0.2,
            4,
            300.0,
            "{}",
        ),
    )
    await db.commit()

    # Insert multiple requests with different statuses
    request_data = [
        ("GET", "https://example.com/page1", "step1", "pending"),
        ("GET", "https://example.com/page2", "step1", "completed"),
        ("GET", "https://example.com/page3", "step2", "failed"),
        ("GET", "https://example.com/page4", "step2", "held"),
        ("GET", "https://example.com/page5", "step1", "completed"),
    ]

    request_ids = []
    for method, url, continuation, target_status in request_data:
        # Insert using SQLManager
        request_id = await sql_manager.insert_request(
            priority=1,
            request_type="navigating",
            method=method,
            url=url,
            headers_json="{}",
            cookies_json="{}",
            body=None,
            continuation=continuation,
            current_location="",
            accumulated_data_json="{}",
            aux_data_json="{}",
            permanent_json="{}",
            expected_type=None,
            dedup_key=None,
            parent_id=None,
        )
        request_ids.append(request_id)

        # Update status to target status (since insert always creates pending)
        if target_status != "pending":
            await db.execute(
                "UPDATE requests SET status = ? WHERE id = ?",
                (target_status, request_id),
            )

    await db.commit()

    # Insert responses for completed requests using SQLManager
    import uuid

    response_data = [
        (
            request_ids[1],
            200,
            b"<html>Response 1</html>",
            "step1",
            "https://example.com/page2",
        ),
        (
            request_ids[4],
            200,
            b"<html>Response 2</html>",
            "step1",
            "https://example.com/page5",
        ),
    ]

    response_ids = []
    for request_id, status_code, content, continuation, url in response_data:
        compressed_content = compress(content)
        response_id = await sql_manager.store_response(
            request_id=request_id,
            status_code=status_code,
            headers_json="{}",
            url=url,
            compressed_content=compressed_content,
            content_size_original=len(content),
            content_size_compressed=len(compressed_content),
            dict_id=None,
            continuation=continuation,
            warc_record_id=str(uuid.uuid4()),
            speculation_outcome=None,
        )
        response_ids.append(response_id)

    await db.commit()

    # Insert results for completed responses (using raw SQL for test fixture)
    result_data = [
        (request_ids[1], "TestResult", {"title": "Result 1"}, True, None),
        (
            request_ids[4],
            "TestResult",
            {"title": "Result 2"},
            False,
            ["error1"],
        ),
    ]

    for request_id, result_type, data, is_valid, errors in result_data:
        await db.execute(
            """
            INSERT INTO results (
                request_id, result_type, data_json, is_valid,
                validation_errors_json, created_at
            ) VALUES (?, ?, ?, ?, ?, datetime('now'))
            """,
            (
                request_id,
                result_type,
                json.dumps(data),
                is_valid,
                json.dumps(errors) if errors else None,
            ),
        )

    await db.commit()

    # Insert errors (using raw SQL for test fixture)
    error_data = [
        (
            request_ids[2],
            "xpath",
            "XPath not found",
            "//*[@id='test']",
            "xpath",
            1,
            1,
            0,
            False,
            None,
        ),
        (
            request_ids[3],
            "http",
            "Connection timeout",
            None,
            None,
            None,
            None,
            None,
            True,
            "Resolved manually",
        ),
    ]

    for (
        request_id,
        error_type,
        message,
        selector,
        selector_type,
        expected_min,
        expected_max,
        actual_count,
        is_resolved,
        resolution_notes,
    ) in error_data:
        await db.execute(
            """
            INSERT INTO errors (
                request_id, error_type, message, selector, selector_type,
                expected_min, expected_max, actual_count, is_resolved,
                resolution_notes, created_at, request_url, error_class, traceback
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), ?, ?, ?)
            """,
            (
                request_id,
                error_type,
                message,
                selector,
                selector_type,
                expected_min,
                expected_max,
                actual_count,
                is_resolved,
                resolution_notes,
                f"https://example.com/page{request_id}",
                "TestError",
                "fake traceback",
            ),
        )

    await db.commit()

    # Insert rate limiter state (using raw SQL for test fixture)
    await db.execute(
        """
        INSERT INTO rate_limiter_state (
            tokens, rate, bucket_size, last_congestion_rate, jitter,
            last_used_at, total_requests, total_successes, total_rate_limited
        ) VALUES (?, ?, ?, ?, ?, datetime('now'), ?, ?, ?)
        """,
        (10.0, 2.0, 20.0, 1.5, 0.2, 100, 95, 5),
    )

    await db.commit()

    # Insert compression dictionary (using raw SQL for test fixture)
    await db.execute(
        """
        INSERT INTO compression_dicts (
            continuation, version, sample_count, dictionary_data, created_at
        ) VALUES (?, ?, ?, ?, datetime('now'))
        """,
        ("step1", 1, 100, b"fake_dict_data"),
    )

    await db.commit()

    return db


class TestDebuggerContextManager:
    """Tests for LocalDevDriverDebugger context manager."""

    async def test_open_read_only(
        self, db_path: Path, initialized_db: aiosqlite.Connection
    ) -> None:
        """Test opening debugger in read-only mode."""
        await initialized_db.close()

        async with LocalDevDriverDebugger.open(
            db_path, read_only=True
        ) as debugger:
            assert debugger.read_only is True
            assert debugger.sql is not None

    async def test_open_write_mode(
        self, db_path: Path, initialized_db: aiosqlite.Connection
    ) -> None:
        """Test opening debugger in write mode."""
        await initialized_db.close()

        async with LocalDevDriverDebugger.open(
            db_path, read_only=False
        ) as debugger:
            assert debugger.read_only is False
            assert debugger.sql is not None

    async def test_open_with_string_path(
        self, db_path: Path, initialized_db: aiosqlite.Connection
    ) -> None:
        """Test opening debugger with string path."""
        await initialized_db.close()

        async with LocalDevDriverDebugger.open(str(db_path)) as debugger:
            assert debugger.sql is not None


class TestRunMetadataAndStats:
    """Tests for run metadata and statistics methods."""

    async def test_get_run_metadata(
        self, db_path: Path, populated_db: aiosqlite.Connection
    ) -> None:
        """Test getting run metadata."""
        await populated_db.close()

        async with LocalDevDriverDebugger.open(db_path) as debugger:
            metadata = await debugger.get_run_metadata()

            assert metadata is not None
            assert metadata["scraper_name"] == "test.scraper"
            assert metadata["scraper_version"] == "1.0.0"
            assert metadata["status"] == "running"
            assert metadata["base_delay"] == 0.5

    async def test_get_run_metadata_empty_db(
        self, db_path: Path, initialized_db: aiosqlite.Connection
    ) -> None:
        """Test getting run metadata from empty database."""
        await initialized_db.close()

        async with LocalDevDriverDebugger.open(db_path) as debugger:
            metadata = await debugger.get_run_metadata()
            assert metadata is None

    async def test_get_run_status_running(
        self, db_path: Path, populated_db: aiosqlite.Connection
    ) -> None:
        """Test getting run status for a running scraper."""
        await populated_db.close()

        async with LocalDevDriverDebugger.open(db_path) as debugger:
            status = await debugger.get_run_status()

            assert status["status"] == "running"
            assert status["is_running"] is True
            assert "pending_count" in status
            # From the populated_db fixture, there's 1 pending request
            assert status["pending_count"] == 1

    async def test_get_run_status_completed(
        self, db_path: Path, initialized_db: aiosqlite.Connection
    ) -> None:
        """Test getting run status for a completed scraper."""
        # Insert run metadata with completed status
        await initialized_db.execute(
            """
            INSERT INTO run_metadata (
                scraper_name, scraper_version, status, created_at,
                base_delay, jitter, num_workers, max_backoff_time, speculation_config_json
            ) VALUES (?, ?, ?, datetime('now'), ?, ?, ?, ?, ?)
            """,
            (
                "test.scraper",
                "1.0.0",
                "completed",
                0.5,
                0.2,
                4,
                300.0,
                "{}",
            ),
        )
        await initialized_db.commit()
        await initialized_db.close()

        async with LocalDevDriverDebugger.open(db_path) as debugger:
            status = await debugger.get_run_status()

            assert status["status"] == "completed"
            assert status["is_running"] is False
            # pending_count should not be present for completed runs
            assert "pending_count" not in status

    async def test_get_run_status_empty_db(
        self, db_path: Path, initialized_db: aiosqlite.Connection
    ) -> None:
        """Test getting run status from empty database."""
        await initialized_db.close()

        async with LocalDevDriverDebugger.open(db_path) as debugger:
            status = await debugger.get_run_status()

            assert status["status"] == "unknown"
            assert status["is_running"] is False

    async def test_get_stats(
        self, db_path: Path, populated_db: aiosqlite.Connection
    ) -> None:
        """Test getting comprehensive statistics."""
        await populated_db.close()

        async with LocalDevDriverDebugger.open(db_path) as debugger:
            stats = await debugger.get_stats()

            assert "queue" in stats
            assert "throughput" in stats
            assert "compression" in stats
            assert "results" in stats
            assert "errors" in stats

            # Verify queue stats
            assert stats["queue"]["total"] == 5


class TestRequestInspection:
    """Tests for request inspection methods."""

    async def test_list_requests_no_filter(
        self, db_path: Path, populated_db: aiosqlite.Connection
    ) -> None:
        """Test listing all requests."""
        await populated_db.close()

        async with LocalDevDriverDebugger.open(db_path) as debugger:
            page = await debugger.list_requests()

            assert page.total == 5
            assert len(page.items) == 5
            assert not page.has_more

    async def test_list_requests_filter_by_status(
        self, db_path: Path, populated_db: aiosqlite.Connection
    ) -> None:
        """Test filtering requests by status."""
        await populated_db.close()

        async with LocalDevDriverDebugger.open(db_path) as debugger:
            # Get completed requests
            page = await debugger.list_requests(status="completed")
            assert page.total == 2
            assert all(req.status == "completed" for req in page.items)

            # Get pending requests
            page = await debugger.list_requests(status="pending")
            assert page.total == 1

            # Get failed requests
            page = await debugger.list_requests(status="failed")
            assert page.total == 1

    async def test_list_requests_filter_by_continuation(
        self, db_path: Path, populated_db: aiosqlite.Connection
    ) -> None:
        """Test filtering requests by continuation."""
        await populated_db.close()

        async with LocalDevDriverDebugger.open(db_path) as debugger:
            page = await debugger.list_requests(continuation="step1")
            assert page.total == 3
            assert all(req.continuation == "step1" for req in page.items)

    async def test_list_requests_pagination(
        self, db_path: Path, populated_db: aiosqlite.Connection
    ) -> None:
        """Test request pagination."""
        await populated_db.close()

        async with LocalDevDriverDebugger.open(db_path) as debugger:
            # First page
            page1 = await debugger.list_requests(limit=2, offset=0)
            assert len(page1.items) == 2
            assert page1.total == 5
            assert page1.has_more

            # Second page
            page2 = await debugger.list_requests(limit=2, offset=2)
            assert len(page2.items) == 2
            assert page2.has_more

            # Last page
            page3 = await debugger.list_requests(limit=2, offset=4)
            assert len(page3.items) == 1
            assert not page3.has_more

    async def test_get_request(
        self, db_path: Path, populated_db: aiosqlite.Connection
    ) -> None:
        """Test getting a single request."""
        await populated_db.close()

        async with LocalDevDriverDebugger.open(db_path) as debugger:
            request = await debugger.get_request(1)

            assert request is not None
            assert request.id == 1
            assert request.url == "https://example.com/page1"
            assert request.continuation == "step1"

    async def test_get_request_not_found(
        self, db_path: Path, populated_db: aiosqlite.Connection
    ) -> None:
        """Test getting a non-existent request."""
        await populated_db.close()

        async with LocalDevDriverDebugger.open(db_path) as debugger:
            request = await debugger.get_request(9999)
            assert request is None

    async def test_get_request_summary(
        self, db_path: Path, populated_db: aiosqlite.Connection
    ) -> None:
        """Test getting request summary."""
        await populated_db.close()

        async with LocalDevDriverDebugger.open(db_path) as debugger:
            summary = await debugger.get_request_summary()

            assert "all" in summary
            assert "step1" in summary
            assert "step2" in summary

            # Check totals
            assert summary["all"]["completed"] == 2
            assert summary["all"]["pending"] == 1
            assert summary["all"]["failed"] == 1
            assert summary["all"]["held"] == 1


class TestResponseInspection:
    """Tests for response inspection methods."""

    async def test_list_responses(
        self, db_path: Path, populated_db: aiosqlite.Connection
    ) -> None:
        """Test listing responses."""
        await populated_db.close()

        async with LocalDevDriverDebugger.open(db_path) as debugger:
            page = await debugger.list_responses()

            assert page.total == 2
            assert len(page.items) == 2

    async def test_list_responses_filter_by_continuation(
        self, db_path: Path, populated_db: aiosqlite.Connection
    ) -> None:
        """Test filtering responses by continuation."""
        await populated_db.close()

        async with LocalDevDriverDebugger.open(db_path) as debugger:
            page = await debugger.list_responses(continuation="step1")
            assert page.total == 2
            assert all(resp.continuation == "step1" for resp in page.items)

    async def test_get_response(
        self, db_path: Path, populated_db: aiosqlite.Connection
    ) -> None:
        """Test getting a single response."""
        await populated_db.close()

        async with LocalDevDriverDebugger.open(db_path) as debugger:
            response = await debugger.get_response(1)

            assert response is not None
            assert response.id == 1
            assert response.status_code == 200

    async def test_get_response_content(
        self, db_path: Path, populated_db: aiosqlite.Connection
    ) -> None:
        """Test getting decompressed response content."""
        await populated_db.close()

        async with LocalDevDriverDebugger.open(db_path) as debugger:
            content = await debugger.get_response_content(1)

            assert content is not None
            assert b"Response 1" in content


class TestErrorInspection:
    """Tests for error inspection methods."""

    async def test_list_errors(
        self, db_path: Path, populated_db: aiosqlite.Connection
    ) -> None:
        """Test listing errors."""
        await populated_db.close()

        async with LocalDevDriverDebugger.open(db_path) as debugger:
            page = await debugger.list_errors()

            assert page.total == 2
            assert len(page.items) == 2

    async def test_list_errors_filter_by_type(
        self, db_path: Path, populated_db: aiosqlite.Connection
    ) -> None:
        """Test filtering errors by type."""
        await populated_db.close()

        async with LocalDevDriverDebugger.open(db_path) as debugger:
            page = await debugger.list_errors(error_type="xpath")
            assert page.total == 1
            assert page.items[0]["error_type"] == "xpath"

    async def test_list_errors_filter_by_resolution(
        self, db_path: Path, populated_db: aiosqlite.Connection
    ) -> None:
        """Test filtering errors by resolution status."""
        await populated_db.close()

        async with LocalDevDriverDebugger.open(db_path) as debugger:
            # Unresolved errors
            page = await debugger.list_errors(is_resolved=False)
            assert page.total == 1

            # Resolved errors
            page = await debugger.list_errors(is_resolved=True)
            assert page.total == 1

    async def test_get_error(
        self, db_path: Path, populated_db: aiosqlite.Connection
    ) -> None:
        """Test getting a single error."""
        await populated_db.close()

        async with LocalDevDriverDebugger.open(db_path) as debugger:
            error = await debugger.get_error(1)

            assert error is not None
            assert error["error_type"] == "xpath"
            assert error["message"] == "XPath not found"
            assert error["selector"] == "//*[@id='test']"

    async def test_get_error_summary(
        self, db_path: Path, populated_db: aiosqlite.Connection
    ) -> None:
        """Test getting error summary."""
        await populated_db.close()

        async with LocalDevDriverDebugger.open(db_path) as debugger:
            summary = await debugger.get_error_summary()

            assert "by_type" in summary
            assert "by_continuation" in summary
            assert "totals" in summary

            # Check totals
            assert summary["totals"]["total"] == 2
            assert summary["totals"]["resolved"] == 1
            assert summary["totals"]["unresolved"] == 1


class TestResultInspection:
    """Tests for result inspection methods."""

    async def test_list_results(
        self, db_path: Path, populated_db: aiosqlite.Connection
    ) -> None:
        """Test listing results."""
        await populated_db.close()

        async with LocalDevDriverDebugger.open(db_path) as debugger:
            page = await debugger.list_results()

            assert page.total == 2
            assert len(page.items) == 2

    async def test_list_results_filter_by_validity(
        self, db_path: Path, populated_db: aiosqlite.Connection
    ) -> None:
        """Test filtering results by validity."""
        await populated_db.close()

        async with LocalDevDriverDebugger.open(db_path) as debugger:
            # Valid results
            page = await debugger.list_results(is_valid=True)
            assert page.total == 1

            # Invalid results
            page = await debugger.list_results(is_valid=False)
            assert page.total == 1

    async def test_get_result(
        self, db_path: Path, populated_db: aiosqlite.Connection
    ) -> None:
        """Test getting a single result."""
        await populated_db.close()

        async with LocalDevDriverDebugger.open(db_path) as debugger:
            result = await debugger.get_result(1)

            assert result is not None
            assert result.result_type == "TestResult"
            assert result.data is not None
            assert result.data["title"] == "Result 1"
            assert result.is_valid is True

    async def test_get_result_summary(
        self, db_path: Path, populated_db: aiosqlite.Connection
    ) -> None:
        """Test getting result summary."""
        await populated_db.close()

        async with LocalDevDriverDebugger.open(db_path) as debugger:
            summary = await debugger.get_result_summary()

            assert "TestResult" in summary
            assert summary["TestResult"]["valid"] == 1
            assert summary["TestResult"]["invalid"] == 1
            assert summary["TestResult"]["total"] == 2


class TestSpeculationInspection:
    """Tests for speculation inspection methods."""

    async def test_get_speculation_summary(
        self, db_path: Path, populated_db: aiosqlite.Connection
    ) -> None:
        """Test getting speculation summary."""
        await populated_db.close()

        async with LocalDevDriverDebugger.open(db_path) as debugger:
            summary = await debugger.get_speculation_summary()

            assert "config" in summary
            assert "progress" in summary
            assert "tracking" in summary

    async def test_get_speculative_progress(
        self, db_path: Path, populated_db: aiosqlite.Connection
    ) -> None:
        """Test getting speculative progress."""
        await populated_db.close()

        async with LocalDevDriverDebugger.open(db_path) as debugger:
            progress = await debugger.get_speculative_progress()

            # Empty progress in test database
            assert isinstance(progress, dict)


class TestRateLimiterInspection:
    """Tests for rate limiter inspection methods."""

    async def test_get_rate_limiter_state(
        self, db_path: Path, populated_db: aiosqlite.Connection
    ) -> None:
        """Test getting rate limiter state."""
        await populated_db.close()

        async with LocalDevDriverDebugger.open(db_path) as debugger:
            state = await debugger.get_rate_limiter_state()

            assert state is not None
            assert state["tokens"] == 10.0
            assert state["rate"] == 2.0
            assert state["bucket_size"] == 20.0
            assert state["total_requests"] == 100

    async def test_get_throughput_stats(
        self, db_path: Path, populated_db: aiosqlite.Connection
    ) -> None:
        """Test getting throughput statistics."""
        await populated_db.close()

        async with LocalDevDriverDebugger.open(db_path) as debugger:
            stats = await debugger.get_throughput_stats()

            assert isinstance(stats, dict)


class TestCompressionInspection:
    """Tests for compression inspection methods."""

    async def test_get_compression_stats(
        self, db_path: Path, populated_db: aiosqlite.Connection
    ) -> None:
        """Test getting compression statistics."""
        await populated_db.close()

        async with LocalDevDriverDebugger.open(db_path) as debugger:
            stats = await debugger.get_compression_stats()

            assert isinstance(stats, dict)
            assert "total" in stats

    async def test_list_compression_dicts(
        self, db_path: Path, populated_db: aiosqlite.Connection
    ) -> None:
        """Test listing compression dictionaries."""
        await populated_db.close()

        async with LocalDevDriverDebugger.open(db_path) as debugger:
            dicts = await debugger.list_compression_dicts()

            assert len(dicts) == 1
            assert dicts[0]["continuation"] == "step1"
            assert dicts[0]["version"] == 1
            assert dicts[0]["sample_count"] == 100


class TestReadOnlyModeEnforcement:
    """Tests for read-only mode enforcement."""

    async def test_cancel_request_read_only(
        self, db_path: Path, populated_db: aiosqlite.Connection
    ) -> None:
        """Test that cancel_request raises error in read-only mode."""
        await populated_db.close()

        async with LocalDevDriverDebugger.open(
            db_path, read_only=True
        ) as debugger:
            with pytest.raises(PermissionError, match="write mode"):
                await debugger.cancel_request(1)

    async def test_cancel_requests_by_continuation_read_only(
        self, db_path: Path, populated_db: aiosqlite.Connection
    ) -> None:
        """Test that cancel_requests_by_continuation raises error in read-only mode."""
        await populated_db.close()

        async with LocalDevDriverDebugger.open(
            db_path, read_only=True
        ) as debugger:
            with pytest.raises(PermissionError, match="write mode"):
                await debugger.cancel_requests_by_continuation("step1")

    async def test_requeue_request_read_only(
        self, db_path: Path, populated_db: aiosqlite.Connection
    ) -> None:
        """Test that requeue_request raises error in read-only mode."""
        await populated_db.close()

        async with LocalDevDriverDebugger.open(
            db_path, read_only=True
        ) as debugger:
            with pytest.raises(PermissionError, match="write mode"):
                await debugger.requeue_request(2)

    async def test_requeue_continuation_read_only(
        self, db_path: Path, populated_db: aiosqlite.Connection
    ) -> None:
        """Test that requeue_continuation raises error in read-only mode."""
        await populated_db.close()

        async with LocalDevDriverDebugger.open(
            db_path, read_only=True
        ) as debugger:
            with pytest.raises(PermissionError, match="write mode"):
                await debugger.requeue_continuation("step1")

    async def test_resolve_error_read_only(
        self, db_path: Path, populated_db: aiosqlite.Connection
    ) -> None:
        """Test that resolve_error raises error in read-only mode."""
        await populated_db.close()

        async with LocalDevDriverDebugger.open(
            db_path, read_only=True
        ) as debugger:
            with pytest.raises(PermissionError, match="write mode"):
                await debugger.resolve_error(1)

    async def test_requeue_error_read_only(
        self, db_path: Path, populated_db: aiosqlite.Connection
    ) -> None:
        """Test that requeue_error raises error in read-only mode."""
        await populated_db.close()

        async with LocalDevDriverDebugger.open(
            db_path, read_only=True
        ) as debugger:
            with pytest.raises(PermissionError, match="write mode"):
                await debugger.requeue_error(1)

    async def test_batch_requeue_errors_read_only(
        self, db_path: Path, populated_db: aiosqlite.Connection
    ) -> None:
        """Test that batch_requeue_errors raises error in read-only mode."""
        await populated_db.close()

        async with LocalDevDriverDebugger.open(
            db_path, read_only=True
        ) as debugger:
            with pytest.raises(PermissionError, match="write mode"):
                await debugger.batch_requeue_errors(error_type="xpath")

    async def test_train_compression_dict_read_only(
        self, db_path: Path, populated_db: aiosqlite.Connection
    ) -> None:
        """Test that train_compression_dict raises error in read-only mode."""
        await populated_db.close()

        async with LocalDevDriverDebugger.open(
            db_path, read_only=True
        ) as debugger:
            with pytest.raises(PermissionError, match="write mode"):
                await debugger.train_compression_dict("step1")

    async def test_recompress_responses_read_only(
        self, db_path: Path, populated_db: aiosqlite.Connection
    ) -> None:
        """Test that recompress_responses raises error in read-only mode."""
        await populated_db.close()

        async with LocalDevDriverDebugger.open(
            db_path, read_only=True
        ) as debugger:
            with pytest.raises(PermissionError, match="write mode"):
                await debugger.recompress_responses("step1")


class TestManipulationMethods:
    """Tests for manipulation methods in write mode."""

    async def test_cancel_request(
        self, db_path: Path, populated_db: aiosqlite.Connection
    ) -> None:
        """Test cancelling a request."""
        await populated_db.close()

        async with LocalDevDriverDebugger.open(
            db_path, read_only=False
        ) as debugger:
            # Cancel a pending request
            result = await debugger.cancel_request(1)
            assert result is True

            # Verify it's marked as failed
            request = await debugger.get_request(1)
            assert request is not None
            assert request.status == "failed"

    async def test_cancel_requests_by_continuation(
        self, db_path: Path, populated_db: aiosqlite.Connection
    ) -> None:
        """Test cancelling all requests for a continuation."""
        await populated_db.close()

        async with LocalDevDriverDebugger.open(
            db_path, read_only=False
        ) as debugger:
            # Cancel all pending/held requests for step2
            count = await debugger.cancel_requests_by_continuation("step2")
            assert count == 1  # Only the held request

    async def test_requeue_request_with_downstream_clear(
        self, db_path: Path, populated_db: aiosqlite.Connection
    ) -> None:
        """Test requeuing a request with downstream cleanup."""
        await populated_db.close()

        async with LocalDevDriverDebugger.open(
            db_path, read_only=False
        ) as debugger:
            # Requeue a completed request
            new_id = await debugger.requeue_request(2, clear_downstream=True)
            assert new_id > 0

            # Verify new request exists
            new_request = await debugger.get_request(new_id)
            assert new_request is not None
            assert new_request.url == "https://example.com/page2"
            assert new_request.status == "pending"

    async def test_requeue_request_without_downstream_clear(
        self, db_path: Path, populated_db: aiosqlite.Connection
    ) -> None:
        """Test requeuing a request without downstream cleanup."""
        await populated_db.close()

        async with LocalDevDriverDebugger.open(
            db_path, read_only=False
        ) as debugger:
            # Requeue without clearing downstream
            new_id = await debugger.requeue_request(2, clear_downstream=False)
            assert new_id > 0

            # Verify new request exists
            new_request = await debugger.get_request(new_id)
            assert new_request is not None

    async def test_requeue_continuation(
        self, db_path: Path, populated_db: aiosqlite.Connection
    ) -> None:
        """Test requeuing all requests for a continuation."""
        await populated_db.close()

        async with LocalDevDriverDebugger.open(
            db_path, read_only=False
        ) as debugger:
            # Requeue all completed requests for step1
            count = await debugger.requeue_continuation(
                "step1", status="completed"
            )
            assert count == 2  # Two completed requests in step1

    async def test_resolve_error(
        self, db_path: Path, populated_db: aiosqlite.Connection
    ) -> None:
        """Test resolving an error."""
        await populated_db.close()

        async with LocalDevDriverDebugger.open(
            db_path, read_only=False
        ) as debugger:
            # Resolve an unresolved error
            result = await debugger.resolve_error(1, "Fixed the selector")
            assert result is True

            # Verify it's resolved
            error = await debugger.get_error(1)
            assert error is not None
            assert error["is_resolved"] is True
            assert error["resolution_notes"] == "Fixed the selector"

    async def test_requeue_error(
        self, db_path: Path, populated_db: aiosqlite.Connection
    ) -> None:
        """Test requeuing an error."""
        await populated_db.close()

        async with LocalDevDriverDebugger.open(
            db_path, read_only=False
        ) as debugger:
            # Requeue an error
            new_id = await debugger.requeue_error(1, "Trying again")
            assert new_id > 0

            # Verify error is resolved
            error = await debugger.get_error(1)
            assert error is not None
            assert error["is_resolved"] is True

    async def test_batch_requeue_errors(
        self, db_path: Path, populated_db: aiosqlite.Connection
    ) -> None:
        """Test batch requeuing errors."""
        await populated_db.close()

        async with LocalDevDriverDebugger.open(
            db_path, read_only=False
        ) as debugger:
            # Batch requeue xpath errors
            count = await debugger.batch_requeue_errors(error_type="xpath")
            assert count == 1  # One unresolved xpath error


class TestExportMethods:
    """Tests for export methods."""

    async def test_export_results_jsonl(
        self, db_path: Path, populated_db: aiosqlite.Connection, tmp_path: Path
    ) -> None:
        """Test exporting results to JSONL."""
        await populated_db.close()

        output_path = tmp_path / "results.jsonl"

        async with LocalDevDriverDebugger.open(db_path) as debugger:
            count = await debugger.export_results_jsonl(output_path)

            assert count == 2
            assert output_path.exists()

            # Verify content
            lines = output_path.read_text().strip().split("\n")
            assert len(lines) == 2

            # Parse first line
            result = json.loads(lines[0])
            assert "id" in result
            assert "result_type" in result
            assert "data" in result
            assert result["result_type"] == "TestResult"

    async def test_export_results_jsonl_filtered(
        self, db_path: Path, populated_db: aiosqlite.Connection, tmp_path: Path
    ) -> None:
        """Test exporting filtered results to JSONL."""
        await populated_db.close()

        output_path = tmp_path / "valid_results.jsonl"

        async with LocalDevDriverDebugger.open(db_path) as debugger:
            count = await debugger.export_results_jsonl(
                output_path, is_valid=True
            )

            assert count == 1
            assert output_path.exists()

    async def test_preview_warc_export(
        self, db_path: Path, populated_db: aiosqlite.Connection
    ) -> None:
        """Test previewing WARC export."""
        await populated_db.close()

        async with LocalDevDriverDebugger.open(db_path) as debugger:
            preview = await debugger.preview_warc_export()

            assert "record_count" in preview
            assert "estimated_size" in preview
            assert preview["record_count"] == 2  # Two responses


class TestDiagnoseMethods:
    """Tests for diagnosis methods."""

    async def test_diagnose_error(
        self, db_path: Path, populated_db: aiosqlite.Connection
    ) -> None:
        """Test diagnosing an error."""
        await populated_db.close()

        async with LocalDevDriverDebugger.open(db_path) as debugger:
            # Diagnose the xpath error
            # Note: Full diagnosis requires scraper class, so we test partial functionality
            with pytest.raises(ValueError, match="No response found"):
                # Error ID 1 is for request_id 3, which has no response
                await debugger.diagnose(1)

    async def test_diagnose_error_not_found(
        self, db_path: Path, populated_db: aiosqlite.Connection
    ) -> None:
        """Test diagnosing a non-existent error."""
        await populated_db.close()

        async with LocalDevDriverDebugger.open(db_path) as debugger:
            with pytest.raises(ValueError, match="Error .* not found"):
                await debugger.diagnose(9999)


class TestResponseSearch:
    """Tests for response search methods."""

    async def test_search_text_match(
        self, db_path: Path, populated_db: aiosqlite.Connection
    ) -> None:
        """Test text search that finds matches."""
        await populated_db.close()

        async with LocalDevDriverDebugger.open(db_path) as debugger:
            matches = await debugger.search_responses(text="Response")

            assert len(matches) == 2
            assert all("response_id" in m for m in matches)
            assert all("request_id" in m for m in matches)

    async def test_search_text_case_insensitive(
        self, db_path: Path, populated_db: aiosqlite.Connection
    ) -> None:
        """Test that text search is case insensitive."""
        await populated_db.close()

        async with LocalDevDriverDebugger.open(db_path) as debugger:
            matches = await debugger.search_responses(text="RESPONSE")

            assert len(matches) == 2

    async def test_search_text_no_match(
        self, db_path: Path, populated_db: aiosqlite.Connection
    ) -> None:
        """Test text search that finds no matches."""
        await populated_db.close()

        async with LocalDevDriverDebugger.open(db_path) as debugger:
            matches = await debugger.search_responses(text="nonexistent")

            assert len(matches) == 0

    async def test_search_regex_match(
        self, db_path: Path, populated_db: aiosqlite.Connection
    ) -> None:
        """Test regex search that finds matches."""
        await populated_db.close()

        async with LocalDevDriverDebugger.open(db_path) as debugger:
            matches = await debugger.search_responses(regex=r"Response \d")

            assert len(matches) == 2

    async def test_search_regex_no_match(
        self, db_path: Path, populated_db: aiosqlite.Connection
    ) -> None:
        """Test regex search that finds no matches."""
        await populated_db.close()

        async with LocalDevDriverDebugger.open(db_path) as debugger:
            matches = await debugger.search_responses(regex=r"Response \d{5}")

            assert len(matches) == 0

    async def test_search_xpath_match(
        self, db_path: Path, populated_db: aiosqlite.Connection
    ) -> None:
        """Test XPath search that finds matches."""
        await populated_db.close()

        async with LocalDevDriverDebugger.open(db_path) as debugger:
            matches = await debugger.search_responses(xpath="//html")

            assert len(matches) == 2

    async def test_search_xpath_no_match(
        self, db_path: Path, populated_db: aiosqlite.Connection
    ) -> None:
        """Test XPath search that finds no matches."""
        await populated_db.close()

        async with LocalDevDriverDebugger.open(db_path) as debugger:
            matches = await debugger.search_responses(
                xpath="//div[@class='nonexistent']"
            )

            assert len(matches) == 0

    async def test_search_with_continuation_filter(
        self, db_path: Path, populated_db: aiosqlite.Connection
    ) -> None:
        """Test search with continuation filter."""
        await populated_db.close()

        async with LocalDevDriverDebugger.open(db_path) as debugger:
            # Both responses are in step1
            matches = await debugger.search_responses(
                text="Response", continuation="step1"
            )

            assert len(matches) == 2

            # No responses in step2
            matches = await debugger.search_responses(
                text="Response", continuation="step2"
            )

            assert len(matches) == 0

    async def test_search_requires_exactly_one_pattern(
        self, db_path: Path, populated_db: aiosqlite.Connection
    ) -> None:
        """Test that exactly one search pattern must be provided."""
        await populated_db.close()

        async with LocalDevDriverDebugger.open(db_path) as debugger:
            # No pattern provided
            with pytest.raises(ValueError, match="Exactly one"):
                await debugger.search_responses()

            # Multiple patterns provided
            with pytest.raises(ValueError, match="Exactly one"):
                await debugger.search_responses(text="foo", regex="bar")

    async def test_search_returns_correct_ids(
        self, db_path: Path, populated_db: aiosqlite.Connection
    ) -> None:
        """Test that search returns correct response and request IDs."""
        await populated_db.close()

        async with LocalDevDriverDebugger.open(db_path) as debugger:
            # Search for "Response 1" - should only match first response
            matches = await debugger.search_responses(text="Response 1")

            assert len(matches) == 1
            assert matches[0]["response_id"] == 1
            # Request IDs are 2 and 5 for the two completed requests
            assert matches[0]["request_id"] == 2


class TestComparisonMethods:
    """Tests for comparison-related methods."""

    async def test_get_child_requests_transitive(
        self, db_path: Path, initialized_db: aiosqlite.Connection
    ) -> None:
        """Test getting child requests transitively."""
        db = initialized_db
        sql_manager = SQLManager(db)

        # Create a parent request
        parent_id = await sql_manager.insert_request(
            priority=1,
            request_type="navigating",
            method="GET",
            url="https://example.com/parent",
            headers_json="{}",
            cookies_json="{}",
            body=None,
            continuation="step1",
            current_location="",
            accumulated_data_json="{}",
            aux_data_json="{}",
            permanent_json="{}",
            expected_type=None,
            dedup_key=None,
            parent_id=None,
        )

        # Create a child request
        child_id = await sql_manager.insert_request(
            priority=1,
            request_type="navigating",
            method="GET",
            url="https://example.com/child",
            headers_json="{}",
            cookies_json="{}",
            body=None,
            continuation="step2",
            current_location="",
            accumulated_data_json="{}",
            aux_data_json="{}",
            permanent_json="{}",
            expected_type=None,
            dedup_key=None,
            parent_id=parent_id,
        )

        # Create a grandchild request
        grandchild_id = await sql_manager.insert_request(
            priority=1,
            request_type="navigating",
            method="GET",
            url="https://example.com/grandchild",
            headers_json="{}",
            cookies_json="{}",
            body=None,
            continuation="step3",
            current_location="",
            accumulated_data_json="{}",
            aux_data_json="{}",
            permanent_json="{}",
            expected_type=None,
            dedup_key=None,
            parent_id=child_id,
        )

        await db.close()

        async with LocalDevDriverDebugger.open(db_path) as debugger:
            # Get all transitive children of parent
            children = await debugger.get_child_requests_transitive(parent_id)

            # Should get both child and grandchild
            assert len(children) == 2
            child_ids = {r.id for r in children}
            assert child_id in child_ids
            assert grandchild_id in child_ids

    async def test_get_results_for_request(
        self, db_path: Path, initialized_db: aiosqlite.Connection
    ) -> None:
        """Test getting results for a request."""
        db = initialized_db
        sql_manager = SQLManager(db)

        # Create a request
        request_id = await sql_manager.insert_request(
            priority=1,
            request_type="navigating",
            method="GET",
            url="https://example.com/test",
            headers_json="{}",
            cookies_json="{}",
            body=None,
            continuation="step1",
            current_location="",
            accumulated_data_json="{}",
            aux_data_json="{}",
            permanent_json="{}",
            expected_type=None,
            dedup_key=None,
            parent_id=None,
        )

        # Store some results
        await sql_manager.store_result(
            request_id=request_id,
            result_type="TestData",
            data_json='{"field": "value1"}',
            is_valid=True,
        )

        await sql_manager.store_result(
            request_id=request_id,
            result_type="TestData",
            data_json='{"field": "value2"}',
            is_valid=True,
        )

        await db.close()

        async with LocalDevDriverDebugger.open(db_path) as debugger:
            results = await debugger.get_results_for_request(request_id)

            assert len(results) == 2
            assert all(r.request_id == request_id for r in results)
            assert all(r.result_type == "TestData" for r in results)

    async def test_sample_terminal_requests(
        self, db_path: Path, initialized_db: aiosqlite.Connection
    ) -> None:
        """Test sampling terminal requests (requests with no children)."""
        db = initialized_db
        sql_manager = SQLManager(db)

        # Create some terminal requests (no children)
        terminal_ids = []
        for i in range(5):
            req_id = await sql_manager.insert_request(
                priority=1,
                request_type="navigating",
                method="GET",
                url=f"https://example.com/terminal{i}",
                headers_json="{}",
                cookies_json="{}",
                body=None,
                continuation="step1",
                current_location="",
                accumulated_data_json="{}",
                aux_data_json="{}",
                permanent_json="{}",
                expected_type=None,
                dedup_key=None,
                parent_id=None,
            )
            # Mark as completed
            await db.execute(
                "UPDATE requests SET status = ? WHERE id = ?",
                ("completed", req_id),
            )
            terminal_ids.append(req_id)

        # Create a non-terminal request (has children)
        parent_id = await sql_manager.insert_request(
            priority=1,
            request_type="navigating",
            method="GET",
            url="https://example.com/parent",
            headers_json="{}",
            cookies_json="{}",
            body=None,
            continuation="step1",
            current_location="",
            accumulated_data_json="{}",
            aux_data_json="{}",
            permanent_json="{}",
            expected_type=None,
            dedup_key=None,
            parent_id=None,
        )
        await db.execute(
            "UPDATE requests SET status = ? WHERE id = ?",
            ("completed", parent_id),
        )

        # Add a child to make it non-terminal
        await sql_manager.insert_request(
            priority=1,
            request_type="navigating",
            method="GET",
            url="https://example.com/child",
            headers_json="{}",
            cookies_json="{}",
            body=None,
            continuation="step2",
            current_location="",
            accumulated_data_json="{}",
            aux_data_json="{}",
            permanent_json="{}",
            expected_type=None,
            dedup_key=None,
            parent_id=parent_id,
        )
        await db.commit()

        await db.close()

        async with LocalDevDriverDebugger.open(db_path) as debugger:
            # Sample 3 terminal requests
            sampled = await debugger.sample_terminal_requests("step1", 3)

            # Should get exactly 3
            assert len(sampled) == 3
            # All should be from our terminal requests
            assert all(req_id in terminal_ids for req_id in sampled)
            # Parent should not be sampled (it has children)
            assert parent_id not in sampled

    @pytest.mark.asyncio
    async def test_compare_continuation_identical_output(
        self, db_path: Path, initialized_db: aiosqlite.Connection
    ) -> None:
        """Test compare_continuation with identical outputs."""
        from juriscraper.scraper_driver.common.data_models import ScrapedData
        from juriscraper.scraper_driver.data_types import (
            BaseScraper,
            NavigatingRequest,
            ParsedData,
            Response,
        )

        class SampleData(ScrapedData):
            title: str
            value: int

        class TestScraper(BaseScraper[SampleData]):
            def get_entry(self):
                yield NavigatingRequest(
                    request={"method": "GET", "url": "https://example.com"},
                    continuation="parse_index",
                )

            def parse_index(self, response: Response):
                # Yield same data as stored
                yield ParsedData(SampleData(title="Test Item", value=100))

        db = initialized_db
        sql_manager = SQLManager(db)

        # Create a request
        req_id = await sql_manager.insert_request(
            priority=1,
            request_type="navigating",
            method="GET",
            url="https://example.com/index",
            headers_json="{}",
            cookies_json="{}",
            body=None,
            continuation="parse_index",
            current_location="https://example.com",
            accumulated_data_json="{}",
            aux_data_json="{}",
            permanent_json="{}",
            expected_type=None,
            dedup_key=None,
            parent_id=None,
        )

        # Create a response
        content = b"<html>Test</html>"
        compressed_content = compress(content)
        await sql_manager.store_response(
            request_id=req_id,
            status_code=200,
            headers_json='{"Content-Type": "text/html"}',
            url="https://example.com/index",
            compressed_content=compressed_content,
            content_size_original=len(content),
            content_size_compressed=len(compressed_content),
            dict_id=None,
            continuation="parse_index",
            warc_record_id=str(uuid.uuid4()),
            speculation_outcome=None,
        )

        # Mark request as completed
        await db.execute(
            "UPDATE requests SET status = ? WHERE id = ?",
            ("completed", req_id),
        )

        # Insert result (same as what scraper will yield)
        await sql_manager.store_result(
            request_id=req_id,
            result_type="SampleData",
            data_json='{"title": "Test Item", "value": 100}',
            is_valid=True,
            validation_errors_json=None,
        )

        await db.commit()
        await db.close()

        async with LocalDevDriverDebugger.open(db_path) as debugger:
            result = await debugger.compare_continuation(req_id, TestScraper)

            # Outputs should be identical
            assert result.is_identical
            assert not result.has_changes
            assert result.data_diff.identical_pairs == 1
            assert len(result.data_diff.changed_pairs) == 0

    @pytest.mark.asyncio
    async def test_compare_continuation_with_data_changes(
        self, db_path: Path, initialized_db: aiosqlite.Connection
    ) -> None:
        """Test compare_continuation when new code yields different data."""
        from juriscraper.scraper_driver.common.data_models import ScrapedData
        from juriscraper.scraper_driver.data_types import (
            BaseScraper,
            NavigatingRequest,
            ParsedData,
            Response,
        )

        class SampleData(ScrapedData):
            title: str
            value: int

        class TestScraper(BaseScraper[SampleData]):
            def get_entry(self):
                yield NavigatingRequest(
                    request={"method": "GET", "url": "https://example.com"},
                    continuation="parse_index",
                )

            def parse_index(self, response: Response):
                # Yield different data than stored
                yield ParsedData(SampleData(title="Updated Item", value=200))

        db = initialized_db
        sql_manager = SQLManager(db)

        # Create a request
        req_id = await sql_manager.insert_request(
            priority=1,
            request_type="navigating",
            method="GET",
            url="https://example.com/index",
            headers_json="{}",
            cookies_json="{}",
            body=None,
            continuation="parse_index",
            current_location="https://example.com",
            accumulated_data_json="{}",
            aux_data_json="{}",
            permanent_json="{}",
            expected_type=None,
            dedup_key=None,
            parent_id=None,
        )

        # Create a response
        content = b"<html>Test</html>"
        compressed_content = compress(content)
        await sql_manager.store_response(
            request_id=req_id,
            status_code=200,
            headers_json='{"Content-Type": "text/html"}',
            url="https://example.com/index",
            compressed_content=compressed_content,
            content_size_original=len(content),
            content_size_compressed=len(compressed_content),
            dict_id=None,
            continuation="parse_index",
            warc_record_id=str(uuid.uuid4()),
            speculation_outcome=None,
        )

        # Mark request as completed
        await db.execute(
            "UPDATE requests SET status = ? WHERE id = ?",
            ("completed", req_id),
        )

        # Insert original result (different from what scraper will yield)
        await sql_manager.store_result(
            request_id=req_id,
            result_type="SampleData",
            data_json='{"title": "Test Item", "value": 100}',
            is_valid=True,
            validation_errors_json=None,
        )

        await db.commit()
        await db.close()

        async with LocalDevDriverDebugger.open(db_path) as debugger:
            result = await debugger.compare_continuation(req_id, TestScraper)

            # Should detect changes
            assert not result.is_identical
            assert result.has_changes
            assert result.data_diff.has_changes
            assert len(result.data_diff.changed_pairs) == 1

            # Check field-level diffs
            orig, new, field_diffs = result.data_diff.changed_pairs[0]
            assert "title" in field_diffs
            assert field_diffs["title"] == ("Test Item", "Updated Item")
            assert "value" in field_diffs
            assert field_diffs["value"] == (100, 200)

    @pytest.mark.asyncio
    async def test_compare_continuation_with_request_changes(
        self, db_path: Path, initialized_db: aiosqlite.Connection
    ) -> None:
        """Test compare_continuation when new code yields different child requests."""
        from juriscraper.scraper_driver.common.data_models import ScrapedData
        from juriscraper.scraper_driver.data_types import (
            BaseScraper,
            HttpMethod,
            HTTPRequestParams,
            NavigatingRequest,
            Response,
        )

        class SampleData(ScrapedData):
            title: str

        class TestScraper(BaseScraper[SampleData]):
            def get_entry(self):
                yield NavigatingRequest(
                    request=HTTPRequestParams(
                        method=HttpMethod.GET, url="https://example.com"
                    ),
                    continuation="parse_index",
                )

            def parse_index(self, response: Response):
                # Yield different child requests than originally stored
                yield NavigatingRequest(
                    request=HTTPRequestParams(
                        method=HttpMethod.GET,
                        url="https://example.com/new_page",
                    ),
                    continuation="parse_detail",
                )

        db = initialized_db
        sql_manager = SQLManager(db)

        # Create a parent request
        parent_id = await sql_manager.insert_request(
            priority=1,
            request_type="navigating",
            method="GET",
            url="https://example.com/index",
            headers_json="{}",
            cookies_json="{}",
            body=None,
            continuation="parse_index",
            current_location="https://example.com",
            accumulated_data_json="{}",
            aux_data_json="{}",
            permanent_json="{}",
            expected_type=None,
            dedup_key=None,
            parent_id=None,
        )

        # Create a response
        content = b"<html>Test</html>"
        compressed_content = compress(content)
        await sql_manager.store_response(
            request_id=parent_id,
            status_code=200,
            headers_json='{"Content-Type": "text/html"}',
            url="https://example.com/index",
            compressed_content=compressed_content,
            content_size_original=len(content),
            content_size_compressed=len(compressed_content),
            dict_id=None,
            continuation="parse_index",
            warc_record_id=str(uuid.uuid4()),
            speculation_outcome=None,
        )

        # Mark parent as completed
        await db.execute(
            "UPDATE requests SET status = ? WHERE id = ?",
            ("completed", parent_id),
        )

        # Create an ORIGINAL child request (different from what new code will yield)
        await sql_manager.insert_request(
            priority=1,
            request_type="navigating",
            method="GET",
            url="https://example.com/old_page",
            headers_json="{}",
            cookies_json="{}",
            body=None,
            continuation="parse_detail",
            current_location="https://example.com",
            accumulated_data_json="{}",
            aux_data_json="{}",
            permanent_json="{}",
            expected_type=None,
            dedup_key=None,
            parent_id=parent_id,
        )

        await db.commit()
        await db.close()

        async with LocalDevDriverDebugger.open(db_path) as debugger:
            result = await debugger.compare_continuation(
                parent_id, TestScraper
            )

            # Should detect request tree changes
            assert not result.is_identical
            assert result.has_changes
            assert result.request_diff.has_changes

            # Should have one removed (old_page) and one added (new_page)
            assert len(result.request_diff.removed) == 1
            assert (
                result.request_diff.removed[0].url
                == "https://example.com/old_page"
            )
            assert len(result.request_diff.added) == 1
            assert (
                result.request_diff.added[0].url
                == "https://example.com/new_page"
            )

    @pytest.mark.asyncio
    async def test_compare_continuation_with_error(
        self, db_path: Path, initialized_db: aiosqlite.Connection
    ) -> None:
        """Test compare_continuation when new code raises an error."""
        from juriscraper.scraper_driver.common.data_models import ScrapedData
        from juriscraper.scraper_driver.data_types import (
            BaseScraper,
            NavigatingRequest,
            Response,
        )

        class SampleData(ScrapedData):
            title: str

        class TestScraper(BaseScraper[SampleData]):
            def get_entry(self):
                yield NavigatingRequest(
                    request={"method": "GET", "url": "https://example.com"},
                    continuation="parse_index",
                )

            def parse_index(self, response: Response):
                # Raise an error
                raise ValueError("Test error from new code")

        db = initialized_db
        sql_manager = SQLManager(db)

        # Create a request
        req_id = await sql_manager.insert_request(
            priority=1,
            request_type="navigating",
            method="GET",
            url="https://example.com/index",
            headers_json="{}",
            cookies_json="{}",
            body=None,
            continuation="parse_index",
            current_location="https://example.com",
            accumulated_data_json="{}",
            aux_data_json="{}",
            permanent_json="{}",
            expected_type=None,
            dedup_key=None,
            parent_id=None,
        )

        # Create a response
        content = b"<html>Test</html>"
        compressed_content = compress(content)
        await sql_manager.store_response(
            request_id=req_id,
            status_code=200,
            headers_json='{"Content-Type": "text/html"}',
            url="https://example.com/index",
            compressed_content=compressed_content,
            content_size_original=len(content),
            content_size_compressed=len(compressed_content),
            dict_id=None,
            continuation="parse_index",
            warc_record_id=str(uuid.uuid4()),
            speculation_outcome=None,
        )

        # Mark request as completed (original execution succeeded)
        await db.execute(
            "UPDATE requests SET status = ? WHERE id = ?",
            ("completed", req_id),
        )

        await db.commit()
        await db.close()

        async with LocalDevDriverDebugger.open(db_path) as debugger:
            result = await debugger.compare_continuation(req_id, TestScraper)

            # Should detect error introduced
            assert not result.is_identical
            assert result.has_changes
            assert result.error_diff.has_change
            assert result.error_diff.status == "introduced"
            assert result.error_diff.new_error.error_type == "ValueError"
            assert (
                "Test error from new code"
                in result.error_diff.new_error.error_message
            )

    @pytest.mark.asyncio
    async def test_compare_continuation_missing_response(
        self, db_path: Path, initialized_db: aiosqlite.Connection
    ) -> None:
        """Test compare_continuation raises error when response is missing."""
        from juriscraper.scraper_driver.common.data_models import ScrapedData
        from juriscraper.scraper_driver.data_types import BaseScraper

        class SampleData(ScrapedData):
            title: str

        class TestScraper(BaseScraper[SampleData]):
            def get_entry(self):
                pass

        db = initialized_db
        sql_manager = SQLManager(db)

        # Create a request WITHOUT a response
        req_id = await sql_manager.insert_request(
            priority=1,
            request_type="navigating",
            method="GET",
            url="https://example.com/index",
            headers_json="{}",
            cookies_json="{}",
            body=None,
            continuation="parse_index",
            current_location="https://example.com",
            accumulated_data_json="{}",
            aux_data_json="{}",
            permanent_json="{}",
            expected_type=None,
            dedup_key=None,
            parent_id=None,
        )

        await db.commit()
        await db.close()

        async with LocalDevDriverDebugger.open(db_path) as debugger:
            # Should raise error for missing response
            with pytest.raises(ValueError, match="No response found"):
                await debugger.compare_continuation(req_id, TestScraper)


class TestIntegrityChecks:
    """Tests for integrity check methods."""

    async def test_check_integrity_no_issues(
        self, db_path: Path, initialized_db: aiosqlite.Connection
    ) -> None:
        """Test check_integrity when database has no issues."""
        db = initialized_db
        sql_manager = SQLManager(db)

        # Create a request with matching response (no orphans)
        req_id = await sql_manager.insert_request(
            priority=1,
            request_type="navigating",
            method="GET",
            url="https://example.com/test",
            headers_json="{}",
            cookies_json="{}",
            body=None,
            continuation="step1",
            current_location="",
            accumulated_data_json="{}",
            aux_data_json="{}",
            permanent_json="{}",
            expected_type=None,
            dedup_key=None,
            parent_id=None,
        )

        # Mark as completed
        await db.execute(
            "UPDATE requests SET status = ? WHERE id = ?",
            ("completed", req_id),
        )

        # Add matching response
        content = b"<html>Test</html>"
        compressed_content = compress(content)
        await sql_manager.store_response(
            request_id=req_id,
            status_code=200,
            headers_json="{}",
            url="https://example.com/test",
            compressed_content=compressed_content,
            content_size_original=len(content),
            content_size_compressed=len(compressed_content),
            dict_id=None,
            continuation="step1",
            warc_record_id=str(uuid.uuid4()),
            speculation_outcome=None,
        )

        await db.commit()
        await db.close()

        async with LocalDevDriverDebugger.open(db_path) as debugger:
            result = await debugger.check_integrity()

            assert result["has_issues"] is False
            assert result["orphaned_requests"]["count"] == 0
            assert result["orphaned_responses"]["count"] == 0

    async def test_check_integrity_orphaned_request(
        self, db_path: Path, initialized_db: aiosqlite.Connection
    ) -> None:
        """Test check_integrity detects orphaned requests."""
        db = initialized_db
        sql_manager = SQLManager(db)

        # Create a completed request WITHOUT a response
        req_id = await sql_manager.insert_request(
            priority=1,
            request_type="navigating",
            method="GET",
            url="https://example.com/orphan",
            headers_json="{}",
            cookies_json="{}",
            body=None,
            continuation="step1",
            current_location="",
            accumulated_data_json="{}",
            aux_data_json="{}",
            permanent_json="{}",
            expected_type=None,
            dedup_key=None,
            parent_id=None,
        )

        # Mark as completed (but no response exists)
        await db.execute(
            "UPDATE requests SET status = ? WHERE id = ?",
            ("completed", req_id),
        )

        await db.commit()
        await db.close()

        async with LocalDevDriverDebugger.open(db_path) as debugger:
            result = await debugger.check_integrity()

            assert result["has_issues"] is True
            assert result["orphaned_requests"]["count"] == 1
            assert req_id in result["orphaned_requests"]["ids"]
            assert result["orphaned_responses"]["count"] == 0

    async def test_check_integrity_orphaned_response(
        self, db_path: Path, initialized_db: aiosqlite.Connection
    ) -> None:
        """Test check_integrity detects orphaned responses."""
        db = initialized_db

        # Insert a response WITHOUT a matching request
        # (We'll temporarily disable foreign keys to allow this)
        content = b"<html>Orphan</html>"
        compressed_content = compress(content)

        await db.execute("PRAGMA foreign_keys = OFF")
        await db.execute(
            """
            INSERT INTO responses (
                request_id, status_code, headers_json, url,
                content_compressed, content_size_original,
                content_size_compressed, compression_dict_id, continuation,
                warc_record_id, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
            """,
            (
                9999,  # Non-existent request ID
                200,
                "{}",
                "https://example.com/orphan",
                compressed_content,
                len(content),
                len(compressed_content),
                None,
                "step1",
                str(uuid.uuid4()),
            ),
        )
        await db.execute("PRAGMA foreign_keys = ON")

        await db.commit()
        await db.close()

        async with LocalDevDriverDebugger.open(db_path) as debugger:
            result = await debugger.check_integrity()

            assert result["has_issues"] is True
            assert result["orphaned_requests"]["count"] == 0
            assert result["orphaned_responses"]["count"] == 1
            # Response ID should be 1 (first response in the table)
            assert 1 in result["orphaned_responses"]["ids"]

    async def test_check_integrity_multiple_issues(
        self, db_path: Path, initialized_db: aiosqlite.Connection
    ) -> None:
        """Test check_integrity detects multiple types of issues."""
        db = initialized_db
        sql_manager = SQLManager(db)

        # Create orphaned request
        orphan_req_id = await sql_manager.insert_request(
            priority=1,
            request_type="navigating",
            method="GET",
            url="https://example.com/orphan_req",
            headers_json="{}",
            cookies_json="{}",
            body=None,
            continuation="step1",
            current_location="",
            accumulated_data_json="{}",
            aux_data_json="{}",
            permanent_json="{}",
            expected_type=None,
            dedup_key=None,
            parent_id=None,
        )
        await db.execute(
            "UPDATE requests SET status = ? WHERE id = ?",
            ("completed", orphan_req_id),
        )

        # Create orphaned response (non-existent request)
        await db.commit()  # Commit orphaned request first
        content = b"<html>Orphan Response</html>"
        compressed_content = compress(content)
        await db.execute("PRAGMA foreign_keys = OFF")
        await db.execute(
            """
            INSERT INTO responses (
                request_id, status_code, headers_json, url,
                content_compressed, content_size_original,
                content_size_compressed, compression_dict_id, continuation,
                warc_record_id, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
            """,
            (
                9999,
                200,
                "{}",
                "https://example.com/orphan_resp",
                compressed_content,
                len(content),
                len(compressed_content),
                None,
                "step2",
                str(uuid.uuid4()),
            ),
        )
        await db.execute("PRAGMA foreign_keys = ON")

        await db.commit()
        await db.close()

        async with LocalDevDriverDebugger.open(db_path) as debugger:
            result = await debugger.check_integrity()

            assert result["has_issues"] is True
            assert result["orphaned_requests"]["count"] == 1
            assert result["orphaned_responses"]["count"] == 1

    async def test_get_orphan_details_no_orphans(
        self, db_path: Path, initialized_db: aiosqlite.Connection
    ) -> None:
        """Test get_orphan_details when there are no orphans."""
        await initialized_db.close()

        async with LocalDevDriverDebugger.open(db_path) as debugger:
            result = await debugger.get_orphan_details()

            assert len(result["orphaned_requests"]) == 0
            assert len(result["orphaned_responses"]) == 0

    async def test_get_orphan_details_with_orphaned_request(
        self, db_path: Path, initialized_db: aiosqlite.Connection
    ) -> None:
        """Test get_orphan_details includes request details."""
        db = initialized_db
        sql_manager = SQLManager(db)

        # Create orphaned request
        req_id = await sql_manager.insert_request(
            priority=1,
            request_type="navigating",
            method="GET",
            url="https://example.com/orphan",
            headers_json="{}",
            cookies_json="{}",
            body=None,
            continuation="step1",
            current_location="",
            accumulated_data_json="{}",
            aux_data_json="{}",
            permanent_json="{}",
            expected_type=None,
            dedup_key=None,
            parent_id=None,
        )
        await db.execute(
            "UPDATE requests SET status = ? WHERE id = ?",
            ("completed", req_id),
        )

        await db.commit()
        await db.close()

        async with LocalDevDriverDebugger.open(db_path) as debugger:
            result = await debugger.get_orphan_details()

            assert len(result["orphaned_requests"]) == 1
            req = result["orphaned_requests"][0]
            assert req["id"] == req_id
            assert req["url"] == "https://example.com/orphan"
            assert req["continuation"] == "step1"

    async def test_get_orphan_details_with_orphaned_response(
        self, db_path: Path, initialized_db: aiosqlite.Connection
    ) -> None:
        """Test get_orphan_details includes response details."""
        db = initialized_db

        # Create orphaned response
        content = b"<html>Orphan</html>"
        compressed_content = compress(content)
        await db.execute("PRAGMA foreign_keys = OFF")
        await db.execute(
            """
            INSERT INTO responses (
                request_id, status_code, headers_json, url,
                content_compressed, content_size_original,
                content_size_compressed, compression_dict_id, continuation,
                warc_record_id, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
            """,
            (
                9999,
                404,
                "{}",
                "https://example.com/orphan_response",
                compressed_content,
                len(content),
                len(compressed_content),
                None,
                "step2",
                str(uuid.uuid4()),
            ),
        )
        await db.execute("PRAGMA foreign_keys = ON")

        await db.commit()
        await db.close()

        async with LocalDevDriverDebugger.open(db_path) as debugger:
            result = await debugger.get_orphan_details()

            assert len(result["orphaned_responses"]) == 1
            resp = result["orphaned_responses"][0]
            assert resp["id"] == 1
            assert resp["url"] == "https://example.com/orphan_response"


class TestGhostRequestDetection:
    """Tests for ghost request detection methods."""

    async def test_get_ghost_requests_no_ghosts(
        self, db_path: Path, initialized_db: aiosqlite.Connection
    ) -> None:
        """Test get_ghost_requests when there are no ghost requests."""
        db = initialized_db
        sql_manager = SQLManager(db)

        # Create a completed request with a result (not a ghost)
        req_id = await sql_manager.insert_request(
            priority=1,
            request_type="navigating",
            method="GET",
            url="https://example.com/test",
            headers_json="{}",
            cookies_json="{}",
            body=None,
            continuation="step1",
            current_location="",
            accumulated_data_json="{}",
            aux_data_json="{}",
            permanent_json="{}",
            expected_type=None,
            dedup_key=None,
            parent_id=None,
        )

        # Mark as completed
        await db.execute(
            "UPDATE requests SET status = ? WHERE id = ?",
            ("completed", req_id),
        )

        # Add a result (prevents it from being a ghost)
        await sql_manager.store_result(
            request_id=req_id,
            result_type="TestData",
            data_json='{"test": "data"}',
            is_valid=True,
        )

        await db.commit()
        await db.close()

        async with LocalDevDriverDebugger.open(db_path) as debugger:
            result = await debugger.get_ghost_requests()

            assert result["total_count"] == 0
            assert len(result["by_continuation"]) == 0
            assert len(result["ghosts"]) == 0

    async def test_get_ghost_requests_detects_ghost(
        self, db_path: Path, initialized_db: aiosqlite.Connection
    ) -> None:
        """Test get_ghost_requests detects a ghost request."""
        db = initialized_db
        sql_manager = SQLManager(db)

        # Create a completed request with NO children and NO results (ghost)
        ghost_id = await sql_manager.insert_request(
            priority=1,
            request_type="navigating",
            method="GET",
            url="https://example.com/ghost",
            headers_json="{}",
            cookies_json="{}",
            body=None,
            continuation="parse_index",
            current_location="",
            accumulated_data_json="{}",
            aux_data_json="{}",
            permanent_json="{}",
            expected_type=None,
            dedup_key=None,
            parent_id=None,
        )

        # Mark as completed
        await db.execute(
            "UPDATE requests SET status = ? WHERE id = ?",
            ("completed", ghost_id),
        )

        await db.commit()
        await db.close()

        async with LocalDevDriverDebugger.open(db_path) as debugger:
            result = await debugger.get_ghost_requests()

            assert result["total_count"] == 1
            assert "parse_index" in result["by_continuation"]
            assert result["by_continuation"]["parse_index"] == 1
            assert len(result["ghosts"]) == 1
            assert result["ghosts"][0]["id"] == ghost_id
            assert result["ghosts"][0]["url"] == "https://example.com/ghost"
            assert result["ghosts"][0]["continuation"] == "parse_index"

    async def test_get_ghost_requests_not_ghost_with_children(
        self, db_path: Path, initialized_db: aiosqlite.Connection
    ) -> None:
        """Test that requests with children are not ghosts."""
        db = initialized_db
        sql_manager = SQLManager(db)

        # Create a parent request
        parent_id = await sql_manager.insert_request(
            priority=1,
            request_type="navigating",
            method="GET",
            url="https://example.com/parent",
            headers_json="{}",
            cookies_json="{}",
            body=None,
            continuation="step1",
            current_location="",
            accumulated_data_json="{}",
            aux_data_json="{}",
            permanent_json="{}",
            expected_type=None,
            dedup_key=None,
            parent_id=None,
        )

        # Mark as completed
        await db.execute(
            "UPDATE requests SET status = ? WHERE id = ?",
            ("completed", parent_id),
        )

        # Create a child request
        await sql_manager.insert_request(
            priority=1,
            request_type="navigating",
            method="GET",
            url="https://example.com/child",
            headers_json="{}",
            cookies_json="{}",
            body=None,
            continuation="step2",
            current_location="",
            accumulated_data_json="{}",
            aux_data_json="{}",
            permanent_json="{}",
            expected_type=None,
            dedup_key=None,
            parent_id=parent_id,
        )

        await db.commit()
        await db.close()

        async with LocalDevDriverDebugger.open(db_path) as debugger:
            result = await debugger.get_ghost_requests()

            # Parent should not be a ghost (has children)
            assert result["total_count"] == 0

    async def test_get_ghost_requests_not_ghost_with_results(
        self, db_path: Path, initialized_db: aiosqlite.Connection
    ) -> None:
        """Test that requests with results are not ghosts."""
        db = initialized_db
        sql_manager = SQLManager(db)

        # Create a request
        req_id = await sql_manager.insert_request(
            priority=1,
            request_type="navigating",
            method="GET",
            url="https://example.com/test",
            headers_json="{}",
            cookies_json="{}",
            body=None,
            continuation="step1",
            current_location="",
            accumulated_data_json="{}",
            aux_data_json="{}",
            permanent_json="{}",
            expected_type=None,
            dedup_key=None,
            parent_id=None,
        )

        # Mark as completed
        await db.execute(
            "UPDATE requests SET status = ? WHERE id = ?",
            ("completed", req_id),
        )

        # Add a result (prevents it from being a ghost)
        await sql_manager.store_result(
            request_id=req_id,
            result_type="TestData",
            data_json='{"test": "data"}',
            is_valid=True,
        )

        await db.commit()
        await db.close()

        async with LocalDevDriverDebugger.open(db_path) as debugger:
            result = await debugger.get_ghost_requests()

            # Should not be a ghost (has results)
            assert result["total_count"] == 0

    async def test_get_ghost_requests_multiple_continuations(
        self, db_path: Path, initialized_db: aiosqlite.Connection
    ) -> None:
        """Test get_ghost_requests groups by continuation."""
        db = initialized_db
        sql_manager = SQLManager(db)

        # Create ghost requests in different continuations
        ghost_ids = []
        for i in range(3):
            continuation = "step1" if i < 2 else "step2"
            ghost_id = await sql_manager.insert_request(
                priority=1,
                request_type="navigating",
                method="GET",
                url=f"https://example.com/ghost{i}",
                headers_json="{}",
                cookies_json="{}",
                body=None,
                continuation=continuation,
                current_location="",
                accumulated_data_json="{}",
                aux_data_json="{}",
                permanent_json="{}",
                expected_type=None,
                dedup_key=None,
                parent_id=None,
            )
            await db.execute(
                "UPDATE requests SET status = ? WHERE id = ?",
                ("completed", ghost_id),
            )
            ghost_ids.append(ghost_id)

        await db.commit()
        await db.close()

        async with LocalDevDriverDebugger.open(db_path) as debugger:
            result = await debugger.get_ghost_requests()

            assert result["total_count"] == 3
            assert result["by_continuation"]["step1"] == 2
            assert result["by_continuation"]["step2"] == 1
            assert len(result["ghosts"]) == 3

    async def test_get_ghost_requests_pending_not_ghost(
        self, db_path: Path, initialized_db: aiosqlite.Connection
    ) -> None:
        """Test that pending requests are not considered ghosts."""
        db = initialized_db
        sql_manager = SQLManager(db)

        # Create a pending request (should not be a ghost)
        _req_id = await sql_manager.insert_request(
            priority=1,
            request_type="navigating",
            method="GET",
            url="https://example.com/pending",
            headers_json="{}",
            cookies_json="{}",
            body=None,
            continuation="step1",
            current_location="",
            accumulated_data_json="{}",
            aux_data_json="{}",
            permanent_json="{}",
            expected_type=None,
            dedup_key=None,
            parent_id=None,
        )

        # Leave as pending (default status)

        await db.commit()
        await db.close()

        async with LocalDevDriverDebugger.open(db_path) as debugger:
            result = await debugger.get_ghost_requests()

            # Pending requests should not be ghosts
            assert result["total_count"] == 0

    async def test_get_ghost_requests_failed_not_ghost(
        self, db_path: Path, initialized_db: aiosqlite.Connection
    ) -> None:
        """Test that failed requests are not considered ghosts."""
        db = initialized_db
        sql_manager = SQLManager(db)

        # Create a failed request
        req_id = await sql_manager.insert_request(
            priority=1,
            request_type="navigating",
            method="GET",
            url="https://example.com/failed",
            headers_json="{}",
            cookies_json="{}",
            body=None,
            continuation="step1",
            current_location="",
            accumulated_data_json="{}",
            aux_data_json="{}",
            permanent_json="{}",
            expected_type=None,
            dedup_key=None,
            parent_id=None,
        )

        # Mark as failed
        await db.execute(
            "UPDATE requests SET status = ? WHERE id = ?",
            ("failed", req_id),
        )

        await db.commit()
        await db.close()

        async with LocalDevDriverDebugger.open(db_path) as debugger:
            result = await debugger.get_ghost_requests()

            # Failed requests should not be ghosts
            assert result["total_count"] == 0


class TestSeedSpeculativeRequests:
    """Tests for seed_speculative_requests method."""

    async def test_seed_speculative_requests_creates_pending_requests(
        self, db_path: Path, initialized_db: aiosqlite.Connection
    ) -> None:
        """Test that seed_speculative_requests creates pending requests in the database."""
        from unittest.mock import MagicMock, patch

        from juriscraper.scraper_driver.common.decorators import entry
        from juriscraper.scraper_driver.data_types import (
            BaseScraper,
            HttpMethod,
            HTTPRequestParams,
            NavigatingRequest,
        )

        db = initialized_db
        sql_manager = SQLManager(db)

        # Create run metadata pointing to our test scraper
        await sql_manager.init_run_metadata(
            scraper_name="test_module.TestSpeculateScraper",
            scraper_version="1.0.0",
            num_workers=1,
            max_backoff_time=60.0,
        )

        await db.commit()
        await db.close()

        # Create a simple test scraper with a speculative @entry function
        class TestSpeculateScraper(BaseScraper):
            @entry(dict, speculative=True, highest_observed=100)
            def fetch_item(self, item_id: int) -> NavigatingRequest:
                return NavigatingRequest(
                    request=HTTPRequestParams(
                        method=HttpMethod.GET,
                        url=f"https://example.com/items/{item_id}",
                    ),
                    continuation="parse_item",
                )

        # Mock the registry
        mock_scraper_info = MagicMock()
        mock_scraper_info.module_path = "test_module.TestSpeculateScraper"
        mock_scraper_info.full_path = "test_module:TestSpeculateScraper"
        mock_scraper_info.class_name = "TestSpeculateScraper"

        mock_registry = MagicMock()
        mock_registry.list_scrapers.return_value = [mock_scraper_info]
        mock_registry.instantiate_scraper.return_value = TestSpeculateScraper()

        with patch(
            "juriscraper.scraper_driver.driver.dev_driver.web.scraper_registry.get_registry",
            return_value=mock_registry,
        ):
            async with LocalDevDriverDebugger.open(
                db_path, read_only=False
            ) as debugger:
                # Seed requests for IDs 1-5
                count = await debugger.seed_speculative_requests(
                    step_name="fetch_item",
                    from_id=1,
                    to_id=5,
                )

        assert count == 5

        # Verify requests are in the database
        async with LocalDevDriverDebugger.open(db_path) as debugger:
            page = await debugger.list_requests(status="pending")
            assert page.total == 5
            assert len(page.items) == 5

            # Check the URLs are correct
            urls = {r.url for r in page.items}
            expected_urls = {
                f"https://example.com/items/{i}" for i in range(1, 6)
            }
            assert urls == expected_urls

            # Verify continuation is set
            for r in page.items:
                assert r.continuation == "parse_item"

    async def test_seed_speculative_requests_requires_write_mode(
        self, db_path: Path, initialized_db: aiosqlite.Connection
    ) -> None:
        """Test that seed_speculative_requests fails in read-only mode."""
        db = initialized_db
        sql_manager = SQLManager(db)

        await sql_manager.init_run_metadata(
            scraper_name="test_module.TestScraper",
            scraper_version="1.0.0",
            num_workers=1,
            max_backoff_time=60.0,
        )
        await db.commit()
        await db.close()

        async with LocalDevDriverDebugger.open(
            db_path, read_only=True
        ) as debugger:
            with pytest.raises(PermissionError):
                await debugger.seed_speculative_requests(
                    step_name="fetch_item",
                    from_id=1,
                    to_id=5,
                )

    async def test_seed_speculative_requests_fails_for_non_speculate_function(
        self, db_path: Path, initialized_db: aiosqlite.Connection
    ) -> None:
        """Test that seed_speculative_requests fails for non-speculative functions."""
        from unittest.mock import MagicMock, patch

        from juriscraper.scraper_driver.data_types import (
            BaseScraper,
            HttpMethod,
            HTTPRequestParams,
            NavigatingRequest,
        )

        db = initialized_db
        sql_manager = SQLManager(db)

        await sql_manager.init_run_metadata(
            scraper_name="test_module.TestNonSpeculateScraper",
            scraper_version="1.0.0",
            num_workers=1,
            max_backoff_time=60.0,
        )
        await db.commit()
        await db.close()

        # Create a scraper without speculative @entry decorator
        class TestNonSpeculateScraper(BaseScraper):
            def fetch_item(self, item_id: int) -> NavigatingRequest:
                return NavigatingRequest(
                    request=HTTPRequestParams(
                        method=HttpMethod.GET,
                        url=f"https://example.com/items/{item_id}",
                    ),
                    continuation="parse_item",
                )

        mock_scraper_info = MagicMock()
        mock_scraper_info.module_path = "test_module.TestNonSpeculateScraper"
        mock_scraper_info.full_path = "test_module:TestNonSpeculateScraper"
        mock_scraper_info.class_name = "TestNonSpeculateScraper"

        mock_registry = MagicMock()
        mock_registry.list_scrapers.return_value = [mock_scraper_info]
        mock_registry.instantiate_scraper.return_value = (
            TestNonSpeculateScraper()
        )

        with patch(
            "juriscraper.scraper_driver.driver.dev_driver.web.scraper_registry.get_registry",
            return_value=mock_registry,
        ):
            async with LocalDevDriverDebugger.open(
                db_path, read_only=False
            ) as debugger:
                with pytest.raises(
                    ValueError, match="is not a speculative entry function"
                ):
                    await debugger.seed_speculative_requests(
                        step_name="fetch_item",
                        from_id=1,
                        to_id=5,
                    )

    async def test_seed_speculative_requests_fails_for_nonexistent_step(
        self, db_path: Path, initialized_db: aiosqlite.Connection
    ) -> None:
        """Test that seed_speculative_requests fails when step doesn't exist."""
        from unittest.mock import MagicMock, patch

        from juriscraper.scraper_driver.data_types import BaseScraper

        db = initialized_db
        sql_manager = SQLManager(db)

        await sql_manager.init_run_metadata(
            scraper_name="test_module.TestEmptyScraper",
            scraper_version="1.0.0",
            num_workers=1,
            max_backoff_time=60.0,
        )
        await db.commit()
        await db.close()

        class TestEmptyScraper(BaseScraper):
            pass

        mock_scraper_info = MagicMock()
        mock_scraper_info.module_path = "test_module.TestEmptyScraper"
        mock_scraper_info.full_path = "test_module:TestEmptyScraper"
        mock_scraper_info.class_name = "TestEmptyScraper"

        mock_registry = MagicMock()
        mock_registry.list_scrapers.return_value = [mock_scraper_info]
        mock_registry.instantiate_scraper.return_value = TestEmptyScraper()

        with patch(
            "juriscraper.scraper_driver.driver.dev_driver.web.scraper_registry.get_registry",
            return_value=mock_registry,
        ):
            async with LocalDevDriverDebugger.open(
                db_path, read_only=False
            ) as debugger:
                with pytest.raises(ValueError, match="not found on scraper"):
                    await debugger.seed_speculative_requests(
                        step_name="nonexistent_step",
                        from_id=1,
                        to_id=5,
                    )

    async def test_seed_speculative_requests_fails_for_unknown_scraper(
        self, db_path: Path, initialized_db: aiosqlite.Connection
    ) -> None:
        """Test that seed_speculative_requests fails when scraper not in registry."""
        from unittest.mock import MagicMock, patch

        db = initialized_db
        sql_manager = SQLManager(db)

        await sql_manager.init_run_metadata(
            scraper_name="unknown_module.UnknownScraper",
            scraper_version="1.0.0",
            num_workers=1,
            max_backoff_time=60.0,
        )
        await db.commit()
        await db.close()

        mock_registry = MagicMock()
        mock_registry.list_scrapers.return_value = []  # No scrapers registered

        with patch(
            "juriscraper.scraper_driver.driver.dev_driver.web.scraper_registry.get_registry",
            return_value=mock_registry,
        ):
            async with LocalDevDriverDebugger.open(
                db_path, read_only=False
            ) as debugger:
                with pytest.raises(ValueError, match="not found in registry"):
                    await debugger.seed_speculative_requests(
                        step_name="fetch_item",
                        from_id=1,
                        to_id=5,
                    )
