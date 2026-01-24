# Change: Add `fails_successfully` Check for Speculative Requests

## Why

Some websites return HTTP 200 status codes but embed error states in the page content or headers. When using `SpeculativeRequest` for pagination probing, the `on_speculation_response` callback needs to detect these hidden failures. Currently each callback must implement its own detection logic. Adding a `fails_successfully` method to scrapers allows this check to happen before the callback, letting callbacks use a simple status code check instead.

## What Changes

- Add `fails_successfully(response: Response) -> bool` method to `BaseScraper` (returns `True` by default)
- Subclasses override this method for websites with known soft-failure patterns
- Drivers call this method when processing `SpeculativeRequest` responses
- If the method returns `False`, set `response.status_code = 555` before calling `on_speculation_response`
- This lets speculation handlers use generic status code checks instead of site-specific logic

## Design Decisions

### Status Code 555
- 555 is an unused HTTP status code (not in any RFC)
- Signals "looks like 200 but scraper detected hidden error"
- Allows speculation handlers to treat it like any other error status

### Only for SpeculativeRequest
- The check runs only for speculative requests, not all responses
- Speculation handlers are the primary consumer of this pattern
- Keeps the change minimal and focused

## Impact

- Affected specs: [scraper-driver](../../specs/scraper-driver/spec.md)
- Affected code:
  - `juriscraper/scraper_driver/data_types.py` - Add `fails_successfully()` to `BaseScraper`
  - `juriscraper/scraper_driver/driver/sync_driver.py` - Call check for SpeculativeRequest
  - `juriscraper/scraper_driver/driver/async_driver.py` - Call check for SpeculativeRequest
  - `juriscraper/scraper_driver/driver/dev_driver/dev_driver.py` - Inherits from AsyncDriver (may need override)
