"""Tests for SQLManager database operations.

These tests verify the SQLManager class which provides standalone database
operations for the LocalDevDriver. Testing is done without a full driver
instance, enabling focused testing of database functionality.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import aiosqlite
import pytest

from juriscraper.scraper_driver.driver.dev_driver.compression import compress
from juriscraper.scraper_driver.driver.dev_driver.schema import init_database
from juriscraper.scraper_driver.driver.dev_driver.sql_manager import (
    Page,
    RequestRecord,
    ResponseRecord,
    ResultRecord,
    SQLManager,
)


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
async def sql_manager(initialized_db: aiosqlite.Connection) -> SQLManager:
    """Create a SQLManager instance."""
    return SQLManager(initialized_db)


class TestSQLManagerContext:
    """Tests for SQLManager context manager and initialization."""

    async def test_open_context_manager(self, db_path: Path) -> None:
        """Test SQLManager.open context manager creates and closes properly."""
        async with SQLManager.open(db_path) as manager:
            assert manager.db is not None
            # Can perform operations
            stats = await manager.get_stats()
            assert stats is not None

    async def test_db_property(self, sql_manager: SQLManager) -> None:
        """Test db property returns the connection."""
        assert sql_manager.db is not None
        assert isinstance(sql_manager.db, aiosqlite.Connection)


class TestRunMetadata:
    """Tests for run metadata operations."""

    async def test_init_run_metadata_new(
        self, sql_manager: SQLManager
    ) -> None:
        """Test initializing new run metadata."""
        await sql_manager.init_run_metadata(
            scraper_name="TestScraper",
            scraper_version="1.0.0",
            num_workers=2,
            max_backoff_time=60.0,
        )

        # Verify metadata was created
        cursor = await sql_manager.db.execute(
            "SELECT scraper_name, num_workers FROM run_metadata WHERE id = 1"
        )
        row = await cursor.fetchone()
        assert row is not None
        assert row[0] == "TestScraper"
        assert row[1] == 2

    async def test_init_run_metadata_idempotent(
        self, sql_manager: SQLManager
    ) -> None:
        """Test init_run_metadata doesn't create duplicates."""
        await sql_manager.init_run_metadata(
            scraper_name="TestScraper",
            scraper_version="1.0.0",
            num_workers=2,
            max_backoff_time=60.0,
        )

        # Call again - should not create duplicate
        await sql_manager.init_run_metadata(
            scraper_name="DifferentScraper",
            scraper_version="2.0.0",
            num_workers=4,
            max_backoff_time=120.0,
        )

        cursor = await sql_manager.db.execute(
            "SELECT COUNT(*) FROM run_metadata"
        )
        row = await cursor.fetchone()
        assert row[0] == 1

    async def test_update_run_status(self, sql_manager: SQLManager) -> None:
        """Test updating run status."""
        await sql_manager.init_run_metadata(
            scraper_name="TestScraper",
            scraper_version="1.0.0",
            num_workers=2,
            max_backoff_time=60.0,
        )

        await sql_manager.update_run_status("running")

        cursor = await sql_manager.db.execute(
            "SELECT status FROM run_metadata WHERE id = 1"
        )
        row = await cursor.fetchone()
        assert row[0] == "running"


