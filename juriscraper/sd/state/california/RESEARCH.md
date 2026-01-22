# California Appellate Courts Research

## Court Structure

California has a three-tier court system:

### 1. Supreme Court of California
- **Website**: https://supreme.courts.ca.gov/
- Highest court in California
- 1 Chief Justice + 6 Associate Justices
- All opinions are published and citable
- Opinions posted at 10:00 a.m. on Mondays and Thursdays

### 2. Courts of Appeal (6 Districts)
- **Website**: https://appellate.courts.ca.gov/
- Intermediate appellate courts divided into 6 geographic districts
- Some districts have multiple divisions

| District | Location | Counties Served |
|----------|----------|-----------------|
| 1st | San Francisco | Alameda, Contra Costa, Del Norte, Humboldt, Lake, Marin, Mendocino, Napa, San Francisco, San Mateo, Solano, Sonoma |
| 2nd | Los Angeles | Los Angeles, Ventura, San Luis Obispo, Santa Barbara |
| 3rd | Sacramento | Alpine, Amador, Butte, Calaveras, Colusa, El Dorado, Glenn, Lassen, Modoc, Mono, Nevada, Placer, Plumas, Sacramento, San Joaquin, Shasta, Sierra, Siskiyou, Sutter, Tehama, Trinity, Yolo, Yuba |
| 4th | San Diego (Div 1), Riverside (Div 2), Santa Ana (Div 3) | Imperial, Inyo, Orange, Riverside, San Bernardino, San Diego |
| 5th | Fresno | Fresno, Kern, Kings, Madera, Mariposa, Merced, Stanislaus, Tulare, Tuolumne |
| 6th | San Jose | Monterey, San Benito, Santa Clara, Santa Cruz |

### 3. Superior Courts (Trial Courts)
- 58 courts (one per county)
- Not covered in this research (focus is on appellate courts)

---

## Key URLs and URL Patterns

### Case Information System
- **Main Portal**: https://appellatecases.courtinfo.ca.gov/
- **Search Page**: `https://appellatecases.courtinfo.ca.gov/search.cfm?dist={dist_code}`
- **Case Summary**: `https://appellatecases.courtinfo.ca.gov/search/case/mainCaseScreen.cfm?dist={dist_code}&doc_id={doc_id}&doc_no={case_number}`
- **Docket**: `https://appellatecases.courtinfo.ca.gov/search/case/dockets.cfm?dist={dist_code}&doc_id={doc_id}&doc_no={case_number}`

#### District Codes
| Court | Code |
|-------|------|
| Supreme Court | 0 |
| 1st District | 1 |
| 2nd District | 2 |
| 3rd District | 3 |
| 4th District Div 1 | 41 |
| 4th District Div 2 | 42 |
| 4th District Div 3 | 43 |
| 5th District | 5 |
| 6th District | 6 |

### Opinions

#### Published Opinions
- **List Page**: https://www.courts.ca.gov/opinions/publishedcitable-opinions
- **PDF Pattern**: `https://www.courts.ca.gov/opinions/documents/{case_number}.PDF`
- **Detail Page**: `https://courts.ca.gov/opinion/published/{date}/{case_number}`

#### Unpublished Opinions
- **List Page**: https://www.courts.ca.gov/opinions/unpublishednon-citable-opinions
- **PDF Pattern**: `https://www.courts.ca.gov/opinions/nonpub/{case_number}.PDF`
- **Detail Page**: `https://courts.ca.gov/opinion/unpublished/{date}/{case_number}`

#### Official Reports (Historical - 1850-Present)
- **LexisNexis Portal**: https://www.lexisnexis.com/clients/CACourts/
- Free searchable archive provided by LexisNexis

### Case Number Patterns
| Court | Pattern | Example |
|-------|---------|---------|
| Supreme Court | S{6 digits} | S275038 |
| 1st District | A{6 digits} | A160328 |
| 2nd District | B{6 digits} | B337904 |
| 3rd District | C{6 digits} | C102901 |
| 4th Dist Div 1 | D{6 digits} | D083172 |
| 4th Dist Div 2 | E{6 digits} | E086720 |
| 4th Dist Div 3 | G{6 digits} | G066061 |
| 5th District | F{6 digits} | F087827 |
| 6th District | H{6 digits} | H052538 |

Note: Case numbers may have letter suffixes (e.g., B337904A, B324360N, B324360M) indicating modifications or related documents.

---

## Current Justices - Supreme Court

### Chief Justice
- **Patricia Guerrero** (29th Chief Justice)
  - Sworn in: January 2, 2023
  - First Latina Chief Justice of California
  - Bio: https://supreme.courts.ca.gov/about-court/justices-court/chief-justice-patricia-guerrero

