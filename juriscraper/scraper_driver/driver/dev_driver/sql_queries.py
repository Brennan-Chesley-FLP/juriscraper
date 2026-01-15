"""SQL queries for LocalDevDriver.

This module centralizes all SQL queries used by the dev_driver module,
making them easier to maintain, review, and test.

Usage:
    from juriscraper.scraper_driver.driver.dev_driver.sql_queries import SQL

    cursor = await db.execute(SQL.SELECT_RUN_METADATA, (1,))
"""

from __future__ import annotations


class SQL:
    """SQL queries used by LocalDevDriver.

    All queries are class attributes for easy access and documentation.
    """

    # --- Run Metadata ---

    SELECT_RUN_METADATA_BY_ID = "SELECT id FROM run_metadata WHERE id = 1"

    INSERT_RUN_METADATA = """
        INSERT INTO run_metadata (
            id, scraper_name, scraper_version, status,
            base_delay, jitter, num_workers, max_backoff_time
        ) VALUES (1, ?, ?, 'created', ?, ?, ?, ?)
    """

    UPDATE_RUN_STATUS_RUNNING = """
        UPDATE run_metadata SET status = 'running', started_at = CURRENT_TIMESTAMP WHERE id = 1
    """

    UPDATE_RUN_STATUS_FINAL = """
        UPDATE run_metadata
        SET status = ?, ended_at = CURRENT_TIMESTAMP, error_message = ?
        WHERE id = 1
    """

    UPDATE_RUN_STATUS_ON_CLOSE = """
        UPDATE run_metadata
        SET status = CASE
            WHEN status = 'running' THEN 'interrupted'
            ELSE status
        END,
        ended_at = CURRENT_TIMESTAMP
        WHERE id = 1
    """

    # --- Request Queue Restore ---

    RESET_IN_PROGRESS_TO_PENDING = (
        "UPDATE requests SET status = 'pending' WHERE status = 'in_progress'"
    )

    COUNT_PENDING_REQUESTS = (
        "SELECT COUNT(*) FROM requests WHERE status = 'pending'"
    )

    COUNT_ALL_REQUESTS = "SELECT COUNT(*) FROM requests"

    COUNT_ACTIVE_REQUESTS = "SELECT COUNT(*) FROM requests WHERE status IN ('pending', 'in_progress')"

    # --- Deduplication ---

    SELECT_REQUEST_BY_DEDUP_KEY = (
        "SELECT id FROM requests WHERE deduplication_key = ?"
    )

    # --- Parent Request Lookup ---

    SELECT_PARENT_REQUEST_ID = """
        SELECT id FROM requests WHERE url = ? AND status IN ('completed', 'in_progress') ORDER BY id DESC LIMIT 1
    """

    # --- Request Insert ---

    INSERT_REQUEST = """
        INSERT INTO requests (
            status, priority, queue_counter, request_type,
            method, url, headers_json, cookies_json, body,
            continuation, current_location,
            accumulated_data_json, aux_data_json, permanent_json,
            expected_type, deduplication_key, parent_request_id
        ) VALUES (
            'pending', ?, ?, ?,
            ?, ?, ?, ?, ?,
            ?, ?,
            ?, ?, ?,
            ?, ?, ?
        )
    """

    INSERT_ENTRY_REQUEST = """
        INSERT INTO requests (
            status, priority, queue_counter,
            method, url, headers_json, cookies_json, body,
            continuation, current_location,
            accumulated_data_json, aux_data_json, permanent_json,
            deduplication_key
        ) VALUES (
            'pending', ?, ?,
            ?, ?, ?, ?, ?,
            ?, ?,
            ?, ?, ?,
            ?
        )
    """

    INSERT_REQUEUE_REQUEST = """
        INSERT INTO requests (
            status, priority, queue_counter,
            method, url, headers_json, cookies_json, body,
            continuation, current_location,
            accumulated_data_json, aux_data_json, permanent_json,
            parent_request_id
        ) VALUES (
            'pending', ?, ?,
            ?, ?, ?, ?, ?,
            ?, ?,
            ?, ?, ?,
            ?
        )
    """

    # --- Get Next Request ---

    SELECT_NEXT_PENDING_REQUEST = """
        SELECT id, request_type, method, url, headers_json, cookies_json, body,
               continuation, current_location,
               accumulated_data_json, aux_data_json, permanent_json,
               expected_type, priority
        FROM requests
        WHERE status = 'pending'
          AND (started_at IS NULL OR started_at <= datetime('now'))
        ORDER BY priority ASC, queue_counter ASC
        LIMIT 1
    """

    UPDATE_REQUEST_IN_PROGRESS = """
        UPDATE requests SET status = 'in_progress', started_at = CURRENT_TIMESTAMP WHERE id = ?
    """

    # --- Request Status Updates ---

    UPDATE_REQUEST_COMPLETED = """
        UPDATE requests SET status = 'completed', completed_at = CURRENT_TIMESTAMP WHERE id = ?
    """

    UPDATE_REQUEST_FAILED = """
        UPDATE requests
        SET status = 'failed', completed_at = CURRENT_TIMESTAMP, last_error = ?
        WHERE id = ?
    """

    # --- Retry Logic ---

    SELECT_RETRY_STATE = (
        "SELECT retry_count, cumulative_backoff FROM requests WHERE id = ?"
    )

    UPDATE_REQUEST_FOR_RETRY = """
        UPDATE requests
        SET status = 'pending',
            retry_count = retry_count + 1,
            cumulative_backoff = ?,
            next_retry_delay = ?,
            last_error = ?,
            started_at = datetime('now', '+' || ? || ' seconds')
        WHERE id = ?
    """

    # --- Response Storage ---

    INSERT_RESPONSE = """
        INSERT INTO responses (
            request_id, status_code, headers_json, url,
            content_compressed, content_size_original, content_size_compressed,
            compression_dict_id, continuation, warc_record_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """

    # --- Result Storage ---

    INSERT_RESULT = """
        INSERT INTO results (
            request_id, result_type, data_json, is_valid, validation_errors_json
        ) VALUES (?, ?, ?, ?, ?)
    """

    # --- Step Control (Pause/Resume) ---

    UPDATE_PAUSE_STEP = """
        UPDATE requests
        SET status = 'held'
        WHERE status = 'pending' AND continuation = ?
    """

    UPDATE_RESUME_STEP = """
        UPDATE requests
        SET status = 'pending'
        WHERE status = 'held' AND continuation = ?
    """

    COUNT_HELD_BY_CONTINUATION = "SELECT COUNT(*) FROM requests WHERE status = 'held' AND continuation = ?"

    COUNT_ALL_HELD = "SELECT COUNT(*) FROM requests WHERE status = 'held'"

    # --- Error Requeue ---

    SELECT_ERROR_WITH_REQUEST = """
        SELECT e.id, e.request_id, e.is_resolved, r.method, r.url, r.headers_json,
               r.cookies_json, r.body, r.continuation, r.current_location,
               r.accumulated_data_json, r.aux_data_json, r.permanent_json, r.priority
        FROM errors e
        LEFT JOIN requests r ON e.request_id = r.id
        WHERE e.id = ?
    """

    # --- Batch Error Requeue ---
    # Note: This query template needs {where_clause} to be formatted in
    SELECT_ERRORS_FOR_REQUEUE = """
        SELECT e.id, e.request_id, r.method, r.url, r.headers_json,
               r.cookies_json, r.body, r.continuation, r.current_location,
               r.accumulated_data_json, r.aux_data_json, r.permanent_json, r.priority
        FROM errors e
        JOIN requests r ON e.request_id = r.id
        WHERE {where_clause}
    """

    # --- Response Content ---

    SELECT_RESPONSE_COMPRESSED = "SELECT content_compressed, compression_dict_id FROM responses WHERE id = ?"

    # --- Request Listing ---

    # Note: list_requests uses dynamic WHERE clause construction

    SELECT_REQUESTS_PAGE = """
        SELECT id, status, priority, queue_counter, method, url,
               continuation, current_location, created_at, started_at,
               completed_at, retry_count, cumulative_backoff, last_error
        FROM requests
        {where_clause}
        ORDER BY priority ASC, queue_counter ASC
        LIMIT ? OFFSET ?
    """

    # --- Response Listing ---

    SELECT_RESPONSES_PAGE = """
        SELECT id, request_id, status_code, url, content_size_original,
               content_size_compressed, continuation, created_at,
               compression_dict_id
        FROM responses
        {where_clause}
        ORDER BY id DESC
        LIMIT ? OFFSET ?
    """

    # --- Result Listing ---

    SELECT_RESULTS_PAGE = """
        SELECT id, request_id, result_type, data_json, is_valid,
               validation_errors_json, created_at
        FROM results
        {where_clause}
        ORDER BY id DESC
        LIMIT ? OFFSET ?
    """

    # --- Single Record Getters ---

    SELECT_REQUEST_BY_ID = """
        SELECT id, status, priority, queue_counter, method, url,
               continuation, current_location, created_at, started_at,
               completed_at, retry_count, cumulative_backoff, last_error
        FROM requests
        WHERE id = ?
    """

    SELECT_RESPONSE_BY_ID = """
        SELECT id, request_id, status_code, url, content_size_original,
               content_size_compressed, continuation, created_at,
               compression_dict_id
        FROM responses
        WHERE id = ?
    """

    SELECT_RESULT_BY_ID = """
        SELECT id, request_id, result_type, data_json, is_valid,
               validation_errors_json, created_at
        FROM results
        WHERE id = ?
    """

    # --- Request Cancellation ---

    UPDATE_CANCEL_REQUEST = """
        UPDATE requests
        SET status = 'failed', completed_at = CURRENT_TIMESTAMP,
            last_error = 'Cancelled by user'
        WHERE id = ? AND status IN ('pending', 'held')
    """

    UPDATE_CANCEL_BY_CONTINUATION = """
        UPDATE requests
        SET status = 'failed', completed_at = CURRENT_TIMESTAMP,
            last_error = 'Cancelled by user (batch)'
        WHERE continuation = ? AND status IN ('pending', 'held')
    """

    # --- Count Helpers ---

    @staticmethod
    def count_table(table: str, where_clause: str = "") -> str:
        """Generate a COUNT query for a table.

        Args:
            table: Table name (requests, responses, results).
            where_clause: Optional WHERE clause (without WHERE keyword).

        Returns:
            SQL query string.
        """
        if where_clause:
            return f"SELECT COUNT(*) FROM {table} WHERE {where_clause}"
        return f"SELECT COUNT(*) FROM {table}"

    # =========================================================================
    # errors.py queries
    # =========================================================================

    INSERT_ERROR = """
        INSERT INTO errors (
            request_id, error_type, error_class, message, request_url,
            context_json, selector, selector_type, expected_min, expected_max,
            actual_count, model_name, validation_errors_json, failed_doc_json,
            status_code, timeout_seconds, traceback
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """

    SELECT_ERROR_FULL = """
        SELECT id, request_id, error_type, error_class, message, request_url,
               context_json, selector, selector_type, expected_min, expected_max,
               actual_count, model_name, validation_errors_json, failed_doc_json,
               status_code, timeout_seconds, traceback, is_resolved, resolved_at,
               resolution_notes, created_at
        FROM errors
        WHERE id = ?
    """

    # Note: list_errors uses dynamic WHERE clause with {where_clause}
    # When continuation filter is used, table alias is 'e' for errors
    SELECT_ERRORS_LIST_WITH_JOIN = """
        SELECT e.id, e.request_id, e.error_type, e.error_class, e.message,
               e.request_url, e.context_json, e.selector, e.selector_type,
               e.expected_min, e.expected_max, e.actual_count, e.model_name,
               e.validation_errors_json, e.failed_doc_json, e.status_code,
               e.timeout_seconds, e.traceback, e.is_resolved, e.resolved_at,
               e.resolution_notes, e.created_at
        FROM errors e
        LEFT JOIN requests r ON e.request_id = r.id
        {where_clause}
        ORDER BY e.created_at DESC
        LIMIT ? OFFSET ?
    """

    SELECT_ERRORS_LIST = """
        SELECT id, request_id, error_type, error_class, message, request_url,
               context_json, selector, selector_type, expected_min, expected_max,
               actual_count, model_name, validation_errors_json, failed_doc_json,
               status_code, timeout_seconds, traceback, is_resolved, resolved_at,
               resolution_notes, created_at
        FROM errors e
        {where_clause}
        ORDER BY created_at DESC
        LIMIT ? OFFSET ?
    """

    UPDATE_RESOLVE_ERROR = """
        UPDATE errors
        SET is_resolved = 1, resolved_at = CURRENT_TIMESTAMP, resolution_notes = ?
        WHERE id = ? AND is_resolved = 0
    """

    # =========================================================================
    # stats.py queries
    # =========================================================================

    SELECT_QUEUE_STATS_BY_STATUS = (
        "SELECT status, COUNT(*) FROM requests GROUP BY status"
    )

    SELECT_QUEUE_STATS_BY_CONTINUATION = """
        SELECT continuation, status, COUNT(*)
        FROM requests
        GROUP BY continuation, status
    """

    SELECT_THROUGHPUT_STATS = """
        SELECT
            COUNT(*) as count,
            MIN(started_at) as first_start,
            MAX(completed_at) as last_complete,
            AVG(julianday(completed_at) - julianday(started_at)) * 86400 as avg_time
        FROM requests
        WHERE status = 'completed' AND started_at IS NOT NULL AND completed_at IS NOT NULL
    """

    SELECT_DURATION_SECONDS = "SELECT (julianday(?) - julianday(?)) * 86400"

    SELECT_COMPRESSION_STATS = """
        SELECT
            COUNT(*) as total,
            COALESCE(SUM(content_size_original), 0) as original,
            COALESCE(SUM(content_size_compressed), 0) as compressed,
            SUM(CASE WHEN compression_dict_id IS NOT NULL THEN 1 ELSE 0 END) as with_dict,
            SUM(CASE WHEN compression_dict_id IS NULL THEN 1 ELSE 0 END) as without_dict
        FROM responses
    """

    SELECT_RESULT_STATS = """
        SELECT
            COUNT(*) as total,
            SUM(CASE WHEN is_valid = 1 THEN 1 ELSE 0 END) as valid,
            SUM(CASE WHEN is_valid = 0 THEN 1 ELSE 0 END) as invalid
        FROM results
    """

    SELECT_RESULT_STATS_BY_TYPE = (
        "SELECT result_type, COUNT(*) FROM results GROUP BY result_type"
    )

    SELECT_ERROR_STATS = """
        SELECT
            COUNT(*) as total,
            SUM(CASE WHEN is_resolved = 0 THEN 1 ELSE 0 END) as unresolved,
            SUM(CASE WHEN is_resolved = 1 THEN 1 ELSE 0 END) as resolved
        FROM errors
    """

    SELECT_ERROR_STATS_BY_TYPE = (
        "SELECT error_type, COUNT(*) FROM errors GROUP BY error_type"
    )

    SELECT_ERROR_STATS_BY_CONTINUATION = """
        SELECT r.continuation, COUNT(e.id)
        FROM errors e
        JOIN requests r ON e.request_id = r.id
        GROUP BY r.continuation
    """

    SELECT_RUN_METADATA = (
        "SELECT scraper_name, status FROM run_metadata WHERE id = 1"
    )

    # =========================================================================
    # warc_export.py queries
    # =========================================================================

    SELECT_RESPONSES_FOR_WARC = """
        SELECT
            resp.id,
            resp.status_code,
            resp.headers_json,
            resp.url,
            resp.content_compressed,
            resp.compression_dict_id,
            resp.warc_record_id,
            req.method,
            req.url as request_url,
            req.headers_json as request_headers_json,
            req.body
        FROM responses resp
        JOIN requests req ON resp.request_id = req.id
        {where_clause}
        ORDER BY resp.id
    """

    SELECT_RESPONSES_FOR_WARC_BY_CONTINUATION = """
        SELECT
            resp.id,
            resp.status_code,
            resp.headers_json,
            resp.url,
            resp.content_compressed,
            resp.compression_dict_id,
            resp.warc_record_id,
            req.method,
            req.url as request_url,
            req.headers_json as request_headers_json,
            req.body
        FROM responses resp
        JOIN requests req ON resp.request_id = req.id
        WHERE resp.continuation = ?
        ORDER BY resp.id
    """

    # =========================================================================
    # rate_limiter.py queries
    # =========================================================================

    INSERT_RATE_ITEM = (
        "INSERT INTO rate_items (name, timestamp, weight) VALUES (?, ?, ?)"
    )

    DELETE_EXPIRED_RATE_ITEMS = "DELETE FROM rate_items WHERE timestamp < ?"

    DELETE_ALL_RATE_ITEMS = "DELETE FROM rate_items"

    SELECT_RATE_ITEMS_SUM_WEIGHT = (
        "SELECT COALESCE(SUM(weight), 0) FROM rate_items"
    )

    SELECT_RATE_ITEM_AT_INDEX = """
        SELECT name, timestamp, weight
        FROM rate_items
        ORDER BY timestamp DESC
        LIMIT 1 OFFSET ?
    """

    SELECT_RATE_WINDOW_STATS = """
        SELECT COALESCE(SUM(weight), 0), MIN(timestamp)
        FROM rate_items
        WHERE timestamp >= ?
    """

    # =========================================================================
    # compression.py queries
    # =========================================================================

    SELECT_COMPRESSION_DICT_LATEST = """
        SELECT id, dictionary_data
        FROM compression_dicts
        WHERE continuation = ?
        ORDER BY version DESC
        LIMIT 1
    """

    SELECT_COMPRESSION_DICT_DATA_BY_ID = (
        "SELECT dictionary_data FROM compression_dicts WHERE id = ?"
    )

    SELECT_RESPONSES_FOR_DICT_TRAINING = """
        SELECT content_compressed, compression_dict_id
        FROM responses
        WHERE continuation = ? AND content_compressed IS NOT NULL
        ORDER BY RANDOM()
        LIMIT ?
    """

    SELECT_NEXT_DICT_VERSION = """
        SELECT COALESCE(MAX(version), 0) + 1
        FROM compression_dicts
        WHERE continuation = ?
    """

    INSERT_COMPRESSION_DICT = """
        INSERT INTO compression_dicts (continuation, version, dictionary_data, sample_count)
        VALUES (?, ?, ?, ?)
    """

    SELECT_RESPONSES_FOR_RECOMPRESSION = """
        SELECT id, content_compressed, compression_dict_id
        FROM responses
        WHERE continuation = ? AND content_compressed IS NOT NULL
    """

    UPDATE_RESPONSE_RECOMPRESSED = """
        UPDATE responses
        SET content_compressed = ?,
            content_size_original = ?,
            content_size_compressed = ?,
            compression_dict_id = ?
        WHERE id = ?
    """

    # =========================================================================
    # run.py (CLI) queries
    # =========================================================================

    SELECT_RUN_STATUS_AND_NAME = (
        "SELECT status, scraper_name FROM run_metadata WHERE id = 1"
    )

    SELECT_REQUEST_COUNTS_BY_STATUS = (
        "SELECT status, COUNT(*) FROM requests GROUP BY status"
    )

    SELECT_ERROR_FOR_CLI_REQUEUE = """
        SELECT e.id, e.request_id, e.is_resolved, r.method, r.url, r.headers_json,
               r.cookies_json, r.body, r.continuation, r.current_location,
               r.accumulated_data_json, r.aux_data_json, r.permanent_json, r.priority
        FROM errors e
        LEFT JOIN requests r ON e.request_id = r.id
        WHERE e.id = ?
    """

    SELECT_ERRORS_BY_TYPE_FOR_CLI_REQUEUE = """
        SELECT e.id, e.request_id, r.method, r.url, r.headers_json,
               r.cookies_json, r.body, r.continuation, r.current_location,
               r.accumulated_data_json, r.aux_data_json, r.permanent_json, r.priority
        FROM errors e
        JOIN requests r ON e.request_id = r.id
        WHERE e.is_resolved = 0 AND e.error_type = ?
    """

    # =========================================================================
    # web/routes queries (shared across multiple route files)
    # =========================================================================

    # Used by web routes for error listing with pagination
    SELECT_ERRORS_PAGE_FOR_WEB = """
        SELECT id, request_id, error_type, error_class, message, request_url,
               is_resolved, resolved_at, resolution_notes, created_at,
               selector, selector_type, expected_min, expected_max, actual_count,
               model_name, status_code, timeout_seconds, traceback, context_json,
               validation_errors_json, failed_doc_json
        FROM errors
        {where_clause}
        ORDER BY created_at DESC
        LIMIT ? OFFSET ?
    """

    SELECT_ERROR_BY_ID_FOR_WEB = """
        SELECT id, request_id, error_type, error_class, message, request_url,
               is_resolved, resolved_at, resolution_notes, created_at,
               selector, selector_type, expected_min, expected_max, actual_count,
               model_name, status_code, timeout_seconds, traceback, context_json,
               validation_errors_json, failed_doc_json
        FROM errors
        WHERE id = ?
    """

    UPDATE_RESOLVE_ERROR_FOR_WEB = """
        UPDATE errors
        SET is_resolved = TRUE,
            resolved_at = CURRENT_TIMESTAMP,
            resolution_notes = ?
        WHERE id = ?
    """

    SELECT_ERROR_FOR_WEB_REQUEUE = """
        SELECT e.id, e.request_id, r.method, r.url, r.continuation,
               r.priority, r.headers_json, r.cookies_json, r.body,
               r.current_location, r.accumulated_data_json, r.aux_data_json,
               r.permanent_json
        FROM errors e
        LEFT JOIN requests r ON e.request_id = r.id
        WHERE e.id = ?
    """

    SELECT_LAST_INSERT_ROWID = "SELECT last_insert_rowid()"

    SELECT_ERROR_SUMMARY_FOR_WEB = """
        SELECT error_type, is_resolved, COUNT(*) as count
        FROM errors
        GROUP BY error_type, is_resolved
    """

    # compression routes
    SELECT_DICT_SAMPLE_COUNT = (
        "SELECT sample_count FROM compression_dicts WHERE id = ?"
    )

    SELECT_COMPRESSION_STATS_FOR_WEB = """
        SELECT
            COUNT(*) as total,
            COALESCE(SUM(content_size_original), 0) as total_original,
            COALESCE(SUM(content_size_compressed), 0) as total_compressed,
            COUNT(CASE WHEN compression_dict_id IS NOT NULL THEN 1 END) as with_dict,
            COUNT(CASE WHEN compression_dict_id IS NULL THEN 1 END) as no_dict
        FROM responses
    """

    SELECT_COMPRESSION_DICTS_FOR_WEB = """
        SELECT id, continuation, version, sample_count,
               LENGTH(dictionary_data) as size, created_at
        FROM compression_dicts
        ORDER BY created_at DESC
    """

    # export routes
    SELECT_WARC_PREVIEW_STATS = """
        SELECT COUNT(*), COALESCE(SUM(content_size_original), 0)
        FROM responses
        {where_clause}
    """

    # results routes
    SELECT_RESULTS_LIST_FOR_WEB = """
        SELECT id, request_id, result_type, is_valid, created_at
        FROM results
        {where_clause}
        ORDER BY created_at DESC
        LIMIT ? OFFSET ?
    """

    SELECT_RESULT_WITH_DATA_FOR_WEB = """
        SELECT id, request_id, result_type, data_json, is_valid,
               validation_errors_json, created_at
        FROM results
        WHERE id = ?
    """

    SELECT_RESULT_TYPE_SUMMARY = """
        SELECT result_type, COUNT(*) as count
        FROM results
        GROUP BY result_type
        ORDER BY count DESC
    """

    SELECT_RESULTS_SUMMARY_FOR_WEB = """
        SELECT
            result_type,
            SUM(CASE WHEN is_valid = 1 THEN 1 ELSE 0 END) as valid_count,
            SUM(CASE WHEN is_valid = 0 THEN 1 ELSE 0 END) as invalid_count,
            COUNT(*) as total_count
        FROM results
        GROUP BY result_type
        ORDER BY total_count DESC
    """

    SELECT_RESULTS_FOR_EXPORT = """
        SELECT id, request_id, result_type, data_json, is_valid,
               validation_errors_json, created_at
        FROM results
        {where_clause}
        ORDER BY created_at ASC
    """

    # responses routes
    SELECT_RESPONSES_LIST_FOR_WEB = """
        SELECT id, request_id, status_code, url, content_size_original,
               content_size_compressed, continuation, created_at, compression_dict_id
        FROM responses
        {where_clause}
        ORDER BY created_at DESC
        LIMIT ? OFFSET ?
    """

    SELECT_RESPONSE_BY_ID_FOR_WEB = """
        SELECT id, request_id, status_code, url, content_size_original,
               content_size_compressed, continuation, created_at, compression_dict_id
        FROM responses
        WHERE id = ?
    """

    SELECT_RESPONSE_CONTENT_FOR_WEB = """
        SELECT content_compressed, compression_dict_id, headers_json
        FROM responses
        WHERE id = ?
    """

    # requests routes
    SELECT_REQUESTS_LIST_FOR_WEB = """
        SELECT id, status, priority, queue_counter, method, url,
               continuation, current_location, created_at, started_at,
               completed_at, retry_count, cumulative_backoff, last_error
        FROM requests
        {where_clause}
        ORDER BY priority ASC, queue_counter ASC
        LIMIT ? OFFSET ?
    """

    SELECT_REQUEST_BY_ID_FOR_WEB = """
        SELECT id, status, priority, queue_counter, method, url,
               continuation, current_location, created_at, started_at,
               completed_at, retry_count, cumulative_backoff, last_error
        FROM requests
        WHERE id = ?
    """

    UPDATE_CANCEL_REQUEST_FOR_WEB = """
        UPDATE requests
        SET status = 'failed', completed_at = CURRENT_TIMESTAMP,
            last_error = 'Cancelled by user'
        WHERE id = ? AND status IN ('pending', 'held')
    """

    SELECT_REQUEST_STATUS = "SELECT status FROM requests WHERE id = ?"

    SELECT_REQUEST_FOR_WEB_REQUEUE = """
        SELECT id, method, url, continuation, priority,
               headers_json, cookies_json, body,
               current_location, accumulated_data_json, aux_data_json,
               permanent_json
        FROM requests
        WHERE id = ?
    """

    UPDATE_CANCEL_BY_CONTINUATION_FOR_WEB = """
        UPDATE requests
        SET status = 'failed', completed_at = CURRENT_TIMESTAMP,
            last_error = 'Cancelled by user (batch)'
        WHERE continuation = ? AND status IN ('pending', 'held')
    """

    # =========================================================================
    # archived_files queries
    # =========================================================================

    INSERT_ARCHIVED_FILE = """
        INSERT INTO archived_files (
            request_id, file_path, original_url, expected_type, file_size, content_hash
        ) VALUES (?, ?, ?, ?, ?, ?)
    """

    SELECT_ARCHIVED_FILES_LIST = """
        SELECT af.id, af.request_id, af.file_path, af.original_url,
               af.expected_type, af.file_size, af.content_hash, af.created_at,
               r.continuation
        FROM archived_files af
        LEFT JOIN requests r ON af.request_id = r.id
        {where_clause}
        ORDER BY af.created_at DESC
        LIMIT ? OFFSET ?
    """

    SELECT_ARCHIVED_FILE_BY_ID = """
        SELECT af.id, af.request_id, af.file_path, af.original_url,
               af.expected_type, af.file_size, af.content_hash, af.created_at,
               r.continuation
        FROM archived_files af
        LEFT JOIN requests r ON af.request_id = r.id
        WHERE af.id = ?
    """

    SELECT_ARCHIVED_FILE_BY_URL = """
        SELECT id, file_path, file_size, content_hash
        FROM archived_files
        WHERE original_url = ?
        ORDER BY created_at DESC
        LIMIT 1
    """

    SELECT_ARCHIVED_FILES_STATS = """
        SELECT
            COUNT(*) as total_files,
            COALESCE(SUM(file_size), 0) as total_size
        FROM archived_files
    """
