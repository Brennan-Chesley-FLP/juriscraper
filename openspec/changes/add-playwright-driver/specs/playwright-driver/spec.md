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

### Requirement: Playwright Driver Database Persistence (LocalDevDriver Compatible)

The Playwright driver SHALL persist all run state to an SQLite database using the same schema as LocalDevDriver. This enables run resumption, debugging, and tooling compatibility.

#### Scenario: Same database schema as LocalDevDriver
- **WHEN** a Playwright driver initializes a new run
- **THEN** the driver SHALL create an SQLite database with the same schema as LocalDevDriver
- **AND** the database SHALL contain tables: `requests`, `responses`, `results`, `errors`, `run_metadata`, `compression_dicts`, `archived_files`, `rate_bucket`, `rate_items`, `rate_limiter_state`, `speculative_progress`, `speculation_tracking`, `speculative_start_ids`, `schema_info`
- **AND** the schema version and migration logic SHALL be identical to LocalDevDriver

#### Scenario: Request persistence
- **WHEN** the Playwright driver executes a request from a `NavigatingRequest` or `NonNavigatingRequest`
- **THEN** the driver SHALL insert a row into the `requests` table with the same fields as LocalDevDriver
- **AND** the `request_type` field SHALL be populated (`navigating`, `non_navigating`, `archive`)
- **AND** the `cache_key` SHALL be computed as SHA256(method, url, body, headers_json)
- **AND** nanosecond timing fields (`created_at_ns`, `started_at_ns`, `completed_at_ns`) SHALL be populated

#### Scenario: Response persistence
- **WHEN** the Playwright driver receives a response (via page navigation or fetch)
- **THEN** the driver SHALL store the response in the `responses` table
- **AND** the response content SHALL be the serialized DOM snapshot (from `page.content()`)
- **AND** the content SHALL be Zstd-compressed with optional dictionary compression
- **AND** the `compression_dict_id` SHALL reference `compression_dicts` if dictionary compression is used

#### Scenario: Result and error persistence
- **WHEN** a step function yields `ParsedData`
- **THEN** the driver SHALL store it in the `results` table with validation status
- **WHEN** a step function raises an exception
- **THEN** the driver SHALL store it in the `errors` table with type-specific fields (structural, validation, transient)

#### Scenario: Run metadata persistence
- **WHEN** a Playwright driver run is created
- **THEN** the driver SHALL store scraper identity, invocation parameters, and run state in `run_metadata`
- **AND** the `params_json` SHALL contain the ScraperParams filters

### Requirement: Incidental Requests Tracking

The Playwright driver SHALL track all network requests made by the browser that are not directly initiated by `BaseRequest` subclasses. These "incidental requests" include images, stylesheets, scripts, fonts, XHR/fetch calls, and other resources loaded by the page.

#### Scenario: Incidental requests table schema
- **WHEN** a Playwright driver initializes a database
- **THEN** the database SHALL contain an `incidental_requests` table with schema:
  ```sql
  CREATE TABLE IF NOT EXISTS incidental_requests (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      parent_request_id INTEGER NOT NULL REFERENCES requests(id),

      -- Request info
      resource_type TEXT NOT NULL,        -- document, stylesheet, image, script, font, xhr, fetch, etc.
      method TEXT NOT NULL,
      url TEXT NOT NULL,
      headers_json TEXT,
      body BLOB,

      -- Response info (NULL if request failed/blocked)
      status_code INTEGER,
      response_headers_json TEXT,
      content_compressed BLOB,            -- Zstd-compressed response body
      content_size_original INTEGER,
      content_size_compressed INTEGER,
      compression_dict_id INTEGER REFERENCES compression_dicts(id),

      -- Timing
      started_at_ns INTEGER,
      completed_at_ns INTEGER,

      -- Metadata
      from_cache BOOLEAN,                 -- Whether browser served from cache
      failure_reason TEXT,                -- If request failed: 'timeout', 'aborted', etc.

      created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
  )
  ```

