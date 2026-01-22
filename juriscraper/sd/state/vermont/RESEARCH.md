# Vermont Courts Research

## Court Structure

Vermont has a unified judicial system with one appellate court (the Supreme Court) and a trial court system (Vermont Superior Court). Notably, Vermont does **not** have an intermediate Court of Appeals - the Supreme Court is the only appellate court.

### 1. Vermont Supreme Court
- **Website**: https://www.vermontjudiciary.org/supreme-court
- Highest and only appellate court in Vermont (court of last resort)
- 5 Justices serving 6-year terms
- Chief Justice and four Associate Justices
- Location: Montpelier, Vermont

#### Jurisdiction
- Appeals from decisions made by state courts
- Appeals from some decisions made by state and municipal agencies
- Adopts rules of procedure for civil, criminal, family, probate, environmental, and appellate cases
- Oversees management of statewide court system
- Oversees admission of attorneys to practice law
- Oversees discipline of judicial officers and attorneys

#### Schedule
- Opinions issued on **Fridays** by 11 a.m. EST/EDT
- Full-Court hearings: Held in person at Vermont Supreme Court
- Three-Justice panel hearings: Conducted remotely via video/telephone
- All hearings livestreamed on YouTube

### 2. Vermont Superior Court (Trial Court)
- **Website**: https://www.vermontjudiciary.org/court-divisions
- Unified trial court with 14 units (one per county)
- Five divisions:
  - **Civil Division** - General civil cases
  - **Criminal Division** - Criminal cases
  - **Environmental Division** - Environmental and land use cases
  - **Family Division** - Domestic relations, juvenile matters
  - **Probate Division** - Estates, guardianships, trusts
- **Judicial Bureau** - Statewide jurisdiction for traffic/civil violations

---

## Key URLs and URL Patterns

### Main Portal
- **Vermont Judiciary Home**: https://www.vermontjudiciary.org/
- **Public Portal (Case Search)**: https://portal.vtcourts.gov/Portal

### Supreme Court Opinions and Decisions
- **Supreme Court Main Page**: https://www.vermontjudiciary.org/supreme-court
- **Published Opinions and Entry Orders**: https://www.vermontjudiciary.org/supreme-court/published-opinions-and-entry-orders
- **Unpublished Entry Orders**: https://www.vermontjudiciary.org/supreme-court/unpublished-entry-orders
- **Opinions Search (All Courts)**: https://www.vermontjudiciary.org/opinions-decisions

#### Opinion Search URL Pattern
```
https://www.vermontjudiciary.org/opinions-decisions?f[0]=court_division_opinions_library:7&search_api_fulltext={query}&facet_from_date={start_date}&facet_to_date={end_date}&page={page_number}
```
- `court_division_opinions_library:7` = Supreme Court filter
- Pagination: `page=0`, `page=1`, etc.

#### Individual Opinion Document URL Pattern
```
https://www.vermontjudiciary.org/media/{document_id}
```
Example: https://www.vermontjudiciary.org/media/19728

### Oral Arguments
- **Audio Recordings of Oral Arguments**: https://www.vermontjudiciary.org/supreme-court/audio-recordings-oral-arguments
- **YouTube Channel (Livestream and Archive)**: https://www.youtube.com/channel/UCx5naSorUsDA-rgrF1_SGkw/videos
- Audio recordings available from 2019-present on website
- Livestream for both full-court and three-justice panel hearings

### Court Calendar
- **Supreme Court Calendar**: https://www.vermontjudiciary.org/supreme-court/supreme-court-calendar
- Calendar PDFs linked from this page

### Case Search (Public Portal)
- **Public Portal Home**: https://portal.vtcourts.gov/Portal
- **Smart Search**: https://portal.vtcourts.gov/Portal/Home/Dashboard/29
- Tyler Technologies Odyssey-based system (Version 2017.1.61.2)

### Judge/Justice Biographies
- **Contact Directory**: https://www.vermontjudiciary.org/people
- Individual bio URL pattern: `https://www.vermontjudiciary.org/people/{slug}`

---

## Current Justices - Vermont Supreme Court

