## Context

Scraper step functions currently receive `lxml_tree: CheckedHtmlElement`, which wraps `lxml.html.HtmlElement`. This works, but the API is tightly coupled to LXML. To support multiple driver types using the same step function code, we need a common interface for data extraction, form submission, and link following.

The critical constraint: step functions are pure generators. They receive data, query it, and yield requests or parsed data. They never perform I/O. The driver handles all I/O — fetching pages, submitting forms, following links.

### Stakeholders

- Scraper authors: need a simple, consistent API for data extraction that works identically regardless of driver
- Driver implementors: need a clear contract for injecting page content
- Debugging tools (LocalDevDriver): need selector capture wired directly into the page interface

### Constraints

- Step functions MUST remain pure generators with no I/O
- Existing scrapers use `lxml_tree: CheckedHtmlElement` and must continue working unchanged
- The `@step` decorator controls argument injection and must support the new parameter

## Goals / Non-Goals

### Goals

1. Define a `PageElement` protocol for data extraction, always backed by static parsed HTML
2. Provide `Form` and `Link` value objects for navigation actions
3. Maintain backward compatibility: `lxml_tree` continues to work
4. Integrate selector observation directly into `PageElement` — no context manager indirection

### Non-Goals

- Rewriting existing scrapers to use the new interface (migration is opt-in)
- Async step functions
- Driver-specific behaviors (those belong in the respective driver specs)

## Decisions

### Decision 1: Protocol-based interface using `typing.Protocol`

Use `typing.Protocol` (structural subtyping) rather than ABC inheritance. This lets `CheckedHtmlElement` satisfy the protocol by adding the right methods, without changing its inheritance chain.

**Alternatives considered:**
- ABC base class: Would require `CheckedHtmlElement` to inherit from it, changing existing code unnecessarily.
- Duck typing without protocol: Loses static type checking.

### Decision 2: Form and Link as value objects that return NavigatingRequest

`Form` and `Link` are pure value objects constructed from parsed HTML. They do not perform I/O. Instead:
- `Link.follow()` returns a `NavigatingRequest` that the step yields
- `Form.submit(data, submit_selector)` returns a `NavigatingRequest` that the step yields

`Form.submit()` always returns `NavigatingRequest`. The `NavigatingRequest` vs `NonNavigatingRequest` distinction exists only for the HTTPX driver's relative URL resolution logic. Since form submission always causes a page transition from the scraper's perspective, `NavigatingRequest` is the correct type uniformly.

`Form.submit()` accepts an optional `submit_selector` parameter — an XPath or CSS selector relative to the form element, identifying which submit button to click. This enables drivers that need to know which button was clicked (e.g., for browser-based form submission). The selector is scoped to the form, so XPath selectors start with `./` (e.g., `.//input[@id='btnSearch']`). The HTTP driver ignores this parameter — it just POSTs the encoded form data. The selector and field data are carried on the `NavigatingRequest` so the driver can interpret them appropriately.

The driver receives these requests and decides how to execute them:
- HTTP driver: sends an HTTP GET/POST with form-encoded data
- Other drivers: may use the `via` field to determine how to replay the action

This preserves the generator-based architecture where steps yield requests and drivers execute them. The step doesn't know or care how the request is fulfilled.

**Alternatives considered:**
- Forms/Links that directly perform navigation: Would bypass the driver's request queue, deduplication, rate limiting, interceptors, and break purity.
- Returning raw URL strings: Doesn't capture form encoding, method, hidden fields.
- Omitting submit selector: Drivers that need it would have to guess which button to click.

### Decision 3: Form.submit() auto-includes hidden fields

When `Form.submit(data)` is called, hidden field values are included automatically in the request. The `data` parameter overrides defaults. This means the common pattern of manually extracting `__VIEWSTATE` and similar hidden fields (as seen in the Connecticut scraper) becomes unnecessary — `Form` handles it.

The step can still inspect and override any field:
```python
form = page.find_form("//form[@id='search']", "search form")
# Hidden fields like __VIEWSTATE are included automatically
# Override specific fields, specify which button to click:
yield form.submit(
    data={"query": "civil rights", "date_from": "2024-01-01"},
    submit_selector=".//input[@id='btnSearch']",
)
```

### Decision 4: Element hierarchy

```
PageElement (Protocol)
  ├── query_xpath(selector, description, min_count, max_count) -> list[PageElement]
  ├── query_xpath_strings(selector, description, min_count, max_count) -> list[str]
  ├── query_css(selector, description, min_count, max_count) -> list[PageElement]
  ├── text_content() -> str
  ├── get_attribute(name) -> str | None
  ├── inner_html() -> str
  ├── tag_name() -> str
  ├── find_form(selector, description) -> Form
  ├── links() -> list[Link]
  └── find_links(selector, description) -> list[Link]

Form (value object, constructed from parsed <form> element)
  ├── action -> str          (resolved absolute URL)
  ├── method -> str          ("GET" or "POST")
  ├── fields -> list[FormField]
  ├── get_field(name) -> FormField | None
  └── submit(data: dict | None, submit_selector: str | None) -> NavigatingRequest

FormField (value object)
  ├── name -> str
  ├── field_type -> str      ("text", "hidden", "select", "checkbox", etc.)
  ├── value -> str | None    (current/default value)
  └── options -> list[str]   (for select elements)

Link (value object, constructed from parsed <a> element)
  ├── url -> str             (resolved absolute URL)
  ├── text -> str
  └── follow() -> NavigatingRequest
```

Only one implementation: `LxmlPageElement` wraps `CheckedHtmlElement` and delegates to its existing methods.

### Decision 5: `via` parameter on BaseRequest

