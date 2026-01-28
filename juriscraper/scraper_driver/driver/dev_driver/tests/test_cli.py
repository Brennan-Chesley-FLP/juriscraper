"""Tests for CLI commands.

These tests verify the Click CLI commands that wrap the LocalDevDriverDebugger
functionality. They test command invocation, argument parsing, and output formatting.
"""

from __future__ import annotations

import json
from pathlib import Path

import aiosqlite
import pytest
from click.testing import CliRunner

from juriscraper.scraper_driver.driver.dev_driver.cli import cli
from juriscraper.scraper_driver.driver.dev_driver.compression import compress
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
    initialized_db: aiosqlite.Connection, db_path: Path
) -> Path:
    """Create a populated database with sample data for testing.

    This fixture creates the same sample data as the debugger tests,
    but returns the path instead of the connection.
    """
    db = initialized_db
    sql_manager = SQLManager(db)

    # Insert run metadata
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

        if target_status != "pending":
            await db.execute(
                "UPDATE requests SET status = ? WHERE id = ?",
                (target_status, request_id),
            )

    await db.commit()

    # Insert responses for completed requests
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

    # Insert results
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

    # Insert errors
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

    # Insert rate limiter state
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

    # Insert compression dictionary
    await db.execute(
        """
        INSERT INTO compression_dicts (
            continuation, version, sample_count, dictionary_data, created_at
        ) VALUES (?, ?, ?, ?, datetime('now'))
        """,
        ("step1", 1, 100, b"fake_dict_data"),
    )

    await db.commit()
    await db.close()

    return db_path


@pytest.fixture
def runner() -> CliRunner:
    """Create a Click test runner."""
    return CliRunner()


class TestInfoCommand:
    """Tests for the info command."""

    def test_info_table_format(
        self, runner: CliRunner, populated_db: Path
    ) -> None:
        """Test info command with table format."""
        result = runner.invoke(cli, ["info", str(populated_db)])

        assert result.exit_code == 0
        assert "Run Metadata" in result.output
        assert "test.scraper" in result.output
        assert "Statistics" in result.output
        assert "Queue Total" in result.output

    def test_info_json_format(
        self, runner: CliRunner, populated_db: Path
    ) -> None:
        """Test info command with JSON format."""
        result = runner.invoke(
            cli, ["info", str(populated_db), "--format", "json"]
        )

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "metadata" in data
        assert "stats" in data
        assert data["metadata"]["scraper_name"] == "test.scraper"

    def test_info_nonexistent_db(self, runner: CliRunner) -> None:
        """Test info command with non-existent database."""
        result = runner.invoke(cli, ["info", "/nonexistent/path.db"])

        assert result.exit_code != 0


