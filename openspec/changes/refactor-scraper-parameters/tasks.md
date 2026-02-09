## 1. Core infrastructure
- [ ] 1.1 Define `EntryMetadata` dataclass in `decorators.py`
- [ ] 1.2 Implement `@entry(ReturnType)` decorator in `decorators.py` (with `speculative` kwarg support)
- [ ] 1.3 Implement `get_entry_metadata()` and `is_entry()` helper functions
- [ ] 1.4 Add `BaseScraper.list_entries()` classmethod for entry introspection
- [ ] 1.5 Add `BaseScraper.initial_seed(params)` method with empty-list error
- [ ] 1.6 Add `BaseScraper.schema()` classmethod using Pydantic native `model_json_schema()`
- [ ] 1.7 Add `validate_params()` to `EntryMetadata` handling both BaseModel and primitive types
- [ ] 1.8 Define shared parameter models (DateRange, etc.) if common across scrapers
- [ ] 1.9 Write unit tests for @entry decorator metadata attachment (including speculative)
- [ ] 1.10 Write unit tests for initial_seed() dispatch, validation errors, and empty-list error
- [ ] 1.11 Write unit tests for schema() output format (primitives + BaseModels + speculative entries)

## 2. Remove old parameter system
- [ ] 2.1 Remove `ScraperParams`, `ModelProxy`, `FieldProxy`, proxy classes from `searchable.py`
- [ ] 2.2 Remove marker classes (`DateRange`, `SetFilter`, `UniqueMatch`, `SpeculativeID`) from `searchable.py`
- [ ] 2.3 Remove filter value holders (`DateRangeFilter`, `SetFilterValue`, etc.) from `searchable.py`
- [ ] 2.4 Remove `build_params_for_scraper()` from `searchable.py`
- [ ] 2.5 Remove `BaseScraper.params()` classmethod
- [ ] 2.6 Remove `BaseScraper.__init__(params)` and `BaseScraper.get_params()`
- [ ] 2.7 Remove `BaseScraper.get_entry()` abstract method
- [ ] 2.8 Remove `@speculate` decorator (replaced by `@entry(..., speculative=True)`)
- [ ] 2.9 Remove `list_speculators()`, `SpeculateMetadata`, and related helpers
- [ ] 2.10 Update/remove tests that depend on old parameter system and @speculate

## 3. Driver updates
- [ ] 3.1 Update `SyncDriver` to call `initial_seed()` instead of `get_entry()`
- [ ] 3.2 Update `AsyncDriver` to call `initial_seed()` instead of `get_entry()`
- [ ] 3.3 Update `DevDriver` to call `initial_seed()` instead of `get_entry()`
- [ ] 3.4 Update driver speculative probing to check `EntryMetadata.speculative` instead of `@speculate`
- [ ] 3.5 Update `scraper_registry.py` to use `schema()` instead of `ScraperParams` introspection
- [ ] 3.6 Update web UI form generation to work with Pydantic native schema
- [ ] 3.7 Update `params_json` storage format in DevDriver SQLite schema

## 4. First-PR scraper migration
- [ ] 4.1 Migrate test scrapers (bug_court.py, etc.) to @entry pattern
- [ ] 4.2 Migrate Connecticut scraper to @entry pattern (including speculative entries)
- [ ] 4.3 Migrate Alabama scraper to @entry pattern

## 5. Validation
- [ ] 5.1 Run full test suite, fix failures
- [ ] 5.2 Verify schema() output for Connecticut and Alabama scrapers
- [ ] 5.3 Verify initial_seed() round-trip: schema -> JSON params -> seed -> requests
- [ ] 5.4 Verify web UI form generation from new schema format
- [ ] 5.5 Verify speculative entry dispatch works end-to-end

## 6. Follow-up PRs (per-scraper, after first PR merges)
- [ ] 6.1 Migrate California scraper
- [ ] 6.2 Migrate remaining state scrapers (one PR per scraper)
- [ ] 6.3 Migrate federal scrapers (if any)
