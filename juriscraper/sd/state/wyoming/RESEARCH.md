# Wyoming Courts Research

## Court Structure

Wyoming has a unified judicial system with the Supreme Court as the sole appellate court. Wyoming is notable for having no intermediate appellate court, meaning all appeals go directly to the Supreme Court.

### 1. Supreme Court of Wyoming
- **Website**: https://www.wyocourts.gov/supreme-court/
- Highest and only appellate court in Wyoming (court of last resort)
- 5 Justices serving 8-year terms through merit selection and retention elections
- Location: 2301 Capitol Avenue, Cheyenne, WY 82001
- Chief Justice: Lynne Boomgaarden (selected by justices for 4-year term)

#### Jurisdiction
- Final appellate jurisdiction over all cases from district courts
- Original jurisdiction for petitions for extraordinary relief (mandamus, prohibition, etc.)
- Administrative supervision over the Wyoming State Bar
- Regulates the practice of law and admits new attorneys

#### Justice Selection
- Merit-based selection: Judicial Nominating Commission submits 3 nominees to the Governor
- After 1 year, justice stands for retention in next general election
- 8-year terms with nonpartisan retention ballots
- Requirements: Lawyer with 9+ years experience, 30+ years old, US citizen, 3+ years Wyoming residency
- Mandatory retirement at age 70

### 2. Chancery Court
- **Website**: https://www.wyocourts.gov/court/chancery-court/
- Specialized court for business matters, trusts, and estates
- Created to expeditiously handle commercial disputes
- Orders and decisions published per Wyo. Stat. Ann. § 5-13-104(f)

### 3. District Courts
- **Website**: https://www.wyocourts.gov/district-court/
- General jurisdiction trial courts
- 9 judicial districts covering Wyoming's 23 counties
- Handle civil, criminal, juvenile, and probate matters

### 4. Circuit Courts
- **Website**: https://www.wyocourts.gov/circuit-courts/
- Limited jurisdiction courts
- Handle misdemeanors, small claims, civil cases up to $50,000

### 5. Municipal Courts
- Handle city ordinance violations

---

## Key URLs and URL Patterns

### Main Portal
- **Wyoming Judicial Branch Home**: https://www.wyocourts.gov/
- **Legacy Domain** (redirects): https://www.courts.state.wy.us
- **Supreme Court Page**: https://www.wyocourts.gov/supreme-court/
- **Chancery Court Page**: https://www.wyocourts.gov/court/chancery-court/

### Opinions and Decisions

#### Supreme Court Opinions
- **Opinions Search Page**: https://www.wyocourts.gov/wy-supreme-court-opinions/
- **Opinion Summaries**: https://www.wyocourts.gov/supreme-court-opinion-summaries/

#### Chancery Court Opinions
- **Chancery Court Orders and Decisions**: https://www.wyocourts.gov/chancery-court-orders-and-decisions/

#### Opinion PDF URL Patterns
- **Supreme Court**: `https://documents.courts.state.wy.us/Opinions/{filename}.pdf`
  - Example: `https://documents.courts.state.wy.us/Opinions/Velasquez S-25-0114.pdf`
  - Filenames vary but typically include case name and docket number
- **Chancery Court**: `https://documents.courts.state.wy.us/ChanceryOpinions/{opinion_id}.pdf`
  - Example: `https://documents.courts.state.wy.us/ChanceryOpinions/2026 WYCH 2.pdf`

### Case Search and Dockets
- **Public Docket Search (C-Track)**: https://efiling.courts.state.wy.us/public/caseSearch.do
- **Case View URL Pattern**: `https://efiling.courts.state.wy.us/public/caseView.do?csIID={case_id}`
- **Issue Search**: https://efiling.courts.state.wy.us/public/issueSearch.do
- **Participant Search**: https://efiling.courts.state.wy.us/public/publicActorSearch.do

### Oral Arguments
- **Calendar**: https://www.wyocourts.gov/calendar/
- **Live Stream**: https://www.wyocourts.gov/live-stream/
- Individual oral argument events linked from calendar (e.g., `https://www.wyocourts.gov/calendar/oral-arguments-47/`)

### Judges/Justices
- **Supreme Court Justices**: https://www.wyocourts.gov/supreme-court/ (scroll to "Meet the Justices" section)
- Justice bios displayed in modal dialogs on the Supreme Court page

### Court Rules
- **Court Rules**: https://www.wyocourts.gov/court-rules/
- **Rule Amendments**: https://www.wyocourts.gov/rule-amendments/
- **General Orders**: https://www.wyocourts.gov/general-orders/