class TestRequestOperations:
    """Tests for request queue operations."""

    async def test_insert_request(self, sql_manager: SQLManager) -> None:
        """Test inserting a new request."""
        request_id = await sql_manager.insert_request(
            priority=5,
            request_type="navigating",
            method="GET",
            url="https://example.com/page",
            headers_json=json.dumps({"Accept": "text/html"}),
            cookies_json=None,
            body=None,
            continuation="parse",
            current_location="https://example.com",
            accumulated_data_json=None,
            aux_data_json=None,
            permanent_json=None,
            expected_type=None,
            dedup_key="GET:https://example.com/page",
            parent_id=None,
        )

        assert request_id > 0

        # Verify request was inserted
        cursor = await sql_manager.db.execute(
            "SELECT url, method, status FROM requests WHERE id = ?",
            (request_id,),
        )
        row = await cursor.fetchone()
        assert row is not None
        assert row[0] == "https://example.com/page"
        assert row[1] == "GET"
        assert row[2] == "pending"

    async def test_check_dedup_key_exists(
        self, sql_manager: SQLManager
    ) -> None:
        """Test deduplication key checking."""
        dedup_key = "GET:https://example.com/unique"

        # Should not exist initially
        assert not await sql_manager.check_dedup_key_exists(dedup_key)

        # Insert request with dedup key
        await sql_manager.insert_request(
            priority=5,
            request_type="navigating",
            method="GET",
            url="https://example.com/unique",
            headers_json=None,
            cookies_json=None,
            body=None,
            continuation="parse",
            current_location="",
            accumulated_data_json=None,
            aux_data_json=None,
            permanent_json=None,
            expected_type=None,
            dedup_key=dedup_key,
            parent_id=None,
        )

        # Should exist now
        assert await sql_manager.check_dedup_key_exists(dedup_key)

    async def test_get_next_pending_request(
        self, sql_manager: SQLManager
    ) -> None:
        """Test getting next pending request from queue."""
        # Insert requests with different priorities
        await sql_manager.insert_request(
            priority=10,  # Lower priority (higher number)
            request_type="navigating",
            method="GET",
            url="https://example.com/low-priority",
            headers_json=None,
            cookies_json=None,
            body=None,
            continuation="parse",
            current_location="",
            accumulated_data_json=None,
            aux_data_json=None,
            permanent_json=None,
            expected_type=None,
            dedup_key="low",
            parent_id=None,
        )

        await sql_manager.insert_request(
            priority=1,  # Higher priority (lower number)
            request_type="navigating",
            method="GET",
            url="https://example.com/high-priority",
            headers_json=None,
            cookies_json=None,
            body=None,
            continuation="parse",
            current_location="",
            accumulated_data_json=None,
            aux_data_json=None,
            permanent_json=None,
            expected_type=None,
            dedup_key="high",
            parent_id=None,
        )

        row = await sql_manager.get_next_pending_request()

        assert row is not None
        # Should get high priority request first (priority=1)
        # Column order: id, request_type, method, url, headers_json, ...
        assert row[3] == "https://example.com/high-priority"

    async def test_mark_request_in_progress(
        self, sql_manager: SQLManager
    ) -> None:
        """Test marking a request as in progress."""
        request_id = await sql_manager.insert_request(
            priority=5,
            request_type="navigating",
            method="GET",
            url="https://example.com/test",
            headers_json=None,
            cookies_json=None,
            body=None,
            continuation="parse",
            current_location="",
            accumulated_data_json=None,
            aux_data_json=None,
            permanent_json=None,
            expected_type=None,
            dedup_key=None,
            parent_id=None,
        )

        await sql_manager.mark_request_in_progress(request_id)

        cursor = await sql_manager.db.execute(
            "SELECT status, started_at FROM requests WHERE id = ?",
            (request_id,),
        )
        row = await cursor.fetchone()
        assert row[0] == "in_progress"
        assert row[1] is not None  # started_at should be set

    async def test_mark_request_completed(
        self, sql_manager: SQLManager
    ) -> None:
        """Test marking a request as completed."""
        request_id = await sql_manager.insert_request(
            priority=5,
            request_type="navigating",
            method="GET",
            url="https://example.com/test",
            headers_json=None,
            cookies_json=None,
            body=None,
            continuation="parse",
            current_location="",
            accumulated_data_json=None,
            aux_data_json=None,
            permanent_json=None,
            expected_type=None,
            dedup_key=None,
            parent_id=None,
        )

        await sql_manager.mark_request_in_progress(request_id)
        await sql_manager.mark_request_completed(request_id)

        cursor = await sql_manager.db.execute(
            "SELECT status, completed_at FROM requests WHERE id = ?",
            (request_id,),
        )
        row = await cursor.fetchone()
        assert row[0] == "completed"
        assert row[1] is not None  # completed_at should be set

    async def test_mark_request_failed(self, sql_manager: SQLManager) -> None:
        """Test marking a request as failed."""
        request_id = await sql_manager.insert_request(
            priority=5,
            request_type="navigating",
            method="GET",
            url="https://example.com/test",
            headers_json=None,
            cookies_json=None,
            body=None,
            continuation="parse",
            current_location="",
            accumulated_data_json=None,
            aux_data_json=None,
            permanent_json=None,
            expected_type=None,
            dedup_key=None,
            parent_id=None,
        )

        await sql_manager.mark_request_failed(request_id, "Test error")

        cursor = await sql_manager.db.execute(
            "SELECT status, last_error FROM requests WHERE id = ?",
            (request_id,),
        )
        row = await cursor.fetchone()
        assert row[0] == "failed"
        assert row[1] == "Test error"

    async def test_restore_queue(self, sql_manager: SQLManager) -> None:
        """Test restore_queue resets in_progress to pending."""
        # Insert and mark a request as in_progress
        request_id = await sql_manager.insert_request(
            priority=5,
            request_type="navigating",
            method="GET",
            url="https://example.com/test",
            headers_json=None,
            cookies_json=None,
            body=None,
            continuation="parse",
            current_location="",
            accumulated_data_json=None,
            aux_data_json=None,
            permanent_json=None,
            expected_type=None,
            dedup_key=None,
            parent_id=None,
        )
        await sql_manager.mark_request_in_progress(request_id)

        # Verify it's in_progress
        cursor = await sql_manager.db.execute(
            "SELECT status FROM requests WHERE id = ?", (request_id,)
        )
        row = await cursor.fetchone()
        assert row[0] == "in_progress"

        # Restore queue
        count = await sql_manager.restore_queue()

        # Should be back to pending
        cursor = await sql_manager.db.execute(
            "SELECT status FROM requests WHERE id = ?", (request_id,)
        )
        row = await cursor.fetchone()
        assert row[0] == "pending"
        assert count == 1

    async def test_count_methods(self, sql_manager: SQLManager) -> None:
        """Test various count methods."""
        # Initially empty
        assert await sql_manager.count_pending_requests() == 0
        assert await sql_manager.count_active_requests() == 0
        assert await sql_manager.count_all_requests() == 0

        # Insert pending request
        req1 = await sql_manager.insert_request(
            priority=5,
            request_type="navigating",
            method="GET",
            url="https://example.com/1",
            headers_json=None,
            cookies_json=None,
            body=None,
            continuation="parse",
            current_location="",
            accumulated_data_json=None,
            aux_data_json=None,
            permanent_json=None,
            expected_type=None,
            dedup_key="1",
            parent_id=None,
        )

        assert await sql_manager.count_pending_requests() == 1
        assert await sql_manager.count_active_requests() == 1

        # Mark in progress
        await sql_manager.mark_request_in_progress(req1)

        assert await sql_manager.count_pending_requests() == 0
        assert await sql_manager.count_active_requests() == 1

        # Mark completed
        await sql_manager.mark_request_completed(req1)

        assert await sql_manager.count_pending_requests() == 0
        assert await sql_manager.count_active_requests() == 0
        assert await sql_manager.count_all_requests() == 1


