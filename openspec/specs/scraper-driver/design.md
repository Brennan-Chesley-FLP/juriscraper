# Scraper Driver Design

## Overview

The scraper driver framework separates parsing logic (Scrapers) from I/O orchestration (Drivers), enabling robust, testable, and extensible web scraping.

## Directory Structure

```
juriscraper/scraper_driver/
├── __init__.py
├── data_types.py                 # Core data model definitions
├── common/
│   ├── checked_html.py          # HTML parsing with XPath validation
│   ├── data_models.py           # Pydantic data models
│   ├── decorators.py            # @step decorator
│   ├── deferred_validation.py   # DeferredValidation wrapper
│   ├── exceptions.py            # Exception hierarchy
│   ├── models/base.py           # ScrapedData base model
│   ├── request_manager.py       # HTTP request handling
│   ├── searchable.py            # Searchable field metadata
│   └── xpath_observer.py        # XPath observation tools
├── driver/
│   ├── async_driver.py          # Async multi-worker driver
│   ├── callbacks.py             # Callback factory helpers
│   ├── sync_driver.py           # Synchronous driver
│   ├── playwright_driver.py     # Browser-based driver
│   └── dev_driver/              # Development web UI
```

## Core Design Patterns

### Generator Protocol

Scrapers are Python generators that yield typed values:

```python
ScraperYield = ParsedData[T] | NavigatingRequest | NonNavigatingRequest | ArchiveRequest | SpeculativeRequest | None
```

The driver consumes the generator, handling each yield type:
- `ParsedData` → invoke `on_data` callback
- `*Request` → enqueue for processing
- `None` → continue to next yield

This enables exhaustive pattern matching and clear separation of concerns.

### Request Chain with Deep Copy Semantics

Each request carries its full context:

```python
@dataclass(frozen=True)
class BaseRequest:
    request: HTTPRequestParams
    continuation: str | Callable
    current_location: str = ""
    previous_requests: list[BaseRequest] = field(default_factory=list)
    accumulated_data: dict[str, Any] = field(default_factory=dict)
    aux_data: dict[str, Any] = field(default_factory=dict)
    permanent: dict[str, Any] = field(default_factory=dict)
    priority: int = 9
    deduplication_key: str | None | SkipDeduplicationCheck = None
```

Critical: `accumulated_data`, `aux_data`, and `permanent` are deep copied in `__post_init__`. This prevents mutation bugs when yielding multiple sibling requests from the same method.

### URL Resolution

Relative URLs are resolved against `current_location`:
- `NavigatingRequest` updates `current_location` to the response URL
- `NonNavigatingRequest` and `ArchiveRequest` preserve `current_location`

```python
# NavigatingRequest: location updates
/listing.html → NavigatingRequest("/detail/1") → current_location="/detail/1"

# NonNavigatingRequest: location preserved
/listing.html → NonNavigatingRequest("/api/data") → current_location="/listing.html"
```

### Continuation Resolution

Continuations are specified as strings for serialization compatibility:

```python
NavigatingRequest(
    request=HTTPRequestParams(url="/search"),
    continuation="parse_search_results",  # Method name string
    current_location=response.url
)
```

The driver resolves strings to methods via `scraper.get_continuation(name)`.

## Driver Architecture

### Priority Queue

Uses `heapq` for memory-efficient priority ordering:

```python
# Queue entry format: (priority, counter, item)
heapq.heappush(queue, (request.priority, next(counter), request))
```

- Priority 1 (high): ArchiveRequest - process terminal requests first
- Priority 9 (default): NavigatingRequest
- Counter ensures FIFO for equal priorities

### Request Processing Loop

```
Entry Point
    ↓
get_entry() → yields NavigatingRequest(s)
    ↓
Driver enqueues request(s)
    ↓
Main loop:
    1. Pop from priority queue
    2. Check deduplication
    3. Execute HTTP request
    4. Call continuation method
    5. Process yields (ParsedData, *Request, None)
    6. Repeat until queue empty
    ↓
on_run_complete callback
```

### Speculation Pattern

For probing pages that may not exist:

```python
# In scraper method:
speculative_id = 1
while True:
    result = yield SpeculativeRequest(
        request=HTTPRequestParams(url=f"/page/{speculative_id}"),
        continuation="parse_page",
        speculative_id=speculative_id
    )
    if not result:  # False means stop
        break
    speculative_id += 1
```

Driver flow:
1. Generator yields SpeculativeRequest
2. Driver parks generator, stores context
3. Driver enqueues request
4. Response triggers `on_speculation_response` callback
5. Callback returns True/False
6. Driver resumes generator with result

## Checked HTML Element

Wrapper around lxml elements with validation:

