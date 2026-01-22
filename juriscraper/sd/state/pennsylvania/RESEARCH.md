# Pennsylvania Courts Research

## Court Structure

Pennsylvania has a unified judicial system with three levels of appellate courts:

### 1. Supreme Court of Pennsylvania
- **Website**: https://www.pacourts.us/courts/supreme-court
- Highest court in Pennsylvania
- 7 Justices (1 Chief Justice + 6 Associate Justices)
- Justices are elected statewide to 10-year terms (retention election after initial term)
- Sits in Philadelphia, Harrisburg, and Pittsburgh on a rotating basis

#### Jurisdiction
- Final appellate jurisdiction over all Pennsylvania courts
- Exclusive jurisdiction over appeals involving:
  - Death penalty cases
  - Legislative reapportionment
  - Constitutional questions
- Discretionary review via Petition for Allowance of Appeal
- Administrative supervision of all Pennsylvania courts

### 2. Superior Court of Pennsylvania
- **Website**: https://www.pacourts.us/courts/superior-court
- Intermediate appellate court (established 1895)
- 15 Judges (1 President Judge + 14 Judges + Senior Judges)
- Judges elected statewide to 10-year terms
- Sits in panels of 3 judges, with en banc review available
- Offices in Philadelphia, Harrisburg, and Pittsburgh

#### Jurisdiction
- Appeals from Courts of Common Pleas in:
  - Civil cases
  - Criminal cases (non-death penalty)
  - Family law matters
  - Domestic relations cases
- Largest appellate court by caseload in Pennsylvania

### 3. Commonwealth Court of Pennsylvania
- **Website**: https://www.pacourts.us/courts/commonwealth-court
- Specialized intermediate appellate court (established 1970)
- 9 Judges (1 President Judge + 8 Judges + Senior Judges)
- Judges elected statewide to 10-year terms
- Based in Harrisburg with sessions also in Philadelphia and Pittsburgh

#### Jurisdiction
- Original jurisdiction in civil actions by or against the Commonwealth
- Appeals from state agencies
- Actions involving:
  - Election law
  - Eminent domain
  - Local government
  - Tax matters
  - Workers' compensation
  - Environmental law

### 4. Courts of Common Pleas (Trial Courts)
- 60 judicial districts (coterminous with 67 counties)
- General jurisdiction trial courts
- **Directory**: https://www.pacourts.us/courts/courts-of-common-pleas

---

## Key URLs and URL Patterns

### Main Portal
- **Unified Judicial System Home**: https://www.pacourts.us/
- **Courts Overview**: https://www.pacourts.us/courts
- **Supreme Court**: https://www.pacourts.us/courts/supreme-court
- **Superior Court**: https://www.pacourts.us/courts/superior-court
- **Commonwealth Court**: https://www.pacourts.us/courts/commonwealth-court

### Opinion Pages
- **All Appellate Court Opinions Search**: https://www.pacourts.us/courts/supreme-court/court-opinions/
- **Supreme Court Opinions**: https://www.pacourts.us/courts/supreme-court/court-opinions/ (select "Supreme Court" filter)
- **Superior Court Opinions**: https://www.pacourts.us/courts/superior-court/court-opinions
- **Commonwealth Court Opinions**: https://www.pacourts.us/courts/commonwealth-court/court-opinions
- **RSS Feed - Supreme Court**: https://www.pacourts.us/Rss/Opinions/Supreme/
- **RSS Feed - Superior Court**: https://www.pacourts.us/Rss/Opinions/Superior/
- **RSS Feed - Commonwealth Court**: https://www.pacourts.us/Rss/Opinions/Commonwealth/

### Case Management System (UJS Web Portal)
- **Portal Home**: https://ujsportal.pacourts.us/
- **Case Information**: https://ujsportal.pacourts.us/Home/CaseInformation
- **Case Search**: https://ujsportal.pacourts.us/CaseSearch
- **E-Filing (PACFile)**: https://ujsportal.pacourts.us/PACFile/Overview

