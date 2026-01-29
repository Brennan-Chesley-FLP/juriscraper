## ADDED Requirements

### Requirement: DOM Snapshot Model for Playwright

The Playwright driver SHALL serialize the rendered DOM to HTML before calling step functions. Step functions SHALL never hold a live connection to a Playwright browser page.

#### Scenario: Playwright driver snapshots rendered DOM
- **WHEN** a Playwright driver navigates to a page
- **THEN** the driver SHALL execute all conditions in the continuation step's `await_list` (from `StepMetadata`) in order (if any)
- **AND** after all waits complete, the driver SHALL serialize the DOM via `page.content()` to obtain an HTML string
- **AND** the HTML SHALL be parsed by LXML into a `CheckedHtmlElement` / `PageElement`
- **AND** the step function SHALL receive the static parsed HTML

#### Scenario: Step function purity preserved
- **WHEN** a step function receives `page: PageElement` from a Playwright-backed driver
- **THEN** the `PageElement` SHALL be an `LxmlPageElement` wrapping LXML-parsed HTML
- **AND** the step function SHALL perform no I/O
- **AND** the step function SHALL have no reference to the Playwright browser or page object

#### Scenario: Navigation requests interpreted by driver
- **WHEN** a step function yields a `NavigatingRequest` from `link.follow()` or `form.submit()`
- **THEN** the HTTP driver SHALL execute it as an HTTP request
- **AND** the Playwright driver SHALL execute it as a browser navigation (navigate to URL, or fill form fields and click the submit element)
- **AND** after the Playwright driver completes navigation, it SHALL snapshot the new DOM and call the continuation with fresh parsed HTML

#### Scenario: NavigatingRequest vs NonNavigatingRequest irrelevant for Playwright
- **WHEN** a Playwright driver receives any request type
- **THEN** the `NavigatingRequest` vs `NonNavigatingRequest` distinction SHALL be ignored
- **AND** the Playwright driver SHALL manage its own URL state via the browser

### Requirement: Playwright Driver Via Handling

The Playwright driver SHALL use the `via` field on `BaseRequest` to determine how to execute browser actions. This requirement specifies the driver-side behavior for interpreting `ViaFormSubmit` and `ViaLink` (the data model for these types is defined in the scraper-driver spec).

#### Scenario: Playwright driver uses via for form submission
- **WHEN** a Playwright driver receives a request with `via` set to `ViaFormSubmit`
- **THEN** the driver SHALL locate the form in the live DOM using `form_selector`
- **AND** the driver SHALL fill the form fields from `field_data`
- **AND** the driver SHALL click the element identified by `submit_selector` (relative to the form)
- **AND** if `submit_selector` is `None`, the driver SHALL click the first submit-type element in the form

#### Scenario: Playwright driver selector replay failure
- **WHEN** a Playwright driver attempts to locate an element using a selector from `via`
- **AND** the selector does not match any element in the live DOM
- **THEN** the driver SHALL raise `HTMLStructuralAssumptionException`
- **AND** the exception SHALL include the selector, the selector type, and the request URL

### Requirement: Await List on Step Decorator for Playwright Wait Conditions

The `@step` decorator SHALL accept an optional `await_list` parameter — a list of reified wait condition objects stored on `StepMetadata`. Before invoking a step function, the Playwright driver SHALL look up the continuation's `StepMetadata` and satisfy each wait condition in `await_list` before taking the DOM snapshot. Each condition corresponds to a Playwright `page.waitFor*` method. The HTTP driver SHALL ignore `await_list`.

#### Scenario: Wait for selector before snapshot
- **WHEN** a step is decorated with `@step(await_list=[WaitForSelector(selector, state="visible")])`
- **AND** the Playwright driver invokes this step as a continuation
- **THEN** the driver SHALL call `page.wait_for_selector(selector, state=state)` before snapshotting
- **AND** if the selector does not appear within the timeout, a `TransientException` SHALL be raised

#### Scenario: Wait for load state before snapshot
- **WHEN** a step is decorated with `@step(await_list=[WaitForLoadState(state="networkidle")])`
- **AND** the Playwright driver invokes this step as a continuation
- **THEN** the driver SHALL call `page.wait_for_load_state(state)` before snapshotting

#### Scenario: Wait for URL before snapshot
- **WHEN** a step is decorated with `@step(await_list=[WaitForURL(url)])`
- **AND** the Playwright driver invokes this step as a continuation
- **THEN** the driver SHALL call `page.wait_for_url(url)` before snapshotting
- **AND** if the URL does not match within the timeout, a `TransientException` SHALL be raised

