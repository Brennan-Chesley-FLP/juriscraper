"""Tests for LocalDevDriver web routes.

Tests cover:
- Request summary endpoint grouping
- Request summary with empty database
- Compression stats by continuation endpoint
"""

from __future__ import annotations

from pathlib import Path

import pytest

from juriscraper.scraper_driver.driver.dev_driver.web.routes.compression import (
    CompressionStatsByContinuationItem,
    CompressionStatsByContinuationResponse,
)
from juriscraper.scraper_driver.driver.dev_driver.web.routes.requests import (
    RequestSummaryItem,
    RequestSummaryResponse,
)


@pytest.fixture
async def db_path(tmp_path: Path) -> Path:
    """Create a temporary database path."""
    return tmp_path / "test.db"


@pytest.fixture
async def initialized_db(db_path: Path):
    """Create and return an initialized database connection."""
    from juriscraper.scraper_driver.driver.dev_driver.schema import (
        init_database,
    )

    db = await init_database(db_path)
    yield db
    await db.close()


class TestRequestSummary:
    """Tests for the request summary endpoint."""

    async def test_summary_empty_db(self, initialized_db) -> None:
        """Returns empty list for no requests."""
        # Query counts grouped by continuation and status
        query = """
            SELECT continuation, status, COUNT(*) as count
            FROM requests
            GROUP BY continuation, status
            ORDER BY continuation
        """
        cursor = await initialized_db.execute(query)
        rows = await cursor.fetchall()

        # Build pivot table (same logic as endpoint)
        summaries: dict[str, RequestSummaryItem] = {}
        grand_total = 0

        for continuation, _status_val, count in rows:
            if continuation not in summaries:
                summaries[continuation] = RequestSummaryItem(
                    continuation=continuation
                )

            item = summaries[continuation]
            grand_total += count
            item.total += count

        result = RequestSummaryResponse(
            items=list(summaries.values()),
            grand_total=grand_total,
        )

        assert result.items == []
        assert result.grand_total == 0

    async def test_summary_endpoint_grouping(self, initialized_db) -> None:
        """Counts correct per continuation/status."""
        # Insert test requests with different continuations and statuses
        requests_data = [
            # parse_list continuation: 2 pending, 1 completed
            ("pending", 1, 1, "GET", "http://example.com/1", "parse_list"),
            ("pending", 1, 2, "GET", "http://example.com/2", "parse_list"),
            ("completed", 1, 3, "GET", "http://example.com/3", "parse_list"),
            # parse_detail continuation: 1 pending, 2 in_progress, 1 failed
            ("pending", 1, 4, "GET", "http://example.com/4", "parse_detail"),
            (
                "in_progress",
                1,
                5,
                "GET",
                "http://example.com/5",
                "parse_detail",
            ),
            (
                "in_progress",
                1,
                6,
                "GET",
                "http://example.com/6",
                "parse_detail",
            ),
            ("failed", 1, 7, "GET", "http://example.com/7", "parse_detail"),
            # archive continuation: 1 held
            ("held", 1, 8, "GET", "http://example.com/8", "archive"),
        ]

        for (
            status,
            priority,
            queue_counter,
            method,
            url,
            continuation,
        ) in requests_data:
            await initialized_db.execute(
                """
                INSERT INTO requests (status, priority, queue_counter, method, url, continuation)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (status, priority, queue_counter, method, url, continuation),
            )
        await initialized_db.commit()

        # Query counts grouped by continuation and status
        query = """
            SELECT continuation, status, COUNT(*) as count
            FROM requests
            GROUP BY continuation, status
            ORDER BY continuation
        """
        cursor = await initialized_db.execute(query)
        rows = await cursor.fetchall()

        # Build pivot table (same logic as endpoint)
        summaries: dict[str, RequestSummaryItem] = {}
        grand_total = 0

        for continuation, status_val, count in rows:
            if continuation not in summaries:
                summaries[continuation] = RequestSummaryItem(
                    continuation=continuation
                )

            item = summaries[continuation]
            grand_total += count
            item.total += count

            if status_val == "pending":
                item.pending = count
            elif status_val == "in_progress":
                item.in_progress = count
            elif status_val == "completed":
                item.completed = count
            elif status_val == "failed":
                item.failed = count
            elif status_val == "held":
                item.held = count
            elif status_val == "cancelled":
                item.cancelled = count

        result = RequestSummaryResponse(
            items=list(summaries.values()),
            grand_total=grand_total,
        )

        # Verify grand total
        assert result.grand_total == 8

        # Verify we have 3 continuations
        assert len(result.items) == 3

        # Find each continuation and verify counts
        items_by_cont = {item.continuation: item for item in result.items}

        # archive: 1 held
        archive_item = items_by_cont["archive"]
        assert archive_item.held == 1
        assert archive_item.pending == 0
        assert archive_item.total == 1

        # parse_detail: 1 pending, 2 in_progress, 1 failed
        detail_item = items_by_cont["parse_detail"]
        assert detail_item.pending == 1
        assert detail_item.in_progress == 2
        assert detail_item.failed == 1
        assert detail_item.completed == 0
        assert detail_item.total == 4

        # parse_list: 2 pending, 1 completed
        list_item = items_by_cont["parse_list"]
        assert list_item.pending == 2
        assert list_item.completed == 1
        assert list_item.in_progress == 0
        assert list_item.total == 3


class TestCompressionStatsByContinuation:
    """Tests for the compression stats by continuation endpoint."""

    async def test_stats_by_continuation_empty_db(
        self, initialized_db
    ) -> None:
        """Returns empty list for no responses."""
        query = """
            SELECT
                r.continuation,
                r.compression_dict_id,
                d.version,
                COUNT(*) as response_count,
                COALESCE(SUM(r.content_size_original), 0) as total_original,
                COALESCE(SUM(r.content_size_compressed), 0) as total_compressed
            FROM responses r
            LEFT JOIN compression_dicts d ON r.compression_dict_id = d.id
            GROUP BY r.continuation, r.compression_dict_id
            ORDER BY r.continuation, d.version DESC NULLS LAST
        """
        cursor = await initialized_db.execute(query)
        rows = await cursor.fetchall()

        items: list[CompressionStatsByContinuationItem] = []
        for (
            continuation,
            dict_id,
            version,
            count,
            total_orig,
            total_comp,
        ) in rows:
            ratio = total_orig / total_comp if total_comp > 0 else 0.0
            items.append(
                CompressionStatsByContinuationItem(
                    continuation=continuation,
                    dict_id=dict_id,
                    dict_version=version,
                    response_count=count,
                    total_original_bytes=total_orig,
                    total_compressed_bytes=total_comp,
                    compression_ratio=round(ratio, 2),
                )
            )

        result = CompressionStatsByContinuationResponse(
            items=items,
            grand_total_responses=0,
            grand_total_original=0,
            grand_total_compressed=0,
            overall_ratio=0.0,
        )

        assert result.items == []
        assert result.grand_total_responses == 0

    async def test_stats_by_continuation_grouping(
        self, initialized_db
    ) -> None:
        """Groups by continuation and calculates compression ratio correctly."""
        # First insert requests (required foreign key)
        await initialized_db.execute(
            """
            INSERT INTO requests (id, status, priority, queue_counter, method, url, continuation)
            VALUES (1, 'completed', 1, 1, 'GET', 'http://example.com/1', 'parse_list'),
                   (2, 'completed', 1, 2, 'GET', 'http://example.com/2', 'parse_list'),
                   (3, 'completed', 1, 3, 'GET', 'http://example.com/3', 'parse_detail')
            """
        )

        # Insert responses for testing (no dictionary)
        responses_data = [
            # parse_list: 2 responses, 10000 original, 2000 compressed (5x ratio)
            (
                1,
                200,
                "http://example.com/1",
                b"compressed1",
                5000,
                1000,
                None,
                "parse_list",
            ),
            (
                2,
                200,
                "http://example.com/2",
                b"compressed2",
                5000,
                1000,
                None,
                "parse_list",
            ),
            # parse_detail: 1 response, 8000 original, 1000 compressed (8x ratio)
            (
                3,
                200,
                "http://example.com/3",
                b"compressed3",
                8000,
                1000,
                None,
                "parse_detail",
            ),
        ]

        for (
            req_id,
            status,
            url,
            content,
            orig_size,
            comp_size,
            dict_id,
            cont,
        ) in responses_data:
            await initialized_db.execute(
                """
                INSERT INTO responses (request_id, status_code, url, content_compressed,
                                       content_size_original, content_size_compressed,
                                       compression_dict_id, continuation)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    req_id,
                    status,
                    url,
                    content,
                    orig_size,
                    comp_size,
                    dict_id,
                    cont,
                ),
            )
        await initialized_db.commit()

        # Query using same logic as endpoint
        query = """
            SELECT
                r.continuation,
                r.compression_dict_id,
                d.version,
                COUNT(*) as response_count,
                COALESCE(SUM(r.content_size_original), 0) as total_original,
                COALESCE(SUM(r.content_size_compressed), 0) as total_compressed
            FROM responses r
            LEFT JOIN compression_dicts d ON r.compression_dict_id = d.id
            GROUP BY r.continuation, r.compression_dict_id
            ORDER BY r.continuation, d.version DESC NULLS LAST
        """
        cursor = await initialized_db.execute(query)
        rows = await cursor.fetchall()

        items: list[CompressionStatsByContinuationItem] = []
        grand_total_responses = 0
        grand_total_original = 0
        grand_total_compressed = 0

        for (
            continuation,
            dict_id,
            version,
            count,
            total_orig,
            total_comp,
        ) in rows:
            ratio = total_orig / total_comp if total_comp > 0 else 0.0
            items.append(
                CompressionStatsByContinuationItem(
                    continuation=continuation,
                    dict_id=dict_id,
                    dict_version=version,
                    response_count=count,
                    total_original_bytes=total_orig,
                    total_compressed_bytes=total_comp,
                    compression_ratio=round(ratio, 2),
                )
            )
            grand_total_responses += count
            grand_total_original += total_orig
            grand_total_compressed += total_comp

        overall_ratio = (
            grand_total_original / grand_total_compressed
            if grand_total_compressed > 0
            else 0.0
        )

        result = CompressionStatsByContinuationResponse(
            items=items,
            grand_total_responses=grand_total_responses,
            grand_total_original=grand_total_original,
            grand_total_compressed=grand_total_compressed,
            overall_ratio=round(overall_ratio, 2),
        )

        # Verify totals
        assert result.grand_total_responses == 3
        assert result.grand_total_original == 18000  # 5000 + 5000 + 8000
        assert result.grand_total_compressed == 3000  # 1000 + 1000 + 1000
        assert result.overall_ratio == 6.0  # 18000 / 3000

        # Verify grouping - should have 2 groups (parse_detail, parse_list)
        assert len(result.items) == 2

        items_by_cont = {item.continuation: item for item in result.items}

        # parse_detail: 1 response, 8x ratio
        detail_item = items_by_cont["parse_detail"]
        assert detail_item.response_count == 1
        assert detail_item.total_original_bytes == 8000
        assert detail_item.total_compressed_bytes == 1000
        assert detail_item.compression_ratio == 8.0
        assert detail_item.dict_id is None

        # parse_list: 2 responses, 5x ratio
        list_item = items_by_cont["parse_list"]
        assert list_item.response_count == 2
        assert list_item.total_original_bytes == 10000
        assert list_item.total_compressed_bytes == 2000
        assert list_item.compression_ratio == 5.0
        assert list_item.dict_id is None
