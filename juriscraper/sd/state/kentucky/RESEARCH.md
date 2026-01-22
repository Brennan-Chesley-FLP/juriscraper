# Kentucky Courts Research

## Court Structure

Kentucky has a two-tier appellate court system: the Supreme Court of Kentucky at the apex and the Kentucky Court of Appeals as the intermediate appellate court.

### 1. Supreme Court of Kentucky
- **Website**: https://www.kycourts.gov/Courts/Supreme-Court/Pages/default.aspx
- Highest court in Kentucky
- 7 Justices (1 Chief Justice + 1 Deputy Chief Justice + 5 Justices)
- Justices elected from 7 Supreme Court Districts
- Term: 8 years
- Chief Justice elected by fellow justices for a 4-year term
- Temporary Location: 669 Chamberlin Ave., Suite A104, Frankfort, KY 40601 (Capitol closed for renovation)
- Phone: 502-564-5444 (Clerk of Court)

### 2. Kentucky Court of Appeals
- **Website**: https://www.kycourts.gov/Courts/Court-of-Appeals/Pages/default.aspx
- Intermediate appellate court
- 14 Judges (1 Chief Judge + 1 Deputy Chief Judge + 12 Judges)
- Judges elected from 7 Appellate Districts (2 divisions per district)
- Term: 8 years
- Chief Judge selected by fellow judges
- Location: 669 Chamberlin Ave., Suite B, Frankfort, KY 40601
- Phone: 502-573-7920 (Clerk of Court)

---

## Key URLs and URL Patterns

### Main Portal
- **Courts Home**: https://www.kycourts.gov/
- **Supreme Court**: https://www.kycourts.gov/Courts/Supreme-Court/Pages/default.aspx
- **Court of Appeals**: https://www.kycourts.gov/Courts/Court-of-Appeals/Pages/default.aspx

### Case Information System (C-Track Public Access)
- **Login/Home**: https://appellatepublic.kycourts.net/login
- **Public Access Home**: https://appellatepublic.kycourts.net/
- **Case Search**: https://appellatepublic.kycourts.net/search/case
- **Document Search**: https://appellatepublic.kycourts.net/search/document
- **Opinion Search**: https://appellatepublic.kycourts.net/search/opinion
- **Party Search**: https://appellatepublic.kycourts.net/search/party
- **Trial Court Search**: https://appellatepublic.kycourts.net/search/lowerCourt

### Case Detail URLs
- **Case Detail**: https://appellatepublic.kycourts.net/case/{hash-id}
  - Example: https://appellatepublic.kycourts.net/case/755e8a13452bd027d43e60882f6231acf6747270e77652077058ff8744d2ce1a
- **Case Summary**: https://appellatepublic.kycourts.net/case/summary/{hash-id}

### Document URLs
- **Document Download**: https://appellatepublic.kycourts.net/documents/{document-hash}/download

### Opinion Search URLs with Filters
- **Supreme Court Minutes**: https://appellatepublic.kycourts.net/search/document?q=true&advanced=true&searchFields[0].searchType=Contains&searchFields[0].operation==&searchFields[0].values[0]=sc%20admin%20-%20minutes&searchFields[0].indexFieldName=caseHeader.caseNumber&p.page=1&p.sort=parentDate&p.sortdir=desc
- **Supreme Court Oral Argument Calendars**: https://appellatepublic.kycourts.net/search/document?q=true&advanced=true&searchFields[0].searchType=Contains&searchFields[0].operation==&searchFields[0].values[0]=sc%20admin%20-%20oral&searchFields[0].indexFieldName=caseHeader.caseNumber&p.page=1&p.sort=parentDate&p.sortdir=desc
- **Supreme Court Case Summaries**: https://appellatepublic.kycourts.net/search/document?q=true&advanced=true&searchFields[0].searchType=Contains&searchFields[0].operation==&searchFields[0].values[0]=sc%20admin%20-%20case&searchFields[0].indexFieldName=caseHeader.caseNumber&p.page=1&p.sort=parentDate&p.sortdir=desc
- **Court of Appeals Minutes**: https://appellatepublic.kycourts.net/search/document?q=true&advanced=true&searchFields[0].searchType=Contains&searchFields[0].operation==&searchFields[0].values[0]=ca%20admin%20-%20minute&searchFields[0].indexFieldName=caseHeader.caseNumber&p.page=1&p.sort=parentDate&p.sortdir=desc
- **Court of Appeals Oral Argument Calendars**: https://appellatepublic.kycourts.net/search/document?q=true&advanced=true&searchFields[0].searchType=Contains&searchFields[0].operation==&searchFields[0].values[0]=ca%20admin%20-%20oral&searchFields[0].indexFieldName=caseHeader.caseNumber&p.page=1&p.sort=parentDate&p.sortdir=desc
- **Court of Appeals Case Summaries**: https://appellatepublic.kycourts.net/search/document?q=true&advanced=true&searchFields[0].searchType=Contains&searchFields[0].operation==&searchFields[0].values[0]=ca%20admin%20-%20case&searchFields[0].indexFieldName=caseHeader.caseNumber&p.page=1&p.sort=parentDate&p.sortdir=desc

