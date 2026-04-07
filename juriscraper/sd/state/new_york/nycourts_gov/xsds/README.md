# XSD Documentation for NY Court of Appeals Scrapers

This directory contains XSD schema files documenting the expected page structures
for the New York Court of Appeals scrapers.

## Opinions Scraper (nycourts.gov/ctapps)

### parse_decisions_index.xsd
- **URL**: https://www.nycourts.gov/ctapps/decisions.htm
- **Step**: `parse_decisions_index`
- **Purpose**: Documents the main index page structure with year/month links

### parse_month_page.xsd
- **URL Pattern**: `https://www.nycourts.gov/ctapps/Decisions/{YYYY}/{Mon}{YY}/{Month}{YY}.html`
- **Step**: `parse_month_page`
- **Purpose**: Documents monthly decision page structure with opinion listings

## Court-PASS Docket Scraper (courtpass.nycourts.gov)

### courtpass_search_page.xsd
- **URL**: https://courtpass.nycourts.gov/Public_search.aspx
- **Steps**: `parse_search_page`, `parse_search_results`
- **Purpose**: Search form (by argument/decision date) and results tables

### courtpass_filing_detail.xsd
- **URL**: Reached via postback from search/browse/docket results
- **Steps**: `parse_filing_detail`, `parse_filing_detail_from_docket`, `parse_docket_filing_detail`
- **Purpose**: Filing detail page with case info, issues, and file downloads
- **Form IDs**: `Form1` (search), `Form3` (browse), `Form2` (docket)
- **Detail spans**: `cphMain_lbDetails` (search/browse), `cphMain_lbDetails2` (docket)

### courtpass_docket_page.xsd
- **URL**: https://courtpass.nycourts.gov/Docket.aspx
- **Steps**: `parse_docket_page`, `fill_docket_search`, `parse_docket_results`, `parse_docket_detail`, `parse_docket_detail_for_entry`, `parse_docket_number_results`
- **Purpose**: Docket search form, paginated results, and detail page with filings table, attorney details, and hidden CallDetails button
- **Form ID**: `Form2`

### courtpass_browse_page.xsd
- **URL**: https://courtpass.nycourts.gov/Public_Browse.aspx
- **Steps**: `parse_browse_page`, `parse_browse_date_page`, `parse_browse_results`
- **Purpose**: Alphabetical case listing with date filtering, pagination, and lost-context recovery
- **Form ID**: `form1` (lowercase)

## Key XPath Patterns

### Index Page
```xpath
//a[contains(@href, 'Decisions/')]/@href
```
Finds all month links on the decisions index page.

### Month Page
```xpath
//table//tr                    # All table rows
td                             # Cells within a row
strong/text()                  # Date headers
a/@href                        # PDF links
.//text()                      # Cell text content
```

## Page Structure Notes

### Decision Dates
Date header rows contain a `<strong>` element with dates like "December 18, 2025".

### Opinion Numbers
Multiple formats observed:
- Simple: "No. 102"
- Range: "No. 105-110" (consolidated cases)
- With SSM: "No. 128 SSM 3" (Special Session Memoranda)
- Typo variant: "No .115" (space before period)

### PDF Filenames
Pattern: `{number}{type}{year}-Decision.pdf`
Types:
- `opn` - Opinion (full written opinion)
- `mem` - Memorandum (brief opinion)
- `ent` - Entry (order/entry)
