# Change: Add `doctor` Subcommand to LDDD CLI

## Why

The LDDD (LocalDevDriver Debugger) CLI needs a health check command that validates database integrity, identifies anomalies, and provides actionable diagnostics. Currently, debugging database issues requires manual SQL queries and cross-referencing multiple commands. A dedicated `doctor` subcommand will streamline troubleshooting workflows.

## What Changes

- Add `ldd-debug doctor <db-path>` command that displays a health report
- Health report includes:
  - Integrity check results (orphaned requests/responses)
  - Error counts summary
  - Pending request count or "run wrapped" indicator
  - Ghost request counts by step (requests with no children or data)
- Add subcommands for listing specific anomalies:
  - `ldd-debug doctor orphans <db-path>` - List requests missing responses or responses missing requests
  - `ldd-debug doctor pending <db-path>` - List pending requests
  - `ldd-debug doctor ghosts <db-path>` - List ghost requests by step

## Impact

- Affected specs: `specs/scraper-driver/spec.md`
- Affected code:
  - `juriscraper/scraper_driver/driver/dev_driver/cli.py`
  - `juriscraper/scraper_driver/driver/dev_driver/debugger.py`
  - `juriscraper/scraper_driver/driver/dev_driver/sql_queries.py` (new queries)