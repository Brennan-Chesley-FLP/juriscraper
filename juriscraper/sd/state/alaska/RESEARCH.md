# Alaska Appellate Courts Scraper Research

## Research Date: 2026-01-22
## Verification Status: Verified via browser testing

## 1. Overview

Alaska has two appellate courts served by a unified case management system at https://appellate-records.courts.alaska.gov/

### Courts
- **Alaska Supreme Court** (5 justices) - Court ID: `alaska`
- **Alaska Court of Appeals** (4 judges) - Court ID: `alaskactapp`

### Data Types Available
1. **Cases/Dockets** - Full case information with docket entries, documents, parties
2. **Opinions** - Slip opinions, MOJs (Memorandum Opinions), Summary Dispositions
3. **Oral Arguments** - Scheduled oral arguments with live streaming

## 2. Official Court Websites

### Main Sites
| Site | URL | Status |
|------|-----|--------|
| Main Court Website | https://courts.alaska.gov/ | Verified |
| Appellate CMS | https://appellate-records.courts.alaska.gov/ | Verified |
| Appellate Courts Section | https://courts.alaska.gov/appellate/index.htm | Verified |
| CourtView (trial courts) | https://records.courts.alaska.gov/ | Referenced |
| Judges Information | https://courts.alaska.gov/judges/index.htm | Verified |

## 3. Court Structure

### Supreme Court Justices (5 total)

