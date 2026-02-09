## ADDED Requirements

### Requirement: Entry Decorator for Scraper Entry Points

The system SHALL provide an `@entry(ReturnType)` decorator for declaring scraper entry points with typed parameters.

#### Scenario: Decorator attaches metadata
- **WHEN** a scraper method is decorated with `@entry(Docket)`
- **THEN** the function SHALL have `EntryMetadata` attached (accessible via `get_entry_metadata()`)
- **AND** the metadata SHALL include the return type (`Docket`), parameter types, and function name

#### Scenario: Multiple entries on one scraper
- **WHEN** a scraper has methods decorated with `@entry(Docket)` and `@entry(Opinion)`
- **THEN** both SHALL be discoverable via `BaseScraper.list_entries()`
- **AND** each SHALL independently declare its return type and parameters

#### Scenario: Entry function with BaseModel parameter
- **WHEN** an entry function is defined as `def search_by_date(self, date_range: DateRange)` where `DateRange` is a `BaseModel`
- **THEN** the `EntryMetadata.param_types` SHALL map `"date_range"` to the `DateRange` type
- **AND** this mapping SHALL be used for schema generation and parameter validation

#### Scenario: Entry function with primitive parameters
- **WHEN** an entry function is defined as `def search_by_number(self, docket_number: str)`
- **THEN** the `EntryMetadata.param_types` SHALL map `"docket_number"` to `str`
- **AND** primitive types `str`, `int`, and `date` SHALL be supported
- **AND** tuple types SHALL NOT be supported

#### Scenario: Entry function yields NavigatingRequests
- **WHEN** an entry function is called with validated parameters
- **THEN** it SHALL yield `NavigatingRequest` instances
- **AND** each request SHALL specify a continuation for the next step in the scraping pipeline

#### Scenario: Speculative entry declaration
- **WHEN** a method is decorated with `@entry(Docket, speculative=True, highest_observed=105336, largest_observed_gap=20)`
- **THEN** `EntryMetadata.speculative` SHALL be `True`
- **AND** the speculative observation metadata SHALL be stored in the `EntryMetadata`
- **AND** the function SHALL be discoverable alongside non-speculative entries via `list_entries()`

### Requirement: Entry Point Discovery

The system SHALL provide a `list_entries()` classmethod on `BaseScraper` for introspecting all `@entry`-decorated methods.

#### Scenario: List entries returns metadata for all entry points
- **WHEN** `MyScraper.list_entries()` is called
- **THEN** it SHALL return a list of `EntryInfo` objects
- **AND** each object SHALL include the function name, return type, parameter schema, and speculative flag

#### Scenario: Entry discovery uses class introspection
- **WHEN** `list_entries()` is called on a scraper class
- **THEN** it SHALL inspect all methods on the class (including inherited) for `@entry` metadata
- **AND** the discovery mechanism SHALL parallel `list_steps()` for consistency

#### Scenario: Speculative entries are included in discovery
- **WHEN** `list_entries()` is called on a scraper with both regular and speculative entries
- **THEN** both types SHALL appear in the returned list
- **AND** speculative entries SHALL be distinguishable via their `speculative` flag

### Requirement: Parameter Schema Generation

The system SHALL provide a `schema()` classmethod on `BaseScraper` that returns a Pydantic-native JSON Schema specification of all entry points and their parameter types.

#### Scenario: Schema includes all entry points
- **WHEN** `MyScraper.schema()` is called
- **THEN** the returned dict SHALL include an `"entries"` mapping from function name to parameter schema
- **AND** each entry SHALL declare its return type, speculative flag, and parameter JSON Schema

#### Scenario: Schema uses Pydantic model_json_schema for BaseModel parameters
- **WHEN** entry parameters reference Pydantic BaseModel subclasses
- **THEN** the schema SHALL use Pydantic's `model_json_schema()` output format
- **AND** referenced models SHALL appear in the `"$defs"` section with `$ref` pointers

#### Scenario: Schema uses inline JSON Schema for primitive parameters
- **WHEN** entry parameters are primitive types (`str`, `int`, `date`)
- **THEN** the schema SHALL emit inline JSON Schema types (e.g. `{"type": "string"}`, `{"type": "integer"}`, `{"type": "string", "format": "date"}`)

#### Scenario: Schema includes speculative metadata
- **WHEN** a speculative entry exists
- **THEN** its schema entry SHALL include `"speculative": true`, `"highest_observed"`, and `"largest_observed_gap"` fields

#### Scenario: Schema is JSON-serializable
- **WHEN** `schema()` is called
- **THEN** the returned dict SHALL be directly serializable to JSON via `json.dumps()`

### Requirement: Initial Seed Dispatch

The system SHALL provide an `initial_seed(params)` method on `BaseScraper` that takes a JSON-serializable parameter list and dispatches invocations to the appropriate `@entry` functions.