```python
class CheckedHtmlElement:
    def checked_xpath(self, selector: str, min_count: int = 1, max_count: int = 1) -> list[CheckedHtmlElement]:
        """Return elements matching selector, raising if count out of range"""

    def checked_css(self, selector: str, min_count: int = 1, max_count: int = 1) -> list[CheckedHtmlElement]:
        """CSS selector version of checked_xpath"""
```

Raises `HTMLStructuralAssumptionException` with:
- URL being scraped
- Selector used
- Expected count range
- Actual count found

## Deferred Validation

Two-phase validation pattern:

```python
# Phase 1: Create wrapper without validation (in scraper)
deferred = MyModel.raw(request_url=url, field1=value1, field2=value2)

# Phase 2: Validate when ready (in driver)
try:
    validated = deferred.confirm()
    on_data(validated)
except ValidationError:
    on_invalid_data(deferred)
```

Benefits:
- Validation errors include source URL
- All data collected before validation
- Invalid data can be inspected/logged

## Searchable Fields

Annotations for filterable parameters:

```python
from typing import Annotated
from juriscraper.scraper_driver.common.searchable import DateRange, SetFilter, UniqueMatch

class CaseData(ScrapedData):
    date_filed: Annotated[date, DateRange()]
    case_type: Annotated[str, SetFilter()]
    docket_number: Annotated[str, UniqueMatch()]

# Usage
params = MyScraper.params()
params.CaseData.date_filed.gte = date(2024, 1, 1)
params.CaseData.case_type.values = {"civil", "criminal"}
```

## Driver Implementations

### SyncDriver

Single-threaded synchronous execution:
- Uses `heapq` for priority queue
- `threading.Event` for stop signal
- Blocking HTTP via `httpx.Client`

### AsyncDriver

Multi-worker concurrent execution:
- Uses `asyncio.PriorityQueue`
- `num_workers` controls concurrency
- `asyncio.Event` for stop signal
- Non-blocking HTTP via `httpx.AsyncClient`

### PlaywrightDriver

Browser-based execution:
- New tab per NavigatingRequest
- JavaScript fully executed
- POST via injected form submission
- Tab lifecycle managed via reference counting

## Callback Helpers

Factory functions in `driver/callbacks.py`:

```python
# Save to JSONL file
on_data = save_to_jsonl_file(open("results.jsonl", "w"))

# Chain multiple callbacks
on_data = combine_callbacks(
    print_data(prefix="Found: "),
    save_to_jsonl_path("results.jsonl"),
    count_data(counter)
)
```

## Step Decorator

Reduces boilerplate via argument inspection:

```python
@step(priority=5, encoding="utf-8")
def parse_listing(self, lxml_tree: CheckedHtmlElement, accumulated_data: dict) -> Generator[ScraperYield, None, None]:
    # lxml_tree and accumulated_data auto-injected based on parameter names
    for item in lxml_tree.checked_xpath("//div[@class='item']"):
        yield ParsedData({"name": item.text_content()})
```

Available injections:
- `response` → Response object
- `request` → BaseRequest
- `previous_request` → Parent request
- `json_content` → Parsed JSON
- `lxml_tree` → CheckedHtmlElement
- `text` → Response text
- `accumulated_data` → Accumulated data dict
- `aux_data` → Auxiliary data dict
- `local_filepath` → File path (ArchiveResponse)
- `speculative_id` → Starting speculation ID

## Development Driver

Web UI for debugging scrapers:
- Step-by-step execution
- WARC recording/playback controls
- Rate limiter adjustment
- Speculation management
- SQL persistence of run state

Location: `driver/dev_driver/`

## Key Files

| File | Purpose |
|------|---------|
| `data_types.py` | All request/response types |
| `common/checked_html.py` | CheckedHtmlElement wrapper |
| `common/exceptions.py` | Exception hierarchy |
| `common/request_manager.py` | HTTP request handling |
| `driver/sync_driver.py` | Synchronous driver |
| `driver/async_driver.py` | Async concurrent driver |
| `driver/playwright_driver.py` | Browser-based driver |

## Performance Considerations

1. **Priority queue**: Terminal requests (ArchiveRequest) processed first to emit data and free memory
2. **Deep copy**: Prevents mutation bugs but has overhead; frozen dataclasses minimize copies
3. **Deduplication**: SHA256 hashing per request; use `SkipDeduplicationCheck` when not needed
4. **Rate limiting**: Thread-safe with Lock; adaptive backoff on 429
5. **Worker count**: AsyncDriver concurrency tunable via `num_workers`

## Testing Strategy

1. **Unit tests**: Test scrapers in isolation with mock Responses
2. **WARC tests**: Record once, replay for fast deterministic tests
3. **Integration tests**: Full driver runs against WARC cache
4. **Dev driver**: Interactive debugging with web UI
