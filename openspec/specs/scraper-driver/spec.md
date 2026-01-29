# Scraper Driver Specification

## Purpose

The scraper driver framework provides a generator-based architecture for building web scrapers with proper error handling, validation, concurrency, and extensibility. The framework separates parsing logic (Scrapers) from I/O orchestration (Drivers), enabling the same scraper code to run with different driver implementations.

## Requirements

<!-- Request Types -->

### Requirement: ParsedData Type Wrapper

The system SHALL provide a `ParsedData[T]` wrapper type that enables exhaustive pattern matching on scraper yields.

#### Scenario: Scraper yields parsed data
- **WHEN** a scraper yields `ParsedData(data)`
- **THEN** the driver SHALL invoke the `on_data` callback with the unwrapped data
- **AND** the data SHALL be distinguishable from request yields via pattern matching

### Requirement: NavigatingRequest for Multi-Page Scraping

The system SHALL provide a `NavigatingRequest` type that fetches a URL and updates the navigation context.

#### Scenario: Scraper yields NavigatingRequest
- **WHEN** a scraper yields `NavigatingRequest(request, continuation, current_location)`
- **THEN** the driver SHALL enqueue the request
- **AND** after fetching, `current_location` SHALL be updated to the response URL
- **AND** the continuation method SHALL be called with the Response

#### Scenario: Relative URL resolution
- **WHEN** a NavigatingRequest contains a relative URL
- **THEN** the URL SHALL be resolved against the current `current_location` using `urllib.parse.urljoin`

### Requirement: NonNavigatingRequest for API Calls

The system SHALL provide a `NonNavigatingRequest` type that fetches supplementary data without changing navigation location.

#### Scenario: Scraper yields NonNavigatingRequest
- **WHEN** a scraper yields `NonNavigatingRequest(request, continuation)`
- **THEN** the driver SHALL fetch the URL
- **AND** `current_location` SHALL remain unchanged (preserved from the parent request)
- **AND** relative URLs in subsequent yields SHALL resolve against the original location

### Requirement: ArchiveRequest for File Downloads

The system SHALL provide an `ArchiveRequest` type for downloading and archiving binary files.

#### Scenario: Scraper yields ArchiveRequest
- **WHEN** a scraper yields `ArchiveRequest(request, continuation, expected_type)`
- **THEN** the driver SHALL download the file
- **AND** invoke the `on_archive` callback with the content, URL, expected type, and storage directory
- **AND** pass an `ArchiveResponse` with `file_url` pointing to the saved location
- **AND** `current_location` SHALL remain unchanged

