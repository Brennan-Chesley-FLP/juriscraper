# Opinion Scraper Migration to scraper_driver Architecture

This document outlines the strategy for migrating existing Opinion scrapers to the new `scraper_driver` architecture using `BaseScraper`.

## Overview

The migration involves:
1. Rewriting each Opinion scraper as a `BaseScraper` subclass
2. Validating the new implementation against the original
3. Handling expected differences (more fields, different ordering, additional results)

## Test Rig Design

### Purpose

Create an automated comparison framework that:
- Runs the **original** Opinion scraper for a given time window
- Runs the **new** BaseScraper-derived scraper for the same window
- Compares results and reports differences
- Accounts for expected variations between implementations

### Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Migration Test Rig                        │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  ┌──────────────┐         ┌──────────────┐                  │
│  │   Original   │         │     New      │                  │
│  │   Opinion    │         │  BaseScraper │                  │
│  │   Scraper    │         │   Scraper    │                  │
│  └──────┬───────┘         └──────┬───────┘                  │
│         │                        │                           │
│         ▼                        ▼                           │
│  ┌──────────────┐         ┌──────────────┐                  │
│  │   Results    │         │   Results    │                  │
│  │   (List of   │         │   (List of   │                  │
│  │   Opinions)  │         │   Opinions)  │                  │
│  └──────┬───────┘         └──────┬───────┘                  │
│         │                        │                           │
│         └──────────┬─────────────┘                          │
│                    ▼                                         │
│            ┌──────────────┐                                  │
│            │  Comparator  │                                  │
│            │              │                                  │
│            │ - Normalize  │                                  │
│            │ - Match      │                                  │
│            │ - Diff       │                                  │
│            └──────┬───────┘                                  │
│                   ▼                                          │
│            ┌──────────────┐                                  │
│            │    Report    │                                  │
│            └──────────────┘                                  │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

### Components

#### 1. Test Runner (`migration_test_runner.py`)

```python
class MigrationTestRunner:
    """Orchestrates comparison between original and new scraper implementations."""

    def __init__(
        self,
        original_scraper_class: Type[OpinionSite],
        new_scraper_class: Type[BaseScraper],
        start_date: date,
        end_date: date,
    ):
        self.original = original_scraper_class
        self.new = new_scraper_class
        self.start_date = start_date
        self.end_date = end_date

    async def run_original(self) -> list[dict]:
        """Run the original scraper and collect results."""
        ...

    async def run_new(self) -> list[dict]:
        """Run the new BaseScraper implementation and collect results."""
        ...

    async def compare(self) -> ComparisonReport:
        """Run both scrapers and generate comparison report."""
        original_results = await self.run_original()
        new_results = await self.run_new()
        return ResultComparator.compare(original_results, new_results)
```

#### 2. Result Comparator (`result_comparator.py`)

The comparator must handle:

- **Different field sets**: New scraper may return additional fields
- **Different ordering**: Results may come in different order
- **Additional results**: New scraper may find opinions the original missed
- **Normalization**: Field values may have minor formatting differences

```python
class ResultComparator:
    """Compares results between original and new scraper implementations."""

    # Fields used to match opinions across implementations
    MATCH_KEYS = ["case_name", "docket_number", "date_filed"]

    # Fields that must match exactly
    REQUIRED_FIELDS = ["case_name", "docket_number", "date_filed", "url"]

    # Fields where differences are acceptable
    OPTIONAL_FIELDS = ["judge", "nature_of_suit", "precedential_status"]

    # Fields expected only in new implementation
    NEW_ONLY_FIELDS = ["source_url", "request_id", "scraped_at"]

    @classmethod
    def compare(
        cls,
        original: list[dict],
        new: list[dict],
    ) -> ComparisonReport:
        """Compare two result sets and generate a detailed report."""
        ...
```

#### 3. Matching Strategy

Since results may arrive in different orders, we need a robust matching strategy:

```python
def create_match_key(opinion: dict) -> str:
    """Create a normalized key for matching opinions."""
    components = [
        normalize_case_name(opinion.get("case_name", "")),
        normalize_docket(opinion.get("docket_number", "")),
        opinion.get("date_filed", ""),
    ]
    return "|".join(components)

def normalize_case_name(name: str) -> str:
    """Normalize case name for comparison."""
    # Remove extra whitespace
    # Normalize v. vs vs. variations
    # Handle abbreviations
    ...

def normalize_docket(docket: str) -> str:
    """Normalize docket number for comparison."""
    # Remove spaces, standardize separators
    ...
```

#### 4. Comparison Report

