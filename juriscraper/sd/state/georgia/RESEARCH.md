# Georgia Courts Research

## Court Structure

Georgia has a two-tier appellate court system with the Supreme Court of Georgia at the apex and the Court of Appeals of Georgia as the intermediate appellate court.

### 1. Supreme Court of Georgia
- **Website**: https://www.gasupreme.us/
- Highest court in Georgia
- 9 Justices (1 Chief Justice + 1 Presiding Justice + 7 Justices)
- Location: Nathan Deal Judicial Center, 330 Capitol Avenue, S.E., 1st Floor, Suite 1100, Atlanta, Georgia 30334
- Phone: (404) 656-3470
- Fax: (404) 656-2253
- Hours: Monday-Friday, 8:30 a.m. to 4:30 p.m. EST/EDT

### 2. Court of Appeals of Georgia
- **Website**: https://www.gaappeals.gov/ (recently migrated from gaappeals.us)
- Intermediate appellate court
- 15 Judges serving in 5 divisions
- Established in 1906
- Location: Nathan Deal Judicial Center, 330 Capitol Ave., S.E., 1st Floor, Suite 1601, Atlanta, Georgia 30334
- Phone: (404) 656-3450

---

## Key URLs and URL Patterns

### Supreme Court of Georgia

#### Main Portal
- **Home**: https://www.gasupreme.us/
- **E-file**: https://www.gasupreme.us/sced/
- **Docket Search**: https://www.gasupreme.us/docket-search/
- **Opinions**: https://www.gasupreme.us/{YYYY}-opinions/ (e.g., https://www.gasupreme.us/2026-opinions/)
- **Forthcoming Opinions**: https://www.gasupreme.us/opinions/forthcoming-opinions/
- **Oral Arguments**: https://www.gasupreme.us/calendar-list/
- **Oral Argument Webcast**: https://www.gasupreme.us/watch/
- **Justices**: https://www.gasupreme.us/court-information/biographies/

#### Opinion PDF URL Pattern
- `https://www.gasupreme.us/wp-content/uploads/{YYYY}/{MM}/{case_number}.pdf`
- Example: `https://www.gasupreme.us/wp-content/uploads/2026/01/s25a0994.pdf`

#### Opinion Summary PDF URL Pattern
- `https://www.gasupreme.us/wp-content/uploads/{YYYY}/{MM}/{Month}{Day}Ops.pdf`
- Example: `https://www.gasupreme.us/wp-content/uploads/2026/01/Jan21Ops.pdf`

#### Docket System (Embedded iFrame)
- Docket search is an embedded iframe with search by case number
- Shows cases docketed in the last 5 years
- Search Type: By Case Number

### Court of Appeals of Georgia

#### Main Portal
- **Home**: https://www.gaappeals.gov/
- **Docket Search**: https://www.gaappeals.gov/docket-search/
- **Opinion Search**: https://www.gaappeals.gov/opinion-search/
- **Judges**: https://www.gaappeals.gov/judges/
- **Oral Arguments**: https://www.gaappeals.gov/oral-arguments/
- **eFile**: https://www.gaappeals.gov/efile/

#### Opinion Search URL Pattern
- `https://www.gaappeals.gov/wp-content/themes/benjamin/docket/docketdate/results_all.php?OPstartDate={DD}-{M}-{YYYY}&OPendDate={DD}-{M}-{YYYY}`
- Example: `https://www.gaappeals.gov/wp-content/themes/benjamin/docket/docketdate/results_all.php?OPstartDate=22-1-2026&OPendDate=22-1-2026`

#### Docket Search URL Pattern
- `https://www.gaappeals.gov/wp-content/themes/benjamin/docket/results_all.php?searchterm={case_number}`
- Example: `https://www.gaappeals.gov/wp-content/themes/benjamin/docket/results_all.php?searchterm=A25A1439`

#### Case Detail URL Pattern
- `https://www.gaappeals.gov/wp-content/themes/benjamin/docket/results_one_record.php?docr_case_num={case_number}`
- Example: `https://www.gaappeals.gov/wp-content/themes/benjamin/docket/results_one_record.php?docr_case_num=A25A1439`

