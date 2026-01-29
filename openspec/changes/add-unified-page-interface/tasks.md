## 1. PageElement Protocol & Value Objects

- [x] 1.1 Define `PageElement` protocol in new file `juriscraper/scraper_driver/common/page_element.py`
- [x] 1.2 Define `Form`, `FormField`, `Link` value objects in same file (Form stores its origin selector)
- [x] 1.3 Define `ViaLink` and `ViaFormSubmit` frozen dataclasses
- [x] 1.4 Write unit tests for protocol conformance checks

## 2. SelectorObserver

- [x] 2.1 Create `SelectorObserver` class with same recording logic as `XPathObserver` (query trees, deduplication, sample capture, `simple_tree()`, `json()`)
- [x] 2.2 `SelectorObserver` is a plain object — no context manager, no context variable
- [x] 2.3 Write unit tests for `SelectorObserver` recording, deduplication, and output formats

## 3. Via on BaseRequest

- [x] 3.1 Add `via: ViaLink | ViaFormSubmit | None = None` field to `BaseRequest` in `data_types.py`
- [x] 3.2 Ensure `via` is carried through `resolve_from()` on `NavigatingRequest` and `NonNavigatingRequest`
- [x] 3.3 Write unit tests for `via` propagation through request chain

## 4. LxmlPageElement Implementation

- [x] 4.1 Implement `LxmlPageElement(checked_element, url, observer=None)` wrapping `CheckedHtmlElement`, delegating `query_xpath` → `checked_xpath`, `query_css` → `checked_css`
- [x] 4.2 All query methods record to `self._observer` when present
- [x] 4.3 Child `LxmlPageElement`s returned from queries inherit the parent's observer
- [x] 4.4 Implement `find_form(selector, description)` — parse matched `<form>` element into `Form` value object with action URL resolution, method detection, field introspection, and stored origin selector
- [x] 4.5 Implement `Form.submit(data, submit_selector)` — auto-include hidden fields, return `NavigatingRequest` with `via=ViaFormSubmit`
- [x] 4.6 Implement `find_links(selector, description)` — parse matched `<a>` elements into `Link` value objects with URL resolution
- [x] 4.7 Implement `links()` — return all `<a>` elements with `href` as `Link` value objects
- [x] 4.8 Implement `Link.follow()` — return `NavigatingRequest` with `via=ViaLink`
- [x] 4.9 Write unit tests for LxmlPageElement (extraction, form submit, link follow, nested queries, observer recording)

## 5. Selector Utilities for Driver Integration

- [x] 5.1 Enrich `HTMLStructuralAssumptionException` to carry `selector`, `selector_type`, and `is_element_query` when raised from `PageElement` query methods
- [x] 5.2 Implement `SelectorObserver.compose_absolute_selector(query)` — walk parent chain, concatenate selectors stripping relative prefixes (`.` / `./`), return `None` for mixed selector types
- [x] 5.3 Implement `can_playwright_wait(selector, selector_type)` — return `False` for non-element XPath (`/text()`, `/@attr`), EXSLT extensions (`re:`, `str:`, `math:`, `set:`, `dyn:`), XPath variables (`$`); return `True` for CSS; return `True` for element-targeting XPath
- [x] 5.4 Write unit tests for `compose_absolute_selector` (relative→absolute, already absolute, mixed types → None)
- [x] 5.5 Write unit tests for `can_playwright_wait` (element XPath, text() XPath, @attr XPath, EXSLT, CSS)