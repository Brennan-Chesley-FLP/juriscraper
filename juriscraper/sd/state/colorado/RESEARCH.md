# Colorado Appellate Courts Research

## Court Structure

Colorado has a three-tier court system:

### 1. Supreme Court of Colorado
- **Website**: https://www.coloradojudicial.gov/supreme-court
- Highest court in Colorado
- 1 Chief Justice + 6 Associate Justices (7 total)
- Justices serve ten-year terms
- All opinions are binding on all other Colorado state courts
- Location: Ralph L. Carr Colorado Judicial Center, 2 East 14th Avenue, Denver, CO 80203
- Hours: Monday-Friday 8:00 a.m. - 4:30 p.m.

### 2. Court of Appeals
- **Website**: https://www.coloradojudicial.gov/court-appeals
- Intermediate appellate court
- 22 judges who serve eight-year terms
- Sits in three-member divisions to decide cases
- Chief Judge appointed by Chief Justice of the Supreme Court
- Location: Ralph L. Carr Colorado Judicial Center (1st, 3rd, and 4th floors)
- Hours: Monday-Friday 8:00 a.m. - 4:30 p.m.

### 3. Trial Courts
- 23 Judicial Districts across 64 counties
- District Courts (general jurisdiction)
- County Courts (limited jurisdiction)
- Water Courts (7 divisions)
- Not covered in this research (focus is on appellate courts)

---

## Key URLs and URL Patterns

### Main Portal
- **Colorado Judicial Branch**: https://www.coloradojudicial.gov/
- Note: www.courts.state.co.us redirects to coloradojudicial.gov

### Case Law Search (Opinions Database)
- **Main Portal**: https://research.coloradojudicial.gov/
- Powered by vLex
- Contains both Supreme Court and Court of Appeals opinions
- **Supreme Court Search**: `https://research.coloradojudicial.gov/search/jurisdiction:US+content_type:2+court:14024_01/*`
- **Court of Appeals Search**: `https://research.coloradojudicial.gov/search/jurisdiction:US+content_type:2+court:14024_02/*`
- **Opinion Detail**: `https://research.coloradojudicial.gov/en/vid/{vlex_id}`

### Opinions (Slip Opinions)
- **Supreme Court Opinions Page**: https://www.coloradojudicial.gov/supreme-court/opinions
- **Opinion Detail Page**: `https://www.coloradojudicial.gov/node/{node_id}`
- **Opinion PDF Pattern**: `https://www.coloradojudicial.gov/system/files/opinions-{year}-{month}/{case_number}.pdf`
  - Example: `https://www.coloradojudicial.gov/system/files/opinions-2025-12/23SC847.pdf`

### Docket Search (Trial Courts)
- **Docket Search**: https://www.coloradojudicial.gov/dockets
- Searches by judicial district, county, case number, party name, or attorney
- Trial court dockets only (not appellate)

### Oral Arguments
- **Livestream Portal**: https://www.coloradojudicial.gov/court-appeals/live
- **Live Stream**: https://live.coloradojudicial.gov/
- **Archive Portal**: https://portal.live.coloradojudicial.gov/archive/
- Case Locator allows searching by Supreme Court or Court of Appeals case number

### Case Number Patterns

| Court | Pattern | Example |
|-------|---------|---------|
| Supreme Court | {YY}SC{sequence} | 25SC347, 23SC847 |
| Supreme Court (Original) | {YY}SA{sequence} | 25SA204, 25SA179 |
| Court of Appeals | {YY}CA{sequence} | 24CA1951, 22CA1504 |

### Citation Patterns

| Court | Pattern | Example |
|-------|---------|---------|
| Supreme Court | {Year} CO {sequence} | 2025 CO 63 |
| Supreme Court (Modified) | {Year} CO {sequence}M | 2025 CO 60M |
| Court of Appeals Published | {Year} COA {sequence} | 2025 COA 1 |

---

## Current Justices - Supreme Court

### Chief Justice
| Name | Title | Appointed | Bio URL |
|------|-------|-----------|---------|
| Monica M. Márquez | Chief Justice | 2010 (Justice), July 2024 (Chief) | https://www.coloradojudicial.gov/contact/monica-m-marquez |

