# Alabama Appellate Courts Scraper

This scraper collects opinions, dockets, and oral arguments from Alabama's three appellate courts using the new Public Portal API.

## Supported Courts

- **Alabama Supreme Court** (`ala`)
  - GUID: `68f021c4-6a44-4735-9a76-5360b2e8af13`
  - Clerk: Megan B. Rhodebeck

- **Alabama Court of Civil Appeals** (`alactapp`)
  - GUID: `1da1a297-c391-4e4f-9480-1bc68b46f21a`
  - Clerk: Seth Rhodebeck

- **Alabama Court of Criminal Appeals** (`alacrimapp`)
  - GUID: `b82b30d5-bd3c-46d7-9451-1cb05e470873`
  - Clerk: D. Scott Mitchell

## Data Types

### Opinions (✅ Implemented)

Scrapes weekly release lists from the Publications API endpoint.

**Data Structure:**
- Release lists are published weekly
- Each release contains multiple opinions grouped by authoring judge
- Opinions include case number, case name, decision, and PDF document
- Lower court information extracted from case title parentheticals
- Handles "Per Curiam" and "On Rehearing" designations

**API Endpoint:**
```
GET https://publicportal-api.alappeals.gov/courts/cms/publications
Parameters:
  - courtID: Court GUID
  - page: Page number (0-indexed)
  - size: Results per page (default: 25)
  - sort: publicationDate,desc
```

**Example Usage:**
```python
from juriscraper.sd.state.alabama.publicportal_alappeals_gov.scraper import AlabamaScraper

# Scrape all courts, all opinions
scraper = AlabamaScraper()

# Scrape only Alabama Supreme Court opinions
params = AlabamaScraper.params()
params.AlaOralArgument = None
params.AlaDocket = None
params.AlaOpinionCluster.court_id.values = {"ala"}
scraper = AlabamaScraper(params=params)

# Filter by date range
params = AlabamaScraper.params()
params.AlaOpinionCluster.date_filed.gte = date(2025, 1, 1)
params.AlaOpinionCluster.date_filed.lte = date(2025, 12, 31)
scraper = AlabamaScraper(params=params)
```

### Dockets/Cases (✅ Implemented)

Full case information including parties, documents, and filings.

**API Endpoints:**
```
GET https://publicportal-api.alappeals.gov/courts/cms/cases
Parameters:
  - caseHeader.filedDateFrom: Start date (ISO 8601)
  - caseHeader.filedDateTo: End date (ISO 8601)
  - page: Page number (0-indexed)
  - size: Results per page (default: 50)
  - sort: caseHeader.filedDate,asc

GET https://publicportal-api.alappeals.gov/courts/{court-guid}/cms/cases/{case-uuid}
GET https://publicportal-api.alappeals.gov/courts/{court-guid}/cms/cases/{case-uuid}/parties
GET https://publicportal-api.alappeals.gov/courts/{court-guid}/cms/cases/{case-uuid}/docketentries
```

**Data Available:**
- Case header: number, title, classification, filed date, originating court
- Parties: name, role, attorneys, status
- Documents tab: filing date, type, subtype, description, PDF links
- Oral arguments tab: scheduled arguments

**Important Features:**
- Handles API's 10,000 result limit by splitting date ranges
- Documents filed on/after March 20, 2022 available
- Document viewing requires registration (metadata is public)

**Example Usage:**
```python
from juriscraper.sd.state.alabama.publicportal_alappeals_gov.scraper import AlabamaScraper

# Scrape all dockets, all courts
params = AlabamaScraper.params()
params.AlaOralArgument = None
params.AlaOpinionCluster = None
scraper = AlabamaScraper(params=params)

# Scrape dockets from specific date range
params = AlabamaScraper.params()
params.AlaDocket.date_filed.gte = date(2024, 1, 1)
params.AlaDocket.date_filed.lte = date(2024, 12, 31)
scraper = AlabamaScraper(params=params)
```

### Oral Arguments (✅ Implemented)

Scheduled oral arguments with case details.

**API Endpoints:**
```
GET https://publicportal-api.alappeals.gov/courts/cms/events
Parameters:
  - startDateFrom: Start date (ISO 8601 with timezone)
  - startDateTo: End date (ISO 8601 with timezone)
  - page: Page number (0-indexed)
  - size: Results per page (default: 100)
  - sort: startDate,desc

GET https://publicportal-api.alappeals.gov/courts/{court-guid}/cms/events/{event-uuid}/hearings
Parameters:
  - page: Page number (0-indexed)
  - size: Results per page (default: 100)
  - sort: orderBy,asc
```

