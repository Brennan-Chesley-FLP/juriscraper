## ADDED Requirements

### Requirement: RequeueResult Return Type

The SQLManager SHALL provide a `RequeueResult` subclass of pydantic.BaseModel that reports what was affected by a requeue operation.

#### Scenario: Requeue result structure
- **WHEN** any requeue operation completes
- **THEN** it SHALL return a `RequeueResult` with:
  - `requeued_request_ids`: List of new request IDs created
  - `cleared_response_ids`: List of response IDs deleted
  - `cleared_downstream_request_ids`: List of downstream request IDs deleted
  - `cleared_result_ids`: List of result IDs deleted
  - `cleared_error_ids`: List of error IDs deleted
  - `resolved_error_ids`: List of error IDs marked as resolved
  - `dry_run`: Boolean indicating if this was a dry run

### Requirement: Core Requeue Requests Function

The SQLManager SHALL provide a `requeue_requests(request_ids, *, clear_responses, clear_downstream, dry_run)` function that requeues a list of requests with configurable cleanup behavior.

#### Scenario: Basic requeue creates new pending requests
- **WHEN** `requeue_requests([1, 2, 3])` is called
- **THEN** new pending requests SHALL be created with the same parameters as the originals
- **AND** the new requests SHALL have fresh `queue_counter` values for FIFO ordering
- **AND** the original requests SHALL remain unchanged

#### Scenario: Clear responses forces re-fetch
- **WHEN** `requeue_requests([1], clear_responses=True)` is called
- **THEN** the response associated with request 1 SHALL be deleted from the database
- **AND** when the new request is processed, it SHALL fetch from the network (no cache hit)

#### Scenario: Clear downstream removes child artifacts
- **WHEN** `requeue_requests([1], clear_downstream=True)` is called
- **AND** request 1 has child requests 2, 3 (via parent_request_id)
- **AND** request 2 has child request 4
- **THEN** requests 2, 3, 4 SHALL be deleted (recursive)
- **AND** results associated with requests 1, 2, 3, 4 SHALL be deleted
- **AND** errors associated with requests 1, 2, 3, 4 SHALL be deleted

#### Scenario: Clear downstream with clear_responses removes entire response chain
- **WHEN** `requeue_requests([1], clear_downstream=True, clear_responses=True)` is called
- **THEN** responses for requests 1, 2, 3, 4 (the full tree including the initial request) SHALL be deleted

#### Scenario: Dry run reports without changes
- **WHEN** `requeue_requests([1], clear_downstream=True, dry_run=True)` is called
- **THEN** no database changes SHALL be made
- **AND** the returned `RequeueResult` SHALL list what would be affected

### Requirement: Requeue from Response Helper

The SQLManager SHALL provide a `requeue_response(response_id, *, clear_responses, clear_downstream, dry_run)` helper that requeues the request associated with a response.

#### Scenario: Requeue from response ID
- **WHEN** `requeue_response(response_id=42)` is called
- **AND** response 42 is associated with request 10
- **THEN** `requeue_requests([10])` SHALL be called with the same options

### Requirement: Requeue from Error Helper

The SQLManager SHALL provide a `requeue_error(error_id, *, mark_resolved, clear_responses, clear_downstream, dry_run)` helper that requeues from an error with resolution control.

#### Scenario: Requeue from error marks resolved by default
- **WHEN** `requeue_error(error_id=5)` is called
- **THEN** error 5 SHALL be marked as resolved with a note indicating it was requeued
- **AND** a new pending request SHALL be created

#### Scenario: Requeue from error can leave unresolved
- **WHEN** `requeue_error(error_id=5, mark_resolved=False)` is called
- **THEN** error 5 SHALL NOT be marked as resolved
- **AND** a new pending request SHALL still be created

#### Scenario: Requeue from error without request
- **WHEN** `requeue_error(error_id=5)` is called
- **AND** error 5 has `request_id=NULL`
- **THEN** the operation SHALL return an empty `RequeueResult`
- **AND** no changes SHALL be made

### Requirement: Requeue from Continuation Helper

The SQLManager SHALL provide a `requeue_continuation(continuation, *, error_type, traceback_contains, clear_responses, clear_downstream, dry_run)` helper that bulk requeues requests by continuation with optional error filtering.

#### Scenario: Requeue all requests for a continuation
- **WHEN** `requeue_continuation("parse_results")` is called with no filters
- **THEN** all completed requests with continuation="parse_results" SHALL be requeued

#### Scenario: Filter by error type
- **WHEN** `requeue_continuation("parse_results", error_type="structural")` is called
- **THEN** only requests with unresolved "structural" errors SHALL be requeued

#### Scenario: Filter by traceback content
- **WHEN** `requeue_continuation("parse_results", traceback_contains="KeyError")` is called
- **THEN** only requests with unresolved errors containing "KeyError" in their traceback SHALL be requeued

#### Scenario: Combined error filters
- **WHEN** `requeue_continuation("parse_results", error_type="validation", traceback_contains="expected str")` is called
- **THEN** only requests matching BOTH filters SHALL be requeued
