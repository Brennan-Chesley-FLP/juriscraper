# Scraper Development Guide

This guide documents how to develop scrapers using the scraper-driver architecture. It captures design decisions and best practices learned from building scrapers like the NYSCEF scraper.

## Quick Start

1. **Explore the site with Playwright** - Use the MCP Playwright tools to understand page structure
2. **Map data to base.py models** - Identify which `ConsumerModel` types match the data
3. **Create scraper-specific models** - Extend base models with site-specific fields
4. **Implement with checked_xpaths** - Use restrictive validation to catch structural changes
5. **Test with LocalDevDriver** - Run the scraper through the development driver

## Architecture Overview

```
BaseScraper[T]
    |
    ├── get_entry() -> NavigatingRequest
    |       Creates initial request to start scraping
    |
    ├── @speculate decorator
    |    Decorate a function to turn an int into a NavigatingRequest.
    |    These function as potentially infinite entry points for enumerating cases that could exist
    |
    └── @step decorated methods
            Generator functions that:
            - Receive Response (auto-parsed as lxml_tree, json_content, etc.)
            - Yield ParsedData[T] (final scraped data)
            - Yield NavigatingRequest (follow links)
            - Yield NonNavigatingRequest (API calls without location change)
            - Yield ArchiveRequest (download files)
```

### Early Branching in get_entry()

When a scraper supports multiple data types (opinions, dockets, oral arguments, judges), **branch early in `get_entry()`** to avoid wasting requests on unwanted data:

```python
def get_entry(self) -> Generator[ScraperYield, None, None]:
    """Entry point - branch based on requested data types."""
    requested = self._get_requested_data_types()

    # Opinions are on the archive site
    if "opinions" in requested:
        yield NavigatingRequest(
            url="https://example.com/opinions/archive",
            continuation=self.parse_opinion_archive,
        )

    # Dockets are on a separate case search portal
    if "dockets" in requested:
        yield NavigatingRequest(
            url="https://example.com/case-search",
            continuation=self.parse_case_search,
        )

    # Oral arguments have their own calendar
    if "oral_arguments" in requested:
        yield NavigatingRequest(
            url="https://example.com/calendar/oral-arguments",
            continuation=self.parse_oral_arguments,
        )

    # Judge bios are typically on a different part of the site
    if "judges" in requested:
        yield NavigatingRequest(
            url="https://example.com/about/justices",
            continuation=self.parse_judges_list,
        )
```

**Why branch early?**
- Different data types often live on completely different parts of a court website
- Avoids fetching and parsing pages you don't need
- Makes the scraper more efficient when only one data type is requested
- Keeps step functions focused on one data type

## Directory Structure

```
juriscraper/sd/
├── AGENTS.md           # This file
├── state/
│   └── {state_name}/
│       └── {court_system}/
│           ├── __init__.py
│           ├── models.py    # Pydantic data models
│           ├── scraper.py   # BaseScraper implementation
│           └── xsds/        # XSDs for pages
│               └── example.xsd # an example xsd, generally named after the step function.
└── federal/
    └── {court_system}/
        └── ...
```

## Step-by-Step Development Process

### 1. Site Exploration with Playwright

Use the MCP Playwright tools to explore the target site:

```
browser_navigate -> Navigate to pages
browser_snapshot -> Get accessibility tree (preferred)
browser_take_screenshot -> Visual capture if needed
browser_click -> Interact with elements
```

Document the following for each page type:
- URL patterns and query parameters
- Form fields and their values
- Table structures (headers, row format)
- Labeled fields (key: value patterns)
- Links that lead to detail pages
- XSD for that page type

### 2. Data Model Mapping

Map site data to `juriscraper/scraper_driver/common/models/base.py` types:

| Site Concept | Base Model | Key Fields |
|-------------|------------|------------|
| Case/Docket | `Docket` | docket_number, case_name, court_id, assigned_to_str |
| Party | `Party` + `PartyType` | name, party_type (via PartyType) |
| Attorney | `Attorney` + `Role` | name, contact_raw, role (via Role) |
| Filing | `DocketEntry` | date_filed, entry_number, description |
| Document | `RECAPDocument` | document_number, download_url, description |

### 3. Create Scraper-Specific Models

