# Change: Enhanced Requeue Operations for LocalDevDriver SQLManager

## Why

The current requeue functionality in LocalDevDriver is a bit underspecified. Debugging scrapers often requires more granular control: the ability to requeue from specific responses, clear cached responses to force re-fetching, and clean up downstream artifacts (child requests, data, errors) when reprocessing a request chain. This proposal adds a unified requeue API with explicit control over what gets cleared and helper functions for common requeue scenarios.

## What Changes

- Add `requeue_requests(request_ids, *, clear_responses, clear_downstream, dry_run)` as the core requeue function
- Add `requeue_response(response_id, *, clear_responses, clear_downstream, dry_run)` helper to requeue from a response
- Add `requeue_error(error_id, *, mark_resolved, clear_responses, clear_downstream, dry_run)` helper to requeue from an error
- Add `requeue_continuation(continuation, *, error_type, traceback_contains, clear_responses, clear_downstream, dry_run)` helper to bulk requeue by continuation with optional filtering
- Support `clear_responses` to delete response records (including the initial request's response) so URLs get re-fetched
- Support `clear_downstream` to recursively clear child requests, results, errors, and optionally responses
- Support `dry_run` mode that returns what would be affected without making changes

## Impact

- Affected specs: `local-dev-driver` (new capability)
- Affected code: `sql_manager.py`, `sql_queries.py`
- No breaking changes to existing API
