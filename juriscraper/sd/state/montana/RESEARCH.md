# Montana Courts Research

## Court Structure

Montana has a two-tier appellate court system. Unlike many states, Montana does **not** have an intermediate Court of Appeals - all appeals go directly to the Supreme Court.

### 1. Montana Supreme Court
- **Website**: https://courts.mt.gov/Courts/Supreme
- Highest and only appellate court in Montana
- 7 Justices (includes 1 Chief Justice)
- Justices elected statewide in nonpartisan elections
- 8-year terms
- Located at Joseph P. Mazurek Justice Building, 215 N. Sanders, Helena, Montana
- Chief Justice: Cory Swanson (elected November 2024)

#### Jurisdiction
- Appeals from District Courts
- Original jurisdiction in some matters (writs, bar discipline)
- No intermediate Court of Appeals - all appeals come directly to Supreme Court

### 2. District Courts (Trial Courts - for reference)
- **Website**: https://courts.mt.gov/Courts/District
- 56 District Courts across Montana
- 22 Judicial Districts
- General jurisdiction for civil and criminal cases
- Appeals go directly to Supreme Court

### 3. Specialty Courts
- **Water Court**: https://courts.mt.gov/Courts/Water - Statewide adjudication of water rights
- **Workers' Compensation Court**: https://courts.mt.gov/Courts/WC - Workers' compensation disputes
- **Courts of Limited Jurisdiction**: Justice Courts, City Courts, Municipal Courts

---

## Key URLs and URL Patterns

### Main Portal
- **Judiciary Home**: https://courts.mt.gov/
- **Courts Overview**: https://courts.mt.gov/Courts/index
- **Supreme Court**: https://courts.mt.gov/Courts/Supreme
- **About Supreme Court**: https://courts.mt.gov/Courts/Supreme/About

### Daily Orders and Opinions
- **Daily Orders/Opinions Page**: https://courts.mt.gov/external/orders/dailyorders
- Contains table with: Document Description, File Date, Case Number, Title
- Links to individual case info pages
- Updated daily with new orders and opinions

### Case Information
- **Case Info URL Pattern**: `https://courts.mt.gov/external/orders/caseInfo?id={CASE_NUMBER}`
  - Example: `https://courts.mt.gov/external/orders/caseInfo?id=DA%2025-0142`
- Shows: Case details, party information, register of actions (docket)
- Links to viewable documents (briefs, orders, opinions)

### Supreme Court Docket Search
- **Docket Search Portal**: https://supremecourtdocket.mt.gov/
- **Search Page**: https://supremecourtdocket.mt.gov/search
- Three search modes:
  - Active Dockets
  - Closed Dockets (2006-Present)
  - Closed Dockets (1979-2005)
- Search by: Case Number, Party Name, Case Attorney, Date Range

### Document Download
- **Document URL Pattern**: `https://juddocumentservice.mt.gov/getDocByCTrackId?DocId={DOC_ID}`
  - Example: `https://juddocumentservice.mt.gov/getDocByCTrackId?DocId=549602`
- Documents served from separate document service domain
- PDFs downloadable directly

### Oral Arguments
- **Oral Arguments Schedule**: https://courts.mt.gov/Courts/Supreme/Oral_Arguments/index
- **Previous Oral Arguments**: https://courts.mt.gov/Courts/Supreme/Oral_Arguments/Previous
- **Live Web Stream**: http://stream.vision.net/MT-JUD/
- Approximately 15 cases per year scheduled for oral argument

### Case Summaries
- **Case Summaries**: https://courts.mt.gov/Courts/Supreme/Summaries/index
- Prepared by Court staff (not official opinions)

### Judge Bio Pages
- **Biographies Index**: https://courts.mt.gov/Courts/Supreme/About/bios/
- **Individual Bio Pattern**: `https://courts.mt.gov/Courts/Supreme/About/bios/{LastName}`
  - Example: `https://courts.mt.gov/Courts/Supreme/About/bios/Swanson`