#### Opinion/Order PDF Download URL Pattern
- `https://efast.gaappeals.us/download?filingId={uuid}`
- Example: `https://efast.gaappeals.us/download?filingId=387bb277-f17a-4c14-b014-8a8149b7e6f8`

---

## Case Number Patterns

### Supreme Court of Georgia
- Format: `S{YY}{Letter}{seq}`
- The "S" prefix indicates Supreme Court
- YY = 2-digit year when case was calendared
- Letter = Case type designation
- seq = Sequential case number

#### Case Type Letter Designations:
| Letter | Description |
|--------|-------------|
| A | Direct appeal from superior court, state court, probate court, juvenile court, or special courts |
| B | Petition to appoint a Special Master in disciplinary proceedings |
| C | Petition for writ of certiorari to review Court of Appeals decision |
| D | Discretionary application to appeal (must be decided within 30 days) |
| E | Petition for certificate of probable cause in death sentence habeas corpus cases |
| F | Direct appeal in domestic relations cases (Family Law Pilot Project, pre-2017) |
| G | Granted petition for writ of certiorari |
| H | Petition for certificate of probable cause in post-conviction habeas corpus |
| I | Interlocutory application to appeal (must be decided within 45 days) |
| J | Judicial Qualifications Commission matters before formal charges |
| M | Emergency motion to stay when notice of appeal filed but not yet docketed |
| O | Petition filed without prior lower court review |
| P | Automatic direct appeal in death sentence capital cases |
| Q | Certified questions of law from federal courts (typically 11th Circuit) |
| R | Interim appellate review in death penalty pre-trial matters |
| T | Request for extension of time to file notice of appeal/application/petition |
| U | Review of State Bar Unauthorized Practice of Law advisory opinions |
| W | Matters involving cases with scheduled execution |
| X | Cross-appeal (see 'A' cases) |
| Y | Attorney discipline case from State Bar of Georgia |
| Z | Appeal from Judicial Qualifications Commission or Office of Bar Admissions |

Examples:
- `S25A0994` - Direct appeal, 2025, case 994
- `S25Y0888` - Attorney discipline case, 2025, case 888
- `S26Y0121` - Attorney discipline case, 2026, case 121

### Court of Appeals of Georgia
- Format: `A{YY}{Letter}{seq}`
- The "A" prefix indicates Court of Appeals
- YY = 2-digit year
- Letter = Case type designation
- seq = Sequential case number

#### Case Type Letter Designations:
| Letter | Description |
|--------|-------------|
| A | Direct appeal |
| D | Discretionary application |
| I | Interlocutory application |

Examples:
- `A25A1439` - Direct appeal, 2025, case 1439
- `A26D0275` - Discretionary application, 2026, case 275
- `A26I0110` - Interlocutory application, 2026, case 110

---

## Current Justices - Supreme Court of Georgia

| Name | Position | Appointed | Bio URL |
|------|----------|-----------|---------|
| Nels S.D. Peterson | Chief Justice | 2016 | https://www.gasupreme.us/court-information/biographies/justice-nels-s-d-peterson/ |
| Sarah Hawkins Warren | Presiding Justice | - | https://www.gasupreme.us/court-information/biographies/justice-sarah-hawkins-warren/ |
| Charles J. Bethel | Justice | - | https://www.gasupreme.us/court-information/biographies/justice-charles-j-bethel/ |
| John J. Ellington | Justice | - | https://www.gasupreme.us/court-information/biographies/justice-john-j-ellington/ |
| Carla Wong McMillian | Justice | - | https://www.gasupreme.us/court-information/biographies/justice-carla-wong-mcmillian/ |
| Shawn Ellen LaGrua | Justice | - | https://www.gasupreme.us/court-information/biographies/justice-shawn-ellen-lagrua/ |
| Verda M. Colvin | Justice | - | https://www.gasupreme.us/court-information/biographies/justice-verda-m-colvin/ |
| Andrew A. Pinson | Justice | - | https://www.gasupreme.us/court-information/biographies/justice-andrew-a-pinson/ |
| Benjamin A. Land | Justice | - | https://www.gasupreme.us/court-information/biographies/justice-benjamin-a-land/ |