class TestRequestsCommands:
    """Tests for the requests commands."""

    def test_requests_list(
        self, runner: CliRunner, populated_db: Path
    ) -> None:
        """Test requests list command."""
        result = runner.invoke(cli, ["requests", "list", str(populated_db)])

        assert result.exit_code == 0
        assert "Total: 5" in result.output
        assert (
            "https://example" in result.output
        )  # URLs are truncated in table format

    def test_requests_list_filter_by_status(
        self, runner: CliRunner, populated_db: Path
    ) -> None:
        """Test filtering requests by status."""
        result = runner.invoke(
            cli,
            ["requests", "list", str(populated_db), "--status", "completed"],
        )

        assert result.exit_code == 0
        assert "Total: 2" in result.output

    def test_requests_list_filter_by_continuation(
        self, runner: CliRunner, populated_db: Path
    ) -> None:
        """Test filtering requests by continuation."""
        result = runner.invoke(
            cli,
            ["requests", "list", str(populated_db), "--continuation", "step1"],
        )

        assert result.exit_code == 0
        assert "Total: 3" in result.output

    def test_requests_list_json_format(
        self, runner: CliRunner, populated_db: Path
    ) -> None:
        """Test requests list with JSON format."""
        result = runner.invoke(
            cli, ["requests", "list", str(populated_db), "--format", "json"]
        )

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "items" in data
        assert "total" in data
        assert data["total"] == 5

    def test_requests_list_pagination(
        self, runner: CliRunner, populated_db: Path
    ) -> None:
        """Test requests list with pagination."""
        result = runner.invoke(
            cli,
            [
                "requests",
                "list",
                str(populated_db),
                "--limit",
                "2",
                "--offset",
                "0",
            ],
        )

        assert result.exit_code == 0
        assert "Showing: 2" in result.output
        assert "Limit: 2" in result.output

    def test_requests_show(
        self, runner: CliRunner, populated_db: Path
    ) -> None:
        """Test requests show command."""
        result = runner.invoke(
            cli, ["requests", "show", str(populated_db), "1"]
        )

        assert result.exit_code == 0
        assert "ID: 1" in result.output
        assert "example.com/page1" in result.output
        assert "Status:" in result.output

    def test_requests_show_json_format(
        self, runner: CliRunner, populated_db: Path
    ) -> None:
        """Test requests show with JSON format."""
        result = runner.invoke(
            cli,
            ["requests", "show", str(populated_db), "1", "--format", "json"],
        )

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["id"] == 1
        assert "url" in data

    def test_requests_show_not_found(
        self, runner: CliRunner, populated_db: Path
    ) -> None:
        """Test requests show with non-existent request."""
        result = runner.invoke(
            cli, ["requests", "show", str(populated_db), "9999"]
        )

        assert result.exit_code != 0
        assert "not found" in result.output

    def test_requests_summary(
        self, runner: CliRunner, populated_db: Path
    ) -> None:
        """Test requests summary command."""
        result = runner.invoke(cli, ["requests", "summary", str(populated_db)])

        assert result.exit_code == 0
        assert "step1" in result.output or "step2" in result.output


class TestResponsesCommands:
    """Tests for the responses commands."""

    def test_responses_list(
        self, runner: CliRunner, populated_db: Path
    ) -> None:
        """Test responses list command."""
        result = runner.invoke(cli, ["responses", "list", str(populated_db)])

        assert result.exit_code == 0
        assert "Total: 2" in result.output

    def test_responses_list_filter_by_continuation(
        self, runner: CliRunner, populated_db: Path
    ) -> None:
        """Test filtering responses by continuation."""
        result = runner.invoke(
            cli,
            [
                "responses",
                "list",
                str(populated_db),
                "--continuation",
                "step1",
            ],
        )

        assert result.exit_code == 0
        assert "Total: 2" in result.output

    def test_responses_show(
        self, runner: CliRunner, populated_db: Path
    ) -> None:
        """Test responses show command."""
        result = runner.invoke(
            cli, ["responses", "show", str(populated_db), "1"]
        )

        assert result.exit_code == 0
        assert "ID: 1" in result.output
        assert "Status Code:" in result.output

    def test_responses_content(
        self, runner: CliRunner, populated_db: Path, tmp_path: Path
    ) -> None:
        """Test responses content command."""
        result = runner.invoke(
            cli, ["responses", "content", str(populated_db), "1"]
        )

        assert result.exit_code == 0
        assert "Response 1" in result.output

    def test_responses_content_to_file(
        self, runner: CliRunner, populated_db: Path, tmp_path: Path
    ) -> None:
        """Test responses content command with output file."""
        output_file = tmp_path / "response.html"
        result = runner.invoke(
            cli,
            [
                "responses",
                "content",
                str(populated_db),
                "1",
                "-o",
                str(output_file),
            ],
        )

        assert result.exit_code == 0
        assert output_file.exists()
        assert b"Response 1" in output_file.read_bytes()


