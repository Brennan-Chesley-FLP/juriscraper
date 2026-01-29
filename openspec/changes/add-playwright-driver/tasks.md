## 1. Wait Condition Types

- [ ] 1.1 Define `WaitForSelector`, `WaitForLoadState`, `WaitForURL`, `WaitForTimeout` frozen dataclasses in `data_types.py`
- [ ] 1.2 Write unit tests for wait condition type construction

## 2. Step Decorator Integration

- [ ] 2.1 Add `page` parameter injection to `@step` decorator in `decorators.py` — parse HTML via LXML, create `SelectorObserver`, construct `LxmlPageElement` with observer
- [ ] 2.2 Add `await_list` parameter to `@step` decorator and `StepMetadata` — list of `WaitForSelector | WaitForLoadState | WaitForURL | WaitForTimeout`, defaults to `[]`
- [ ] 2.3 Add `auto_await_timeout` parameter to `@step` decorator and `StepMetadata` — `int | None`, defaults to `None` (disabled)
- [ ] 2.4 After step function returns or raises, make observer accessible to driver for debugging and autowait
- [ ] 2.5 Write unit tests for `page` injection alongside existing `lxml_tree` injection
- [ ] 2.6 Write unit tests for `await_list` and `auto_await_timeout` on `StepMetadata` via `get_step_metadata()`
- [ ] 2.7 Verify `lxml_tree` backward compatibility — `CheckedHtmlElement` + `XPathObserver` context variable pattern unchanged

## 3. Playwright Driver DOM Snapshot, Via Handling, Await List & Autowait

- [ ] 3.1 Read continuation's `StepMetadata.await_list` via `get_step_metadata()` before invoking step; process each wait condition by calling corresponding `page.wait_for_*` method in order
- [ ] 3.2 After all waits complete, call `page.content()` to get HTML string; parse via LXML and inject as `LxmlPageElement` with `SelectorObserver`
- [ ] 3.3 Pattern-match on `request.via` in Playwright driver: `ViaFormSubmit` → locate form, fill fields, click submit element; `ViaLink` / `None` → navigate to URL
- [ ] 3.4 Raise `HTMLStructuralAssumptionException` when a `via` selector fails to match in the live DOM
- [ ] 3.5 Raise `TransientException` when an `await_list` wait condition times out
- [ ] 3.6 Implement autowait retry loop in Playwright driver: catch `HTMLStructuralAssumptionException`, check `auto_await_timeout` and `is_element_query`, compose absolute selector via observer, check `can_playwright_wait`, call `page.wait_for_selector`, re-snapshot, restart step
- [ ] 3.7 Implement buffered yield collection: buffer all yields during autowait-eligible step execution, flush on success, discard on retry
- [ ] 3.8 Write integration tests: autowait catches JS-delayed element → re-snapshot → step succeeds on retry
- [ ] 3.9 Write integration tests: autowait skips non-element query failure (text()/attr), raises immediately
- [ ] 3.10 Write integration tests: autowait timeout exhaustion → raises original exception
- [ ] 3.11 Write integration tests: Playwright renders JS-heavy page → await_list waits → snapshot → step queries static HTML → yields form submit → driver replays

## 4. Proof of Concept

- [ ] 4.1 Convert one existing scraper step to use `page: PageElement` instead of `lxml_tree`
- [ ] 4.2 Verify the converted scraper works with both SyncDriver (HTTP) and PlaywrightDriver
- [ ] 4.3 Document migration pattern for scraper authors
