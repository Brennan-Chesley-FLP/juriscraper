"""Tests for Playwright driver database persistence.

Tests schema extensions and SQLManager methods for incidental requests
and browser configuration.
"""

from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from juriscraper.scraper_driver.driver.dev_driver.schema import (
    SCHEMA_VERSION,
    init_database,
)
from juriscraper.scraper_driver.driver.dev_driver.sql_manager import SQLManager


@pytest.mark.asyncio
async def test_schema_includes_incidental_requests_table():
    """Verify the database schema includes incidental_requests table."""
    with TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        db = await init_database(db_path)

        # Check that incidental_requests table exists
        cursor = await db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='incidental_requests'"
        )
        row = await cursor.fetchone()
        assert row is not None
        assert row[0] == "incidental_requests"

        # Check schema has expected columns
        cursor = await db.execute("PRAGMA table_info(incidental_requests)")
        columns = await cursor.fetchall()
        column_names = {col[1] for col in columns}

        expected_columns = {
            "id",
            "parent_request_id",
            "resource_type",
            "method",
            "url",
            "headers_json",
            "body",
            "status_code",
            "response_headers_json",
            "content_compressed",
            "content_size_original",
            "content_size_compressed",
            "compression_dict_id",
            "started_at_ns",
            "completed_at_ns",
            "from_cache",
            "failure_reason",
            "created_at",
        }
        assert expected_columns.issubset(column_names)

        await db.close()


@pytest.mark.asyncio
async def test_schema_includes_browser_config_json_field():
    """Verify run_metadata table has browser_config_json field."""
    with TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        db = await init_database(db_path)

        # Check that run_metadata has browser_config_json column
        cursor = await db.execute("PRAGMA table_info(run_metadata)")
        columns = await cursor.fetchall()
        column_names = {col[1] for col in columns}

        assert "browser_config_json" in column_names

        await db.close()


@pytest.mark.asyncio
async def test_schema_version_is_11():
    """Verify schema version is updated to 11."""
    assert SCHEMA_VERSION == 11


@pytest.mark.asyncio
async def test_insert_incidental_request():
    """Test inserting an incidental request."""
    with TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        db = await init_database(db_path)
        manager = SQLManager(db)

        # Create a parent request first
        await manager.init_run_metadata(
            scraper_name="test_scraper",
            scraper_version="1.0",
            num_workers=1,
            max_backoff_time=60.0,
        )

        # Insert a test request to be the parent
        parent_id = await manager.insert_request(
            priority=1,
            request_type="navigating",
            method="GET",
            url="https://example.com",
            headers_json=None,
            cookies_json=None,
            body=None,
            continuation="start",
            current_location="https://example.com",
            accumulated_data_json=None,
            aux_data_json=None,
            permanent_json=None,
            expected_type=None,
            dedup_key="test-key",
            parent_id=None,
        )

        # Insert an incidental request
        incidental_id = await manager.insert_incidental_request(
            parent_request_id=parent_id,
            resource_type="stylesheet",
            method="GET",
            url="https://example.com/style.css",
            headers_json='{"Accept": "text/css"}',
            body=None,
            status_code=200,
            response_headers_json='{"Content-Type": "text/css"}',
            content_compressed=b"compressed css content",
            content_size_original=1024,
            content_size_compressed=512,
            compression_dict_id=None,
            started_at_ns=1000000000,
            completed_at_ns=1000001000,
            from_cache=False,
            failure_reason=None,
        )

        assert incidental_id > 0

        # Retrieve the incidental request
        incidental = await manager.get_incidental_request_by_id(incidental_id)
        assert incidental is not None
        assert incidental["parent_request_id"] == parent_id
        assert incidental["resource_type"] == "stylesheet"
        assert incidental["method"] == "GET"
        assert incidental["url"] == "https://example.com/style.css"
        assert incidental["status_code"] == 200
        assert incidental["from_cache"] == 0  # SQLite stores False as 0

        await db.close()


