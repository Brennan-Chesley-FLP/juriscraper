# Change: Add dry-run comparison for continuation changes

## Why

When modifying scraper continuation methods, developers need to understand the downstream impact of their changes before running a full scrape. Currently, there's no way to compare what a modified continuation would produce against what was previously captured, making it difficult to validate changes or debug regressions.

## What Changes

- Add a new `compare` command to the `ldd-debug` CLI
- Implement a `DryRunDriver` that captures requests/results without executing network calls
- Add comparison logic with fuzzy matching for data changes
- Support full transitive child comparison (all downstream requests)

## Impact

- Affected specs: `debugger-cli` (new capability)
- Affected code:
  - `juriscraper/scraper_driver/driver/dev_driver/cli.py` - new CLI command
  - `juriscraper/scraper_driver/driver/dev_driver/debugger.py` - new comparison methods
  - New module for dry-run driver and comparison logic