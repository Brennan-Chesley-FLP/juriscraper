# Florida Courts Research

## Court Structure

Florida has a comprehensive appellate court system with the Supreme Court at the apex and six District Courts of Appeal serving as intermediate appellate courts.

### 1. Supreme Court of Florida
- **Website**: https://supremecourt.flcourts.gov/
- Highest court in Florida
- 7 Justices (1 Chief Justice + 6 Associate Justices)
- At least 5 Justices must participate in every case
- At least 4 must agree for a decision to be reached
- Location: 500 South Duval Street, Tallahassee, FL 32399-1925
- Phone: (850) 488-0125

### 2. District Courts of Appeal (6 Districts)

| District | Website | Geographic Coverage |
|----------|---------|---------------------|
| 1st DCA | https://1dca.flcourts.gov/ | Northwest Florida (Panhandle) |
| 2nd DCA | https://2dca.flcourts.gov/ | West Central Florida |
| 3rd DCA | https://3dca.flcourts.gov/ | South Florida (Miami-Dade, Monroe) |
| 4th DCA | https://4dca.flcourts.gov/ | Southeast Florida |
| 5th DCA | https://5dca.flcourts.gov/ | Central Florida |
| 6th DCA | https://6dca.flcourts.gov/ | Tampa Bay Area (newly created) |

### 3. Trial Courts - Circuit (20 Judicial Circuits)
- Courts of general jurisdiction
- Handle felony criminal cases and major civil cases
- Appeals go to District Courts of Appeal

### 4. Trial Courts - County
- Limited jurisdiction courts
- Handle misdemeanors, small claims, and traffic

---

## Key URLs and URL Patterns

### Main Portals
- **Florida Courts Main**: https://www.flcourts.gov/
- **Supreme Court**: https://supremecourt.flcourts.gov/
- **ACIS (Appellate Case Information System)**: https://acis.flcourts.gov/

### ACIS - Appellate Case Information System
- **Home**: https://acis.flcourts.gov/portal/home
- **Case Search**: https://acis.flcourts.gov/portal/search/case
- **Party Search**: https://acis.flcourts.gov/portal/search/party
- **Oral Argument Search**: https://acis.flcourts.gov/portal/search/calendar
- **Document Search**: https://acis.flcourts.gov/portal/search/document
- **Publication Search**: https://acis.flcourts.gov/portal/search/publication

### ACIS Case Detail URL Pattern
- `https://acis.flcourts.gov/portal/court/{court-uuid}/case/{case-uuid}`
- Example: `https://acis.flcourts.gov/portal/court/68f021c4-6a44-4735-9a76-5360b2e8af13/case/93a367d7-c7d6-4ed7-b125-056e257c8694`

### Supreme Court URLs
- **Opinions**: https://supremecourt.flcourts.gov/case-information/opinions
- **Most Recent Opinions**: https://supremecourt.flcourts.gov/Opinions/Most-Recent-Opinions
- **Opinion Search (All Appellate Courts)**: https://supremecourt.flcourts.gov/case-information/opinions/Opinion-Search-For-All-Appellate-Courts
- **Justices**: https://supremecourt.flcourts.gov/the-court/about-the-court/justices
- **Oral Arguments**: https://supremecourt.flcourts.gov/case-information/Oral-Arguments/oral-argument-summaries-and-schedule
- **Docket Search (Legacy)**: http://onlinedocketssc.flcourts.org/
- **Admin Orders**: https://supremecourt.flcourts.gov/case-information/Case-Info/admin-orders
- **Dispositions**: https://supremecourt.flcourts.gov/case-information/Case-Info/dispositions

### Opinion Search API
- **Endpoint**: `https://flcourts-media.flcourts.gov/_search/opinions`
- **Parameters**: `query=&siteaccess=supreme2&searchtype=opinions`

