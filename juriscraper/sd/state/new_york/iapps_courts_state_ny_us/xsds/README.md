# XSD Documentation for NYSCEF Scraper

This directory contains XSD schema files documenting the expected page structures
for the NYSCEF (iapps.courts.state.ny.us/nyscef) scraper.

## Pages

### search_results.xsd
- **URL**: https://iapps.courts.state.ny.us/nyscef/CaseSearchResults
- **Step**: `parse_search_results`
- **Purpose**: Documents the search results table after case number search

### case_detail.xsd
- **URL Pattern**: `https://iapps.courts.state.ny.us/nyscef/CaseDetails?docketId={base64}`
- **Step**: `parse_case_detail`
- **Purpose**: Documents case detail page with parties, originating court info

### document_list.xsd
- **URL Pattern**: `https://iapps.courts.state.ny.us/nyscef/DocumentList?docketId={base64}&display=all`
- **Step**: `parse_document_list`
- **Purpose**: Documents the document list table with all filed documents

## Key XPath Patterns

### Search Results
```xpath
//table[contains(@class, 'NewSearchResults')]//tr[position()>1]
```
Finds all data rows in the search results table.

### Case Detail
```xpath
//div[contains(@class, 'DataEntry_InnerBox')]//span[contains(@class, 'DataRow')]
//div[contains(@class, 'tableHeading')]
//table[contains(@summary, 'in this case')]//tbody/tr
```
Full caption, party group headings, and party rows.

### Document List
```xpath
//table[contains(@summary, 'all documents')]//tr[position()>1]
```
All document rows in the filing table.

## URL Patterns

### Case Number Format
`YYYY-NNNNN` (e.g., `2024-00003`)

### Internal IDs
- `docketId`: Base64-encoded opaque identifier (e.g., `3xtYV7mv1CzzdOJn_PLUS_mnRpA==`)
- `docIndex`: Base64-encoded document identifier for ViewDocument URLs

### Page URLs
- Search: `CaseSearch?TAB=caseIdentifier`
- Results: `CaseSearchResults`
- Detail: `CaseDetails?docketId={id}`
- Documents: `DocumentList?docketId={id}&display=all`
- View Doc: `ViewDocument?docIndex={id}`