#### Scenario: Capture incidental requests during navigation
- **WHEN** the Playwright driver navigates to a URL or submits a form
- **THEN** the driver SHALL register a network request listener via `page.on('request')` and `page.on('response')`
- **AND** all network requests made by the browser during the navigation SHALL be captured
- **AND** each captured request SHALL be stored in `incidental_requests` with `parent_request_id` linking to the primary request

#### Scenario: Resource type classification
- **WHEN** an incidental request is captured
- **THEN** the `resource_type` field SHALL be populated from Playwright's `request.resource_type()`
- **AND** recognized types SHALL include: `document`, `stylesheet`, `image`, `media`, `font`, `script`, `texttrack`, `xhr`, `fetch`, `eventsource`, `websocket`, `manifest`, `other`

#### Scenario: Response content storage for incidental requests
- **WHEN** an incidental request receives a response
- **THEN** the response body SHALL be compressed with Zstd and stored in `content_compressed`

#### Scenario: Cache key lookup includes incidental requests
- **WHEN** the Playwright driver checks for a cached response
- **THEN** the driver SHALL check both `requests.cache_key` and `incidental_requests` for cache hits
- **AND** if the primary request has a cache hit AND all associated incidental requests have cache hits
- **THEN** the driver MAY skip the network request and replay from cache

### Requirement: LDD-Debug Tool Compatibility

The Playwright driver's database artifacts SHALL be fully compatible with the `ldd-debug` CLI and LocalDevDriverDebugger class. All debugging, inspection, and manipulation operations SHALL work identically.

#### Scenario: ldd-debug info command
- **WHEN** `ldd-debug info <playwright-run.db>` is executed
- **THEN** the command SHALL display run metadata, statistics, and status
- **AND** output SHALL include Playwright-specific metadata (browser type, viewport size, etc.)

#### Scenario: ldd-debug requests commands
- **WHEN** `ldd-debug requests list|show|summary` is executed on a Playwright run database
- **THEN** the commands SHALL work identically to LocalDevDriver databases
- **AND** request details SHALL include the `via` field interpretation (ViaFormSubmit, ViaLink)

#### Scenario: ldd-debug responses commands
- **WHEN** `ldd-debug responses list|show|content|search` is executed on a Playwright run database
- **THEN** the commands SHALL work identically to LocalDevDriver databases
- **AND** response content SHALL be the serialized DOM snapshot (decompressed)
- **AND** XPath/CSS search SHALL work on the DOM snapshot content

#### Scenario: ldd-debug incidental command (new)
- **WHEN** `ldd-debug incidental list <db>` is executed
- **THEN** the command SHALL list all incidental requests grouped by parent request
- **AND** filters SHALL include: `--resource-type`, `--status-code`, `--parent-request-id`

#### Scenario: ldd-debug incidental show
- **WHEN** `ldd-debug incidental show <db> <id>` is executed
- **THEN** the command SHALL display full incidental request details including headers and timing

#### Scenario: ldd-debug incidental content
- **WHEN** `ldd-debug incidental content <db> <id>` is executed
- **THEN** the command SHALL display the decompressed response content

#### Scenario: ldd-debug diagnose compatibility
- **WHEN** `ldd-debug diagnose <playwright-run.db> <error-id>` is executed
- **THEN** the diagnose command SHALL re-run XPath observation on the stored DOM snapshot
- **AND** the observer SHALL work on the serialized HTML exactly as it would for HTTP-fetched content

#### Scenario: ldd-debug compare compatibility
- **WHEN** `ldd-debug compare <playwright-run.db> <continuation>` is executed
- **THEN** the compare command SHALL replay step functions using stored DOM snapshots
- **AND** dry-run mode SHALL inject the stored `PageElement` (from serialized DOM)
- **AND** comparison SHALL detect data and request tree changes