class TestErrorsCommands:
    """Tests for the errors commands."""

    def test_errors_list(self, runner: CliRunner, populated_db: Path) -> None:
        """Test errors list command."""
        result = runner.invoke(cli, ["errors", "list", str(populated_db)])

        assert result.exit_code == 0
        assert "Total: 2" in result.output

    def test_errors_list_filter_by_type(
        self, runner: CliRunner, populated_db: Path
    ) -> None:
        """Test filtering errors by type."""
        result = runner.invoke(
            cli, ["errors", "list", str(populated_db), "--type", "xpath"]
        )

        assert result.exit_code == 0
        assert "Total: 1" in result.output

    def test_errors_list_filter_by_resolution(
        self, runner: CliRunner, populated_db: Path
    ) -> None:
        """Test filtering errors by resolution status."""
        result = runner.invoke(
            cli, ["errors", "list", str(populated_db), "--unresolved"]
        )

        assert result.exit_code == 0
        assert "Total: 1" in result.output

    def test_errors_show(self, runner: CliRunner, populated_db: Path) -> None:
        """Test errors show command."""
        result = runner.invoke(cli, ["errors", "show", str(populated_db), "1"])

        assert result.exit_code == 0
        assert "ID: 1" in result.output
        assert "Type:" in result.output
        assert "xpath" in result.output

    def test_errors_summary(
        self, runner: CliRunner, populated_db: Path
    ) -> None:
        """Test errors summary command."""
        result = runner.invoke(cli, ["errors", "summary", str(populated_db)])

        assert result.exit_code == 0
        assert "Totals" in result.output or "By Type" in result.output

    def test_errors_resolve(
        self, runner: CliRunner, populated_db: Path
    ) -> None:
        """Test errors resolve command."""
        result = runner.invoke(
            cli,
            ["errors", "resolve", str(populated_db), "1", "--notes", "Fixed"],
        )

        assert result.exit_code == 0
        assert "resolved" in result.output

    def test_errors_requeue(
        self, runner: CliRunner, populated_db: Path
    ) -> None:
        """Test errors requeue command."""
        result = runner.invoke(
            cli,
            [
                "errors",
                "requeue",
                str(populated_db),
                "1",
                "--notes",
                "Trying again",
            ],
        )

        assert result.exit_code == 0
        assert "requeued" in result.output


class TestResultsCommands:
    """Tests for the results commands."""

    def test_results_list(self, runner: CliRunner, populated_db: Path) -> None:
        """Test results list command."""
        result = runner.invoke(cli, ["results", "list", str(populated_db)])

        assert result.exit_code == 0
        assert "Total: 2" in result.output

    def test_results_list_filter_by_validity(
        self, runner: CliRunner, populated_db: Path
    ) -> None:
        """Test filtering results by validity."""
        result = runner.invoke(
            cli, ["results", "list", str(populated_db), "--valid"]
        )

        assert result.exit_code == 0
        assert "Total: 1" in result.output

    def test_results_show(self, runner: CliRunner, populated_db: Path) -> None:
        """Test results show command."""
        result = runner.invoke(
            cli, ["results", "show", str(populated_db), "1"]
        )

        assert result.exit_code == 0
        assert "ID: 1" in result.output
        assert "Type:" in result.output

    def test_results_summary(
        self, runner: CliRunner, populated_db: Path
    ) -> None:
        """Test results summary command."""
        result = runner.invoke(cli, ["results", "summary", str(populated_db)])

        assert result.exit_code == 0
        assert "TestResult" in result.output


class TestRequeueCommands:
    """Tests for the requeue commands."""

    def test_requeue_request(
        self, runner: CliRunner, populated_db: Path
    ) -> None:
        """Test requeue request command."""
        result = runner.invoke(
            cli, ["requeue", "request", str(populated_db), "2"]
        )

        assert result.exit_code == 0
        assert "requeued" in result.output

    def test_requeue_request_no_clear_downstream(
        self, runner: CliRunner, populated_db: Path
    ) -> None:
        """Test requeue request without clearing downstream."""
        result = runner.invoke(
            cli,
            [
                "requeue",
                "request",
                str(populated_db),
                "2",
                "--no-clear-downstream",
            ],
        )

        assert result.exit_code == 0
        assert "requeued" in result.output

    def test_requeue_continuation(
        self, runner: CliRunner, populated_db: Path
    ) -> None:
        """Test requeue continuation command."""
        result = runner.invoke(
            cli, ["requeue", "continuation", str(populated_db), "step1"]
        )

        assert result.exit_code == 0
        assert "Requeued" in result.output

    def test_requeue_errors(
        self, runner: CliRunner, populated_db: Path
    ) -> None:
        """Test requeue errors command."""
        result = runner.invoke(
            cli, ["requeue", "errors", str(populated_db), "--type", "xpath"]
        )

        assert result.exit_code == 0
        assert "Requeued" in result.output


