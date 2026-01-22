# Louisiana Courts Research

## Court Structure

Louisiana has a three-tier court system: the Louisiana Supreme Court at the apex, five Courts of Appeal as intermediate appellate courts, and district courts at the trial level.

### 1. Louisiana Supreme Court
- **Website**: https://www.lasc.org/
- Highest court in Louisiana
- 7 Justices (1 Chief Justice + 6 Associate Justices)
- Justices elected from 7 judicial districts for 10-year terms
- Chief Justice: Hon. John L. Weimer (became Chief Justice January 1, 2021)
- Location: 400 Royal Street, New Orleans, LA 70130

### 2. Courts of Appeal (Five Circuits)

Louisiana has five intermediate appellate courts, each serving a defined geographic region:

#### First Circuit Court of Appeal
- **Website**: https://www.la-fcca.org/
- **Location**: 1600 North Third Street, Baton Rouge, LA 70802
- **Phone**: 225-382-3000
- Covers parishes in southeastern Louisiana

#### Second Circuit Court of Appeal
- **Website**: https://www.la2nd.org/
- **Location**: 430 Fannin Street, Shreveport, LA 71101
- **Phone**: (318) 227-3700
- 9 judges from 3 election districts
- Covers 20 northernmost parishes

#### Third Circuit Court of Appeal
- **Website**: https://www.la3circuit.org/
- **Location**: 1000 Main Street, Lake Charles, LA 70615
- **Phone**: (337) 433-9403
- 12 judges
- Largest circuit, covers 21 parishes in southwest and central Louisiana
- Chief Judge: Elizabeth A. Pickett
- Building dedicated to Judge Albert Tate (first Chief Judge)

#### Fourth Circuit Court of Appeal
- **Website**: https://www.la4th.org/
- **Location**: 410 Royal Street, New Orleans, LA 70130
- Chief Judge: Roland L. Belsome
- Clerk of Court: Justin I. Woods

#### Fifth Circuit Court of Appeal
- **Website**: https://www.fifthcircuit.org/
- **Location**: 101 Derbigny Street, Gretna, LA 70053
- **Phone**: (504) 376-1400
- Covers Jefferson, St. Charles, St. James, and St. John the Baptist parishes
- Clerk of Court: Curtis B. Pursell

---

## Key URLs and URL Patterns

### Louisiana Supreme Court

#### Main Portal
- **Home**: https://www.lasc.org/
- **Court Actions (Opinions)**: https://www.lasc.org/CourtActions/2026
- **Docket**: https://www.lasc.org/Docket
- **Court Rules**: https://www.lasc.org/CourtRules
- **Press Room**: https://www.lasc.org/PressRoom/2026

#### Court Actions (Opinions) URLs
- **Court Actions by Year**: `https://www.lasc.org/CourtActions/{year}`
- **Individual Action Release**: `https://www.lasc.org/Actions?p={year}-{release-number}` (e.g., `?p=2026-001`)
- **Opinion PDF Pattern**: `https://www.lasc.org/opinions/{year}/{case-number}.{suffix}.pdf`
  - Example: `https://www.lasc.org/opinions/2026/25-1635.C.PC.pdf`
  - Suffix types include: `.PC.pdf` (per curiam), `.action.pdf` (action), `.action.re.pdf` (rehearing action)
  - Concurrence/dissent: `{case-number}.{justice-initials}.{type}.pdf` (e.g., `25-1635.C.ahp.dip.pdf`)

#### Docket PDFs
- **Pattern**: `https://www.lasc.org/dockets/{month}{year}.pdf`
- **Example**: `https://www.lasc.org/dockets/Jan2026.pdf`

#### Oral Arguments
- **Live Stream**: https://livestream.lasc.org/
- **Note**: Only available when court is in session

#### Justice Biographies
- **Pattern**: `https://www.lasc.org/About/Biography?p={Justice_Name}`
- **Example**: `https://www.lasc.org/About/Biography?p=John_L._Weimer`

### First Circuit Court of Appeal

#### Main Portal
- **Home**: https://www.la-fcca.org/
- **Decisions**: https://www.la-fcca.org/decisions
- **Docket**: https://www.la-fcca.org/docket
- **Judges**: https://lafcca.hosted2.civiclive.com/the_court/decision_days

#### Decisions Search
- **Recent Decisions**: https://lafcca.hosted2.civiclive.com/cms/One.aspx?portalId=161585&pageId=179687
- **By Year**: `https://lafcca.hosted2.civiclive.com/decisions/o_p_i_n_i_o_n_s_{year}`
- **Search All**: https://www.la-fcca.org/search
- **eFiling**: https://eclerk2.la-fcca.org/
- **Records**: https://ecaseaccess.la-fcca.org/weblink/Browse.aspx?cr=1

