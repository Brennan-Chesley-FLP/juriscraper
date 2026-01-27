# LocalDevDriverDebugger Specification

## Purpose

The LocalDevDriverDebugger (LDDD) provides a standalone interface for inspecting and manipulating LocalDevDriver run databases without requiring the full driver runtime. It supports both read-only inspection (viewing requests, responses, errors, results, stats) and safe manipulation operations (requeue, cancel, resolve errors, compression management).

## ADDED Requirements

<!-- Request Inspection -->

### Requirement: Request Listing and Filtering

The system SHALL provide paginated request listing with filtering capabilities.

#### Scenario: List requests with status filter
- **WHEN** `debugger.list_requests(status="failed", limit=50, offset=0)` is called
- **THEN** the system SHALL return a `Page[RequestRecord]` containing up to 50 failed requests
- **AND** include total count for pagination

#### Scenario: List requests by continuation
- **WHEN** `debugger.list_requests(continuation="parse_results")` is called
- **THEN** only requests with that continuation SHALL be returned

#### Scenario: Get single request
- **WHEN** `debugger.get_request(request_id=123)` is called
- **THEN** the system SHALL return the full `RequestRecord` or `None` if not found

### Requirement: Request Summary Statistics

The system SHALL provide aggregated request statistics.

#### Scenario: Request summary by status and continuation
- **WHEN** `debugger.get_request_summary()` is called
- **THEN** the system SHALL return counts grouped by (continuation, status)
- **AND** include totals for each status across all continuations

<!-- Response Inspection -->

### Requirement: Response Listing and Content Access

The system SHALL provide response listing and content decompression.

#### Scenario: List responses with filters
- **WHEN** `debugger.list_responses(continuation="parse_results", speculation_outcome="success")` is called
- **THEN** only matching responses SHALL be returned

#### Scenario: Get response metadata
- **WHEN** `debugger.get_response(response_id=456)` is called
- **THEN** the system SHALL return `ResponseRecord` with metadata (status_code, url, content_size, compression_ratio)

#### Scenario: Get decompressed response content
- **WHEN** `debugger.get_response_content(response_id=456)` is called
- **THEN** the system SHALL decompress using the stored zstd dictionary
- **AND** return the original bytes

#### Scenario: Get response with headers
- **WHEN** `debugger.get_response_content_with_headers(response_id=456)` is called
- **THEN** the system SHALL return a tuple of (content_bytes, headers_dict)

### Requirement: Speculation Summary

The system SHALL provide speculation outcome statistics.

#### Scenario: Speculation outcome breakdown
- **WHEN** `debugger.get_speculation_summary()` is called
- **THEN** the system SHALL return counts for: success, stopped, skipped, non_speculative

<!-- Error Inspection -->

### Requirement: Error Listing and Details

The system SHALL provide error listing with filtering and full details.

#### Scenario: List errors by type
- **WHEN** `debugger.list_errors(error_type="structural", is_resolved=False)` is called
- **THEN** only unresolved structural errors SHALL be returned

#### Scenario: Get error with traceback
- **WHEN** `debugger.get_error(error_id=789)` is called
- **THEN** the system SHALL return full error details including traceback, selector, validation_errors

### Requirement: Error Summary Statistics

The system SHALL provide error statistics by type and resolution status.

#### Scenario: Error summary breakdown
- **WHEN** `debugger.get_error_summary()` is called
- **THEN** the system SHALL return counts grouped by (error_type, is_resolved)

<!-- Result Inspection -->

### Requirement: Result Listing and Export

The system SHALL provide result listing with validation status and export capabilities.

#### Scenario: List results by type and validity
- **WHEN** `debugger.list_results(result_type="Opinion", is_valid=True)` is called
- **THEN** only valid Opinion results SHALL be returned

#### Scenario: Get result with validation errors
- **WHEN** `debugger.get_result(result_id=101)` is called
- **THEN** the system SHALL return the full result data and any validation_errors

#### Scenario: Export results as JSONL stream
- **WHEN** `debugger.export_results_jsonl()` is called
- **THEN** the system SHALL yield result dicts as a generator for streaming export
- **AND** include result_type and is_valid metadata with each record

### Requirement: Result Summary Statistics

The system SHALL provide result statistics by type and validation status.

