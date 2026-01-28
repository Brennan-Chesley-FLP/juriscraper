## ADDED Requirements

### Requirement: Doctor Command for Database Health Checks

The LDDD CLI SHALL provide a `doctor` command that validates database integrity and reports anomalies.

#### Scenario: Run doctor health check
- **WHEN** `ldd-debug doctor <db-path>` is executed
- **THEN** the system SHALL display:
  - Integrity violations (orphaned requests/responses)
  - Error counts summary
  - Pending request count OR "run wrapped" indicator if no pending
  - Ghost request counts grouped by continuation (step)

#### Scenario: All checks pass
- **WHEN** no integrity issues, errors, pending requests, or ghosts exist
- **THEN** the output SHALL indicate a healthy database state

### Requirement: Orphan Detection

The system SHALL detect orphaned database records that violate expected relationships.

#### Scenario: Orphaned request detection
- **WHEN** a completed request exists with no corresponding response record
- **THEN** the integrity check SHALL report it as an orphaned request
- **AND** include the request ID and URL in the report

#### Scenario: Orphaned response detection
- **WHEN** a response record exists with a request_id that has no matching request
- **THEN** the integrity check SHALL report it as an orphaned response
- **AND** include the response ID and request_id in the report

#### Scenario: List orphans with subcommand
- **WHEN** `ldd-debug doctor orphans <db-path>` is executed
- **THEN** the system SHALL list all orphaned requests and responses
- **AND** support --format option (table/json/jsonl)

### Requirement: Ghost Request Detection

The system SHALL identify ghost requests - completed requests that produced no observable output.

#### Scenario: Ghost request identification
- **WHEN** a completed request has:
  - No child requests (via parent_request_id)
  - No results in the results table
- **THEN** it SHALL be classified as a ghost request
- **AND** counted in the ghost request summary by continuation

#### Scenario: Ghost requests by step
- **WHEN** the doctor command runs
- **THEN** ghost requests SHALL be grouped and counted by their continuation field
- **AND** displayed as a table with columns: continuation, ghost_count

#### Scenario: List ghosts with subcommand
- **WHEN** `ldd-debug doctor ghosts <db-path>` is executed
- **THEN** the system SHALL list ghost request details
- **AND** support --format option and --continuation filter

### Requirement: Pending Request Status

The system SHALL report the status of pending work in the database.

#### Scenario: Pending requests exist
- **WHEN** requests with status='pending' exist
- **THEN** the doctor command SHALL display the count of pending requests

#### Scenario: Run is wrapped (no pending)
- **WHEN** no requests have status='pending'
- **THEN** the doctor command SHALL display "Run wrapped - no pending requests"

#### Scenario: List pending with subcommand
- **WHEN** `ldd-debug doctor pending <db-path>` is executed
- **THEN** the system SHALL list pending request details
- **AND** support --format and --limit options

### Requirement: Extensible Integrity Checks

The integrity check system SHALL be designed for easy extension with new check types.

#### Scenario: Adding new integrity check
- **WHEN** a developer needs to add a new integrity check
- **THEN** they SHALL be able to add a new check method following the existing pattern
- **AND** register it in a central check registry or list
- **AND** the doctor command SHALL automatically include the new check