class TestResponseStorage:
    """Tests for response storage operations."""

    async def test_store_response(self, sql_manager: SQLManager) -> None:
        """Test storing an HTTP response."""
        # First create a request
        request_id = await sql_manager.insert_request(
            priority=5,
            request_type="navigating",
            method="GET",
            url="https://example.com/test",
            headers_json=None,
            cookies_json=None,
            body=None,
            continuation="parse",
            current_location="",
            accumulated_data_json=None,
            aux_data_json=None,
            permanent_json=None,
            expected_type=None,
            dedup_key=None,
            parent_id=None,
        )

        content = b"<html>Test content</html>"
        compressed = compress(content)

        response_id = await sql_manager.store_response(
            request_id=request_id,
            status_code=200,
            headers_json=json.dumps({"Content-Type": "text/html"}),
            url="https://example.com/test",
            compressed_content=compressed,
            content_size_original=len(content),
            content_size_compressed=len(compressed),
            dict_id=None,
            continuation="parse",
            warc_record_id=str(uuid.uuid4()),
        )

        assert response_id > 0

        # Verify response was stored
        cursor = await sql_manager.db.execute(
            "SELECT status_code, content_size_original FROM responses WHERE id = ?",
            (response_id,),
        )
        row = await cursor.fetchone()
        assert row is not None
        assert row[0] == 200
        assert row[1] == len(content)

    async def test_get_response_content(self, sql_manager: SQLManager) -> None:
        """Test retrieving decompressed response content."""
        request_id = await sql_manager.insert_request(
            priority=5,
            request_type="navigating",
            method="GET",
            url="https://example.com/test",
            headers_json=None,
            cookies_json=None,
            body=None,
            continuation="parse",
            current_location="",
            accumulated_data_json=None,
            aux_data_json=None,
            permanent_json=None,
            expected_type=None,
            dedup_key=None,
            parent_id=None,
        )

        content = b"<html>Test content for retrieval</html>"
        compressed = compress(content)

        response_id = await sql_manager.store_response(
            request_id=request_id,
            status_code=200,
            headers_json=None,
            url="https://example.com/test",
            compressed_content=compressed,
            content_size_original=len(content),
            content_size_compressed=len(compressed),
            dict_id=None,
            continuation="parse",
            warc_record_id=str(uuid.uuid4()),
        )

        # Retrieve content
        retrieved = await sql_manager.get_response_content(response_id)

        assert retrieved == content

    async def test_get_response_content_empty(
        self, sql_manager: SQLManager
    ) -> None:
        """Test retrieving empty response content (headers only)."""
        request_id = await sql_manager.insert_request(
            priority=5,
            request_type="navigating",
            method="HEAD",
            url="https://example.com/resource",
            headers_json=None,
            cookies_json=None,
            body=None,
            continuation="parse",
            current_location="",
            accumulated_data_json=None,
            aux_data_json=None,
            permanent_json=None,
            expected_type=None,
            dedup_key=None,
            parent_id=None,
        )

        response_id = await sql_manager.store_response(
            request_id=request_id,
            status_code=200,
            headers_json=json.dumps(
                {"Content-Type": "application/pdf", "Content-Length": "5000"}
            ),
            url="https://example.com/resource",
            compressed_content=None,
            content_size_original=0,
            content_size_compressed=0,
            dict_id=None,
            continuation="parse",
            warc_record_id=str(uuid.uuid4()),
        )

        # Retrieve content
        retrieved = await sql_manager.get_response_content(response_id)

        assert retrieved == b""


