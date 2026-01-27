# Change: Replace SpeculativeRequest with @speculate Decorator

## Why

The current speculation architecture requires scraper authors to manually create bidirectional generators that yield `SpeculativeRequest` objects and receive True/False responses. This pattern is complex to manage, hard to manage resumable scrapers with, and we probably don't need the power. By moving to a `@speculate` decorator pattern, we simplify scraper authoring while enabling drivers to seed their queues directly from annotated functions.

## What Changes

- **BREAKING**: Remove `SpeculativeRequest` type entirely
- **BREAKING**: Remove `@step(speculative=True)` pattern
- **BREAKING**: Remove bidirectional generator pattern for speculation (no more `should_continue = yield ...`)
- Add `@speculate` decorator for marking functions that generate speculative requests
- Add `is_speculative: bool` field to `BaseRequest` to identify speculative requests
- Add `speculation_id: tuple[str, int] | None` field to `BaseRequest` to track (function_name, integer_id)
- Add `speculative(func_name, id)` method to `NavigatingRequest` to create speculative copies
- Add `speculative()` method to `BaseRequest` that raises `NotImplementedError` (only NavigatingRequest can be speculative)
- Update `@speculate` decorator to call `request.speculative(func_name, id)` on returned requests
- Update `ScraperParams.speculative` interface to expose `definite_range` and `plus` configuration
- Drivers now responsible for calling `@speculate` functions to seed initial queues
- Drivers use `speculation_id` tuple for tracking instead of accumulated_data lookups
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