#### Scenario: ArchiveRequest default priority
- **WHEN** an ArchiveRequest is created without explicit priority
- **THEN** the priority SHALL default to 1 (higher than NavigatingRequest's default of 9)

### Requirement: SpeculativeRequest for Pagination Probing

The system SHALL provide a `SpeculativeRequest` type for probing pages that may or may not exist.

#### Scenario: Scraper yields SpeculativeRequest
- **WHEN** a scraper generator yields `SpeculativeRequest(request, continuation, speculative_id)`
- **THEN** the driver SHALL park the generator
- **AND** enqueue the request
- **AND** invoke `on_speculation_response` callback with the response
- **AND** resume the generator with True/False based on callback result

#### Scenario: Speculative pagination loop
- **WHEN** a generator yields SpeculativeRequest with `speculative_id=1`
- **AND** receives True back from the driver
- **THEN** the generator MAY yield another SpeculativeRequest with `speculative_id=2`
- **AND** this pattern SHALL continue until the generator receives False or stops yielding

<!-- Request Data Flow -->

### Requirement: Accumulated Data Across Request Chain

The system SHALL provide an `accumulated_data` field on requests for collecting data across multiple pages.

#### Scenario: Data accumulation across requests
- **WHEN** a continuation method yields a new request with `accumulated_data`
- **THEN** the child request SHALL inherit a deep copy of the parent's accumulated_data
- **AND** modifications to the child's accumulated_data SHALL NOT affect the parent or sibling requests

#### Scenario: Deep copy semantics prevent mutation bugs
- **WHEN** a method yields two sibling requests from the same parent
- **THEN** each sibling SHALL have independent copies of accumulated_data
- **AND** mutations in one branch SHALL NOT affect the other branch

### Requirement: Auxiliary Data for Navigation Metadata

The system SHALL provide an `aux_data` field for navigation metadata separate from case data.

#### Scenario: Session token in aux_data
- **WHEN** an authentication step stores a token in `aux_data["session_token"]`
- **THEN** subsequent requests SHALL have access to the token via their `aux_data` field
- **AND** the token SHALL NOT appear in `accumulated_data` or final output

#### Scenario: Aux data deep copy
- **WHEN** child requests are created
- **THEN** `aux_data` SHALL be deep copied with the same semantics as `accumulated_data`

### Requirement: Permanent Data for Persistent Headers

The system SHALL provide a `permanent` field for headers and cookies that persist across the entire request chain.

#### Scenario: Bearer token authentication
- **WHEN** a login step sets `permanent["Authorization"] = "Bearer <token>"`
- **THEN** all subsequent requests in the chain SHALL include the Authorization header
- **AND** the header SHALL be merged into HTTPRequestParams automatically

#### Scenario: Permanent data inheritance
- **WHEN** a child request is created
- **THEN** it SHALL inherit the parent's permanent data
- **AND** the driver SHALL merge permanent headers into outgoing requests

### Requirement: Request Ancestry Tracking

The system SHALL track the ancestry of each request via a `previous_requests` list.

#### Scenario: Request chain reconstruction
- **WHEN** a request is processed
- **THEN** `request.previous_requests` SHALL contain the complete chain of parent requests
- **AND** this chain SHALL enable debugging, error reporting, and state reconstruction

<!-- Driver Orchestration -->

### Requirement: Priority Queue Processing

The system SHALL process requests using a priority queue with lower values indicating higher priority.

#### Scenario: Archive requests processed first
- **WHEN** both ArchiveRequest (priority 1) and NavigatingRequest (priority 9) are queued
- **THEN** the ArchiveRequest SHALL be processed first
- **AND** this SHALL reduce peak memory usage by emitting data early

#### Scenario: FIFO ordering for equal priorities
- **WHEN** multiple requests have the same priority
- **THEN** they SHALL be processed in FIFO order using a counter for deterministic tie-breaking

### Requirement: Request Deduplication

The system SHALL prevent fetching the same resource multiple times using deduplication.

#### Scenario: Automatic deduplication key generation
- **WHEN** a request does not specify a custom `deduplication_key`
- **THEN** the key SHALL be generated as SHA256 hash of URL, sorted query params, and request data

#### Scenario: Duplicate request skipped
- **WHEN** a request's deduplication_key matches a previously processed request
- **THEN** the driver SHALL skip the request
- **AND** the `duplicate_check` callback SHALL be consulted if provided

#### Scenario: Skip deduplication check
- **WHEN** a request sets `deduplication_key = SkipDeduplicationCheck`
- **THEN** deduplication SHALL be bypassed for that specific request

### Requirement: Continuation Method Resolution

The system SHALL resolve continuation method names to callable methods on the scraper.

#### Scenario: String continuation resolution
- **WHEN** a request specifies `continuation="parse_results"`
- **THEN** the driver SHALL look up `scraper.parse_results` method
- **AND** call it with the Response object

#### Scenario: Callable continuation
- **WHEN** a request specifies a callable as continuation
- **THEN** the driver SHALL resolve it to the method's name for serialization compatibility

<!-- Error Handling -->

### Requirement: Structural Assumption Errors

The system SHALL fail fast with clear errors when HTML structure does not match expectations.

#### Scenario: XPath returns unexpected element count
- **WHEN** `CheckedHtmlElement.checked_xpath(selector, min_count=1, max_count=1)` finds 0 or 2+ elements
- **THEN** an `HTMLStructuralAssumptionException` SHALL be raised
- **AND** the exception SHALL include URL, selector, expected count, actual count

#### Scenario: Structural error callback
- **WHEN** a structural error occurs
- **THEN** the `on_structural_error` callback SHALL be invoked
- **AND** callback return value (bool) SHALL determine whether scraping continues

### Requirement: Data Validation Errors

The system SHALL validate scraped data against Pydantic schemas with deferred validation.

#### Scenario: Deferred validation pattern
- **WHEN** a scraper calls `MyModel.raw(request_url=url, **data)`
- **THEN** a `DeferredValidation` wrapper SHALL be created without validation
- **AND** validation SHALL occur when `confirm()` is called by the driver

#### Scenario: Validation failure handling
- **WHEN** `DeferredValidation.confirm()` raises a Pydantic validation error
- **THEN** a `DataFormatAssumptionException` SHALL be raised
- **AND** the `on_invalid_data` callback SHALL be invoked with the DeferredValidation object

### Requirement: Transient Exception Handling

The system SHALL distinguish temporary failures (retryable) from permanent errors.

#### Scenario: Timeout classified as transient
- **WHEN** an HTTP request times out
- **THEN** a `RequestTimeoutException` (subclass of TransientException) SHALL be raised
- **AND** the `on_transient_exception` callback SHALL be invoked

#### Scenario: Rate limit (429) detected as transient
- **WHEN** an HTTP response has status 429
- **THEN** a `RateLimitedException` SHALL be raised
- **AND** the request MAY be retried based on callback decision

#### Scenario: Server error (5xx) handling
- **WHEN** an HTTP response has status 5xx
- **THEN** an `HTMLResponseAssumptionException` SHALL be raised
- **AND** it SHALL be classified as transient for retry purposes

<!-- Callbacks and Lifecycle -->

### Requirement: Data Event Callbacks

The system SHALL invoke the `on_data` callback when ParsedData is yielded.

#### Scenario: Streaming results to file
- **WHEN** `on_data` callback is configured to write JSONL
- **THEN** each ParsedData SHALL be written immediately
- **AND** memory usage SHALL remain constant regardless of total results

### Requirement: Archive Event Callback

The system SHALL invoke `on_archive` callback for file downloads.

#### Scenario: Custom storage backend
- **WHEN** `on_archive` callback writes to S3
- **THEN** file content, URL, expected_type, and storage_dir SHALL be passed
- **AND** the callback SHALL return the storage URL for the ArchiveResponse

### Requirement: Lifecycle Hooks

The system SHALL provide lifecycle callbacks for run start and completion.

#### Scenario: Run completion guaranteed
- **WHEN** a scraper run finishes (success or failure)
- **THEN** `on_run_complete` SHALL always be called via finally block
- **AND** status SHALL be "completed" or "error"
- **AND** exception SHALL be passed if failure occurred

#### Scenario: Run start callback
- **WHEN** a scraper run begins
- **THEN** `on_run_start` SHALL be called with the scraper ID
- **AND** this SHALL occur before any requests are processed

<!-- Driver Implementations -->

### Requirement: Synchronous Driver

The system SHALL provide a `SyncDriver` for single-threaded synchronous execution.

#### Scenario: Basic synchronous execution
- **WHEN** `SyncDriver.run()` is called
- **THEN** requests SHALL be processed sequentially from the priority queue
- **AND** generators SHALL be consumed until exhausted

### Requirement: Asynchronous Driver

The system SHALL provide an `AsyncDriver` for concurrent execution with configurable workers.

#### Scenario: Concurrent worker execution
- **WHEN** `AsyncDriver` is configured with `num_workers=5`
- **THEN** up to 5 requests SHALL be processed concurrently
- **AND** `asyncio.PriorityQueue` SHALL be used for async-safe coordination

#### Scenario: Graceful shutdown
- **WHEN** `stop_event.set()` is called
- **THEN** workers SHALL complete current requests
- **AND** exit gracefully without processing queued requests

### Requirement: Playwright Driver

The system SHALL provide a `PlaywrightDriver` for browser-based JavaScript rendering.

#### Scenario: JavaScript-rendered pages
- **WHEN** a NavigatingRequest is processed by PlaywrightDriver
- **THEN** a new browser tab SHALL be opened
- **AND** JavaScript SHALL be fully executed before content extraction
- **AND** the page SHALL be fully rendered

#### Scenario: POST requests via form injection
- **WHEN** a POST request is made via PlaywrightDriver
- **THEN** a hidden form SHALL be injected into the page
- **AND** the form SHALL be submitted for proper browser semantics

#### Scenario: Driver-agnostic scrapers
- **WHEN** a scraper is written following the framework conventions
- **THEN** it SHALL work with SyncDriver, AsyncDriver, or PlaywrightDriver
- **AND** no scraper code changes SHALL be required

<!-- Step Decorator -->

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

#### Scenario: Available injection names
- **THEN** the following parameter names SHALL be available for injection:
  - `response`: Response object
  - `request`: BaseRequest object
  - `previous_request`: Parent request from chain
  - `json_content`: Parsed JSON dict
  - `lxml_tree`: CheckedHtmlElement (parsed HTML)
  - `text`: Response text
  - `accumulated_data`: Accumulated data dict
  - `aux_data`: Auxiliary data dict
  - `local_filepath`: Local file path (for ArchiveResponse)
  - `speculative_id`: Starting ID for speculative steps

### Requirement: Step Metadata

The system SHALL allow metadata configuration via decorator arguments.

#### Scenario: Priority override
- **WHEN** `@step(priority=3)` is applied
- **THEN** requests yielded from this method SHALL use priority 3 instead of default

#### Scenario: Encoding specification
- **WHEN** `@step(encoding="latin-1")` is applied
- **THEN** response content SHALL be decoded using latin-1 encoding

<!-- Searchable Fields -->

### Requirement: Filterable Scraper Parameters

The system SHALL provide annotations for searchable/filterable fields on data models.

#### Scenario: Date range filter
- **WHEN** a field is annotated with `Annotated[date, DateRange()]`
- **THEN** the scraper params interface SHALL expose `gte` and `lte` properties for filtering

#### Scenario: Set filter
- **WHEN** a field is annotated with `Annotated[str, SetFilter()]`
- **THEN** the scraper params interface SHALL expose a `values` set for filtering

#### Scenario: Unique match filter
- **WHEN** a field is annotated with `Annotated[str, UniqueMatch()]`
- **THEN** the scraper params interface SHALL expose a `value` property for exact matching

#### Scenario: Params interface usage
- **WHEN** `params = MyScraper.params()` is called
- **THEN** filters SHALL be configurable via `params.ModelName.field_name.gte = value`
- **AND** setting `params.ModelName = None` SHALL disable that data type entirely

<!-- Scraper Metadata -->

### Requirement: Standard Scraper ClassVars

The system SHALL require scrapers to define standard metadata as ClassVars.

#### Scenario: Required metadata fields
- **WHEN** a scraper class is defined
- **THEN** the following ClassVars SHALL be defined:
  - `court_ids`: Set of linked court identifiers
  - `court_url`: Primary court system URL
  - `data_types`: Set of data types produced
  - `status`: Lifecycle status (IN_DEVELOPMENT, ACTIVE, RETIRED)
  - `version`: Scraper version string

#### Scenario: Optional metadata fields
- **WHEN** a scraper requires additional configuration
- **THEN** the following optional ClassVars MAY be defined:
  - `oldest_record`: Earliest available data date
  - `requires_auth`: Whether authentication is required
  - `msec_per_request_rate_limit`: Rate limiting configuration
  - `last_verified`: Last verification date

<!-- Exception Hierarchy -->

### Requirement: Structured Exception Types

The system SHALL provide a hierarchy of exception types for error classification.

#### Scenario: Exception inheritance
- **THEN** the exception hierarchy SHALL be:
  - `ScraperAssumptionException` (base)
    - `HTMLStructuralAssumptionException`: XPath count mismatch
    - `DataFormatAssumptionException`: Validation failure
    - `RequestFailedHalt`: Stop scraping immediately
    - `RequestFailedSkip`: Skip to next request
    - `TransientException` (retryable base)
      - `RequestTimeoutException`: Timeout
      - `RateLimitedException`: 429 response
      - `ServiceUnavailableException`: 503 response
    - `HTMLResponseAssumptionException`: 5xx response