#### Scenario: ldd-debug requeue compatibility
- **WHEN** `ldd-debug requeue request|continuation|errors` is executed on a Playwright run database
- **THEN** the requeue operations SHALL work identically to LocalDevDriver
- **AND** requeued requests SHALL clear associated incidental requests when `--clear-responses` is used

#### Scenario: WARC export includes incidental requests
- **WHEN** `ldd-debug export warc <playwright-run.db> <output>` is executed
- **THEN** the WARC export SHALL include both primary responses and incidental requests
- **AND** incidental requests SHALL be grouped with their parent request record

### Requirement: Rate Limiting via pyrate_limiter

The Playwright driver SHALL use pyrate_limiter for rate limiting, with persistent state stored in the SQLite database. The rate limiter SHALL control the pace of browser navigations.

#### Scenario: pyrate_limiter integration
- **WHEN** the Playwright driver is initialized
- **THEN** the driver SHALL create a `pyrate_limiter.Limiter` with configurable `Rate` objects

#### Scenario: Navigation rate limiting
- **WHEN** the Playwright driver is about to navigate to a new URL
- **THEN** the driver SHALL acquire a token from the rate limiter
- **AND** if no token is available, the driver SHALL wait until one becomes available
- **AND** the wait time SHALL be calculated from the configured rate limits

#### Scenario: Rate limiter configuration
- **WHEN** a Playwright driver is opened with rate limiting configuration
- **THEN** the driver SHALL accept a `rates: list[Rate]` parameter
- **AND** common configurations SHALL include:
  - Single rate: `[Rate(1, Duration.SECOND)]` — 1 request per second
  - Burst with sustained: `[Rate(5, Duration.SECOND), Rate(30, Duration.MINUTE)]` — 5/sec burst, 30/min sustained

#### Scenario: Rate limiting bypassed for incidental requests
- **WHEN** the browser makes incidental requests (images, scripts, etc.)
- **THEN** incidental requests SHALL NOT consume rate limiter tokens
- **AND** only primary navigations (from `NavigatingRequest`/`NonNavigatingRequest`) SHALL be rate-limited

#### Scenario: Adaptive rate limiting (optional)
- **WHEN** the driver receives a 429 (Too Many Requests) or 5xx response
- **THEN** the driver MAY reduce the rate limit dynamically
- **AND** rate limiter state changes SHALL be persisted in `rate_limiter_state` table

#### Scenario: Jitter support
- **WHEN** the driver is configured with jitter
- **THEN** the driver SHALL add random jitter (±configured seconds) to wait times
- **AND** jitter SHALL be applied after rate limiter wait time is calculated

### Requirement: Browser Lifecycle Management

The Playwright driver SHALL manage browser and context lifecycle efficiently, reusing resources where appropriate.

#### Scenario: Browser context per run
- **WHEN** a Playwright driver run is started
- **THEN** the driver SHALL create a single browser context for the entire run
- **AND** the context SHALL be configured with: viewport size, user agent, locale, timezone
- **AND** the context SHALL persist cookies and storage across navigations within the run

#### Scenario: Page reuse within context
- **WHEN** the driver processes sequential navigations
- **THEN** the driver SHALL reuse the same page instance when possible
- **AND** a new page SHALL be created only when required (e.g., popup handling, parallel tabs)

#### Scenario: Browser configuration persistence
- **WHEN** a run is created
- **THEN** browser configuration SHALL be stored in `run_metadata` as `browser_config_json`:
  ```json
  {
    "browser_type": "chromium",
    "headless": true,
    "viewport": {"width": 1280, "height": 720},
    "user_agent": "...",
    "locale": "en-US",
    "timezone_id": "America/New_York"
  }
  ```

#### Scenario: Run resumption with browser config
- **WHEN** a Playwright driver resumes an existing run
- **THEN** the driver SHALL read browser configuration from `run_metadata.browser_config_json`
- **AND** the driver SHALL create a new browser context with the same configuration
- **AND** stored cookies/storage MAY be restored from a separate persistence mechanism


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