#### Scenario: Dispatch single invocation
- **WHEN** `initial_seed([{"search_by_number": {"docket_number": "A10"}}])` is called
- **THEN** the scraper's `search_by_number` method SHALL be called with `docket_number="A10"`
- **AND** the yielded `NavigatingRequest`s SHALL be yielded from `initial_seed()`

#### Scenario: Dispatch multiple invocations
- **WHEN** `initial_seed()` receives a list with 3 invocation dicts
- **THEN** all 3 SHALL be dispatched in order
- **AND** the resulting `NavigatingRequest`s SHALL be yielded as a single combined generator

#### Scenario: Same entry called multiple times with different parameters
- **WHEN** the parameter list contains `[{"search_by_number": {"docket_number": "A10"}}, {"search_by_number": {"docket_number": "A20"}}]`
- **THEN** `search_by_number` SHALL be called twice with different validated parameters
- **AND** both invocations' requests SHALL appear in the combined output

#### Scenario: Dispatch to speculative entry
- **WHEN** the parameter list includes `{"fetch_docket": {"crn": 42}}`
- **AND** `fetch_docket` is decorated with `@entry(Docket, speculative=True)`
- **THEN** the speculative entry SHALL be called with `crn=42`
- **AND** the yielded request SHALL be marked as speculative by the entry function

#### Scenario: Empty parameter list raises error
- **WHEN** `initial_seed([])` or `initial_seed(None)` is called
- **THEN** a `ValueError` SHALL be raised
- **AND** the error message SHALL indicate that at least one parameter invocation is required

#### Scenario: Parameter validation on dispatch
- **WHEN** `initial_seed()` receives parameters that don't match the entry function's expected types
- **THEN** a Pydantic `ValidationError` SHALL be raised
- **AND** the error SHALL identify which entry function and which parameter failed validation

#### Scenario: Unknown entry function name
- **WHEN** the parameter list references a function name not decorated with `@entry`
- **THEN** a `ValueError` SHALL be raised
- **AND** the error message SHALL list available entry function names

### Requirement: Driver Entry Point Integration

The system's drivers SHALL use `initial_seed()` as the entry point for starting scraper runs.

#### Scenario: SyncDriver uses initial_seed
- **WHEN** `SyncDriver.run()` begins execution
- **THEN** it SHALL call `scraper.initial_seed(params)` to obtain initial requests
- **AND** the yielded requests SHALL be enqueued into the priority queue

#### Scenario: AsyncDriver uses initial_seed
- **WHEN** `AsyncDriver.run()` begins execution
- **THEN** it SHALL call `scraper.initial_seed(params)` to obtain initial requests
- **AND** the yielded requests SHALL be placed into the async priority queue

#### Scenario: DevDriver uses initial_seed
- **WHEN** the DevDriver starts a scraper run
- **THEN** it SHALL call `scraper.initial_seed(params)` to obtain initial requests
- **AND** the parameter list SHALL be stored in the run's metadata for reproducibility

#### Scenario: Driver speculative probing uses EntryMetadata
- **WHEN** a driver processes requests from a speculative entry
- **THEN** it SHALL check `EntryMetadata.speculative` to determine speculative behavior
- **AND** the observation metadata (`highest_observed`, `largest_observed_gap`) SHALL be read from `EntryMetadata`

## REMOVED Requirements

### Requirement: Searchable Field Annotations

**Reason**: Replaced by typed parameters on `@entry` functions. Field-level searchable annotations (`DateRange`, `SetFilter`, `UniqueMatch`, `SpeculativeID` markers) on data models are no longer needed because parameter schemas are defined explicitly as function arguments.

**Migration**: Scrapers that used `Annotated[date, DateRange()]` field markers to advertise searchable fields should instead define Pydantic parameter models or primitive parameters for their `@entry` functions.

### Requirement: ScraperParams Proxy System

**Reason**: Replaced by `initial_seed()` with JSON-serializable parameter lists. The proxy-based API (`ScraperParams`, `ModelProxy`, `FieldProxy`) for imperatively configuring filters is no longer needed.

**Migration**: Callers that built `ScraperParams` via `MyScraper.params()` and set filters via attribute assignment should instead construct a JSON parameter list and pass it to `initial_seed()`. Use `MyScraper.schema()` to discover available parameters.

### Requirement: SpeculativeRequest for Pagination Probing

**Reason**: The `@speculate` decorator and its associated `SpeculateMetadata`, `SpeculateFunctionProxy`, and `SpeculativeFunctionsProxy` are replaced by `@entry(ReturnType, speculative=True)`. Speculative functions are now unified with regular entry points.

**Migration**: Functions decorated with `@speculate(highest_observed=N, largest_observed_gap=M)` should be re-decorated as `@entry(ReturnType, speculative=True, highest_observed=N, largest_observed_gap=M)`. The function body remains unchanged. Driver logic that checked for `@speculate` metadata should check `EntryMetadata.speculative` instead.
