# North Carolina Courts Research

## Court Structure

North Carolina has a straightforward appellate court structure with one intermediate appellate court.

### 1. Supreme Court of North Carolina
- **Website**: https://www.nccourts.gov/courts/supreme-court
- Highest court in North Carolina
- 7 Justices (1 Chief Justice + 6 Associate Justices)
- Justices are elected to 8-year terms
- Located at the Justice Building, 2 East Morgan Street, Raleigh, NC 27601
- Chief Justice serves as head of the Judicial Branch

#### Jurisdiction
- Final appellate court for all state courts
- Direct appeals in death penalty cases
- Discretionary review of Court of Appeals decisions
- No jury; decides questions of law only

### 2. Court of Appeals
- **Website**: https://www.nccourts.gov/courts/court-of-appeals
- Intermediate appellate court
- 15 Judges (1 Chief Judge + 14 Judges)
- Judges are elected to 8-year terms
- Cases heard in panels of 3 judges
- Located at 1 West Morgan Street, Raleigh, NC 27601

#### Jurisdiction
- Reviews trial court proceedings for errors of law
- Hears appeals from Superior and District Courts
- Direct appeals from certain state administrative agencies
- Death penalty appeals go directly to Supreme Court

### 3. Trial Courts
- **Superior Court**: General jurisdiction, felonies, civil cases over $25,000
- **District Court**: Misdemeanors, civil cases under $25,000, family law, juvenile
- **Business Court**: Complex business disputes (https://www.nccourts.gov/courts/business-court)

---

## Key URLs and URL Patterns

### Main Portal
- **Judiciary Home**: https://www.nccourts.gov/
- **Courts Overview**: https://www.nccourts.gov/courts
- **Appellate Court Opinions**: https://www.nccourts.gov/documents/appellate-court-opinions

### Supreme Court
- **Supreme Court Home**: https://www.nccourts.gov/courts/supreme-court
- **Meet the Justices**: https://www.nccourts.gov/courts/supreme-court/meet-the-justices
- **Slip Opinions**: https://appellate.nccourts.org/opinion-filings/?c=sc
- **Dockets**: https://appellate.nccourts.org/dockets.php?c=1
- **Orders**: https://appellate.nccourts.org/orders.php
- **Calendars of Arguments**: https://appellate.nccourts.org/calendar.php?court=1
- **Petition Rulings**: https://appellate.nccourts.org/petitions.php

### Court of Appeals
- **Court of Appeals Home**: https://www.nccourts.gov/courts/court-of-appeals
- **Biographies of Judges**: https://www.nccourts.gov/courts/court-of-appeals/biographies-of-the-judges
- **Slip Opinions**: https://appellate.nccourts.org/opinion-filings/?c=coa
- **Dockets**: https://appellate.nccourts.org/dockets.php?c=2
- **Orders**: https://appellate.nccourts.org/orders.php?court=2
- **Calendar of Oral Arguments**: https://appellate.nccourts.org/calendar.php?court=2

### eFiling and Document Library
- **eFiling Site**: https://www.ncappellatecourts.org/
- No registration required for searching/viewing documents
- Registration required only for eFiling

### Other Resources
- **Case Summaries/Headnotes Search**: https://appellate.nccourts.org/opinion-filings/index-search.php
- **PDF Volumes (Official Reports)**: https://www.nccourts.gov/documents/pdf-volumes
- **Advance Sheets**: https://www.nccourts.gov/documents/advance-sheets
- **Email Notification Signup**: https://appellate.nccourts.org/notify_signup.php

---

## Opinion URL Patterns

### Appellate Court Opinions Page (Main Search)
- **Base URL**: `https://www.nccourts.gov/documents/appellate-court-opinions`
- **With filters**: `?field_court_type_target_id=19` (Supreme Court) or `20` (Court of Appeals)
- **Pagination**: `?page=N` (0-indexed)
- Supports filtering by: keywords, author, date range, court type, opinion type (published/unpublished)

### Individual Opinion PDFs
- **Pattern**: `https://appellate.nccourts.org/opinions/?c={court}&pdf={id}`
  - `c=1` for Supreme Court
  - `c=2` for Court of Appeals
- **Example**: `https://appellate.nccourts.org/opinions/?c=2&pdf=44878`

### Grouped Opinion Downloads (ZIP)
- **Pattern**: `https://appellate.nccourts.org/getopzip.php?c={court}&d={base64_date}`
- **Parameters**:
  - `c=1` for Supreme Court
  - `c=2` for Court of Appeals
  - `d` is base64-encoded date (e.g., `MjAyNi0wMS0yMQ==` = "2026-01-21")
  - Add `&u=0` for unpublished opinions
- **Example**: `https://appellate.nccourts.org/getopzip.php?c=2&d=MjAyNi0wMS0yMQ==`

### Slip Opinions by Year
- **Supreme Court**: `https://appellate.nccourts.org/opinion-filings/?c=sc&y={year}`
- **Court of Appeals**: `https://appellate.nccourts.org/opinion-filings/?c=coa&y={year}`

### Petition Rulings PDFs
- **Pattern**: `https://appellate.nccourts.org/petitions/p-{MMDDYYYY}.pdf`
- **Example**: `https://appellate.nccourts.org/petitions/p-12122025.pdf`
- Data available from 1997 to present

### Calendar PDFs
- **Pattern**: `https://appellate.nccourts.org/getCal.php?q={base64_params}`
- Parameters are base64-encoded (e.g., `date=2026-02-17&court=1`)

---

## Current Justices - Supreme Court

| Name | Position | Bio URL |
|------|----------|---------|
| Hon. Paul Newby | Chief Justice | https://www.nccourts.gov/judicial-directory/paul-newby |
| Hon. Anita Earls | Associate Justice | https://www.nccourts.gov/judicial-directory/anita-earls |
| Hon. Philip Berger Jr. | Associate Justice | https://www.nccourts.gov/judicial-directory/philip-berger-jr |
| Hon. Tamara Barringer | Associate Justice | https://www.nccourts.gov/judicial-directory/tamara-barringer |
| Hon. Richard Dietz | Associate Justice | https://www.nccourts.gov/judicial-directory/richard-dietz |
| Hon. Trey Allen | Associate Justice | https://www.nccourts.gov/judicial-directory/trey-allen |
| Hon. Allison Riggs | Associate Justice | https://www.nccourts.gov/judicial-directory/allison-riggs |

**Notes**:
- Chief Justice Paul Newby first elected as Associate Justice in 2004, elevated to Chief Justice in 2020 election
- Chief Justice serves as head of the Judicial Branch (30th Chief Justice)
- Justices serve 8-year terms

---

## Current Judges - Court of Appeals

| Name | Position | Bio URL |
|------|----------|---------|
| Hon. Chris Dillon | Chief Judge | https://www.nccourts.gov/judicial-directory/chris-dillon |
| Hon. Donna Stroud | Judge | https://www.nccourts.gov/judicial-directory/donna-stroud |
| Hon. John Tyson | Judge | https://www.nccourts.gov/judicial-directory/john-tyson |
| Hon. Valerie Zachary | Judge | https://www.nccourts.gov/judicial-directory/valerie-zachary |
| Hon. John Arrowood | Judge | https://www.nccourts.gov/judicial-directory/john-arrowood |
| Hon. Allegra Collins | Judge | https://www.nccourts.gov/judicial-directory/allegra-collins |
| Hon. Toby Hampson | Judge | https://www.nccourts.gov/judicial-directory/toby-hampson |
| Hon. Jeffery Carpenter | Judge | https://www.nccourts.gov/judicial-directory/jeffery-carpenter |
| Hon. April Wood | Judge | https://www.nccourts.gov/judicial-directory/april-wood |
| Hon. Fred Gore | Judge | https://www.nccourts.gov/judicial-directory/fred-gore |
| Hon. Jefferson Griffin | Judge | https://www.nccourts.gov/judicial-directory/jefferson-griffin |
| Hon. Julee Flood | Judge | https://www.nccourts.gov/judicial-directory/julee-flood |
| Hon. Michael Stading | Judge | https://www.nccourts.gov/judicial-directory/michael-stading |
| Hon. Thomas Murry | Judge | https://www.nccourts.gov/judicial-directory/thomas-murry |
| Hon. Christopher Freeman | Judge | https://www.nccourts.gov/judicial-directory/christopher-freeman |

**Notes**:
- Chief Judge designated by Chief Justice of Supreme Court
- Cases heard in panels of 3 judges
- Judges serve 8-year terms

---

## Case Number Formats

### Court of Appeals
- **Format**: `COA{YY}-{NNNN}`
- **Example**: `COA25-170`, `COA24-443`
- YY = 2-digit year case was filed
- NNNN = sequential number

### Supreme Court
- **Docket Format**: `{NNN}P{YY}` or `{NNN}PA{YY}`
- **Example**: `123P24` (discretionary review petition)
- P = Petition for discretionary review
- PA = Petition from administrative agency

---

## Opinion Types and Publication

### Opinion Categories
1. **Published Opinions**: Precedential, included in official reports
2. **Unpublished Opinions**: Not precedential, but publicly available

### Official Reports
- **North Carolina Reports**: Supreme Court opinions (e.g., 388 N.C. 123)
- **North Carolina Court of Appeals Reports**: Court of Appeals opinions (e.g., 295 N.C. App. 456)

### Publication Schedule
- Opinions released as slip opinions immediately after filing
- Advance sheets published periodically
- Final PDF volumes published after headnotes are added

### Document Formats
- All opinions available in PDF format
- ZIP downloads available for grouped opinions by date

---

## Access Restrictions

### No Login Required
- All appellate court opinions (published and unpublished)
- Docket searches
- Order searches
- Calendar/argument schedules
- Judge biographies
- eFiling document library (search and view)

### Login Required
- eFiling documents with the courts (registration required)

### Rate Limiting
- No apparent CAPTCHA or aggressive rate limiting
- Standard best practices recommended for scraping

---

## Oral Arguments

### Supreme Court
- **Live Stream**: Available on YouTube (http://govu.us/scncoa)
- **Archive**: Available on YouTube channel
- **Schedule**: Published annually with session dates
- **2026 Sessions**: February 17-19, April 14-16, April 21-23, September 8-10, September 15-17, November 10-12, November 17-19

### Court of Appeals
- **Calendar**: https://appellate.nccourts.org/calendar.php?court=2
- Arguments heard in panels of 3 judges

---

## Technical Implementation Notes

### Website Structure
- **Primary Domain**: www.nccourts.gov (Drupal-based)
- **Appellate Portal**: appellate.nccourts.org (PHP-based)
- **eFiling**: www.ncappellatecourts.org

### Search Systems
1. **Appellate Court Opinions Page**: Best for browsing recent opinions with filters
2. **Slip Opinions Pages**: Year-based browsing for each court
3. **eFiling Document Library**: Comprehensive search including briefs, motions, records
4. **Case Summaries/Headnotes**: Full-text search of headnotes

### Scraping Approach
1. **Recent Opinions**: Use the appellate court opinions page with date filters
   - URL: `https://www.nccourts.gov/documents/appellate-court-opinions`
   - Paginated results with detailed metadata
2. **Bulk Downloads**: Use ZIP download endpoint with base64-encoded dates
3. **Historical Data**: Use year-based slip opinion pages
4. **Dockets**: Search by case number, party, or attorney

### Data Availability
- **Opinions**: 36,244+ appellate court opinions available
- **Petition Rulings**: Available from 1997 to present
- **Case Summaries/Headnotes**: Supreme Court since December 2014, Court of Appeals since April 2016

---

## Example URLs

```
# Appellate court opinions main page
GET https://www.nccourts.gov/documents/appellate-court-opinions

# Supreme Court slip opinions for 2025
GET https://appellate.nccourts.org/opinion-filings/?c=sc&y=2025

# Court of Appeals slip opinions current year
GET https://appellate.nccourts.org/opinion-filings/?c=coa

# Individual opinion PDF (Court of Appeals)
GET https://appellate.nccourts.org/opinions/?c=2&pdf=44878

# Grouped opinions ZIP download (Court of Appeals, Jan 21, 2026)
GET https://appellate.nccourts.org/getopzip.php?c=2&d=MjAyNi0wMS0yMQ==

# Supreme Court docket search
GET https://appellate.nccourts.org/dockets.php?c=1

# Court of Appeals docket search
GET https://appellate.nccourts.org/dockets.php?c=2

# Supreme Court orders
GET https://appellate.nccourts.org/orders.php

# Court of Appeals orders
GET https://appellate.nccourts.org/orders.php?court=2

# Supreme Court calendar
GET https://appellate.nccourts.org/calendar.php?court=1

# Petition rulings page
GET https://appellate.nccourts.org/petitions.php

# Petition ruling PDF (December 12, 2025)
GET https://appellate.nccourts.org/petitions/p-12122025.pdf

# eFiling document library search
GET https://www.ncappellatecourts.org/

# Case summaries/headnotes search
GET https://appellate.nccourts.org/opinion-filings/index-search.php

# Justice bio page
GET https://www.nccourts.gov/judicial-directory/paul-newby

# Judge bio page
GET https://www.nccourts.gov/judicial-directory/chris-dillon
```

---

## Example Cases

### Recent Court of Appeals Cases (January 21, 2026)
- **Eagles v. Integon Indem. Corp.** - COA25-263 (Published) - Receivership; venue; standing
- **Lawrence v. Lawrence** - COA25-304 (Published) - Equitable distribution; marital property
- **State v. Braswell** - COA25-286 (Published) - Impeachment; Rule 608(a)
- **State v. Haizlip** - COA25-469 (Published) - Motion for appropriate relief

### Supreme Court Argument Schedule 2026
- February 17-19
- April 14-16
- April 21-23
- September 8-10
- September 15-17
- November 10-12
- November 17-19

---

## Contact Information

### Supreme Court Clerk's Office
- **Phone**: (919) 831-5700
- **Hours**: Monday-Friday, 8:00 AM - 5:00 PM
- **Physical Address**: 2 East Morgan Street, Raleigh, NC 27601-1428
- **Mailing Address**: PO Box 2170, Raleigh, NC 27602
- **Email (MIS/Tech)**: mis@sc.state.nc.us

### Court of Appeals Clerk's Office
- **Phone**: (919) 831-3600
- **Hours**: Monday-Friday, 8:00 AM - 5:00 PM
- **Physical Address**: 1 West Morgan Street, Raleigh, NC 27601
- **Mailing Address**: PO Box 2779, Raleigh, NC 27602
- **Email (Reporter)**: creporter@sc.nccourts.org

### Social Media
- **Facebook**: https://www.facebook.com/NCcourts
- **Twitter/X**: https://x.com/NCCourts
- **YouTube**: https://www.youtube.com/@NorthCarolinaCourts
- **LinkedIn**: https://www.linkedin.com/company/north-carolina-administrative-office-of-the-courts
- **Podcast**: https://www.nccourts.gov/learn/all-things-judicial-podcast

---

## Notes

1. **Clean URL Structure**: Bio pages use `/judicial-directory/{firstname}-{lastname}` pattern consistently.

2. **Base64 Encoding**: Download URLs and calendar URLs use base64-encoded parameters for dates and query strings.

3. **Court Identifiers**:
   - Supreme Court: `c=1` or `c=sc`
   - Court of Appeals: `c=2` or `c=coa`

4. **No CAPTCHA**: The appellate system does not appear to use CAPTCHA protection.

5. **Unified System**: All appellate courts share the same infrastructure at appellate.nccourts.org.

6. **Email Notifications**: Users can sign up for email notifications when new opinions are filed.

7. **Hybrid Calendar**: Oral arguments may include hybrid (in-person/remote) options.

8. **Self-Representation Guide**: Available at https://www.nccourts.gov/assets/inline-files/COA-Pro-Se-Packet-05-02-2024.pdf

9. **Business Court**: Separate from appellate courts, has its own opinion page at https://www.nccourts.gov/documents/business-court-opinions

10. **Drupal CMS**: Main nccourts.gov site runs on Drupal, with custom PHP applications for the appellate portal.
