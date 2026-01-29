## ADDED Requirements

### Requirement: PageElement Protocol for Unified Data Extraction

The system SHALL provide a `PageElement` protocol (using `typing.Protocol`) that defines a common interface for querying elements, extracting text and attributes, and navigating the DOM. `PageElement` SHALL always be backed by static parsed HTML (LXML). The driver is responsible for obtaining the HTML, whether via HTTP or by serializing a rendered Playwright DOM.

#### Scenario: Query elements by XPath
- **WHEN** `page.query_xpath(selector, description, min_count=1)` is called
- **THEN** elements matching the XPath selector SHALL be returned as `list[PageElement]`
- **AND** if the result count is below `min_count` or above `max_count`, an `HTMLStructuralAssumptionException` SHALL be raised
- **AND** the query SHALL be recorded by the `PageElement`'s `SelectorObserver` if one was provided at construction

#### Scenario: Query string values by XPath
- **WHEN** `page.query_xpath_strings(selector, description, min_count=1)` is called
- **THEN** string results (text nodes, attribute values) SHALL be returned as `list[str]`
- **AND** count validation and observer recording SHALL apply

#### Scenario: Query elements by CSS selector
- **WHEN** `page.query_css(selector, description, min_count=1)` is called
- **THEN** elements matching the CSS selector SHALL be returned as `list[PageElement]`
- **AND** count validation and observer recording SHALL apply

#### Scenario: Extract text content
- **WHEN** `element.text_content()` is called on a `PageElement`
- **THEN** the visible text content of the element and its descendants SHALL be returned as a string

#### Scenario: Extract attribute value
- **WHEN** `element.get_attribute(name)` is called on a `PageElement`
- **THEN** the value of the named attribute SHALL be returned, or `None` if the attribute does not exist

#### Scenario: Get inner HTML
- **WHEN** `element.inner_html()` is called on a `PageElement`
- **THEN** the inner HTML content of the element SHALL be returned as a string

#### Scenario: Get tag name
- **WHEN** `element.tag_name()` is called on a `PageElement`
- **THEN** the element's tag name SHALL be returned as a lowercase string

### Requirement: LXML PageElement Implementation

The system SHALL provide an `LxmlPageElement` class that wraps `CheckedHtmlElement` and implements the `PageElement` protocol. This is the only implementation — all step functions work against LXML-parsed HTML regardless of which driver fetched the content.

#### Scenario: LxmlPageElement wraps CheckedHtmlElement
- **WHEN** an `LxmlPageElement` is constructed from a `CheckedHtmlElement`
- **THEN** `query_xpath()` SHALL delegate to `checked_xpath()`
- **AND** `query_css()` SHALL delegate to `checked_css()`
- **AND** `text_content()` SHALL delegate to the underlying lxml element's `text_content()`

#### Scenario: LxmlPageElement returns LxmlPageElement children
- **WHEN** `query_xpath()` or `query_css()` returns child elements
- **THEN** each child SHALL be wrapped in `LxmlPageElement`
- **AND** nested queries on children SHALL work recursively

#### Scenario: Observer wired at construction
- **WHEN** an `LxmlPageElement` is constructed with an optional `SelectorObserver`
- **THEN** all query methods (`query_xpath`, `query_css`, `find_form`, `find_links`, `links`) SHALL record to the observer
- **AND** child `LxmlPageElement`s returned from queries SHALL inherit the same observer

#### Scenario: Observer not provided
- **WHEN** an `LxmlPageElement` is constructed without an observer
- **THEN** query methods SHALL execute normally without recording
- **AND** no error SHALL occur

### Requirement: Form Abstraction

The system SHALL provide a `Form` value object that represents an HTML `<form>` element with its fields, action URL, and submission method. Forms SHALL be discoverable via `PageElement.find_form(selector, description)`. Scrapers MUST always specify a selector to locate a form — no unfiltered `forms()` method is provided. `Form` is a pure value object constructed from parsed HTML — it performs no I/O.

#### Scenario: Find a form by selector
- **WHEN** `page.find_form(selector, description)` is called
- **THEN** the first `<form>` matching the selector SHALL be returned as a `Form`
- **AND** the `Form` SHALL store the selector that found it (for replay by Playwright driver)
- **AND** the `Form` SHALL expose `action` (resolved URL), `method` (GET or POST), and `fields`
- **AND** if no form matches, an `HTMLStructuralAssumptionException` SHALL be raised