### Docket Sheets
- **Docket Sheets Overview**: https://ujsportal.pacourts.us/Home/CaseInformation
- **Supreme Court Docket Sheets**: https://www.pacourts.us/courts/supreme-court/docket-sheets
- **Superior Court Docket Sheets**: https://www.pacourts.us/courts/superior-court/docket-sheets
- **Commonwealth Court Docket Sheets**: https://www.pacourts.us/courts/commonwealth-court/docket-sheets

### Justices and Judges
- **Supreme Court Justices**: https://www.pacourts.us/courts/supreme-court/supreme-court-justices
- **Superior Court Judges**: https://www.pacourts.us/courts/superior-court/superior-court-judges
- **Commonwealth Court Judges**: https://www.pacourts.us/courts/commonwealth-court-judges

### Oral Arguments / Calendar
- **Supreme Court Calendar**: https://www.pacourts.us/courts/supreme-court/calendar
- **Superior Court Calendar**: https://www.pacourts.us/courts/superior-court/calendar
- **Commonwealth Court Calendar**: https://www.pacourts.us/courts/commonwealth-court/calendar
- **Appellate Court Livestream**: Linked from homepage sidebar

---

## Opinion URL Patterns

### Opinion Search Page
The unified opinion search at https://www.pacourts.us/courts/supreme-court/court-opinions/ provides:
- Court type filter (Supreme Court, Superior Court, Commonwealth Court, Disciplinary Board)
- Full-text search within opinions
- Filter by posting type (Majority Opinion, Per Curiam Order, Concurring Opinion, etc.)
- Filter by caption, author, date range, month/year
- Sorting by date (most recent to oldest or vice versa)

### Direct Opinion PDF URL Pattern
```
https://www.pacourts.us/assets/opinions/{Court}/out/{filename}.pdf?cb={cache_buster}
```
Where:
- `{Court}` = "Supreme", "Superior", "Commonwealth"
- `{filename}` = Opinion identifier (e.g., "J-86-2025mo", "167WAL2025 - 106651033344041265")
- `?cb=1` = Cache buster parameter

#### Example URLs
```
# Supreme Court Majority Opinion
https://www.pacourts.us/assets/opinions/Supreme/out/J-86-2025mo - 106651291344073938.pdf?cb=1

# Supreme Court Petition for Allowance of Appeal
https://www.pacourts.us/assets/opinions/Supreme/out/167WAL2025 - 106651033344041265.pdf?cb=1

# Per Curiam Order
https://www.pacourts.us/assets/opinions/Supreme/out/Order Entered - 106651498344099266.pdf?cb=1
```

### RSS Feed Pattern
```
https://www.pacourts.us/Rss/Opinions/{Court}/
```
Where `{Court}` = "Supreme", "Superior", "Commonwealth"

---

## Case Docket URL Patterns

### UJS Web Portal Case Search
```
https://ujsportal.pacourts.us/CaseSearch
```

### Search Options
The case search supports multiple search types:
- Appellate
- Attorney
- Calendar Event
- Citation Number
- Complaint Number
- Date Filed
- Docket Number
- Incident Number
- Organization
- OTN (Offense Tracking Number)
- Parcel
- Participant Name
- SID (State ID Number)

### Appellate Search Parameters
When searching by "Appellate", available filters include:
- Court Name (Supreme Court, Superior Court, Commonwealth Court)
- District
- Docket Type
- Case Category
- Case Type
- Party Name (Last, First)
- Attorney Name (Last, First)
- Filed Date Range

### Case Number Format
- **Supreme Court**: `{Number} {District} {Year}` format
  - Examples: `167 WAL 2025`, `385 MAL 2025`, `95 MAP 2024`
  - Districts: WAL (Western), MAL (Middle), EAL (Eastern)
  - Docket Types: MAP (Appeal), MAL (Allowance), etc.
- **Superior Court**: Similar format with different docket types
- **Commonwealth Court**: Similar format

---

## Current Justices - Supreme Court

