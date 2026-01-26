## 1. Core Types

- [ ] 1.1 Add `is_speculative: bool = False` field to `BaseRequest` in data_types.py
- [ ] 1.2 Create `SpeculateMetadata` dataclass for decorator metadata
- [ ] 1.3 Create `@speculate` decorator in decorators.py
- [ ] 1.4 Update `ScraperParams` to add `definite_range` and `plus` properties
- [ ] 1.5 Add `_find_speculate_functions()` helper to searchable.py
- [ ] 1.6 Add `list_speculators()` public method to BaseScraper returning list of (name, highest_observed, observation_date, largest_observed_gap)

## 2. Driver Updates

- [ ] 2.1 Add `_discover_speculate_functions()` method to base driver
- [ ] 2.2 Add `_seed_speculative_queue()` method to base driver
- [ ] 2.3 Add speculation tracking state (`highest_successful_id`, `consecutive_failures`, `current_ceiling` per function)
- [ ] 2.4 Add `_extend_speculation()` method for dynamic queue extension
- [ ] 2.5 Update SyncDriver to seed and track speculation
- [ ] 2.6 Update AsyncDriver to seed and track speculation
- [ ] 2.7 Remove `on_speculation_response` callback from driver interfaces
- [ ] 2.8 Update request processing to update speculation tracking on response

## 3. LocalDevDriver Updates

- [ ] 3.1 Add DB schema for speculation tracking (`highest_successful_id`, `consecutive_failures`, `current_ceiling` per function)
- [ ] 3.2 Remove generator tracking from LocalDevDriver
- [ ] 3.3 Implement speculation state persistence for run resumption
- [ ] 3.4 Update requeue logic to respect speculation state

## 4. Scraper Migration

- [ ] 4.1 Migrate Tennessee scrapers from @step(speculative=True) to @speculate
- [ ] 4.2 Migrate California scrapers
- [ ] 4.3 Migrate Connecticut scrapers
- [ ] 4.4 Migrate Mississippi scrapers
- [ ] 4.5 Migrate Arkansas scrapers
- [ ] 4.6 Migrate Alabama scrapers

## 5. Deprecation and Cleanup

- [ ] 5.1 Mark `SpeculativeRequest` as deprecated with warning
- [ ] 5.2 Mark `@step(speculative=True)` as deprecated with warning
- [ ] 5.3 Remove `SpeculationContext` and `ResumeStep` types
- [ ] 5.4 Remove bidirectional generator support from @step decorator
- [ ] 5.5 Remove `SpeculativeRequest` type entirely
- [ ] 5.6 Update spec documentation

## 6. Testing

- [ ] 6.1 Unit tests for @speculate decorator
- [ ] 6.2 Unit tests for params interface changes
- [ ] 6.3 Unit tests for list_speculators() method
- [ ] 6.4 Integration tests for SyncDriver with speculate functions
- [ ] 6.5 Integration tests for AsyncDriver with speculate functions
- [ ] 6.6 Integration tests for LocalDevDriver speculation state persistence
- [ ] 6.7 Integration test for LocalDevDriver resumability with speculation
- [ ] 6.8 Remove old SpeculativeRequest and @step(speculative=True) tests