class TestResultStorage:
    """Tests for result storage operations."""

    async def test_store_result_valid(self, sql_manager: SQLManager) -> None:
        """Test storing a valid result."""
        request_id = await sql_manager.insert_request(
            priority=5,
            request_type="navigating",
            method="GET",
            url="https://example.com/test",
            headers_json=None,
            cookies_json=None,
            body=None,
            continuation="parse",
            current_location="",
            accumulated_data_json=None,
            aux_data_json=None,
            permanent_json=None,
            expected_type=None,
            dedup_key=None,
            parent_id=None,
        )

        result_id = await sql_manager.store_result(
            request_id=request_id,
            result_type="CaseData",
            data_json=json.dumps({"case_name": "Smith v. Jones", "id": 123}),
            is_valid=True,
            validation_errors_json=None,
        )

        assert result_id > 0

        # Verify result was stored
        cursor = await sql_manager.db.execute(
            "SELECT result_type, is_valid, data_json FROM results WHERE id = ?",
            (result_id,),
        )
        row = await cursor.fetchone()
        assert row is not None
        assert row[0] == "CaseData"
        assert row[1] == 1  # is_valid
        data = json.loads(row[2])
        assert data["case_name"] == "Smith v. Jones"

    async def test_store_result_invalid(self, sql_manager: SQLManager) -> None:
        """Test storing an invalid result with validation errors."""
        request_id = await sql_manager.insert_request(
            priority=5,
            request_type="navigating",
            method="GET",
            url="https://example.com/test",
            headers_json=None,
            cookies_json=None,
            body=None,
            continuation="parse",
            current_location="",
            accumulated_data_json=None,
            aux_data_json=None,
            permanent_json=None,
            expected_type=None,
            dedup_key=None,
            parent_id=None,
        )

        validation_errors = [
            {"loc": ["docket_number"], "msg": "field required"}
        ]

        result_id = await sql_manager.store_result(
            request_id=request_id,
            result_type="CaseData",
            data_json=json.dumps({"case_name": "Incomplete"}),
            is_valid=False,
            validation_errors_json=json.dumps(validation_errors),
        )

        # Verify result was stored as invalid
        cursor = await sql_manager.db.execute(
            "SELECT is_valid, validation_errors_json FROM results WHERE id = ?",
            (result_id,),
        )
        row = await cursor.fetchone()
        assert row[0] == 0  # is_valid = False
        assert row[1] is not None


class TestStepControl:
    """Tests for pause/resume step operations."""

    async def test_pause_step(self, sql_manager: SQLManager) -> None:
        """Test pausing requests for a continuation."""
        # Insert requests with different continuations
        await sql_manager.insert_request(
            priority=5,
            request_type="navigating",
            method="GET",
            url="https://example.com/1",
            headers_json=None,
            cookies_json=None,
            body=None,
            continuation="parse_listing",
            current_location="",
            accumulated_data_json=None,
            aux_data_json=None,
            permanent_json=None,
            expected_type=None,
            dedup_key="1",
            parent_id=None,
        )
        await sql_manager.insert_request(
            priority=5,
            request_type="navigating",
            method="GET",
            url="https://example.com/2",
            headers_json=None,
            cookies_json=None,
            body=None,
            continuation="parse_listing",
            current_location="",
            accumulated_data_json=None,
            aux_data_json=None,
            permanent_json=None,
            expected_type=None,
            dedup_key="2",
            parent_id=None,
        )
        await sql_manager.insert_request(
            priority=5,
            request_type="navigating",
            method="GET",
            url="https://example.com/3",
            headers_json=None,
            cookies_json=None,
            body=None,
            continuation="parse_detail",
            current_location="",
            accumulated_data_json=None,
            aux_data_json=None,
            permanent_json=None,
            expected_type=None,
            dedup_key="3",
            parent_id=None,
        )

        # Pause parse_listing
        held_count = await sql_manager.pause_step("parse_listing")
        assert held_count == 2

        # Verify held count
        assert await sql_manager.get_held_count("parse_listing") == 2
        assert await sql_manager.get_held_count("parse_detail") == 0
        assert await sql_manager.get_held_count() == 2

    async def test_resume_step(self, sql_manager: SQLManager) -> None:
        """Test resuming held requests."""
        # Insert and pause
        await sql_manager.insert_request(
            priority=5,
            request_type="navigating",
            method="GET",
            url="https://example.com/1",
            headers_json=None,
            cookies_json=None,
            body=None,
            continuation="parse",
            current_location="",
            accumulated_data_json=None,
            aux_data_json=None,
            permanent_json=None,
            expected_type=None,
            dedup_key="1",
            parent_id=None,
        )

        await sql_manager.pause_step("parse")
        assert await sql_manager.get_held_count() == 1

        # Resume
        resumed_count = await sql_manager.resume_step("parse")
        assert resumed_count == 1
        assert await sql_manager.get_held_count() == 0