```python
@dataclass
class ComparisonReport:
    """Results of comparing original vs new scraper."""

    # Summary counts
    original_count: int
    new_count: int
    matched_count: int

    # Categorized differences
    missing_in_new: list[dict]      # In original but not new (regressions)
    missing_in_original: list[dict]  # In new but not original (improvements)

    # Field-level differences for matched opinions
    field_differences: list[FieldDiff]

    # New fields present only in new implementation
    new_fields_found: set[str]

    def is_acceptable(self) -> bool:
        """Check if differences are within acceptable bounds."""
        # No regressions (missing_in_new should be empty)
        # Field differences are in optional/new-only categories
        ...

    def to_markdown(self) -> str:
        """Generate human-readable report."""
        ...
```

### Expected Differences

#### Acceptable Differences

1. **Additional fields in new implementation**
   - `source_url`: The URL the opinion was scraped from
   - `request_id`: Internal tracking ID
   - `scraped_at`: Timestamp of scrape
   - Any new fields the court provides that weren't previously captured

2. **Additional opinions in new implementation**
   - New scraper may implement better pagination
   - New scraper may capture opinions the original missed
   - Should be reviewed but not flagged as failures

3. **Minor formatting differences**
   - Whitespace normalization
   - Date format variations (normalized during comparison)
   - Case name punctuation

#### Unacceptable Differences (Regressions)

1. **Missing opinions**: Opinions found by original but not by new
2. **Changed core fields**: Different case_name, docket_number, or date_filed for matched opinions
3. **Missing URLs**: Opinion URL not captured
4. **Broken downloads**: PDF/document URLs that don't work

### CLI Interface

```bash
# Run comparison for a specific court and date range
uv run python -m juriscraper.migration.compare \
    --court nyscef \
    --start-date 2025-01-01 \
    --end-date 2025-01-07 \
    --output report.md

# Run comparison with verbose output
uv run python -m juriscraper.migration.compare \
    --court nyscef \
    --start-date 2025-01-01 \
    --end-date 2025-01-07 \
    --verbose

# Run comparison for all courts with new implementations
uv run python -m juriscraper.migration.compare_all \
    --start-date 2025-01-01 \
    --end-date 2025-01-07
```

### Integration with LocalDevDriver

The test rig can leverage LocalDevDriver for the new scraper:

1. Create a run with the new scraper
2. Execute and wait for completion
3. Extract results from the SQLite database
4. Compare against original scraper output

```python
async def run_new_with_dev_driver(
    scraper_class: Type[BaseScraper],
    start_date: date,
    end_date: date,
) -> list[dict]:
    """Run new scraper using LocalDevDriver infrastructure."""
    run_id = f"migration-test-{scraper_class.__name__}-{uuid4().hex[:8]}"

    async with LocalDevDriver(db_path=f"runs/{run_id}.db") as driver:
        scraper = scraper_class(
            driver=driver,
            start_date=start_date,
            end_date=end_date,
        )
        await driver.run_scraper(scraper)

        # Extract results from driver's database
        return driver.get_all_opinions()
```

## Migration Workflow

### Per-Court Migration Process

1. **Create new scraper class**
   ```python
   class NYSCEFOpinionScraper(BaseScraper):
       """NYSCEF Opinion scraper using new architecture."""
       ...
   ```

2. **Run comparison test**
   ```bash
   uv run python -m juriscraper.migration.compare \
       --court nyscef \
       --start-date 2025-01-01 \
       --end-date 2025-01-07
   ```

3. **Review report**
   - Verify no regressions
   - Document any new fields captured
   - Note any additional opinions found

4. **Iterate if needed**
   - Fix any regressions
   - Re-run comparison until acceptable

5. **Mark migration complete**
   - Update migration status tracking
   - Deprecate original scraper

### Migration Status Tracking

Track progress in a structured format:

| Court | Original Class | New Class | Status | Notes |
|-------|---------------|-----------|--------|-------|
| nyscef | `opinions.united_states.state.ny.nyscef` | `NYSCEFOpinionScraper` | In Progress | |
| ... | ... | ... | ... | ... |

## Configuration

### `migration_config.yaml`

```yaml
# Fields configuration
match_keys:
  - case_name
  - docket_number
  - date_filed

required_fields:
  - case_name
  - docket_number
  - date_filed
  - url

optional_fields:
  - judge
  - nature_of_suit
  - precedential_status

# Normalization rules
normalizations:
  case_name:
    - strip_whitespace
    - normalize_vs
    - lowercase_compare
  docket_number:
    - strip_whitespace
    - remove_spaces
    - uppercase

# Acceptable thresholds
thresholds:
  max_missing_in_new: 0          # Regressions not allowed
  max_field_differences: 0.05    # 5% field-level differences OK
```

## Future Considerations

1. **Continuous validation**: Run comparison tests periodically to catch regressions
2. **Performance comparison**: Track scrape time and resource usage
3. **Error rate comparison**: Compare transient error rates between implementations
4. **Coverage metrics**: Track which courts have been migrated

## Open Questions

1. How should we handle courts where the original scraper has known bugs?
2. Should we maintain both implementations during a transition period?
3. What's the rollback strategy if the new scraper has issues in production?