#### Scenario: Wait for explicit timeout
- **WHEN** a step is decorated with `@step(await_list=[WaitForTimeout(timeout)])`
- **AND** the Playwright driver invokes this step as a continuation
- **THEN** the driver SHALL wait for the specified number of milliseconds before proceeding

#### Scenario: Multiple wait conditions processed in order
- **WHEN** a step's `await_list` contains multiple conditions
- **THEN** the Playwright driver SHALL process them sequentially in list order
- **AND** the DOM snapshot SHALL be taken only after all conditions are satisfied

#### Scenario: Empty await_list
- **WHEN** a step has no `await_list` (the default)
- **THEN** the Playwright driver SHALL take the DOM snapshot immediately after navigation completes
- **AND** the HTTP driver SHALL behave unchanged

#### Scenario: HTTP driver ignores await_list
- **WHEN** an HTTP driver invokes a step whose `StepMetadata` has a non-empty `await_list`
- **THEN** the driver SHALL ignore the `await_list`
- **AND** the driver SHALL process the request using `HTTPRequestParams` as usual

#### Scenario: Driver reads await_list from StepMetadata
- **WHEN** a driver is about to invoke a continuation step function
- **THEN** the driver SHALL call `get_step_metadata()` on the continuation
- **AND** the driver SHALL read `metadata.await_list` to determine wait conditions
- **AND** the driver SHALL execute all wait conditions before snapshotting the DOM

### Requirement: Autowait — Retry Step on Structural Failure

The `@step` decorator SHALL accept an optional `auto_await_timeout` parameter (milliseconds) stored on `StepMetadata`. When the Playwright driver invokes a step with `auto_await_timeout` set and the step raises `HTMLStructuralAssumptionException` from an element query, the driver SHALL attempt to wait for the failing selector in the live browser, re-snapshot the DOM, and retry the step. The HTTP driver SHALL ignore `auto_await_timeout`.

#### Scenario: Autowait catches element query failure
- **WHEN** a step with `auto_await_timeout` set raises `HTMLStructuralAssumptionException` from `query_xpath` or `query_css`
- **AND** the failing selector is Playwright-compatible (targets elements, not text nodes or attributes)
- **THEN** the Playwright driver SHALL compose an absolute selector from the observer's query tree
- **AND** the driver SHALL call `page.wait_for_selector()` with the composed selector and remaining timeout
- **AND** after the wait succeeds, the driver SHALL call `page.content()` for a fresh DOM snapshot
- **AND** the driver SHALL restart the step function from the beginning with the new snapshot

#### Scenario: Absolute selector composition from observer
- **WHEN** the failing selector is relative (e.g., `.//td[@class='name']`)
- **THEN** the driver SHALL use the `SelectorObserver`'s query tree to walk the parent chain
- **AND** the driver SHALL compose an absolute selector by concatenating ancestor selectors (e.g., `//table[@id='results']//tr//td[@class='name']`)
- **AND** the composed selector SHALL be used for the Playwright `wait_for_selector` call

#### Scenario: Absolute selector already present
- **WHEN** the failing selector is already absolute (e.g., `//table[@id='results']`)
- **THEN** the driver SHALL use it directly for the Playwright `wait_for_selector` call

#### Scenario: Non-Playwright-compatible selector skips autowait
- **WHEN** the failing selector targets non-element XPath nodes (ends in `/text()` or `/@attr`)
- **OR** the selector uses EXSLT extensions (`re:`, `str:`, `math:`, `set:`, `dyn:`)
- **OR** the selector uses XPath variables (`$name`)
- **OR** the query was from `query_xpath_strings` (string query, not element query)
- **THEN** the driver SHALL skip autowait and raise the `HTMLStructuralAssumptionException` immediately

#### Scenario: Timeout exhaustion
- **WHEN** the total time spent in autowait retries exceeds `auto_await_timeout`
- **THEN** the driver SHALL raise the most recent `HTMLStructuralAssumptionException`
- **AND** no further retries SHALL be attempted

#### Scenario: Multiple retries on different selectors
- **WHEN** a retry succeeds (the waited-for selector appears) but the step fails on a different selector
- **THEN** the driver SHALL repeat the autowait process for the new failing selector
- **AND** the remaining `auto_await_timeout` SHALL be used for subsequent waits