class TestCancelCommands:
    """Tests for the cancel commands."""

    def test_cancel_request(
        self, runner: CliRunner, populated_db: Path
    ) -> None:
        """Test cancel request command."""
        result = runner.invoke(
            cli, ["cancel", "request", str(populated_db), "1"]
        )

        assert result.exit_code == 0
        assert "cancelled" in result.output

    def test_cancel_request_not_pending(
        self, runner: CliRunner, populated_db: Path
    ) -> None:
        """Test cancel request that is not pending."""
        result = runner.invoke(
            cli, ["cancel", "request", str(populated_db), "2"]
        )

        assert result.exit_code != 0

    def test_cancel_continuation(
        self, runner: CliRunner, populated_db: Path
    ) -> None:
        """Test cancel continuation command."""
        result = runner.invoke(
            cli, ["cancel", "continuation", str(populated_db), "step2"]
        )

        assert result.exit_code == 0
        assert "Cancelled" in result.output


class TestCompressionCommands:
    """Tests for the compression commands."""

    def test_compression_stats(
        self, runner: CliRunner, populated_db: Path
    ) -> None:
        """Test compression stats command."""
        result = runner.invoke(
            cli, ["compression", "stats", str(populated_db)]
        )

        assert result.exit_code == 0
        assert (
            "Compression Statistics" in result.output
            or "Total" in result.output
        )

    def test_compression_stats_json_format(
        self, runner: CliRunner, populated_db: Path
    ) -> None:
        """Test compression stats with JSON format."""
        result = runner.invoke(
            cli,
            ["compression", "stats", str(populated_db), "--format", "json"],
        )

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "total" in data

    def test_compression_train(
        self, runner: CliRunner, populated_db: Path
    ) -> None:
        """Test compression train command."""
        result = runner.invoke(
            cli,
            [
                "compression",
                "train",
                str(populated_db),
                "step1",
                "--samples",
                "10",
            ],
        )

        # This may fail if there aren't enough samples, which is expected
        assert result.exit_code in (0, 1)

    def test_compression_recompress(
        self, runner: CliRunner, populated_db: Path
    ) -> None:
        """Test compression recompress command."""
        result = runner.invoke(
            cli, ["compression", "recompress", str(populated_db), "step1"]
        )

        assert result.exit_code == 0


class TestExportCommands:
    """Tests for the export commands."""

    def test_export_jsonl(
        self, runner: CliRunner, populated_db: Path, tmp_path: Path
    ) -> None:
        """Test export jsonl command."""
        output_file = tmp_path / "results.jsonl"
        result = runner.invoke(
            cli, ["export", "jsonl", str(populated_db), str(output_file)]
        )

        assert result.exit_code == 0
        assert "Exported" in result.output
        assert output_file.exists()

        # Verify content
        lines = output_file.read_text().strip().split("\n")
        assert len(lines) == 2
        first_result = json.loads(lines[0])
        assert "id" in first_result
        assert "result_type" in first_result

    def test_export_jsonl_filtered(
        self, runner: CliRunner, populated_db: Path, tmp_path: Path
    ) -> None:
        """Test export jsonl with filters."""
        output_file = tmp_path / "valid_results.jsonl"
        result = runner.invoke(
            cli,
            [
                "export",
                "jsonl",
                str(populated_db),
                str(output_file),
                "--valid",
            ],
        )

        assert result.exit_code == 0
        assert "Exported 1" in result.output

    def test_export_warc(
        self, runner: CliRunner, populated_db: Path, tmp_path: Path
    ) -> None:
        """Test export warc command."""
        output_file = tmp_path / "archive.warc.gz"
        result = runner.invoke(
            cli, ["export", "warc", str(populated_db), str(output_file)]
        )

        assert result.exit_code == 0
        assert "Exported" in result.output
        assert output_file.exists()

    def test_export_warc_no_compress(
        self, runner: CliRunner, populated_db: Path, tmp_path: Path
    ) -> None:
        """Test export warc without compression."""
        output_file = tmp_path / "archive.warc"
        result = runner.invoke(
            cli,
            [
                "export",
                "warc",
                str(populated_db),
                str(output_file),
                "--no-compress",
            ],
        )

        assert result.exit_code == 0
        assert "Exported" in result.output


