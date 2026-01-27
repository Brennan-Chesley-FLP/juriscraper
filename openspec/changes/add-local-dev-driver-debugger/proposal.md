# Change: Add LocalDevDriverDebugger for Run Inspection and Manipulation

## Why

The LocalDevDriver currently mixes two concerns: running scrapers and debugging/inspecting runs. This makes it difficult to:
- Inspect a completed run without loading the full driver machinery
- Build tooling (CLI, WebUI) that doesn't need runtime capabilities
- Test debugging features in isolation
- Reason about which operations are safe on a "cold" database vs a running driver

Factoring out debugging/inspection into a dedicated `LocalDevDriverDebugger` (LDDD) class enables cleaner separation of concerns, lighter-weight tooling, and a clear API contract for inspection vs execution.

## What Changes

- **NEW**: `LocalDevDriverDebugger` class for read-only inspection and safe manipulation of run databases
- **NEW**: CLI tool (`ldd-debug`) for command-line debugging of runs
- **REFACTOR**: WebUI routes to use LDDD instead of direct SQL queries

## Impact

- Affected specs: NEW `local-dev-driver-debugger` capability
- Affected code:
  - `juriscraper/scraper_driver/driver/dev_driver/debugger.py` (new)
  - `juriscraper/scraper_driver/driver/dev_driver/cli.py` (new)
  - `juriscraper/scraper_driver/web/routes/*.py` (refactor to use LDDD)