### eFiling
- **eFiling Portal**: https://www.wyocourts.gov/efiling/
- Available for Supreme Court, district courts, and chancery court
- Phased implementation underway for circuit courts

---

## Current Justices - Supreme Court of Wyoming

| Position | Name | Appointment Date | Term Expires | Retention |
|----------|------|------------------|--------------|-----------|
| Chief Justice | Lynne Boomgaarden | February 2018 | January 2029 | November 2028 |
| Justice | Kari Gray | October 2018 | January 2029 | November 2028 |
| Justice | John G. Fenn | January 2022 | January 2033 | November 2032 |
| Justice | Robert C. Jarosh | March 2024 | January 2027 | November 2026 |
| Justice | Bridget Hill | May 2025 | January 2028 | November 2026 |

### Justice Bio URLs
Justice biographies are displayed via modal dialogs on the Supreme Court page. The modals are triggered by clicking on the justice's name/card. Modal anchors:
- Chief Justice Lynne Boomgaarden: `#teamModal5739`
- Justice Kari Gray: `#teamModal5740`
- Justice John G. Fenn: `#teamModal5741`
- Justice Robert C. Jarosh: `#teamModal5742`
- Justice Bridget Hill: `#teamModal17908`

**Note**: Bio URLs are modal anchors on `https://www.wyocourts.gov/supreme-court/`, not separate pages.

---

## Opinion Types and Document Categories

### Supreme Court Opinions
- **Opinion ID Format**: `YYYY WY #` (e.g., "2026 WY 11")
- **Docket Number Format**: `S-YY-NNNN` (e.g., "S-25-0114")
  - S = Supreme Court
  - YY = Year
  - NNNN = Sequential case number

### Chancery Court Decisions
- **Opinion ID Format**: `YYYY WYCH #` (e.g., "2026 WYCH 2")
- **Docket Number Format**: `CH-YYYY-NNNNNNN` (e.g., "CH-2025-0000013")

### Case Types (from C-Track)
- **Groups**: Direct Appeal, Original Proceeding, Professional Regulation, Rule 12.09(b) Certification
- **Types**: Criminal, Civil, Petition for writ of review, Certified Question, Attorney, Judge/Justice, Other, Bill of Exceptions, Unauthorized Practice of Law
- **Statuses**: Active, Unmatured, Matured, Brief Only, Oral/Under Advisement, Decided, Closed, etc.

---

## Data Availability

| Content | Date Range | Source |
|---------|------------|--------|
| Supreme Court Opinions | 2006 - present | https://www.wyocourts.gov/wy-supreme-court-opinions/ |
| Chancery Court Orders | 2023 - present | https://www.wyocourts.gov/chancery-court-orders-and-decisions/ |
| Public Docket (C-Track) | Historical | https://efiling.courts.state.wy.us/public/caseSearch.do |
| Oral Arguments Calendar | Current | https://www.wyocourts.gov/calendar/ |

**Note**: "Opinions and orders published prior to 2006 are not available in this search" per the website.

---

## Access Restrictions

### No Login Required
- All Supreme Court opinions (2006+)
- All Chancery Court orders and decisions
- Public docket search (C-Track)
- Court calendar and oral arguments schedule
- Justice information

### eFiling Login Required
- Document filing and case management
- C-Track authenticated features

### No Known Rate Limits
- No explicit rate limiting mentioned
- Standard web scraping etiquette should be observed

---

## Technical Implementation Notes

### Website Architecture
- **Primary Domain**: www.wyocourts.gov (WordPress-based)
- **Legacy Domain**: www.courts.state.wy.us (redirects to wyocourts.gov)
- **Documents Server**: documents.courts.state.wy.us
- **eFiling/Case Search**: efiling.courts.state.wy.us (C-Track system)

### Opinions Page Structure
The opinions search page at `https://www.wyocourts.gov/wy-supreme-court-opinions/` contains:
- Search form with fields: Start Date, End Date, Appellant, Appellee
- Results table with columns: Opinion ID, Publish Date, Appellant, Appellee, Docket Number
- Pagination controls (25/50/75 per page)
- Opinion ID links directly to PDF

### C-Track Case Search Structure
The public case search at `https://efiling.courts.state.wy.us/public/caseSearch.do`:
- Search fields: Case Number, Full Title, Group, Status, Type, Docketed Date From/To, Subtype
- "Exclude Closed" checkbox
- Results table with: Case Number, Short Title, Status, Type, Subtype, Docketed Date
- Case numbers link to detail view