### Public Access Portals
- **District Court Public Access**: Referenced on main site (login may be required)
- **Courts of Limited Jurisdiction Public Access**: Referenced on main site

---

## Current Justices - Montana Supreme Court

| Name | Position | Bio URL |
|------|----------|---------|
| Hon. Cory Swanson | Chief Justice | https://courts.mt.gov/Courts/Supreme/About/bios/Swanson |
| Hon. James Jeremiah Shea | Justice | https://courts.mt.gov/Courts/Supreme/About/bios/Shea |
| Hon. Laurie McKinnon | Justice | https://courts.mt.gov/Courts/Supreme/About/bios/McKinnon |
| Hon. Beth Baker | Justice | https://courts.mt.gov/Courts/Supreme/About/bios/Baker |
| Hon. Katherine M. Bidegaray | Justice | https://courts.mt.gov/Courts/Supreme/About/bios/Bidegaray |
| Hon. James A. Rice | Justice | https://courts.mt.gov/Courts/Supreme/About/bios/Rice |
| Hon. Ingrid Gustafson | Justice | https://courts.mt.gov/Courts/Supreme/About/bios/Gustafson |

**Notes**:
- Chief Justice Swanson was elected in November 2024
- Previously served as Broadwater County Attorney (2014-2024)
- All justices serve 8-year terms, elected statewide

---

## Case Number Format

Montana Supreme Court case numbers follow the pattern: `{PREFIX} {YY}-{NNNN}`

### Prefixes
- **DA**: Direct Appeal
- **OP**: Original Proceeding
- **PR**: Professional Responsibility/Attorney Discipline
- **AF**: Administrative Filing

### Examples
- `DA 25-0142` - Direct Appeal from 2025
- `DA 24-0559` - Direct Appeal from 2024
- `DA 25-0481` - Direct Appeal from 2025
- `DA 25-0187` - Direct Appeal from 2025

### Case Types (from docket)
- Direct Appeal - Declaratory Judgment
- Direct Appeal - Civil
- Direct Appeal - Criminal
- Original Proceeding

---

## Opinion Types and Publication

### Daily Orders/Opinions Page Content
Each entry on the daily orders page includes:
- Document Description (Order text summary or "Opinion")
- File Date (timestamp format: `YYYY-MM-DD HH:MM:SS.0`)
- Case Number (linked to case info page)
- Title (full case name with parties)

### Document Types
- **Orders**: Procedural orders, extension grants, scheduling
- **Opinions**: Full written decisions
- **Notices**: Administrative filings
- **Briefs**: Appellant, Appellee, Reply, Amicus briefs

### Register of Actions
Case info pages show complete register of actions with:
- Document description
- Filing date
- Links to view documents (some marked "Unavailable Document")

---

## Access Restrictions

### No Login Required
- Daily orders/opinions page publicly accessible
- Case info pages publicly accessible
- Justice bio pages publicly accessible
- Oral argument schedule publicly accessible
- Docket search (supremecourtdocket.mt.gov) publicly accessible

### Document Availability
- Most briefs and opinions viewable/downloadable
- Some documents marked "Unavailable Document" in register of actions
- Documents served from juddocumentservice.mt.gov

### Rate Limiting
- No obvious rate limiting observed
- Standard web scraping best practices recommended

---

## Oral Arguments

### Schedule
- **Current Schedule**: https://courts.mt.gov/Courts/Supreme/Oral_Arguments/index
- Approximately 15 cases per year
- Held primarily at Montana Supreme Court Courtroom, Helena
- Some arguments held in other Montana cities

### Time Limits
- Typically 20-40 minutes per party
- Set by Court order for each case

### Live Streaming
- **Stream URL**: http://stream.vision.net/MT-JUD/
- Arguments streamed live when in session
- All oral arguments open to the public

---

## Technical Implementation Notes

### Website Structure
- **Primary Domain**: courts.mt.gov
- **Docket Search**: supremecourtdocket.mt.gov (separate application)
- **Document Service**: juddocumentservice.mt.gov (PDF downloads)
- Mix of static pages and dynamic content