| Justice | Location | Appointed | Bio PDF |
|---------|----------|-----------|---------|
| **Susan M. Carney** (Chief Justice) | Fairbanks | 2016 | [smc.pdf](https://courts.alaska.gov/judges/docs/smc.pdf) |
| Dario Borghesan | Anchorage | 2020 | [db.pdf](https://courts.alaska.gov/judges/docs/db.pdf) |
| Jennifer S. Henderson | Anchorage | 2021 | [SCJSH.pdf](https://courts.alaska.gov/judges/docs/SCJSH.pdf) |
| Jude Pate | Juneau | 2023 | [scjp.pdf](https://courts.alaska.gov/judges/docs/scjp.pdf) |
| Aimee A. Oravec | Fairbanks | 2025 | Not yet available |

### Court of Appeals Judges (4 total)

| Judge | Location | Appointed | Bio PDF |
|-------|----------|-----------|---------|
| **Marjorie K. Allard** (Chief Judge) | Anchorage | 2012 | [mka.pdf](https://courts.alaska.gov/judges/docs/mka.pdf) |
| Tracey Wollenberg | Anchorage | 2017 | [tw.pdf](https://courts.alaska.gov/judges/docs/tw.pdf) |
| Timothy W. Terrell | Anchorage | 2020 | [twt.pdf](https://courts.alaska.gov/judges/docs/twt.pdf) |
| Ruthanne Beach | Anchorage | 2025 | Not yet available |

## 4. Case Search System

### Search Endpoints

| Function | URL Pattern | Status |
|----------|-------------|--------|
| Search Landing | `/CMSPublic/Search` | Verified |
| Quick Search | Header search box accepts case number or name | Verified |
| Case Number Search | `/CMSPublic/Search/CaseNumber?CaseNumber={number}` | Verified |
| Party Name Search | `/CMSPublic/Search/Party` | Verified |
| Attorney Search | `/CMSPublic/Search/Attorney` | Verified |

### Case Number Formats

| Court | Format | Example |
|-------|--------|---------|
| Supreme Court | S-##### | S-19135 |
| Court of Appeals | A-##### | A-10945 |
| Trial Court | #XX-##-#####XX | 3AN-07-20531CR, 4FA-23-01376CI |

## 5. Case Detail Pages

### Tab Structure (Verified)

All case detail pages share this tab structure:
- Case Summary
- Participants & Attorneys
- Record
- Docket
- Motions and Orders
- Briefs

### URL Patterns

| Tab | URL Pattern |
|-----|-------------|
| Case Summary | `/CMSPublic/Case/General?q={encrypted_id}` |
| Participants & Attorneys | `/CMSPublic/Case/Parties?q={encrypted_id}` |
| Record | `/CMSPublic/Case/Records?q={encrypted_id}` |
| Docket | `/CMSPublic/Case/Docket?q={encrypted_id}` |
| Motions and Orders | `/CMSPublic/Case/Motions?q={encrypted_id}` |
| Briefs | `/CMSPublic/Case/BriefSummary?q={encrypted_id}` |
| Subscribe | `/CMSPublic/Case/Subscribe?q={encrypted_id}` |

**Note**: The `q` parameter is a base64-encoded case identifier. Each case has a unique encrypted ID that cannot be predicted.

### Case Summary Tab Data (Verified)

- Case number and title (e.g., "S19135 Alex Koponen v. Vsevolod Romanov and Maria Sanders")
- Case status (Open/Closed)
- Full case caption
- Contact case manager (phone and email)
- Case type (e.g., "204 Appeal")
- Date filed
- Oral argument information (status, date/time, location, video link)
- **Opinions table**:
  - Number
  - Type (Opinion, MOJ, Summary Disposition)
  - Decision (Affirmed, Reversed, etc.)
  - Date
  - Citation (Pacific Reporter)
  - Document download link
- **Lower court information**:
  - Case number
  - Judgment date
  - Distribution date
  - Lower court or agency
  - Judge name
- Related appellate cases

### Docket Tab Data (Verified)

Two views available: "Docket By Date" (default) and "Docket By Category"

**Table columns**:
- Dkt# (docket number)
- Document (PDF icon/link when available)
- Item (description)
- Status
- Date Filed or Issued
- Filed or Issued By

**Document download URL**: `/CMSPublic/UserControl/OpenDocument?q={encrypted_id}`

**Status values observed**:
| Status | Description |
|--------|-------------|
| Filed | Document filed by party |
| Distributed | Court notice/order distributed |
| Issued | Court order issued |
| Complete | Brief filing completed |
| Received | Document received by court |
| Rejected | Document rejected by court |
| Removed | Entry removed (e.g., clerical error) |
| Lodged | Document lodged with court |

**Common entry types**:
- Docketing Statement/NOA (Notice of Appeal)
- Points on Appeal
- Designation of Transcript
- Original Briefing (Appellant's/Appellee's/Reply)
- Excerpt of Record
- Motions (to extend time, etc.)
- Orders (granting/denying motions)
- Notices (various court notices)
- Entry of Appearance
- 221 Certificate
- Bill of Costs & Affidavit
- Final Order/Judgment

## 6. Opinions System

### Opinion Landing Page
URL: `/CMSPublic/Home/AppellateOpinions`

### Opinion Types and URLs (Verified)

| Opinion Type | Court | URL | Precedential | Publication |
|--------------|-------|-----|--------------|-------------|
| Slip Opinions | Supreme Court | `/CMSPublic/Home/Opinions?isCOA=False` | Yes | Fridays 9AM |
| Slip Opinions | Court of Appeals | `/CMSPublic/Home/Opinions?isCOA=True` | Yes | Fridays 9AM |
| MO&Js | Supreme Court | `/CMSPublic/Home/MOJOpinions?isCOA=False` | No | Wednesdays 8AM |
| MO&Js | Court of Appeals | `/CMSPublic/Home/MOJOpinions?isCOA=True` | No | Wednesdays 8AM |
| Summary Dispositions | Court of Appeals | `/CMSPublic/Home/SummaryDispositions?isCOA=True` | No | Wednesdays 8AM |
| Published Orders | Supreme Court | `/CMSPublic/Home/PublishedOrders?isCOA=False` | Yes | Day of release |
| Case-Related Orders | Court of Appeals | `/CMSPublic/Home/CaseRelatedOrders` | No | Day of release |
| Bail Orders | Court of Appeals | `/CMSPublic/Home/BailOrders` | No | Day of release |

### Opinion Download
URL pattern: `/CMSPublic/UserControl/OpenOpinionDocument?q={encrypted_id}`

### Opinion Page Structure (Verified)

Opinions are grouped by release date (e.g., "Friday, December 19, 2025")

**Table columns**:
- Document (PDF download icon)
- Opinion Number (e.g., 7799)
- Case Number (link to case detail, e.g., S19135)
- Case Title (e.g., "Alex Koponen v. Vsevolod Romanov and Maria Sanders")
- Pacific Reporter Reference (when published)

### Retention Policies

| Type | Retention |
|------|-----------|
| Slip Opinions | Until published in Pacific Reporter |
| Published Orders | Until published in Pacific Reporter |
| MO&Js | 3 months on website |
| Summary Dispositions | 3 months on website |

### Opinion Notification
- Email listserv: http://list.state.ak.us/mailman/listinfo/ak-slip-opinions
- Archives: http://list.state.ak.us/pipermail/ak-slip-opinions/

## 7. Oral Arguments

### Live Streaming

| Court | Platform | URL |
|-------|----------|-----|
| Supreme Court | Gavel Alaska (KTOO) | https://www.ktoo.org/gavel/supreme-court/ |
| Supreme Court | 360 North | http://www.360north.org/alaska-supreme-court/ |
| Court of Appeals | Dedicated stream | https://stream.akcourts.gov/ |

**Note**: Court of Appeals streams are live only (not archived). Supreme Court has archived videos.

### Calendars (PDF)

| Court | URL |
|-------|-----|
| Supreme Court | https://public.courts.alaska.gov/web/scheduled/docs/oac-sc.pdf |
| Court of Appeals | https://public.courts.alaska.gov/web/scheduled/docs/oac-coa.pdf |

### Media Search
URL: `/CMSPublic/Search/Media`

### Locations
- **Anchorage**: Supreme Court courtroom, 5th floor, Boney Courthouse, 303 K Street
- **Fairbanks**: Courtroom 502, 5th floor, Rabinowitz Courthouse, 101 Lacey Street
- **Juneau**: Courtroom A, 1st floor, Dimond Courthouse, 123 4th Street

## 8. Case Types

| Code | Description |
|------|-------------|
| 204 Appeal | Standard appeals |
| 215 Sentence Appeal | Appeals of sentences only |
| 302 Petition for Hearing | Petition to Alaska Supreme Court for review of Court of Appeals decision |
| 402 Petition for Review | Another type of review petition |

## 9. Access Restrictions

### No Restrictions
- No login required for case search, docket viewing, or opinion access
- No date limitations for searching
- No rate limiting observed
- PDF downloads available directly without authentication
- No CAPTCHA on search forms

### Document Access Notes
- Some documents may be sealed or confidential (case-specific)
- Older MOJs and Summary Dispositions only available for 3 months on website (can be requested from clerk)
- Very old cases (pre-1960) may have limited digital availability
- Not all docket entries have downloadable documents (some are informational only)

## 10. Technical Implementation Notes

### Key Challenges

1. **Encrypted Case IDs**
   - URLs use encrypted/base64-encoded query parameters
   - Cannot generate URLs programmatically without searching first
   - Different encrypted IDs used for different tabs of same case
   - Solution: Extract links from search/browse interfaces

2. **Large Opinion Pages**
   - Opinion list pages can be very large (100+ KB) with no pagination
   - All opinions for all dates on single page
   - Grouped by release date (e.g., "Friday, December 19, 2025")
   - Need efficient parsing of large HTML documents

3. **PDF Calendars**
   - Oral argument calendars are PDFs, require PDF parsing

4. **Multiple Opinion Types**
   - Different precedential values and retention periods
   - MOJs and Summary Dispositions expire after 3 months

5. **No Direct API**
   - All data must be scraped from HTML pages
   - No JSON endpoints identified
   - No RSS feeds for opinions (only email listserv)

### Data Format
- HTML pages (no JSON API observed)
- Pagination exists for large search result sets (e.g., "1 to 10 of 1000 rows")
- Search results show both "Full Match" and "Partial Match" sections

## 11. Recommended Scraping Strategy

### For Opinions
1. Start with opinion list pages (slip opinions, MOJs, etc.)
2. Parse by release date groups - opinions organized by Friday/Wednesday dates
3. Extract case links from opinion tables to get encrypted case IDs
4. Download opinion PDFs directly via encrypted document URLs
5. Track release dates to avoid re-scraping old opinions
6. Handle different opinion types separately due to different retention policies

### For Dockets
1. **Option A**: Follow case links from opinion pages
2. **Option B**: Search by case number ranges if pattern can be determined
3. Parse all tabs for complete case information (Summary, Docket, Parties, etc.)
4. Queue document downloads for available PDFs
5. Track case status (Open/Closed) to determine update frequency

### For Oral Arguments
1. Download PDF calendars from known URLs
2. Parse PDF content to extract case numbers and dates
3. Cross-reference with case data to link arguments to cases
4. Consider live stream metadata if available via media search

## 12. Data Points to Capture

### Per Opinion
- Case number
- Case name
- Date filed
- Date decided
- Opinion type (slip, MOJ, summary disposition)
- Court (Supreme/Court of Appeals)
- Authoring judge
- Decision (affirmed, reversed, etc.)
- Citation (Pacific Reporter)
- Lower court case number
- Lower court judge
- PDF download URL
- Full text (extracted from PDF)

### Per Case
All of the above, plus:
- Docket entries
- Parties and attorneys
- Related cases
- Oral argument information
- Case status

## 13. Forms and Documents

### Docketing Statements

**Supreme Court**:
- Docketing Statement A (Rule 204 and 218 Appeals): https://courts.alaska.gov/appellate/docs/sct-a.pdf
- Docketing Statement B (Petitions/Original Applications): https://courts.alaska.gov/appellate/docs/sct-b.pdf

**Court of Appeals**:
- Docketing Statement A (Felony Merit Appeals): https://courts.alaska.gov/appellate/docs/coa-a.pdf
- Docketing Statement B (Petitions/Original Applications): https://courts.alaska.gov/appellate/docs/coa-b.pdf
- Docketing Statement C (Extradition/Juvenile Appeals): https://courts.alaska.gov/appellate/docs/coa-c.pdf
- Docketing Statement D (Misdemeanor Merit Appeals): https://courts.alaska.gov/appellate/docs/coa-d.pdf
- Docketing Statement E (Sentence Appeals): https://courts.alaska.gov/appellate/docs/coa-e.pdf

## 14. Historical Data

- All opinions and some MOJs back to 1960 available in Alaska Case Law Service
- URL: https://govt.westlaw.com/akcases/Index

## 15. Contact Information

**Appellate Clerk's Office**:
- Phone: 907-264-0608
- Fax: 907-264-0878
- Email: corrections@akcourts.gov (for opinion errors)
- Location: 303 K Street, Anchorage, Alaska 99501

## 16. Comparison to Other States

### Similar to Connecticut
- Both use case management systems with multiple tabs for case information
- Both provide docket information
- Both have downloadable opinions

### Differences from Connecticut
- Alaska has separate Supreme Court and Court of Appeals
- Alaska provides more extensive oral argument video archives (Supreme Court)
- Alaska has a more structured opinion notification system
- Alaska's case search is more user-friendly with better search options

### Similar to Alabama
- Both have Supreme Court and Court of Appeals
- Both provide public docket access without login
- Both publish opinions in PDF format
- Both track oral arguments
- Both use encrypted/non-sequential identifiers

### Differences from Alabama
- Alaska: Encrypted query parameters vs Alabama's GUID system
- Alaska: Multiple opinion types with different precedential values
- Alaska: Longer retention (until published vs. Alabama's access windows)
- Alaska: Live streaming infrastructure for oral arguments
- Alaska: No release lists - opinions organized by date on single pages
- Alaska: Simpler, more traditional website vs Alabama's modern portal design
- Alaska: Historical depth (back to 1960) vs Alabama's 2022 cutoff for documents
- Alaska: Email listserv vs Alabama's portal-based notifications
- Alaska: Separate case management system vs Alabama's integrated portal

## 17. Implementation Recommendations

### Scraper Structure
```
juriscraper/sd/state/alaska/
├── __init__.py
├── alaska.py           # Supreme Court opinions
├── alaskactapp.py      # Court of Appeals opinions
└── RESEARCH.md         # This file
```

### Key Features to Implement

1. **Opinion Scrapers**:
   - Scrape slip opinions (weekly, Fridays 9 AM)
   - Scrape MOJs (weekly, Wednesdays 8 AM)
   - Scrape summary dispositions (Court of Appeals)
   - Scrape published orders

2. **Case Detail Scraper**:
   - Extract case information from case detail pages
   - Parse docket entries
   - Extract party/attorney information

3. **Oral Argument Scraper**:
   - Monitor oral argument calendars
   - Extract video links (Supreme Court only)

4. **Judge Information**:
   - Scrape current justices/judges
   - Extract bio PDF links
   - Track appointment dates

## 18. Example Case

**S-19135: Alex Koponen v. Vsevolod Romanov and Maria Sanders**
- Case URL: https://appellate-records.courts.alaska.gov/CMSPublic/Case/General?q=w6sobc/DATfbLFego/8maQ==
- Status: Closed
- Filed: 6/10/2024
- Opinion: #7799, Affirmed 12/19/2025
- Lower court: 4FA-23-01376CI (Superior Court, Judge Kirk Schwalm)
- 36 docket entries from initial filing to final disposition

## 19. References

- Main website: https://courts.alaska.gov/
- Appellate page: https://courts.alaska.gov/appellate/index.htm
- Case Management System: https://appellate-records.courts.alaska.gov/
- Judges page: https://courts.alaska.gov/judges/index.htm
- Opinion notification listserv: http://list.state.ak.us/mailman/listinfo/ak-slip-opinions
- Appellate Procedure Rules: https://courts.alaska.gov/rules/docs/app.pdf
- Alaska Case Law Service (Westlaw): https://govt.westlaw.com/akcases/Index
- Gavel Alaska (Supreme Court video): http://www.360north.org/alaska-supreme-court/
- Court of Appeals live stream: https://stream.akcourts.gov/
