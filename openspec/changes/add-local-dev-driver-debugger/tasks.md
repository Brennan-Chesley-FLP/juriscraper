# Tasks: Add LocalDevDriverDebugger

## 1. Core LDDD Implementation

- [ ] 1.1 Create `debugger.py` with `LocalDevDriverDebugger` class skeleton
- [ ] 1.2 Implement connection management (async context manager, read-only mode)
- [ ] 1.3 Implement request inspection methods (list_requests, get_request, get_request_summary)
- [ ] 1.4 Implement response inspection methods (list_responses, get_response, get_response_content)
- [ ] 1.5 Implement error inspection methods (list_errors, get_error, get_error_summary)
- [ ] 1.6 Implement result inspection methods (list_results, get_result, get_result_summary)
- [ ] 1.7 Implement run metadata and stats methods (get_run_metadata, get_stats)
- [ ] 1.8 Implement speculation inspection (get_speculation_summary, get_speculative_progress)
- [ ] 1.9 Implement rate limiter inspection (get_rate_limiter_state, get_throughput_stats)
- [ ] 1.10 Implement compression inspection (get_compression_stats, list_compression_dicts)

## 2. LDDD Manipulation Methods

- [ ] 2.1 Implement request cancellation (cancel_request, cancel_requests_by_continuation)
- [ ] 2.2 Implement request requeue (requeue_request, requeue_continuation)
- [ ] 2.3 Implement error resolution (resolve_error)
- [ ] 2.4 Implement error requeue (requeue_error, batch_requeue_errors)
- [ ] 2.5 Implement compression manipulation (train_compression_dict, recompress_responses)

## 3. LDDD Debugging Methods

- [ ] 3.1 Implement diagnose method with XPath observation
- [ ] 3.2 Implement speculation cap for diagnosis

## 4. LDDD Export Methods

- [ ] 4.1 Implement export_results_jsonl streaming
- [ ] 4.2 Implement export_warc and preview_warc_export

## 5. LDDD Tests

- [ ] 5.1 Unit tests for inspection methods
- [ ] 5.2 Unit tests for manipulation methods
- [ ] 5.3 Unit tests for read-only mode enforcement
- [ ] 5.4 Integration tests with sample database

## 6. CLI Implementation

- [ ] 6.1 Create `cli.py` with Click app skeleton
- [ ] 6.2 Add `ldd-debug` entry point to pyproject.toml
- [ ] 6.3 Implement `info` command (run metadata, stats)
- [ ] 6.4 Implement `requests` command (list, show, summary)
- [ ] 6.5 Implement `responses` command (list, show, content)
- [ ] 6.6 Implement `errors` command (list, show, summary, resolve, requeue)
- [ ] 6.7 Implement `results` command (list, show, summary, export)
- [ ] 6.8 Implement `requeue` command (request, continuation, errors)
- [ ] 6.9 Implement `cancel` command (request, continuation)
- [ ] 6.10 Implement `compression` command (stats, train, recompress)
- [ ] 6.11 Implement `diagnose` command
- [ ] 6.12 Implement `export` command (jsonl, warc)
- [ ] 6.13 Add shell completion support
- [ ] 6.14 Add `--format` option (table, json, jsonl)

## 7. CLI Tests

- [ ] 7.1 Unit tests for CLI commands
- [ ] 7.2 Integration tests with sample database

## 8. WebUI Migration

- [ ] 8.1 Add LDDD dependency injection to FastAPI app
- [ ] 8.2 Migrate `routes/requests.py` to use LDDD
- [ ] 8.3 Migrate `routes/responses.py` to use LDDD
- [ ] 8.4 Migrate `routes/errors.py` to use LDDD
- [ ] 8.5 Migrate `routes/results.py` to use LDDD
- [ ] 8.6 Migrate `routes/compression.py` to use LDDD
- [ ] 8.7 Migrate `routes/rate_limiter.py` to use LDDD
- [ ] 8.8 Migrate `routes/debug.py` to use LDDD
- [ ] 8.9 Migrate `routes/export.py` to use LDDD
- [ ] 8.10 Remove direct SQL queries from route handlers
- [ ] 8.11 Update WebUI integration tests

## 9. Documentation

- [ ] 10.1 Add docstrings to all LDDD methods
- [ ] 10.2 Add CLI help text and examples
- [ ] 10.3 Update README with CLI usage
