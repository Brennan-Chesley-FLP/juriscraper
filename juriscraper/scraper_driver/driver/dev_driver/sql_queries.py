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
            base_delay, jitter, num_workers, max_backoff_time,
            speculation_config_json
        ) VALUES (1, ?, ?, 'created', ?, ?, ?, ?, ?)
    """

    UPDATE_SPECULATION_CONFIG = """
        UPDATE run_metadata SET speculation_config_json = ? WHERE id = 1
    """

    SELECT_SPECULATION_CONFIG = """
        SELECT speculation_config_json FROM run_metadata WHERE id = 1
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

    COUNT_IN_PROGRESS_REQUESTS = (
        "SELECT COUNT(*) FROM requests WHERE status = 'in_progress'"
    )

    # --- Scheduled Retries ---

    # Get the minimum time until a scheduled retry becomes available
    # Returns seconds until next retry, or NULL if no scheduled retries
    SELECT_NEXT_SCHEDULED_RETRY_DELAY = """
        SELECT MIN(
            CASE
                WHEN started_at > datetime('now') THEN
                    (julianday(started_at) - julianday('now')) * 86400.0
                ELSE NULL
            END
        ) as seconds_until_ready
        FROM requests
        WHERE status = 'pending' AND started_at > datetime('now')
    """

    # Count pending requests that are scheduled for later (not immediately available)
    COUNT_SCHEDULED_RETRIES = """
        SELECT COUNT(*) FROM requests
        WHERE status = 'pending' AND started_at > datetime('now')
    """

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
            expected_type, deduplication_key, parent_request_id,
            created_at_ns, cache_key
        ) VALUES (
            'pending', ?, ?, ?,
            ?, ?, ?, ?, ?,
            ?, ?,
            ?, ?, ?,
            ?, ?, ?,
            ?, ?
        )
    """

    INSERT_ENTRY_REQUEST = """
        INSERT INTO requests (
            status, priority, queue_counter,
            method, url, headers_json, cookies_json, body,
            continuation, current_location,
            accumulated_data_json, aux_data_json, permanent_json,
            deduplication_key, created_at_ns
        ) VALUES (
            'pending', ?, ?,
            ?, ?, ?, ?, ?,
            ?, ?,
            ?, ?, ?,
            ?, ?
        )
    """

    INSERT_REQUEUE_REQUEST = """
        INSERT INTO requests (
            status, priority, queue_counter,
            request_type, expected_type,
            method, url, headers_json, cookies_json, body,
            continuation, current_location,
            accumulated_data_json, aux_data_json, permanent_json,
            parent_request_id, created_at_ns
        ) VALUES (
            'pending', ?, ?,
            ?, ?,
            ?, ?, ?, ?, ?,
            ?, ?,
            ?, ?, ?,
            ?, ?
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

    # Atomic dequeue: UPDATE the next pending request to 'in_progress' and return it.
    # This prevents race conditions where multiple workers could select the same request.
    # Uses a subquery to find the next request and UPDATE ... RETURNING to atomically
    # claim and return it in a single operation.
    # Parameter: started_at_ns (monotonic timestamp for duration tracking)
    DEQUEUE_NEXT_REQUEST = """
        UPDATE requests
        SET status = 'in_progress',
            started_at = CURRENT_TIMESTAMP,
            started_at_ns = ?
        WHERE id = (
            SELECT id FROM requests
            WHERE status = 'pending'
              AND (started_at IS NULL OR started_at <= datetime('now'))
            ORDER BY priority ASC, queue_counter ASC
            LIMIT 1
        )
        RETURNING id, request_type, method, url, headers_json, cookies_json, body,
                  continuation, current_location,
                  accumulated_data_json, aux_data_json, permanent_json,
                  expected_type, priority
    """

    UPDATE_REQUEST_IN_PROGRESS = """
        UPDATE requests SET status = 'in_progress', started_at = CURRENT_TIMESTAMP, started_at_ns = ? WHERE id = ?
    """

    # --- Request Status Updates ---

    UPDATE_REQUEST_COMPLETED = """
        UPDATE requests SET status = 'completed', completed_at = CURRENT_TIMESTAMP, completed_at_ns = ? WHERE id = ?
    """

    UPDATE_REQUEST_FAILED = """
        UPDATE requests
        SET status = 'failed', completed_at = CURRENT_TIMESTAMP, completed_at_ns = ?, last_error = ?
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
            compression_dict_id, continuation, warc_record_id, speculation_outcome
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """

    # Get most recent successful response by cache key (hash of method+url+body+headers)
    # Only returns 2xx responses. Gets the most recent one.
    # The cache_key is stored in the requests table, looked up via response's request_id
    SELECT_CACHED_RESPONSE_BY_KEY = """
        SELECT r.id, r.request_id, r.status_code, r.headers_json, r.url,
               r.content_compressed, r.compression_dict_id, r.created_at,
               req.method
        FROM responses r
        JOIN requests req ON r.request_id = req.id
        WHERE req.cache_key = ? AND r.status_code >= 200 AND r.status_code < 300
        ORDER BY r.id DESC
        LIMIT 1
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
               r.accumulated_data_json, r.aux_data_json, r.permanent_json, r.priority,
               r.request_type, r.expected_type
        FROM errors e
        LEFT JOIN requests r ON e.request_id = r.id
        WHERE e.id = ?
    """

    # --- Batch Error Requeue ---
    # Note: This query template needs {where_clause} to be formatted in
    SELECT_ERRORS_FOR_REQUEUE = """
        SELECT e.id, e.request_id, r.method, r.url, r.headers_json,
               r.cookies_json, r.body, r.continuation, r.current_location,
               r.accumulated_data_json, r.aux_data_json, r.permanent_json, r.priority,
               r.request_type, r.expected_type
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
               completed_at, retry_count, cumulative_backoff, last_error,
               created_at_ns, started_at_ns, completed_at_ns
        FROM requests
        {where_clause}
        ORDER BY priority ASC, queue_counter ASC
        LIMIT ? OFFSET ?
    """

    # --- Response Listing ---

    SELECT_RESPONSES_PAGE = """
        SELECT id, request_id, status_code, url, content_size_original,
               content_size_compressed, continuation, created_at,
               compression_dict_id, speculation_outcome
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
               completed_at, retry_count, cumulative_backoff, last_error,
               created_at_ns, started_at_ns, completed_at_ns
        FROM requests
        WHERE id = ?
    """

    SELECT_RESPONSE_BY_ID = """
        SELECT id, request_id, status_code, url, content_size_original,
               content_size_compressed, continuation, created_at,
               compression_dict_id, speculation_outcome
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
        SET status = 'failed', completed_at = CURRENT_TIMESTAMP, completed_at_ns = ?,
            last_error = 'Cancelled by user'
        WHERE id = ? AND status IN ('pending', 'held')
    """

    UPDATE_CANCEL_BY_CONTINUATION = """
        UPDATE requests
        SET status = 'failed', completed_at = CURRENT_TIMESTAMP, completed_at_ns = ?,
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
               r.accumulated_data_json, r.aux_data_json, r.permanent_json, r.priority,
               r.request_type, r.expected_type
        FROM errors e
        LEFT JOIN requests r ON e.request_id = r.id
        WHERE e.id = ?
    """

    SELECT_ERRORS_BY_TYPE_FOR_CLI_REQUEUE = """
        SELECT e.id, e.request_id, r.method, r.url, r.headers_json,
               r.cookies_json, r.body, r.continuation, r.current_location,
               r.accumulated_data_json, r.aux_data_json, r.permanent_json, r.priority,
               r.request_type, r.expected_type
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
               r.permanent_json, r.request_type, r.expected_type
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
               content_size_compressed, continuation, created_at, compression_dict_id,
               speculation_outcome
        FROM responses
        {where_clause}
        ORDER BY created_at DESC
        LIMIT ? OFFSET ?
    """

    SELECT_RESPONSE_BY_ID_FOR_WEB = """
        SELECT id, request_id, status_code, url, content_size_original,
               content_size_compressed, continuation, created_at, compression_dict_id,
               speculation_outcome
        FROM responses
        WHERE id = ?
    """

    SELECT_SPECULATION_SUMMARY_FOR_WEB = """
        SELECT speculation_outcome, COUNT(*) as count
        FROM responses
        GROUP BY speculation_outcome
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
               completed_at, retry_count, cumulative_backoff, last_error,
               created_at_ns, started_at_ns, completed_at_ns
        FROM requests
        {where_clause}
        ORDER BY priority ASC, queue_counter ASC
        LIMIT ? OFFSET ?
    """

    SELECT_REQUEST_BY_ID_FOR_WEB = """
        SELECT id, status, priority, queue_counter, method, url,
               continuation, current_location, created_at, started_at,
               completed_at, retry_count, cumulative_backoff, last_error,
               created_at_ns, started_at_ns, completed_at_ns
        FROM requests
        WHERE id = ?
    """

    UPDATE_CANCEL_REQUEST_FOR_WEB = """
        UPDATE requests
        SET status = 'failed', completed_at = CURRENT_TIMESTAMP, completed_at_ns = ?,
            last_error = 'Cancelled by user'
        WHERE id = ? AND status IN ('pending', 'held')
    """

    SELECT_REQUEST_STATUS = "SELECT status FROM requests WHERE id = ?"

    SELECT_REQUEST_FOR_WEB_REQUEUE = """
        SELECT id, method, url, continuation, priority,
               headers_json, cookies_json, body,
               current_location, accumulated_data_json, aux_data_json,
               permanent_json, request_type, expected_type
        FROM requests
        WHERE id = ?
    """

    UPDATE_CANCEL_BY_CONTINUATION_FOR_WEB = """
        UPDATE requests
        SET status = 'failed', completed_at = CURRENT_TIMESTAMP, completed_at_ns = ?,
            last_error = 'Cancelled by user (batch)'
        WHERE continuation = ? AND status IN ('pending', 'held')
    """

    SELECT_REQUESTS_FOR_BATCH_REQUEUE = """
        SELECT id, method, url, continuation, priority,
               headers_json, cookies_json, body,
               current_location, accumulated_data_json, aux_data_json,
               permanent_json, request_type, expected_type
        FROM requests
        WHERE continuation = ? AND status = ?
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

    # --- Speculative Progress Tracking ---

    UPSERT_SPECULATIVE_PROGRESS = """
        INSERT INTO speculative_progress (step_name, latest_speculative_id, updated_at)
        VALUES (?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(step_name) DO UPDATE SET
            latest_speculative_id = MAX(latest_speculative_id, excluded.latest_speculative_id),
            updated_at = CURRENT_TIMESTAMP
    """

    SELECT_SPECULATIVE_PROGRESS = """
        SELECT latest_speculative_id FROM speculative_progress WHERE step_name = ?
    """

    SELECT_ALL_SPECULATIVE_PROGRESS = """
        SELECT step_name, latest_speculative_id, updated_at FROM speculative_progress
    """

    # --- Speculative Start IDs (for restart-speculative feature) ---

    UPSERT_SPECULATIVE_START_ID = """
        INSERT INTO speculative_start_ids (step_name, starting_id, updated_at)
        VALUES (?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(step_name) DO UPDATE SET
            starting_id = excluded.starting_id,
            updated_at = CURRENT_TIMESTAMP
    """

    SELECT_SPECULATIVE_START_IDS = """
        SELECT step_name, starting_id FROM speculative_start_ids
    """

    DELETE_SPECULATIVE_START_ID = """
        DELETE FROM speculative_start_ids WHERE step_name = ?
    """

    DELETE_ALL_SPECULATIVE_START_IDS = """
        DELETE FROM speculative_start_ids
    """

    # --- Speculation Tracking (new @speculate pattern) ---

    UPSERT_SPECULATION_TRACKING = """
        INSERT INTO speculation_tracking (
            func_name, highest_successful_id, consecutive_failures,
            current_ceiling, stopped, updated_at
        ) VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(func_name) DO UPDATE SET
            highest_successful_id = excluded.highest_successful_id,
            consecutive_failures = excluded.consecutive_failures,
            current_ceiling = excluded.current_ceiling,
            stopped = excluded.stopped,
            updated_at = CURRENT_TIMESTAMP
    """

    SELECT_SPECULATION_TRACKING = """
        SELECT func_name, highest_successful_id, consecutive_failures,
               current_ceiling, stopped, updated_at
        FROM speculation_tracking WHERE func_name = ?
    """

    SELECT_ALL_SPECULATION_TRACKING = """
        SELECT func_name, highest_successful_id, consecutive_failures,
               current_ceiling, stopped, updated_at
        FROM speculation_tracking
    """

    DELETE_SPECULATION_TRACKING = """
        DELETE FROM speculation_tracking WHERE func_name = ?
    """

    DELETE_ALL_SPECULATION_TRACKING = """
        DELETE FROM speculation_tracking
    """

    # =========================================================================
    # ATB Rate Limiter State
    # =========================================================================

    SELECT_RATE_LIMITER_STATE = """
        SELECT tokens, rate, bucket_size, last_congestion_rate, jitter,
               last_used_at, total_requests, total_successes, total_rate_limited,
               created_at, updated_at
        FROM rate_limiter_state
        WHERE id = 1
    """

    UPSERT_RATE_LIMITER_STATE = """
        INSERT INTO rate_limiter_state (
            id, tokens, rate, bucket_size, last_congestion_rate, jitter,
            last_used_at, total_requests, total_successes, total_rate_limited,
            updated_at
        ) VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(id) DO UPDATE SET
            tokens = excluded.tokens,
            rate = excluded.rate,
            bucket_size = excluded.bucket_size,
            last_congestion_rate = excluded.last_congestion_rate,
            jitter = excluded.jitter,
            last_used_at = excluded.last_used_at,
            total_requests = excluded.total_requests,
            total_successes = excluded.total_successes,
            total_rate_limited = excluded.total_rate_limited,
            updated_at = CURRENT_TIMESTAMP
    """

    UPDATE_RATE_LIMITER_TOKENS = """
        UPDATE rate_limiter_state
        SET tokens = ?, last_used_at = ?, updated_at = CURRENT_TIMESTAMP
        WHERE id = 1
    """

    UPDATE_RATE_LIMITER_RATE_INCREASE = """
        UPDATE rate_limiter_state
        SET rate = ?, total_requests = total_requests + 1,
            total_successes = total_successes + 1, updated_at = CURRENT_TIMESTAMP
        WHERE id = 1
    """

    UPDATE_RATE_LIMITER_RATE_DECREASE = """
        UPDATE rate_limiter_state
        SET rate = ?, last_congestion_rate = ?, tokens = 0,
            total_requests = total_requests + 1,
            total_rate_limited = total_rate_limited + 1,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = 1
    """

    UPDATE_RATE_LIMITER_SUCCESS = """
        UPDATE rate_limiter_state
        SET total_requests = total_requests + 1,
            total_successes = total_successes + 1,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = 1
    """

    UPDATE_RATE_LIMITER_RATE_LIMITED = """
        UPDATE rate_limiter_state
        SET total_requests = total_requests + 1,
            total_rate_limited = total_rate_limited + 1,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = 1
    """

    # =========================================================================
    # Enhanced Requeue Queries
    # =========================================================================

    # Recursive CTE to find all downstream requests via parent_request_id
    # Parameter: request_id (the root request ID to start traversal from)
    SELECT_DOWNSTREAM_REQUEST_IDS = """
        WITH RECURSIVE downstream AS (
            SELECT id FROM requests WHERE parent_request_id = ?
            UNION ALL
            SELECT r.id FROM requests r
            INNER JOIN downstream d ON r.parent_request_id = d.id
        )
        SELECT id FROM downstream
    """

    # Get request_id from a response_id
    SELECT_REQUEST_ID_BY_RESPONSE = """
        SELECT request_id FROM responses WHERE id = ?
    """

    # Delete responses by request IDs
    # Note: Uses dynamic IN clause, caller must format with placeholders
    DELETE_RESPONSES_BY_REQUEST_IDS = """
        DELETE FROM responses WHERE request_id IN ({placeholders})
    """

    # Delete results by request IDs
    # Note: Uses dynamic IN clause, caller must format with placeholders
    DELETE_RESULTS_BY_REQUEST_IDS = """
        DELETE FROM results WHERE request_id IN ({placeholders})
    """

    # Delete errors by request IDs
    # Note: Uses dynamic IN clause, caller must format with placeholders
    DELETE_ERRORS_BY_REQUEST_IDS = """
        DELETE FROM errors WHERE request_id IN ({placeholders})
    """

    # Delete requests by IDs
    # Note: Uses dynamic IN clause, caller must format with placeholders
    DELETE_REQUESTS_BY_IDS = """
        DELETE FROM requests WHERE id IN ({placeholders})
    """

    # Select response IDs by request IDs (for tracking what will be deleted)
    # Note: Uses dynamic IN clause, caller must format with placeholders
    SELECT_RESPONSE_IDS_BY_REQUEST_IDS = """
        SELECT id FROM responses WHERE request_id IN ({placeholders})
    """

    # Select result IDs by request IDs (for tracking what will be deleted)
    # Note: Uses dynamic IN clause, caller must format with placeholders
    SELECT_RESULT_IDS_BY_REQUEST_IDS = """
        SELECT id FROM results WHERE request_id IN ({placeholders})
    """

    # Select error IDs by request IDs (for tracking what will be deleted)
    # Note: Uses dynamic IN clause, caller must format with placeholders
    SELECT_ERROR_IDS_BY_REQUEST_IDS = """
        SELECT id FROM errors WHERE request_id IN ({placeholders})
    """

    # =========================================================================
    # sql_manager.py additional queries
    # =========================================================================

    # Full run metadata for get_run_metadata()
    SELECT_RUN_METADATA_FULL = """
        SELECT scraper_name, scraper_version, status, created_at, started_at,
               ended_at, error_message, base_delay, jitter, num_workers,
               max_backoff_time, speculation_config_json
        FROM run_metadata WHERE id = 1
    """

    # Get permanent_json for a request (used by resume step)
    SELECT_PERMANENT_JSON_BY_REQUEST_ID = """
        SELECT permanent_json FROM requests WHERE id = ?
    """

    # Get responses for JSON validation
    SELECT_RESPONSES_FOR_JSON_VALIDATION = """
        SELECT id, request_id, content_compressed, compression_dict_id
        FROM responses
        WHERE continuation = ?
    """

    # Get request data for requeue operations
    # Note: Uses dynamic IN clause, caller must format with placeholders
    SELECT_REQUESTS_FOR_REQUEUE_BY_IDS = """
        SELECT id, method, url, continuation, priority,
               headers_json, cookies_json, body,
               current_location, accumulated_data_json, aux_data_json,
               permanent_json, request_type, expected_type
        FROM requests
        WHERE id IN ({placeholders})
    """

    # Delete responses by response ID (not request_id)
    # Note: Uses dynamic IN clause, caller must format with placeholders
    DELETE_RESPONSES_BY_IDS = """
        DELETE FROM responses WHERE id IN ({placeholders})
    """

    # Delete results by result ID
    # Note: Uses dynamic IN clause, caller must format with placeholders
    DELETE_RESULTS_BY_IDS = """
        DELETE FROM results WHERE id IN ({placeholders})
    """

    # Delete errors by error ID
    # Note: Uses dynamic IN clause, caller must format with placeholders
    DELETE_ERRORS_BY_IDS = """
        DELETE FROM errors WHERE id IN ({placeholders})
    """

    # Get error ID and request_id for requeue_error
    SELECT_ERROR_ID_AND_REQUEST_ID = """
        SELECT id, request_id FROM errors WHERE id = ?
    """

    # Get distinct request IDs for requeue_continuation with error filtering
    # Note: Uses dynamic WHERE clause, caller must format with {where_clause}
    SELECT_REQUEST_IDS_WITH_ERROR_FILTER = """
        SELECT DISTINCT r.id
        FROM requests r
        INNER JOIN errors e ON e.request_id = r.id
        WHERE {where_clause}
    """

    # Get request IDs for requeue_continuation (completed requests)
    SELECT_REQUEST_IDS_BY_CONTINUATION_COMPLETED = """
        SELECT id
        FROM requests
        WHERE continuation = ? AND status = 'completed'
    """

    # Get unresolved error IDs by request IDs (for bulk resolution)
    # Note: Uses dynamic IN clause, caller must format with placeholders
    SELECT_UNRESOLVED_ERROR_IDS_BY_REQUEST_IDS = """
        SELECT e.id
        FROM errors e
        WHERE e.request_id IN ({placeholders})
          AND e.is_resolved = 0
    """

    # Bulk resolve errors with resolution note
    # Note: Uses dynamic IN clause, caller must format with placeholders
    BULK_RESOLVE_ERRORS = """
        UPDATE errors
        SET is_resolved = 1,
            resolved_at = CURRENT_TIMESTAMP,
            resolution_notes = ?
        WHERE id IN ({placeholders})
    """

    # Batch mark errors as resolved (used by batch_requeue_errors)
    # Note: Uses dynamic IN clause, caller must format with placeholders
    BATCH_MARK_ERRORS_RESOLVED = """
        UPDATE errors
        SET is_resolved = 1, resolved_at = CURRENT_TIMESTAMP,
            resolution_notes = 'Batch requeued'
        WHERE id IN ({placeholders})
    """