class TestListingOperations:
    """Tests for list_requests, list_responses, list_results."""

    async def test_list_requests_by_status(
        self, sql_manager: SQLManager
    ) -> None:
        """Test listing requests filtered by status."""
        # Create requests with different statuses
        req1 = await sql_manager.insert_request(
            priority=5,
            request_type="navigating",
            method="GET",
            url="https://example.com/1",
            headers_json=None,
            cookies_json=None,
            body=None,
            continuation="parse",
            current_location="",
            accumulated_data_json=None,
            aux_data_json=None,
            permanent_json=None,
            expected_type=None,
            dedup_key="1",
            parent_id=None,
        )
        _req2 = await sql_manager.insert_request(
            priority=5,
            request_type="navigating",
            method="GET",
            url="https://example.com/2",
            headers_json=None,
            cookies_json=None,
            body=None,
            continuation="parse",
            current_location="",
            accumulated_data_json=None,
            aux_data_json=None,
            permanent_json=None,
            expected_type=None,
            dedup_key="2",
            parent_id=None,
        )

        # Complete one
        await sql_manager.mark_request_in_progress(req1)
        await sql_manager.mark_request_completed(req1)

        # List pending
        pending_page = await sql_manager.list_requests(status="pending")
        assert pending_page.total == 1
        assert all(r.status == "pending" for r in pending_page.items)

        # List completed
        completed_page = await sql_manager.list_requests(status="completed")
        assert completed_page.total == 1
        assert all(r.status == "completed" for r in completed_page.items)

    async def test_list_requests_by_continuation(
        self, sql_manager: SQLManager
    ) -> None:
        """Test listing requests filtered by continuation."""
        await sql_manager.insert_request(
            priority=5,
            request_type="navigating",
            method="GET",
            url="https://example.com/1",
            headers_json=None,
            cookies_json=None,
            body=None,
            continuation="parse_listing",
            current_location="",
            accumulated_data_json=None,
            aux_data_json=None,
            permanent_json=None,
            expected_type=None,
            dedup_key="1",
            parent_id=None,
        )
        await sql_manager.insert_request(
            priority=5,
            request_type="navigating",
            method="GET",
            url="https://example.com/2",
            headers_json=None,
            cookies_json=None,
            body=None,
            continuation="parse_detail",
            current_location="",
            accumulated_data_json=None,
            aux_data_json=None,
            permanent_json=None,
            expected_type=None,
            dedup_key="2",
            parent_id=None,
        )

        listing_page = await sql_manager.list_requests(
            continuation="parse_listing"
        )
        assert listing_page.total == 1
        assert listing_page.items[0].continuation == "parse_listing"

    async def test_list_requests_pagination(
        self, sql_manager: SQLManager
    ) -> None:
        """Test pagination in list_requests."""
        # Create 10 requests
        for i in range(10):
            await sql_manager.insert_request(
                priority=5,
                request_type="navigating",
                method="GET",
                url=f"https://example.com/{i}",
                headers_json=None,
                cookies_json=None,
                body=None,
                continuation="parse",
                current_location="",
                accumulated_data_json=None,
                aux_data_json=None,
                permanent_json=None,
                expected_type=None,
                dedup_key=str(i),
                parent_id=None,
            )

        # Get first page
        page1 = await sql_manager.list_requests(limit=3, offset=0)
        assert page1.total == 10
        assert len(page1.items) == 3
        assert page1.has_more

        # Get second page
        page2 = await sql_manager.list_requests(limit=3, offset=3)
        assert len(page2.items) == 3
        assert page2.offset == 3

        # Get last page
        page_last = await sql_manager.list_requests(limit=3, offset=9)
        assert len(page_last.items) == 1
        assert not page_last.has_more

    async def test_list_responses(self, sql_manager: SQLManager) -> None:
        """Test listing responses with filters."""
        req1 = await sql_manager.insert_request(
            priority=5,
            request_type="navigating",
            method="GET",
            url="https://example.com/1",
            headers_json=None,
            cookies_json=None,
            body=None,
            continuation="parse_listing",
            current_location="",
            accumulated_data_json=None,
            aux_data_json=None,
            permanent_json=None,
            expected_type=None,
            dedup_key="1",
            parent_id=None,
        )
        req2 = await sql_manager.insert_request(
            priority=5,
            request_type="navigating",
            method="GET",
            url="https://example.com/2",
            headers_json=None,
            cookies_json=None,
            body=None,
            continuation="parse_detail",
            current_location="",
            accumulated_data_json=None,
            aux_data_json=None,
            permanent_json=None,
            expected_type=None,
            dedup_key="2",
            parent_id=None,
        )

        # Store responses
        content = b"Content"
        compressed = compress(content)

        await sql_manager.store_response(
            request_id=req1,
            status_code=200,
            headers_json=None,
            url="https://example.com/1",
            compressed_content=compressed,
            content_size_original=len(content),
            content_size_compressed=len(compressed),
            dict_id=None,
            continuation="parse_listing",
            warc_record_id=str(uuid.uuid4()),
        )
        await sql_manager.store_response(
            request_id=req2,
            status_code=200,
            headers_json=None,
            url="https://example.com/2",
            compressed_content=compressed,
            content_size_original=len(content),
            content_size_compressed=len(compressed),
            dict_id=None,
            continuation="parse_detail",
            warc_record_id=str(uuid.uuid4()),
        )

        # Filter by continuation
        listing_page = await sql_manager.list_responses(
            continuation="parse_listing"
        )
        assert listing_page.total == 1
        assert listing_page.items[0].continuation == "parse_listing"

        # Get all
        all_page = await sql_manager.list_responses()
        assert all_page.total == 2

    async def test_list_results(self, sql_manager: SQLManager) -> None:
        """Test listing results with filters."""
        req_id = await sql_manager.insert_request(
            priority=5,
            request_type="navigating",
            method="GET",
            url="https://example.com/test",
            headers_json=None,
            cookies_json=None,
            body=None,
            continuation="parse",
            current_location="",
            accumulated_data_json=None,
            aux_data_json=None,
            permanent_json=None,
            expected_type=None,
            dedup_key=None,
            parent_id=None,
        )

        await sql_manager.store_result(
            request_id=req_id,
            result_type="CaseData",
            data_json=json.dumps({"id": 1}),
            is_valid=True,
        )
        await sql_manager.store_result(
            request_id=req_id,
            result_type="CaseData",
            data_json=json.dumps({"id": 2}),
            is_valid=False,
            validation_errors_json=json.dumps([{"error": "bad"}]),
        )
        await sql_manager.store_result(
            request_id=req_id,
            result_type="DocumentData",
            data_json=json.dumps({"id": 3}),
            is_valid=True,
        )

        # Filter by type
        case_results = await sql_manager.list_results(result_type="CaseData")
        assert case_results.total == 2

        # Filter by validity
        valid_results = await sql_manager.list_results(is_valid=True)
        assert valid_results.total == 2

        invalid_results = await sql_manager.list_results(is_valid=False)
        assert invalid_results.total == 1