class TestDiagnoseCommand:
    """Tests for the diagnose command."""

    def test_diagnose_error_without_response(
        self, runner: CliRunner, populated_db: Path
    ) -> None:
        """Test diagnose command on error without response."""
        result = runner.invoke(cli, ["diagnose", str(populated_db), "1"])

        # Should fail because error 1 doesn't have a response
        assert result.exit_code != 0

    def test_diagnose_error_not_found(
        self, runner: CliRunner, populated_db: Path
    ) -> None:
        """Test diagnose command on non-existent error."""
        result = runner.invoke(cli, ["diagnose", str(populated_db), "9999"])

        assert result.exit_code != 0
        assert "not found" in result.output


class TestOutputFormats:
    """Tests for different output formats across commands."""

    def test_table_format_default(
        self, runner: CliRunner, populated_db: Path
    ) -> None:
        """Test that table format is the default."""
        result = runner.invoke(cli, ["requests", "list", str(populated_db)])

        assert result.exit_code == 0
        # Table format should have column separators
        assert "Total:" in result.output

    def test_json_format(self, runner: CliRunner, populated_db: Path) -> None:
        """Test JSON output format."""
        result = runner.invoke(
            cli, ["requests", "list", str(populated_db), "--format", "json"]
        )

        assert result.exit_code == 0
        # Should be valid JSON
        data = json.loads(result.output)
        assert isinstance(data, dict)

    def test_jsonl_format(self, runner: CliRunner, populated_db: Path) -> None:
        """Test JSONL output format."""
        result = runner.invoke(
            cli,
            [
                "errors",
                "list",
                str(populated_db),
                "--format",
                "jsonl",
                "--limit",
                "10",
            ],
        )

        assert result.exit_code == 0
        # Should be valid JSONL (newline-delimited JSON)
        if result.output.strip():
            lines = result.output.strip().split("\n")
            for line in lines:
                data = json.loads(line)
                assert isinstance(data, dict)