### Associate Justices
| Justice | Bio URL |
|---------|---------|
| Carol A. Corrigan | https://supreme.courts.ca.gov/about-court/justices-court/associate-justice-carol-corrigan |
| Goodwin H. Liu | https://supreme.courts.ca.gov/about-court/justices-court/associate-justice-goodwin-h-liu |
| Leondra R. Kruger | https://supreme.courts.ca.gov/about-court/justices-court/associate-justice-leondra-r-kruger |
| Joshua P. Groban | https://supreme.courts.ca.gov/about-court/justices-court/associate-justice-joshua-p-groban |
| Martin J. Jenkins | https://supreme.courts.ca.gov/about-court/justices-court/associate-justice-martin-j-jenkins |
| Kelli M. Evans | https://supreme.courts.ca.gov/about-court/justices-court/justice-kelli-m-evans |

---

## Opinion Types and Publication

### Published (Citable) Opinions
- All Supreme Court opinions are published
- Court of Appeal opinions may be certified for publication
- Must meet criteria in California Rules of Court, rule 8.1105
- Published in the Official Reports
- Slip opinions posted for 120 days on the opinions page
- After 120 days, available via Case Information Search

### Unpublished (Non-Citable) Opinions
- Majority of Court of Appeal opinions
- Cannot generally be cited (Cal. Rules of Court, rule 8.1115)
- Still public records
- Posted for 60 days on the opinions page
- After 60 days, available via Case Information Search

### Publication Schedule
- Supreme Court: 10:00 a.m. on Mondays and Thursdays
- Courts of Appeal: Throughout the day as filed

---

## Oral Arguments

### Supreme Court
- **Calendar**: https://supreme.courts.ca.gov/case-information/oral-arguments/oral-arguments-calendar
- **Webcast Library**: https://supreme.courts.ca.gov/case-information/oral-arguments/webcast-library
- **Briefs of Argued Cases**: https://supreme.courts.ca.gov/case-information/briefs-argued-cases
- Live and archived webcasts available
- Last 8 years of case information stored

---

## Docket Information

### Available Data Fields
From the Case Information System docket:
- Case Number
- Case Caption
- Case Category
- Start Date
- Case Status
- Issues
- Disposition Date
- Case Citation
- Cross-Referenced Cases
- Court of Appeal Case(s) (for Supreme Court cases)

### Docket Entries
- Date
- Description
- Notes (party info, attorney info, etc.)

---

## Access Restrictions

### No Login Required
- All opinion PDFs publicly accessible
- Case Information System is public
- No rate limiting observed during research

### Data Availability
- Slip opinions: Last 120 days (published), 60 days (unpublished) on opinions pages
- Older opinions: Via Case Information Search
- Official Reports archive (1850-present): Via LexisNexis (free)
- Case information: Updated hourly during business day

---

## Technical Implementation Notes

### API/Data Access
- No public API identified
- Web scraping required
- Case Information System uses ColdFusion (`.cfm` pages)
- Request tokens appear in URLs but session management seems minimal

### Search Capabilities
1. **By Case Number** (Supreme Court, Court of Appeal, or Trial Court)
2. **By Party** (Last Name/Organization required)
3. **By Attorney** (Last Name or Law Firm required)
4. **By Case Caption** (e.g., "Smith v. Jones")
5. **By Calendar Date** (Court of Appeal only)

### Opinion List Page Parameters
- Source filter (court selection)
- Case Number filter
- Title filter
- Pagination: 50, 100, or 200 per page

---

## Example Cases

### Supreme Court
- **S282937** - City of Gilroy v. Superior Court (1/15/26)
  - PDF: https://www.courts.ca.gov/opinions/documents/S282937.PDF
  - Case Info: https://appellatecases.courtinfo.ca.gov/search/searchResults.cfm?dist=0&search=number&useSession=0&query_caseNumber=S282937

### Court of Appeal (2nd District)
- **B337904** - Yeh v. Barrington Pacific (1/21/26)
  - PDF: https://www.courts.ca.gov/opinions/documents/B337904.PDF
  - Case Info: https://appellatecases.courtinfo.ca.gov/search/searchResults.cfm?dist=2&search=number&useSession=0&query_caseNumber=B337904

---

## Recommended Scraper Architecture

### Opinion Scrapers
1. **Published Opinions Scraper**
   - Source: https://www.courts.ca.gov/opinions/publishedcitable-opinions
   - Parse opinion list, extract case numbers, dates, courts
   - Download PDFs from document URL pattern

2. **Unpublished Opinions Scraper**
   - Source: https://www.courts.ca.gov/opinions/unpublishednon-citable-opinions
   - Similar structure to published opinions

### Case Information Scraper
1. **Case Summary Scraper**
   - Query by case number
   - Extract case metadata

2. **Docket Scraper**
   - Navigate to docket tab
   - Parse docket entry table

### Oral Arguments Scraper
1. **Calendar Scraper**
   - Source: https://supreme.courts.ca.gov/case-information/oral-arguments/oral-arguments-calendar

2. **Webcast Scraper**
   - Source: https://supreme.courts.ca.gov/case-information/oral-arguments/webcast-library