### Oral Arguments
- **Supreme Court Oral Arguments Calendars**: https://www.kycourts.gov/Courts/Supreme-Court/Pages/Oral-Arguments-Calendar.aspx
- **Supreme Court Oral Argument Calendar PDF Pattern**: https://apps.kycourts.net/Supreme/CALENDAR/SCO{MONTH}{YY}.pdf
  - Example: https://apps.kycourts.net/Supreme/CALENDAR/SCOJAN26.pdf
- **Court Week Calendar**: https://www.kycourts.gov/Courts/Supreme-Court/Documents/2026_2027_sccourtweekcalendar.pdf
- **Supreme Court Livestream**: https://ket.org/ky-supreme-court/
- **Court of Appeals Oral Arguments**: https://www.kycourts.gov/Courts/Court-of-Appeals/Pages/Oral-Arguments-Calendar.aspx
- **Court of Appeals Livestream (Franklin)**: https://kycourts.devosvideo.com/show?video=99836d8dfa57
- **Court of Appeals Livestream (Hardin)**: https://kycourts.devosvideo.com/show?video=cc7e9267761b
- **Court of Appeals Livestream (Jefferson)**: https://kycourts.devosvideo.com/show?video=e756135cf594

### Docket Information (Trial Courts)
- **Docket Search**: https://kcoj.kycourts.net/dockets/

### eFiling/CourtNet
- **eFiling Portal**: https://kcoj.kycourts.net/kyecourts/Login
- **Guest Login**: https://kcoj.kycourts.net/kyecourts/login/guestlogin

### Other Resources
- **Court Rules (Westlaw)**: https://govt.westlaw.com/kyrules/Index?transitionType=Default&contextData=%28sc.Default%29
- **Rules of Appellate Procedure**: https://www.kycourts.gov/Courts/Supreme-Court/Supreme%20Court%20Orders/202249.pdf
- **Searchable Opinions (dtSearch)**: http://opinions.kycourts.net/dtsearch.html
- **Court Personnel Directory**: https://kcoj.kycourts.net/ContactList/Search
- **Supreme Court District Map**: https://www.kycourts.gov/Courts/Documents/SC_COA_districtsmap.pdf
- **Supreme Court/COA Face Map**: https://www.kycourts.gov/Courts/Documents/P-103_Supreme_Ct-Court_of_Appeals_Face_Map.pdf

---

## Current Justices - Supreme Court of Kentucky