---

## Current Judges - Court of Appeals of Georgia

| Name | Bio URL |
|------|---------|
| E. Trenton Brown, III (Chief Judge) | https://www.gaappeals.gov/e-trenton-brown-iii/ |
| Elizabeth Gobeil | https://www.gaappeals.gov/elizabeth-gobeil/ |
| Anne Elizabeth Barnes | https://www.gaappeals.gov/anne-elizabeth-barnes/ |
| Sara L. Doyle | https://www.gaappeals.gov/sara-l-doyle/ |
| Stephen Dillard | https://www.gaappeals.gov/stephen-dillard/ |
| Christopher McFadden | https://www.gaappeals.gov/christopher-mcfadden/ |
| Brian M. Rickman | https://www.gaappeals.gov/brian-m-rickman/ |
| Amanda H. Mercier | https://www.gaappeals.gov/amanda-h-mercier/ |
| Todd Markle | https://www.gaappeals.gov/todd-markle/ |
| Kenneth B. Hodges, III | https://www.gaappeals.gov/kennneth-hodges/ |
| John A. Pipkin | https://www.gaappeals.gov/john-a-pipkin/ |
| Jeffrey A. Watkins | https://www.gaappeals.gov/jeffrey-a-watkins/ |
| J. Wade Padgett | https://www.gaappeals.gov/j-wade-padgett/ |
| Jeffrey Davis | https://www.gaappeals.gov/jeffrey-davis/ |

---

## Jurisdiction

### Supreme Court of Georgia - Exclusive Appellate Jurisdiction
- Cases involving construction of a treaty or of the Constitution of Georgia or the United States
- Constitutionality of law, ordinance, or constitutional provision challenged
- Election contests
- Cases involving title to land
- Equity cases
- Wills
- Habeas corpus
- Extraordinary remedies
- Divorce and alimony
- Murder cases
- Certified questions from Court of Appeals or federal courts

### Court of Appeals of Georgia - Statewide Appellate Jurisdiction
- All cases except those involving:
  - Constitutional questions
  - Murder
  - Habeas corpus
- May certify legal questions to the Supreme Court

---

## Opinion Types and Publication

### Supreme Court
- Opinions released and published on the website
- Subject to modification from motions for reconsideration (Rule 27)
- Final opinions published in Georgia Reports
- Summaries of Noteworthy Opinions published as separate PDFs

### Court of Appeals
- Opinion search available by date range
- Results show: Case Number, Style, Judgment Date, COA Judgment/Ruling
- Judgment types include: AFFIRMED, REVERSED, DISMISSED, VACATED & CASE REMANDED, DISCRETIONARY APPLICATION GRANTED/DENIED, INTERLOCUTORY APPLICATION GRANTED

---

## Access Restrictions

### No Login Required
- Public access to docket searches
- Opinion searches and downloads
- Case information lookups

### Data Availability
- Supreme Court: Cases docketed in the last 5 years
- Court of Appeals: Cases since January 2003

---

## Technical Implementation Notes

### Website Platform
- Both courts use WordPress-based websites
- Court of Appeals recently migrated from gaappeals.us to gaappeals.gov domain
- Static HTML pages for opinions (no complex API)

### Supreme Court Docket System
- Embedded iframe for docket search
- Simple search by case number
- Returns case information including:
  - Case Style
  - Case Number
  - Case Status (e.g., Judgment)
  - Docket Date
  - Description
  - Argument Date/Calendar
  - County
  - Lower Court Case Numbers
  - Filings and Orders (with dates)
  - Judgments tab
  - Attorney Information tab

### Court of Appeals Docket System
- PHP-based search system
- Search by: case number, trial court case number, or case style/name
- Case detail pages include:
  - Court of Appeals Information (case number, style, status, dates, judgment)
  - Trial Court Information (case number, clerk, judge, county, court)
  - Filings, Motions, and Court Actions (chronological list)
  - Court Initiated Actions
  - Attorney Information
  - Supreme Court Information (if applicable)