### Opinion Archive
- **FSU Law Library Archive**: https://library.law.fsu.edu/Digital-Collections/flsupct/index.html
  - Contains opinions since 1990 and briefs
- Opinions on court website available from September 24, 1999 to present

---

## Case Number Patterns

### Supreme Court
- Format: `SC{YY}-{seq}` or `{YYYY}-{seq}`
- Example: `SC24-123` or `2024-123`

### District Courts of Appeal
- Format: `{D}D{YY}-{seq}` where D = district number
- Example: `1D24-1234` (1st DCA, 2024, case 1234)

---

## Current Justices - Supreme Court

| Name | Position | Appointed | Justice Number | Merit Retention Vote |
|------|----------|-----------|----------------|---------------------|
| Carlos G. Muñiz | Chief Justice | 2019 | 89th | 2026 |
| Jorge Labarga | Justice | 2009 | 84th | 2028 |
| John D. Couriel | Justice | 2020 | 90th | 2028 |
| Jamie R. Grosshans | Justice | 2020 | 91st | 2028 |
| Renatha Francis | Justice | 2022 | 92nd | 2030 |
| Meredith L. Sasso | Justice | 2023 | 93rd | 2030 |
| Adam S. Tanenbaum | Justice | January 14, 2026 | 94th | TBD |

### Justice Bio URLs
| Name | Bio URL |
|------|---------|
| Chief Justice Carlos G. Muñiz | https://supremecourt.flcourts.gov/the-court/about-the-court/justices/chief-justice-carlos-g.-muniz |
| Justice Jorge Labarga | https://supremecourt.flcourts.gov/the-court/about-the-court/justices/justice-jorge-labarga |
| Justice John D. Couriel | https://supremecourt.flcourts.gov/the-court/about-the-court/justices/justice-john-d.-couriel |
| Justice Jamie R. Grosshans | https://supremecourt.flcourts.gov/the-court/about-the-court/justices/justice-jamie-r.-grosshans |
| Justice Renatha Francis | https://supremecourt.flcourts.gov/the-court/about-the-court/justices/justice-renatha-francis |
| Justice Meredith L. Sasso | https://supremecourt.flcourts.gov/the-court/about-the-court/justices/justice-meredith-l.-sasso |
| Justice Adam S. Tanenbaum | https://supremecourt.flcourts.gov/the-court/about-the-court/justices/justice-adam-s.-tanenbaum |

---

## Opinion Types and Publication

### Supreme Court Jurisdiction

**Mandatory Jurisdiction** (Court MUST review):
- Final orders imposing death sentences
- DCA decisions declaring a state statute or state constitutional provision invalid
- Bond validations
- Certain Public Service Commission orders on utility rates and services

**Discretionary Jurisdiction** (Court MAY review):
- DCA decisions expressly declaring valid a state statute
- DCA decisions construing a provision of state or federal constitution
- DCA decisions affecting a class of constitutional or state officers
- DCA decisions directly conflicting with another DCA or Supreme Court decision
- Cases certified as great public importance
- Certified direct conflict
- Certified judgment of trial courts
- Certified questions from federal courts

### Opinion Release Schedule
- **Regular Release**: 11 a.m. each Thursday
- **Summer Recess**: July into August (regular releases suspended)
- **Winter Recess**: Christmas and New Year's holidays
- **Out-of-Calendar Releases**: Possible at any time for time-sensitive cases

### Publication
- Opinions subject to formal revision before publication in **Southern Reporter, 3rd Series**
- Not final until motions for rehearing are disposed of

---

## Access Restrictions

### No Login Required
- Public access to ACIS case dockets and available case documents
- Opinion searches and downloads
- No rate limiting observed during research

### Login Required (ACIS Registered Users)
- Attorneys of record
- Judges
- Clerks of court
- Public agencies
- Self-represented litigants
- Full access available the day following registration acceptance

---

## Technical Implementation Notes

