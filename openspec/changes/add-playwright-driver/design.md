## Context

This change builds on `add-unified-page-interface`, which provides the `PageElement` protocol, `LxmlPageElement` implementation, `SelectorObserver`, `Form`/`Link` abstractions, and `Via` types on `BaseRequest`. This change adds a Playwright-based driver that can render JavaScript-heavy pages while preserving step function purity.

The critical constraint: step functions are pure generators. They receive data, query it, and yield requests or parsed data. They never perform I/O. The driver handles all I/O — fetching pages, submitting forms, following links.

This means a step function cannot hold a live connection to a Playwright browser page. Querying a Playwright locator is I/O (it talks to a browser process), which would break purity.

### Stakeholders

- Scraper authors: need JavaScript-rendered pages accessible via the same `PageElement` interface
- Driver implementors: need a clear contract for Playwright integration
- Debugging tools (LocalDevDriver): need selector capture and autowait to work with Playwright

### Constraints

- Step functions MUST remain pure generators with no I/O
- The `PageElement` interface from `add-unified-page-interface` MUST be used unchanged
- Playwright pages must be fully rendered before the step sees them
- The HTTP driver MUST ignore Playwright-specific metadata (`await_list`, `auto_await_timeout`)

## Goals / Non-Goals

### Goals

1. Implement DOM snapshot model: Playwright renders, serializes to HTML, LXML parses
2. Provide `await_list` on `@step` decorator for explicit wait conditions
3. Provide autowait for automatic retry on element query failures
4. Handle `ViaFormSubmit` and `ViaLink` for browser-based form submission and navigation

### Non-Goals

- Exposing live Playwright page/locator objects to step functions (violates purity)
- Async step functions
- Complex multi-page flows within a single step (each step gets one snapshot)

## Decisions

### Decision 1: DOM Snapshot Model

The Playwright driver renders the page fully (handling JavaScript, waiting for network idle, etc.), then serializes the rendered DOM to an HTML string. That string is parsed by LXML into a `CheckedHtmlElement` / `PageElement`, which is injected into the step function.

This means:
- Step functions always query a static, in-memory HTML tree
- There is no `PlaywrightElement` class — everything is LXML-backed
- The step has no knowledge of whether HTTPX or Playwright fetched the page
- Selector capture is wired directly into `PageElement` — no context manager

The driver's lifecycle for a Playwright-backed request:
1. Navigate browser to URL (or submit form, or click link)
2. Wait for page to be ready (network idle, selectors present, etc.)
3. Serialize DOM: `page.content()` → HTML string
4. Parse HTML: `lxml.html.fromstring(html)` → `CheckedHtmlElement` → `PageElement`
5. Call step function with the static `PageElement`
6. Step yields requests → driver executes them as browser actions

**Alternatives considered:**
- Live Playwright queries in step functions (via sync bridge): Breaks purity. A step calling `locator.text_content()` performs I/O. This means step functions could have side effects, couldn't be replayed from WARC, and would be tied to a specific driver.
- Pre-materialized query results: Step declares selectors upfront, driver resolves them. Too rigid — scrapers need to make conditional queries based on intermediate results.

**Trade-off acknowledged:** The snapshot loses access to JavaScript-computed state that isn't reflected in the DOM (e.g., canvas content, Web Components with closed shadow DOM). For the court scraping domain, this is acceptable — the rendered DOM contains the data we need.

### Decision 2: `await_list` on `@step` decorator for Playwright wait conditions

The `@step` decorator gains an optional `await_list` parameter — a list of reified wait condition objects that the Playwright driver must satisfy before taking the DOM snapshot. Each condition corresponds to a Playwright `page.waitFor*` method. The HTTP driver ignores `await_list`. The `await_list` is stored on `StepMetadata` and read by the driver when invoking a continuation.

```python
@dataclass(frozen=True)
class WaitForSelector:
    selector: str
    state: str = "visible"  # "attached" | "detached" | "visible" | "hidden"
    timeout: int | None = None  # ms

@dataclass(frozen=True)
class WaitForLoadState:
    state: str = "networkidle"  # "load" | "domcontentloaded" | "networkidle"

@dataclass(frozen=True)
class WaitForURL:
    url: str  # substring, regex, or predicate
    timeout: int | None = None  # ms

@dataclass(frozen=True)
class WaitForTimeout:
    timeout: int  # ms — explicit sleep, last resort

# On StepMetadata (via @step decorator):
await_list: list[WaitForSelector | WaitForLoadState | WaitForURL | WaitForTimeout] = []
```