#### Scenario: Introspect form fields
- **WHEN** `form.fields` is accessed
- **THEN** all `<input>`, `<select>`, and `<textarea>` elements within the form SHALL be returned as `list[FormField]`
- **AND** each `FormField` SHALL expose `name`, `field_type`, `value` (current/default value), and `options` (for select elements)

#### Scenario: Get a specific field by name
- **WHEN** `form.get_field(name)` is called
- **THEN** the `FormField` with the matching `name` attribute SHALL be returned, or `None` if not found

#### Scenario: Submit a form as a request
- **WHEN** `form.submit(data, submit_selector)` is called with optional field overrides and an optional submit element selector
- **THEN** a `NavigatingRequest` SHALL be returned with the form's `action` as URL and `method` as HTTP method
- **AND** all field values (including hidden fields) SHALL be included automatically
- **AND** the `data` parameter SHALL override default field values
- **AND** for GET forms, field data SHALL be encoded as query parameters
- **AND** for POST forms, field data SHALL be encoded as form-encoded body
- **AND** the `submit_selector` SHALL be relative to the form element (e.g., XPath selectors start with `./`)
- **AND** the returned `NavigatingRequest` SHALL have `via` set to a `ViaFormSubmit` carrying the form selector, submit selector, and merged field data
- **AND** the step SHALL yield the returned request for the driver to execute

### Requirement: Link Abstraction

The system SHALL provide a `Link` value object that represents an `<a>` element with its resolved URL and text content. Links SHALL be discoverable via `PageElement.links()` and `PageElement.find_links()`. `Link` is a pure value object — it performs no I/O.

#### Scenario: Discover all links
- **WHEN** `page.links()` is called
- **THEN** all `<a>` elements with `href` attributes SHALL be returned as `list[Link]`
- **AND** each `Link` SHALL expose `url` (resolved absolute URL) and `text` (visible text content)

#### Scenario: Find links matching a selector
- **WHEN** `page.find_links(selector, description)` is called
- **THEN** `<a>` elements matching the selector SHALL be returned as `list[Link]`

#### Scenario: Follow a link
- **WHEN** `link.follow()` is called
- **THEN** a `NavigatingRequest` SHALL be returned with the link's resolved URL
- **AND** the request SHALL use `HttpMethod.GET`
- **AND** the returned `NavigatingRequest` SHALL have `via` set to a `ViaLink` carrying the selector that found the link
- **AND** the step SHALL yield the returned request for the driver to execute

### Requirement: Via Parameter on BaseRequest

`BaseRequest` SHALL provide an optional `via` field that describes how the request was produced — from a link click, a form submission, or manually constructed. The `via` field enables the Playwright driver to replay the browser action that corresponds to the request. The HTTP driver ignores `via`.

#### Scenario: ViaLink for link-originated requests
- **WHEN** `link.follow()` constructs a `NavigatingRequest`
- **THEN** `via` SHALL be set to `ViaLink(selector, description)` where `selector` is the XPath/CSS that found the `<a>` element

#### Scenario: ViaFormSubmit for form-originated requests
- **WHEN** `form.submit()` constructs a `NavigatingRequest`
- **THEN** `via` SHALL be set to `ViaFormSubmit(form_selector, submit_selector, field_data, description)` where `form_selector` is the selector that found the `<form>`, `submit_selector` is relative to the form, and `field_data` is the merged field values

#### Scenario: Manually constructed requests have no via
- **WHEN** a step function constructs a `NavigatingRequest` directly (not via `Form` or `Link`)
- **THEN** `via` SHALL default to `None`
- **AND** the driver SHALL execute the request using `HTTPRequestParams` as usual

#### Scenario: HTTP driver ignores via
- **WHEN** an HTTP driver receives a request with `via` set
- **THEN** the driver SHALL ignore the `via` field
- **AND** the driver SHALL execute the request using `HTTPRequestParams`

### Requirement: SelectorObserver Integrated into PageElement