### Associate Justices
| Name | Bio URL |
|------|---------|
| Brian D. Boatright | https://www.coloradojudicial.gov/contact/brian-d-boatright |
| William W. Hood, III | https://www.coloradojudicial.gov/contact/william-w-hood-iii |
| Richard L. Gabriel | https://www.coloradojudicial.gov/contact/richard-l-gabriel |
| Carlos A. Samour, Jr. | https://www.coloradojudicial.gov/contact/carlos-samour-jr |
| Maria E. Berkenkotter | https://www.coloradojudicial.gov/contact/maria-e-berkenkotter |

Note: One seat appears to be vacant (Melissa Hart retired per photo caption)

### Clerk of the Supreme Court
- Cheryl L. Stevens

---

## Current Judges - Court of Appeals

### Chief Judge
| Name | Liaison District | Bio URL |
|------|------------------|---------|
| Gilbert M. Román | 9th Judicial District | https://www.coloradojudicial.gov/contact/gilbert-m-roman |

### Judges (21 total)
| Name | Liaison District | Bio URL |
|------|------------------|---------|
| Jerry N. Jones | 7th | https://www.coloradojudicial.gov/contact/jerry-n-jones |
| Terry Fox | 5th | https://www.coloradojudicial.gov/contact/terry-fox |
| Stephanie Dunn | 8th | https://www.coloradojudicial.gov/contact/stephanie-dunn |
| Elizabeth L. Harris | 2nd | https://www.coloradojudicial.gov/contact/elizabeth-l-harris |
| Rebecca R. Freyre | 4th | https://www.coloradojudicial.gov/contact/rebecca-r-freyre |
| Craig R. Welling | 20th | https://www.coloradojudicial.gov/contact/craig-r-welling |
| Ted C. Tow III | 17th | https://www.coloradojudicial.gov/contact/ted-c-tow-iii |
| Lino S. Lipinsky de Orlov | 14th | https://www.coloradojudicial.gov/contact/lino-s-lipinsky-de-orlov |
| Matthew D. Grove | 3rd | https://www.coloradojudicial.gov/contact/matthew-d-grove |
| Neeti V. Pawar | 19th | https://www.coloradojudicial.gov/contact/neeti-v-pawar |
| Jaclyn Casey Brown | 11th | https://www.coloradojudicial.gov/contact/jaclyn-casey-brown |
| Sueanna P. Johnson | 1st | https://www.coloradojudicial.gov/contact/sueanna-p-johnson |
| Christina F. Gomez | 12th | https://www.coloradojudicial.gov/contact/christina-f-gomez |
| David H. Yun | 18th | https://www.coloradojudicial.gov/contact/david-h-yun |
| W. Eric Kuhn | 6th | https://www.coloradojudicial.gov/contact/w-eric-kuhn |
| Timothy J. Schutz | 22nd | https://www.coloradojudicial.gov/contact/timothy-j-schutz |
| Karl L. Schock | 16th | https://www.coloradojudicial.gov/contact/karl-l-schock |
| Katharine E. Lum | 15th | https://www.coloradojudicial.gov/contact/katharine-e-lum |
| Pax L. Moultrie | 13th | https://www.coloradojudicial.gov/contact/pax-l-moultrie |
| Grant T. Sullivan | 21st | https://www.coloradojudicial.gov/contact/grant-t-sullivan |
| Melissa C. Meirink | 10th | https://www.coloradojudicial.gov/contact/melissa-c-meirink |

### Clerk of the Court of Appeals
- Tiffany Mortier

---

## Opinion Types and Publication

### Supreme Court Opinions
- All Supreme Court opinions are published and citable
- Slip opinions are subject to modification, rehearing, withdrawal, or clerical corrections
- Citation format: {Year} CO {sequence} (e.g., 2025 CO 63)
- Modified opinions use "M" suffix (e.g., 2025 CO 60M)

### Court of Appeals Opinions
- **Published opinions**: Citable, available on research.coloradojudicial.gov
- **Unpublished opinions**:
  - Generally not citable except to explain case history, law of the case, or issue/claim preclusion
  - Exception: Opinions between January 1, 1970 and November 1, 1975 may be cited
