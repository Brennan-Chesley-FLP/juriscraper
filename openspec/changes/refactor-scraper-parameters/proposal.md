# Change: Refactor scraper parameter system to use @entry decorators with Pydantic models

## Why

The current parameter system (`ScraperParams`, `ModelProxy`, `FieldProxy`, searchable field markers) is tightly coupled to the data model's field annotations and requires callers to understand a custom proxy API. Parameters are configured imperatively via attribute assignment rather than declared as structured, serializable inputs. This makes it difficult to:

- Programmatically discover what parameters a scraper accepts
- Serialize/deserialize parameter sets for storage, APIs, or queuing
- Generate machine-readable API documentation
- Compose multiple parameter sets into a single scraper invocation

The new approach replaces all of this with `@entry`-decorated functions that declare their parameters as Pydantic models or primitives, enabling JSON Schema generation, JSON serialization, and a clean `initial_seed()` dispatch mechanism.

## What Changes

- **BREAKING**: Remove the existing parameter system entirely:
  - `ScraperParams`, `ModelProxy`, `FieldProxy`, `SpeculateFunctionProxy`, `SpeculativeFunctionsProxy`
  - `DateRange`, `SetFilter`, `UniqueMatch`, `SpeculativeID` marker classes
  - `DateRangeFilter`, `SetFilterValue`, `UniqueMatchValue`, `SpeculativeIDValue` filter value holders
  - `build_params_for_scraper()` function
  - `BaseScraper.params()` classmethod
  - `BaseScraper.__init__(params: ScraperParams)` parameter
  - `BaseScraper.get_params()` method

- **BREAKING**: Remove `BaseScraper.get_entry()` abstract method

- **BREAKING**: Remove `@speculate` decorator and related infrastructure (`SpeculateMetadata`, `list_speculators()`, speculate proxy classes)

- **ADD**: `@entry(ReturnType)` decorator for scraper methods that serve as entry points
  - Attaches metadata (return type, parameter schema) to the decorated function
  - Parameters can be Pydantic BaseModel subclasses or primitives (`str`, `int`, `date` -- no tuples)
  - Supports `speculative=True` kwarg to replace `@speculate`
  - Functions return `Generator[NavigatingRequest, ...]`

- **ADD**: `BaseScraper.schema()` classmethod returning a Pydantic-native JSON Schema specification describing all entry points and their parameter types

- **ADD**: `BaseScraper.initial_seed(params: list[dict])` method that takes a JSON-serializable list of parameter invocations and dispatches them to the appropriate `@entry` functions, returning a combined generator of `NavigatingRequest`s. Raises `ValueError` on empty parameter list.

- **ADD**: `BaseScraper.list_entries()` classmethod for introspecting available entry points and their metadata

- **MODIFY**: All drivers (SyncDriver, AsyncDriver, DevDriver) to call `initial_seed()` instead of `get_entry()`

- **MODIFY**: Driver speculative probing to use `EntryMetadata.speculative` instead of `@speculate` decorator discovery

- **MODIFY**: Existing scrapers to replace `get_entry()` with `@entry`-decorated methods (Connecticut + Alabama in first PR, remaining scrapers in follow-up PRs)

## Impact

- Affected specs: `scraper-driver`
- Affected code:
  - `juriscraper/scraper_driver/data_types.py` (BaseScraper)
  - `juriscraper/scraper_driver/common/searchable.py` (entire file replaced or gutted)
  - `juriscraper/scraper_driver/common/decorators.py` (add @entry, remove @speculate)
  - `juriscraper/scraper_driver/driver/sync_driver.py`
  - `juriscraper/scraper_driver/driver/async_driver.py`
  - `juriscraper/scraper_driver/driver/dev_driver/dev_driver.py`
  - `juriscraper/scraper_driver/driver/dev_driver/web/scraper_registry.py`
  - Connecticut and Alabama scrapers under `juriscraper/sd/` (first PR)
  - All test scrapers under `tests/scraper_driver/`
  - Remaining scrapers (follow-up PRs)
