# XSD Documentation for NY Court of Appeals Scraper

This directory contains XSD schema files documenting the expected page structures
for the New York Court of Appeals scraper.

## Files

### parse_decisions_index.xsd
- **URL**: https://www.nycourts.gov/ctapps/decisions.htm
- **Step**: `parse_decisions_index`
- **Purpose**: Documents the main index page structure with year/month links

### parse_month_page.xsd
- **URL Pattern**: `https://www.nycourts.gov/ctapps/Decisions/{YYYY}/{Mon}{YY}/{Month}{YY}.html`
- **Step**: `parse_month_page`
- **Purpose**: Documents monthly decision page structure with opinion listings

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
