## Context

The scraper framework currently uses a custom parameter system built on field-level annotations (`DateRange`, `SetFilter`, `UniqueMatch`) in Pydantic data models, with a proxy-based API (`ScraperParams`, `ModelProxy`, `FieldProxy`) for configuring filters. Scrapers override `get_entry()` to yield initial `NavigatingRequest`s, reading their configured parameters from `self._params`.

This refactor replaces that entire system with `@entry`-decorated methods whose parameters ARE the scraper's input contract, using standard Pydantic models for validation and schema generation.

## Goals / Non-Goals

**Goals:**
- Each scraper declares entry points as `@entry(ReturnType)` decorated methods
- Entry function parameters are Pydantic BaseModel subclasses or primitives (`str`, `int`, `date` -- no tuples)
- `BaseScraper.schema()` generates a JSON spec for all entry points using Pydantic's native `model_json_schema()`
- `BaseScraper.initial_seed(params)` dispatches a JSON parameter list to the correct entry functions; errors on empty list
- Parameters are fully JSON-serializable for storage, APIs, and queuing
- `@speculate` functions are subsumed as special `@entry` functions
- `BaseScraper[T]` generic parameter remains as a union of all return types
- Remove the old parameter system entirely (no dual support)

**Non-Goals:**
- Changing how `@step` decorators work (separate concern)
- Changing the request/response types (`NavigatingRequest`, `ParsedData`, etc.)
- Changing driver internals beyond the entry point invocation
- Adding runtime parameter validation beyond what Pydantic provides

## Decisions

### Decision 1: @entry decorator API

The `@entry` decorator takes the return data type as its argument:

```python
@entry(Docket)
def search_by_number(self, docket_number: str) -> Generator[NavigatingRequest, None, None]:
    ...

@entry(Docket)
def search_by_date(self, date_range: DateRange) -> Generator[NavigatingRequest, None, None]:
    ...

@entry(Opinion)
def browse_opinions(self, filters: OpinionFilters) -> Generator[NavigatingRequest, None, None]:
    ...
```

Parameters can be:
- **Pydantic BaseModel subclasses** (e.g. `DateRange`, `OpinionFilters`) -- serialized as dicts
- **Primitive types**: `str`, `int`, `date` -- serialized as their JSON equivalents
- **No tuples**

The decorator:
1. Attaches `EntryMetadata` to the function (return type, parameter types, function name)
2. Does NOT modify the function's behavior at call time (unlike `@step` which injects arguments)
3. Is discoverable via `BaseScraper.list_entries()` similar to `list_steps()`

**Rationale:** Mirrors the `@step`/`@speculate` pattern of attaching metadata without altering runtime behavior. Allowing primitives keeps simple entry points clean (`docket_number: str` rather than wrapping in a model).

### Decision 2: Parameter serialization format

Parameters are serialized as a JSON list of single-key dicts mapping entry function name to kwargs:

```json
[
  {"search_by_number": {"docket_number": "A10"}},
  {"search_by_date": {"date_range": {"start": "2020-01-01", "end": "2020-12-31"}}},
  {"search_by_number": {"docket_number": "A20"}}
]
```

Each item in the list represents one invocation. The same entry function can appear multiple times with different parameters. Primitive parameters serialize as their JSON type directly; BaseModel parameters serialize as dicts.

**Rationale:** This format is self-describing (function name is the key), supports repeated invocations of the same entry, and maps directly to Pydantic's validation for deserialization. Primitives stay flat for simplicity.

### Decision 3: Empty parameters error

`initial_seed([])` and `initial_seed(None)` SHALL raise a `ValueError`. Callers must always specify at least one parameter invocation.

**Rationale:** Explicit is better than implicit. Scrapers that previously had parameterless `get_entry()` methods will need at least one `@entry` function with parameters that the caller provides. This forces callers to be intentional about what they're searching for.

### Decision 4: initial_seed() implementation

```python
def initial_seed(self, params: list[dict[str, dict[str, Any]]]) -> Generator[NavigatingRequest, None, None]:
    """Dispatch parameter list to entry functions and yield combined requests."""
    if not params:
        raise ValueError("initial_seed() requires at least one parameter invocation")

    entry_map = {info.func_name: (method, info) for method, info in self._list_entry_info()}

    for invocation in params:
        for func_name, kwargs_dict in invocation.items():
            if func_name not in entry_map:
                available = list(entry_map.keys())
                raise ValueError(f"Unknown entry '{func_name}'. Available: {available}")
            method, meta = entry_map[func_name]
            validated_kwargs = meta.validate_params(kwargs_dict)
            yield from method(**validated_kwargs)
```

### Decision 5: @speculate as special @entry

The `@speculate` decorator is replaced by `@entry(ReturnType, speculative=True)`. Speculative entries:

```python
@entry(Docket, speculative=True, highest_observed=105336, largest_observed_gap=20)
def fetch_docket(self, crn: int) -> NavigatingRequest:
    """Generate a speculative request for a docket by CRN."""
    return NavigatingRequest(
        request=HTTPRequestParams(method=HttpMethod.GET, url=f"/docket/{crn}"),
        continuation=self.parse_docket_page,
    )
```