In `models.py`, create Pydantic models that:
- **Subclass ConsumerModel types** from `base.py` (Docket, Party, Attorney, DocketEntry, etc.)
- Make optional base fields required where appropriate
- Add site-specific fields
- Include **searchable field annotations** for filtering
- Map court names to CourtListener IDs from `docs/data/courts.toml`

#### Searchable Fields

Use `typing.Annotated` with markers from `searchable.py` to enable filtering:

```python
from typing import Annotated
from juriscraper.scraper_driver.common.searchable import (
    DateRange,    # Filter by date range (gte/lte)
    SetFilter,    # Filter by set of allowed values
    UniqueMatch,  # Filter by exact single value
)

class MySiteDocket(Docket):
    """A docket from MySite."""

    # Searchable fields - annotate with filter type
    docket_number: Annotated[str, UniqueMatch()]
    """Case number for direct lookup"""

    court_id: Annotated[str, SetFilter()]
    """Court ID from courts.toml (enables multi-court search)"""

    date_filed: Annotated[date | None, DateRange()] = None
    """Filing date (enables date range filtering)"""

    # Non-searchable fields - no annotation needed
    case_name: str
    case_type: str | None = None
```

#### Using Search Parameters

Scrapers receive search parameters via `ScraperParams`:

```python
# Building params (caller/driver side)
params = MyScraper.params()
params.MySiteDocket.date_filed.gte = date(2024, 1, 1)
params.MySiteDocket.date_filed.lte = date(2024, 12, 31)
params.MySiteDocket.court_id.values = {"nysupctbrnx", "nysupctkings"}
params.MySiteDocket.docket_number.value = "2024-CV-001"

# Disable a data type entirely by setting its model to None
# IMPORTANT: Use this pattern, NOT params.data_types = {...}
params.MySiteDocket = None

# Initialize scraper with params
scraper = MyScraper(params=params)
```

```python
# Inside scraper - reading params
class MyScraper(BaseScraper[MySiteDocket]):
    def __init__(self, params: ScraperParams | None = None):
        self._params = params

    def _get_search_filters(self):
        if not self._params:
            return None, None, None

        model = self._params.MySiteDocket

        # Read DateRange filter
        date_filter = model.get_searchable_fields().get("date_filed")
        if date_filter and date_filter.is_set():
            date_gte = date_filter.gte
            date_lte = date_filter.lte

        # Read SetFilter
        court_filter = model.get_searchable_fields().get("court_id")
        if court_filter and court_filter.is_set():
            court_ids = court_filter.values  # set of court IDs

        # Read UniqueMatch
        docket_filter = model.get_searchable_fields().get("docket_number")
        if docket_filter and docket_filter.is_set():
            docket_num = docket_filter.value
```

#### Disabling Data Types

For scrapers that support multiple data types (e.g., opinions, oral arguments, dockets), disable unwanted types by setting their model to `None`:

```python
# Example: Scrape only opinions from a multi-type scraper
params = ConnScraper.params()
params.ConnOralArgument = None  # Disable oral arguments
params.ConnDocket = None        # Disable dockets
# ConnOpinionCluster is still enabled
scraper = ConnScraper(params=params)

# Example: Scrape only dockets with a filter
params = ConnScraper.params()
params.ConnOpinionCluster = None
params.ConnOralArgument = None
params.ConnDocket.crn.gt = 90000  # Start from CRN 90000
scraper = ConnScraper(params=params)
```

**IMPORTANT:** Do NOT use `params.data_types = {"opinions"}`. Always disable unwanted data types by setting their model to `None`.

#### Court ID Mapping

Map site-specific court names to CourtListener IDs:

```python
# In models.py
COURT_ID_MAP: dict[str, str] = {
    "Bronx County Supreme Court": "nysupctbrnx",
    "Kings County Supreme Court": "nysupctkings",
    # ... see docs/data/courts.toml for all IDs
}

def get_court_id(site_court_name: str) -> str:
    """Map site court name to CourtListener court_id."""
    court_id = COURT_ID_MAP.get(site_court_name)
    if court_id is None:
        raise ValueError(f"Unknown court: {site_court_name}")
    return court_id
```

### 4. Implement Scraper with Checked XPaths

Key principles:

#### a. Use Restrictive Checked XPaths

```python
# GOOD: Validates expected count, fails if structure changes
headers = tree.checked_xpath(
    "//table//th/text()",
    "table headers",
    min_count=4,
    max_count=4,
    type=str,
)

# BAD: Silent failure on structure changes
headers = tree.xpath("//table//th/text()")
```

