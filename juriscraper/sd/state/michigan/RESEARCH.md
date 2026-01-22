# Michigan Courts Research

## Court Structure

Michigan has a unified court system called "One Court of Justice" with the following appellate courts:

### 1. Michigan Supreme Court
- **Website**: https://www.courts.michigan.gov/courts/supreme-court/
- Highest court in Michigan
- 7 Justices (1 Chief Justice + 6 Justices)
- Justices are elected to 8-year terms
- Handles appeals from the Court of Appeals (discretionary review)
- Published opinions are binding precedent on all Michigan courts
- Term runs from August 1 to July 31

### 2. Michigan Court of Appeals
- **Website**: https://www.courts.michigan.gov/courts/court-of-appeals/
- Intermediate appellate court
- 25 Judges elected from 4 geographical districts
- Chief Judge: Michael F. Gadola (2024-present)
- Chief Judge Pro Tem: Stephen L. Borrello (2024-present)
- Judges sit in panels of 3 to decide cases
- Hears appeals as of right from Circuit Courts, Probate Courts, and some agency orders
- Issues both published (binding) and unpublished (non-binding) opinions
- Courtroom locations: Detroit, Lansing, and Grand Rapids

### 3. Court of Claims
- **Website**: https://www.courts.michigan.gov/courts/court-of-claims/
- Handles civil cases against the State of Michigan
- Part of the Court of Appeals for administrative purposes

---

## Key URLs and URL Patterns

### Main Portal
- **Judiciary Home**: https://www.courts.michigan.gov/
- **Case Search**: https://www.courts.michigan.gov/case-search/

### Michigan Supreme Court
- **Home**: https://www.courts.michigan.gov/courts/supreme-court/
- **Justices**: https://www.courts.michigan.gov/courts/supreme-court/justices/
- **Opinions by Term**: https://www.courts.michigan.gov/courts/supreme-court/opinions/
- **Current Term Opinions**: https://www.courts.michigan.gov/courts/supreme-court/opinions/2024-2025-term-opinions/
- **Oral Arguments Schedule**: https://www.courts.michigan.gov/courts/supreme-court/schedule-of-oral-arguments/
- **Cases Awaiting Argument**: https://www.courts.michigan.gov/courts/supreme-court/cases-awaiting-argument/
- **Clerk's Office**: https://www.courts.michigan.gov/courts/supreme-court/clerks-office/

### Michigan Court of Appeals
- **Home**: https://www.courts.michigan.gov/courts/court-of-appeals/
- **Judges**: https://www.courts.michigan.gov/courts/court-of-appeals/judges/
- **Current Judges**: https://www.courts.michigan.gov/courts/court-of-appeals/judges/current-judges/
- **Case Call Schedule**: https://www.courts.michigan.gov/courts/court-of-appeals/case-call-schedule/
- **Clerk's Office**: https://www.courts.michigan.gov/courts/court-of-appeals/clerks-office/

### Opinion ZIP Files (Bulk Downloads)
- **Main Page**: https://www.courts.michigan.gov/courts/opinion-order-zip-files/

#### Court of Appeals Opinion ZIP Patterns
- All opinions: `/{hash}/siteassets/case-documents/uploads/opinions/final/coa/zip-files/{YYYYMMDD}_all.zip`
- Published only: `/{hash}/siteassets/case-documents/uploads/opinions/final/coa/zip-files/{YYYYMMDD}_published.zip`
- Unpublished only: `/{hash}/siteassets/case-documents/uploads/opinions/final/coa/zip-files/{YYYYMMDD}_unpublished.zip`
- Available for past 28 days

#### Supreme Court Opinion ZIP Patterns
- Opinions: `/{hash}/siteassets/case-documents/uploads/opinions/final/sct/zip-files/{YYYYMMDD}_msc_opinions.zip`
- Available for past 90 days

#### Supreme Court Order ZIP Patterns
- Orders: `/{hash}/siteassets/case-documents/uploads/sct/public/orders/zip-files/{YYYYMMDD}_msc_orders.zip`
- Available for past 28 days

### Individual Opinion PDF Patterns
Supreme Court opinions follow this pattern:
- `https://www.courts.michigan.gov/{hash}/siteassets/case-documents/uploads/opinions/final/sct/{case_number}_{id}_01.pdf`
- Example: `https://www.courts.michigan.gov/4a26f4/siteassets/case-documents/uploads/opinions/final/sct/167745_74_01.pdf`

Court of Appeals opinions follow this pattern:
- `https://www.courts.michigan.gov/{hash}/siteassets/case-documents/uploads/opinions/final/coa/{filename}.pdf`

---

## Current Justices - Michigan Supreme Court

