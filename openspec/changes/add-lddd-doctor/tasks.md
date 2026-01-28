## 1. Debugger Backend

- [ ] 1.1 Add `check_integrity()` method to LocalDevDriverDebugger
  - Detects orphaned requests (completed but no response)
  - Detects orphaned responses (no matching request)
  - Returns structured result with counts and IDs
- [ ] 1.2 Add `get_orphan_details()` method to list orphan specifics
- [ ] 1.3 Add `get_ghost_requests()` method
  - Finds completed requests with no child requests AND no results
  - Groups by continuation (step)
- [ ] 1.4 Add `get_run_status()` method
  - Returns pending count or wrapped status indicator
- [ ] 1.5 Add SQL queries to sql_queries.py for integrity checks

## 2. CLI Implementation

- [ ] 2.1 Add `doctor` command group to cli.py
- [ ] 2.2 Implement base `doctor` command for health report
  - Displays integrity check summary
  - Displays error counts
  - Displays pending/wrapped status
  - Displays ghost request summary by step
- [ ] 2.3 Implement `doctor orphans` subcommand
  - Lists orphaned requests/responses
  - Supports --format option (table/json/jsonl)
- [ ] 2.4 Implement `doctor pending` subcommand
  - Lists pending requests with details
  - Supports --format and --limit options
- [ ] 2.5 Implement `doctor ghosts` subcommand
  - Lists ghost requests grouped by step
  - Supports --format and --continuation filter

## 3. Testing

- [ ] 3.1 Add unit tests for integrity check methods
- [ ] 3.2 Add unit tests for ghost request detection
- [ ] 3.3 Add CLI integration tests for doctor command