#### Opinion PDF Pattern
- **Pattern**: `https://lafcca.hosted2.civiclive.com/common/pages/GetFile.ashx?key={encoded-key}`
- Each opinion has a unique encoded key

### Second Circuit Court of Appeal

#### Main Portal
- **Home**: https://www.la2nd.org/
- **Opinions**: https://www.la2nd.org/opinions/
- **Orders**: https://www.la2nd.org/orders/
- **Resources**: https://www.la2nd.org/resources/
- **Local Rules**: https://www.la2nd.org/local-rules-of-court/
- **Personnel**: https://www.la2nd.org/court-personnel-overview/
- **Calendar**: https://www.la2nd.org/calendar/

#### Docket PDFs
- **Pattern**: `https://www.la2nd.org/wp-content/uploads/{year}/{month}/{month-name}-{year}-mailout-docket.pdf`
- **Example**: `https://www.la2nd.org/wp-content/uploads/2025/12/January-2026-mailout-docket.pdf`

### Third Circuit Court of Appeal

#### Main Portal
- **Home**: https://www.la3circuit.org/
- **eCourt System**: https://ecourt.la3circuit.org/
- **Calendar**: https://www.la3circuit.org/calendar.aspx

#### Opinion Search
- **By Case Number**: Search form on homepage with year dropdown and case number input
- **By Month/Year**: Search form with year and month dropdowns
- **By Opinion Date**: Date picker search
- **By Title/Party**: Text search for litigant name
- Opinion data available from 1992 to present

#### Document Downloads
- **Pattern**: `https://www.la3circuit.org/transmit.aspx?id={base64-encoded-path}`
- Resources like Citation Manual, Court Rules, Pro Se Manual available via transmit.aspx

### Fourth Circuit Court of Appeal

#### Main Portal
- **Home**: https://www.la4th.org/
- **Docket Schedule**: https://www.la4th.org/Schedule.aspx
- **eFiling**: https://ecourt.la4th.org/

#### Search Options
Available searches for:
- Lodged Appeals (by court case number, district court number, case year & bar roll, litigant name)
- Dockets (by court case number, docket month/year, district court number, litigant name)
- Opinions (by court case number, opinion month/year, opinion date, litigant name)

#### Opinion PDF Pattern
- **Pattern**: `https://www.la4th.org/opinion/News/{number}.pdf`
- News items and announcements follow this pattern

### Fifth Circuit Court of Appeal

#### Main Portal
- **Home**: https://www.fifthcircuit.org/
- **Announcements**: https://www.fifthcircuit.org/announcements.aspx
- **eCourt**: https://ecourt.fifthcircuit.org/
- **Case Search**: https://www.fifthcircuit.org/searchcases.aspx
- **Docket Search**: https://www.fifthcircuit.org/searchdocket.aspx
- **Decision Search**: https://www.fifthcircuit.org/searchopinions.aspx
- **Local Rules**: https://www.fifthcircuit.org/localrules.aspx
- **Uniform Rules**: https://www.fifthcircuit.org/uniform.aspx
- **Filing Fees**: https://www.fifthcircuit.org/filingfees.aspx

#### Decision Search
- Search by case number, litigant name, decision month/year, or decision date
- Opinions available from 1992 to present
- Cases with opinion dispositions can be viewed by clicking PDF icon

#### Docket Reports
- **Pattern**: `https://www.fifthcircuit.org/reportviewer.aspx?r=docket&m={month}&y={year}`
- **Example**: `https://www.fifthcircuit.org/reportviewer.aspx?r=docket&m=January&y=2026`

---

## Current Justices - Louisiana Supreme Court

| Name | Position | District | Elected/Appointed | Bio URL |
|------|----------|----------|-------------------|---------|
| John L. Weimer | Chief Justice | 6th District | 2001 (Chief: 2021) | https://www.lasc.org/About/Biography?p=John_L._Weimer |
| Allison H. Penzato | Justice Pro Tempore | 1st District | - | https://www.lasc.org/About/Biography?p=Allison_H._Penzato |
| John Michael Guidry | Associate Justice | 2nd District | - | https://www.lasc.org/About/Biography?p=John_Michael_Guidry |
| Cade R. Cole | Associate Justice | 3rd District | - | https://www.lasc.org/About/Biography?p=Cade_R_Cole |
| Jay B. McCallum | Associate Justice | 4th District | - | https://www.lasc.org/About/Biography?p=Jay_B._McCallum |
| Jefferson Hughes | Associate Justice | 5th District | - | https://www.lasc.org/About/Biography?p=Jefferson_Hughes |
| Piper D. Griffin | Associate Justice | 7th District | 2020 | https://www.lasc.org/About/Biography?p=Piper_D._Griffin |