| Name | Position | District | Bio URL |
|------|----------|----------|---------|
| Debra Hembree Lambert | Chief Justice | 3rd District | https://www.kycourts.gov/Courts/Supreme-Court/Pages/3rd-Supreme-Court-District.aspx |
| Robert B. Conley | Deputy Chief Justice | 7th District | https://www.kycourts.gov/Courts/Supreme-Court/Pages/7th-Supreme-Court-District.aspx |
| Shea Nickell | Justice | 1st District | https://www.kycourts.gov/Courts/Supreme-Court/Pages/1st-Supreme-Court-District.aspx |
| Kelly Thompson | Justice | 2nd District | https://www.kycourts.gov/Courts/Supreme-Court/Pages/2nd-Supreme-Court-District.aspx |
| Angela McCormick Bisig | Justice | 4th District | https://www.kycourts.gov/Courts/Supreme-Court/Pages/4th-Supreme-Court-District.aspx |
| Pamela R. Goodwine | Justice | 5th District | https://www.kycourts.gov/Courts/Supreme-Court/Pages/5th-Supreme-Court-District.aspx |
| Michelle M. Keller | Justice | 6th District | https://www.kycourts.gov/Courts/Supreme-Court/Pages/6th-Supreme-Court-District.aspx |

Note: Chief Justice Lambert's term as Chief Justice began January 7, 2025.

---

## Current Judges - Kentucky Court of Appeals

| Name | Position | District | Division | Bio URL |
|------|----------|----------|----------|---------|
| Larry E. Thompson | Chief Judge | 7th | Division 2 | https://www.kycourts.gov/Courts/Court-of-Appeals/Pages/7th-Appellate-District-Division-2.aspx |
| J. Christopher McNeill | Deputy Chief Judge | 1st | Division 1 | https://www.kycourts.gov/Courts/Court-of-Appeals/Pages/1st-Appellate-District-Division-1.aspx |
| Lisa P. Jones | Judge | 1st | Division 2 | https://www.kycourts.gov/Courts/Court-of-Appeals/Pages/1st-Appellate-District-Division-2.aspx |
| Jeff S. Taylor | Judge | 2nd | Division 1 | https://www.kycourts.gov/Courts/Court-of-Appeals/Pages/2nd-Appellate-District-Division-1.aspx |
| Kelly Mark Easton | Judge | 2nd | Division 2 | https://www.kycourts.gov/Courts/Court-of-Appeals/Pages/2nd-Appellate-District-Division-2.aspx |
| Jacqueline M. Caldwell | Judge | 3rd | Division 1 | https://www.kycourts.gov/Courts/Court-of-Appeals/Pages/3rd-Appellate-District-Division-1.aspx |
| James H. Lambert | Judge | 3rd | Division 2 | https://www.kycourts.gov/Courts/Court-of-Appeals/Pages/3rd-Appellate-District-Division-2.aspx |
| Audra Jean Eckerle | Judge | 4th | Division 1 | https://www.kycourts.gov/Courts/Court-of-Appeals/Pages/4th-Appellate-District-Division-1.aspx |
| Annette C. Karem | Judge | 4th | Division 2 | https://www.kycourts.gov/Courts/Court-of-Appeals/Pages/4th-Appellate-District-Division-2.aspx |
| Will Moynahan | Judge | 5th | Division 1 | https://www.kycourts.gov/Courts/Court-of-Appeals/Pages/5th-Appellate-District-Division-1.aspx |
| Glenn E. Acree | Judge | 5th | Division 2 | https://www.kycourts.gov/Courts/Court-of-Appeals/Pages/5th-Appellate-District-Division-2.aspx |
| Allison Jones | Judge | 6th | Division 1 | https://www.kycourts.gov/Courts/Court-of-Appeals/Pages/6th-Appellate-District-Division-1.aspx |
| Susanne M. Cetrulo | Judge | 6th | Division 2 | https://www.kycourts.gov/Courts/Court-of-Appeals/Pages/6th-Appellate-District-Division-2.aspx |
| Sara Walter Combs | Judge | 7th | Division 1 | https://www.kycourts.gov/Courts/Court-of-Appeals/Pages/7th-Appellate-District-Division-1.aspx |

Note: Judge James H. Lambert announced retirement in January 2026.

---

## Jurisdiction

### Supreme Court of Kentucky
- Court of last resort in Kentucky
- All opinions are binding precedent on Kentucky courts
- Has exclusive appellate jurisdiction in:
  - Death penalty cases
  - Life imprisonment cases
  - Constitutional challenges to statutes