#### Scenario: Result summary breakdown
- **WHEN** `debugger.get_result_summary()` is called
- **THEN** the system SHALL return counts grouped by (result_type, is_valid)

<!-- Run Metadata and Stats -->

### Requirement: Run Metadata Access

The system SHALL provide access to run configuration and status.

#### Scenario: Get run metadata
- **WHEN** `debugger.get_run_metadata()` is called
- **THEN** the system SHALL return scraper_name, version, status, timestamps, worker config, speculation config, scraper params.

### Requirement: Comprehensive Statistics

The system SHALL provide aggregated statistics across all aspects of a run.

#### Scenario: Get full stats
- **WHEN** `debugger.get_stats()` is called
- **THEN** the system SHALL return a `DevDriverStats` object with:
  - Queue stats (pending, in_progress, completed, failed, held counts)
  - Throughput stats (requests/sec, avg duration)
  - Error breakdown by type
  - Result breakdown by type
  - Compression stats (total size, compressed size, ratio)

<!-- Debugging and Diagnosis -->

### Requirement: Response Diagnosis

The system SHALL support re-running continuations to diagnose response handling.

#### Scenario: Diagnose response with XPath observation
- **WHEN** `debugger.diagnose(response_id=456)` is called
- **THEN** the system SHALL re-run the continuation method for that response
- **AND** capture XPath/CSS selectors used with match counts
- **AND** return yields produced and any errors

<!-- Request Manipulation -->

### Requirement: Request Cancellation

The system SHALL support cancelling pending or held requests.

#### Scenario: Cancel single request
- **WHEN** `debugger.cancel_request(request_id=123)` is called
- **AND** the request status is "pending" or "held"
- **THEN** the status SHALL change to "cancelled"
- **AND** return True

#### Scenario: Cancel request in wrong state
- **WHEN** `debugger.cancel_request(request_id=123)` is called
- **AND** the request status is "completed" or "in_progress"
- **THEN** return False without modification

#### Scenario: Batch cancel by continuation
- **WHEN** `debugger.cancel_requests_by_continuation(continuation="parse_results")` is called
- **THEN** all pending/held requests for that continuation SHALL be cancelled
- **AND** return the count of cancelled requests

### Requirement: Request Requeue

The system SHALL support requeuing failed requests with optional cleanup.

#### Scenario: Requeue single request
- **WHEN** `debugger.requeue_request(request_id=123)` is called
- **THEN** a new pending request SHALL be created with the same parameters
- **AND** return the new request_id

#### Scenario: Requeue with response clearing
- **WHEN** `debugger.requeue_request(request_id=123, clear_responses=True)` is called
- **THEN** existing responses for that request SHALL be deleted
- **AND** a new pending request SHALL be created

#### Scenario: Requeue with downstream clearing
- **WHEN** `debugger.requeue_request(request_id=123, clear_downstream=True)` is called
- **THEN** all child requests and results (requests or results spawned from this one) SHALL be recursively cleared
- **AND** their responses and results SHALL be deleted

#### Scenario: Batch requeue by continuation
- **WHEN** `debugger.requeue_continuation(continuation="parse_results", dry_run=True)` is called
- **THEN** the system SHALL return a preview of what would be requeued without making changes

#### Scenario: Batch requeue completed requests
- **WHEN** `debugger.requeue_continuation(continuation="parse_results", clear_responses=True)` is called
- **THEN** all completed requests for that continuation SHALL be requeued
- **AND** their responses SHALL be cleared

<!-- Error Manipulation -->

### Requirement: Error Resolution

The system SHALL support marking errors as resolved.

#### Scenario: Resolve error with notes
- **WHEN** `debugger.resolve_error(error_id=789, notes="Fixed selector in v2.1")` is called
- **THEN** the error is_resolved SHALL be set to True
- **AND** resolution_notes and resolution_timestamp SHALL be recorded

### Requirement: Error Requeue

The system SHALL support requeuing the request that caused an error.

#### Scenario: Requeue error's request
- **WHEN** `debugger.requeue_error(error_id=789)` is called
- **THEN** the request associated with that error SHALL be requeued
- **AND** return the new request_id

#### Scenario: Batch requeue errors by type
- **WHEN** `debugger.batch_requeue_errors(continuation="parse_results", error_type="structural", dry_run=False)` is called
- **THEN** all matching errors' requests SHALL be requeued
- **AND** return count of requeued requests

