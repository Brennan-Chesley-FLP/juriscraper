# Change: Replace SpeculativeRequest with @speculate Decorator

## Why

The current speculation architecture requires scraper authors to manually create bidirectional generators that yield `SpeculativeRequest` objects and receive True/False responses. This pattern is complex to manage, hard to manage resumable scrapers with, and we probably don't need the power. By moving to a `@speculate` decorator pattern, we simplify scraper authoring while enabling drivers to seed their queues directly from annotated functions.

## What Changes

- **BREAKING**: Remove `SpeculativeRequest` type entirely
- **BREAKING**: Remove `@step(speculative=True)` pattern
- **BREAKING**: Remove bidirectional generator pattern for speculation (no more `should_continue = yield ...`)
- Add `@speculate` decorator for marking functions that generate speculative requests
- Add `is_speculative: bool` field to `BaseRequest` to identify speculative requests
- Update `ScraperParams.speculative` interface to expose `definite_range` and `plus` configuration
- Drivers now responsible for calling `@speculate` functions to seed initial queues
- LocalDevDriver removes generator tracking, adds metadata persistence in DB

## Impact

- Affected specs: `scraper-driver`
- Affected code:
  - `juriscraper/scraper_driver/data_types.py` (SpeculativeRequest, BaseRequest)
  - `juriscraper/scraper_driver/common/decorators.py` (@step, new @speculate)
  - `juriscraper/scraper_driver/common/searchable.py` (params interface)
  - `juriscraper/scraper_driver/driver/sync_driver.py`
  - `juriscraper/scraper_driver/driver/async_driver.py`
  - `juriscraper/scraper_driver/driver/dev_driver/` (LocalDevDriver)
  - All scrapers using `@step(speculative=True)` pattern (Tennessee, California, Connecticut, Mississippi, Arkansas, Alabama)