| Position | Name | Term | Bio URL |
|----------|------|------|---------|
| Chief Justice | Hon. Debra Todd | January 2018 - December 2027 | https://www.pacourts.us/courts/supreme-court/supreme-court-justices/justice-debra-todd |
| Justice | Hon. Christine Donohue | | https://www.pacourts.us/courts/supreme-court/supreme-court-justices/justice-christine-donohue |
| Justice | Hon. Kevin M. Dougherty | | https://www.pacourts.us/courts/supreme-court/supreme-court-justices/justice-kevin-m-dougherty |
| Justice | Hon. David N. Wecht | | https://www.pacourts.us/courts/supreme-court/supreme-court-justices/justice-david-n-wecht |
| Justice | Hon. Sallie Updyke Mundy | | https://www.pacourts.us/courts/supreme-court/supreme-court-justices/judge-sallie-updyke-mundy |
| Justice | Hon. P. Kevin Brobson | | https://www.pacourts.us/courts/supreme-court/supreme-court-justices/judge-p-kevin-brobson |
| Justice | Hon. Daniel D. McCaffery | | https://www.pacourts.us/courts/supreme-court/supreme-court-justices/justice-daniel-d-mccaffery |

---

## Current Judges - Superior Court

| Position | Name | Bio URL |
|----------|------|---------|
| President Judge | Hon. Anne E. Lazarus | https://www.pacourts.us/courts/superior-court/superior-court-judges |
| President Judge Emeritus | Hon. Jack A. Panella | https://www.pacourts.us/courts/superior-court/superior-court-judges |
| Judge | Hon. Mary Jane Bowes | https://www.pacourts.us/courts/superior-court/superior-court-judges |
| Judge | Hon. Judith Ference Olson | https://www.pacourts.us/courts/superior-court/superior-court-judges |
| Judge | Hon. Victor P. Stabile | https://www.pacourts.us/courts/superior-court/superior-court-judges |
| Judge | Hon. Alice Beck Dubow | https://www.pacourts.us/courts/superior-court/superior-court-judges |
| Judge | Hon. Deborah A. Kunselman | https://www.pacourts.us/courts/superior-court/superior-court-judges |
| Judge | Hon. Carolyn H. Nichols | https://www.pacourts.us/courts/superior-court/superior-court-judges |
| Judge | Hon. Mary P. Murray | https://www.pacourts.us/courts/superior-court/superior-court-judges |
| Judge | Hon. Maria McLaughlin | https://www.pacourts.us/courts/superior-court/superior-court-judges |
| Judge | Hon. Megan McCarthy King | https://www.pacourts.us/courts/superior-court/superior-court-judges |
| Judge | Hon. Megan Sullivan | https://www.pacourts.us/courts/superior-court/superior-court-judges |
| Judge | Hon. Jill Beck | https://www.pacourts.us/courts/superior-court/superior-court-judges |
| Judge | Hon. Timika Lane | https://www.pacourts.us/courts/superior-court/superior-court-judges |

### Senior Judges (Superior Court)
- President Judge Emeritus Hon. Correale F. Stevens
- President Judge Emeritus Hon. John T. Bender
- President Judge Emerita Hon. Kate Ford Elliott

---

## Current Judges - Commonwealth Court

| Position | Name | Bio URL |
|----------|------|---------|
| President Judge | Hon. Renée Cohn Jubelirer | https://www.pacourts.us/courts/commonwealth-court-judges |
| Judge | Hon. Patricia A. McCullough | https://www.pacourts.us/courts/commonwealth-court-judges |
| Judge | Hon. Anne E. Covey | https://www.pacourts.us/courts/commonwealth-court-judges |
| Judge | Hon. Michael H. Wojcik | https://www.pacourts.us/courts/commonwealth-court-judges |
| Judge | Hon. Christine Fizzano Cannon | https://www.pacourts.us/courts/commonwealth-court-judges |
| Judge | Hon. Lori A. Dumas | https://www.pacourts.us/courts/commonwealth-court-judges |
| Judge | Hon. Stacy Wallace | https://www.pacourts.us/courts/commonwealth-court-judges |
| Judge | Hon. Matthew S. Wolf | https://www.pacourts.us/courts/commonwealth-court-judges |