**Note**: Louisiana Supreme Court has 7 judicial districts. Each justice is elected from their respective district.

---

## Jurisdiction

### Louisiana Supreme Court
- Court of last resort in Louisiana
- Exclusive original jurisdiction over disciplinary proceedings against attorneys
- Mandatory jurisdiction in cases involving constitutionality of a law, death penalty cases
- Discretionary review of Court of Appeal decisions via writ applications
- General supervisory jurisdiction over all lower courts
- Administers Louisiana Judiciary

### Courts of Appeal
- Intermediate appellate courts
- Appellate jurisdiction over civil and criminal matters from district courts
- Original jurisdiction in certain matters
- Judges sit in panels of at least three

---

## Opinion Types and Publication

### Louisiana Supreme Court
- **Per Curiam**: Opinion by the whole court
- **Actions**: Brief dispositions of writ applications
- **Rehearing Actions**: Dispositions of rehearing applications
- Concurrences and dissents published separately with justice initials

### Publication Schedule
- **Supreme Court**: Opinions scheduled for release on Fridays of each sitting
- **Tentative dates for 2025-2026 session**:
  - September 5, 2025
  - October 24, 2025
  - January 9, 2026
  - March 6, 2026
  - May 1, 2026
  - June 26, 2026
- **First Circuit**: Public Decision Days (2026): February 27, April 17, June 5

### Case Number Format
- **Supreme Court**: `{year}-{type}-{number}` (e.g., 2025-C-01635, 2026-KK-00009)
- Type codes include: C (civil), K (criminal), KK (criminal writ), CC (civil certified), etc.
- **Courts of Appeal**: Similar format, varies by circuit (e.g., 2025 CW 0426)

---

## Access Restrictions

### No Login Required
- All court websites are publicly accessible
- Opinion searches and downloads
- Docket information
- Justice/Judge biographies
- Court rules and forms

### eFiling Systems
- Each circuit has its own eFiling portal
- Registration required for filing
- **Important (Effective January 1, 2026)**: All Louisiana appellate courts will no longer accept filings by attorneys via U.S. mail or commercial courier. Attorneys must file electronically or in person.

### Filing Fees (Effective January 1, 2026)
- **First Circuit**:
  - Civil Record of Appeal: $334.00
  - Civil Writ Application: $184.00
  - Rehearing Application: $109.50
- **Fifth Circuit**:
  - Civil Appeals and Civil Writs increased by $2.00 each

### reCAPTCHA
- Some search forms (e.g., Fifth Circuit opinion search) require reCAPTCHA verification

---

## Technical Implementation Notes

### Louisiana Supreme Court Website
- **Domain**: lasc.org
- Clean URL structure with query parameters
- PDF opinions organized by year and case number
- RSS feed available for Court Actions alerts
- Constant Contact subscription for email alerts

### First Circuit
- **Domain**: la-fcca.org and lafcca.hosted2.civiclive.com
- CivicLive CMS platform
- Document management via GetFile.ashx with encoded keys
- DataTables-style file listings with sorting and pagination

### Second Circuit
- **Domain**: la2nd.org
- WordPress-based site
- PDFs stored in wp-content/uploads directory structure
- Bandwise, LLC developed site

### Third Circuit
- **Domain**: la3circuit.org
- Custom ASP.NET application
- Opinion search with multiple search options
- Base64-encoded document paths for downloads
- Opinion data from 1992 to present

### Fourth Circuit
- **Domain**: la4th.org
- Custom ASP.NET application
- Bootstrap-based responsive design
- Accordion-style search panels
- Modal dialogs for expanded content

### Fifth Circuit
- **Domain**: fifthcircuit.org
- Custom ASP.NET application
- Responsive design (tablet/mobile friendly)
- Report viewer for dockets and decisions
- Decision data from 1992 to present

---

## Oral Arguments

### Louisiana Supreme Court
- Live streaming available at https://livestream.lasc.org/
- Only during court sessions
- Uses Swagit media service for streaming
- Court docket shows upcoming argument schedule

### Courts of Appeal
- Most circuits offer Zoom oral arguments
- Fourth Circuit: Zoom oral argument information at https://www.la4th.org/downloads/zoom.pdf
- Third Circuit: Zoom Attorney Guide available for virtual proceedings

---

## Example Cases

### Louisiana Supreme Court (from Court Actions 2026-001)
- **2025-C-01635**: James Carnez Burns vs. Loomis Armored US, LLC - Writ application granted, per curiam
- **2026-OK-00030**: State of Louisiana vs. Damon Bryant - Writ application denied
- **2025-B-01471**: In Re: Ginger Vidrine - Reciprocal discipline imposed

