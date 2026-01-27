# Design: LocalDevDriverDebugger

## Context

The LocalDevDriver currently handles both execution (running scrapers) and inspection (debugging runs). The WebUI accesses run data through a mix of:
1. Direct SQL queries via SQLManager
2. Driver methods (when loaded)
3. Read-only connections (when unloaded)

This creates complexity in the WebUI routes and makes it difficult to build additional tooling (CLI, tests) without coupling to the full driver.

**Stakeholders:**
- Developers debugging scraper runs
- WebUI serving inspection endpoints
- CLI users wanting quick run analysis
- Tests needing to verify run state

## Goals / Non-Goals

### Goals
- Provide a single, well-documented API for all run inspection/manipulation
- Support both read-only inspection and write operations (requeue, cancel)
- Enable CLI tooling without WebUI dependency
- Reduce code duplication between WebUI routes and potential CLI
- Make it easy to reason about what operations are safe on a cold database

### Non-Goals
- Replacing LocalDevDriver for running scrapers
- Changing the SQL schema
- Adding new inspection capabilities not already in WebUI
- Real-time streaming (WebSocket) - that remains in WebUI

## Decisions

### Decision 1: LDDD wraps SQLManager, not extends it

**What:** LDDD will compose SQLManager internally rather than subclassing.

**Why:**
- SQLManager is low-level with raw SQL; LDDD provides higher-level operations
- Keeps SQLManager focused on raw queries, LDDD on semantic operations
- Allows LDDD to add caching, validation, connection management independently

**Alternatives considered:**
- Subclass SQLManager: Rejected - mixes abstraction levels
- Replace SQLManager: Rejected - driver still needs low-level access

### Decision 2: Read-only mode as constructor parameter

**What:** `LocalDevDriverDebugger(db_path, read_only=True)` controls write capability.

**Why:**
- Explicit about intent
- Enforced at connection level (SQLite read-only mode)
- CLI can default to read-only for safety
- WebUI can use read-write for manipulation endpoints

**Alternatives considered:**
- Separate classes (Inspector vs Manipulator): Rejected - too much duplication
- Method-level permissions: Rejected - harder to audit

### Decision 3: Async-first API matching driver

**What:** LDDD uses async methods matching the driver's async nature.

**Why:**
- Consistent with existing codebase
- WebUI (FastAPI) is async
- SQLite operations can benefit from async I/O
- CLI can use `asyncio.run()` wrapper

### Decision 4: Reuse existing record types

**What:** Use existing `RequestRecord`, `ResponseRecord`, `ResultRecord`, `Page[T]` types.

**Why:**
- No duplication of data structures
- WebUI already uses these
- Pydantic models provide serialization

### Decision 5: CLI uses Click framework

**What:** CLI tool built with Click, matching existing tooling patterns.

**Why:**
- Click is already used in the codebase
- Good async support via `asyncclick` or decorators
- Rich help text and subcommand support

### Decision 6: WebUI routes delegate to LDDD

**What:** Refactor WebUI routes to use LDDD instead of direct SQL queries.

**Why:**
- Single source of truth for inspection logic
- Easier testing of routes (mock LDDD)
- Routes become thin HTTP wrappers

**Migration approach:**
- Add LDDD as new code
- Update routes one at a time
- Remove direct SQL from routes
- Keep SQLManager for driver's internal use

## Risks / Trade-offs

### Risk: Performance regression in WebUI
- **Mitigation:** LDDD can cache expensive aggregations
- **Mitigation:** Benchmark before/after for critical paths

### Trade-off: Added abstraction layer
- **Cost:** More indirection, slightly larger codebase
- **Benefit:** Clearer separation, testability, reusability

## Migration Plan

### Phase 1: Add LDDD (non-breaking)
1. Create `debugger.py` with LDDD class
2. Implement all inspection methods
3. Add comprehensive tests

### Phase 2: Add CLI
1. Create `cli.py` with Click commands
2. Map CLI commands to LDDD methods
3. Add shell completion support

### Phase 3: Migrate WebUI routes
1. Update routes one file at a time
2. Inject LDDD via dependency injection
3. Remove direct SQL from route handlers
4. Verify all endpoints unchanged via integration tests

### Rollback
- Each phase is independently deployable
- WebUI can fall back to direct SQL if LDDD issues found
- CLI is additive, can be removed without impact

## Open Questions

1. **Should LDDD support loading multiple runs simultaneously?**
   - Current design: one LDDD instance per database
   - Alternative: LDDD manages multiple connections
   - Recommendation: Keep simple, create multiple instances

2. **How should CLI handle authentication for manipulation?**
   - Options: require flag, prompt, env var
   - Recommendation: Default read-only, require `--write` flag for mutations

3. **Should diagnosis re-run require the scraper class?**
   - Current WebUI approach: loads scraper dynamically
   - LDDD approach: prefer to discover from run metadata, if not found, check optional parameter, else raise error
   - Recommendation: discover from run_metadata. If that fails, check optional parameter, if that fails, raise error.