### Daily Orders Page
- HTML table structure
- Columns: Document Description, File Date, Case Number, Title
- Links to case info pages
- URL: https://courts.mt.gov/external/orders/dailyorders

### Scraping Approach
1. **Daily Orders**: Parse table on dailyorders page for new filings
2. **Case Details**: Follow case number links to caseInfo pages
3. **Documents**: Download from juddocumentservice.mt.gov via DocId
4. **Docket Search**: Use supremecourtdocket.mt.gov for historical cases

### Date Handling
- File dates in format: `YYYY-MM-DD HH:MM:SS.0`
- Daily orders page appears to show recent filings (rolling window)

### Example API-like Calls
```
# Get daily orders/opinions list
GET https://courts.mt.gov/external/orders/dailyorders

# Get case information
GET https://courts.mt.gov/external/orders/caseInfo?id=DA%2025-0142

# Download document
GET https://juddocumentservice.mt.gov/getDocByCTrackId?DocId=549602

# Search docket (browser-based, may need form submission)
https://supremecourtdocket.mt.gov/search
```

---

## Example Cases

### Case DA 25-0142 (Ellingson v. State)
- **Type**: Direct Appeal - Declaratory Judgment
- **Court**: Lewis & Clark County District Court
- **Full Title**: MAE NAN ELLINGSON; JEROME LOENDORF; ARLYNE REICHERT; HAL HARPER; BOB BROWN; EVAN BARRETT; C.B. PEARSON; CAROLE MACKIN; MARK MACKIN; JONATHAN MOTL vs. STATE OF MONTANA; GREG GIANFORTE; AUSTIN KNUDSEN; CHRISTI JACOBSEN
- **Case Info URL**: https://courts.mt.gov/external/orders/caseInfo?id=DA%2025-0142
- **Oral Argument**: April 10, 2026, University of Montana
- **Subject**: Challenge to SB 93 (ballot initiative regulations)

### Case DA 25-0187 (Montana Conservation Voters v. Jacobsen)
- **Type**: Direct Appeal
- **Full Title**: MONTANA CONSERVATION VOTERS et al. vs. CHRISTI JACOBSEN
- **Case Info URL**: https://courts.mt.gov/external/orders/caseInfo?id=DA%2025-0187
- **Oral Argument**: February 11, 2026, Helena
- **Subject**: Public Service Commission redistricting challenge

### Recent Orders (from Daily Orders page)
- **DA 25-0481**: Westview Mobile Home Park v. Lockhart (2026-01-22)
- **DA 24-0559**: State v. B. Evans (2026-01-22)

---

## Contact Information

### Clerk of the Supreme Court
- **Clerk**: Bowen Greenwood
- **Website**: https://courts.mt.gov/clerk
- **Resources**: https://courts.mt.gov/clerk/resources

### Montana Supreme Court
- **Address**: Joseph P. Mazurek Justice Building, 215 N. Sanders, Helena, MT
- **General Info**: https://courts.mt.gov/Courts/Supreme

---

## Notes

1. **No Intermediate Appellate Court**: Montana is one of few states without an intermediate Court of Appeals. All appeals go directly to the Supreme Court.

2. **Existing Scraper**: Juriscraper already has `mont.py` in the opinions state directory.

3. **Docket System**: The Supreme Court docket system (supremecourtdocket.mt.gov) is a separate application from the main courts website.

4. **Document Service**: Documents are served from a separate domain (juddocumentservice.mt.gov).

5. **Oral Arguments**: Only about 15 cases per year get oral argument; most decided on briefs only.

6. **Public Meeting Minutes**: Available at https://courts.mt.gov/Courts/Supreme/pubminutes

7. **Court Rules**: Available at https://courts.mt.gov/Courts/Rules/Supreme

8. **Cookie Notice**: Site uses Google Analytics and shows cookie consent dialog.

9. **Historical Coverage**: Docket search covers cases from 1979 to present (in two databases: 1979-2005 and 2006-present).