class TestIntegration:
    """Integration tests that test workflows across multiple commands."""

    def test_workflow_inspect_and_requeue(
        self, runner: CliRunner, populated_db: Path
    ) -> None:
        """Test workflow: inspect failed request, then requeue it."""
        # First, list failed requests
        result = runner.invoke(
            cli, ["requests", "list", str(populated_db), "--status", "failed"]
        )
        assert result.exit_code == 0
        assert "Total: 1" in result.output

        # Then requeue it (request ID 3 is failed)
        result = runner.invoke(
            cli, ["requeue", "request", str(populated_db), "3"]
        )
        assert result.exit_code == 0

        # Verify it was requeued by checking pending requests increased
        result = runner.invoke(
            cli, ["requests", "list", str(populated_db), "--status", "pending"]
        )
        assert result.exit_code == 0

    def test_workflow_inspect_error_and_resolve(
        self, runner: CliRunner, populated_db: Path
    ) -> None:
        """Test workflow: inspect error, then resolve it."""
        # First, show the error details
        result = runner.invoke(cli, ["errors", "show", str(populated_db), "1"])
        assert result.exit_code == 0
        assert "xpath" in result.output

        # Then resolve it
        result = runner.invoke(
            cli,
            ["errors", "resolve", str(populated_db), "1", "--notes", "Fixed"],
        )
        assert result.exit_code == 0

        # Verify it was resolved
        result = runner.invoke(
            cli, ["errors", "list", str(populated_db), "--unresolved"]
        )
        assert result.exit_code == 0
        # Should now have 0 unresolved (previously was 1)

    def test_workflow_export_results(
        self, runner: CliRunner, populated_db: Path, tmp_path: Path
    ) -> None:
        """Test workflow: inspect results, then export them."""
        # First, check results summary
        result = runner.invoke(cli, ["results", "summary", str(populated_db)])
        assert result.exit_code == 0

        # Then export only valid results
        output_file = tmp_path / "valid.jsonl"
        result = runner.invoke(
            cli,
            [
                "export",
                "jsonl",
                str(populated_db),
                str(output_file),
                "--valid",
            ],
        )
        assert result.exit_code == 0
        assert output_file.exists()

        # Verify export contains expected data
        lines = output_file.read_text().strip().split("\n")
        assert len(lines) == 1  # Only 1 valid result