### First Circuit (2026)
- **2025 CW 0426 R**: State Of Louisiana In The Matter of The Succession of Garrett J. Claybourn
- **2025 CW 0919**: Yolanda Chappell Norman, et al vs. Holly Court Assisted Living and Memory Care
- **2025 CW 0939**: E L & F Properties, L.L.C., et al vs. Santec Consulting Services Inc, et al

### Fifth Circuit (2026)
- **25-C-590**: Shannon Couch versus Loya Insurance Company and John Doe

---

## Recommended Scraper Architecture

### 1. Louisiana Supreme Court Opinion Scraper
**Source**: https://www.lasc.org/CourtActions/{year}

**Approach**:
1. Navigate to Court Actions page for target year
2. Parse list of release dates
3. For each release, navigate to action page
4. Extract case numbers, titles, disposition types
5. Parse PDF links for opinions, concurrences, dissents
6. Download PDFs directly

**Data Available**:
- Release date
- Case number with type code
- Case title/parties
- Parish of origin
- Disposition type (granted, denied, etc.)
- Justice votes and dissents
- Direct PDF URLs

### 2. First Circuit Opinion Scraper
**Source**: https://lafcca.hosted2.civiclive.com/decisions/o_p_i_n_i_o_n_s_{year}

**Approach**:
1. Navigate to opinions page for target year
2. Parse paginated file listing
3. Extract case numbers and titles from filenames
4. Follow GetFile.ashx links for PDFs
5. Handle pagination (10+ entries per page)

**Data Available**:
- Case number (with type code)
- Case title
- File size
- Modified date
- PDF download link

### 3. Multi-Circuit Scraper
**Approach**:
- Create separate scrapers for each circuit due to different platforms
- Third, Fourth, and Fifth circuits use similar ASP.NET architecture
- Second circuit uses WordPress with different URL structure
- First circuit uses CivicLive CMS

### 4. Docket Scraper
**Source**: Various docket pages per circuit

**Approach**:
- Supreme Court: Parse docket PDFs
- Fifth Circuit: Use report viewer with month/year parameters
- Other circuits: Parse HTML docket listings or PDFs

---

## Additional Resources

### Court Rules
- **Supreme Court Rules**: https://www.lasc.org/CourtRules
- **Uniform Rules of Courts of Appeal**: Available on each circuit's website
- Each circuit has local rules in addition to uniform rules

### Language Access
- Louisiana courts are committed to providing access for Limited English Proficiency (LEP) individuals
- Language coordinators designated at each court
- Interpreter services available
- Multi-language support on websites (Spanish, Vietnamese, Chinese, Arabic)
- Supreme Court Language Access: https://www.lasc.org/Language_Access

### E-Filing Portals
- **Supreme Court**: https://cdx.lasc.org/
- **First Circuit**: https://eclerk2.la-fcca.org/
- **Third Circuit**: https://ecourt.la3circuit.org/
- **Fourth Circuit**: https://ecourt.la4th.org/
- **Fifth Circuit**: https://ecourt.fifthcircuit.org/

---

## Contact Information

### Louisiana Supreme Court
- Address: 400 Royal Street, New Orleans, LA 70130
- Clerk of Court: Veronica O. Koclanes
- Judicial Administrator: Sandra A. Vujnovich
- Website: https://www.lasc.org/Contact

### Circuit Courts of Appeal
| Circuit | Phone | Address |
|---------|-------|---------|
| First | (225) 382-3000 | 1600 North Third Street, Baton Rouge, LA 70802 |
| Second | (318) 227-3700 | 430 Fannin Street, Shreveport, LA 71101 |
| Third | (337) 433-9403 | 1000 Main Street, Lake Charles, LA 70615 |
| Fourth | - | 410 Royal Street, New Orleans, LA 70130 |
| Fifth | (504) 376-1400 | 101 Derbigny Street, Gretna, LA 70053 |

---

## Notes

1. **Civil Law Jurisdiction**: Louisiana is unique among U.S. states in having a civil law legal system (based on French and Spanish law) rather than common law, though criminal law follows common law traditions.

2. **2026 Filing Changes**: Effective January 1, 2026, all Louisiana appellate courts no longer accept attorney filings via U.S. mail or commercial courier. Electronic filing or in-person filing required.

3. **Fee Increases (2026)**: Filing fees increased at all circuits effective January 1, 2026.

4. **Data Coverage**: Most circuits have online opinions from 1992 or later.

5. **Pinpoint Citation Notice**: For purposes of pinpoint citation, the pagination of opinions on the Supreme Court website may not conform with the official opinion of the court.