`BaseRequest` gains an optional `via` field that describes how the request was produced — either from a link or a form submission. Drivers can use `via` to determine how to execute the request appropriately. The HTTP driver ignores it and uses `HTTPRequestParams` as usual.

```python
@dataclass(frozen=True)
class ViaLink:
    selector: str          # selector that found the <a> element
    description: str

@dataclass(frozen=True)
class ViaFormSubmit:
    form_selector: str     # selector that found the <form>
    submit_selector: str | None  # relative to form, e.g. ".//button[@id='go']"
    field_data: dict[str, str]   # merged hidden + user-provided field values
    description: str

# On BaseRequest:
via: ViaLink | ViaFormSubmit | None = None
```

`Link.follow()` populates `ViaLink`. `Form.submit()` populates `ViaFormSubmit`. Manually constructed requests have `via=None`.

**Alternatives considered:**
- `FormSubmitRequest` subclass: Adds to the request type hierarchy that drivers must pattern-match on. `via` is metadata on the existing types, not a new type.
- Metadata in `aux_data`: Untyped, easy to misspell keys, no static checking. `via` is a typed union.

### Decision 6: Scrapers always specify selectors for forms

`PageElement` does not provide a no-argument `forms()` method. Form discovery always requires a selector via `find_form(selector, description)`. This ensures every form interaction has an explicit, auditable selector that can be captured by the observer.

### Decision 7: Selector observer is a construction parameter on PageElement

The existing `XPathObserver` uses a context variable (`contextvars.ContextVar`) — `CheckedHtmlElement` calls `get_active_observer()` on every query to find the observer. This works but is indirect: the observer is hidden global state, you have to remember to wrap calls in `with XPathObserver()`, and the relationship between the page and its observer is implicit.

For `PageElement`, the observer is an explicit construction parameter:

```python
observer = SelectorObserver()
page = LxmlPageElement(tree, url, observer=observer)

# Step runs — every query automatically recorded
step_fn(page=page)

# Driver inspects results — no context manager needed
print(observer.simple_tree())
```

The recording logic (query trees, deduplication, sample capture, formatting) stays the same — it's the `SelectorObserver` class (renamed from `XPathObserver` since it now covers CSS and form/link queries too). What changes is how it's wired in:

- **`LxmlPageElement` holds an `observer` reference**, passed at construction
- **Child elements inherit the observer**: when `query_xpath()` returns child `LxmlPageElement`s, each carries the same observer reference
- **All query methods record to `self._observer`** if it's not `None`
- **No context variable, no `with` block** — the observer is explicitly owned by whoever creates the `PageElement`
- **`CheckedHtmlElement` keeps its existing context variable pattern** for backward compatibility with `lxml_tree`. The two mechanisms are independent — `lxml_tree` uses the old pattern, `page` uses the new one.

**Alternatives considered:**
- Keep the context variable pattern for `PageElement` too: Works, but the whole point of `PageElement` is a cleaner interface. Hidden global state undermines that.
- Make `PageElement` protocol require an `observer` property: Over-constrains the protocol. The observer is an implementation detail of `LxmlPageElement`, not part of the query interface that scraper authors use.

### Decision 8: HTMLStructuralAssumptionException carries selector context

`HTMLStructuralAssumptionException` is enriched to carry the failing selector, selector type, and whether it was an element query or string query. This enables drivers to make decisions based on what failed (e.g., for retry logic or debugging).

```python
# Exception attributes:
selector: str           # the selector that failed
selector_type: str      # "xpath" or "css"
is_element_query: bool  # True for query_xpath/query_css, False for query_xpath_strings
```

### Decision 9: SelectorObserver provides absolute selector composition

The `SelectorObserver` provides a `compose_absolute_selector(query)` method that walks the parent chain and concatenates selectors, stripping relative prefixes (leading `.` or `./`). This is useful for drivers that need to wait for elements identified by relative selectors.

Example:
```
//table[@id='results']//tr  +  .//td[@class='name']
                              → //table[@id='results']//tr//td[@class='name']
```

If the parent chain contains mixed selector types (XPath parent + CSS child or vice versa), the method returns `None`.

### Decision 10: can_playwright_wait utility function

A static `can_playwright_wait(selector, selector_type)` function determines whether a selector can be used with browser-based waiting. It returns `False` for:
- **Non-element XPath targets**: selectors ending in `/text()` or `/@attr`
- **EXSLT extensions**: `re:test()`, `str:*`, `math:*`, `set:*`, `dyn:*`
- **XPath variables**: `$name`

CSS selectors always return `True`.

## Risks / Trade-offs

- **Two naming conventions**: `checked_xpath` (existing) vs `query_xpath` (new). Mitigation: clear documentation that `page` is the new unified interface; `lxml_tree` is the legacy LXML-specific one.
- **Form abstraction fidelity**: Static form analysis cannot capture JavaScript-attached event handlers or AJAX submissions. But drivers can handle these — the step just yields `form.submit()` and the driver decides how to execute it.

## Migration Plan

1. Implement `PageElement` protocol and `LxmlPageElement` adapter
2. Implement `Form`, `FormField`, `Link` value objects
3. Implement `SelectorObserver` with `compose_absolute_selector` and `can_playwright_wait`
4. Write one scraper using `page: PageElement` as proof of concept
5. Existing scrapers continue using `lxml_tree` unchanged; migration is per-scraper, opt-in

Rollback: Since `lxml_tree` is unchanged and `page` is opt-in, reverting just means removing the new protocol and adapter. No existing code is affected.

## Open Questions

1. Should there be a `Page` top-level object distinct from `PageElement`, representing the full document with URL context for resolving relative URLs? Or does passing the URL into `LxmlPageElement` constructor suffice?
