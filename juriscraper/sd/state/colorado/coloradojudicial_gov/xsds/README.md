# Colorado Scraper XSD Documentation

This directory contains XSD files documenting the expected HTML structure of pages
scraped by the Colorado appellate courts scraper.

## Files

### parse_slip_opinions_page.xsd

Documents the structure of the Supreme Court slip opinions page at:
https://www.coloradojudicial.gov/supreme-court/opinions

Key elements:
- Date headers in paragraphs
- Citation links to detail pages
- Docket numbers and case names

### parse_opinion_detail_page.xsd

Documents the structure of individual opinion detail pages at:
https://www.coloradojudicial.gov/node/{node_id}

Key elements:
- PDF download link with pattern: `/system/files/opinions-{year}-{month}/{docket}.pdf`

## URL Patterns

| Page Type | URL Pattern | Example |
|-----------|-------------|---------|
| Slip Opinions | /supreme-court/opinions | https://www.coloradojudicial.gov/supreme-court/opinions |
| Opinion Detail | /node/{node_id} | https://www.coloradojudicial.gov/node/15390 |
| Opinion PDF | /system/files/opinions-{YYYY}-{MM}/{docket}.pdf | /system/files/opinions-2025-12/23SC847.pdf |

## Data Patterns

### Citation Format
- Supreme Court: `YYYY CO N` or `YY CO N` (e.g., "2025 CO 63", "26 CO 1")
- Modified opinions: append "M" (e.g., "2025 CO 60M")

### Docket Number Format
- Supreme Court: `{YY}SC{sequence}` or `{YY}SA{sequence}`
  - SC = certiorari/appeal cases
  - SA = original jurisdiction cases
  - Examples: 25SC347, 23SC847, 25SA204
- Court of Appeals: `{YY}CA{sequence}`
  - Example: 24CA1951

### Date Format
Dates appear as "Month DD, YYYY" (e.g., "January 12, 2026")