- Discretionary review of Court of Appeals decisions
- Supervisory control over all Kentucky courts
- Admits attorneys to practice law in Kentucky
- Promulgates rules of practice and procedure

### Kentucky Court of Appeals
- Intermediate appellate court
- Mandatory appellate jurisdiction from Circuit Court
- Reviews appeals from trial court decisions
- Cases typically decided by 3-judge panels
- Decisions may be reviewed by Supreme Court on discretionary review
- Some opinions are published and precedential

---

## Opinion Types and Publication

### Supreme Court Opinions
- All opinions are published and precedential
- Opinion types include:
  - DISPOSITION - MEMORANDUM OPINION (various subtypes: AFFIRMING, REVERSING, REMANDING, etc.)
  - Published opinions with full precedential value
- Comments section often lists participating justices and concurrences/dissents
- "*NOT TO BE PUBLISHED*" notation for unpublished memorandum opinions

### Court of Appeals Opinions
- Published opinions (precedential)
- Unpublished opinions (not precedential, but persuasive)
- Opinion types similar to Supreme Court

### Opinion Statistics (as of January 2026)
- Supreme Court: 10,744 opinions
- Court of Appeals: 56,444 opinions
- Total: 67,188 opinions in system

---

## Case Number Format

- **Supreme Court**: `{YYYY}-SC-{NNNN}` (e.g., 2018-SC-0250)
- **Court of Appeals**: `{YYYY}-CA-{NNNN}` (e.g., 2024-CA-0123)
- Four-digit year prefix
- Court abbreviation (SC or CA)
- Four-digit sequential number

### Administrative Case Numbers
- `SC ADMIN - MINUTES` - Supreme Court administrative minutes
- `SC ADMIN - ORAL` - Supreme Court oral argument calendars
- `SC ADMIN - CASE` - Supreme Court case summaries
- `CA ADMIN - MINUTE` - Court of Appeals minutes
- `CA ADMIN - ORAL` - Court of Appeals oral argument calendars
- `CA ADMIN - CASE` - Court of Appeals case summaries

---

## Access Restrictions

### No Login Required
- Public access to C-Track system (click "Continue as Public User")
- Opinion search
- Case search
- Document search
- Party search
- Docket search
- Judge biographies
- Court rules
- Oral argument calendars

### Terms of Use
- Must agree to Terms of Use: https://kcoj.kycourts.net/Content/docs/TermsOfUse2-4-13.pdf
- Information cannot be used for employment, licensing, or eligibility for government programs
- Data subject to change and may not reflect true status of cases

### No Known Rate Limits
- Standard web pages without explicit rate limiting
- Results capped at 10,000 records in search results
- Pagination available for large result sets

---

## Technical Implementation Notes

### C-Track Public Access System
- Modern web application (Vue.js based)
- REST API endpoints for searches
- Document hashes used for unique identification
- Supports sorting and filtering
- Pagination with page number parameters

### Opinion Search Parameters
- `q=true` - Query flag
- `advanced=true/false` - Advanced search mode
- `searchFields[0].searchType` - Search type (Contains, Equals, etc.)
- `searchFields[0].operation` - Operation (=)
- `searchFields[0].values[0]` - Search value
- `searchFields[0].indexFieldName` - Field to search (e.g., caseHeader.caseNumber)
- `p.page` - Page number
- `p.sort` - Sort field (e.g., parentDate)
- `p.sortdir` - Sort direction (asc/desc)

### Case Detail Structure
- Case Number
- Title (parties)
- Classification (case type)
- Filed Date
- Case Status (FINAL, ACTIVE, etc.)
- Status Date
- Court
- Docket Entries with:
  - Filed Date
  - Description
  - Submitted By
  - Comments (includes judge participation info)
  - Due Date
  - Documents List

### Document Access
- Documents accessed via hash-based URLs
- Download links provided in document lists
- PDFs embedded for viewing

---

## Oral Arguments

### Supreme Court
- Oral argument calendars published monthly as PDFs
- URL pattern: `https://apps.kycourts.net/Supreme/CALENDAR/SCO{MONTH}{YY}.pdf`
- Month codes: JAN, FEB, MAR, APR, MAY, JUN, JUL, AUG, SEP, OCT, NOV, DEC
- Live streaming via KET: https://ket.org/ky-supreme-court/
- Conference week calendar published separately