- Database contains 96,530 Court of Appeals opinions and 33,171 Supreme Court opinions

### Publication Schedule
- Opinions posted as decided
- Slip opinions page shows current fiscal year (July 1 through June 30)
- Archived opinions available via Colorado Case Law Search

---

## Oral Arguments

### Supreme Court
- **Calendar/Info**: https://www.coloradojudicial.gov/supreme-court/supreme-court-oral-arguments
- Open to public in person at Ralph L. Carr Judicial Center
- Available via livestream and archives

### Court of Appeals
- **Calendar/Info**: https://www.coloradojudicial.gov/topic/77/court-appeals-oral-arguments
- Held at Ralph Carr Building unless remote order issued
- Available via livestream and archives at https://portal.live.coloradojudicial.gov/archive/

---

## Docket Information

### Appellate Dockets
- Not directly available through coloradojudicial.gov docket search (that's for trial courts)
- Case information available through:
  - Colorado Case Law Search (research.coloradojudicial.gov)
  - Oral Arguments Archive (portal.live.coloradojudicial.gov)

### Trial Court Docket Search
Available fields at https://www.coloradojudicial.gov/dockets:
- Judicial District (1-23)
- County (64 counties)
- Courthouse
- Court Type (County/District)
- Division
- Date Range
- Case Number (Year, Class, Sequence)
- Party Name (Individual/Business)
- Attorney Name/Bar Number

Case Classes:
- C, CR (Criminal)
- CV (Civil)
- CW (County/Civil)
- DR (Domestic Relations)
- JD, JV (Juvenile)
- M (Misdemeanor)
- PR (Probate)
- R, S, T (Various)

---

## Access Restrictions

### No Login Required
- All opinion PDFs publicly accessible
- Colorado Case Law Search is public
- Oral argument archives are public
- No rate limiting observed during research

### Data Availability
- Slip opinions: Current fiscal year on opinions page
- Historical opinions: Via Colorado Case Law Search (research.coloradojudicial.gov)
- Oral arguments: Live stream and archives available

---

## Technical Implementation Notes

### Website Platform
- Main site (coloradojudicial.gov) appears to be Drupal-based
- URLs use `/node/{id}` pattern for content pages
- Case Law Search powered by vLex

### API/Data Access
- No public API identified
- Web scraping required for most data
- vLex-powered search may have API capabilities (not explored)

### Search Capabilities on Case Law Search
1. **Full-text search** across opinion content
2. **Court filter** (Supreme Court or Court of Appeals)
3. **Publication Status filter** (Published/Unpublished)
4. **Date filter** (exact or range)
5. **Results sorted by date** (most recent first)

---

## Example Cases

### Supreme Court
- **25SC347** - Jones v. People (Jan 20, 2026)
  - Case Law Search: https://research.coloradojudicial.gov/en/vid/1103023863

- **23SC847** - People v. Kennedy (Dec 15, 2025)
  - Opinion Page: https://www.coloradojudicial.gov/node/15390
  - PDF: https://www.coloradojudicial.gov/system/files/opinions-2025-12/23SC847.pdf

### Court of Appeals
- **24CA1951** - People v. Peters (Jan 14, 2026)
  - Oral argument available in archive

---

## Recommended Scraper Architecture

### Opinion Scrapers

1. **Colorado Case Law Search Scraper** (Primary)
   - Source: https://research.coloradojudicial.gov/
   - Search by court, date range, publication status
   - Extract case metadata (title, docket number, date, citation)
   - Note: vLex platform - may need to handle JavaScript rendering

2. **Slip Opinions Scraper** (Supplemental)
   - Source: https://www.coloradojudicial.gov/supreme-court/opinions
   - Parse opinions list by date
   - Extract node IDs and PDF URLs
   - Download PDFs from `/system/files/` pattern

### Oral Arguments Scraper
1. **Archive Scraper**
   - Source: https://portal.live.coloradojudicial.gov/archive/
   - Search by case number
   - Extract video links and case metadata

### Considerations
- The vLex-powered Case Law Search is likely the best source for comprehensive opinion data
- Slip opinions page useful for most recent opinions before they appear in vLex
- Consider using both sources for completeness