| Position | Name | Appointed | Bio URL |
|----------|------|-----------|---------|
| Chief Justice | Paul L. Reiber | October 2003 (by Gov. James Douglas); Chief Justice December 17, 2004 | https://www.vermontjudiciary.org/people/honorable-paul-l-reiber |
| Associate Justice | Harold E. Eaton, Jr. | October 27, 2014 (by Gov. Peter Shumlin) | https://www.vermontjudiciary.org/people/honorable-harold-e-eaton-jr |
| Associate Justice | Nancy J. Waples | April 15, 2022 (by Gov. Phil Scott) | https://www.vermontjudiciary.org/people/honorable-nancy-jear-waples |
| Associate Justice (pending) | Christina Nolan | January 5, 2026 (by Gov. Phil Scott) - Not yet sworn in | - |
| Associate Justice (pending) | Michael Drescher | January 5, 2026 (by Gov. Phil Scott) - Not yet sworn in | - |

**Note**: As of January 2026, two new justices (Christina Nolan and Michael Drescher) have been appointed but not yet sworn in.

---

## Opinion Types and Document Categories

### Supreme Court
- **Published Opinions**: Full written opinions with precedential value, included in Vermont Reports
- **Published Entry Orders/Memorandum Decisions**: Shorter decisions with precedential value, also in Vermont Reports
- **Unpublished Entry Orders**: Three-justice panel decisions, not included in Vermont Reports, not precedential
  - Usually issued within 48 hours of argument
  - Oral argument limited to 5 minutes per side

### Decision Classification
- **Full Court Cases** (5 Justices):
  - More complex issues
  - 30-minute oral argument (15 per side)
  - In-person hearings
  - Result in published opinions or entry orders

- **Three-Justice Panel Cases**:
  - Settled law, fewer issues
  - 5-minute oral argument per side
  - Remote hearings (video/telephone)
  - Unanimous decision required
  - Result in unpublished entry orders (non-precedential)

---

## Case Number Formats

Based on observed patterns:
- **Supreme Court Appeals**: `YY-AP-NNN` (e.g., `25-AP-042`, `24-AP-320`)
  - YY = Two-digit year filed
  - AP = Appeal designation
  - NNN = Sequential number

- **Citation Format**: `YYYY VT NN` (e.g., `2025 VT 68`, `2025 VT 1`)
  - YYYY = Year of decision
  - VT = Vermont designation
  - NN = Sequential opinion number for that year

- **Civil Division**: `YY-cv-NNNN` (e.g., `25-cv-3918`)
- **Environmental Division**: `YY-ENV-NNNNN` (e.g., `25-ENV-00066`)

---

## Data Availability

| Content | Date Range | Source |
|---------|------------|--------|
| Published Opinions & Entry Orders | 1999 - present | https://www.vermontjudiciary.org/supreme-court/published-opinions-and-entry-orders |
| Unpublished Entry Orders | 2001 - present | https://www.vermontjudiciary.org/supreme-court/unpublished-entry-orders |
| Oral Argument Audio | 2019 - present | https://www.vermontjudiciary.org/supreme-court/audio-recordings-oral-arguments |
| Oral Argument Video (YouTube) | Various | https://www.youtube.com/channel/UCx5naSorUsDA-rgrF1_SGkw |
| All Opinions/Decisions Library | Extensive | https://www.vermontjudiciary.org/opinions-decisions |

---

## Access Restrictions

### No Login Required
- All published and unpublished Supreme Court decisions
- Opinion search and browse functionality
- Oral argument audio recordings
- Court calendars
- Judge biographies
- News and announcements

### Public Portal (Limited Access)
- **Anonymous Users**: Can view case summaries for Civil Division and Judicial Bureau cases remotely
- **Other Case Types** (criminal, family, probate): Only available at courthouse public access terminals
- **Elevated Access**: Case parties, attorneys, and some public agency personnel can register for enhanced access

### Registration Requirements
- Two-step process for elevated access:
  1. Register for account and verify email
  2. Request elevated access via "Request Access" link

### Technical Notes
- Pop-up blockers should be disabled for Public Portal
- Safari browser not recommended for Public Portal
- Parties' home addresses hidden from case summary pages (as of 8/2/23)

---

## Technical Implementation Notes