### Case Detail Page Structure
Each case view page contains:
- Case heading: Number, Docketed Date, Status, Original Court, Case Type, Short/Full Title
- Party Information: Role, Party Name, Attorney(s)
- Pending Ticklers: Due dates and status
- Case Decision Information: Issues, Opinion Number, Citation
- Docket Information: Filing Date, Document Description, Entry Type/Subtype, Status

### JavaScript Requirements
- Main opinions pages work without JavaScript (paginated server-side)
- C-Track requires JavaScript for some functionality
- Calendar uses JavaScript for date navigation

### PDF Format
- Opinions provided as Adobe Acrobat PDF documents
- Direct download via URL patterns

---

## Example Cases

### Recent Supreme Court Opinions (January 2026)
| Opinion ID | Publish Date | Appellant | Appellee | Docket Number |
|------------|--------------|-----------|----------|---------------|
| 2026 WY 11 | 1/22/2026 | Jeremy S. Velasquez | The State of Wyoming | S-25-0114 |
| 2026 WY 10 | 1/22/2026 | Manuel Armenta Serrano | The State of Wyoming | S-25-0257 |
| 2026 WY 9 | 1/22/2026 | Christine Rhayanna Allemand | The State of Wyoming | S-25-0233 |
| 2026 WY 8 | 1/15/2026 | Russell Lee Lynch | The State of Wyoming | S-25-0140 |
| 2026 WY 1 | 1/6/2026 | State of Wyoming et al. | Danielle Johnson et al. | S-24-0326 |

### Recent Chancery Court Orders (January 2026)
| Opinion ID | Publish Date | Plaintiff | Defendant | Docket Number |
|------------|--------------|-----------|-----------|---------------|
| 2026 WYCH 2 | 1/19/2026 | Sapphire Strategic Advisory, LLC | Altius Strategic Consulting, LLC | CH-2025-0000013 |
| 2026 WYCH 1 | 1/14/2026 | Sapphire Strategic Advisory, LLC | Altius Strategic Consulting LLC | CH-2025-0000013 |

---

## Example API/Scraping URLs

```
# Supreme Court Opinions Search (no filters - returns all)
GET https://www.wyocourts.gov/wy-supreme-court-opinions/
# Click "Search" button to load results

# Chancery Court Orders Search
GET https://www.wyocourts.gov/chancery-court-orders-and-decisions/
# Click "Search" button to load results

# Supreme Court Opinion PDF
GET https://documents.courts.state.wy.us/Opinions/Velasquez S-25-0114.pdf

# Chancery Court Opinion PDF
GET https://documents.courts.state.wy.us/ChanceryOpinions/2026 WYCH 2.pdf

# C-Track Public Case Search
GET https://efiling.courts.state.wy.us/public/caseSearch.do

# C-Track Case Detail View
GET https://efiling.courts.state.wy.us/public/caseView.do?csIID=29588

# C-Track Issue Search
GET https://efiling.courts.state.wy.us/public/issueSearch.do

# C-Track Participant Search
GET https://efiling.courts.state.wy.us/public/publicActorSearch.do

# Oral Arguments Calendar
GET https://www.wyocourts.gov/calendar/

# Court Rules
GET https://www.wyocourts.gov/court-rules/

# Email Updates Subscription
GET https://public.govdelivery.com/accounts/WYJB/subscriber/new?qsp=CODE_RED
```

---

## Notes

1. **No Intermediate Appellate Court**: Wyoming is one of only 11 states without an intermediate appellate court. All appeals go directly from district courts to the Supreme Court.

2. **Merit Selection**: Wyoming uses a merit-based judicial selection system (Missouri Plan) rather than direct election. The Judicial Nominating Commission screens candidates.

3. **Chancery Court**: A specialized court established to handle business disputes, trusts, and estates expeditiously. Similar to Delaware's Court of Chancery.

4. **C-Track System**: The eFiling and case management system is powered by C-Track, a browser-based CMS for appellate courts.

5. **Opinion Availability**: Opinions prior to 2006 are not available through the website search.

6. **Live Streaming**: Oral arguments are available via live stream, though trial court livestreams are currently unavailable.

7. **WordPress Platform**: The main wyocourts.gov site appears to be WordPress-based (evidenced by /wp/ paths and JQMIGRATE console messages).

8. **Justice Bridget Hill**: Newest justice, appointed May 2025. Previously served as Wyoming Attorney General (2019-2025).

9. **Five Justices**: The Supreme Court has exactly 5 justices, with the Chief Justice selected by the justices themselves for a 4-year term.

10. **8-Year Terms**: Wyoming Supreme Court justices serve 8-year terms, longer than many states.