### Opinion Downloads
- Supreme Court: Direct PDF links from WordPress uploads
- Court of Appeals: UUID-based downloads from efast.gaappeals.us

---

## Example Cases

### Supreme Court
- **S25A0994 - FRANKLIN v. THE STATE** (January 21, 2026)
  - Criminal - Murder Life
  - County: DeKalb
  - Status: Judgment
  - Opinion: https://www.gasupreme.us/wp-content/uploads/2026/01/s25a0994.pdf

- **S25Y0888 - IN THE MATTER OF MYLEE MCKINNEY** (January 21, 2026)
  - Attorney discipline case
  - Opinion: https://www.gasupreme.us/wp-content/uploads/2026/01/s25y0888.pdf

### Court of Appeals
- **A25A1439 - TERRELL T. TOLBERT v. THE STATE** (January 22, 2026)
  - Docketed: March 21, 2025
  - Status: Disposition Made
  - Judgment: AFFIRMED
  - Trial Court: Superior Court, Muscogee County (Case 2012CR000399)
  - Docket: https://www.gaappeals.gov/wp-content/themes/benjamin/docket/results_one_record.php?docr_case_num=A25A1439
  - Opinion: https://efast.gaappeals.us/download?filingId=387bb277-f17a-4c14-b014-8a8149b7e6f8

---

## Recommended Scraper Architecture

### 1. Supreme Court Opinion Scraper
**Source**: https://www.gasupreme.us/{YYYY}-opinions/

**Approach**:
1. Parse HTML for opinion links organized by release date
2. Extract case numbers and PDF URLs from WordPress content
3. Parse case number to determine case type
4. Download PDFs directly

**Data Available**:
- Case number
- Case style (from PDF link text)
- Opinion date
- Summary PDF URL (when available)
- Opinion PDF URL

### 2. Supreme Court Docket Scraper
**Source**: https://www.gasupreme.us/docket-search/ (iframe)

**Approach**:
1. Query docket system by case number
2. Parse case detail response for metadata
3. Extract filing history and judgment information

**Data Available**:
- Case number, style, status
- Docket date, argument date
- Description, county
- Lower court case numbers
- Filings and orders with dates
- Attorney information

### 3. Court of Appeals Opinion Scraper
**Source**: https://www.gaappeals.gov/opinion-search/

**Approach**:
1. Query by date range to get opinion list
2. Parse HTML table for case metadata
3. Extract opinion PDF links (efast.gaappeals.us UUIDs)
4. Download opinions

**Data Available**:
- Case number
- Style
- Judgment date
- COA Judgment/Ruling
- Opinion/Order PDF link

### 4. Court of Appeals Docket Scraper
**Source**: https://www.gaappeals.gov/docket-search/

**Approach**:
1. Query by case number, trial court number, or style
2. Parse case detail page for full docket information
3. Extract all metadata sections

**Data Available**:
- Full case information
- Trial court details
- Complete filing history
- Attorney information
- Related Supreme Court information

### Scraping Considerations
- Both courts use straightforward HTML/PHP pages
- No complex JavaScript rendering required for core data
- Court of Appeals uses UUID-based PDF links (efast.gaappeals.us)
- Supreme Court uses WordPress media upload URLs
- No apparent rate limiting, but respectful scraping recommended
- Court of Appeals recently migrated domains - use gaappeals.gov

---

## Additional Resources

- **Supreme Court Rules**: https://www.gasupreme.us/rules/
- **Court of Appeals Citizen's Guide**: https://www.gaappeals.gov/citizens-guide/
- **Court of Appeals FAQ**: https://www.gaappeals.gov/citizens-guide-faq/
- **Georgia Constitution**: https://www.senate.ga.gov/en-US/GeorgiaConstitution.aspx
- **Rule 3.15 Search**: http://rule315.gasupreme.us/#/search