The system SHALL provide a `SelectorObserver` class (replacing the context-variable-based `XPathObserver` for `PageElement` usage) that records query trees, deduplicates repeated selectors, captures sample content, and provides human-readable and JSON output.

#### Scenario: Observer records query tree
- **WHEN** a `PageElement` with an observer executes `query_xpath("//tr", "rows")` and then a child executes `query_xpath(".//td", "cells")`
- **THEN** the observer SHALL record a tree: `//tr` with child `.//td`
- **AND** match counts and sample content SHALL be captured at each level

#### Scenario: Observer deduplicates repeated queries
- **WHEN** the same selector is called multiple times on sibling elements (e.g., extracting a column from each row)
- **THEN** the observer SHALL aggregate into a single query entry
- **AND** match counts SHALL be summed

#### Scenario: Observer provides output formats
- **WHEN** `observer.simple_tree()` is called
- **THEN** a human-readable indented tree of selectors with match counts SHALL be returned
- **WHEN** `observer.json()` is called
- **THEN** a JSON-serializable list of query dictionaries SHALL be returned

#### Scenario: CheckedHtmlElement backward compatibility
- **WHEN** `lxml_tree: CheckedHtmlElement` is used (not `page: PageElement`)
- **THEN** the existing `XPathObserver` context variable pattern SHALL continue to work unchanged

### Requirement: HTMLStructuralAssumptionException Carries Selector Context

`HTMLStructuralAssumptionException` SHALL carry the failing selector, selector type, and query kind when raised from `PageElement` query methods. This enables the Playwright driver's autowait mechanism to determine what to wait for.

#### Scenario: Exception from element query
- **WHEN** `query_xpath` or `query_css` raises `HTMLStructuralAssumptionException`
- **THEN** the exception SHALL carry the failing `selector` string
- **AND** the exception SHALL carry the `selector_type` (`"xpath"` or `"css"`)
- **AND** the exception SHALL carry `is_element_query = True`

#### Scenario: Exception from string query
- **WHEN** `query_xpath_strings` raises `HTMLStructuralAssumptionException`
- **THEN** the exception SHALL carry `is_element_query = False`
- **AND** the autowait mechanism SHALL skip this exception

### Requirement: SelectorObserver Absolute Selector Composition

The `SelectorObserver` SHALL provide a method to compose an absolute selector from a query's parent chain. This is used by the Playwright driver's autowait mechanism.

#### Scenario: Compose absolute selector from relative query
- **WHEN** `observer.compose_absolute_selector(query)` is called
- **AND** the query has a parent query in the observer tree
- **THEN** the observer SHALL walk the parent chain to the root
- **AND** the observer SHALL concatenate selectors, stripping relative prefixes (`.` or `./`)
- **AND** the result SHALL be a single absolute selector string

#### Scenario: Query is already absolute
- **WHEN** `observer.compose_absolute_selector(query)` is called
- **AND** the query has no parent (it is a root-level query)
- **THEN** the observer SHALL return the query's selector unchanged

#### Scenario: Mixed selector types in parent chain
- **WHEN** the parent chain contains mixed selector types (XPath parent, CSS child or vice versa)
- **THEN** `compose_absolute_selector` SHALL return `None`
- **AND** the driver SHALL skip autowait for this failure

### Requirement: Playwright Compatibility Check for Selectors

The system SHALL provide a `can_playwright_wait(selector, selector_type)` function that determines whether a selector can be used with Playwright's `page.wait_for_selector()`.

#### Scenario: Element-targeting XPath is compatible
- **WHEN** an XPath selector targets elements (e.g., `//div[@class='content']`, `//table//tr`)
- **THEN** `can_playwright_wait` SHALL return `True`

#### Scenario: Non-element XPath is incompatible
- **WHEN** an XPath selector ends in `/text()` or `/@attribute_name`
- **THEN** `can_playwright_wait` SHALL return `False`

#### Scenario: EXSLT functions are incompatible
- **WHEN** an XPath selector uses EXSLT namespace prefixes (`re:`, `str:`, `math:`, `set:`, `dyn:`)
- **THEN** `can_playwright_wait` SHALL return `False`

#### Scenario: CSS selectors are compatible
- **WHEN** the selector type is `"css"`
- **THEN** `can_playwright_wait` SHALL return `True`
