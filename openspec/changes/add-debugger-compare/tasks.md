# Implementation Tasks

## 1. DryRunDriver Implementation

- [ ] 1.1 Create `dry_run_driver.py` module with `DryRunDriver` class
- [ ] 1.2 Implement request capture for `NavigatingRequest`, `NonNavigatingRequest`, `ArchiveRequest`
- [ ] 1.4 Implement `ParsedData` capture
- [ ] 1.5 Implement context reconstruction from stored request data
- [ ] 1.6 Add error capture during continuation execution

## 2. Comparison Logic

- [ ] 2.1 Create `comparison.py` module with comparison data structures
- [ ] 2.2 Implement transitive child request tree comparison
- [ ] 2.3 Implement Levenshtein-based result pairing (greedy minimum distance assignment)
- [ ] 2.4 Implement exact dict comparison for paired results with field-level diff
- [ ] 2.5 Identify added/removed results from unpaired items
- [ ] 2.6 Implement error comparison (introduced/resolved/changed)
- [ ] 2.7 Generate comparison summary statistics

## 3. Debugger API Extensions

- [ ] 3.1 Add `compare_continuation()` method to `LocalDevDriverDebugger`
- [ ] 3.2 Add helper to get child requests transitively by `parent_request_id`
- [ ] 3.3 Add helper to get results for a request
- [ ] 3.4 Add sampling logic for terminal requests

## 4. CLI Command

- [ ] 4.1 Add `compare` command to `ldd-debug` CLI
- [ ] 4.2 Implement `--request-id` option for single request comparison
- [ ] 4.3 Implement `--sample` option for terminal step sampling
- [ ] 4.4 Implement `--output-mode` option (summary/detail/json)
- [ ] 4.5 Implement `--show-requests` and `--show-data` filters
- [ ] 4.6 Implement `--limit` option

## 5. Testing

- [ ] 5.1 Unit tests for `DryRunDriver` request/data capture
- [ ] 5.2 Unit tests for Levenshtein matching logic
- [ ] 5.3 Unit tests for transitive tree comparison
- [ ] 5.4 Integration tests with sample scraper and stored database
- [ ] 5.5 Test error scenarios (scraper import failure, missing responses)

## 6. Documentation

- [ ] 6.1 Add CLI help text and examples
- [ ] 6.2 Update SKILL.md for debug-scraper skill