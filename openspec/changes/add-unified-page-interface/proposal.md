# Change: Add Unified Page Interface for LXML

## Why

Scraper step functions are currently tightly coupled to LXML's `CheckedHtmlElement`. To support multiple driver types (HTTP, Playwright) using the same step function code, we need a common interface for data extraction, form submission, and link following that works against parsed HTML regardless of how the HTML was obtained. Step functions must remain pure generators — they receive data, yield requests, and never perform I/O.

## What Changes

- **New `PageElement` protocol**: A common interface for querying elements, extracting text/attributes, and navigating the DOM. Always backed by parsed HTML (LXML). The driver is responsible for obtaining the HTML — whether via HTTPX or by other means.
- **New `Form` abstraction**: Identifies `<form>` elements, introspects their fields (`<input>`, `<select>`, `<textarea>`), and provides a `submit()` method that returns a request the step can yield. The driver decides whether to execute that request as an HTTP POST or a browser form submission.
- **New `Link` abstraction**: Wraps `<a>` elements with `.url`, `.text`, and a `.follow()` method that returns a `NavigatingRequest`.
- **`via` parameter on BaseRequest**: Typed union (`ViaLink | ViaFormSubmit | None`) that tells drivers *how* a request was produced — from a link click or form submission. Drivers can use this to replay the action appropriately.
- **`SelectorObserver` integrated into PageElement**: Replaces the context-variable-based `XPathObserver` for `PageElement` usage. Observer is a construction parameter on `LxmlPageElement`, not hidden global state. `CheckedHtmlElement` backward compat is unchanged.
- **`HTMLStructuralAssumptionException` enrichment**: Exceptions from `PageElement` queries carry the failing selector, selector type, and query kind for driver-level handling.
- **`can_playwright_wait` utility**: Static check for whether a selector can be used with Playwright's `wait_for_selector()` (filters out non-element XPath, EXSLT, variables).
- **`SelectorObserver.compose_absolute_selector`**: Composes absolute selectors from relative queries by walking the observer's parent chain.

## Impact

- Affected specs: `scraper-driver`
- Affected code:
  - `juriscraper/scraper_driver/common/checked_html.py` — implements `PageElement` protocol
  - `juriscraper/scraper_driver/data_types.py` — `via` field on `BaseRequest`; `ViaLink`, `ViaFormSubmit` types
  - New file for `PageElement` protocol, `LxmlPageElement`, `SelectorObserver`, `Form`, `FormField`, `Link`
  - Existing scrapers: no changes required; migration is opt-in per scraper