### Senior Judges (Commonwealth Court)
- President Judge Emerita Hon. Bonnie Brigance Leadbetter
- President Judge Emerita Hon. Mary Hannah Leavitt

---

## Opinion Types and Posting Categories

### Supreme Court Posting Types
- Majority Opinion
- Per Curiam Order
- Affirmance, Evenly Divided Court
- Evenly Divided Court, Reversal
- Concurring Opinion
- Concurring Statement
- Concurring and Dissenting Opinion
- Concurring and Dissenting Statement
- Dissenting Opinion
- Dissenting Statement
- Appointment
- Argument List
- Court Calendar
- Dismissal, Evenly Divided Court
- Disciplinary Order
- Opinion Announcing the Judgment of the Court
- Petitions for Allowance of Appeal
- Rules
- Summary Disposition
- Miscellaneous
- Other
- Downlist - List of Opinions

### Publication Status
- All opinions posted to the court website are considered published
- Both majority and dissenting/concurring opinions are posted

---

## Access Restrictions

### No Login Required
- Opinion search and viewing on pacourts.us
- Opinion PDF downloads
- Justice/judge biographies
- Court calendars and argument lists
- RSS feeds
- UJS Portal public case search (basic information)

### Login Required
- UJS Portal secure docket sheets (additional content)
- PACFile e-filing system
- Secure calendar schedules

### Mobile App
- **PAeDocket**: Free app for searching court cases/dockets
- Available on iOS App Store

---

## Oral Arguments

### Calendar and Sessions
The Supreme Court holds oral argument sessions throughout the year in three locations:
- Philadelphia
- Harrisburg
- Pittsburgh

### 2026 Sessions
| Dates | Location | Notes |
|-------|----------|-------|
| Jan. 27 | Philadelphia | Administrative Session |
| March 9-13 | Philadelphia | Argument Session |
| March 24 | Harrisburg | Administrative Session |
| April 13-17 | Pittsburgh | Argument Session |
| May 18-22 | Harrisburg | Argument Session |
| June 2 | Pittsburgh | Administrative Session |
| Sept. 14-18 | Philadelphia | Argument Session |
| Oct. 14-16 | Pittsburgh | Argument Session |
| Nov. 16-20 | Harrisburg | Argument Session |

### Argument Lists
Argument lists are posted as PDFs before each session:
```
https://www.pacourts.us/assets/opinions/Supreme/out/{Month}{Year}ArgumentList.pdf
```
Example: https://www.pacourts.us/assets/opinions/Supreme/out/March2026ArgumentList.pdf

### Livestreaming
- Appellate court sessions are livestreamed
- Link available from the pacourts.us homepage sidebar

---

## Technical Implementation Notes

### Website Architecture
- **Primary Domain**: www.pacourts.us (main court information site)
- **Portal Domain**: ujsportal.pacourts.us (case search, e-filing, payments)
- Both sites use modern web frameworks with JavaScript-heavy interfaces

### Opinion Search System
The opinion search is a web application with:
- Dynamic filtering via dropdowns and checkboxes
- Date range picker with calendar widget
- Text search within opinion content
- Pagination of results
- Sort order toggle (most recent to oldest / oldest to most recent)

### Data Availability by Date Range
- **Opinion search**: Data available from 1998 to present
- **Year dropdown**: Goes back to 1998

### API/RSS Access
RSS feeds provide structured access to recent opinions:
- Supreme Court: https://www.pacourts.us/Rss/Opinions/Supreme/
- Superior Court: https://www.pacourts.us/Rss/Opinions/Superior/
- Commonwealth Court: https://www.pacourts.us/Rss/Opinions/Commonwealth/

### Scraping Approach
1. **Recent Opinions**: Use RSS feeds for new opinions
2. **Historical Opinions**: Use opinion search with date filters
3. **Opinion PDFs**: Direct download from /assets/opinions/ paths
4. **Case Information**: Use UJS Portal case search
5. **Judges**: Scrape from justices/judges pages

---

## Example URLs