The `await_list` lives on the step decorator because it describes what the step function *needs to see* in the page before it can run. A step that parses a results table declares that it needs the table to be visible; a step that parses a search form declares that it needs the form to be present. This is metadata about the step's preconditions, not about a particular request's navigation path.

The Playwright driver processes the list in order:
1. Execute the browser action (navigate, submit form, etc.)
2. Look up the continuation's `StepMetadata` via `get_step_metadata()`
3. For each condition in the step's `await_list`: call the corresponding Playwright `waitFor*` method
4. After all waits complete, call `page.content()` to snapshot the DOM
5. Parse the snapshot and call the step function

```python
# Example: step that parses search results — declares it needs the table visible
@step(await_list=[
    WaitForLoadState("networkidle"),
    WaitForSelector("//table[@id='results']", state="visible"),
])
def parse_search_results(self, page: PageElement):
    rows = page.query_xpath("//table[@id='results']//tr", "result rows")
    ...

# The request that navigates to this step doesn't need to know about waits:
yield NavigatingRequest(
    request=HTTPRequestParams(method=HttpMethod.GET, url=url),
    continuation=self.parse_search_results,
)
```

This means every invocation of a given step uses the same wait conditions, which is the right default — a step's DOM requirements don't change based on how it was reached. If a future step truly needs different waits depending on the navigation path, it can be split into two steps with different `await_list` declarations.

**Alternatives considered:**
- `await_list` on `BaseRequest`: Allows per-request wait conditions, but puts driver-specific configuration on a data structure that step functions construct. Steps shouldn't need to know about Playwright wait strategies — that's the step's precondition metadata, not the request's concern.
- Injectable parameter on the step function: The step runs *after* the snapshot, so it can't declare what to wait for before its own snapshot.

### Decision 3: Autowait — retry step on structural failure with Playwright wait

The Playwright driver can automatically retry a step function when it fails due to content that hasn't rendered yet. The `@step` decorator gains an optional `auto_await_timeout` parameter (milliseconds) stored on `StepMetadata`. When set, the Playwright driver catches `HTMLStructuralAssumptionException` from element queries, waits for the failing selector to appear in the live browser, re-snapshots the DOM, and retries the step from scratch.

This complements `await_list`: the `await_list` handles known preconditions (networkidle, specific URL), while autowait catches residual element-level failures without the scraper author needing to enumerate every selector.

**Mechanism:**

1. Driver runs `await_list` conditions (if any) and takes initial snapshot
2. Driver calls step function with snapshot
3. Step raises `HTMLStructuralAssumptionException` on a `query_xpath` or `query_css` call
4. Driver inspects the exception to get the failing selector
5. If the selector is relative (starts with `.`), the driver uses the observer's query tree to compose an absolute selector by walking the parent chain
6. Driver checks if the composed selector is Playwright-compatible (`can_playwright_wait`)
7. If compatible: `page.wait_for_selector("xpath=" + composed, timeout=remaining)` (or CSS equivalent)
8. After the wait succeeds, driver calls `page.content()` for a fresh snapshot
9. Driver restarts the step function from the beginning with the new snapshot
10. If the step succeeds, its buffered yields are processed
11. If the step fails again (same or different selector), repeat from step 4
12. If `auto_await_timeout` is exhausted, raise the original exception

**Selector composition from observer:**

The `SelectorObserver` (from `add-unified-page-interface`) records the full query tree with parent-child relationships. When `.//td[@class='name']` fails and was executed on an element produced by `//table[@id='results']//tr`, the observer can compose:

```
//table[@id='results']//tr  +  .//td[@class='name']
                              → //table[@id='results']//tr//td[@class='name']
```

The composed selector doesn't need to be semantically identical to the scoped query — it just needs to signal that the content has rendered. For autowait, "approximately right" is sufficient.

**Playwright compatibility check:**

Not all lxml selectors can be used with Playwright's `wait_for_selector`. The `can_playwright_wait(selector, selector_type)` function (from `add-unified-page-interface`) filters out:
- **Non-element XPath targets**: selectors ending in `/text()` or `/@attr` (Playwright locators only target elements — these silently time out rather than matching)
- **EXSLT extensions**: `re:test()`, `str:*`, `math:*`, `set:*`, `dyn:*` (browser's `Document.evaluate` doesn't support EXSLT)
- **XPath variables**: `$name` (lxml-only feature)

String queries (`query_xpath_strings`) inherently target text/attribute nodes and are always excluded from autowait. Only element-returning queries (`query_xpath`, `query_css`, `find_form`, `find_links`) are autowait-eligible.