| Name | Position | Bio URL |
|------|----------|---------|
| Hon. Megan K. Cavanagh | Chief Justice | https://www.courts.michigan.gov/courts/supreme-court/justices/justice-megan-k.-cavanagh/ |
| Hon. Brian K. Zahra | Justice | https://www.courts.michigan.gov/courts/supreme-court/justices/justice-brian-k.-zahra/ |
| Hon. Richard Bernstein | Justice | https://www.courts.michigan.gov/courts/supreme-court/justices/justice-richard-bernstein/ |
| Hon. Elizabeth M. Welch | Justice | https://www.courts.michigan.gov/courts/supreme-court/justices/justice-elizabeth-m.-welch/ |
| Hon. Kyra H. Bolden | Justice | https://www.courts.michigan.gov/courts/supreme-court/justices/justice-kyra-h.-bolden/ |
| Hon. Kimberly A. Thomas | Justice | https://www.courts.michigan.gov/courts/supreme-court/justices/justice-kimberly-a.-thomas/ |
| Hon. Noah P. Hood | Justice | https://www.courts.michigan.gov/courts/supreme-court/justices/justice-noah-p.-hood/ |

---

## Current Judges - Michigan Court of Appeals

The Court of Appeals has 25 judges elected from 4 geographical districts. Current judges (as of 2025):

### First District
- Christopher M. Murray (2002)
- Michael J. Riordan (2012)
- Thomas C. Cameron (2017)
- Anica Letica (2018)
- Kristina Robinson Garrett (2022)
- Mariam Saad Bazzi (2025)

### Second District
- Colleen A. O'Brien (2015)
- Sima G. Patel (2022)
- Randy J. Wallace (2024)
- Adrienne N. Young (2024)
- Matthew S. Ackerman (2025)
- Christopher M. Trebilcock (2025)

### Third District
- Mark T. Boonstra (2012)
- James Robert Redford (2018)
- Christopher P. Yates (2022)
- Kathleen A. Feeney (2023)
- Philip P. Mariani (2024)
- Daniel S. Korobkin (2025)

### Fourth District
- Stephen L. Borrello (2003, Chief Judge Pro Tem)
- Michael J. Kelly (2008)
- Michael F. Gadola (2015, Chief Judge)
- Brock A. Swartzle (2017)
- Michelle M. Rick (2021)
- Allie Greenleaf Maldonado (2023)

**Full Roster**: https://www.courts.michigan.gov/courts/court-of-appeals/judges/current-judges/

---

## Opinion Types and Publication

### Published Opinions
- **Citation Format**: `___ Mich ___` (Supreme Court) or `___ Mich App ___` (Court of Appeals)
- Binding precedential value
- Available through the case search and opinion pages

### Unpublished Opinions (Court of Appeals)
- Not binding precedent
- May be cited for persuasive value
- Available through ZIP files and case search
- Marked as "unpublished" in filenames

### Docket Number Format
- Supreme Court: 6-digit case number (e.g., `167745`)
- Court of Appeals: 6-digit case number (e.g., `366123`)
- Multiple related cases joined with hyphens (e.g., `166477-8`)

---

## Access Restrictions

### No Login Required
- All court websites are publicly accessible
- Published opinions freely downloadable as PDFs
- Case search available without authentication
- ZIP files of opinions available for bulk download

### Usage Restrictions (from footer)
- "Bulk data downloads and commercial uses of the data from this site are prohibited"
- Standard terms of use apply

### Electronic Filing
- **MiFILE**: https://www.courts.michigan.gov/mifile-systems/
- Mandatory e-filing for attorneys (effective February 1, 2020)
- Available for both Supreme Court and Court of Appeals

### Data Retention on ZIP File Page
- Court of Appeals opinions: 28-day history
- Supreme Court opinions: 90-day history
- Supreme Court orders: 28-day history
- Business Court opinions: 1-month history

---

## Technical Implementation Notes

### Website Structure
- **Domain**: courts.michigan.gov
- Modern responsive website with JavaScript-heavy interface
- Case search uses AJAX/dynamic loading
- URLs contain hash prefixes for static assets

### Case Search Interface
- **URL**: https://www.courts.michigan.gov/case-search/
- Supports searching: Cases, Opinions, Orders
- Filters: Case Number, Appellate Court, Party Name, Author, Panel Members, Case Type, Lower Court
- Appellate Court options: Supreme Court, Court Of Claims, Court Of Appeals, COA and MSC

### Opinion Listing Structure
On term opinion pages (e.g., 2024-2025 Term), opinions are listed as:
- `{Case Number}, {Case Name}, {Date}`
- Direct links to PDF files

### Data Available for Each Opinion
- Case number
- Case name/parties
- Decision date
- PDF document
- Author (in search results)
- Panel members (in search results for COA)

### ZIP File Contents
- PDFs named with 6-digit docket numbers
- Generated next business day by approximately 9:00 a.m.
- Multiple files per archive for days with multiple releases

---

## Oral Arguments

### Supreme Court
- **Schedule**: https://www.courts.michigan.gov/courts/supreme-court/schedule-of-oral-arguments/
- **Livestream**: https://www.courts.michigan.gov/court-livestream/
- Arguments held at Michigan Hall of Justice, 925 W. Ottawa St., Lansing
- Special sessions sometimes held at other locations
- Call notices and schedules available as PDF documents
- Arguments typically start at 9:30 a.m.