@pytest.mark.asyncio
async def test_get_incidental_requests_by_parent():
    """Test retrieving all incidental requests for a parent request."""
    with TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        db = await init_database(db_path)
        manager = SQLManager(db)

        # Setup parent request
        await manager.init_run_metadata(
            scraper_name="test_scraper",
            scraper_version="1.0",
            num_workers=1,
            max_backoff_time=60.0,
        )

        parent_id = await manager.insert_request(
            priority=1,
            request_type="navigating",
            method="GET",
            url="https://example.com",
            headers_json=None,
            cookies_json=None,
            body=None,
            continuation="start",
            current_location="https://example.com",
            accumulated_data_json=None,
            aux_data_json=None,
            permanent_json=None,
            expected_type=None,
            dedup_key="test-key",
            parent_id=None,
        )

        # Insert multiple incidental requests
        resource_types = ["stylesheet", "script", "image", "xhr"]
        for i, resource_type in enumerate(resource_types):
            await manager.insert_incidental_request(
                parent_request_id=parent_id,
                resource_type=resource_type,
                method="GET",
                url=f"https://example.com/resource{i}.{resource_type}",
                status_code=200,
                started_at_ns=1000000000 + i * 1000,
                completed_at_ns=1000001000 + i * 1000,
            )

        # Retrieve all incidental requests
        incidentals = await manager.get_incidental_requests(parent_id)
        assert len(incidentals) == 4
        assert [r["resource_type"] for r in incidentals] == resource_types

        await db.close()


@pytest.mark.asyncio
async def test_browser_config_persistence():
    """Test storing and retrieving browser configuration."""
    with TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        db = await init_database(db_path)
        manager = SQLManager(db)

        browser_config = {
            "browser_type": "chromium",
            "headless": True,
            "viewport": {"width": 1280, "height": 720},
            "user_agent": "Mozilla/5.0 Test",
            "locale": "en-US",
            "timezone_id": "America/New_York",
        }

        # Initialize with browser config
        await manager.init_run_metadata(
            scraper_name="test_scraper",
            scraper_version="1.0",
            num_workers=1,
            max_backoff_time=60.0,
            browser_config=browser_config,
        )

        # Retrieve metadata and check browser config
        metadata = await manager.get_run_metadata()
        assert metadata is not None
        assert metadata["browser_config"] == browser_config

        await db.close()


@pytest.mark.asyncio
async def test_migration_to_version_10():
    """Test migration adds browser_config_json to existing database."""
    with TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"

        # Create database and manually set schema version to 9
        db = await init_database(db_path)

        # Simulate old schema by removing browser_config_json
        try:
            await db.execute(
                "ALTER TABLE run_metadata DROP COLUMN browser_config_json"
            )
        except Exception:
            pass  # Column might not exist or be droppable

        # Delete schema version records
        await db.execute("DELETE FROM schema_info")
        await db.execute("INSERT INTO schema_info (version) VALUES (9)")
        await db.commit()
        await db.close()

        # Re-init should run migration
        db = await init_database(db_path)

        # Check that browser_config_json exists
        cursor = await db.execute("PRAGMA table_info(run_metadata)")
        columns = await cursor.fetchall()
        column_names = {col[1] for col in columns}

        assert "browser_config_json" in column_names

        await db.close()


@pytest.mark.asyncio
async def test_migration_to_version_11():
    """Test migration adds incidental_requests table to existing database."""
    with TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"

        # Create database and manually set schema version to 10
        db = await init_database(db_path)

        # Drop incidental_requests table if exists and reset version
        await db.execute("DROP TABLE IF EXISTS incidental_requests")
        await db.execute("DELETE FROM schema_info")
        await db.execute("INSERT INTO schema_info (version) VALUES (10)")
        await db.commit()
        await db.close()

        # Re-init should run migration
        db = await init_database(db_path)

        # Check that incidental_requests table exists
        cursor = await db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='incidental_requests'"
        )
        row = await cursor.fetchone()
        assert row is not None

        await db.close()