If the selector is not Playwright-compatible, the driver skips autowait and raises immediately — these failures are structural mismatches, not loading timing issues.

**Buffered yields:**

During an autowait-eligible step execution, the driver buffers all yields from the generator instead of processing them immediately. If the step completes without exception, the buffer is flushed and processed normally. If the step raises, the buffer is discarded and the step is restarted. This is necessary because the step is a generator — once it raises, it cannot be resumed, and any yields from a partial execution based on an incomplete snapshot must be discarded.

```python
@step(
    await_list=[WaitForLoadState("networkidle")],
    auto_await_timeout=10_000,  # 10 seconds
)
def parse_search_results(self, page: PageElement):
    # await_list ensures networkidle before first snapshot.
    # If the table still hasn't rendered (JS delay), autowait catches it:
    rows = page.query_xpath("//table[@id='results']//tr", "result rows")
    for row in rows:
        name = row.query_xpath(".//td[@class='name']", "name cell")
        # If this fails, driver composes //table[@id='results']//tr//td[@class='name']
        # and waits for it before re-snapshotting
        ...
```

**Trade-offs acknowledged:**

- **Slow genuine failures**: If a selector genuinely doesn't exist (structural change, not loading delay), autowait waits the full `auto_await_timeout` before failing. Mitigation: use `await_list` with `WaitForLoadState("networkidle")` as the primary mechanism; keep `auto_await_timeout` short (5-10 seconds).
- **Wasted first execution**: On JS-heavy pages without adequate `await_list`, the first step execution always fails and is discarded. The `await_list` should handle the common case; autowait is the safety net.
- **min_count ambiguity**: `query_xpath("//tr", "rows", min_count=5)` returning 3 rows — autowait can't distinguish "still loading" from "genuinely 3 rows." The driver waits for more rows that may never come. Mitigation: short timeout, and `await_list` should ensure the page is loaded before the step runs.
- **Mixed selector types**: Composing absolute selectors only works for same-type nesting (XPath parent + XPath child, or CSS parent + CSS child). Mixed nesting falls back to the child selector alone, which may be too broad.

**Alternatives considered:**
- No autowait, only `await_list`: Forces scraper authors to exhaustively declare every selector. Creates DRY violations between `await_list` and the step body's queries. Chosen as the primary mechanism but not the only one.
- Autowait without `await_list`: Would mean the first step execution always fails on JS pages. Too wasteful — `await_list` handles the predictable waits efficiently.
- Fixed polling interval instead of selector-targeted waits: Less efficient, doesn't leverage the observer's knowledge of what selector is needed.

### Decision 4: Playwright driver interprets `via` for browser actions

The Playwright driver pattern-matches on the `via` field (from `add-unified-page-interface`) to execute browser actions:
- `ViaLink`: navigate to URL (same as `via=None`)
- `ViaFormSubmit`: locate the form by `form_selector`, fill fields from `field_data`, click the element at `submit_selector`
- `None`: navigate to URL from `HTTPRequestParams`

If the Playwright driver cannot locate the form or submit element in the live DOM using the selector from `via`, it raises `HTMLStructuralAssumptionException`. This is the same error type used when a selector fails during step function parsing — the selector worked on the snapshot but the live DOM doesn't match, which is a structural assumption violation.

### Decision 5: `page` injection in step decorator

The `@step` decorator adds support for a `page` parameter name that injects an `LxmlPageElement`. When injecting `page`:
1. Parse response HTML via LXML into `CheckedHtmlElement`
2. Create a `SelectorObserver` instance
3. Construct `LxmlPageElement(checked_element, url, observer)`
4. Inject as `page` parameter

After the step function returns (or raises), the driver can inspect the observer for:
- Debugging (what selectors were used)
- Autowait (composing absolute selectors from the query tree)

This works identically for HTTP and Playwright drivers — the `page` injection is driver-agnostic. The driver-specific behavior is in how the HTML is obtained (HTTP fetch vs Playwright render + serialize).

## Risks / Trade-offs

- **Snapshot is a point-in-time view**: If the page changes after the snapshot (e.g., lazy-loaded content), the step won't see updates. Mitigation: the Playwright driver should wait for the page to be fully rendered before snapshotting.
- **Playwright dependency**: Adds a significant dependency. Mitigation: Playwright is optional — only scrapers that need it will use it.
- **Browser resource overhead**: Running a browser is heavier than HTTP requests. Mitigation: Use HTTP driver where possible; Playwright only for JS-required sites.