#### Scenario: Batch requeue with traceback filter
- **WHEN** `debugger.batch_requeue_errors(traceback_contains="TimeoutError")` is called
- **THEN** only errors with matching traceback text SHALL be requeued

<!-- Compression Management -->

### Requirement: Compression Statistics

The system SHALL provide compression statistics.

#### Scenario: Overall compression stats
- **WHEN** `debugger.get_compression_stats()` is called
- **THEN** the system SHALL return total_original_size, total_compressed_size, overall_ratio

#### Scenario: Per-continuation compression stats
- **WHEN** `debugger.get_compression_stats_by_continuation()` is called
- **THEN** the system SHALL return stats broken down by continuation name

### Requirement: Dictionary Management

The system SHALL support listing and training compression dictionaries.

#### Scenario: List compression dictionaries
- **WHEN** `debugger.list_compression_dicts()` is called
- **THEN** the system SHALL return all dictionaries with continuation, version, sample_count

#### Scenario: Train new dictionary
- **WHEN** `debugger.train_compression_dict(continuation="parse_results", sample_size=1000)` is called
- **THEN** the system SHALL train a new zstd dictionary from response samples
- **AND** return the new dictionary_id

### Requirement: Response Recompression

The system SHALL support recompressing responses with new dictionaries.

#### Scenario: Recompress continuation responses
- **WHEN** `debugger.recompress_responses(continuation="parse_results", dict_id=5)` is called
- **THEN** all responses for that continuation SHALL be recompressed with the new dictionary
- **AND** return count of recompressed responses

<!-- Rate Limiter Inspection -->

### Requirement: Rate Limiter State Access

The system SHALL provide access to rate limiter state and throughput.

#### Scenario: Get rate limiter state
- **WHEN** `debugger.get_rate_limiter_state()` is called
- **THEN** the system SHALL return tokens, rate, bucket_size, last_congestion_rate

#### Scenario: Get throughput stats
- **WHEN** `debugger.get_throughput_stats()` is called
- **THEN** the system SHALL return requests/sec over time windows (5m, 15m, 1h, 1d)
- **AND** include total_requests, total_successes, success_rate

<!-- Speculation Inspection -->

### Requirement: Speculation State Access

The system SHALL provide access to speculation tracking state.

#### Scenario: Get all speculation progress
- **WHEN** `debugger.get_all_speculative_progress()` is called
- **THEN** the system SHALL return a dict mapping func_name to latest_speculative_id

#### Scenario: Get speculation state for @speculate functions
- **WHEN** `debugger.get_speculation_state(func_name="list_cases")` is called
- **THEN** the system SHALL return highest_successful_id, consecutive_failures, current_ceiling, stopped

<!-- Data Export -->

### Requirement: WARC Export

The system SHALL support exporting responses to WARC format.

#### Scenario: Export to WARC file
- **WHEN** `debugger.export_warc(output_path="run.warc.gz", compressed=True)` is called
- **THEN** all responses SHALL be exported in WARC format
- **AND** include request/response metadata

#### Scenario: Preview WARC export
- **WHEN** `debugger.preview_warc_export()` is called
- **THEN** the system SHALL return estimated file size and record count without creating file

<!-- Database Connection Management -->

### Requirement: Read-Only Database Access

The system SHALL support opening databases in read-only mode for safe inspection.

#### Scenario: Open database read-only
- **WHEN** `debugger = LocalDevDriverDebugger(db_path, read_only=True)` is created
- **THEN** the database SHALL be opened with read-only connection
- **AND** any write operations SHALL raise an error

#### Scenario: Open database read-write
- **WHEN** `debugger = LocalDevDriverDebugger(db_path, read_only=False)` is created
- **THEN** manipulation operations (requeue, cancel, resolve) SHALL be allowed

### Requirement: Connection Lifecycle

The system SHALL support async context manager protocol for connection management.

#### Scenario: Async context manager
- **WHEN** `async with LocalDevDriverDebugger(db_path) as debugger:` is used
- **THEN** the database connection SHALL be opened on enter
- **AND** properly closed on exit

#### Scenario: Idle connection timeout
- **WHEN** a debugger connection is idle for 30 seconds
- **THEN** the connection MAY be closed to free resources
- **AND** SHALL be transparently reopened on next operation