#### b. Validate Table Column Headers

```python
EXPECTED_COLUMNS = ["#", "Document", "Filed By", "Status"]

def _validate_table_headers(self, tree):
    headers = tree.checked_xpath(
        "//table//th/text()",
        "document table headers",
        min_count=len(EXPECTED_COLUMNS),
        max_count=len(EXPECTED_COLUMNS),
        type=str,
    )
    for i, expected in enumerate(EXPECTED_COLUMNS):
        actual = headers[i].strip()
        if expected.lower() != actual.lower():
            raise ValueError(
                f"Unexpected column: expected '{expected}', got '{actual}'"
            )
```

#### d. Use @step Decorator for Argument Injection

```python
@step
def parse_page(
    self,
    lxml_tree: CheckedHtmlElement,  # Auto-parsed HTML
    response: Response,              # Original response
    accumulated_data: dict,          # Data from previous steps
) -> Generator[ScraperYield[MyCase], bool | None, None]:
    ...
```

Available injected parameters:
- `response` - The Response object
- `request` - The current BaseRequest
- `previous_request` - Parent request from chain
- `accumulated_data` - Dict carried across requests
- `aux_data` - Navigation metadata (tokens, session data)
- `json_content` - Response parsed as JSON
- `lxml_tree` - Response parsed as CheckedHtmlElement
- `text` - Response as string
- `local_filepath` - Local path from ArchiveResponse

#### e. Use accumulated_data for Cross-Page Data

```python
@step
def parse_list(self, lxml_tree):
    for link in links:
        yield NavigatingRequest(
            url=link,
            continuation=self.parse_detail,
            accumulated_data={"list_page_url": response.url},
        )

@step
def parse_detail(self, lxml_tree, accumulated_data):
    list_url = accumulated_data["list_page_url"]
    # ... use data from previous step
```

### 5. Priority Hints

Use `@step(priority=N)` to control processing order (lower = higher priority):

```python
@step(priority=1)  # Process first (e.g., document downloads)
def download_document(self, ...): ...

@step(priority=5)  # Standard priority (e.g., detail pages)
def parse_detail(self, ...): ...

@step(priority=9)  # Default priority (e.g., list pages)
def parse_list(self, ...): ...
```

### 6. Scraper Metadata

Set class-level metadata for documentation and registry:

```python
class MyScraper(BaseScraper[MyCase]):
    court_ids: ClassVar[set[str]] = {"my_court"}
    court_url: ClassVar[str] = "https://example.com/"
    data_types: ClassVar[set[str]] = {"dockets", "docket_entries"}
    status: ClassVar[ScraperStatus] = ScraperStatus.IN_DEVELOPMENT
    version: ClassVar[str] = "2025-01-10"
    requires_auth: ClassVar[bool] = False
    msec_per_request_rate_limit: ClassVar[int] = 2000  # Be respectful
```

## Common Patterns

### Form Submission

```python
@step
def submit_search(self, lxml_tree, response):
    yield NavigatingRequest(
        request=HTTPRequestParams(
            method=HttpMethod.POST,
            url="/search",
            data={
                "query": self.search_term,
                "date": self.date.strftime("%m/%d/%Y"),
            },
        ),
        continuation=self.parse_results,
    )
```

### File Downloads

**IMPORTANT:** All binary files (PDFs, audio files, images, etc.) MUST be fetched using `ArchiveRequest`. Do not just store URLs in your models—the driver needs to actually download the files.

```python
@step
def download_document(self, lxml_tree, response, accumulated_data):
    yield ArchiveRequest(
        request=HTTPRequestParams(url=doc_url),
        continuation=self.process_download,
        expected_type="pdf",
        accumulated_data=accumulated_data,
    )
```

When you encounter document URLs (e.g., opinion PDFs, oral argument audio):

1. **Yield an `ArchiveRequest`** for each file URL
2. **Add a continuation** to handle the downloaded file
3. **Store the local path** from `response.file_url` in your model
4. **Only yield `ParsedData`** after all files are downloaded

Example pattern for multiple files per result:

```python
@step
def parse_case(self, lxml_tree, response, accumulated_data):
    # Collect all PDF URLs
    pdf_urls = [...]  # Extract from page

    # Store metadata for final assembly
    cluster_data = {
        "case_name": case_name,
        "pdfs": [{"url": url, "type": t} for url, t in pdf_urls],
        "pending_downloads": len(pdf_urls),
        "completed_downloads": 0,
        "downloaded_paths": {},
    }

    # Yield ArchiveRequest for first PDF
    yield ArchiveRequest(
        request=HTTPRequestParams(url=pdf_urls[0][0]),
        continuation=self.handle_pdf_download,
        expected_type="pdf",
        accumulated_data={**cluster_data, "current_index": 0},
    )

@step
def handle_pdf_download(self, response: ArchiveResponse, accumulated_data):
    idx = accumulated_data["current_index"]
    accumulated_data["downloaded_paths"][idx] = response.file_url
    accumulated_data["completed_downloads"] += 1

    if accumulated_data["completed_downloads"] >= accumulated_data["pending_downloads"]:
        # All done - build and yield final result
        yield ParsedData(MyCluster(...))
    else:
        # More files to download
        next_idx = idx + 1
        yield ArchiveRequest(
            request=HTTPRequestParams(url=accumulated_data["pdfs"][next_idx]["url"]),
            continuation=self.handle_pdf_download,
            expected_type="pdf",
            accumulated_data={**accumulated_data, "current_index": next_idx},
        )
```

## Running Scrapers

### CLI (Recommended for Quick Runs)

Use the CLI for running scrapers and exporting results:

```bash
# List available scrapers
uv run python scripts/async_cli.py --list-scrapers

# Run a scraper (by class name)
uv run python scripts/async_cli.py --scraper NYSCEFScraper

# Run with search parameters
uv run python scripts/async_cli.py \
    --scraper NYSCEFScraper \
    --param "NYSCEFDocket.date_filed.gte=2025-01-01" \
    --param "NYSCEFDocket.date_filed.lte=2025-01-07" \
    --param "NYSCEFDocket.court_id.values=nysupctbrnx,nysupctkings"

# Run with max results and output file
uv run python scripts/async_cli.py \
    --scraper NYSCEFScraper \
    --max-results 100 \
    --results output.jsonl

# Verbose mode (shows each result)
uv run python scripts/async_cli.py --scraper NYSCEFScraper --verbose
```

**CLI Options:**
| Option | Description |
|--------|-------------|
| `--scraper, -s NAME` | Scraper name or full path (module:Class) |
| `--list-scrapers` | List all available scrapers |
| `--param, -p PARAM` | Parameter in `Model.field.operator=value` format |
| `--max-results, -n N` | Stop after collecting N results |
| `--results, -r PATH` | Write results as JSONL to file |
| `-v, --verbose` | Show each result as it's collected |

**Parameter Format:**
- DateRange: `Model.field.gte=2025-01-01`, `Model.field.lte=2025-12-31`
- SetFilter: `Model.field.values=value1,value2,value3`
- UniqueMatch: `Model.field.value=exact-value`

### Web Interface (For Development & Debugging)

The LocalDevDriver web interface provides:
- Run management (create, load, start, stop)
- Request queue inspection
- Error tracking with HTML response viewing
- Response compression stats

```bash
# Start the web interface
uv run python -m juriscraper.scraper_driver.driver.dev_driver.run --serve --port 8001

# With reload for development
uv run uvicorn juriscraper.scraper_driver.driver.dev_driver.web.app:app --reload --port 8001
```

Then visit http://127.0.0.1:8001

## Design Patterns Reference

These patterns are documented in `docs/source/scraper_driver/design/`.

### Request Types

| Type | Purpose | When to Use |
|------|---------|-------------|
| `NavigatingRequest` | Standard page fetch | Following links, loading detail pages |
| `NonNavigatingRequest` | API calls | AJAX/JSON endpoints that don't change "location" |
| `ArchiveRequest` | File downloads | PDFs, audio files - content saved to disk |

### Data Flow Patterns

#### accumulated_data
Data that flows **forward** through request chains. Use for:
- Case metadata from list page needed on detail page
- Parent IDs needed when creating child records
- **Deep copied** at each step - modifications don't affect parent

```python
yield NavigatingRequest(
    url=detail_url,
    continuation=self.parse_detail,
    accumulated_data={"case_id": case_id, "court": court_name},
)
```

#### aux_data
Navigation metadata **separate** from scraped data. Use for:
- Session tokens, CSRF tokens
- Pagination cursors, page numbers
- Internal navigation state