### Decision 6: LocalDevDriver-compatible database schema

The Playwright driver uses the same SQLite schema as LocalDevDriver. This enables:
- Full compatibility with `ldd-debug` CLI and LocalDevDriverDebugger
- Run resumption with the same semantics
- Response caching and compression dictionaries
- Error tracking and requeue operations
- WARC export

**Key mapping from Playwright to schema:**
- Navigation + DOM snapshot → `requests` row + `responses` row (content = serialized DOM)
- Form submission → same, with `via` field populated in request serialization
- Step yields → `results` table
- Step exceptions → `errors` table with type-specific fields

The only schema addition is the `incidental_requests` table (Decision 7).

### Decision 7: Incidental requests table for browser-initiated network activity

Playwright makes many network requests that aren't directly initiated by `BaseRequest` subclasses: images, stylesheets, scripts, XHR/fetch calls, fonts, etc. These need to be captured for:
- Debugging (what resources failed to load?)
- Cache validation (can we replay from cache?)
- WARC completeness (archive all network activity)

The `incidental_requests` table captures these with:
- `parent_request_id` linking to the navigation that triggered them
- `resource_type` from Playwright's classification
- Request/response details, compressed content
- Timing and caching metadata
- Blocking status (if route interception blocked the request)

**Caching strategy:** A primary request cache hit requires all associated incidental requests to also have cache hits. This ensures the DOM snapshot is consistent with the resources that were available when it was captured.

**Storage limits:** Large binary resources (images, fonts) can be excluded or truncated based on driver configuration. The goal is debugging and archival, not perfect fidelity.

### Decision 8: Rate limiting via pyrate_limiter

The Playwright driver uses `pyrate_limiter` with `AioSQLiteBucket` for rate limiting, identical to LocalDevDriver. This provides:
- Persistent rate limiting state across restarts
- Configurable rate limits (requests per second, per minute, etc.)
- Burst handling with multiple rate tiers

**Only primary navigations are rate-limited.** Incidental requests (browser-initiated resource loads) are not counted against the rate limit — they're a side effect of the navigation, not separate intentional requests. This matches how courts view "a page load" vs "N requests."

**Jitter** is applied after the rate limiter wait time to avoid thundering herd effects.

### Decision 9: Browser lifecycle — context per run, page reuse

A single browser context is used for the entire run:
- Cookies and storage persist across navigations (important for session handling)
- Configuration (viewport, user agent) is consistent
- Stored in `run_metadata.browser_config_json` for resumption

Pages are reused where possible to reduce overhead. A new page is created only for:
- Popup/new tab handling
- Parallel navigation (if supported in future)

On run resumption, a new browser context is created with the same configuration. Cookie restoration is out of scope for initial implementation — the resume behavior is: pending requests are re-executed, responses are not re-fetched if cached.

### Decision 10: LDD-Debug compatibility as a hard requirement

The Playwright driver's artifacts MUST work with `ldd-debug`. This is not optional. Specific extensions:
- `ldd-debug incidental list|show|content` — new commands for incidental requests
- `ldd-debug diagnose` — works on DOM snapshots identically to HTTP responses
- `ldd-debug compare` — replays step functions with stored DOM snapshots
- `ldd-debug export warc` — includes incidental requests grouped with parent

The debugger doesn't need to know whether the run was HTTP or Playwright — the schema is the same.

## Risks / Trade-offs

- **Snapshot is a point-in-time view**: If the page changes after the snapshot (e.g., lazy-loaded content), the step won't see updates. Mitigation: the Playwright driver should wait for the page to be fully rendered before snapshotting.
- **Playwright dependency**: Adds a significant dependency. Mitigation: Playwright is optional — only scrapers that need it will use it.
- **Browser resource overhead**: Running a browser is heavier than HTTP requests. Mitigation: Use HTTP driver where possible; Playwright only for JS-required sites.
- **Incidental requests storage**: Can grow large. Mitigation: Configurable exclusion of binary resources, compression.
- **Cache complexity**: Validating incidental request cache hits is complex. Mitigation: Conservative cache invalidation — any missing incidental request invalidates the cache.

## Open Questions

1. ~~Should there be a browser pool / context reuse strategy, or is a fresh browser per scraper run acceptable?~~ Resolved: Single context per run, page reuse.
2. Should incidental request content storage be opt-in or opt-out? (Current design: opt-out for large binaries)
3. Should we support parallel page workers within a single run? (Deferred to future enhancement)
