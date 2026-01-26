# Design: Refactored Speculation Architecture

## Context

The current speculation system uses a bidirectional generator pattern where scrapers yield `SpeculativeRequest` objects and receive True/False back via `generator.send()`. This requires:
- Manual generator management with parking/resuming
- `SpeculationContext` to track parked generators
- `ResumeStep` queue items to coordinate resumption
- Complex state management in drivers
- External callbacks (`on_speculation_response`) for flow control

The new design inverts control: scrapers declare *which functions* generate speculative requests, and drivers decide *when and how* to call them based purely on configuration.

## Goals

1. Simplify scraper authoring by eliminating bidirectional generators
2. Decouple scrapers from speculation flow control
3. Enable drivers to seed queues proactively based on metadata
4. Support historical observation data for intelligent range selection
5. Remove external callbacks - pure configuration-driven speculation
6. Maintain backward compatibility for request processing (speculative requests still flow through same pipeline)

## Non-Goals

1. Changing how HTTP responses are processed (same continuation mechanism)
2. Altering the deduplication system
3. Modifying the interceptor chain
4. Cross-run learning (each run is isolated)

## Decisions

### Decision 1: @speculate Decorator

Functions decorated with `@speculate` take an integer parameter and return a single `NavigatingRequest`. The decorator attaches metadata describing historical observations. The function may include accumulated_data or aux_data in the returned request.

```python
@speculate(
    observation_date=date(2025, 1, 15),
    highest_observed=89000,
    largest_observed_gap=50
)
def speculate_docket(self, docket_id: int) -> NavigatingRequest:
    return NavigatingRequest(
        request=HTTPRequestParams(url=f"/dockets/{docket_id}"),
        continuation="parse_docket",
        accumulated_data={"docket_id": docket_id}
    )
```

**Rationale**: This pattern is simpler than generators, self-documenting, and testable in isolation.

**Alternative considered**: Keep generators but add metadata via decorator arguments. Rejected because generators add complexity and tight coupling.

### Decision 2: Speculative Request Identification via Boolean Field

Instead of a separate `SpeculativeRequest` type, add `is_speculative: bool = False` to `BaseRequest`. The request returned by a `@speculate` function gets this flag set automatically.

**Rationale**:
- Simplifies type hierarchy (fewer types to dispatch on)
- The request still flows through NavigatingRequest processing
- Drivers can identify speculative requests for tracking

### Decision 3: Params Interface Changes

The `.params().speculative.{function_name}` interface changes to expose:
- `definite_range: tuple[int, int]` - defaults to `(1, highest_observed)`
- `plus: int` - defaults to `largest_observed_gap`

The driver uses these to determine: "fetch IDs 1 through N (definite_range), then speculatively probe up to `plus` consecutive failures beyond the highest successful ID."

**Rationale**: This gives external control over speculation behavior without requiring scraper code changes.

### Decision 4: Driver Speculation Seeding and Extension

Drivers become responsible for:
1. Discovering `@speculate` functions on scrapers
2. Reading params configuration
3. Calling the function for each ID in `definite_range` during initialization
4. Enqueuing returned requests with `is_speculative=True`
5. Tracking `highest_successful_id` per @speculate function as responses complete
6. Dynamically extending the queue when speculation succeeds near the ceiling
7. Stopping when `plus` consecutive failures occur beyond `highest_successful_id`

**No external callbacks** - speculation policy is entirely configuration-driven.

**Rationale**: This inverts control - drivers know about speculation policy, scrapers just define the URL pattern. Removing callbacks simplifies the driver interface and makes behavior predictable.

### Decision 5: Distinguishing @step and @speculate

- `@step`: Decorates continuation methods that process HTTP responses. Returns a generator.
- `@speculate`: Decorates request-factory methods that take an integer ID. Returns a single request.

These are orthogonal concerns:
- A `@speculate` function returns a request whose `continuation` points to a `@step` method
- A `@step` method can yield more requests, but never calls `@speculate` functions directly

A scraper may have multiple `@speculate` functions for different ID spaces (e.g., `speculate_docket()` and `speculate_document()`).

**Detection**: Introspection checks for `StepMetadata` vs `SpeculateMetadata` attached to methods.

### Decision 6: LocalDevDriver Speculation Tracking

LocalDevDriver tracks speculation state within a single run (runs are isolated, no cross-run learning):

- Track `highest_successful_id` per @speculate function
- Track `current_ceiling` (highest ID currently seeded)
- Track `consecutive_failures` beyond `highest_successful_id`
- When a speculative request succeeds and `highest_successful_id` approaches `current_ceiling`, generate and enqueue more requests
- Stop extending when `consecutive_failures >= plus`

Remove entirely:
- Generator parking/tracking
- `SpeculationContext` and `ResumeStep` handling

## Risks / Trade-offs

| Risk | Mitigation |
|------|------------|
| Breaking change for all speculative scrapers | Provide migration guide; changes are mechanical |
| Loss of fine-grained mid-speculation control | Configuration via `definite_range` and `plus` covers common cases |
| Cannot abort speculation early based on response content | Could add `fails_successfully()` support for speculative requests |

## Migration Plan

1. Add new `@speculate` decorator alongside existing `@step(speculative=True)`
2. Add `is_speculative` field to `BaseRequest`
3. Update drivers to support both patterns temporarily
4. Migrate scrapers one-by-one from old to new pattern
5. Remove deprecated `SpeculativeRequest` type and `@step(speculative=True)`
6. Remove `on_speculation_response` callback from driver interfaces
7. Archive change

### Decision 7: fails_successfully() Applies to Speculation

When a speculative request's response matches `scraper.fails_successfully()`, it counts as a failure for `consecutive_failures` tracking. This allows scrapers to signal "this ID doesn't exist" via response content analysis (e.g., soft 404 pages that return HTTP 200).

## Open Questions

1. **Should @speculate support async functions?** Initial implementation assumes sync; async could be added later.
2. **How should params override interact with decorator defaults?** Proposed: params always wins if explicitly set.