class TestGetterMethods:
    """Tests for get_request, get_response, get_result."""

    async def test_get_request_found(self, sql_manager: SQLManager) -> None:
        """Test getting a request by ID when found."""
        request_id = await sql_manager.insert_request(
            priority=5,
            request_type="navigating",
            method="GET",
            url="https://example.com/test",
            headers_json=None,
            cookies_json=None,
            body=None,
            continuation="parse",
            current_location="https://example.com",
            accumulated_data_json=None,
            aux_data_json=None,
            permanent_json=None,
            expected_type=None,
            dedup_key=None,
            parent_id=None,
        )

        request = await sql_manager.get_request(request_id)

        assert request is not None
        assert request.id == request_id
        assert request.url == "https://example.com/test"
        assert request.method == "GET"
        assert request.continuation == "parse"

    async def test_get_request_not_found(
        self, sql_manager: SQLManager
    ) -> None:
        """Test getting a request by ID when not found."""
        request = await sql_manager.get_request(999)
        assert request is None

    async def test_get_response_found(self, sql_manager: SQLManager) -> None:
        """Test getting a response by ID when found."""
        request_id = await sql_manager.insert_request(
            priority=5,
            request_type="navigating",
            method="GET",
            url="https://example.com/test",
            headers_json=None,
            cookies_json=None,
            body=None,
            continuation="parse",
            current_location="",
            accumulated_data_json=None,
            aux_data_json=None,
            permanent_json=None,
            expected_type=None,
            dedup_key=None,
            parent_id=None,
        )

        content = b"Test"
        compressed = compress(content)

        response_id = await sql_manager.store_response(
            request_id=request_id,
            status_code=200,
            headers_json=json.dumps({"Content-Type": "text/html"}),
            url="https://example.com/test",
            compressed_content=compressed,
            content_size_original=len(content),
            content_size_compressed=len(compressed),
            dict_id=None,
            continuation="parse",
            warc_record_id=str(uuid.uuid4()),
        )

        response = await sql_manager.get_response(response_id)

        assert response is not None
        assert response.id == response_id
        assert response.status_code == 200
        assert response.url == "https://example.com/test"
        assert response.content_size_original == len(content)

    async def test_get_response_not_found(
        self, sql_manager: SQLManager
    ) -> None:
        """Test getting a response by ID when not found."""
        response = await sql_manager.get_response(999)
        assert response is None

    async def test_get_result_found(self, sql_manager: SQLManager) -> None:
        """Test getting a result by ID when found."""
        request_id = await sql_manager.insert_request(
            priority=5,
            request_type="navigating",
            method="GET",
            url="https://example.com/test",
            headers_json=None,
            cookies_json=None,
            body=None,
            continuation="parse",
            current_location="",
            accumulated_data_json=None,
            aux_data_json=None,
            permanent_json=None,
            expected_type=None,
            dedup_key=None,
            parent_id=None,
        )

        result_id = await sql_manager.store_result(
            request_id=request_id,
            result_type="CaseData",
            data_json=json.dumps({"case_name": "Smith v. Jones", "id": 123}),
            is_valid=True,
        )

        result = await sql_manager.get_result(result_id)

        assert result is not None
        assert result.id == result_id
        assert result.result_type == "CaseData"
        assert result.is_valid
        data = json.loads(result.data_json)
        assert data["case_name"] == "Smith v. Jones"

    async def test_get_result_not_found(self, sql_manager: SQLManager) -> None:
        """Test getting a result by ID when not found."""
        result = await sql_manager.get_result(999)
        assert result is None


