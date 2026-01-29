# Change: Add Playwright Driver

## Why

Some court websites require JavaScript rendering to access their content. The existing HTTP-based driver cannot execute JavaScript. A Playwright-based driver can render these pages, but step functions must remain pure generators that never perform I/O. This change introduces a Playwright driver that renders pages, serializes the DOM to HTML, and hands static snapshots to step functions via the `PageElement` interface defined in the `add-unified-page-interface` change.

## Prerequisites

- `add-unified-page-interface` — provides `PageElement` protocol, `LxmlPageElement`, `SelectorObserver`, `Form`/`Link` abstractions, `Via` types on `BaseRequest`

## What Changes

- **DOM snapshot model**: Playwright driver renders the page (handling JavaScript, waiting for network idle, etc.), then serializes the rendered DOM via `page.content()`. That HTML is parsed by LXML into a `PageElement`. Step functions never communicate with a live browser — they query a static snapshot.
- **`await_list` on `@step` decorator**: List of reified wait conditions (`WaitForSelector`, `WaitForLoadState`, `WaitForURL`, `WaitForTimeout`) stored on `StepMetadata`. The Playwright driver reads the continuation step's metadata and satisfies each condition before snapshotting the DOM. HTTP driver ignores it.
- **Autowait**: Optional `auto_await_timeout` on `@step` decorator. When a step raises `HTMLStructuralAssumptionException` from an element query, the Playwright driver uses the `SelectorObserver`'s query tree to compose an absolute selector, waits for it in the live browser, re-snapshots the DOM, and retries the step. Complements `await_list` by catching element-level loading delays without requiring scraper authors to enumerate every selector. Non-Playwright-compatible selectors (text nodes, attributes, EXSLT) skip autowait. HTTP driver ignores it.
- **Playwright driver via handling**: Pattern-matches on `request.via` to execute browser actions — `ViaFormSubmit` fills form fields and clicks the submit element; `ViaLink` or `None` navigates to URL.
- **Updated `@step` decorator**: New `await_list` and `auto_await_timeout` parameters stored on `StepMetadata`. Also adds `page` parameter injection for the `PageElement` interface.

## Impact

- Affected specs: `playwright-driver`
- Affected code:
  - `juriscraper/scraper_driver/common/decorators.py` — `await_list` and `auto_await_timeout` parameters on `@step` decorator; `page` injection
  - New Playwright driver module — DOM snapshot, via handling, await_list processing, autowait retry loop
  - Existing scrapers: no changes required; Playwright support is opt-in per scraper