```python
yield NavigatingRequest(
    url=next_page,
    continuation=self.parse_list,
    aux_data={"page_token": next_token, "page_num": page + 1},
)
```

### @step Decorator

The `@step` decorator uses **argument inspection** to auto-inject values based on parameter names:

```python
@step
def parse_page(self, lxml_tree, response):
    # lxml_tree and response automatically injected!
    cases = lxml_tree.checked_xpath("//div[@class='case']", "cases")
    for case in cases:
        yield ParsedData(...)

@step
def parse_api(self, json_content, request):
    # json_content and request automatically injected!
    for item in json_content['items']:
        yield ParsedData(...)
```

**Supported parameter names:**

| Parameter | Injected Value |
|-----------|----------------|
| `response` | The Response object |
| `request` | The current BaseRequest |
| `previous_request` | Parent request from chain (None for entry) |
| `json_content` | Response parsed as JSON |
| `lxml_tree` | Response parsed as CheckedHtmlElement |
| `text` | Response as string |
| `accumulated_data` | Dict from Request object |
| `aux_data` | Dict from Request object |
| `local_filepath` | File path from ArchiveResponse |

**Features:**
- Content parsed **on-demand** (only parse JSON if `json_content` requested)
- **Callable continuations** auto-resolve to function names
- **Priority metadata** via `@step(priority=N)` (lower = higher priority)

```python
@step
def parse_first(self, response):
    yield NavigatingRequest(
        url="/next",
        continuation=self.parse_second  # Callable - auto-resolved!
    )

@step(priority=5)  # Lower = higher priority
def parse_second(self, response):
    yield ParsedData(...)
```

### CheckedHtmlElement

Wrapper that validates XPath/CSS results against expected counts:

```python
# Raises HTMLStructuralAssumptionException if count doesn't match
cases = tree.checked_xpath(
    "//div[@class='case']",
    "case cards",
    min_count=1,
    max_count=50,
)
```

### DeferredValidation

Pydantic model validation deferred to driver:

```python
yield ParsedData(
    MyCaseData.raw(
        request_url=response.url,
        docket="2024-001",
        case_name="Smith v. Jones",
        # ... fields validated by driver
    )
)
```

### Exception Types

| Exception | Meaning |
|-----------|---------|
| `HTMLStructuralAssumptionException` | HTML structure changed - scraper needs update |
| `DataFormatAssumptionException` | Data doesn't match schema - model needs update |

## Final Pass: XSD Documentation

After completing and testing the scraper, create XSD files to document the expected page structure for each `@step` function that processes HTML. This helps catch structural changes and aids debugging.

### Creating XSD Files

1. **Use Playwright to capture each page type** the scraper processes:
   ```
   browser_navigate -> Navigate to the page
   browser_snapshot -> Capture the accessibility tree structure
   ```

2. **Create XSD files** in the `xsds/` directory, named after the step function:
   ```
   xsds/
   ├── parse_archive_index.xsd
   ├── parse_year_page.xsd
   └── README.md
   ```

3. **Document in each XSD**:
   - URL pattern for this page type
   - XPaths used by the scraper
   - Expected element counts (min/max)
   - Regex patterns for data extraction
   - Edge cases and known variations

Example XSD structure:
```xml
<?xml version="1.0" encoding="UTF-8"?>
<!--
  XSD Schema for [Page Type]
  URL: [URL pattern]

  Step: [step_function_name]
  XPath used: [xpath expression]
-->
<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema">
  <xs:annotation>
    <xs:documentation>
      Page Structure
      ==============
      [Description of page layout and key elements]

      Scraper XPath Assertions
      ========================
      1. XPATH_NAME: [xpath]
         - Description: "[description]"
         - min_count: N
         - Expected: [what it returns]
    </xs:documentation>
  </xs:annotation>

  <!-- Element definitions -->
</xs:schema>
```

### Adding XSD Annotations to Steps

Add the `xsd` parameter to each `@step` decorator that processes HTML:

```python
@step(xsd="xsds/parse_archive_index.xsd")
def parse_archive_index(self, lxml_tree, response):
    """Parse the archive index page."""
    ...

@step(xsd="xsds/parse_year_page.xsd")
def parse_year_page(self, lxml_tree, response, accumulated_data):
    """Parse a year's archive page."""
    ...

@step  # No xsd needed - processes ArchiveResponse (PDF), not HTML
def handle_download(self, response: ArchiveResponse, accumulated_data):
    """Handle downloaded file."""
    ...
```

