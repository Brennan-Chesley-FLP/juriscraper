## REMOVED Requirements

### Requirement: SpeculativeRequest for Pagination Probing

**Reason**: Replaced by `@speculate` decorator pattern. Speculative requests are now NavigatingRequests with `is_speculative=True`.

**Migration**:
1. Replace `@step(speculative=True)` with `@speculate` decorator on a new function
2. Move URL generation logic into the `@speculate` function
3. Remove bidirectional generator pattern (no more `should_continue = yield`)
4. The continuation method remains unchanged

## ADDED Requirements

### Requirement: Speculative Request Identification

The system SHALL identify speculative requests via an `is_speculative` boolean field and a `speculation_id` tuple on `BaseRequest`.

#### Scenario: Speculative flag on request
- **WHEN** a driver calls a `@speculate` function
- **THEN** the returned request SHALL have `is_speculative=True`
- **AND** the request SHALL have a `speculation_id` tuple of `(function_name, integer_id)`
- **AND** these fields SHALL be preserved through URL resolution and enqueuing

#### Scenario: Non-speculative requests default
- **WHEN** a request is created without explicit `is_speculative` flag
- **THEN** `is_speculative` SHALL default to `False`
- **AND** `speculation_id` SHALL default to `None`

#### Scenario: Speculation ID structure
- **WHEN** a speculative request is created
- **THEN** `speculation_id` SHALL be a tuple of `(str, int)`
- **AND** the first element SHALL be the name of the `@speculate` function
- **AND** the second element SHALL be the integer ID passed to the function

### Requirement: Speculative Method on Request Types

The system SHALL provide a `speculative()` method for creating speculative copies of requests.

#### Scenario: NavigatingRequest.speculative() method
- **WHEN** `speculative(func_name: str, id: int)` is called on a `NavigatingRequest`
- **THEN** a shallow copy of the request SHALL be returned
- **AND** the copy SHALL have `is_speculative=True`
- **AND** the copy SHALL have `speculation_id=(func_name, id)`

#### Scenario: BaseRequest.speculative() raises NotImplementedError
- **WHEN** `speculative()` is called on a `NonNavigatingRequest` or `ArchiveRequest`
- **THEN** a `NotImplementedError` SHALL be raised
- **AND** the error message SHALL explain that only `NavigatingRequest` can be speculative

### Requirement: Speculate Decorator for Request Factories

The system SHALL provide a `@speculate` decorator for marking functions that generate speculative requests from sequential IDs.

#### Scenario: Basic speculate function
- **WHEN** a method is decorated with `@speculate`
- **THEN** the method SHALL accept a single integer parameter
- **AND** return a single `NavigatingRequest` object
- **AND** the decorator SHALL call `request.speculative(func_name, id)` on the returned request
- **AND** the returned request SHALL have `is_speculative=True`
- **AND** the returned request SHALL have `speculation_id=(func_name, id)`

#### Scenario: Speculate metadata attachment
- **WHEN** `@speculate(observation_date=date, highest_observed=int, largest_observed_gap=int)` is applied
- **THEN** `SpeculateMetadata` SHALL be attached to the function
- **AND** drivers MAY read this metadata for queue seeding decisions

#### Scenario: Speculate metadata defaults
- **WHEN** `@speculate()` is applied without arguments
- **THEN** `observation_date` SHALL default to `None`
- **AND** `highest_observed` SHALL default to `1`
- **AND** `largest_observed_gap` SHALL default to `10`

### Requirement: Speculate Function Discovery

The system SHALL discover `@speculate` functions on scrapers via introspection.

#### Scenario: Discovery via metadata
- **WHEN** a driver inspects a scraper instance
- **THEN** it SHALL find all methods with `SpeculateMetadata` attached
- **AND** distinguish them from `@step` methods which have `StepMetadata`

#### Scenario: Speculate functions not in step list
- **WHEN** a method is decorated with `@speculate`
- **THEN** it SHALL NOT appear in the list of step functions
- **AND** it SHALL NOT be callable as a continuation

### Requirement: Driver Speculation Seeding

The system SHALL have drivers seed their queues by calling `@speculate` functions during initialization.

#### Scenario: Seeding from params configuration
- **WHEN** a driver starts and `params.speculative.{func_name}.definite_range` is set
- **THEN** the driver SHALL call the speculate function for each ID in the range
- **AND** enqueue all returned requests with `is_speculative=True`

#### Scenario: Seeding defaults from metadata
- **WHEN** `definite_range` is not explicitly configured
- **THEN** `definite_range` SHALL default to `(1, highest_observed)` from decorator metadata
- **AND** `plus` SHALL default to `largest_observed_gap` from decorator metadata

### Requirement: Driver Speculation Tracking and Extension

The system SHALL have drivers track speculation success and dynamically extend the queue.

#### Scenario: Track highest successful ID
- **WHEN** a speculative request receives a 2xx response
- **THEN** the driver SHALL update `highest_successful_id` for that @speculate function
- **AND** reset `consecutive_failures` to zero

#### Scenario: Track consecutive failures
- **WHEN** a speculative request receives a non-2xx response
- **OR** the response matches `scraper.fails_successfully()`
- **AND** the speculative ID is greater than `highest_successful_id`
- **THEN** the driver SHALL increment `consecutive_failures` for that @speculate function

#### Scenario: Dynamic queue extension
- **WHEN** `highest_successful_id` approaches `current_ceiling` (highest seeded ID)
- **AND** `consecutive_failures` is less than `plus`
- **THEN** the driver SHALL call the @speculate function for additional IDs
- **AND** enqueue the returned requests

#### Scenario: Stop speculation on consecutive failures
- **WHEN** `consecutive_failures` reaches or exceeds `plus`
- **THEN** the driver SHALL stop generating new speculative requests for that function
- **AND** existing queued speculative requests MAY still be processed

### Requirement: Speculative Params Interface

The system SHALL expose speculative configuration via the params interface with `definite_range` and `plus` properties.

#### Scenario: Configure definite range
- **WHEN** `params.speculative.{func_name}.definite_range = (100, 500)` is set
- **THEN** the driver SHALL fetch IDs 100 through 500 inclusively
- **AND** these requests SHALL be treated as speculative

#### Scenario: Configure plus for probing
- **WHEN** `params.speculative.{func_name}.plus = 20` is set
- **THEN** the driver SHALL probe up to 20 consecutive failures beyond the highest successful ID
- **AND** probing SHALL stop after 20 consecutive non-2xx responses

#### Scenario: Disable speculation
- **WHEN** `params.speculative.{func_name} = None` is set
- **THEN** the driver SHALL NOT seed any requests from that speculate function

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

### Requirement: Step Metadata

The system SHALL allow metadata configuration via decorator arguments.

#### Scenario: Priority override
- **WHEN** `@step(priority=3)` is applied
- **THEN** requests yielded from this method SHALL use priority 3 instead of default

#### Scenario: Encoding specification
- **WHEN** `@step(encoding="latin-1")` is applied
- **THEN** response content SHALL be decoded using latin-1 encoding

#### Scenario: Step is not speculative
- **WHEN** `@step` is applied to a method
- **THEN** the method SHALL NOT support bidirectional generator patterns
- **AND** yields SHALL be standard Generator[ScraperYield, None, None]