### Website Platform
- Next.js-based website (modern React framework)
- Multiple domains for different courts
- API-driven content via `flcourts-media.flcourts.gov`

### ACIS Architecture
- Thomson Reuters Court Management Solutions platform
- Vue.js/Vuetify frontend
- RESTful API backend
- UUID-based court and case identifiers
- Document storage at `acis-api.flcourts.gov/dms/documents/{uuid}`

### Opinion Search Architecture
- Search endpoint: `flcourts-media.flcourts.gov/_search/opinions`
- Parameters include:
  - `query`: Search text
  - `siteaccess`: Court identifier (e.g., `supreme2`)
  - `searchtype`: Type of search (e.g., `opinions`)

### Data APIs Observed
- Content API: `flcourts-media.flcourts.gov/api/data/fetch`
- Footer API: `flcourts-media.flcourts.gov/api/footer/{id}`
- Supports pagination with `limit` and `parentLocationID` parameters

---

## Example Cases

### Supreme Court
- **State of Florida v. Zachary Wester** (01/21/26)
  - ACIS: https://acis.flcourts.gov/portal/court/68f021c4-6a44-4735-9a76-5360b2e8af13/case/93a367d7-c7d6-4ed7-b125-056e257c8694

- **Advisory Opinion to the Attorney General Re: Adult Personal Use of Marijuana** (01/20/26)
  - ACIS: https://acis.flcourts.gov/portal/court/68f021c4-6a44-4735-9a76-5360b2e8af13/case/cef46eec-a0b2-4dd9-b56c-70d02e031fbe

- **LULAC Florida, Inc., et al. v. Florida Public Service Commission, et al.** (01/12/26)
  - ACIS: https://acis.flcourts.gov/portal/court/68f021c4-6a44-4735-9a76-5360b2e8af13/case/ba78f857-3ba2-4fe7-bac8-da15ca5084d9

---

## Recommended Scraper Architecture

### 1. ACIS-Based Scraper (Primary)
**Source**: https://acis.flcourts.gov/portal/search

**Approach**:
1. Use ACIS search API to find cases
2. Extract case metadata from search results
3. Navigate to case detail pages for full docket
4. Download documents via DMS API

**Data Available**:
- Case number
- Case title/parties
- Case category
- Filed date
- Originating court case number
- Case status (open/closed)
- Docket entries
- Documents (PDFs)

**Courts Covered**:
- Supreme Court of Florida
- 1st District Court of Appeal
- 2nd District Court of Appeal
- 3rd District Court of Appeal
- 4th District Court of Appeal
- 5th District Court of Appeal
- 6th District Court of Appeal

### 2. Supreme Court Opinion Scraper
**Source**: https://supremecourt.flcourts.gov/case-information/opinions

**Approach**:
1. Query opinion search API
2. Parse results for opinion metadata
3. Extract PDF download links
4. Cross-reference with ACIS for full case details

### 3. Oral Arguments Scraper
**Source**: https://supremecourt.flcourts.gov/case-information/Oral-Arguments/oral-argument-summaries-and-schedule

**Data Available**:
- Argument date and time
- Case information
- Video/audio recordings (via YouTube)

### Scraping Considerations
- ACIS uses UUIDs for courts and cases (not sequential IDs)
- Court UUID for Supreme Court: `68f021c4-6a44-4735-9a76-5360b2e8af13`
- Modern React/Vue.js frontends may require JavaScript rendering
- API endpoints are discoverable and can be used directly
- No apparent rate limiting, but respectful scraping recommended

---

## Additional Resources

- **User Guide**: https://www.flcourts.gov/content/download/861390/file/ACIS-User-Guide.pdf
- **Registration Guide**: https://www.flcourts.gov/ACIS
- **Florida Bar Rules of Procedure**: https://www.floridabar.org/rules/ctproc/
- **Westlaw (historical opinions)**: http://next.westlaw.com/
- **Florida Law Weekly**: http://www.floridalawweekly.com/