class TestRecordSerialization:
    """Tests for record serialization methods."""

    async def test_request_record_to_dict(self) -> None:
        """Test RequestRecord.to_dict() and to_json()."""
        record = RequestRecord(
            id=1,
            status="pending",
            priority=5,
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

        d = record.to_dict()
        assert d["id"] == 1
        assert d["status"] == "pending"
        assert d["url"] == "https://example.com"

        json_str = record.to_json()
        parsed = json.loads(json_str)
        assert parsed["id"] == 1

    async def test_response_record_to_dict(self) -> None:
        """Test ResponseRecord.to_dict() with compression_ratio."""
        record = ResponseRecord(
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

        d = record.to_dict()
        assert d["compression_ratio"] == 10.0

    async def test_result_record_to_dict(self) -> None:
        """Test ResultRecord.to_dict() parses JSON fields."""
        record = ResultRecord(
            id=1,
            request_id=1,
            result_type="CaseData",
            data_json='{"name": "test"}',
            is_valid=True,
            validation_errors_json=None,
            created_at="2024-01-01",
        )

        d = record.to_dict()
        assert d["data"] == {"name": "test"}
        assert d["validation_errors"] is None

    async def test_page_to_dict(self) -> None:
        """Test Page.to_dict() and to_json()."""
        record = RequestRecord(
            id=1,
            status="pending",
            priority=5,
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

        page = Page(items=[record], total=10, offset=0, limit=1)

        d = page.to_dict()
        assert d["total"] == 10
        assert d["has_more"] is True
        assert len(d["items"]) == 1

        json_str = page.to_json()
        parsed = json.loads(json_str)
        assert parsed["total"] == 10


class TestWarcExport:
    """Tests for WARC export functionality via warc_export module."""

    async def test_export_warc_basic(
        self, sql_manager: SQLManager, tmp_path: Path
    ) -> None:
        """Test basic WARC export."""
        from juriscraper.scraper_driver.driver.dev_driver.warc_export import (
            export_warc,
        )

        # Create a request and response
        request_id = await sql_manager.insert_request(
            priority=5,
            request_type="navigating",
            method="GET",
            url="https://example.com/page",
            headers_json=json.dumps({"Accept": "text/html"}),
            cookies_json=None,
            body=None,
            continuation="parse",
            current_location="",
            accumulated_data_json=None,
            aux_data_json=None,
            permanent_json=None,
            expected_type=None,
            dedup_key=None,
            parent_id=None,
        )
        await sql_manager.mark_request_completed(request_id)

        content = b"<html>Test page</html>"
        compressed = compress(content)
        warc_id = str(uuid.uuid4())

        await sql_manager.store_response(
            request_id=request_id,
            status_code=200,
            headers_json=json.dumps({"Content-Type": "text/html"}),
            url="https://example.com/page",
            compressed_content=compressed,
            content_size_original=len(content),
            content_size_compressed=len(compressed),
            dict_id=None,
            continuation="parse",
            warc_record_id=warc_id,
        )

        output_path = tmp_path / "test.warc.gz"
        count = await export_warc(sql_manager.db, output_path)

        assert count == 1
        assert output_path.exists()

    async def test_export_warc_by_continuation(
        self, sql_manager: SQLManager, tmp_path: Path
    ) -> None:
        """Test WARC export filtered by continuation."""
        from juriscraper.scraper_driver.driver.dev_driver.warc_export import (
            export_warc,
        )

        # Create requests with different continuations
        for cont, url in [
            ("parse_listing", "https://example.com/listing1"),
            ("parse_listing", "https://example.com/listing2"),
            ("parse_detail", "https://example.com/detail1"),
        ]:
            request_id = await sql_manager.insert_request(
                priority=5,
                request_type="navigating",
                method="GET",
                url=url,
                headers_json=None,
                cookies_json=None,
                body=None,
                continuation=cont,
                current_location="",
                accumulated_data_json=None,
                aux_data_json=None,
                permanent_json=None,
                expected_type=None,
                dedup_key=url,
                parent_id=None,
            )
            await sql_manager.mark_request_completed(request_id)

            content = f"<html>Content for {url}</html>".encode()
            compressed = compress(content)

            await sql_manager.store_response(
                request_id=request_id,
                status_code=200,
                headers_json=None,
                url=url,
                compressed_content=compressed,
                content_size_original=len(content),
                content_size_compressed=len(compressed),
                dict_id=None,
                continuation=cont,
                warc_record_id=str(uuid.uuid4()),
            )

        # Export only parse_listing
        listing_path = tmp_path / "listing.warc.gz"
        count = await export_warc(
            sql_manager.db, listing_path, continuation="parse_listing"
        )
        assert count == 2

        # Export only parse_detail
        detail_path = tmp_path / "detail.warc.gz"
        count = await export_warc(
            sql_manager.db, detail_path, continuation="parse_detail"
        )
        assert count == 1

        # Export all
        all_path = tmp_path / "all.warc.gz"
        count = await export_warc(sql_manager.db, all_path)
        assert count == 3

    async def test_export_warc_empty(
        self, sql_manager: SQLManager, tmp_path: Path
    ) -> None:
        """Test WARC export with no responses."""
        from juriscraper.scraper_driver.driver.dev_driver.warc_export import (
            export_warc,
        )

        output_path = tmp_path / "empty.warc"
        count = await export_warc(
            sql_manager.db, output_path, continuation="nonexistent"
        )

        assert count == 0

    async def test_export_warc_headers_only(
        self, sql_manager: SQLManager, tmp_path: Path
    ) -> None:
        """Test WARC export for headers-only response."""
        from juriscraper.scraper_driver.driver.dev_driver.warc_export import (
            export_warc,
        )

        request_id = await sql_manager.insert_request(
            priority=5,
            request_type="navigating",
            method="HEAD",
            url="https://example.com/resource",
            headers_json=None,
            cookies_json=None,
            body=None,
            continuation="parse",
            current_location="",
            accumulated_data_json=None,
            aux_data_json=None,
            permanent_json=None,
            expected_type=None,
            dedup_key=None,
            parent_id=None,
        )
        await sql_manager.mark_request_completed(request_id)

        await sql_manager.store_response(
            request_id=request_id,
            status_code=200,
            headers_json=json.dumps(
                {"Content-Type": "application/pdf", "Content-Length": "5000"}
            ),
            url="https://example.com/resource",
            compressed_content=None,
            content_size_original=0,
            content_size_compressed=0,
            dict_id=None,
            continuation="parse",
            warc_record_id=str(uuid.uuid4()),
        )

        output_path = tmp_path / "headers_only.warc.gz"
        count = await export_warc(sql_manager.db, output_path)

        assert count == 1
        assert output_path.exists()


class TestRunStatus:
    """Tests for run status checking."""

    async def test_get_run_status_unstarted(
        self, sql_manager: SQLManager
    ) -> None:
        """Test run status is unstarted when no requests."""
        status = await sql_manager.get_run_status()
        assert status == "unstarted"

    async def test_get_run_status_in_progress(
        self, sql_manager: SQLManager
    ) -> None:
        """Test run status is in_progress with pending requests."""
        await sql_manager.insert_request(
            priority=5,
            request_type="navigating",
            method="GET",
            url="https://example.com/test",
            headers_json=None,
            cookies_json=None,
            body=None,
            continuation="parse",
            current_location="",
            accumulated_data_json=None,
            aux_data_json=None,
            permanent_json=None,
            expected_type=None,
            dedup_key=None,
            parent_id=None,
        )

        status = await sql_manager.get_run_status()
        assert status == "in_progress"

    async def test_get_run_status_done(self, sql_manager: SQLManager) -> None:
        """Test run status is done when all completed."""
        request_id = await sql_manager.insert_request(
            priority=5,
            request_type="navigating",
            method="GET",
            url="https://example.com/test",
            headers_json=None,
            cookies_json=None,
            body=None,
            continuation="parse",
            current_location="",
            accumulated_data_json=None,
            aux_data_json=None,
            permanent_json=None,
            expected_type=None,
            dedup_key=None,
            parent_id=None,
        )
        await sql_manager.mark_request_in_progress(request_id)
        await sql_manager.mark_request_completed(request_id)

        status = await sql_manager.get_run_status()
        assert status == "done"


class TestCancelRequests:
    """Tests for request cancellation."""

    async def test_cancel_request(self, sql_manager: SQLManager) -> None:
        """Test cancelling a single pending request."""
        request_id = await sql_manager.insert_request(
            priority=5,
            request_type="navigating",
            method="GET",
            url="https://example.com/test",
            headers_json=None,
            cookies_json=None,
            body=None,
            continuation="parse",
            current_location="",
            accumulated_data_json=None,
            aux_data_json=None,
            permanent_json=None,
            expected_type=None,
            dedup_key=None,
            parent_id=None,
        )

        cancelled = await sql_manager.cancel_request(request_id)
        assert cancelled

        cursor = await sql_manager.db.execute(
            "SELECT status, last_error FROM requests WHERE id = ?",
            (request_id,),
        )
        row = await cursor.fetchone()
        assert row[0] == "failed"
        assert "Cancelled" in row[1]

    async def test_cancel_request_not_pending(
        self, sql_manager: SQLManager
    ) -> None:
        """Test that completed requests can't be cancelled."""
        request_id = await sql_manager.insert_request(
            priority=5,
            request_type="navigating",
            method="GET",
            url="https://example.com/test",
            headers_json=None,
            cookies_json=None,
            body=None,
            continuation="parse",
            current_location="",
            accumulated_data_json=None,
            aux_data_json=None,
            permanent_json=None,
            expected_type=None,
            dedup_key=None,
            parent_id=None,
        )
        await sql_manager.mark_request_in_progress(request_id)
        await sql_manager.mark_request_completed(request_id)

        cancelled = await sql_manager.cancel_request(request_id)
        assert not cancelled

    async def test_cancel_requests_by_continuation(
        self, sql_manager: SQLManager
    ) -> None:
        """Test batch cancelling requests by continuation."""
        # Create multiple requests
        await sql_manager.insert_request(
            priority=5,
            request_type="navigating",
            method="GET",
            url="https://example.com/1",
            headers_json=None,
            cookies_json=None,
            body=None,
            continuation="parse",
            current_location="",
            accumulated_data_json=None,
            aux_data_json=None,
            permanent_json=None,
            expected_type=None,
            dedup_key="1",
            parent_id=None,
        )
        await sql_manager.insert_request(
            priority=5,
            request_type="navigating",
            method="GET",
            url="https://example.com/2",
            headers_json=None,
            cookies_json=None,
            body=None,
            continuation="parse",
            current_location="",
            accumulated_data_json=None,
            aux_data_json=None,
            permanent_json=None,
            expected_type=None,
            dedup_key="2",
            parent_id=None,
        )
        await sql_manager.insert_request(
            priority=5,
            request_type="navigating",
            method="GET",
            url="https://example.com/3",
            headers_json=None,
            cookies_json=None,
            body=None,
            continuation="other",
            current_location="",
            accumulated_data_json=None,
            aux_data_json=None,
            permanent_json=None,
            expected_type=None,
            dedup_key="3",
            parent_id=None,
        )

        count = await sql_manager.cancel_requests_by_continuation("parse")
        assert count == 2

        # Verify 'other' is still pending
        cursor = await sql_manager.db.execute(
            "SELECT status FROM requests WHERE continuation = 'other'"
        )
        row = await cursor.fetchone()
        assert row[0] == "pending"