### Website Architecture
- **Main Site**: www.vermontjudiciary.org (Drupal-based CMS)
- **Public Portal**: portal.vtcourts.gov (Tyler Technologies Odyssey ePortal)
- **eFiling**: vermont.tylertech.cloud/OfsWeb (Odyssey File & Serve)

### Opinion Format
- Opinions provided as downloadable PDF documents
- Accessed via `/media/{document_id}` URLs
- Search functionality with date range filtering, court division, and document type filters

### Data Structure
The opinions search page returns:
- Case name (linked to document)
- Date of decision
- Court division
- Docket number

### Accordion-Style Navigation
- Year-by-year browsing uses accordion/collapsible sections
- JavaScript-driven content expansion
- Direct year access may require clicking to expand

### Session Management
- Public Portal sessions idle after 30 minutes
- Session warnings displayed via JavaScript

---

## Social Media & Other Resources

- **Facebook**: https://www.facebook.com/VTCourts/
- **Twitter**: https://twitter.com/VermontCourts
- **YouTube**: https://www.youtube.com/channel/UCx5naSorUsDA-rgrF1_SGkw

---

## Example Cases

### Recent Supreme Court Opinions (2025)
| Case Name | Docket # | Citation | Date |
|-----------|----------|----------|------|
| Christopher Gade v. Erin Gade | 25-AP-042 | 2025 VT 68 | 12/26/2025 |
| State v. Anna Sylvester | 24-AP-320 | 2025 VT 69 | 12/19/2025 |
| State v. John R. Lyddy II | 23-AP-303 | 2025 VT 1 | 1/3/2025 |

---

## Example API/Scraping URLs

```
# Published Opinions Main Page
GET https://www.vermontjudiciary.org/supreme-court/published-opinions-and-entry-orders

# Unpublished Entry Orders Main Page
GET https://www.vermontjudiciary.org/supreme-court/unpublished-entry-orders

# Opinions Search with Supreme Court Filter
GET https://www.vermontjudiciary.org/opinions-decisions?f[0]=court_division_opinions_library:7

# Opinions Search with Pagination
GET https://www.vermontjudiciary.org/opinions-decisions?f[0]=court_division_opinions_library:7&page=1

# Individual Opinion Document
GET https://www.vermontjudiciary.org/media/19728

# Audio Recordings of Oral Arguments
GET https://www.vermontjudiciary.org/supreme-court/audio-recordings-oral-arguments

# Supreme Court Calendar
GET https://www.vermontjudiciary.org/supreme-court/supreme-court-calendar

# Justice Biography
GET https://www.vermontjudiciary.org/people/honorable-paul-l-reiber

# Public Portal Smart Search
GET https://portal.vtcourts.gov/Portal/Home/Dashboard/29
```

---

## Notes

1. **No Intermediate Appellate Court**: Vermont is one of the few states without an intermediate Court of Appeals. All appeals go directly to the Supreme Court.

2. **Unified Court System**: Vermont operates a unified judicial system, meaning all courts operate under the administrative direction of the Supreme Court.

3. **Retention System**: Justices are appointed by the Governor from candidates prepared by the Judicial Nominating Board, confirmed by the Senate for 6-year terms, and subject to General Assembly retention votes.

4. **Three-Justice Panels**: Unlike most states, Vermont uses three-justice panels for certain categories of cases to manage caseload efficiently. These panels must reach unanimous decisions.

5. **Modern Digital Infrastructure**: The court system uses Tyler Technologies Odyssey platform for case management and public access, with good online accessibility for opinions.

6. **Opinion Release Schedule**: Consistent Friday release schedule at 11 a.m. makes scraping predictable.

7. **Comprehensive Archive**: Opinions available back to 1999 for published decisions and 2001 for unpublished entry orders.

8. **YouTube Integration**: All oral arguments are livestreamed on YouTube, providing accessible public records.

9. **14 County Units**: Vermont Superior Court has 14 geographic units corresponding to the state's 14 counties: Addison, Bennington, Caledonia, Chittenden, Essex, Franklin, Grand Isle, Lamoille, Orange, Orleans, Rutland, Washington, Windham, and Windsor.

10. **Environmental Division**: Vermont has a dedicated Environmental Division for land use and environmental cases, reflecting the state's strong environmental focus.