```
# Opinion Search Page (all courts)
GET https://www.pacourts.us/courts/supreme-court/court-opinions/

# Supreme Court Justices
GET https://www.pacourts.us/courts/supreme-court/supreme-court-justices

# Individual Justice Bio
GET https://www.pacourts.us/courts/supreme-court/supreme-court-justices/justice-debra-todd

# Supreme Court Calendar
GET https://www.pacourts.us/courts/supreme-court/calendar

# Opinion PDF (example)
GET https://www.pacourts.us/assets/opinions/Supreme/out/J-86-2025mo - 106651291344073938.pdf?cb=1

# RSS Feed - Supreme Court
GET https://www.pacourts.us/Rss/Opinions/Supreme/

# UJS Portal Case Search
GET https://ujsportal.pacourts.us/CaseSearch

# Superior Court Judges
GET https://www.pacourts.us/courts/superior-court/superior-court-judges

# Commonwealth Court Judges
GET https://www.pacourts.us/courts/commonwealth-court-judges

# Argument List PDF
GET https://www.pacourts.us/assets/opinions/Supreme/out/March2026ArgumentList.pdf
```

---

## Example Cases

### Recent Supreme Court Cases (January 2026)
- **Commonwealth v. Fitzpatrick, J.** - No. 95 MAP 2024 - Majority Opinion by Justice David Wecht
- **In Re: Chester Water Auth** - No. 50 MAP 2022 - Majority Opinion by Justice Christine Donohue
- **Volk, S. v. Tobin-Volk, K.** - No. 167 WAL 2025 - Petition for Allowance of Appeal
- **Commonwealth v. Layer, S.** - No. 385 MAL 2025 - Petition for Allowance of Appeal

---

## Contact Information

### Administrative Office of Pennsylvania Courts
- **Mailing Address**: Pennsylvania Judicial Center, 601 Commonwealth Avenue, P.O. Box 61260, Suite 1500, Harrisburg, PA 17106
- **Physical Address**: Pennsylvania Judicial Center, 601 Commonwealth Avenue, Suite 1500, Harrisburg, PA 17120

### AOPC Philadelphia Office
- 1515 Market Street, Suite 1414, Philadelphia, PA 19102

### Prothonotary Offices
- **Supreme Court**: https://www.pacourts.us/courts/supreme-court/prothonotarys-addresses
- **Superior Court**: https://www.pacourts.us/courts/superior-court/prothonotarys-addresses
- **Commonwealth Court**: https://www.pacourts.us/courts/commonwealth-court/commonwealth-court-prothonotarys-address

### Social Media
- Twitter/X: @pacourts, @SupremeCtofPA
- Facebook: /pennsylvaniacourts
- YouTube: UCR7oiMya78Iixm8XFjQ3ctQ
- Bluesky: pacourts.bsky.social

---

## Notes

1. **Three Appellate Courts**: Pennsylvania is one of few states with both a Superior Court and a Commonwealth Court as intermediate appellate courts, each with specialized jurisdiction.

2. **Unified Opinion Search**: The pacourts.us site provides a single search interface for all three appellate courts plus the Disciplinary Board.

3. **Opinion Naming Convention**: Opinion filenames often include both a case identifier (e.g., "J-86-2025mo") and a numeric ID (e.g., "106651291344073938"), separated by " - ".

4. **RSS Feeds**: The RSS feeds are an efficient way to track new opinions without scraping the full search interface.

5. **Multiple Districts**: Supreme Court cases are filed in three districts - Eastern (Philadelphia), Middle (Harrisburg), and Western (Pittsburgh) - designated by EAL, MAL, WAL in docket numbers.

6. **E-Filing System**: PACFile is the e-filing system for Pennsylvania courts, integrated with the UJS Portal.

7. **Historical Coverage**: Opinion search extends back to 1998 based on the year dropdown options.

8. **Mobile Access**: The PAeDocket mobile app provides convenient access to case/docket information.

9. **Livestreaming**: Court proceedings are livestreamed and may be archived for later viewing.

10. **Court Rotation**: The Supreme Court rotates its sessions among Philadelphia, Harrisburg, and Pittsburgh throughout the year.
