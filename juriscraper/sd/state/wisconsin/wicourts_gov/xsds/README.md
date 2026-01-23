# Wisconsin Courts XSD Documentation

This directory contains XSD documentation for the page structures scraped by the Wisconsin appellate courts scraper.

## Page Types

### parse_supreme_court_opinions.xsd
Documents the Supreme Court opinions search results page:
- URL: `https://www.wicourts.gov/supreme/scopin.jsp?begin_date=MM/DD/YYYY&end_date=MM/DD/YYYY&SortBy=date`
- Table columns: Release date, Case number, Caption, Select/view (PDF link)

### parse_appeals_court_opinions.xsd
Documents the Court of Appeals opinions search results page:
- URL: `https://www.wicourts.gov/other/appeals/caopin.jsp?begin_date=MM/DD/YYYY&end_date=MM/DD/YYYY&SortBy=date`
- Table columns: Release date, Case number, Caption, District, County, Select/view (PDF link)
- Caption may contain "[Recommended for Publication]" in bold
