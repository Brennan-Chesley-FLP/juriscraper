# North Dakota Courts Scraper XSD Documentation

This directory contains XSD schema files documenting the page structures
scraped by the North Dakota Supreme Court opinions scraper.

## Important Note

**This scraper requires PlaywrightDriver** due to the React/JavaScript
SPA architecture of the ndcourts.gov website. The opinion detail pages
are rendered client-side and will appear blank with static HTTP requests.

## Files

### parse_opinions_list.xsd

Documents the opinions search/list page at:
- `https://www.ndcourts.gov/supreme-court/opinions`
- `https://www.ndcourts.gov/supreme-court/opinions?page=N`

This page is server-rendered and shows a table of opinion cards with:
- Case name and citation
- Docket number
- Filing date
- Case type
- Author
- View Opinion button

### parse_opinion_detail.xsd

Documents individual opinion detail pages at:
- `https://www.ndcourts.gov/supreme-court/opinions/{internal_id}`

This page requires JavaScript rendering and contains:
- Full opinion metadata
- Opinion text
- PDF download link

## URL Patterns

| Page | URL Pattern | Rendering |
|------|-------------|-----------|
| Opinions List | `/supreme-court/opinions` | Server-side |
| Opinions List (paged) | `/supreme-court/opinions?page=N` | Server-side |
| Opinion Detail | `/supreme-court/opinions/{id}` | JavaScript (React) |

## Data Patterns

### Citation Format
- Pattern: `YYYY ND NNN` (e.g., "2026 ND 7")
- Regex: `(\d{4})\s+ND\s+(\d+)`

### Docket Number Format
- Pattern: 8-digit number (e.g., "20240233")
- Contains: YYYY + sequential number

### Date Format
- Pattern: `M/D/YYYY` (e.g., "1/15/2026")
- Single or double digit month/day