### Court of Appeals
- Oral arguments conducted at various locations
- "Appeals on Wheels" program brings court to communities
- Live streaming available from multiple locations
- Calendars available through C-Track system

---

## Example Cases

### Supreme Court
- **2018-SC-0250**: ANTONIO CORDERIERO DOUGLAS VS COMMONWEALTH OF KENTUCKY
  - Classification: MATTER OF RIGHT - CRIMINAL - REGULAR CRIMINAL
  - Filed: 05/22/2018
  - Status: FINAL (05/09/2019)
  - Disposition: MEMORANDUM OPINION - AFFIRMING (04/18/2019)
  - Participating: MINTON, C.J.; HUGHES, KELLER, LAMBERT, VANMETER AND WRIGHT, JJ., CONCUR. BUCKINGHAM, J., NOT SITTING.

---

## Recommended Scraper Architecture

### 1. Opinion Scraper
**Source**: C-Track Opinion Search API

**Approach**:
1. Use opinion search endpoint with date filters
2. Filter by court (Supreme Court or Court of Appeals)
3. Paginate through results (25 per page, max 10,000)
4. Extract case hash IDs from results
5. Fetch case details for each opinion
6. Download opinion documents via document URLs

**Data Available from Opinion Search**:
- Case Number
- Type (DISPOSITION - MEMORANDUM OPINION, etc.)
- Subtype (AFFIRMING, REVERSING, etc.)
- Description
- Filed Date
- Documents List

### 2. Case Detail Scraper
**Source**: C-Track Case View

**Approach**:
1. Navigate to case detail URL using hash ID
2. Parse case metadata
3. Extract docket entries
4. Download attached documents

**Data Available**:
- Full case style/title
- Classification
- Filed date
- Status
- Court
- Docket entries with comments
- Document attachments

### 3. Oral Arguments Scraper
**Source**: Calendar PDFs and C-Track

**Approach**:
1. Download monthly calendar PDFs
2. Parse PDF content for case numbers and dates
3. Alternatively use C-Track document search for oral argument calendars
4. Extract YouTube/streaming video links when available

---

## Additional Resources

- **User Basics Guide**: https://kycourts.gov/Documents/ctrackuserguide_2020.pdf
- **Expanded User Guide**: https://kycourts.gov/Documents/expandedctrackuserguide_2020.pdf
- **Appellant Checklist**: https://www.kycourts.gov/Courts/Court-of-Appeals/Documents/AppellantBrief.pdf
- **Appellee Checklist**: https://www.kycourts.gov/Courts/Court-of-Appeals/Documents/AppelleeBrief.pdf
- **Reply Brief Checklist**: https://www.kycourts.gov/Courts/Court-of-Appeals/Documents/ReplyBrief.pdf
- **Basic Appellate Handbook**: https://www.kycourts.gov/Courts/Court-of-Appeals/Documents/P56BasicAppellatePracticeHandbook.pdf
- **News Releases**: https://www.kycourts.gov/Pages/Communications.aspx
- **Twitter**: https://twitter.com/kentuckycourts
- **Facebook**: https://www.facebook.com/KentuckyCourts/
- **LinkedIn**: https://www.linkedin.com/company/kentuckycourts/
- **YouTube**: https://www.youtube.com/@KentuckyCourts/featured

---

## Contact Information

### Supreme Court Clerk
- Katie Bing
- Phone: 502-564-5444
- Temporary Address: 669 Chamberlin Ave., Suite A104, Frankfort, KY 40601

### Court of Appeals Clerk
- Kate Morgan
- Phone: 502-573-7920
- Address: 669 Chamberlin Ave., Suite B, Frankfort, KY 40601

### Administrative Office of the Courts
- Address: 1001 Vandalay Drive, Frankfort, KY 40601
- Phone: 502-573-2350
- Contact Page: https://www.kycourts.gov/Pages/contact.aspx