### Court of Appeals
- **Case Call Schedule**: https://www.courts.michigan.gov/courts/court-of-appeals/case-call-schedule/
- Arguments held in Detroit, Lansing, and Grand Rapids

### Court Livestream
- **URL**: https://www.courts.michigan.gov/court-livestream/
- Live and archived recordings available
- YouTube channels:
  - Supreme Court: https://www.youtube.com/user/MichiganCourts
  - Court of Appeals: https://www.youtube.com/c/MichiganCourtofAppeals
  - Court of Claims: https://www.youtube.com/c/MichiganCourtofClaims

---

## Example Cases

### Supreme Court (2024-2025 Term)
- **167745**: In re Barber/Espinoza (7/31/25)
- **166923**: People v Carson (7/31/25)
- **163989**: Rayford v American House Roseville I, LLC (7/31/25)
- PDF URL example: `https://www.courts.michigan.gov/4a26f4/siteassets/case-documents/uploads/opinions/final/sct/167745_74_01.pdf`

### Court of Appeals ZIP Files
- All opinions (1/21/2026): `https://www.courts.michigan.gov/48f6e9/siteassets/case-documents/uploads/opinions/final/coa/zip-files/20260121_all.zip`
- Published opinions (1/20/2026): `https://www.courts.michigan.gov/48f4e2/siteassets/case-documents/uploads/opinions/final/coa/zip-files/20260120_published.zip`

---

## Recommended Scraper Architecture

### 1. Michigan Supreme Court Opinion Scraper
**Source**: https://www.courts.michigan.gov/courts/supreme-court/opinions/

**Approach**:
1. Navigate to term opinions page (e.g., 2024-2025 Term)
2. Parse opinion listing with case numbers, names, and dates
3. Extract direct PDF URLs
4. Note: URLs contain hash prefixes that may change

**Data Available**:
- Case number
- Case name
- Decision date
- Direct PDF URL

### 2. Michigan Court of Appeals Opinion Scraper
**Source**: Opinion ZIP files page or case search

**Approach for ZIP Files** (Recommended):
1. Access ZIP file page: https://www.courts.michigan.gov/courts/opinion-order-zip-files/
2. Download daily ZIP files (published, unpublished, or all)
3. Extract PDFs and parse metadata from filenames
4. Available for past 28 days

**Approach for Case Search**:
1. Use advanced search with Appellate Court = "Court Of Appeals"
2. Filter by date or party as needed
3. Parse search results for case metadata and PDF links

### 3. Case Search API
**Source**: https://www.courts.michigan.gov/case-search/

The search appears to use a JavaScript-based interface. May require:
- Browser automation (Playwright/Selenium)
- Or reverse-engineering the underlying API calls

### 4. Oral Arguments Scraper
**Source**: https://www.courts.michigan.gov/courts/supreme-court/schedule-of-oral-arguments/

**Approach**:
1. Parse the schedule page for argument dates and cases
2. Extract links to individual case information pages
3. Download call notices and schedules (PDF)

---

## Additional Resources

### Court Rules
- **Michigan Court Rules**: https://www.courts.michigan.gov/rules-administrative-orders-and-jury-instructions/
- **Michigan Appellate Opinion Manual**: https://www.courts.michigan.gov/4a4a11/siteassets/publications/manuals/msc/miappopmanual.pdf

### Publications
- **Michigan Bound Volumes**: https://www.courts.michigan.gov/publications/michigan-bound-volumes/
- **Court of Appeals Annual Report**: https://www.courts.michigan.gov/49ad19/siteassets/reports/coa/annualreports/annualreport2024.pdf

### Subscription Services
- **Email Notifications**: https://www.courts.michigan.gov/newsroom-social-media/subscribe/
- Receive opinions, orders, and administrative matters via email

### Contact Information
- **Supreme Court Clerk's Office**: (517) 373-0120
- **Michigan Hall of Justice**: 925 W. Ottawa St., Lansing, MI 48915

---

## Notes

1. **ZIP File Approach**: The most reliable method for bulk opinion collection is through the ZIP file archives, though they have limited retention (28-90 days depending on court).

2. **Hash Prefixes**: URLs for static assets include hash prefixes (e.g., `/4a26f4/`). These may be content hashes and could change if files are updated.

3. **JavaScript-Heavy Site**: The case search interface uses significant JavaScript. A browser automation approach may be necessary for scraping search results.

4. **MiFILE Integration**: Attorneys are required to e-file, but public access to documents doesn't require authentication.

5. **Court of Appeals Volume**: The Court of Appeals is described as "one of the highest volume intermediate appellate courts in the country" - handling 2,000+ appeals per year.

6. **Opinion Release Schedule**:
   - Supreme Court opinions are released on a "random schedule" throughout the term
   - Court of Appeals releases opinions on business days
   - ZIP files are generated and posted by approximately 9:00 a.m. the next business day

7. **District System**: Court of Appeals judges are elected from 4 geographical districts but rotate statewide among panels and courtroom locations.