#### Scenario: Buffered yields during autowait
- **WHEN** autowait is active for a step
- **THEN** the driver SHALL buffer all yields from the step generator
- **AND** if the step completes without exception, the buffer SHALL be flushed and processed normally
- **AND** if the step raises, the buffer SHALL be discarded before retry

#### Scenario: Autowait after await_list
- **WHEN** a step has both `await_list` and `auto_await_timeout`
- **THEN** the `await_list` SHALL be processed first (before the initial snapshot)
- **AND** autowait SHALL only activate if the step still fails after `await_list` conditions were satisfied

#### Scenario: HTTP driver ignores auto_await_timeout
- **WHEN** an HTTP driver invokes a step whose `StepMetadata` has `auto_await_timeout` set
- **THEN** the driver SHALL ignore `auto_await_timeout`
- **AND** `HTMLStructuralAssumptionException` SHALL propagate normally

#### Scenario: auto_await_timeout not set
- **WHEN** a step has no `auto_await_timeout` (the default)
- **THEN** `HTMLStructuralAssumptionException` SHALL propagate normally without retry
- **AND** behavior SHALL be identical to the non-autowait case

### Requirement: Step Decorator Page Injection, Await List, and Autowait Metadata

The `@step` decorator SHALL support a `page` parameter name for injecting a `PageElement` into step functions. The `@step` decorator SHALL also accept `await_list` and `auto_await_timeout` parameters that are stored on `StepMetadata` for use by the driver before and during step invocation.

#### Scenario: Inject PageElement with observer
- **WHEN** a step function declares `page: PageElement`
- **THEN** the decorator SHALL parse the response HTML via LXML
- **AND** the decorator SHALL create a `SelectorObserver` and construct `LxmlPageElement` with it
- **AND** this SHALL work identically regardless of whether the driver is HTTP-based or Playwright-based
- **AND** after the step function returns (or raises), the driver MAY inspect the observer for debugging and autowait

#### Scenario: Backward compatibility with lxml_tree
- **WHEN** a step function declares `lxml_tree: CheckedHtmlElement`
- **THEN** behavior SHALL be unchanged from the current implementation
- **AND** `lxml_tree` and `page` MAY coexist in the same step function signature

#### Scenario: Await list stored on StepMetadata
- **WHEN** `@step(await_list=[...])` is used
- **THEN** the `await_list` SHALL be stored on the `StepMetadata` object attached to the decorated function
- **AND** `get_step_metadata()` SHALL return metadata with the `await_list` field populated
- **AND** drivers SHALL read `metadata.await_list` before invoking the step function

#### Scenario: Auto await timeout stored on StepMetadata
- **WHEN** `@step(auto_await_timeout=10000)` is used
- **THEN** the `auto_await_timeout` SHALL be stored on the `StepMetadata` object attached to the decorated function
- **AND** `get_step_metadata()` SHALL return metadata with the `auto_await_timeout` field populated
- **AND** the Playwright driver SHALL use this value to bound autowait retry attempts

## MODIFIED Requirements

### Requirement: Automatic Argument Injection

The system SHALL provide a `@step` decorator that injects arguments based on parameter names.

#### Scenario: Inject lxml_tree
- **WHEN** a method parameter is named `lxml_tree`
- **THEN** the decorator SHALL parse the response as HTML and inject a CheckedHtmlElement

#### Scenario: Inject json_content
- **WHEN** a method parameter is named `json_content`
- **THEN** the decorator SHALL parse the response as JSON and inject the parsed dict

#### Scenario: Inject accumulated_data
- **WHEN** a method parameter is named `accumulated_data`
- **THEN** the decorator SHALL inject the request's accumulated_data dict

#### Scenario: Inject page
- **WHEN** a method parameter is named `page`
- **THEN** the decorator SHALL parse the response HTML via LXML and provide an `LxmlPageElement`

#### Scenario: Available injection names
- **THEN** the following parameter names SHALL be available for injection:
  - `response`: Response object
  - `request`: BaseRequest object
  - `previous_request`: Parent request from chain
  - `json_content`: Parsed JSON dict
  - `lxml_tree`: CheckedHtmlElement (parsed HTML)
  - `page`: PageElement (unified page interface, LXML-backed)
  - `text`: Response text
  - `accumulated_data`: Accumulated data dict
  - `aux_data`: Auxiliary data dict
  - `local_filepath`: Local file path (for ArchiveResponse)
  - `speculative_id`: Starting ID for speculative steps