**Data Available:**
- Event date and location
- Case number and name
- Hearing date/time
- Hearing status (Scheduled, Completed, Cancelled)
- Link to case detail page

**Portal URL Pattern:**
- Search: `https://publicportal.alappeals.gov/portal/search/calendar`

**Example Usage:**
```python
from juriscraper.sd.state.alabama.publicportal_alappeals_gov.scraper import AlabamaScraper

# Scrape all oral arguments, all courts
params = AlabamaScraper.params()
params.AlaOpinionCluster = None
params.AlaDocket = None
scraper = AlabamaScraper(params=params)

# Scrape oral arguments from specific date range
params = AlabamaScraper.params()
params.AlaOralArgument.date_argued.gte = date(2026, 1, 1)
params.AlaOralArgument.date_argued.lte = date(2026, 12, 31)
scraper = AlabamaScraper(params=params)
```

**Notes:**
- YouTube URLs are not provided by the API
- Default date range: 6 months in past to 1 year in future
- Events are filtered by court if specified in params

## Technical Details

### Architecture

- **Framework:** scraper_driver (new async/modern framework)
- **Data source:** JSON API (not HTML scraping)
- **Rate limiting:** 1000ms per request
- **Authentication:** Not required for public data

### Models

All models in `models.py` extend base types from `kent.common.models.base`:

- `AlaOpinionCluster` → `OpinionCluster`
- `AlaOpinion` → `Opinion`
- `AlaOralArgument` → `Audio`
- `AlaDocket` → `Docket`
- `AlaDocketEntry` → `DocketEntry`

**Searchable Fields:**
- `case_number`: UniqueMatch (find specific case)
- `court_id`: SetFilter (select which courts)
- `date_filed`: DateRange (filter by date range)
- `case_instance_uuid`: SpeculativeID (for dockets - future use)

### XSD Documentation

XSD files in `xsds/` document the structure of API responses and pages:

- ✅ `parse_publications_list.xsd` - Publications API response structure
- ✅ `parse_dockets_search.xsd` - Case search API response structure
- ✅ `parse_case_detail.xsd` - Case detail API response structure
- ✅ `parse_case_parties.xsd` - Case parties API response structure
- ✅ `parse_docket_entries.xsd` - Docket entries API response structure
- ✅ `parse_events_list.xsd` - Events/calendar API response structure
- ✅ `parse_event_hearings.xsd` - Event hearings API response structure

## Implementation Status

### ✅ Completed

- [x] Directory structure created
- [x] Models defined for all data types
- [x] Opinions scraping implemented
  - [x] Lower court extraction from case titles
  - [x] Per curiam and rehearing detection
  - [x] PDF archiving via ArchiveRequest
  - [x] XSD documentation for publications API
  - [x] Pagination support
    - Processes all results on each page (not just first)
    - Automatically fetches next page when needed
    - Respects date range filters (date_filed.gte/lte)
    - Stops pagination when outside date range
- [x] Dockets scraping implemented
  - [x] Case search with date range splitting (handles 10,000 result limit)
  - [x] Case detail parsing
  - [x] Parties extraction with attorneys
  - [x] Docket entries parsing with pagination
  - [x] XSD documentation for all docket endpoints

- [x] Oral arguments scraping implemented
  - [x] Events API endpoint discovery and implementation
  - [x] Event hearings parsing
  - [x] XSD documentation for events and hearings
  - [x] Pagination support
  - [ ] YouTube URL extraction (not available in API)

### ⏳ TODO

- [ ] Add tests
  - Unit tests for data extraction
  - Integration tests with mock API responses
  - Example test fixtures

- [ ] Add date filtering to API calls
  - API may support date parameters (needs investigation)
  - Currently filters happen client-side via params

## References

- **Public Portal:** https://publicportal.alappeals.gov/
- **API Base:** https://publicportal-api.alappeals.gov
- **User Guide:** https://judicial.alabama.gov/docs/PublicPortalUserGuide.pdf
- **Supreme Court:** https://judicial.alabama.gov/Appellate/SupremeCourt
- **Civil Appeals:** https://judicial.alabama.gov/Appellate/CivilAppeals
- **Criminal Appeals:** https://judicial.alabama.gov/Appellate/CriminalAppeals

## Historical Note

Alabama previously used different systems for opinions:
- **Before May 19, 2023:** judicial.alabama.gov → acis.alabama.gov
- **After May 19, 2023:** publicportal.alappeals.gov (this scraper)

The existing juriscraper opinions scrapers (`ala.py`, `alacivapp.py`, `alacrimapp.py`) use the same API but with the older OpinionSiteLinear framework. This scraper uses the modern scraper_driver framework for better features like searchable fields, speculative requests, and structured data models.