- Speculative entries have `EntryMetadata.speculative = True` plus the observation metadata
- `initial_seed()` can dispatch to them like any other entry
- The driver still handles the speculative probing/range logic, but the function is discovered through the unified `@entry` system
- `SpeculateMetadata` fields (`observation_date`, `highest_observed`, `largest_observed_gap`) are folded into `EntryMetadata`

**Rationale:** Unifying under `@entry` means a single discovery mechanism, single schema format, and single dispatch path. The speculative behavior is an attribute of the entry, not a separate system.

### Decision 6: BaseScraper generic parameter stays as union

```python
class ConnecticutScraper(BaseScraper[Docket | Opinion]):
    @entry(Docket)
    def search_dockets_by_number(self, docket_number: str) -> Generator[NavigatingRequest, None, None]:
        ...

    @entry(Opinion)
    def browse_opinions(self, court_id: str) -> Generator[NavigatingRequest, None, None]:
        ...
```

The generic parameter declares the full set of return types the scraper can produce. Each `@entry` narrows which type a specific entry path returns. Data validation continues to use the generic parameter.

**Rationale:** The generic parameter serves type checking and data validation. Removing it would break existing validation infrastructure for no clear benefit.

### Decision 7: Schema generation uses Pydantic native format

`BaseScraper.schema()` returns a dict using Pydantic's `model_json_schema()` for BaseModel parameters and standard JSON Schema types for primitives:

```python
@classmethod
def schema(cls) -> dict[str, Any]:
    """Generate schema for all entry points."""
    ...
```

Output format:
```json
{
  "scraper": "ConnecticutScraper",
  "entries": {
    "search_by_number": {
      "returns": "Docket",
      "speculative": false,
      "parameters": {
        "type": "object",
        "properties": {
          "docket_number": {"type": "string"}
        },
        "required": ["docket_number"]
      }
    },
    "search_by_date": {
      "returns": "Docket",
      "speculative": false,
      "parameters": {
        "type": "object",
        "properties": {
          "date_range": {"$ref": "#/$defs/DateRange"}
        },
        "required": ["date_range"]
      }
    },
    "fetch_docket": {
      "returns": "Docket",
      "speculative": true,
      "highest_observed": 105336,
      "largest_observed_gap": 20,
      "parameters": {
        "type": "object",
        "properties": {
          "crn": {"type": "integer"}
        },
        "required": ["crn"]
      }
    }
  },
  "$defs": {
    "DateRange": {
      "type": "object",
      "properties": {
        "start": {"type": "string", "format": "date"},
        "end": {"type": "string", "format": "date"}
      },
      "required": ["start", "end"]
    }
  }
}
```

Uses Pydantic's `$defs` convention (not `components/schemas`) for referenced models. Primitive parameters emit inline JSON Schema types.

### Decision 8: EntryMetadata dataclass

```python
@dataclass(frozen=True)
class EntryMetadata:
    return_type: type                                # e.g. Docket
    param_types: dict[str, type]                     # param_name -> type (BaseModel or primitive)
    func_name: str                                   # Name of the decorated function
    speculative: bool = False                        # Whether this is a speculative entry
    observation_date: date | None = None             # For speculative: last observed date
    highest_observed: int = 1                        # For speculative: highest known ID
    largest_observed_gap: int = 10                   # For speculative: largest gap in sequence
```

Attached to the function as `func._entry_metadata`, discoverable via `get_entry_metadata(func)` / `is_entry(func)` helpers, paralleling `get_step_metadata()` / `is_step()`.

### Decision 9: Web UI and scraper_registry adaptation

- The web UI generates forms from the Pydantic-native schema returned by `schema()`
- `scraper_registry.build_params_from_web_data()` becomes `build_seed_from_web_data()` producing the JSON parameter list
- The `params_json` column in the DevDriver SQLite schema stores the new JSON format
- This follows naturally from the parameter system change

### Decision 10: Migration strategy -- Connecticut + Alabama first

First PR migrates:
1. Core infrastructure (@entry decorator, initial_seed, schema, removal of old param system)
2. Test scrapers (bug_court.py etc.)
3. Connecticut scraper
4. Alabama scraper
5. Driver updates

Follow-up PRs migrate remaining scrapers on a per-scraper basis.

**Rationale:** Connecticut and Alabama are representative scrapers that exercise different patterns. Migrating them alongside the infrastructure validates the approach. Per-scraper follow-up PRs keep the diff manageable.

## Risks / Trade-offs

- **Large migration surface**: Every scraper eventually needs updating. Mitigated by: incremental per-scraper PRs after the first PR lands with infrastructure + 2 scrapers.
- **Loss of field-level filtering semantics**: The old system had `DateRange(gte/lte)`, `SetFilter(values)`, `UniqueMatch(value)` with specific filter semantics tied to data model fields. The new system pushes this into entry function parameter models, which is more explicit but requires each scraper to define its own parameter models.
- **Mixed parameter types**: Allowing both primitives and BaseModels in entry signatures means `validate_params()` must handle both. The serialization format has primitives as flat values and models as dicts, which is slightly heterogeneous but natural.
- **Speculate unification**: Folding `@speculate` into `@entry` means the driver's speculative probing logic needs to check `EntryMetadata.speculative` rather than looking for a separate decorator. This is a minor change but touches driver code.