**Note:** Only add `xsd` annotations to steps that process HTML pages (`lxml_tree`). Steps that handle `ArchiveResponse` (file downloads) or `json_content` don't need XSD documentation.

## Checklist for New Scrapers

- [ ] Explored site structure with Playwright
- [ ] Documented URL patterns
- [ ] Mapped data to base.py ConsumerModel types
- [ ] Created scraper-specific models that subclass base.py types
- [ ] Added searchable field annotations (DateRange, SetFilter, UniqueMatch)
- [ ] Created court ID mapping to CourtListener IDs (from courts.toml)
- [ ] Implemented BaseScraper subclass with ScraperParams support
- [ ] Used checked_xpath/checked_css with count validation
- [ ] Validated table column headers
- [ ] Validated expected labeled fields
- [ ] **Used ArchiveRequest for all binary files (PDFs, audio, etc.)**
- [ ] Added scraper metadata (court_ids, version, etc.)
- [ ] Tested with LocalDevDriver
- [ ] **Created XSD files for each HTML page type in `xsds/` directory**
- [ ] **Added `xsd="xsds/..."` annotations to `@step` decorators**

## Coverage

The goal of every scraper is **complete coverage**—we want to collect all available opinions, oral arguments, dockets, etc. from a court site. The approach depends on what the site offers.

### Preferred: Date-Based Search

When a site offers date-based search or filtering, use it. This is the most reliable way to ensure complete coverage:

```python
@step
def search_by_date_range(self, lxml_tree):
    """Search for all records within the configured date range."""
    start_date, end_date = self._get_date_range()

    yield NavigatingRequest(
        request=HTTPRequestParams(
            url=f"/search?from={start_date}&to={end_date}",
        ),
        continuation=self.parse_results,
    )
```

**Why date-based is preferred:**
- Deterministic—you know exactly what date range you're covering
- Efficient—no wasted requests probing for non-existent records
- Resumable—easy to pick up where you left off by adjusting the date range
- Complete—if the site has records for those dates, you'll get them

### Fallback: The @speculate Decorator

Some sites only allow search by docket number or case ID, with no date-based filtering. When that's the case, use the `@speculate` decorator to enumerate potential cases:

```python
from juriscraper.scraper_driver.common.decorators import speculate

class MyScraper(BaseScraper[MyCase]):

    @speculate(highest_observed=50000, largest_observed_gap=100)
    def fetch_case(self, case_id: int) -> NavigatingRequest:
        """Probe for a case by ID.

        The driver will call this with sequential IDs, tracking successes
        and failures to determine when to stop probing.
        """
        return NavigatingRequest(
            request=HTTPRequestParams(
                url=f"/case/{case_id}",
            ),
            continuation=self.parse_case,
        )
```

**How @speculate works:**
1. The driver calls the decorated function with incrementing integer IDs
2. For each ID, it makes the request and checks the response
3. It tracks the highest successful ID and consecutive failures
4. When failures exceed `largest_observed_gap`, it stops probing

**@speculate parameters:**
- `highest_observed`: The highest ID known to exist (starting point for probing)
- `largest_observed_gap`: How many consecutive failures before stopping
- `observation_date`: When these values were last verified (for documentation)

**When to use @speculate:**
- Site only offers search by case/docket number
- Resources have sequential integer IDs (e.g., `/case/12345`, `/opinion/67890`)
- No date-based search or index page available

**When NOT to use @speculate:**
- Site has date-based search (use that instead)
- Site has pagination with "next page" links (use regular `NavigatingRequest`)
- Site has a complete index or listing page you can parse

### Coverage Checklist

When exploring a new site, determine your coverage strategy:

1. **Look for date-based search first**
   - Search forms with date pickers
   - URL parameters like `?from=...&to=...` or `?date=...`
   - "Recent opinions" pages that can be parameterized

2. **Check for complete listings**
   - Archive pages by year/month
   - "All opinions" or "All cases" indexes
   - Sitemaps

3. **Fall back to @speculate only when necessary**
   - Identify the URL pattern (e.g., `/case/{id}`)
   - Determine the current highest ID (probe manually or check recent records)
   - Estimate the largest gap between IDs (some sites skip numbers)