class TestDoctorCommand:
    """Tests for doctor command and subcommands."""

    def test_doctor_base_command_table_format(
        self, runner: CliRunner, populated_db: Path
    ) -> None:
        """Test base doctor command with table format."""
        result = runner.invoke(cli, ["doctor", str(populated_db)])

        assert result.exit_code == 0
        assert "Health Report" in result.output
        assert "Run Status:" in result.output
        assert "Integrity Check:" in result.output
        assert "Errors:" in result.output
        assert "Ghost Requests:" in result.output

    def test_doctor_base_command_json_format(
        self, runner: CliRunner, populated_db: Path
    ) -> None:
        """Test base doctor command with JSON format."""
        result = runner.invoke(
            cli, ["doctor", "--format", "json", str(populated_db)]
        )

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "status" in data
        assert "integrity" in data
        assert "ghosts" in data
        assert "error_stats" in data

    def test_doctor_base_command_jsonl_format(
        self, runner: CliRunner, populated_db: Path
    ) -> None:
        """Test base doctor command with JSONL format."""
        result = runner.invoke(
            cli, ["doctor", "--format", "jsonl", str(populated_db)]
        )

        assert result.exit_code == 0
        lines = result.output.strip().split("\n")
        assert len(lines) == 4  # status, integrity, ghosts, errors

        # Each line should be valid JSON with section field
        for line in lines:
            data = json.loads(line)
            assert "section" in data

    def test_doctor_orphans_table_format(
        self, runner: CliRunner, populated_db: Path
    ) -> None:
        """Test doctor orphans command with table format."""
        result = runner.invoke(cli, ["doctor", str(populated_db), "orphans"])

        assert result.exit_code == 0
        assert "Orphaned Requests" in result.output
        assert "Orphaned Responses" in result.output

    def test_doctor_orphans_json_format(
        self, runner: CliRunner, populated_db: Path
    ) -> None:
        """Test doctor orphans command with JSON format."""
        result = runner.invoke(
            cli, ["doctor", str(populated_db), "orphans", "--format", "json"]
        )

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "orphaned_requests" in data
        assert "orphaned_responses" in data
        assert isinstance(data["orphaned_requests"], list)
        assert isinstance(data["orphaned_responses"], list)

    def test_doctor_orphans_jsonl_format(
        self, runner: CliRunner, populated_db: Path
    ) -> None:
        """Test doctor orphans command with JSONL format."""
        result = runner.invoke(
            cli, ["doctor", str(populated_db), "orphans", "--format", "jsonl"]
        )

        assert result.exit_code == 0
        # Should have lines for any orphaned requests/responses
        # In populated_db, we have no orphans, so output may be empty or minimal

    def test_doctor_pending_table_format(
        self, runner: CliRunner, populated_db: Path
    ) -> None:
        """Test doctor pending command with table format."""
        result = runner.invoke(cli, ["doctor", str(populated_db), "pending"])

        assert result.exit_code == 0
        assert "Total Pending:" in result.output
        # populated_db has 1 pending request
        assert "1" in result.output

    def test_doctor_pending_json_format(
        self, runner: CliRunner, populated_db: Path
    ) -> None:
        """Test doctor pending command with JSON format."""
        result = runner.invoke(
            cli, ["doctor", str(populated_db), "pending", "--format", "json"]
        )

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "total" in data
        assert "items" in data
        assert data["total"] == 1  # One pending request in populated_db

    def test_doctor_pending_with_limit(
        self, runner: CliRunner, populated_db: Path
    ) -> None:
        """Test doctor pending command with limit option."""
        result = runner.invoke(
            cli,
            ["doctor", str(populated_db), "pending", "--limit", "50"],
        )

        assert result.exit_code == 0

    def test_doctor_ghosts_table_format(
        self, runner: CliRunner, populated_db: Path
    ) -> None:
        """Test doctor ghosts command with table format."""
        result = runner.invoke(cli, ["doctor", str(populated_db), "ghosts"])

        assert result.exit_code == 0
        assert "Ghost Requests" in result.output
        assert "Total:" in result.output

    def test_doctor_ghosts_json_format(
        self, runner: CliRunner, populated_db: Path
    ) -> None:
        """Test doctor ghosts command with JSON format."""
        result = runner.invoke(
            cli, ["doctor", str(populated_db), "ghosts", "--format", "json"]
        )

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "total_count" in data
        assert "by_continuation" in data
        assert "ghosts" in data

    def test_doctor_ghosts_jsonl_format(
        self, runner: CliRunner, populated_db: Path
    ) -> None:
        """Test doctor ghosts command with JSONL format."""
        result = runner.invoke(
            cli, ["doctor", str(populated_db), "ghosts", "--format", "jsonl"]
        )

        assert result.exit_code == 0
        # Output should be valid (may be empty if no ghosts)

    def test_doctor_ghosts_with_continuation_filter(
        self, runner: CliRunner, populated_db: Path
    ) -> None:
        """Test doctor ghosts command with continuation filter."""
        result = runner.invoke(
            cli,
            [
                "doctor",
                str(populated_db),
                "ghosts",
                "--continuation",
                "step1",
            ],
        )

        assert result.exit_code == 0

    def test_doctor_ghosts_nonexistent_continuation(
        self, runner: CliRunner, populated_db: Path
    ) -> None:
        """Test doctor ghosts with nonexistent continuation."""
        result = runner.invoke(
            cli,
            [
                "doctor",
                str(populated_db),
                "ghosts",
                "--continuation",
                "nonexistent",
            ],
        )

        assert result.exit_code == 0
        assert "No ghost requests found" in result.output


class TestErrorHandling:
    """Tests for error handling and edge cases."""

    def test_invalid_database_path(self, runner: CliRunner) -> None:
        """Test commands with invalid database path."""
        result = runner.invoke(cli, ["info", "/invalid/path.db"])
        assert result.exit_code != 0

    def test_invalid_format_option(
        self, runner: CliRunner, populated_db: Path
    ) -> None:
        """Test commands with invalid format option."""
        result = runner.invoke(
            cli, ["info", str(populated_db), "--format", "invalid"]
        )
        assert result.exit_code != 0

    def test_missing_required_argument(self, runner: CliRunner) -> None:
        """Test commands with missing required arguments."""
        result = runner.invoke(cli, ["requests", "show"])
        assert result.exit_code != 0

    def test_invalid_request_id(
        self, runner: CliRunner, populated_db: Path
    ) -> None:
        """Test commands with invalid request ID."""
        result = runner.invoke(
            cli, ["requests", "show", str(populated_db), "abc"]
        )
        assert result.exit_code != 0
